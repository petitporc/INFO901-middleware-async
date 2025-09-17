from MessageBase import MessageBase

class TokenMessage(MessageBase):
  def __init__(self, clock, sender, to):
    super().__init__(payload=None, clock=clock, sender=sender, payload_type="TokenMessage")
    self.to = to
  
  def getTo(self):
    return self.to
  
  def __repr__(self):
    return (f"{self.__class__.__name__}(payload={self._payload!r}, " f"clock={self._clock}, sender={self._sender}, to={self.to}, type={self._payload_type})")