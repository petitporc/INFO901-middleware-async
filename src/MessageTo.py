from MessageBase import MessageBase

class MessageTo(MessageBase):
  """
  Message adressé à un destinataire unique (point-à-point).
  Ajoute le champ `to` à la structure de base.
  """
  def __init__(self, payload, clock, sender: int, to: int, payload_type=None):
    """
    Construit un message direct vers `to`.
    :param payload: contenu applicatif
    :param clock: horloge logique au moment de l'envoi
    :param sender: nom/id logique de l'émetteur
    :param to: identifiant du destinataire
    :param payload_type: étiquette de type (optionnelle)
    """
    super().__init__(payload, clock, sender, payload_type)
    self.to = to
  
  def getTo(self):
    """
    Retourne l'identifiant du destinataire.
    """
    return self.to
  
  def __repr__(self):
    """
    Représentation utile au débogage (classe, payload, horloge, émetteur, destinataire, type).
    """
    return (f"{self.__class__.__name__}(payload={self._payload!r}, "
            f"clock={self._clock}, sender={self._sender}, to={self.to}, "
            f"type={self._payload_type})")
