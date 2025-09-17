from MessageBase import MessageBase

class BroadcastMessage(MessageBase):
  def __init__(self, payload, clock, sender, payload_type=None):
    super().__init__(payload, clock, sender, payload_type)