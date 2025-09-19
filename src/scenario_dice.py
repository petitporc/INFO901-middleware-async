
# Scenario de démonstration: jeu de dés synchronisé par jeton
# Montre REGISTER + barrière, broadcast/publish/sendTo, sendToSync/receiveFromSync,
# broadcastSync (annonce démarrage), et section critique par anneau à jeton.
#
# Utilisation:
#   python scenario_dice.py
#
# Remarque: s'appuie sur vos classes Com/Process/Message* existantes.

import random
import threading
import time

from Com import Com
from pyeventbus3.pyeventbus3 import PyBus, Mode, subscribe

TARGET = 20

class DiceProcess(threading.Thread):
    def __init__(self, name, np):
        super().__init__(name=f"Dice-{name}")
        self.name_str = name
        self.np = np
        self.com = Com(self.name_str, np)
        self.score = 0
        self.winner_announced = False
        self.alive = True
        PyBus.Instance().register(self, self)
        self.start()

    def log(self, *a):
        print(f"[DICE][{self.name}]", *a)

    def run(self):
        # 1) REGISTER + barrière
        self.com.register()
        self.com.synchronize(self.np)

        my_id = self.com.getMyId()

        # 2) Exemple point-à-point sync P0 -> P1 (ping/ack)
        if my_id == 0 and self.np >= 2:
            self.log("sendToSync ping -> P1")
            self.com.sendToSync({"type":"ping"}, to=1, my_id=my_id)
        if my_id == 1:
            # attente d'un ping venant de P0
            msg = self.com.receiveFromSync(from_id=0, timeout=5)
            self.log("receiveFromSync de P0:", msg.getPayload() if msg else "timeout")

        # 3) Le leader P0 annonce le début de partie en diffusion synchrone
        if my_id == 0:
            self.com.broadcastSync("START GAME", from_id=0, my_id=my_id)

        # 4) Boucle de jeu: on utilise la SC distribuée (jeton) pour protéger un lancer
        #    Chaque détenteur du jeton:
        #      - entre en SC
        #      - lance le dé (1..6)
        #      - publie son nouveau score
        #      - s'il atteint TARGET -> annonce la victoire en broadcastSync et stoppe
        #      - sort de SC (le jeton passe au voisin)
        start = time.time()
        while self.alive and (time.time()-start) < 30:  # garde-fou 30s
            # on attend notre tour (SC via jeton)
            self.com.requestSC()
            if not self.alive:  # arrêt demandé pendant l'attente
                break
            roll = random.randint(1, 6)
            self.score += roll
            self.com.publish({"type":"roll","by":self.name_str,"roll":roll,"score":self.score})

            if self.score >= TARGET and not self.winner_announced:
                # annonce synchrone: tout le monde reçoit puis ACK
                self.com.broadcastSync({"type":"winner","name":self.name_str,"score":self.score}, from_id=my_id, my_id=my_id)
                self.winner_announced = True
                self.alive = False

            # libère la SC -> jeton passe au suivant
            self.com.releaseSC()
            time.sleep(0.2)

        # arrêt propre
        self.com.stop()

    # Abonnement aux messages publish pour afficher les lancers
    @subscribe(threadMode=Mode.PARALLEL, onEvent=__import__("Message").Message)
    def onPublish(self, event):
        pl = event.getPayload()
        if isinstance(pl, dict) and pl.get("type") == "roll":
            print(f"[DICE][EVT] {pl['by']} a fait {pl['roll']} (score={pl['score']})")

def main():
    N = 3
    procs = [DiceProcess(f"P{i}", N) for i in range(N)]
    # Donne le jeton initial à P0 après REGISTER (lorsque P0 l'obtiendra il réveillera sa SC)
    # Ici on attend un peu, puis on envoie le jeton à P0 si personne ne l'a fait.
    time.sleep(1.0)
    procs[-1].com.sendToken(0)

    # Laisse tourner la partie et stoppe à la première annonce de victoire
    deadline = time.time() + 30
    while time.time() < deadline and any(p.is_alive() for p in procs):
        time.sleep(0.5)
        # si l'un a posé winner_announced, on arrête les autres
        winners = [p for p in procs if p.winner_announced]
        if winners:
            for p in procs:
                p.alive = False
            break
    for p in procs:
        p.join(timeout=2)

if __name__ == "__main__":
    main()
