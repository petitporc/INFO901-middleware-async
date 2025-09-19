from threading import Lock, Thread
from queue import Empty
from time import sleep

from Message import Message
from BroadcastMessage import BroadcastMessage
from MessageTo import MessageTo
from TokenMessage import TokenMessage
from Com import Com

from pyeventbus3.pyeventbus3 import *


class Process(Thread):
    """
    Thread représentant un processus applicatif.
    Sert de façade au communicateur (Com) et exécute le scénario.
    """

    _token_started = False
    _token_lock = Lock()

    def __init__(self, name, npProcess):
        """
        Initialise le processus et son communicateur, s'abonne au bus et démarre le thread.
        :param name: nom logique (ex. "P0")
        :param npProcess: nombre total de processus attendus
        """
        Thread.__init__(self)

        self.npProcess = npProcess
        self.myProcessName = name
        self.com = Com(self.myProcessName, self.npProcess)
        self.setName("MainThread-" + name)

        # États internes
        self.alive = True

        # Inscription au bus d'événements
        PyBus.Instance().register(self, self)

        # Liste des participants connus
        self.participants = set()

        # Démarrage du thread
        self.start()

    def _log(self, category: str, msg: str):
        """
        Affiche un message de log uniformisé côté Process.
        :param category: étiquette (ex. "STOP", "BARRIER", …)
        :param msg: contenu à afficher
        """
        print(f"[PROCESS][{self.getName()}][{category}] {msg}")
    
    # --------------------------------------------------------------
    # Wrapers vers Com
    # --------------------------------------------------------------

    def incrementClock(self):
        """
        Incrémente l'horloge de Lamport via Com (opération atomique).
        :return: nouvelle valeur de l'horloge
        """
        return self.com.incrementClock()

    def updateClockOnReceive(self, receivedClock):
        """
        Met à jour l'horloge locale (max + 1) à la réception d'un message.
        :param receivedClock: horloge fournie par le message reçu
        :return: horloge locale mise à jour
        """
        return self.com.update_on_receive(receivedClock)
    
    def getClock(self):
        """
        Retourne l'horloge logique courante (Lamport).
        :return: entier représentant l'horloge
        """
        return self.com.getClock()

    def broadcast(self, payload):
        """
        Envoie un message broadcast (tous sauf l'émetteur).
        :param payload: contenu applicatif à diffuser
        """
        self.com.broadcast(payload)

    def sendTo(self, payload, to):
        """
        Envoie un message direct vers l'identifiant cible.
        :param payload: contenu applicatif
        :param to: id du destinataire
        """
        self.com.sendTo(payload, to)

    #--------------------------------------------------------------
    # Boucle principale
    #--------------------------------------------------------------

    def run(self):
        """
        Point d'entrée du thread : exécute le scénario applicatif puis arrête proprement.
        """
        try:
            # import local our éviter toute importation circulaire
            from scenario import play_demo
            play_demo(self)
            
        finally:
            # On termine proprement le processus
            self.alive = False
            self._log("STOP", "Processus terminé")
            self.com.stop()

    #--------------------------------------------------------------
    # Stop
    #--------------------------------------------------------------

    def stop(self):
        """
        Demande l'arrêt du processus : désinscription bus puis arrêt du communicateur.
        """
        self.alive = False
        try:
            PyBus.Instance().unregister(self, self)
        except Exception:
            pass
        self.com.stop()

    def waitStopped(self):
        """
        Bloque jusqu'à l'arrêt effectif du thread (join).
        """
        if self.is_alive():
            self.stop()
        self.join()
