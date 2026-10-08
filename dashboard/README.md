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

Opened without the server, the app falls back to a **demo mode** with
sample chats (tool steps included), routines, alerts and memory. Replies are
canned and nothing leaves the browser. This is the public demo at
<https://getmav.dev/demo/>: `scripts/build-demo.sh` copies the
app into `docs/demo/`, and CI fails if that copy is out of date. Run it, and
commit, after any change in `dashboard/`.

## Screens

- **Welcome** (first visit on a fresh install): connect a model, a few facts
  about you (name, city, language, interests, saved as memory), and starter
  routines with the daily briefing. It ends on *Brief me now*. Every step can
  be skipped, and Settings → General → *Welcome setup* reopens it. Installs
  that already have routines or memory are never asked
  (`/api/onboarding`).
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

## Server (`server/`)

Python stdlib HTTP server + `psycopg2` + `pywebpush`. It serves the front-end,
talks to the opencode engine, and reads/writes Postgres. `mav_api.py` is the
entry point and the HTTP handler; the rest is split by area, each name in
exactly one module:

| Module | What it holds |
| --- | --- |
| `mav_core.py` | configuration, optional modules, Postgres/JSON/subprocess helpers |
| `mav_engine.py` | the engine as a service: status, restart, connections (MCP), provider, helper files, versions |
| `mav_routines.py` | routines, schedules, templates, briefing, welcome, actions, keep an eye on, events |
| `mav_store.py` | memory, notifications, drafts, mail, interests, search, usage, channels, calendars, backups |
| `mav_chat.py` | sessions, titles, learned facts, the after-answer queue, messages, uploads |
| `mav_stream.py` | the engine's event stream, the run registry, the streamed answer |
| `mav_media.py` | media archive, assets and downloads, charts, Web Push |
| `mav_auth.py`, `mav_backup.py`, `mav_mail.py`, `mav_provider.py` | sign-in, backup/restore, mail, model providers |

Modules call each other as `mav_chat.session_title(…)`, so circular imports
are safe. `mav_api.<name>` still reaches any name, for reading and for
assigning (tests set `mav_api.JOBS_FILE`), because it forwards to the owner.

The front-end is plain classic scripts in `assets/js/`, loaded in order by
`index.html` and sharing one global scope: `util`, `state`, `chat`, `stream`,
`markdown`, `routines`, `watch`, `settings`, `connections`, `notify`,
`search`, then `app` (start-up, demo, PWA). No bundler.

- Chats are opencode sessions titled `dash: …`; their helper, pin and title
  lock live in `BOT_DIR/dash_sessions.json`.
- Routine chats are titled `dash: Routine · <name>` — the worker posts
  scheduled runs there, the dashboard posts _Run now_ runs there.
- An answer runs server-side, detached from the browser (`/api/runs`); a tab
  that comes back, or a connection that drops, resumes it from its cursor.
  The server follows the engine's `/event` stream (polling only as a
  fallback), and a turn the engine stored as several steps — tools, helpers —
  is shown as **one** message, exactly as it was streamed.
- Tool calls are listed above the answer, one per row, in the order they
  happened. Click a row to see the tool, its status, when it started, how
  long it took, and what went in and came out (`input`, `output`, `error`,
  cut to 4,000 characters). The `tool` SSE event carries these fields, and a
  reloaded chat gets them back in each message's `tools` list.
- Titles and learned facts are produced after the answer, in one model call,
  queued until no answer is running — never competing with the next reply.
- The daily briefing is a routine with `"kind": "briefing"`: when it runs (on
  schedule in the worker, or *Brief me*), `bot/ocbriefing.py` gathers facts,
  the last day's alerts and reports, pending drafts and interests into a
  hidden context; the chat shows only "Brief me on my day.".
- Every answer's `tokens` and `cost` (as the engine reports them) go to
  `BOT_DIR/usage.json` via `bot/ocusage.py` — by the web app (chats,
  background calls) and the worker (routines). A "stop" budget that is used up
  refuses new answers with a clear message; background calls use the
  "background model" when one is set.
- Memory (facts + exchanges) is injected as a hidden part when a chat starts,
  and each answer is stored (`bot/ocmemory.py`, shared with the worker).
- The model provider is written by `server/mav_provider.py`, the same module
  the installer uses.

