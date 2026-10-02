# Mav dashboard

The web interface for **Mav**, your personal AI companion. Warm and simple:
talk to it, it remembers, it watches, and it acts in the background.

> This module is part of the [Mav](../README.md) project. A full Mav install is
> handled by the top-level `install.sh`; the details below are for running the
> dashboard on its own.

Two modes:

- **LIVE** — served from your machine, wired to the real agent: jobs, memory
  (Postgres), watch items, service status, and a real chat that runs through a
  dedicated session.
- **MOCK** — automatic fallback if the API is unreachable (e.g. GitHub Pages):
  the UI stays browsable with simulated data.

## Architecture

```
Browser (VPN)
      │
      ▼
mav_api.py  ── HTTP ──►  serves the UI + /api/*
      │
      ├──► opencode serve :4096  (engine, agents, sessions)
      └──► Postgres (Docker)      (conversations, facts, watch_items…)
```

The dashboard uses **its own opencode session** (`dash:` prefix), separate from
the Telegram session, so it never interferes with the bot running alongside.

## Stack

- Front: vanilla HTML / CSS / JS, zero dependencies, zero build.
- Back: Python stdlib (`http.server`) + `psycopg2` + `pywebpush`.
- Deploy: GitHub Pages (mock) or a private machine (live, over VPN).

## Structure

```
.
├── index.html
├── assets
│   ├── css/style.css
│   ├── js/app.js          # live mode + mock fallback
│   └── vendor/            # vendored libs (charts)
├── server/mav_api.py      # backend: UI + /api/*
├── tools/                 # cert / icon generators
├── sw.js                  # service worker (PWA + push)
└── manifest.webmanifest
```

## API

| Method | Route                                                          | Purpose                                   |
| ------ | -------------------------------------------------------------- | ----------------------------------------- |
| GET    | `/api/status`                                                  | engine health, metrics, counters          |
| GET    | `/api/connections`                                             | service status                            |
| GET    | `/api/proxmox`                                                 | Proxmox nodes and VMs                     |
| GET    | `/api/jobs`                                                    | scheduled jobs + last run                 |
| GET    | `/api/job-results`                                             | latest reports produced by jobs           |
| GET    | `/api/memory`                                                  | conversations, facts, preferences         |
| GET    | `/api/search?q=`                                               | memory + document search                  |
| GET    | `/api/watch`                                                   | watch items                               |
| GET    | `/api/notifications`                                           | notification history                      |
| GET    | `/api/notification?id=`                                        | one notification                          |
| GET    | `/api/agents`                                                  | available agents                          |
| GET    | `/api/sessions`                                                | dashboard conversations                   |
| GET    | `/api/session?id=`                                             | messages + title of a conversation        |
| GET    | `/api/session/export?id=`                                      | markdown export                           |
| GET    | `/api/stream`                                                  | **SSE**: streamed answer                  |
| GET    | `/api/push/key`                                                | VAPID public key                          |
| GET    | `/api/chart` / `/api/quotes`                                   | market data                               |
| GET    | `/api/media` / `/api/asset`                                    | media / local files                       |
| GET    | `/api/config`                                                  | agent config snapshot (agents+mcp+engine) |
| GET    | `/api/config/agents`                                           | AGENTS.md content                         |
| GET    | `/api/config/mcp`                                              | MCP servers (secrets masked)              |
| GET    | `/api/config/engine`                                           | engine/service live status                |
| POST   | `/api/ask`                                                     | send a prompt (blocking)                  |
| POST   | `/api/session/new` / `rename` / `delete` / `abort` / `summary` | conversation management                   |
| POST   | `/api/job/toggle` / `/api/job/run`                             | job control                               |
| POST   | `/api/watch/add` / `/api/watch/remove`                         | watch control                             |
| POST   | `/api/upload`                                                  | attachment (base64 → file)                |
| POST   | `/api/push/subscribe` / `unsubscribe` / `test` / `ack`         | push management                           |
| POST   | `/api/config/agents`                                           | save AGENTS.md                            |
| POST   | `/api/config/mcp`                                              | save MCP servers (keeps masked secrets)   |
| POST   | `/api/config/restart`                                          | restart the engine and wait for it        |

### Sessions

Dashboard conversations are opencode sessions whose title starts with `dash: ` —
that prefix tells them apart from Telegram sessions and jobs, with no local
registry. The front end offers a ChatGPT-style manager: create, list, open,
rename, delete.

> ⚠️ **No authentication**: meant for VPN access only. Do not expose it publicly.

## Run locally

Front only (mock):

```bash
python3 -m http.server 8080
```

With the backend (live):

```bash
MAV_STATIC="$PWD" BOT_DIR="$HOME/bot" \
  <venv>/bin/python server/mav_api.py
# http://localhost:8787
```

## Screens

- **Home** — greeting, message bar, shortcuts, today's summary, automations.
- **Conversations** — conversation manager + **streaming** chat with the agent,
  per-conversation agent selector, attachments, stop, summary, markdown export.
- **Automations** — scheduled jobs + actions: run, enable/pause.
- **Memories** — memory (conversations, facts, preferences) + full-text search.
- **Watch** — watched items, add/remove, alert only on change.
- **Infra** — live Proxmox nodes and VMs (CPU, RAM, uptime, status).
- **Settings** — engine live status (online/offline, version, model, agent and
  MCP counts), a markdown editor for **AGENTS.md**, an editor for your **MCP
  servers**, and a **Restart engine** button to apply changes.

## Features

- **SSE streaming**: answers arrive word by word, with tool progress and a stop button.
- **Command palette** (`⌘K` / `Ctrl+K`): find a conversation, a memory, an action.
- **Voice**: dictation (Web Speech) and read-aloud of answers.
- **Web Push**: Mav pushes watch alerts to your phone, app closed. Tapping a
  notification opens a chat that explains the alert.
- **Global search** across memory and indexed documents.
- **Export / summary** of a conversation.

## Design

iOS-style "glass" styling: frosted-glass surfaces (`backdrop-filter`), animated
color halos in the background, soft shadows. Automatic fallback to an opaque
background when `backdrop-filter` is unsupported.

## PWA (install on mobile)

The app is installable: `manifest.webmanifest`, service worker (`sw.js`), icons
and an install banner.

**Constraint**: the service worker and installability require a **secure
context** (HTTPS, or `localhost`). Over plain HTTP on an IP, Chrome does not
expose `navigator.serviceWorker` and install is not offered.

- **GitHub Pages mock**: already HTTPS → installable directly.
- **Live on a LAN**: HTTP on an IP → you need the local TLS described below.

### Local TLS

The service listens on **HTTP :80** _and_ **HTTPS :443** with a local
certificate (`certs/`, not committed). Only the public CA `certs/ca.crt` is ever
served.

To install on your phone (once on the LAN):

1. Open `https://<host>/certs/ca.crt` and approve the certificate.
2. Open `https://<host>/`, then "Add to Home Screen".

Server env vars: `MAV_TLS_PORT`, `MAV_TLS_CERT`, `MAV_TLS_KEY`
(set `MAV_TLS_PORT=0` to disable TLS).

### Regenerate the certificate

```bash
python3 tools/make_icons.py          # icons
tools/make_certs.sh                  # CA + server cert (adjust SAN IP/DNS)
```
