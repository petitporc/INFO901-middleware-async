from threading import Lock, Thread, Event

from time import sleep

#from geeteventbus.subscriber import subscriber
#from geeteventbus.eventbus import eventbus
#from geeteventbus.event import event

#from EventBus import EventBus
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
        self.myId = Process.nbProcessCreated
        Process.nbProcessCreated +=1
        self.myProcessName = name
        self.com = Com(self.myProcessName)
        self.setName("MainThread-" + name)

        PyBus.Instance().register(self, self)

        self.alive = True

        # Initialisation de l'horloge Lamport avec des locks
        self.clock = 0
        self.lock = Lock()

        # Etat token ring
        self.waiting = False # en demande de section critique ?
        self.holding_token = False # en possession du token ?
        self.token_event = Event() # pour reveiller request

        # Synchronisation des processus
        self.sync_event = Event()
        self.sync_seen = set()
        self.sync_lock = Lock()

        self.start()

        # si je suis le dernier créé, j'initialise le jeton vers P0 (après un court délai)
        if self.myId == self.npProcess - 1:
            def _delayed_start():
                sleep(0.2)
                with Process._token_lock:
                    if not Process._token_started:
                        print(f"[{self.getName()}] Initial token launch -> P0")
                        self.sendToken(to_id=0)
                        Process._token_started = True
            Thread(target=_delayed_start, daemon=True).start()
    
    # Incrément de l'horloge Lamport avec accès lock
    def incrementClock(self):
        # Délégation à Com
        return self.com.incrementClock()

    # Mise à jour de l'horloge lors de la récupération
    def updateClockOnReceive(self, receivedClock):
        # Délégation à Com
        return self.com.update_on_receive(receivedClock)
    
    # Accès en lecture de l'horloge
    def getClock(self):
        # Délégation à Com
        return self.com.getClock()

    # Ajout du broadcastMessage
    def broadcast(self, payload):
        # délégation à Com
        self.com.broadcast(payload)

    # Ajout de sendTo
    def sendTo(self, payload, to):
        # délégation à Com
        self.com.sendTo(payload, to)

    # Renvoi l'ID du voisin suivant sur l'anneau
    def nextId(self):
        return (self.myId + 1) % self.npProcess

    # Envoi du jeton au prochain
    def sendToken(self, to_id: int):
        send_clock = self.incrementClock()
        tm = TokenMessage(send_clock, self.myProcessName, to_id)
        print(f"[{self.getName()}][TOKEN-SEND] to=P{to_id} clock={tm.getClock()} sender={tm.getSender()}")
        PyBus.Instance().post(tm)
    
    # Demander le jeton
    def request(self):
        self.waiting = True
        print(f"[{self.getName()}][REQUEST] J'attends le jeton...")

        # bloquer jusqu'au jeton
        self.token_event.wait()
        self.token_event.clear()
        print(f"[{self.getName()}][ENTER] J'entre en SC")
    
    # Relacher le jeton
    def release(self):
        if not self.holding_token:
            return
        print(f"[{self.getName()}][EXIT] Je sors de la SC")
        self.waiting = False
        self.holding_token = False
        self.sendToken(self.nextId())

    # Méthode de synchronisation
    def synchronize(self):
        print(f"[{self.getName()}][SYNC] Demande de synchronisation...")
        # Je m'ajoute comme prête sans écraser ce qui est déjà arrivé
        with self.sync_lock:
            self.sync_seen.add(self.myProcessName)
            count = len(self.sync_seen)
            if count >= self.npProcess:
                self.sync_event.set()

        # J'annonce aux autres que je suis prêt
        self.broadcast({"type": "SYNC"})

        # J'attends les autres
        while self.alive and not self.sync_event.is_set():
            self.sync_event.wait(timeout=0.1)
        
        if self.sync_event.is_set():
            print(f"[{self.getName()}][SYNC] Barrière franchie")


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
        if isinstance(payload, dict) and payload.get("type") == "ACK-SYNC":
            # c'est un ACK de synchro -> passe par le communicateur
            print(f"[{self.getName()}][SYNC-ACK-RECV] de {event.getSender()}")
            self.com.handle_ack()
            return # pas de mise en boîte aux lettres
        
        # Traitement normal
        updated = self.updateClockOnReceive(event.getClock())
        print(f"[{self.getName()}][RECV-TO] from={event.getSender()} to={event.getTo()} msg={payload} msgClock={event.getClock()} -> localClock={updated} (thread={threading.current_thread().name})")
        self.com.enqueue_incoming(event)

    @subscribe(threadMode = Mode.PARALLEL, onEvent=TokenMessage)
    def onToken(self, event):
        # Seul le destinataire traite le message
        if event.getTo() != self.myId:
            return
        updated = self.updateClockOnReceive(event.getClock())
        print(f"[{self.getName()}][TOKEN-RECV] from={event.getSender()} -> localClock={updated}")

        if self.waiting:
            # ce processus garde le jeton
            self.holding_token = True
            self.token_event.set()  # pour reveiller request
            print(f"[{self.getName()}][TOKEN-HELD] je garde le jeton pour la SC")
        else:
            # ce processus relaye le jeton
            if self.alive:
                sleep(0.5)
                self.sendToken(self.nextId())

    def run(self):
        loop = 0
        while self.alive:

            # Horloge locale
            local_clock = self.incrementClock()
            print(f"[{self.getName()}][LOOP {loop}] localClock={local_clock}")
            sleep(1)

            # Synchronisation des processus au tour 2 avec le middleware
            if self.myProcessName == "P0" and loop == 2:
                self.com.broadcastSync("Hello everyone, sync time!", from_id=0, my_id=self.myId, npProcess=self.npProcess)

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
                self.request()
                sleep(2)  # simulation de travail en SC
                self.release()

            # Exemple : P2 demande la SC après 6 tours
            if self.myProcessName == "P2" and loop == 6:
                self.request()
                sleep(2)
                self.release()

        
            loop+=1
        print(self.getName() + " stopped")

    def stop(self):
        self.alive = False
        # Débloquer toute attente éventuelle
        #self.token_event.set()
        #self.sync_event.set()

    def waitStopped(self):
        self.join()
