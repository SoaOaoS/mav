<div align="center">

# Mav

**Your everyday AI assistant — proactive, private, on your own machine, with your own model.**

Chat like ChatGPT. Then let it work for you: routines that run on their own,
pages and prices it keeps an eye on, and a memory of what matters to you.

`curl -fsSL https://raw.githubusercontent.com/SoaOaoS/mav/main/get.sh | sudo bash`

**Website & docs:** <https://soaoaos.github.io/mav/> ·
[documentation](https://soaoaos.github.io/mav/docs.html)

</div>

## What it does

- **Chat** — a clean, ChatGPT-style web app (installable on your phone).
  Chats are titled automatically and grouped by day; type `/` for commands.
- **Helpers** — you talk to the **Assistant** by default. It calls in the
  **Researcher** (web, facts, comparisons), **Writer** (messages, emails),
  **Planner** (days, trips, to-dos) or **Money** (budgets, purchases) when
  useful — or you pick one yourself. You always see who is answering.
- **Memory** — Mav learns facts about you and recalls them, and relevant past
  chats, in new conversations. See, add and delete everything on the Memory
  page, or type `/remember …` in a chat. Stored in Postgres on your machine.
- **Routines** — "every morning at 7, tell me if I need an umbrella". Create
  them from a simple form, with `/routine`, or just say it in a chat and
  confirm. Each routine has its own chat you can open and follow up in, and
  you get a push notification when it has something for you.
- **Keep an eye on** — a web page, a product price (optionally only below a
  target), or a news topic. Alerts only when something actually changes.
- **For you** — the new-chat screen shows your latest routine reports and
  alerts, each with *Tell me more*.
- **Your model** — Anthropic, OpenAI, Ollama (local or cloud), OpenRouter or
  any OpenAI-compatible API. Switch anytime from Settings → Model: no terminal.
- **Connections** — plug in other apps and services (calendar, notes, files…)
  through the MCP standard, from Settings → Connections.

## Install

On a Debian/Ubuntu machine (a home server, a mini PC, a VPS):

```bash
curl -fsSL https://raw.githubusercontent.com/SoaOaoS/mav/main/get.sh | sudo bash
```

or

```bash
git clone https://github.com/SoaOaoS/mav.git && cd mav && sudo ./install.sh
```

The setup asks only what it must:

1. **Your model provider** (arrow keys), your **API key** — checked live — and
   the **model**, picked from the provider's own list. Or *set it up later* in
   the dashboard.
2. Optionally, a **contact email** for push notifications.

Everything else gets sensible defaults (an *Advanced settings?* prompt lets
you change the user, ports and quiet hours). Then it installs and starts
everything; details go to `/var/log/mav-install.log`. Open the address it
prints, and say hello.

## Manage it

```bash
mav update        # download the latest version, keep your settings
mav reconfigure   # change the model, or re-run the setup
mav restart       # restart the assistant
mav status        # services
mav logs          # follow the logs
mav uninstall     # remove the services (your data is kept)
```

Unattended install: `sudo ./install.sh --yes` with `MAV_PROVIDER`
(`anthropic`, `openai`, `ollama`, `ollama-cloud-api`, `openrouter`),
`MAV_PROVIDER_APIKEY`, `MAV_OPENCODE_MODEL`, and optionally
`MAV_PROVIDER_BASEURL`, `MAV_VAPID_EMAIL`. `--dry-run` shows what would happen.

## How it works

```
   Browser / phone (PWA)
          │
          ▼
   ┌──────────────────┐      ┌──────────────────────┐
   │  mav-dashboard   │ ───► │  mav-server          │
   │  web app + API   │      │  opencode agent      │
   └──────────────────┘      │  engine (:4096)      │
          │                  └──────────────────────┘
          │                            ▲
          ▼                            │
   ┌──────────────────┐      ┌──────────────────────┐
   │  Postgres        │ ◄─── │  mav-worker          │
   │  memory, alerts  │      │  routines, watching, │
   └──────────────────┘      │  push notifications  │
                             └──────────────────────┘
```

| Service         | Role                                                    |
| --------------- | ------------------------------------------------------- |
| `mav-dashboard` | the web app and its API                                 |
| `mav-server`    | the agent engine ([opencode](https://opencode.ai))      |
| `mav-worker`    | runs routines and "keep an eye on", sends notifications |

Everything runs on your machine. The only thing that leaves it is what you send
to the model provider you chose — or nothing at all with a local Ollama.

## Upgrading from the Telegram version

Telegram support was removed: Mav is now a web app (installable on your phone)
with push notifications. Older versions of `mav update` only reinstalled the
local copy, so run the one-line installer once
(`curl -fsSL https://raw.githubusercontent.com/SoaOaoS/mav/main/get.sh | sudo bash`)
and choose **Update**; from then on `mav update` downloads new versions by
itself. The update migrates for you — it replaces the
`mav-bot` service with `mav-worker`, keeps your memory (it now lives in
Postgres; the old `memory.json` is imported automatically), your routines, your
model and your settings. Helper files you already had in
`~/.config/opencode/agent/` are left untouched; the new everyday helpers are
added next to them.

## Repository

```
mav/
├── get.sh              # "curl | bash" bootstrap
├── install.sh          # the setup wizard
├── agents/             # the everyday helpers (Assistant, Researcher, …)
├── bot/                # mav-worker: routines, watching, memory, notifications
├── dashboard/          # the web app (front-end + server/)
├── scripts/schema.sql  # database schema
├── systemd/            # service templates
└── docs/               # website and documentation
```

Hacking on the web app without a model: run
`python3 dashboard/tools/fake_engine.py` and point the dashboard at it with
`OPENCODE_URL=http://127.0.0.1:4096` (see [dashboard/README.md](dashboard/README.md)).

## License

MIT — see [LICENSE](LICENSE).
