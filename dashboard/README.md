# Mav web app

The ChatGPT-style interface of **Mav**, your everyday assistant: chat with
helpers, routines, "keep an eye on", memory and settings — plus the small
Python server behind it.

> Part of the [Mav](../README.md) project. A full install is handled by the
> top-level `install.sh`; this page is for running or hacking on the web app.

## Run it locally (no model needed)

```bash
# 1. a fake agent engine with canned answers
# ("research …" prompts — or all, with --multi-step — answer in several
#  steps, word by word, like a turn that calls a helper)
python3 dashboard/tools/fake_engine.py --port 4096 &

# 2. the web app (Postgres optional: without it, memory is disabled)
cd dashboard/server
OPENCODE_URL=http://127.0.0.1:4096 MAV_STATIC="$PWD/.." BOT_DIR=/tmp/mav \
  MAV_API_PORT=8787 MAV_API_BIND=127.0.0.1 python3 mav_api.py
# → http://127.0.0.1:8787
```

Opened without the server (e.g. from GitHub Pages), the app falls back to a
**demo mode** with sample data.

## Screens

- **Chat** (the main screen). A new chat shows a greeting, a centred message
  box, four everyday suggestions and **For you**: the latest routine reports
  and alerts, each with _Tell me more_. Chats are titled automatically after
  the first answer, grouped by day in the sidebar, and can be renamed (click
  the title), pinned, summarised, exported or deleted.
- **Who you talk to** is shown on the message box, in the header and on every
  answer, and remembered per chat. Switching mid-chat adds a divider.
- **Routines**: create from a form (what, when — every day / some days /
  every few hours —, which helper), from `/routine`, or by accepting the
  _Make this a routine?_ card that appears when you write things like "every
  morning…". Each routine has its own chat. Second tab: **Keep an eye on**
  (a page, a price — optionally below a target —, or a news topic).
- **Memory**: facts about you (add / delete) and remembered past chats.
- **Settings**: Model (provider, key check, model list), Custom instructions,
  Helpers, Connections (MCP), General (notifications, read-aloud, theme) and
  _Advanced_ (assistant status and restart, file locations, raw JSON).

Shortcuts: `⌘K` search & commands, `Alt+N` new chat, `/` focus the message
box, `Esc` stop. Commands: `/new`, `/helper`, `/remember`, `/routine`,
`/watch`, `/rename`, `/summary`, `/export`, `/help`.

## Server (`server/mav_api.py`)

Python stdlib HTTP server + `psycopg2` + `pywebpush`. It serves the front-end,
talks to the opencode engine, and reads/writes Postgres.

- Chats are opencode sessions titled `dash: …`; their helper, pin and title
  lock live in `BOT_DIR/dash_sessions.json`.
- Routine chats are titled `dash: Routine · <name>` — the worker posts
  scheduled runs there, the dashboard posts _Run now_ runs there.
- An answer runs server-side, detached from the browser (`/api/runs`); a tab
  that comes back, or a connection that drops, resumes it from its cursor.
  The server follows the engine's `/event` stream (polling only as a
  fallback), and a turn the engine stored as several steps — tools, helpers —
  is shown as **one** message, exactly as it was streamed.
- Titles and learned facts are produced after the answer, in one model call,
  queued until no answer is running — never competing with the next reply.
- Memory (facts + exchanges) is injected as a hidden part when a chat starts,
  and each answer is stored (`bot/ocmemory.py`, shared with the worker).
- The model provider is written by `server/mav_provider.py`, the same module
  the installer uses.

