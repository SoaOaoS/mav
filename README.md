# ============================================================================

# Mav

#

# Un compagnon IA personnel : un bot Telegram, un dashboard web, une mémoire

# persistante, une veille automatique et des notifications. Tout s'installe

# en une commande.

# ============================================================================

Mav, c'est deux morceaux qui bossent ensemble :

- **le bot Telegram** — tu lui parles, il agit, il retient, il surveille ;
- **le dashboard web** — la même chose en interface, avec les rapports, l'état
  de l'infra, la mémoire et les notifications push.

Le tout s'appuie sur **opencode** comme moteur d'agent et **Postgres** pour la
mémoire. Tu choisis ton modèle : **Ollama** (local), **Claude**, **OpenAI**, ou
n'importe quel endpoint compatible OpenAI.

## Installation

**En une ligne** (télécharge et lance l'assistant) :

```bash
curl -fsSL https://raw.githubusercontent.com/SoaOaoS/mav/main/get.sh | sudo bash
```

Ou, si tu préfères cloner d'abord :

```bash
git clone https://github.com/SoaOaoS/mav.git
cd mav
sudo ./install.sh
```

Sur une machine Debian/Ubuntu fraîche, un assistant te guide : identité, token
Telegram, moteur opencode, Postgres, dashboard, comportement du bot. Tu peux
tout valider par défaut là où c'est possible. Puis il fait le reste —
dépendances, base, certificats, services.

Autres modes :

```bash
sudo ./install.sh --yes        # tout par défaut, sans question
sudo ./install.sh --dry-run    # montre ce qui serait fait, ne touche à rien
sudo ./install.sh --uninstall  # retire services, configs et conteneur
```

En mode `--yes`, tu peux fournir les valeurs par variables d'environnement
(pratique pour automatiser) : `MAV_TELEGRAM_TOKEN`, `MAV_ALLOWED_CHAT_IDS`,
`MAV_OPENCODE_MODEL`, `MAV_API_BIND`, `MAV_POSTGRES_PASSWORD`, etc.

> L'installeur est **idempotent** : tu peux le relancer pour mettre à jour
> sans rien casser.

## Ce que l'installeur fait

1. Vérifie le système et installe les dépendances (python, docker, openssl…).
2. Crée l'utilisateur système du bot (par défaut : ton utilisateur courant).
3. Copie le bot et le dashboard aux bons endroits.
4. Crée les environnements Python et installe les dépendances.
5. Lance **Postgres** (Docker) et applique le **schéma** (mémoire, veille, RAG,
   notifications).
6. Génère les **certificats TLS** du dashboard et les **clés VAPID** (push).
7. Écrit les fichiers de configuration (`/etc/mav.env`,
   `/etc/mav-dashboard.env`).
8. Installe et démarre les **trois services** systemd.
9. Vérifie que le moteur et le dashboard répondent.

## Architecture

```
                    ┌─────────────────────┐
   Telegram  ─────► │  mav-bot            │ ──┐
   (bot)            │  pont + veille/jobs │   │
                    └─────────────────────┘   │
                                              ▼
                    ┌─────────────────────┐  ┌──────────────────┐
   Navigateur ────► │  mav-dashboard      │─►│  opencode serve  │
   (VPN)            │  UI + /api/*        │  │  (moteur, :4096) │
                    └─────────────────────┘  └──────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │  Postgres (Docker)  │  mémoire, veille, RAG, notifs
                    └─────────────────────┘
```

Trois services systemd :

| Service         | Rôle                               |
| --------------- | ---------------------------------- |
| `mav-server`    | moteur opencode (`127.0.0.1:4096`) |
| `mav-bot`       | pont Telegram + veille + jobs      |
| `mav-dashboard` | interface web (HTTP/HTTPS)         |

## Ce que tu configures toi-même

**L'agent opencode.** L'installeur écrit une config minimale
(`~/.config/opencode/opencode.json`) avec ton provider et ton modèle, et pose
ta clé API dans l'env du service. Le reste — agents personnalisés, MCP, skills —
reste à ta main, dans `~/.config/opencode/`. Mav fonctionne avec _ton_ agent.

## Providers supportés

Le wizard te laisse choisir :

| Provider      | Ce qu'il te faut                     | Modèle (exemple)            |
| ------------- | ------------------------------------ | --------------------------- |
| **ollama**    | Ollama qui tourne (local ou distant) | `llama3.1`, `qwen2.5-coder` |
| **anthropic** | une clé `ANTHROPIC_API_KEY`          | `claude-sonnet-4-5`         |
| **openai**    | une clé `OPENAI_API_KEY`             | `gpt-4o`                    |
| **custom**    | endpoint compatible OpenAI + clé     | selon ton fournisseur       |

## Licence

MIT — voir [LICENSE](LICENSE).

## Commandes utiles

```bash
systemctl status mav-bot mav-dashboard      # état
journalctl -u mav-bot -f                     # logs du bot
journalctl -u mav-dashboard -f               # logs du dashboard
```

Commandes du bot (sur Telegram) : `/ask`, `/new`, `/agent`, `/stop`,
`/memory`, `/jobs`, `/run <nom>`, `/watch`, `/rag`, `/notify`.

## Structure du dépôt

```
mav/
├── get.sh                  # bootstrap « curl | bash »
├── install.sh              # l'installeur unifié (le wizard)
├── scripts/schema.sql      # schéma complet de la base
├── systemd/                # templates des 3 services
├── bot/                    # le bot Telegram (oc*.py)
└── dashboard/              # le dashboard web (front + server/)
```

## Configuration manuelle (sans l'installeur)

L'installeur écrit deux fichiers :

- `/etc/mav.env` — bot : token Telegram, chat ids, moteur, Postgres, veille.
- `/etc/mav-dashboard.env` — dashboard : IP/ports, TLS, base, rattachement.

Les variables sont documentées directement dans ces fichiers après génération.
