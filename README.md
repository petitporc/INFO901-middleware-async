# INFO901-middleware-async
Middleware distribué (Lamport, BAL, sync, SC par jeton)

🎯 Objectif
Ce TP implémente un middleware de communication inter-processus en Python :
Horloge de Lamport (ordre partiel des événements),
BAL (boîte aux lettres) pour la réception asynchrone,
Envois asynchrones : publish, broadcast, sendTo,
Envois synchrones : broadcastSync (ACK de tous), sendToSync / receiveFromSync,
Section critique distribuée via anneau à jeton,
Numérotation automatique (REGISTER) par ordre d’arrivée,
Heartbeats & vue distribuée avec re-numérotation si un pair disparaît.

🧩 Contenu
Com.py : communicateur (toute la logique réseau/middleware)
Process.py : thread applicatif, façade vers Com
scenario.py : scénario de démonstration end-to-end
Message*.py : types de messages (MessageBase, Message, BroadcastMessage, MessageTo, TokenMessage)
Launcher.py : point d’entrée pour démarrer N processus (démonstration)
Sujet.pdf : énoncé du TP

✅ Prérequis
Python 3.10+ (recommandé)
Dépendances :
pip install pyeventbus3
(tout le reste est standard library)

▶️ Lancer la démo
Depuis la racine du projet :
python Launcher.py
Par défaut, N=3 processus (P0, P1, P2) exécutent le scénario suivant :
REGISTER → chacun diffuse sa présence, puis une barrière pour s’aligner,
Heartbeats (émis/surveillés en tâche de fond),
Démarrage du jeton par le dernier processus,
Envois asynchrones (depuis P1) : broadcast, sendTo, publish,
Barrière puis broadcastSync (P0 envoie; attend les ACK de tous),
sendToSync P0→P1 (P1 attend avec receiveFromSync),
Section critique (SC) : P1 puis P2 demandent le jeton, entrent en SC, ressortent,
Arrêt propre.
Pour changer N : ouvre Launcher.py et ajuste le nombre de Process(...).

🖥️ Ce que vous verrez dans la console
Exemple de logs significatifs :
[COM P1][SEND] broadcast payload=... → envoi asynchrone,
[COM P0][RECEIVE] ... → réception (mise à jour Lamport indiquée),
[COM P0][SYNC] ... / Tous les SYNC reçus, barrière franchie → barrière,
[COM P0][SYNC-BROADCAST] ... / ACK reçu de ... → diffusion synchrone,
[COM P2][SC-REQUEST] ... / [COM P2][SC-ENTER] ... → section critique,
[COM P0][TOKEN] ... → réception / conservation du jeton.

🔧 Paramètres & variations utiles
Nombre de processus (N) : modifie la création dans Launcher.py.
Temporisations du scénario : dans scenario.py (les sleep(...) structurent la démo).
Intervalle heartbeat : HEARTBEAT_INTERVAL dans Com.py (par défaut 0.5 s).
Timeout heartbeat : HEARTBEAT_TIMEOUT (par défaut 2.0 s).
Ordre d’arrivée / IDs : calculé après REGISTER ; affiché dans les logs.

🧠 Concepts clés (très bref)
Horloge de Lamport : à l’envoi, clock+=1 ; à la réception d’un message utilisateur, clock=max(local, reçu)+1.
Les messages système (ex. jeton) n’affectent pas l’horloge.
BAL : chaque réception passe par une queue locale consommée par le processus.
Sync :
synchronize(N) = barrière (attend un SYNC de chaque pair),
broadcastSync(data) = le diffuseur attend un ACK de tous,
sendToSync(payload, to) ∥ receiveFromSync(from) = rendez-vous bloquant P2P.
SC par jeton : un seul jeton circule ; requestSC() attend le jeton ; releaseSC() passe au suivant.
Vue distribuée : heartbeats réguliers ; si un pair est muet > timeout → vue recalculée et IDs re-attribués selon l’ordre d’arrivée initial.

🧪 Comment valider que “ça marche”
REGISTER : vérifiez un log ordre d'arrivée=['P0','P1','P2'] -> mon ID=....
Barrières : cherchez Tous les SYNC reçus, barrière franchie.
Sync Diffusion : ACK reçu de P1, ACK reçu de P2, puis Tous les ACK reçus.
Sync P2P : côté P1, un log receiveFromSync puis le message reçu.
SC : SC-REQUEST → SC-ENTER → SC-EXIT (avec passages de jeton).
Heartbeats : heartbeat reçu de Px en continu tant que tout vit.

🧯 Dépannage
Rien ne s’affiche / bloqué au REGISTER
Assurez-vous que N processus sont bien lancés et que npProcess correspond.
Barrière qui ne passe pas
Un processus n’a peut-être pas envoyé son SYNC (regarder les logs [SYNC] j'envoi SYNC).
ACK manquants en broadcastSync
Vérifiez que la phase REGISTER est terminée (les IDs sont connus) avant d’appeler broadcastSync.
SC qui n’avance pas
Personne ne libère le jeton ? Regarder SC-EXIT et les logs [TOKEN].
Beaucoup de heartbeats après l’arrêt
Normal si tout le monde ne s’arrête pas exactement au même moment.

🧱 Limites (dans cette démo)
Pas de tolérance aux partitions réseau (vue simple via heartbeats locaux),
Jeton unique (un seul détenteur possible),
Pas de persistance disque (tout est en mémoire),
Pas de sécurité/authentification (démo pédagogique).

📚 API (survol minimal pour l’utilisateur avancé)
Asynchrone :
com.publish(payload) | com.broadcast(payload) | com.sendTo(payload, to)
Synchrone :
com.synchronize(N) | com.broadcastSync(data, from_id, my_id) |
com.sendToSync(payload, to, my_id) | com.receiveFromSync(from_id, timeout=None)
SC par jeton :
com.requestSC() → section critique → com.releaseSC()

🧾 Licence & crédits
Projet pédagogique — utilisation libre pour l’apprentissage.
Implémentation basée sur pyeventbus3 et la bibliothèque standard Python.
