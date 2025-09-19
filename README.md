# Middleware distribué — Lamport, BAL, Sync & SC par jeton

> TP : middleware de communication inter-processus en Python  
> Horloge de Lamport • BAL • Envois async/sync • Barrière • Section critique par anneau à jeton • REGISTER auto • Heartbeats & vues

---

## 📦 Contenu du dépôt

- `Com.py` — Communicateur (bus, horloge, BAL, sync, SC, heartbeats, REGISTER)
- `Process.py` — Thread applicatif, façade vers `Com`
- `scenario.py` — Scénario de démonstration end-to-end
- `MessageBase.py` — Classe de base des messages
- `Message.py`, `BroadcastMessage.py`, `MessageTo.py`, `TokenMessage.py` — Types de messages
- `Launcher.py` — Point d’entrée pour lancer N processus
- `Sujet.pdf` — Énoncé du TP

---

## ✅ Prérequis

- **Python 3.10+** (recommandé)
- Dépendances :
  ```bash
  pip install pyeventbus3
  ```
  > Le reste utilise uniquement la bibliothèque standard.

---

## ▶️ Lancer la démo

Depuis la racine du projet :

```bash
python Launcher.py
```

Par défaut, **N = 3** processus (`P0`, `P1`, `P2`) exécutent le scénario :
1. **REGISTER** → attribution d’IDs par ordre d’arrivée, puis **barrière**.
2. **Heartbeats** (émission & surveillance en tâche de fond).
3. **Démarrage du jeton** par le dernier processus.
4. **Envois asynchrones** (depuis `P1`) : `broadcast`, `sendTo`, `publish`.
5. **Barrière** puis **broadcastSync** (ACK de tous requis).
6. **sendToSync** `P0 → P1` (et `receiveFromSync` côté `P1`).
7. **Section critique** : `P1` puis `P2` demandent/obtiennent/libèrent le jeton.
8. **Arrêt propre**.

> 💡 Pour changer **N**, ouvrez `Launcher.py` et modifiez la création des `Process(...)`.

---

## 🖥️ Logs attendus (exemples)

- Envoi async :  
  `"[COM P1][SEND] broadcast payload=..."`

- Réception + Lamport :  
  `"[COM P0][RECEIVE] ... clock=6 -> local=7"`

- Barrière :  
  `"[COM P0][SYNC] Tous les SYNC reçus, barrière franchie"`

- Diffusion synchrone :  
  `"[COM P0][SYNC-BROADCAST] ACK reçu de P1"` puis `"... Tous les ACK reçus"`

- Section critique :  
  `"[COM P2][SC-REQUEST] ..."` → `"[COM P2][SC-ENTER] ..."` → `"[COM P2][SC-EXIT] ..."`

- Jeton :  
  `"[COM P0][TOKEN] Token reçu de P2 -> waiting=False"`

---

## 🔧 Paramètres utiles

- **Intervalle heartbeat** : `HEARTBEAT_INTERVAL` dans `Com.py` (par défaut `0.5 s`)
- **Timeout heartbeat** : `HEARTBEAT_TIMEOUT` (par défaut `2.0 s`)
- **Temporisations de la démo** : `sleep(...)` dans `scenario.py`

---

## 🧠 Concepts (vue d’ensemble)

- **Horloge de Lamport**  
  À l’envoi : `clock += 1`  
  À la réception d’un message *utilisateur* : `clock = max(local, reçu) + 1`  
  *(Les messages système, ex. jeton, n’affectent pas l’horloge.)*

- **BAL (boîte aux lettres)**  
  Les handlers déposent les messages reçus dans une `Queue` locale.

- **Synchronisation**  
  - `synchronize(N)` : barrière (attend un SYNC de chaque pair).  
  - `broadcastSync(data)` : le diffuseur attend un **ACK** de tous.  
  - `sendToSync(payload, to)` / `receiveFromSync(from)` : rendez-vous bloquant P2P.

- **Section critique (anneau à jeton)**  
  Un **seul jeton** circule. `requestSC()` bloque jusqu’au jeton, `releaseSC()` le passe au **voisin suivant**.

- **Numérotation automatique (REGISTER)**  
  Chaque processus diffuse sa présence au démarrage ; l’ID est attribué **par ordre d’arrivée** (tie-break sur le nom).  
  Aucune **variable de classe** pour ce mécanisme.

- **Vues & heartbeats**  
  Heartbeats réguliers ; si un pair est muet > `HEARTBEAT_TIMEOUT`, on recalcule une **vue des vivants** et on **réattribue les IDs** dans l’ordre d’arrivée initial, puis on diffuse la nouvelle vue.

---

## 🧪 Checklist de validation

- **REGISTER** : log `ordre d'arrivée=[...] -> mon ID=k`
- **Barrières** : `Tous les SYNC reçus, barrière franchie`
- **broadcastSync** : `ACK reçu de Px` pour tous les autres, puis `Tous les ACK reçus`
- **sendToSync/receiveFromSync** : message reçu côté destinataire + ACK côté émetteur
- **SC** : `SC-REQUEST` → `SC-ENTER` → `SC-EXIT`
- **Heartbeats** : flux `heartbeat reçu de Px`

---

## 🧯 Dépannage

- **Bloqué au REGISTER**  
  Vérifiez que **N** processus sont lancés et que `npProcess` correspond.

- **Barrière qui ne passe pas**  
  Un processus n’a peut-être pas envoyé son SYNC (cherchez `[SYNC] j'envoi SYNC`).

- **ACK manquants en broadcastSync**  
  Assurez-vous que REGISTER est terminé avant l’appel (IDs disponibles pour adresser les ACK).

- **SC qui n’avance pas**  
  Personne ne libère le jeton ? Regardez `SC-EXIT` et les logs `[TOKEN]`.

- **Heartbeats après arrêt**  
  Normal si les threads ne s’arrêtent pas exactement au même instant (brève latence résiduelle).

---

## 📚 API (survol)

```python
# Asynchrone
com.publish(payload)
com.broadcast(payload)
com.sendTo(payload, to)

# Barrière
com.synchronize(N)

# Synchrone
com.broadcastSync(data, from_id, my_id)
com.sendToSync(payload, to, my_id)
msg = com.receiveFromSync(from_id, timeout=None)

# Section critique par jeton
com.requestSC()
# ... section critique ...
com.releaseSC()
```

---

## 🧱 Limites (démo pédagogique)

- Pas de gestion de **partitions réseau** (vue locale simple)
- Jeton **unique** (un seul détenteur)
- **Volatile** (pas de persistance)
- Pas d’authentification/sécurité

---

## 📝 Licence

Projet pédagogique – libre d’utilisation pour l’apprentissage.  
Basé sur **pyeventbus3** et la bibliothèque standard Python.
