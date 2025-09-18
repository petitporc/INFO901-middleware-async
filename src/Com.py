from threading import Lock, Event
from queue import Queue, Empty
import time

from pyeventbus3.pyeventbus3 import PyBus, Mode, subscribe

from Message import Message
from MessageTo import MessageTo
from TokenMessage import TokenMessage
from BroadcastMessage import BroadcastMessage

class Com:
  """
  Communicateur (middleware) qui gère :
  - l'horloge de Lamport (protégée par un lock)
  - les envois de message (publish, broadcast, send_to)
  - la boite aux lettres (mailbox) pour les réceptions
  - la mise à jour d'horloge à la reception
  - les communications synchrones (barrières et envois/recep. bloquants)
  - la section critique distribuée (token ring)
  - la numérotation REGISTER des processus
  """

  def __init__(self, owner_name: str, npProcess: int):
    self.owner_name = owner_name
    self.npProcess = npProcess
    self._clock = 0
    self._clock_lock = Lock()

    # Boîte aux lettres des messages reçus pour ce process
    self._mailbox = Queue()

    # État section critique distribuée (token ring)
    self.waiting = False
    self.holding_token = False
    self.token_event = Event()  # pour bloquer en attente du token

    # Infos sur le processus
    self.myId = None # sera fixé par le process après REGISTER
    self.alive = True

    # Synchronisation (barrière)
    self._sync_received = set()
    self._sync_event = None

    # REGISTER
    self.participants = set()

    # Enregistrement de l'ordre d'arrivée des REGISTER
    self._register_records = [] # liste de tuples (clock, name)
    self._register_seen = set() # pour éviter les doublons
    self.register_event = Event()  # permet de réveiller register() quand tous reçus

    # Inscription au bus
    PyBus.Instance().register(self, self)

  # --------------------------------------------------------------
  # Horloge de Lamport (APIs)
  # Règle Lamport: clock = max(local, received) + 1
  # --------------------------------------------------------------

  # Incrementer l'horloge locale
  def incrementClock(self) -> int:
    with self._clock_lock:
      self._clock += 1
      return self._clock
    
  # Retourne la valeur courante de l'horloge
  def getClock(self) -> int:
    with self._clock_lock:
      return self._clock
    
  # Mise à jour de l'horloge à la réception d'un message utilisateur
  def update_on_receive(self, received_clock: int) -> int:
    with self._clock_lock:
      self._clock = max(self._clock, received_clock) + 1
      return self._clock
    
  # --------------------------------------------------------------
  # Envois (messages utilisateurs)
  # --------------------------------------------------------------

  # Envoi 'publish' (type Message) : tout le monde reçoit y compris l'emetteur (affecte l'horloge)
  def publish(self, payload):
    send_clock = self.incrementClock()
    m = Message(payload, send_clock, self.owner_name)
    print(f"[{self.owner_name}][COM-PUBLISH] msg={m.getPayload()} msgClock={m.getClock()} sender={m.getSender()}")
    PyBus.Instance().post(m)
    
  # Envoi 'broadcast' (type BroadcastMessage) : tous les autres reçoivent et l'emetteur s'ignore (affecte l'horloge)
  def broadcast(self, payload):
    send_clock = self.incrementClock()
    bm = BroadcastMessage(payload, send_clock, self.owner_name)
    print(f"[{self.owner_name}][COM-BROADCAST] msg={bm.getPayload()} msgClock={bm.getClock()} sender={bm.getSender()}")
    PyBus.Instance().post(bm)
    
  # Envoi ciblé (type MessageTo) : seul 'to' reçoit (affecte l'horloge)
  def sendTo(self, payload, to):
    send_clock = self.incrementClock()
    mt = MessageTo(payload, send_clock, self.owner_name, to)
    print(f"[{self.owner_name}][COM-SEND-TO] msg={mt.getPayload()} msgClock={mt.getClock()} sender={mt.getSender()} to={mt.getTo()}")
    PyBus.Instance().post(mt)
    
  # --------------------------------------------------------------
  # Réception / Boîte aux lettres
  # --------------------------------------------------------------

  # Dépose un message reçu dans la boîte aux lettres du process (à appeler depuis les handlers de réception)
  def enqueue_incoming(self, msg_obj):
    self._mailbox.put(msg_obj)
    
  # Récupère un message de la boîte aux lettres :
  # - si timeout = Non -> bloquant jusqu'à réception
  # - si timeout = x (float) -> attente max de x secondes
  # lève Empty si timeout écoulé
  def try_get(self, timeout=None):
    return self._mailbox.get(timeout=timeout)
    
  # Récupère un message de la boîte aux lettres sans attente (None si vide)
  def poll_no_wait(self):
    try:
      return self._mailbox.get_nowait()
    except Empty:
      return None
    
  # --------------------------------------------------------------
  # REGISTER (numérotation des processus)
  # --------------------------------------------------------------

  # Envoi de mon REGISTER
  def register(self):
    # Réinitialise le suivi d'inscription
    self.participants = {self.owner_name}  # je me compte déjà
    self._register_records = []
    self._register_seen = {self.owner_name}

    # Diffuse mon REGISTER et mémorise l'horloge d'envoi
    my_reg_clock = self.incrementClock()
    self.broadcast({"type": "REGISTER", "name": self.owner_name, "clock": my_reg_clock})
    self._register_records.append((my_reg_clock, self.owner_name))

    print(f"[{self.owner_name}][REGISTER] annoncé {self.owner_name}, attente de {self.npProcess} participants...")

    # Attente des autres REGISTER
    while len(self.participants) < self.npProcess:
      self.register_event.wait(timeout=0.2)  # reveil périodique pour vérifier la condition

    # Calcul des IDs par ordre d'arrivée (horloge, puis nom pour déterminisme)
    ordered = sorted(self._register_records, key=lambda t: (t[0], t[1]))
    sorted_names = [name for _, name in ordered]
    self.name_to_id = {name: idx for idx, name in enumerate(sorted_names)}
    self.myId = sorted_names.index(self.owner_name)

    print(f"[{self.owner_name}][REGISTER] ordre d'arrivée={sorted_names} -> myID={self.myId}")
    
    return self.myId
  
  
  @subscribe(threadMode=Mode.PARALLEL, onEvent=BroadcastMessage)
  def onBroadcast(self, event):
    if event.getSender() == self.owner_name:
      return  # j'ignore mes propres broadcasts
    updated = self.update_on_receive(event.getClock())
    payload = event.getPayload()

    # Gestion des REGISTER
    if isinstance(payload, dict) and payload.get("type") == "REGISTER":
      name = payload["name"]
      if name not in self._register_seen:
        self._register_seen.add(name)
        self.participants.add(name)
        # on stocke l'horloge envoyée par le processus emetteur
        msg_clock = payload.get("clock", event.getClock())
        self._register_records.append((msg_clock, name))

      print(f"[{self.owner_name}][REGISTER] reçu de {name} ({len(self.participants)}/{self.npProcess})")

      if self.npProcess is not None and len(self.participants) >= self.npProcess:
        self.register_event.set()  # reveille la boucle d'attente
      return
    
    # Gestion des REQUEST (SC)
    if isinstance(payload, dict) and payload.get("type") == "REQUEST":
      requester = payload["from"]
      print(f"[{self.owner_name}][REQUEST-RECV] reçu REQUEST de P{requester}")
      if self.holding_token and not self.waiting:
        # Je n'attends pas, je passe le token au demandeur
        print(f"[{self.owner_name}][REQUEST-RELAY] je passe le token à P{requester}")
        self.holding_token = False
        self.sendToken(requester)
      return

    # Gestion des SYNC
    if isinstance(payload, dict) and payload.get("type") == "SYNC":
      self._sync_received.add(event.getSender())
      print(f"[{self.owner_name}][COM-SYNC-RECV] reçu SYNC de {event.getSender()} ({len(self._sync_received)}/{self.npProcess})")
      if len(self._sync_received) >= self.npProcess:
        self._sync_event.set()  # reveille la boucle d'attente
      return
    
    # Gestion des SYNC-BROADCAST
    if isinstance(payload, dict) and payload.get("type") == "SYNC-BROADCAST":
      print(f"[{self.owner_name}][COM-SYNC-BROADCAST-RECV] reçu SYNC-BROADCAST de {event.getSender()} -> msg={payload['data']}")
      # Répondre par un ACK
      to_id = self.name_to_id.get(event.getSender(), event.getSender())
      ack = MessageTo({"type": "ACK-SYNC-BROADCAST"}, self.incrementClock(), self.owner_name, to_id)
      PyBus.Instance().post(ack)
      print(f"[{self.owner_name}][COM-SYNC-ACK-SEND] envoyé ACK à {event.getSender()}")
      return
    
    print(f"[{self.owner_name}][COM-BROADCAST-RECV] reçu de {event.getSender()} msg={payload} msgClock={event.getClock()} -> localClock={updated})")
    self.enqueue_incoming(event)

  @subscribe(threadMode=Mode.PARALLEL, onEvent=MessageTo)
  def onReceive(self, event):
    if self.myId is None or event.getTo() != self.myId:
      return
    
    payload = event.getPayload()
    if isinstance(payload, dict) and payload.get("type") == "ACK-SYNC-BROADCAST":
      if event.getSender() != self.owner_name: # j'ignore mes propres ACK
        print(f"[{self.owner_name}][COM-SYNC-ACK-RECV] reçu ACK de {event.getSender()}")
        self.handle_ack()
        return
    if isinstance(payload, dict) and payload.get("type") == "ACK-SYNC-TO":
      if event.getSender() != self.owner_name: # j'ignore mes propres ACK
        print(f"[{self.owner_name}][COM-SYNC-TO-ACK-RECV] reçu ACK de {event.getSender()}")
        self.handle_ack()
        return

    updated = self.update_on_receive(event.getClock())
    print(f"[{self.owner_name}][COM-RECV-TO] reçu de {event.getSender()} to={event.getTo()} msg={payload} msgClock={event.getClock()} -> localClock={updated})")
    self.enqueue_incoming(event)
  
  # --------------------------------------------------------------
  # Synchronisation (barrière générrale)
  # --------------------------------------------------------------

  # Barrière distribuée : attend que tous les processus aient appelé synchronize().
  # Envoie un message SYNC et attend d'en recevoir un de chaque participant.
  def synchronize(self, npProcess: int):
    # Envoi de mon SYNC
    send_clock = self.incrementClock()
    bm = BroadcastMessage({"type": "SYNC"}, send_clock, self.owner_name)
    print(f"[{self.owner_name}][COM-SYNC] envoi SYNC msgClock={send_clock}")
    PyBus.Instance().post(bm)

    # Préparer la barrière
    self._sync_received = {self.owner_name}  # je me compte déjà
    self._sync_event = Event()

    # Bloque jusqu'à réception de tous les SYNC
    while not self._sync_event.wait(timeout=0.1):
      pass
    print(f"[{self.owner_name}][COM-SYNC] Tous les SYNC reçus, barrière franchie")

    # Nettoyage des variables temporaires
    del self._sync_received
    del self._sync_event

  # --------------------------------------------------------------
  # Communications Synchrones
  # --------------------------------------------------------------

  # Broadcast synchrone :
  # - si je suis l'emetteur, j'envoie et j'attends que tous les autres aient fait de même
  # - sinon j'attends de recevoir le broadcast et j'envoie un ACK
  def broadcastSync(self, payload, from_id: int, my_id: int):

    # Cas 1 : je suis l'emetteur
    if from_id == my_id:
      send_clock = self.incrementClock()
      bm = BroadcastMessage({"type": "SYNC-BROADCAST", "data": payload}, send_clock, self.owner_name)
      print(f"[{self.owner_name}][COM-SYNC-BROADCAST] msg={payload} msgClock={send_clock}")
      PyBus.Instance().post(bm)

      # J'attends les ACK de tous les autres
      self._acks_received = 0
      self._acks_target = self.npProcess - 1  # tous sauf moi
      self._acks_event = Event()

      # Bloque jusqu'à réception de tous les ACK
      while not self._acks_event.wait(timeout=0.1):
        pass
      print(f"[{self.owner_name}][COM-SYNC-BROADCAST] Tous les ACK reçus, barrière franchie")

      # Nettoyage des variables temporaires
      del self._acks_received
      del self._acks_target
      del self._acks_event
  
  # Envoi synchrone : envoi d'un message dédié à 'to' et attend un ACK
  def sendToSync(self, payload, to, my_id: int):
    send_clock = self.incrementClock()
    mt = MessageTo(payload, send_clock, self.owner_name, to)
    print(f"[{self.owner_name}][COM-SEND-TO-SYNC] msg={mt.getPayload()} msgClock={mt.getClock()} sender={mt.getSender()} to={to}")

    # Prépare un event pour attendre l'ACK
    self._acks_received = 0
    self._acks_target = 1  # un seul ACK attendu
    self._acks_event = Event()
    self._acks_from = to  # on note de qui on attend l'ACK

    # Envoi du message
    PyBus.Instance().post(mt)

    # Bloque jusqu'à réception de l'ACK
    while not self._acks_event.wait(timeout=0.1):
      pass
    print(f"[{self.owner_name}][COM-SEND-TO-SYNC] ACK reçu de P{to}")

    # Nettoyage des variables temporaires
    del self._acks_received
    del self._acks_target
    del self._acks_event
    del self._acks_from

  # Réception synchrone :  bloque jusuq'à la réception d'un message venant de 'from_id'
  def receiveFromSync(self, from_id: int, timeout=None):
    try:
      while True:
        msg = self.try_get(timeout=timeout)
        if msg is None:
          continue
        if isinstance(msg, MessageTo):
          sender = msg.getSender()
          if sender == f"P{from_id}" or sender == from_id:
            print(f"[{self.owner_name}][COM-RECEIVE-FROM-SYNC] reçu de P{from_id} -> msg={msg.getPayload()}")
            # Répondre par un ACK
            ack = MessageTo({"type": "ACK-SYNC-TO"}, self.incrementClock(), self.owner_name, from_id)
            PyBus.Instance().post(ack)
            return msg
    except Empty:
      print(f"[{self.owner_name}][COM-RECEIVE-FROM-SYNC] timeout d'attente écoulé")
      return None
  
  # Incrémente le compteur d'ACK reçus et débloque si tous reçus
  def handle_ack(self):
    if hasattr(self, '_acks_received'):
      self._acks_received += 1
      if self._acks_received >= self._acks_target:
        self._acks_event.set()
  
  # --------------------------------------------------------------
  # Section Critique Distribuée (Token Ring)
  # --------------------------------------------------------------
  # Demande l'entrée en section critique (bloque jusqu'à obtention du token)
  def requestSC(self):
    self.waiting = True
    print(f"[{self.owner_name}][REQUEST] J'attends le token...")
    # Annonce aux autres que je veux entrer en SC (optionnel)
    self.broadcast({"type": "REQUEST", "from": self.myId})
    self.token_event.wait()  # bloque jusqu'à obtention du token
    self.token_event.clear()  # réinitialise l'event pour la prochaine fois
    print(f"[{self.owner_name}][ENTER] J'ai le token, j'entre en SC")
  
  # Libère le token et le passe au suivant
  def releaseSC(self):
    if not self.holding_token:
      return
    print(f"[{self.owner_name}][EXIT] Je quitte la SC et passe le token au suivant")
    self.waiting = False
    self.holding_token = False
    self.sendToken(self.nextId()) # passage explicite après la SC
  
  # Envoi du token au voisin suivant
  def sendToken(self, to_id: int):
    send_clock = self.getClock()  # pas d'incrémentation ici
    tm = TokenMessage(send_clock, self.owner_name, to_id)
    print(f"[{self.owner_name}][TOKEN-SEND] to=P{to_id} clock={tm.getClock()} sender={tm.getSender()}")
    PyBus.Instance().post(tm)
  
  # Calcule l'ID du voisin suivant dans le ring
  def nextId(self):
    return (self.myId + 1) % self.npProcess

  # Réception du token (handler d'événement)
  @subscribe(threadMode=Mode.PARALLEL, onEvent=TokenMessage)
  def onToken(self, event):
    if not self.alive:
      return
    if event.getTo() != self.myId:
      return
    
    local = self.getClock()
    print(f"[{self.owner_name}][TOKEN-RECV] from={event.getSender()} waiting={self.waiting} -> localClock={local}")

    if not self.alive:
      return

    if self.waiting:
      # Garde le jeton pour la SC
      self.holding_token = True
      self.token_event.set()  # pour reveiller request
      print(f"[{self.owner_name}][TOKEN-HELD] je garde le jeton pour la SC")
    else:
      # Je n'attends pas, je garde le jeton en réserve
      self.holding_token = True
      print(f"[{self.owner_name}][TOKEN-RELAY] je garde le jeton en réserve")

  # Arrête proprement le communicateur
  def stop(self):
    self.alive = False
    try:
      self.com.stop()
    except Exception:
      pass

    # Débloque une éventuelle attente du token
    try:
      self.token_event.set()
    except Exception:
      pass

    # Si une barrière SYNC est en cours, la libérer
    if hasattr(self, '_sync_event') and self._sync_event is not None:
      try:
        self._sync_event.set()
      except Exception:
        pass
    
    # Si un broadcastSync/sendToSync est en cours, le libérer
    if hasattr(self, '_acks_event') and self._acks_event is not None:
      try:
        self._acks_event.set()
      except Exception:
        pass
    
    # Débloque une éventuelle get() bloquante si jamais elle est utilisée sans timeout
    try:
      self._mailbox.put_nowait(None)
    except Exception:
      pass
    
    # Se désinscrire du bus
    try:
      PyBus.Instance().unregister(self)
    except Exception:
      pass

      