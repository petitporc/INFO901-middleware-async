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
        self.myId = None  # sera fixé après phase REGISTER

        # Inscription au bus d'événements
        PyBus.Instance().register(self, self)

        # Liste des participants connus
        self.participants = set()

        # Démarrage du thread
        self.start()
    
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
        print(f"[{self.getName()}][RECV] from={event.getSender()} msg={event.getPayload()} msgClock={event.getClock()} -> localClock={updated} (thread={threading.current_thread().name})")
        self.com.enqueue_incoming(event)

    #--------------------------------------------------------------
    # Boucle principale
    #--------------------------------------------------------------

    def run(self):
        loop = 0
        while self.alive:

            # Horloge locale
            local_clock = self.incrementClock()
            print(f"[{self.getName()}][LOOP {loop}] localClock={local_clock}")

            for _ in range(10):
                if not self.alive:
                    break
                sleep(0.1)

            # PHASE REGISTER
            if loop == 0:
                self.myId = self.com.register() # récupère l'ID depuis Com

                # Dernier processus démarre le jeton
                if self.myId == self.npProcess - 1:
                    def _delayed_start():
                        sleep(0.2)
                        with Process._token_lock:
                            if not Process._token_started:
                                print(f"[{self.getName()}] Initial token launch -> P0")
                                self.com.sendToken(to_id=0)
                                Process._token_started = True
                    Thread(target=_delayed_start, daemon=True).start()

            # EXEMPLES D'UTILISATION

            # Synchronisation des processus au tour 2 avec le middleware
            if self.myProcessName == "P0" and loop == 2:
                self.com.broadcastSync("Hello everyone, sync time!", from_id=0, my_id=self.myId)
            
            # Exemple de test SendToSync / ReceiveFromSync
            if self.myProcessName == "P0" and loop == 3:
                print(f"[{self.getName()}] TEST sendToSync vers P1")
                self.com.sendToSync({"type": "test-sync", "text": "Hello P1, synchro!"}, to=1, my_id=self.myId)

            if self.myProcessName == "P1" and loop == 3:
                print(f"[{self.getName()}] TEST receiveFromSync de P0")
                msg = self.com.receiveFromSync(from_id=0, timeout=5)
                if msg:
                    print(f"... -> {msg.getPayload()}")
                else:
                    print(f"[{self.getName()}] Rien reçu de P0 (timeout)")

            # Envoi de messages par P1
            if self.myProcessName == "P1":
                # Envoi de broadcast
                self.broadcast({"type": "greeting", "text": "ga"})

                # Envoi de message dedié
                self.sendTo({"type": "greeting", "text": "Hello P0"}, to=0)

                # Envoi de message
                self.com.publish({"type": "greeting", "text": "bu"})

            # Demande de section critique
            # Exemple : P1 demande la SC après 3 tours
            if self.myProcessName == "P1" and loop == 3:
                self.com.requestSC()
                sleep(2)  # simulation de travail en SC
                self.com.releaseSC()

            # Exemple : P2 demande la SC après 6 tours
            if self.myProcessName == "P2" and loop == 6:
                self.com.requestSC()
                sleep(2)
                self.com.releaseSC()

        
            loop+=1
        print(self.getName() + " stopped")

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
