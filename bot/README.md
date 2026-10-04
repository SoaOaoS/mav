# Mav worker

The background half of Mav: it runs **routines** and **keeps an eye on**
things, and reaches you with **Web Push** notifications. Conversations happen
in the [web app](../dashboard/README.md).

> This module is part of the [Mav](../README.md) project. In a full install the
> top-level `install.sh` sets everything up and runs it as the `mav-worker`
> systemd service.

## What it does

- **Routines** (`jobs.json`, managed from the web app → Routines): at a time
  on given days, every few hours, on fixed days of the month or the last day
  of the month, or triggered by an event, with one automatic retry. Create
  them from a ready-made template, or by just saying "every morning…" in a
  chat (English, French or Spanish — `ocroutine_nl.py`). Each run happens in
  the routine's own chat (`Routine · <name>`) with what Mav remembers about
  you; a short summary is pushed to your devices and lands in _For you_.
- **Conditions** (`occonditions.py`): a routine can carry a `skip_if` block,
  so "only tell me if it's going to rain" costs nothing when there's nothing
  to say. Skipped before the model is even called.
- **Events** (`ocevents.py`): the outside world can wake Mav up. A webhook
  (`POST /api/hooks/event`) records an event; every routine with a matching
  `on_event` runs.
- **Keep an eye on**: a web page (text changes), a price on a product page
  (any change, or below a target) and news topics (Google News). Alerts only
  when something actually changes — deduplicated, quiet hours respected.
- **Priorities** (`ocpriority.py`): every alert is ranked
  critical/important/useful/fyi. Below the user's proactivity level it is not
  pushed but collected, then sent as one daily recap (`DIGEST_HOUR`).
- **Drafts & actions** (`ocdrafts.py`, `ocactions.py`): Mav proposes
  ready-to-send replies and runs long tasks in the background, delivering the
  result later — both surfaced in the web app.
- **Memory** (`ocmemory.py`): the Postgres-backed memory shared with the web
  app — facts about you and past exchanges.

## Configuration

Environment variables (in a full install: `/etc/mav.env`). See
[`.env.example`](.env.example) for the full list. The essentials:

```bash
OPENCODE_URL=http://127.0.0.1:4096
OPENCODE_MODEL=<provider>/<model>
MAV_CHAT_ID=0              # owner id: memory/watch items are attached to it
BOT_DIR=/home/USER/bot     # data folder (jobs.json, push subscriptions, keys)
PG_DSN=host=127.0.0.1 port=5432 user=mav password=CHANGE_ME dbname=mav
```

## Run

```bash
systemctl status mav-worker
journalctl -u mav-worker -f
```

## Structure

```
mav_worker.py       # entry point: routines scheduler + watch loop
ocbus.py            # SSE event bus (follows engine sessions)
ocjobs.py           # routines scheduler
ocmemory.py         # memory on Postgres (shared with the dashboard)
ocnotify.py         # Web Push + notification history/dedup
ocprogress.py       # session progress tracking
ocwatch.py          # keep an eye on: page, price, news
ocrag.py            # full-text document search (RAG)
jobs.json           # routines (empty by default)
```
