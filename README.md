<div align="center">

# Mav

**A personal AI companion — Telegram bot + web dashboard, installed in one command.**

Talk to it, it acts, it remembers, it watches things for you.

`curl -fsSL https://raw.githubusercontent.com/SoaOaoS/mav/main/get.sh | sudo bash`

**Website & docs:** <https://soaoaos.github.io/mav/> ·
[documentation](https://soaoaos.github.io/mav/docs.html)

</div>

Mav is made of two pieces that work together:

- **the Telegram bot** — you talk to it, it acts on your machine, it remembers,
  it watches sources and pings you when something changes;
- **the web dashboard** — the same brain with an interface: reports, infra
  status, memory, and push notifications.

Under the hood it uses **opencode** as the agent engine and **Postgres** for
memory. You bring your own model: **Ollama** (local), **Claude**, **OpenAI**, or
any OpenAI-compatible endpoint.

## Features

- **Chat** on Telegram and in the dashboard, routed through your own agent.
- **Persistent memory** — past exchanges, durable facts and preferences are
  stored in Postgres and injected back into new sessions.
- **Watch** — poll web pages, mailboxes, GitHub repos, Proxmox VMs, service
  health, or stock levels, and alert only when something actually changes.
- **Scheduled jobs** — run prompts on a schedule (cron-like), with retries.
- **Web Push** — get notified outside the app, and tap a notification to open a
  chat that explains the alert in detail.
- **RAG** — index documents and retrieve relevant excerpts into context.
- **Self-service config** — edit your agent's `AGENTS.md`, create your own
  **agents**, and manage your **MCP servers** right from the dashboard, with a
  live engine status indicator and a one-click **Restart engine** to apply
  changes.
- **An orchestrator built in** — a default agent that analyses a request,
  convenes the right specialists, has them challenge each other, then
  synthesises a single answer.

## Installation

**One-liner** (downloads the repo and runs the wizard):

```bash
curl -fsSL https://raw.githubusercontent.com/SoaOaoS/mav/main/get.sh | sudo bash
```

Or clone first:

```bash
git clone https://github.com/SoaOaoS/mav.git
cd mav
sudo ./install.sh
```

On a fresh Debian/Ubuntu machine, a wizard walks you through: contact email,
Telegram token, model provider, Postgres, dashboard. Accept the defaults where
it makes sense. Then it does the rest — dependencies, database, certificates,
services.

## Updating

No need to re-answer everything. The installer installs a small `mav` command
and remembers your configuration, so updates are one word:

```bash
mav update        # update the code and services, keep your config
mav reconfigure   # re-run the wizard to change settings
mav status        # show the service status
mav logs          # follow the bot logs
mav uninstall     # remove services, configs and the container
```

Or, from the installer directly:

```bash
sudo ./install.sh --update     # same as `mav update`
```

`--update` reads your existing configuration (`/etc/mav.env`,
`/etc/mav-dashboard.env`, `/etc/mav-server.env`) and **asks nothing** — it just
refreshes the code, the venvs, the schema and the services.

Even simpler: **just re-run the installer**. If it detects an existing install,
it asks one question — `[U] update it (keep my config)` or `[R] reconfigure from
scratch` — and defaults to updating.

Other modes:

```bash
sudo ./install.sh --yes        # all defaults, no questions
sudo ./install.sh --dry-run    # show what would happen, change nothing
sudo ./install.sh --uninstall  # remove services, configs and container
```

In `--yes` mode you can supply values via environment variables (handy for
automation): `MAV_TELEGRAM_TOKEN`, `MAV_ALLOWED_CHAT_IDS`, `MAV_PROVIDER`,
`MAV_OPENCODE_MODEL`, `MAV_API_BIND`, `MAV_POSTGRES_PASSWORD`, and so on.

> The installer is **idempotent**: run it again to upgrade without breaking an
> existing install.

## What the installer does

1. Checks the system and installs dependencies (python, docker, openssl, …).
2. Creates the system user that runs the bot (defaults to your current user).
3. Copies the bot and the dashboard into place.
4. Creates the Python venvs and installs dependencies.
5. Starts **Postgres** (Docker) and applies the **schema** (memory, watch, RAG,
   notifications).
6. Generates the dashboard **TLS certificates** and the **VAPID keys** (push).
7. Writes the configuration files (`/etc/mav.env`, `/etc/mav-dashboard.env`).
8. Installs and starts the **three systemd services**.
9. Health-checks the engine and the dashboard.

## Architecture

```
                    ┌─────────────────────┐
   Telegram  ─────► │  mav-bot            │ ──┐
   (bot)            │  bridge + watch/jobs│   │
                    └─────────────────────┘   │
                                              ▼
                    ┌─────────────────────┐  ┌──────────────────┐
   Browser  ──────► │  mav-dashboard      │─►│  opencode serve  │
   (VPN)            │  UI + /api/*        │  │  (engine, :4096) │
                    └─────────────────────┘  └──────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │  Postgres (Docker)  │  memory, watch, RAG, notifs
                    └─────────────────────┘
```

Three systemd services:

| Service         | Role                               |
| --------------- | ---------------------------------- |
| `mav-server`    | opencode engine (`127.0.0.1:4096`) |
| `mav-bot`       | Telegram bridge + watch + jobs     |
| `mav-dashboard` | web interface (HTTP/HTTPS)         |

## Supported providers

The wizard lets you pick:

| Provider      | What you need                    | Model (example)             |
| ------------- | -------------------------------- | --------------------------- |
| **ollama**    | a running Ollama (local/remote)  | `llama3.1`, `qwen2.5-coder` |
| **anthropic** | an `ANTHROPIC_API_KEY`           | `claude-sonnet-4-5`         |
| **openai**    | an `OPENAI_API_KEY`              | `gpt-4o`                    |
| **custom**    | OpenAI-compatible endpoint + key | depends on your provider    |

## What you configure yourself

The installer writes a minimal opencode config
(`~/.config/opencode/opencode.json`) with your provider and model, and stores
your API key in the engine's environment. Everything else — custom agents, MCP
servers, skills — stays in your hands, under `~/.config/opencode/`. Mav runs on
_your_ agent.

## Useful commands

```bash
systemctl status mav-bot mav-dashboard      # status
journalctl -u mav-bot -f                     # bot logs
journalctl -u mav-dashboard -f               # dashboard logs
```

Bot commands (on Telegram): `/ask`, `/new`, `/agent`, `/stop`, `/memory`,
`/jobs`, `/run <name>`, `/watch`, `/rag`, `/notify`.

## Repository layout

```
mav/
├── get.sh                  # "curl | bash" bootstrap
├── install.sh              # the unified installer (the wizard)
├── scripts/schema.sql      # full database schema
├── systemd/                # the 3 service templates
├── bot/                    # the Telegram bot (oc*.py)
├── dashboard/              # the web dashboard (front + server/)
└── examples/               # optional example scripts
```

## Manual configuration (without the installer)

The installer writes two files:

- `/etc/mav.env` — bot: Telegram token, chat ids, engine, Postgres, watch.
- `/etc/mav-dashboard.env` — dashboard: IP/ports, TLS, database, chat binding.

Their variables are documented inline after generation.

## License

MIT — see [LICENSE](LICENSE).
