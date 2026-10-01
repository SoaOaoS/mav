# Mav bot

The **opencode ↔ Telegram** bridge: ask a question from Telegram, opencode
answers with live progress, cross-session memory and scheduled runs.

> This module is part of the [Mav](../README.md) project. In a full Mav install
> the top-level `install.sh` sets everything up; the details below are for
> running the bot on its own.

## Features

- **Questions**: `/ask <question>` or just send a message
- **Live progress**: status updated while the answer streams in
- **Cross-session memory**: relevant past exchanges are recalled
- **Attachments**: photos and documents forwarded to opencode
- **Scheduled jobs**: recurring prompts pushed to Telegram
- **Multi-agent debates**: `/debate <question>`
- **Security**: allowlist of authorized chats

## Commands

| Command              | Description                           |
| -------------------- | ------------------------------------- |
| `/ask <question>`    | Ask a question                        |
| `/new`               | New session                           |
| `/agent [name]`      | Show / switch agent                   |
| `/stop`              | Abort the current task                |
| `/memory`            | Memory status                         |
| `/forget`            | Clear the chat's memory               |
| `/clear`             | Delete the bot's messages (allowlist) |
| `/jobs`              | List scheduled jobs                   |
| `/run <name>`        | Trigger a job                         |
| `/watch`             | Manage watch items                    |
| `/rag`               | Full-text document search/index       |
| `/notify`            | Toggle push / Telegram notifications  |
| `/debate <question>` | Start a multi-agent debate            |
| `/id`                | Chat identifier                       |

## Configuration

The bot reads environment variables (in a full install these live in
`/etc/mav.env`). See [`.env.example`](.env.example) for the full list. The
essentials:

```bash
TELEGRAM_TOKEN=            # bot token (from @BotFather)
ALLOWED_CHAT_IDS=          # allowed chats, comma-separated
OPENCODE_URL=http://127.0.0.1:4096/
OPENCODE_MODEL=<provider>/<model>
OPENCODE_AGENT=            # empty = opencode default
STATE_FILE=/home/USER/bot/sessions.json
BOT_DIR=/home/USER/bot
PG_DSN=host=127.0.0.1 port=5432 user=mav password=CHANGE_ME dbname=mav
```

## Requirements

- A running **opencode** server (`opencode serve`, default
  `http://127.0.0.1:4096`)
- Python 3.10+
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- Postgres (for memory, watch, RAG, notifications) — optional but recommended

## systemd services

The top-level installer sets up three services; the bot is one of them:

- **`mav-server`** — the headless opencode engine on `127.0.0.1:4096`
- **`mav-bot`** — the Telegram bridge, depends on `mav-server`
- **`mav-dashboard`** — the web interface

```bash
systemctl status mav-bot
journalctl -u mav-bot -f
```

## Structure

```
opencode_bot.py     # main bot (Telegram <-> opencode bridge)
ocbus.py            # SSE event bus
ocformat.py         # markdown -> Telegram HTML rendering
ocjobs.py           # job scheduler
ocmemory.py         # cross-session memory
ocnotify.py         # proactive notifications (Web Push + history/dedup)
ocprogress.py       # progress tracking
ocwatch.py          # continuous watch (alerts on state change)
ocrag.py            # full-text search (RAG)
jobs.json           # scheduled jobs (empty by default)
requirements.txt    # Python dependencies
.env.example        # configuration reference
```
