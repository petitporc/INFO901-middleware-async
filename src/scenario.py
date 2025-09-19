from threading import Thread
from time import sleep

def play_demo(proc):
    """
    Rejoue exactement le scénario de démonstration avec l'instance de Process `proc`.
    """
    com = proc.com
    ProcClass = proc.__class__  # accès à _token_lock / _token_started

    # --- ÉTAPE 0 --- : REGISTER + Barrière globale
    com.register()  # ID stocké dans le communicateur

    proc._log("BARRIER", "Attente de REGISTER de tous les processus")
    com.synchronize(proc.npProcess)
    proc._log("BARRIER", "REGISTER de tous les processus OK")

    # Heartbeats (idempotent)
    com._start_heartbeats()

    # --- ÉTAPE 1 --- : Dernier processus démarre le jeton
    if com.getMyId() == proc.npProcess - 1:
        def _delayed_start():
            from time import sleep as _sleep
            _sleep(0.2)
            with ProcClass._token_lock:
                if not ProcClass._token_started:
                    proc._log("TOKEN", "Dernier processus lance le jeton")
                    com.sendToken(to_id=0)
                    ProcClass._token_started = True
        Thread(target=_delayed_start, daemon=True).start()

    # Petite marge pour laisser circuler le jeton
    sleep(0.3)

    # --- ÉTAPE 2 --- : Démo asynchrone (P1 envoie)
    if proc.myProcessName == "P1":
        com.broadcast({"type": "greeting", "text": "Hello je broadcast !"})
        com.sendTo({"type": "greeting", "text": "Hello je sendTo P0 !"}, to=0)
        com.publish({"type": "greeting", "text": "Hello je publish !"})

    sleep(0.3)

    # --- ÉTAPE 3 --- : Barrière 2 pour aligner tout le monde en synchro
    proc._log("BARRIER", "Préparation broadcastSync")
    com.synchronize(proc.npProcess)
    proc._log("BARRIER", "broadcastSync OK")

    # --- ÉTAPE 4 --- : Diffusion synchrone (ACK de tous requis)
    if proc.myProcessName == "P0":
        com.broadcastSync("Hello, synchronize time !", from_id=0, my_id=com.getMyId())

    sleep(0.3)

    # --- ÉTAPE 5 --- : Synchro point à point P0 -> P1
    if proc.myProcessName == "P0":
        proc._log("TEST-SYNC-TO", "sendToSync P0 -> P1")
        com.sendToSync({"type": "test-sync", "text": "Hello je sendToSync P1 !"},
                       to=1, my_id=com.getMyId())

    if proc.myProcessName == "P1":
        proc._log("TEST-SYNC-FROM", "receiveFromSync P1 <- P0")
        msg = com.receiveFromSync(from_id=0, timeout=5)
        if msg:
            proc._log("TEST-SYNC-FROM", f"reçu de P0 -> {msg.getPayload()}")
        else:
            proc._log("TEST-SYNC-FROM", "timeout en attente de P0")

    # --- ÉTAPE 6 --- : Section critique (anneau à jeton)
    if proc.myProcessName == "P1":
        sleep(0.2)
        com.requestSC()
        sleep(1.0)
        com.releaseSC()

    if proc.myProcessName == "P2":
        sleep(1.2)
        com.requestSC()
        sleep(1.0)
        com.releaseSC()

    # Laisser finir les ACK éventuels
    sleep(0.5)
