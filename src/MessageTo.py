class MessageTo:
  def __init__(self, payload, clock, sender, to, payload_type=None):
    self.payload = payload
    self.clock = clock
    self.sender = sender
    self.to = to
    self.payload_type = payload_type
  
  def getPayload(self):
    return self.payload
  
  def getClock(self):
    return self.clock
  
  def getSender(self):
    return self.sender
  
  def getTo(self):
    return self.to
  
  def getPayloadType(self):
    return self.payload_type
  
  def __repr__(self):
    return f"MessageTo(payload={self.payload!r}, clock={self.clock}, sender={self.sender}, to={self.to}, type={self.payload_type})"
  