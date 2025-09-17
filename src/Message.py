from MessageBase import MessageBase

class Message(MessageBase):
    def __init__(self, payload, clock, sender, payload_type=None):
        super().__init__(payload, clock, sender, payload_type)
    