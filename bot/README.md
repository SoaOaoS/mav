# opencode-bot

Pont **opencode ↔ Telegram** : posez une question depuis Telegram, opencode
répond avec progression en direct, mémoire inter-sessions et exécutions
programmées.

## Fonctionnalités

- **Questions** : `/ask <question>` ou simplement écrire un message
- **Progression en direct** : statut mis à jour pendant la réponse
- **Mémoire inter-sessions** : les échanges pertinents sont rappelés
- **Pièces jointes** : photos et documents envoyés à opencode
- **Jobs planifiés** : exécutions programmées poussées vers Telegram
- **Débats multi-agents** : `/debate <question>`
- **Sécurité** : allowlist des chats autorisés

## Commandes

| Commande             | Description                             |
| -------------------- | --------------------------------------- |
| `/ask <question>`    | Poser une question                      |
| `/new`               | Nouvelle session                        |
| `/agent [nom]`       | Afficher / changer d'agent              |
| `/stop`              | Interrompre la tâche en cours           |
| `/memory`            | État de la mémoire                      |
| `/forget`            | Effacer la mémoire du chat              |
| `/clear`             | Effacer les messages du bot (allowlist) |
| `/jobs`              | Lister les exécutions programmées       |
| `/run <nom>`         | Déclencher un job                       |
| `/debate <question>` | Lancer un débat multi-agents            |
| `/id`                | Identifiant du chat                     |

## Installation

```bash
git clone <repo-url>
cd opencode-bot
sudo ./install.sh
```

Le script installe les dépendances, copie les fichiers, crée le fichier de
config et démarre le service systemd.

## Configuration

Copiez `.env.example` vers `/etc/opencode-bot.env` (fait par le script) et
remplissez :

```bash
TELEGRAM_TOKEN=            # token du bot (via @BotFather)
ALLOWED_CHAT_IDS=          # chats autorisés, séparés par des virgules
OPENCODE_URL=http://127.0.0.1:4096/
OPENCODE_MODEL=<provider>/<modele>
OPENCODE_AGENT=research
ANSWER_MODE=last
PLAIN_TEXT_IS_ASK=1
STATE_FILE=/home/USER/bot/sessions.json
SHOW_PROGRESS=1
IDLE_TIMEOUT=1800
MEMORY=1
MEMORY_TOP=3
BOT_DIR=/home/USER/bot
CLEAR_ALLOWED_CHAT_IDS=
```

## Prérequis

- Un serveur **opencode** qui tourne (`opencode serve`, par défaut sur
  `http://127.0.0.1:4096`) — le script installe le service `opencode-server`
- Python 3.10+
- Un token de bot Telegram (via [@BotFather](https://t.me/BotFather))

## Services systemd

Le script installe deux services :

- **`opencode-server`** — le serveur headless opencode sur `127.0.0.1:4096`
  (fichier : `systemd/opencode-server.service`)
- **`opencode-bot`** — le pont Telegram, qui dépend d'opencode-server
  (fichier : `systemd/opencode-bot.service`)

```bash
systemctl status opencode-server
systemctl status opencode-bot
journalctl -u opencode-bot -f
```

## Structure

```
opencode_bot.py     # bot principal (pont Telegram <-> opencode)
ocbus.py            # bus d'événements SSE
ocformat.py         # rendu markdown -> HTML Telegram
ocjobs.py           # planificateur de jobs
ocmemory.py         # mémoire inter-sessions
ocnotify.py         # notifications proactives (Web Push + historique/dédup)
ocprogress.py       # suivi de progression
ocwatch.py          # veille continue (alerte sur changement d'état)
ocrag.py            # recherche plein-texte (RAG)
monitor_sls.py      # script de monitoring (exemple)
biotech_brief.py    # collecte de données biotech (Yahoo, openFDA, ClinicalTrials)
jobs.json           # exemples de jobs planifiés
install.sh          # script d'installation
.env.example        # modèle de configuration
systemd/            # fichiers de services systemd
```
