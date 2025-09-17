from MessageBase import MessageBase

class MessageTo(MessageBase):
  def __init__(self, payload, clock, sender, to, payload_type=None):
    super().__init__(payload, clock, sender, payload_type)
    self.to = to
  
  def getTo(self):
    return self.to
  
  def __repr__(self):
    return (f"{self.__class__.__name__}(payload={self._payload!r}, " f"clock={self._clock}, sender={self._sender}, to={self.to}, type={self._payload_type})")
  