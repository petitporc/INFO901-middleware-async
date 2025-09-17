class MessageBase:
  """
  Classe de base pour les messages échangés dans le middleware.
  """

  def __init__(self, payload, clock, sender, payload_type=None):
    self._payload = payload
    self._clock = clock
    self._sender = sender
    self._payload_type = payload_type if payload_type is not None else type(payload).__name__

  def getPayload(self):
    return self._payload

  def getClock(self):
    return self._clock

  def getSender(self):
    return self._sender
  
  def getPayloadType(self):
    return self._payload_type
  
  def __repr__(self):
    return (f"{self.__class__.__name__}(payload={self._payload!r}, " f"clock={self._clock}, sender={self._sender}, type={self._payload_type})")