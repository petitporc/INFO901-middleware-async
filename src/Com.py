from threading import Lock, Event, Thread
from queue import Queue, Empty
import time

from pyeventbus3.pyeventbus3 import PyBus, Mode, subscribe

from Message import Message
from MessageTo import MessageTo
from TokenMessage import TokenMessage
from BroadcastMessage import BroadcastMessage


class Com:
  """
  Communicateur (middleware) responsable des services de communication inter-processus.

  Rôles pris en charge :
  - Horloge de Lamport (protégée par un verrou) et mise à jour automatique à l’envoi/réception
    des messages *utilisateurs* (les messages système — ex. jeton — n’affectent PAS l’horloge).
  - Envois asynchrones : publish, broadcast, sendTo.
  - Boîte aux lettres (queue) pour la réception asynchrone côté processus.
  - Communications synchrones : barrière (synchronize), broadcastSync/ACK, sendToSync/receiveFromSync.
  - Section critique distribuée (anneau à jeton) gérée par un **thread dédié** (token manager).
  - Numérotation automatique (REGISTER) à l’initialisation : attribution d’un ID unique par ordre d’arrivée.

  Remarques de conception :
  - Toutes les méthodes qui manipulent l’horloge utilisent un Lock pour garantir l’exclusion mutuelle
    entre le processus et le communicateur.
  - Les attentes bloquantes (barrière, synchro, jeton) sont implémentées avec des Event(s) pour éviter
    les attentes actives.
  """

  # ---------------------------------------------------------------------------
  # Construction / initialisation
  # ---------------------------------------------------------------------------
  def __init__(self, owner_name: str, npProcess: int):
    """
    Initialise le communicateur d’un processus.

    :param owner_name: nom logique du propriétaire (ex. "P0", "P1", …)
    :param npProcess:  nombre total de processus attendus dans le système
    """
    self.owner_name = owner_name
    self.npProcess = npProcess

    # Horloge logique (Lamport)
    self._clock = 0
    self._clock_lock = Lock()

    # Boîte aux lettres des messages reçus par ce processus (flux asynchrone)
    self._mailbox = Queue()

    # État lié à la section critique distribuée (anneau à jeton)
    self.waiting = False           # ce processus souhaite-t-il entrer en SC ?
    self.holding_token = False     # ce processus détient-il actuellement le jeton ?
    self.token_event = Event()     # réveille requestSC() lorsqu’on obtient le jeton

    # Infos locales
    self.myId = None               # fixé après REGISTER
    self.alive = True              # drapeau d’activité (arrêt propre)

    # Synchronisation (barrière)
    self._sync_received = set()
    self._sync_event = None

    # REGISTER (numérotation par ordre d’arrivée)
    self.participants = set()        # noms vus
    self._register_records = []      # [(horloge_de_register, nom)]
    self._register_seen = set()      # évite doublons
    self.register_event = Event()    # pour réveiller register() quand tous sont reçus

    # Inscription sur le bus d’événements
    PyBus.Instance().register(self, self)

    # Thread de gestion du jeton (imposé par l’énoncé)
    self._token_q = Queue()          # file interne de jetons reçus
    self._token_thread_alive = True
    self._token_thread = Thread(target=self._token_loop, daemon=True)
    self._token_thread.start()

  # ---------------------------------------------------------------------------
  # Logger uniforme (FR)
  # ---------------------------------------------------------------------------
  def _log(self, category: str, msg: str):
    """
    Affiche un log homogène côté communicateur.

    :param category: courte catégorie en MAJ (ex. "SEND", "REGISTER", "SYNC", "TOKEN", …)
    :param msg:      message libre
    """
    print(f"[COM {self.owner_name}][{category}] {msg}")

  # ---------------------------------------------------------------------------
  # Horloge de Lamport (APIs)
  # Règle : clock = max(clock_local, clock_reçu) + 1
  # ---------------------------------------------------------------------------
  def incrementClock(self) -> int:
    """
    Incrémente l’horloge locale de Lamport (opération atomique).

    À utiliser pour *tout envoi utilisateur*. Les méthodes d’envoi (publish/broadcast/sendTo)
    l’appellent déjà — un processus n’a donc *pas* à le faire manuellement avant d’émettre.

    :return: nouvelle valeur de l’horloge
    """
    with self._clock_lock:
      self._clock += 1
      return self._clock

  def getClock(self) -> int:
    """
    Retourne la valeur courante de l’horloge de Lamport.

    :return: valeur entière de l’horloge
    """
    with self._clock_lock:
      return self._clock

  def update_on_receive(self, received_clock: int) -> int:
    """
    Met à jour l’horloge locale à la réception d’un message *utilisateur*.

    :param received_clock: horloge contenue dans le message reçu
    :return: nouvelle valeur de l’horloge locale
    """
    with self._clock_lock:
      self._clock = max(self._clock, received_clock) + 1
      return self._clock

  # ---------------------------------------------------------------------------
  # Envois asynchrones (messages utilisateurs)
  # ---------------------------------------------------------------------------
  def publish(self, payload):
    """
    Envoi de type *publish* : tout le monde reçoit, y compris l’émetteur.

    Impacte l’horloge locale (incrément) car c’est un message utilisateur.
    """
    send_clock = self.incrementClock()
    m = Message(payload, send_clock, self.owner_name)
    self._log("SEND", f"publish payload={m.getPayload()} clock={m.getClock()}")
    PyBus.Instance().post(m)

  def broadcast(self, payload):
    """
    Envoi de type *broadcast* : tous les autres reçoivent (l’émetteur s’ignore).

    Impacte l’horloge locale (incrément) car c’est un message utilisateur.
    """
    send_clock = self.incrementClock()
    bm = BroadcastMessage(payload, send_clock, self.owner_name)
    self._log("SEND", f"broadcast payload={bm.getPayload()} clock={bm.getClock()}")
    PyBus.Instance().post(bm)

  def sendTo(self, payload, to):
    """
    Envoi *ciblé* vers un destinataire unique (identifié par son ID).

    Impacte l’horloge locale (incrément) car c’est un message utilisateur.
    """
    send_clock = self.incrementClock()
    mt = MessageTo(payload, send_clock, self.owner_name, to)
    self._log("SEND", f"sendTo -> P{to} payload={mt.getPayload()} clock={mt.getClock()}")
    PyBus.Instance().post(mt)

  # ---------------------------------------------------------------------------
  # Réception / Boîte aux lettres (BAL)
  # ---------------------------------------------------------------------------
  def enqueue_incoming(self, msg_obj):
    """
    Dépose un message reçu dans la BAL du processus. Appelé par les handlers de réception.
    """
    self._mailbox.put(msg_obj)

  def try_get(self, timeout=None):
    """
    Récupère un message de la BAL éventuellement en *bloquant*.

    :param timeout: None -> blocage illimité ; float -> délai max en secondes (Empty si dépassement)
    :return:        l’objet message ou lève `queue.Empty` si timeout
    """
    return self._mailbox.get(timeout=timeout)

  def poll_no_wait(self):
    """
    Récupère un message de la BAL *sans attendre*.

    :return: message si disponible, sinon None
    """
    try:
      return self._mailbox.get_nowait()
    except Empty:
      return None

  # ---------------------------------------------------------------------------
  # REGISTER (numérotation automatique par ordre d’arrivée)
  # ---------------------------------------------------------------------------
  def register(self):
    """
    Diffuse un message REGISTER et attend d’avoir reçu ceux de tous les participants.
    L’ID est attribué par ordre d’arrivée (clé primaire : horloge d’envoi, puis nom pour
    départager à horloge égale).

    :return: l’ID attribué à ce processus
    """
    # Réinitialise le suivi
    self.participants = {self.owner_name}
    self._register_records = []
    self._register_seen = {self.owner_name}

    # Diffuse mon REGISTER + mémorise l’horloge d’envoi
    my_reg_clock = self.incrementClock()
    self.broadcast({"type": "REGISTER", "name": self.owner_name, "clock": my_reg_clock})
    self._register_records.append((my_reg_clock, self.owner_name))

    self._log("REGISTER", f"j'annonce {self.owner_name}, attente de {self.npProcess} processus...")

    # Attente des autres REGISTER
    while len(self.participants) < self.npProcess:
      self.register_event.wait(timeout=0.2)

    # Calcul des IDs par ordre d’arrivée
    ordered = sorted(self._register_records, key=lambda t: (t[0], t[1]))
    sorted_names = [name for _, name in ordered]
    self.name_to_id = {name: idx for idx, name in enumerate(sorted_names)}
    self.myId = sorted_names.index(self.owner_name)

    self._log("REGISTER", f"ordre d'arrivée={sorted_names} -> mon ID={self.myId}")
    return self.myId

  # ---------------------------------------------------------------------------
  # Handlers bus — réceptions asynchrones (Broadcast/Direct) + système
  # ---------------------------------------------------------------------------
  @subscribe(threadMode=Mode.PARALLEL, onEvent=BroadcastMessage)
  def onBroadcast(self, event):
    """
    Handler d’événements *broadcast* (tous sauf l’émetteur).
    Gère REGISTER, REQUEST (SC), SYNC (barrière), SYNC-BROADCAST (synchro avec ACK),
    sinon réexpédie dans la BAL comme message utilisateur.
    """
    if event.getSender() == self.owner_name:
      return  # j'ignore mes propres broadcasts

    updated = self.update_on_receive(event.getClock())
    payload = event.getPayload()

    # REGISTER
    if isinstance(payload, dict) and payload.get("type") == "REGISTER":
      name = payload["name"]
      if name not in self._register_seen:
        self._register_seen.add(name)
        self.participants.add(name)
        msg_clock = payload.get("clock", event.getClock())
        self._register_records.append((msg_clock, name))
      self._log("REGISTER", f"REGISTER reçu de {name} ({len(self.participants)}/{self.npProcess})")
      if self.npProcess is not None and len(self.participants) >= self.npProcess:
        self.register_event.set()
      return

    # REQUEST (section critique)
    if isinstance(payload, dict) and payload.get("type") == "REQUEST":
      requester = payload["from"]
      self._log("SC", f"REQUEST reçu de P{requester}")
      if self.holding_token and not self.waiting:
        # Je n'attends pas -> je passe le jeton au demandeur
        self._log("TOKEN", f"je passe le token à P{requester}")
        self.holding_token = False
        self.sendToken(requester)
      return

    # SYNC (barrière)
    if isinstance(payload, dict) and payload.get("type") == "SYNC":
      self._sync_received.add(event.getSender())
      self._log("SYNC", f"reçu SYNC de {event.getSender()} ({len(self._sync_received)}/{self.npProcess})")
      if len(self._sync_received) >= self.npProcess:
        self._sync_event.set()
      return

    # SYNC-BROADCAST (synchro avec ACK)
    if isinstance(payload, dict) and payload.get("type") == "SYNC-BROADCAST":
      self._log("SYNC-BROADCAST", f"réception de {event.getSender()} -> {payload['data']}")
      # Répond par un ACK (destinataire = ID du sender)
      to_id = self.name_to_id.get(event.getSender(), event.getSender())
      ack = MessageTo({"type": "ACK-SYNC-BROADCAST"}, self.incrementClock(), self.owner_name, to_id)
      PyBus.Instance().post(ack)
      self._log("SYNC-BROADCAST", f"ACK envoyé à {event.getSender()}")
      return

    # Par défaut : message utilisateur broadcast -> BAL
    self._log("RECEIVE", f"broadcast reçu de {event.getSender()} payload={payload} clock={event.getClock()}")
    self.enqueue_incoming(event)

  @subscribe(threadMode=Mode.PARALLEL, onEvent=MessageTo)
  def onReceive(self, event):
    """
    Handler d’événements *directs* (MessageTo) destinés à CE processus.
    Gère les ACK des synchros ; sinon relaye vers la BAL.
    """
    if self.myId is None or event.getTo() != self.myId:
      return

    payload = event.getPayload()

    # ACK de synchro broadcast
    if isinstance(payload, dict) and payload.get("type") == "ACK-SYNC-BROADCAST":
      if event.getSender() != self.owner_name:  # ignore un éventuel auto-ACK
        self._log("SYNC-BROADCAST", f"ACK reçu de {event.getSender()}")
        self.handle_ack()
        return

    # ACK de synchro point-à-point
    if isinstance(payload, dict) and payload.get("type") == "ACK-SYNC-TO":
      if event.getSender() != self.owner_name:
        self._log("SYNC-BROADCAST", f"ACK reçu de {event.getSender()}")
        self.handle_ack()
        return

    # Message utilisateur direct -> BAL
    updated = self.update_on_receive(event.getClock())
    self._log(
      "RECEIVE",
      f"réception directe de {event.getSender()} -> P{event.getTo()} "
      f"payload={payload} clock={event.getClock()} -> local={updated}"
    )
    self.enqueue_incoming(event)

  # ---------------------------------------------------------------------------
  # Barrière de synchronisation
  # ---------------------------------------------------------------------------
  def synchronize(self, npProcess: int):
    """
    Barrière globale : tous les processus doivent appeler synchronize() pour passer.

    Implémentation : envoie un SYNC (broadcast), attend d’en recevoir un de chaque participant,
    puis débloque l’attente locale.
    """
    # Envoi de mon SYNC
    send_clock = self.incrementClock()
    bm = BroadcastMessage({"type": "SYNC"}, send_clock, self.owner_name)
    self._log("SYNC", f"j'envoi SYNC clock={send_clock}")
    PyBus.Instance().post(bm)

    # Prépare la barrière
    self._sync_received = {self.owner_name}
    self._sync_event = Event()

    # Bloque jusqu’à réception de tous les SYNC
    while not self._sync_event.wait(timeout=0.1):
      pass
    self._log("SYNC", "Tous les SYNC reçus, barrière franchie")

    # Nettoyage
    del self._sync_received
    del self._sync_event

  # ---------------------------------------------------------------------------
  # Communications synchrones
  # ---------------------------------------------------------------------------
  def broadcastSync(self, payload, from_id: int, my_id: int):
    """
    Diffusion synchrone :
      - Si *from_id == my_id* : diffuse le message à tous et attend les ACK de tous les autres.
      - Sinon : réceptionne le message et renvoie un ACK (géré dans onBroadcast()).
    """
    if from_id == my_id:
      send_clock = self.incrementClock()
      bm = BroadcastMessage({"type": "SYNC-BROADCAST", "data": payload}, send_clock, self.owner_name)
      self._log("SYNC-BROADCAST", f"diffusion synchrone payload={payload} clock={send_clock}")
      PyBus.Instance().post(bm)

      # Attente des ACK de tous les autres
      self._acks_received = 0
      self._acks_target = self.npProcess - 1
      self._acks_event = Event()

      while not self._acks_event.wait(timeout=0.1):
        pass
      self._log("SYNC-BROADCAST", "Tous les ACK reçus, barrière franchie")

      # Nettoyage
      del self._acks_received
      del self._acks_target
      del self._acks_event

  def sendToSync(self, payload, to, my_id: int):
    """
    Envoi synchrone point-à-point.
    Bloque jusqu’à réception de l’ACK par le destinataire `to`.
    """
    send_clock = self.incrementClock()
    mt = MessageTo(payload, send_clock, self.owner_name, to)
    self._log("SYNC-TO", f"envoi synchrone à P{to} payload={mt.getPayload()} clock={mt.getClock()}")

    # Prépare l’attente d’un seul ACK
    self._acks_received = 0
    self._acks_target = 1
    self._acks_event = Event()
    self._acks_from = to

    PyBus.Instance().post(mt)

    while not self._acks_event.wait(timeout=0.1):
      pass
    self._log("SYNC-TO", f"ACK reçu de P{to}, envoi synchrone terminé")

    # Nettoyage
    del self._acks_received
    del self._acks_target
    del self._acks_event
    del self._acks_from

  def receiveFromSync(self, from_id: int, timeout=None):
    """
    Réception synchrone point-à-point : bloque jusqu’à réception d’un MessageTo *venant de* `from_id`.

    :param from_id: ID attendu de l’émetteur
    :param timeout: délai max en secondes (None = illimité). En cas de dépassement : retourne None.
    :return:        le message reçu (MessageTo) ou None si timeout
    """
    try:
      while True:
        msg = self.try_get(timeout=timeout)
        if msg is None:
          continue
        if isinstance(msg, MessageTo):
          sender = msg.getSender()
          if sender == f"P{from_id}" or sender == from_id:
            self._log("SYNC-TO", f"réception de P{from_id} -> msg={msg.getPayload()}")
            # Envoi ACK retour
            ack = MessageTo({"type": "ACK-SYNC-TO"}, self.incrementClock(), self.owner_name, from_id)
            PyBus.Instance().post(ack)
            return msg
    except Empty:
      self._log("SYNC-TO", "timeout d'attente écoulé")
      return None

  def handle_ack(self):
    """
    Incrémente le compteur d’ACK et débloque l’attente si la cible est atteinte.
    (Utilisé pour `broadcastSync` et `sendToSync`)
    """
    if hasattr(self, '_acks_received'):
      self._acks_received += 1
      if self._acks_received >= self._acks_target:
        self._acks_event.set()

  # ---------------------------------------------------------------------------
  # Section Critique (anneau à jeton)
  # ---------------------------------------------------------------------------
  def requestSC(self):
    """
    Demande d’entrée en section critique : bloque jusqu’à obtention du jeton.
    """
    self.waiting = True
    self._log("SC-REQUEST", "Demande de SC, j'attends le token...")
    # Annonce (optionnelle) aux autres
    self.broadcast({"type": "REQUEST", "from": self.myId})
    # Attente du jeton (réveil par _token_loop via token_event)
    self.token_event.wait()
    self.token_event.clear()
    self._log("SC-ENTER", "J'ai le token, j'entre en SC")

  def releaseSC(self):
    """
    Sortie de section critique : passe explicitement le jeton au voisin suivant.
    """
    if not self.holding_token:
      return
    self._log("SC-EXIT", "Je quitte la SC et passe le token au suivant")
    self.waiting = False
    self.holding_token = False
    self.sendToken(self.nextId())

  def sendToken(self, to_id: int):
    """
    Envoie le jeton (message système) à `to_id`.

    IMPORTANT : n’incrémente PAS l’horloge — c’est un message système.
    """
    send_clock = self.getClock()  # pas d’incrément ici !
    tm = TokenMessage(send_clock, self.owner_name, to_id)
    print(f"[{self.owner_name}][TOKEN-SEND] to=P{to_id} clock={tm.getClock()} sender={tm.getSender()}")
    PyBus.Instance().post(tm)

  def nextId(self):
    """
    Calcule l’ID du voisin suivant dans l’anneau.
    """
    return (self.myId + 1) % self.npProcess

  @subscribe(threadMode=Mode.PARALLEL, onEvent=TokenMessage)
  def onToken(self, event):
    """
    Handler d’événements jeton (TokenMessage) — **ne prend pas de décision ici**.
    Se contente de déposer l’événement dans la file interne du *token manager*.
    """
    if not self.alive:
      return
    if event.getTo() != self.myId:
      return
    self._token_q.put(event)

  def _token_loop(self):
    """
    Thread *token manager* :
      - lit les TokenMessage destinés à ce processus,
      - réveille requestSC() si `waiting` est vrai,
      - sinon conserve le jeton (en réserve) pour un passage ultérieur.
    """
    while self._token_thread_alive:
      try:
        ev = self._token_q.get(timeout=0.2)
      except Empty:
        continue
      if not self.alive or ev is None:
        continue

      local = self.getClock()
      self._log("TOKEN", f"Token reçu de {ev.getSender()} -> waiting={self.waiting} -> localClock={local}")

      if self.waiting:
        # On réveille la demande de SC
        self.holding_token = True
        self.token_event.set()
        self._log("TOKEN", "Je garde le token pour entrer en SC")
      else:
        # Pas de demande -> on garde le token en réserve
        self.holding_token = True
        self._log("TOKEN", "Je garde le token en réserve")

  # ---------------------------------------------------------------------------
  # Arrêt propre
  # ---------------------------------------------------------------------------
  def stop(self):
    """
    Arrête proprement le communicateur :
      - déblocage des attentes (token/barrières/synchros),
      - arrêt du thread token manager,
      - désinscription du bus.
    """
    self.alive = False
    self._log("STOP", "Arrêt du communicateur...")

    # Débloque une éventuelle attente du token
    try:
      self.token_event.set()
    except Exception:
      pass

    # Arrête le thread de gestion du token
    self._token_thread_alive = False
    try:
      self._token_q.put_nowait(None)
    except Exception:
      pass
    try:
      self._token_thread.join(timeout=1.0)
    except Exception:
      pass

    # Si une barrière SYNC est en cours, la libérer
    if hasattr(self, '_sync_event') and self._sync_event is not None:
      try:
        self._sync_event.set()
      except Exception:
        pass

    # Si un broadcastSync / sendToSync est en cours, la libérer
    if hasattr(self, '_acks_event') and self._acks_event is not None:
      try:
        self._acks_event.set()
      except Exception:
        pass

    # Débloque une éventuelle get() bloquante si elle était utilisée sans timeout
    try:
      self._mailbox.put_nowait(None)
    except Exception:
      pass

    # Désinscription du bus
    try:
      PyBus.Instance().unregister(self)
    except Exception:
      pass

    self._log("STOP", "Communicateur arrêté.")