| Method   | Route                                                                                | Purpose                                                                          |
| -------- | ------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| GET | `/api/usage?days=30` · POST `/api/usage/budget` (`{monthly_usd, action: warn|stop}`) · `/api/usage/small-model` | cost, tokens, budget, background model |
| GET/POST | `/api/briefing` (`{enabled, time}`), POST `/api/briefing/run` | daily briefing settings / brief me now (returns the chat to open) |
| GET/POST | `/api/auth/state` · `setup` · `login` · `logout` · `password` | sign-in (login takes an optional `name`) |
| GET/POST | `/api/family` · `family/add` · `rename` · `password` · `remove` | family accounts (owner only) |
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
| GET/POST | `/api/backup` (download) · `backup/safety` · `backup/restore` (raw .tar.gz + `X-Mav-Password`) | backup and restore (`mav_backup.py`)                                            |
| GET/POST | `/api/calendar` (sources + today) · `calendar/save` · `delete` · `test`         | CalDAV and iCal calendars (`bot/occalendar.py`, secrets masked)                  |
| GET/POST | `/api/channels` · `channels/save` · `delete` · `test` · `public-url`                 | ntfy, Gotify, Discord, Slack (`bot/occhannels.py`, secrets masked)               |

### Charts and downloadable files in answers

An answer can embed two directives, each on its own line:

- `[[chart:SYMBOL:PERIOD]]` — an interactive sparkline card (Yahoo Finance,
  via the `/api/chart` proxy). `PERIOD` is `1d`, `5d`, `1mo`, `3mo`, `6mo`,
  `1y`, `2y` or `5y`. Example: `[[chart:^GDAXI:1mo]]`.
- `[[file:PATH]]` — a download card pointing at `/api/download`. `PATH` can
  be absolute (within an allowed root) or a bare filename, resolved in
  `mav-files/` first, then the media archive, the attachments folder and
  `tools/` output folders.

**Files Mav hands you.** The helpers may write files in one folder only,
`~/workspace/mav-files/` (the engine's working directory; `MAV_FILES`
overrides it). Their `permission.edit` rule denies everything else. Asked for
a CSV, a plan or a letter, Mav writes it there and answers with
`[[file:name]]`. Each shared file is also copied to the media archive, so its
card keeps working after the folder is cleaned.

`/api/download` serves **any file type** from the same roots as `/api/asset`
(images stay images-only there), so Mav can hand back whatever it produced —
a PDF, a spreadsheet, an archive, a binary… The one exception is **sensitive
files**, which are never served: `.env` (and `*.env`), private keys
(`.pem`, `.key`, `.p12`…, SSH keys such as `id_rsa` / `id_ed25519`), credential/config files (`mail.conf`,
`mav*.env`, `push_subs.json`, `auth.json`, `.netrc`, `.pgpass`…), and any
name containing `secret` / `credential` / `password` / `token` / `apikey`.
Every answer also has a **Download** action in its toolbar that saves the
message as a local `.md` file.

### Sign-in

The first visit asks for a password that protects the app; from then on every
`/api/*` call needs the session cookie (HttpOnly, SameSite=Lax, `Secure` over
HTTPS, 30 days). Changing the password signs every other device out. Repeated
wrong passwords are slowed down. Public routes: `/api/auth/*`, `/api/health`
and `/api/hooks/*` (webhooks carry their own token). `sudo mav password` resets
it from the machine; `MAV_AUTH=off` turns sign-in off (only behind your own
authenticating proxy). Stored in `BOT_DIR/auth.json` (PBKDF2-SHA256).

**A model that comes with the plan.** `MAV_MODEL_MANAGED=1` (set by Mav Cloud
for CloudMav) makes the model part of the plan, not a setting: the Model tab,
the background-model setting and the welcome flow's model step are hidden, and
`POST /api/config/provider`, `/api/config/provider/test` and
`/api/usage/small-model` answer 403. `/api/auth/state` carries `model_managed`.

**Running code.** `dashboard/tools/mav_code.py` is a stdio MCP server (the
`code` connection): `run_python`, `run_command`, `write_file`, `read_file`,
`list_files`, `save_to_chat` (a workspace file → `mav-files/`, shown as a
download card) and `load_from_chat`. Self-hosted, the owner turns it on with
`POST /api/config/code {"enabled": true}` (Settings → General): commands run on
this machine in `MAV_CODE_DIR` (default `~/workspace/code`) with secrets
removed from the environment. With `MAV_CODE_URL` and `MAV_CODE_TOKEN` (set by
Mav Cloud) they run in the person's sandbox instead, and the setting is locked.

**Family accounts.** The owner can add people (Settings → General → Family;
`/api/family/*`). Members sign in with their name; their chats, memory,
routines, watch items, notifications and push devices are kept apart (by
`chat_id` in Postgres, an `owner` on each routine, a `user` on each chat and
device). A member reaches only the routes in `MEMBER_GET` / `MEMBER_POST`
(`mav_api.py`); everything else (model, connections, helpers, mail,
interests, calendars, channels, usage, backup, updates) is the owner's.
Removing a member erases their data. Files the assistant writes stay in one
shared workspace.

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
