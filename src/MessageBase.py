class MessageBase:
  """
  Classe de base pour les messages échangés dans le middleware.
  Stocke le payload applicatif, l'horloge (Lamport), l'émetteur et le type de payload.
  """

  def __init__(self, payload, clock, sender, payload_type=None):
    """
    Initialise un message générique.
    :param payload: contenu applicatif (dict/str/obj)
    :param clock: horloge logique associée à l'envoi
    :param sender: nom du processus émetteur (ex. "P0")
    :param payload_type: étiquette de type (défaut = type(payload).__name__)
    """
    self._payload = payload
    self._clock = clock
    self._sender = sender
    self._payload_type = payload_type if payload_type is not None else type(payload).__name__

  def getPayload(self):
    """
    Retourne le contenu applicatif (payload) du message.
    """
    return self._payload

  def getClock(self):
    """
    Retourne l'horloge de Lamport présente dans le message.
    """
    return self._clock

  def getSender(self):
    """
    Retourne l'identifiant logique de l'émetteur (ex. "P1").
    """
    return self._sender
  
  def getPayloadType(self):
    """
    Retourne l'étiquette de type du payload (utile pour le dispatch/diagnostic).
    """
    return self._payload_type
  
  def __repr__(self):
    """
    Représentation lisible pour le débogage (classe, payload, horloge, émetteur, type).
    """
    return (f"{self.__class__.__name__}(payload={self._payload!r}, " f"clock={self._clock}, sender={self._sender}, type={self._payload_type})")