| Method   | Route                                                                                | Purpose                                                                          |
| -------- | ------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| GET      | `/api/status`                                                                        | assistant health, model, counters                                                |
| GET      | `/api/stream?prompt=&session=&agent=`                                                | **SSE** answer (`start`, `delta`, `reset`, `tool`, `done`, `error`); `&from=N` resumes |
| GET      | `/api/sessions`, `/api/session?id=`                                                  | chats, one chat's messages (one per turn; `running` = answer in progress) |
| POST     | `/api/session/new` · `rename` · `delete` · `abort` · `summary` · `agent` · `pin`     | chat actions                                                                     |
| GET      | `/api/session/export?id=`                                                            | Markdown export                                                                  |
| GET      | `/api/agents`                                                                        | helpers with descriptions, and the default                                       |
| GET/POST | `/api/jobs`, `/api/job/save` · `delete` · `toggle` · `run`                           | routines                                                                         |
| GET      | `/api/job-results`                                                                   | latest report of each routine                                                    |
| GET/POST | `/api/watch`, `/api/watch/add` · `remove`                                            | keep an eye on (`web`, `price`, `news`)                                          |
| GET/POST | `/api/memory`, `/api/memory/fact/add` · `fact/delete` · `exchange/delete` · `forget` | memory                                                                           |
| GET      | `/api/search?q=`                                                                     | memory + documents                                                               |
| GET      | `/api/notifications`, `/api/notification?id=`                                        | the inbox                                                                        |
| GET/POST | `/api/config/provider`, `/api/config/provider/test`                                  | model provider                                                                   |
| GET/POST | `/api/config/agents`                                                                 | custom instructions (AGENTS.md)                                                  |
| GET/POST | `/api/config/agent-files`, `/api/config/agent-file`, `…/delete`                      | helper files                                                                     |
| GET/POST | `/api/config/mcp`                                                                    | connections (secrets masked)                                                     |
| GET      | `/api/config/mcp/catalog`                                                            | ready-made connections (`mcp-catalog.json`) + whether Node.js / uv are installed |
| POST     | `/api/config/mcp/install`                                                            | add a catalog connection (`{id, values}`)                                        |
| GET      | `/api/version`                                                                       | installed / latest version, `update_available`, release notes                    |
| POST     | `/api/update`, GET `/api/update/status`                                              | run `mav update` in its own systemd unit, follow it                              |
| GET/POST | `/api/config/engine`, `/api/config/restart`                                          | assistant status (incl. `pending` changes) / restart                             |
| POST     | `/api/upload`                                                                        | attachment                                                                       |
| GET      | `/api/chart?symbol=&range=`                                                          | Yahoo Finance series for inline `[[chart:SYM:PERIOD]]`                           |
| GET      | `/api/download?path=`                                                                | download a document/code/archive (see below)                                     |
| GET/POST | `/api/push/key` · `subscribe` · `unsubscribe` · `test` · `ack`                       | Web Push                                                                         |

### Charts and downloadable files in answers

An answer can embed two directives, each on its own line:

- `[[chart:SYMBOL:PERIOD]]` — an interactive sparkline card (Yahoo Finance,
  via the `/api/chart` proxy). `PERIOD` is `1d`, `5d`, `1mo`, `3mo`, `6mo`,
  `1y`, `2y` or `5y`. Example: `[[chart:^GDAXI:1mo]]`.
- `[[file:PATH]]` — a download card pointing at `/api/download`. `PATH` can
  be absolute (within an allowed root) or a bare filename, resolved in the
  media archive, the attachments folder and `tools/` output folders.

`/api/download` serves **any file type** from the same roots as `/api/asset`
(images stay images-only there), so Mav can hand back whatever it produced —
a PDF, a spreadsheet, an archive, a binary… The one exception is **sensitive
files**, which are never served: `.env` (and `*.env`), private keys
(`.pem`, `.key`, `.p12`…), credential/config files (`mail.conf`,
`mav*.env`, `push_subs.json`, `auth.json`, `.netrc`, `.pgpass`…), and any
name containing `secret` / `credential` / `password` / `token` / `apikey`.
Every answer also has a **Download** action in its toolbar that saves the
message as a local `.md` file.

> ⚠️ **No authentication**: keep it on your home network or behind a VPN.

## Install it on a phone (PWA)

The app is installable (manifest, service worker, icons). Browsers require
HTTPS for that, so the server also listens on **:443** with a local
certificate (`certs/`, generated by the installer; only `certs/ca.cer` /
`ca.crt` are ever served):

1. On the phone, open `https://<host>/certs/ca.cer` and trust the certificate.
2. Open `https://<host>/` and "Add to Home Screen".
3. Turn on notifications (bell icon, or Settings → General).

Server variables: `MAV_TLS_PORT`, `MAV_TLS_CERT`, `MAV_TLS_KEY` (empty port =
no HTTPS). `tools/make_certs.sh` regenerates the certificates,
`tools/make_icons.py` the icons.
