class TokenMessage:
  def __init__(self, clock, sender, to):
    self.clock = clock
    self.sender = sender
    self.to = to

  def getClock(self):
    return self.clock
  
  def getSender(self):
    return self.sender
  
  def getTo(self):
    return self.to
  
  def __repr__(self):
    return f"TokenMessage(clock={self.clock}, sender={self.sender}, to={self.to})"