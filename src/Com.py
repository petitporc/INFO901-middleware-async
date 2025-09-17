from threading import Lock
from queue import Queue, Empty

from pyeventbus3.pyeventbus3 import PyBus

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
  """

  def __init__(self, owner_name: str):
    self.owner_name = owner_name
    self._clock = 0
    self._clock_lock = Lock()

    # Boîte aux lettres des messages reçus pour ce process
    self._mailbox = Queue()

  # --------------------------------------------------------------
  # Horloge de Lamport (APIs)
  # Règle Lamport: clock = max(local, received) + 1
  # --------------------------------------------------------------

  # Incrementer l'horloge de Lamport
  def incrementClock(self) -> int:
    with self._clock_lock:
      self._clock += 1
      return self._clock
    
  # Lecture de l'horloge de Lamport
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
    
