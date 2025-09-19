from MessageBase import MessageBase

class Message(MessageBase):
    """
    Message de type *publish* (tout le monde reçoit, y compris l'émetteur).
    Hérite : payload, horloge (Lamport), émetteur, type de payload.
    """
    def __init__(self, payload, clock, sender, payload_type=None):
        """
        Construit un message générique (publish).
        :param payload: contenu applicatif
        :param clock: horloge logique à l'envoi
        :param sender: nom du processus émetteur (ex. "P0")
        :param payload_type: étiquette de type optionnelle
        """
        super().__init__(payload, clock, sender, payload_type)
