class Message():
    def __init__(self, payload, clock, sender, payload_type=None):
        self.payload=payload
        self.clock=clock
        self.sender=sender
        self.payload_type=payload_type if payload_type is not None else type(payload).__name__
    
    def getPayload(self):
        return self.payload

    def getClock(self):
        return self.clock
    
    def getSender(self):
        return self.sender
    
    def getPayloadType(self):
        return self.payload_type
    
    def __repr__(self):
        return f"Message(payload={self.payload!r}, clock={self.clock}, sender={self.sender}, type={self.payload_type})"