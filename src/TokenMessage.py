from MessageBase import MessageBase

class TokenMessage(MessageBase):
  """
  Message système représentant le jeton de l'anneau (SC distribuée).
  Ne transporte pas de payload applicatif, seulement `clock/sender` et `to`.
  """
  def __init__(self, clock, sender, to):
    """
    Construit un message de jeton.
    :param clock: horloge logique (non incrémentée à l'envoi du jeton)
    :param sender: nom/id logique de l'émetteur du jeton
    :param to: identifiant du destinataire du jeton
    """
    super().__init__(payload=None, clock=clock, sender=sender, payload_type="TokenMessage")
    self.to = to
  
  def getTo(self):
    """
    Retourne l'identifiant du destinataire du jeton.
    """
    return self.to
  
  def __repr__(self):
    """
    Représentation détaillée pour le débogage (classe, horloge, émetteur, destinataire, type).
    """
    return (f"{self.__class__.__name__}(payload={self._payload!r}, "
            f"clock={self._clock}, sender={self._sender}, to={self.to}, "
            f"type={self._payload_type})")
