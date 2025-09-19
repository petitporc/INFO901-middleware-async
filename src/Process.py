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
    _token_started = False
    _token_lock = Lock()

    def __init__(self, name, npProcess):
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
        print(f"[PROCESS][{self.getName()}][{category}] {msg}")
    
    # --------------------------------------------------------------
    # Wrapers vers Com
    # --------------------------------------------------------------

    # Incrément de l'horloge Lamport avec accès lock
    def incrementClock(self):
        return self.com.incrementClock()

    # Mise à jour de l'horloge lors de la récupération
    def updateClockOnReceive(self, receivedClock):
        return self.com.update_on_receive(receivedClock)
    
    # Accès en lecture de l'horloge
    def getClock(self):
        return self.com.getClock()

    # Ajout du broadcastMessage
    def broadcast(self, payload):
        self.com.broadcast(payload)

    # Ajout de sendTo
    def sendTo(self, payload, to):
        self.com.sendTo(payload, to)

    #--------------------------------------------------------------
    # Boucle principale
    #--------------------------------------------------------------

    def run(self):
        try:
            # import local our éviter toute importation circulaire
            from scenario import play_demo
            play_demo(self)
            
        finally:
            # On termine proprement le processus
            self.alive = False
            self._log("STOP", "Processus terminé")
            self.com.stop()

    def stop(self):
        self.alive = False
        try:
            PyBus.Instance().unregister(self, self)
        except Exception:
            pass
        self.com.stop()

    def waitStopped(self):
        if self.is_alive():
            self.stop()
        self.join()
