from threading import Lock, Thread, Event
from queue import Empty
from time import sleep

from Message import Message
from BroadcastMessage import BroadcastMessage
from MessageTo import MessageTo
from TokenMessage import TokenMessage
from Com import Com

from pyeventbus3.pyeventbus3 import *


class Process(Thread):
        
    nbProcessCreated = 0
    _token_started = False
    _token_lock = Lock()

    def __init__(self, name, npProcess):
        Thread.__init__(self)

        self.npProcess = npProcess
        self.myProcessName = name
        self.com = Com(self.myProcessName)
        self.setName("MainThread-" + name)

        # États internes
        self.alive = True
        self.clock = 0
        self.lock = Lock()
        self.waiting = False # en demande de section critique ?
        self.holding_token = False # en possession du token ?
        self.token_event = Event() # pour reveiller request
        self.sync_event = Event()
        self.sync_seen = set()
        self.sync_lock = Lock()

        # Inscription au bus d'événements
        PyBus.Instance().register(self, self)

        # --------------------------------------------------------------
        # Phase REGISTER (numéro d'ID déterministe)
        # --------------------------------------------------------------

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

    @subscribe(threadMode = Mode.PARALLEL, onEvent=BroadcastMessage)
    def onBroadcast(self, event):
        if event.getSender() == self.myProcessName:
            # Ignore mes propres messages
            return
        updated = self.updateClockOnReceive(event.getClock())

        payload = event.getPayload()
        if isinstance(payload, dict) and payload.get("type") == "SYNC":
            with self.sync_lock:
                self.sync_seen.add(event.getSender())
                count = len(self.sync_seen)
                print(f"[{self.getName()}][SYNC-RECV] de {event.getSender()} ({count}/{self.npProcess})")
                if count >= self.npProcess:
                    self.sync_event.set()
            return
        
        # Mettre les SYNC-BROADCAST dans la mailbox
        if isinstance(payload, dict) and payload.get("type") == "SYNC-BROADCAST":
            print(f"[{self.getName()}][COM-SYNC-BROADCAST-RECV] from={event.getSender()} msg={payload['data']}")
            # J'envoie un ACK à l'émetteur
            ack = MessageTo({"type": "ACK-SYNC"}, self.incrementClock(), self.myProcessName, 0) # to=0 car l'émetteur est P0
            print(f"[{self.getName()}][COM-SYNC-ACK-SEND] envoi ACK vers P0")
            PyBus.Instance().post(ack)
            return # pas de mise en boîte aux lettres

        # Sinon traitement normal
        print(f"[{self.getName()}][RECV-BROADCAST] from={event.getSender()} msg={event.getPayload()} msgClock={event.getClock()} -> localClock={updated} (thread={threading.current_thread().name})")
        self.com.enqueue_incoming(event)

    @subscribe(threadMode = Mode.PARALLEL, onEvent=MessageTo)
    def onReceive(self, event):
        # Seul le destinataire traite le message
        if event.getTo() != self.myId:
            return
        
        # Vérification du type payload
        payload = event.getPayload()

        # Gestion des ACK de synchro
        if isinstance(payload, dict):
            if payload.get("type") == "ACK-SYNC":
                # ACK de broadcastSync
                print(f"[{self.getName()}][SYNC-ACK-RECV] de {event.getSender()}")
                self.com.handle_ack()
                return # pas de mise en boîte aux lettres
                
            if payload.get("type") == "ACK-SYNC-TO":
                # ACK de sendToSync
                print(f"[{self.getName()}][SYNC-ACK-TO-RECV] de {event.getSender()}")
                self.com.handle_ack()
                return # pas de mise en boîte aux lettres
        
        # Traitement normal
        updated = self.updateClockOnReceive(event.getClock())
        print(f"[{self.getName()}][RECV-TO] from={event.getSender()} to={event.getTo()} msg={payload} msgClock={event.getClock()} -> localClock={updated} (thread={threading.current_thread().name})")
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
            sleep(1)

            # --- PHASE REGISTER (numérotation déterministe) ---
            if loop == 0:
                # 1) j'annonce
                self.participants = set()
                self.participants.add(self.myProcessName)
                self.broadcast({"type": "REGISTER", "name": self.myProcessName})
                print(f"[{self.getName()}][REGISTER] annoncé {self.myProcessName}, attente de {self.npProcess} participants...")

                # 2) je collecte avec un timeout global (ex: 3s)
                import time
                deadline = time.time() + 3.0  # ajuste si besoin
                while len(self.participants) < self.npProcess and time.time() < deadline:
                    try:
                        msg = self.com.try_get(timeout=0.2)  # peut lever Empty
                    except Empty:
                        continue
                    payload = msg.getPayload()
                    if isinstance(payload, dict) and payload.get("type") == "REGISTER":
                        self.participants.add(payload["name"])
                        print(f"[{self.getName()}][REGISTER] reçu {payload['name']} ({len(self.participants)}/{self.npProcess})")
                    else:
                        # remet en BAL ce qui n'est pas du REGISTER
                        self.com.enqueue_incoming(msg)

                # 3) calcul de l'ID (même si tout le monde n'a pas répondu, on essaye)
                sorted_names = sorted(self.participants)
                if self.myProcessName not in sorted_names:
                    sorted_names.append(self.myProcessName)
                    sorted_names = sorted(sorted_names)

                self.myId = sorted_names.index(self.myProcessName)
                print(f"[{self.getName()}][REGISTER] participants={sorted_names} -> myID={self.myId}")

                # on recopie dans Com
                self.com.myId = self.myId
                self.com.npProcess = self.npProcess

                # 4) si je suis le dernier (ID max = npProcess-1), je déclenche le jeton
                if self.myId == self.npProcess - 1:
                    def _delayed_start():
                        sleep(0.2)
                        with Process._token_lock:
                            if not Process._token_started:
                                print(f"[{self.getName()}] Initial token launch -> P0")
                                self.com.sendToken(to_id=0)
                                Process._token_started = True
                    Thread(target=_delayed_start, daemon=True).start()
            # --- fin phase REGISTER ---

            # Synchronisation des processus au tour 2 avec le middleware
            if self.myProcessName == "P0" and loop == 2:
                self.com.broadcastSync("Hello everyone, sync time!", from_id=0, my_id=self.myId, npProcess=self.npProcess)
            
            # Exemple de test SendToSync / ReceiveFromSync
            if self.myProcessName == "P0" and loop == 3:
                print(f"[{self.getName()}] TEST sendToSync vers P1")
                self.com.sendToSync({"type": "test-sync", "text": "Hello P1, synchro!"}, to=1, my_id=self.myId)

            if self.myProcessName == "P1" and loop == 3:
                print(f"[{self.getName()}] TEST receiveFromSync de P0")
                msg = self.com.receiveFromSync(from_id=0, timeout=5)
                print(f"[{self.getName()}] Message synchrone reçu de P0 -> {msg.getPayload()}")

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
        # Débloquer toute attente éventuelle
        #self.token_event.set()
        #self.sync_event.set()

    def waitStopped(self):
        self.join()
