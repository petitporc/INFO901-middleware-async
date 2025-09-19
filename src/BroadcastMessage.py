from MessageBase import MessageBase

class BroadcastMessage(MessageBase):
  """
  Message diffusé à tous les autres processus (l'émetteur s'ignore).
  Hérite des champs : payload, clock (Lamport), sender, payload_type.
  """
  def __init__(self, payload, clock, sender, payload_type=None):
    """
    Construit un message broadcast.
    :param payload: contenu applicatif
    :param clock: horloge logique au moment de l'envoi
    :param sender: nom du processus émetteur (ex. "P0")
    :param payload_type: étiquette de type (optionnelle)
    """
    super().__init__(payload, clock, sender, payload_type)
