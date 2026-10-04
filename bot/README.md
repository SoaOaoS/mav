# Mav worker

The background half of Mav: it runs **scheduled jobs** and the **continuous
watch**, and reaches you with **Web Push** notifications. Conversations happen
in the [dashboard](../dashboard/README.md).

> This module is part of the [Mav](../README.md) project. In a full install the
> top-level `install.sh` sets everything up and runs it as the `mav-worker`
> systemd service.

## What it does

- **Scheduled jobs** (`jobs.json`, editable from the dashboard → Automations):
  at a fixed time on given days, or every N minutes, with automatic retries.
  Each run gets its own `job-<name>` session, so its report shows up in the
  dashboard's *Job results*, and a short summary is pushed to your devices.
- **Watch**: web pages, GitHub repos, Proxmox VMs, service health and stock
  levels. It only alerts when the state actually changes (deduplicated, quiet
  hours respected).
- **Memory** (`ocmemory.py`): the Postgres-backed memory shared with the
  dashboard — exchanges and durable facts, recalled at the start of a new
  conversation.

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
mav_worker.py       # entry point: scheduler + watch loop
ocbus.py            # SSE event bus (follows engine sessions)
ocjobs.py           # job scheduler
ocmemory.py         # memory on Postgres (shared with the dashboard)
ocnotify.py         # Web Push + notification history/dedup
ocprogress.py       # session progress tracking
ocwatch.py          # continuous watch (alerts on state change)
ocrag.py            # full-text document search (RAG)
jobs.json           # scheduled jobs (empty by default)
```
