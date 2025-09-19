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

    # --------------------------------------------------------------
    # Abonnement aux événements
    # --------------------------------------------------------------

    @subscribe(threadMode = Mode.PARALLEL, onEvent=Message)
    def process(self, event):
        updated = self.updateClockOnReceive(event.getClock())
        self._log("RECEIVE", f"de={event.getSender()} payload={event.getPayload()} msgClock={event.getClock()} -> localClock={updated} (thread={threading.current_thread().name})")
        self.com.enqueue_incoming(event)

    #--------------------------------------------------------------
    # Boucle principale
    #--------------------------------------------------------------

    def run(self):
        try:
            # --- ÉTAPE 0 --- : REGISTER + Barrière globale
            self.com.register() # ID stocké dans le communicateur

            # barriere pour s'assurer que tout le monde a fini de REGISTER
            self._log("BARRIER", f"Attente de REGISTER de tous les processus")
            self.com.synchronize(self.npProcess) 
            self._log("BARRIER", f"REGISTER de tous les processus OK")
            self.com._start_heartbeats()

            # --- ÉTAPE 1 --- : Dernier processus démarre le jeton
            if self.com.getMyId() == self.npProcess - 1:
                def _delayed_start():
                    from time import sleep as _sleep
                    _sleep(0.2)
                    with Process._token_lock:
                        if not Process._token_started:
                            self._log("TOKEN", "Dernier processus lance le jeton")
                            self.com.sendToken(to_id=0)
                            Process._token_started = True
                Thread(target=_delayed_start, daemon=True).start()
            
            # Petite marge pour laisser circuler le jeton
            sleep(0.3)

            # --- ÉTAPE 2 --- : Démo asynchrone (P1 envoie)
            if self.myProcessName == "P1":
                # Broadcast tout le monde sauf l'émetteur
                self.com.broadcast({"type": "greeting", "text": "Hello je broadcast !"})
                # Message ciblé vers P0
                self.com.sendTo({"type": "greeting", "text": "Hello je sendTo P0 !"}, to=0)
                # Publish tout le monde y compris l'émetteur
                self.com.publish({"type": "greeting", "text": "Hello je publish !"})
            
            sleep(0.3)

            # --- ÉTAPE 3 --- : Barrière 2 pour aligner tout le monde en synchro
            self._log("BARRIER", f"Préparation broadcastSync")
            self.com.synchronize(self.npProcess)
            self._log("BARRIER", f"broadcastSync OK")

            # --- ÉTAPE 4 --- : Diffusion synchrone (ACK de tous requis)
            if self.myProcessName == "P0":
                self.com.broadcastSync("Hello, synchronize time !", from_id=0, my_id=self.com.getMyId())
            
            sleep(0.3)

            # --- ÉTAPE 5 --- : Synchro point à point P0 -> P1
            if self.myProcessName == "P0":
                self._log("TEST-SYNC-TO", "sendToSync P0 -> P1")
                self.com.sendToSync({"type": "test-sync", "text": "Hello je sendToSync P1 !"}, to=1, my_id=self.com.getMyId())
            
            if self.myProcessName == "P1":
                self._log("TEST-SYNC-FROM", "receiveFromSync P1 <- P0")
                msg = self.com.receiveFromSync(from_id=0, timeout=5)
                if msg:
                    self._log("TEST-SYNC-FROM", f"reçu de P0 -> {msg.getPayload()}")
                else:
                    self._log("TEST-SYNC-FROM", "timeout en attente de P0")
            
            # --- ÉTAPE 6 --- : Section critique (anneau à jeton)
            # P1 passe d'abord en SC puis P2
            if self.myProcessName == "P1":
                sleep(0.2) # léger décalage pour que le jeton circule si besoin
                self.com.requestSC()
                sleep(1.0) # travail en SC
                self.com.releaseSC()

            if self.myProcessName == "P2":
                sleep(1.2) # démarre après P1
                self.com.requestSC()
                sleep(1.0) # travail en SC
                self.com.releaseSC()
            
            # Laisser finir les ACK éventuels
            sleep(0.5)

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
