"""Incoming events: let the outside world wake Mav up.

A routine can subscribe to events instead of (or as well as) a schedule:

    { "name": "pr review", "on_event": { "kind": "github", "contains": "opened" }, … }

Events are pushed to ``POST /api/hooks/<kind>`` (optionally guarded by a token
stored in the ``hooks.token`` preference) and stored in Postgres. The worker
reads the unconsumed ones on each tick, fires every routine whose ``on_event``
matches, then marks the event consumed.

Like the rest of the worker, everything is best-effort: without Postgres the
events fall back to a small JSON file so a home install without Docker still
works. The matching logic is pure and unit-tested.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("ocevents")

BOT_DIR = Path(os.environ.get("BOT_DIR", Path(__file__).resolve().parent))
EVENTS_FILE = Path(os.environ.get("EVENTS_FILE", BOT_DIR / "events.json"))
PG_DSN = os.environ.get(
    "PG_DSN",
    "host=127.0.0.1 port=5432 user=mav password=mav_secret dbname=mav",
)

# Keep at most this many events in the JSON fallback.
MAX_FILE_EVENTS = 200

__all__ = [
    "KINDS", "ensure_schema", "push", "pending", "consume", "matches", "kind_of",
]

# The kinds offered in the UI. Free-form kinds are still accepted (a "custom"
# webhook can send anything), this list is only for the picker and docs.
KINDS = ("github", "calendar", "form", "payment", "iot", "custom")


def kind_of(event: dict) -> str:
    return str((event or {}).get("kind") or "").strip().lower()


def matches(job: dict, event: dict) -> bool:
    """True when `job` wants to run on this `event`.

    `on_event` may be a string (the kind) or a block:
        {"kind": "github", "contains": "opened", "negate": false}
    A job without `on_event` never matches. An empty `kind` matches any event.
    """
    want = job.get("on_event")
    if not want:
        return False
    if isinstance(want, str):
        want = {"kind": want}
    if not isinstance(want, dict):
        return False
    wkind = str(want.get("kind") or "").strip().lower()
    ekind = kind_of(event)
    if wkind and wkind != "any" and wkind != ekind:
        return False
    needle = want.get("contains")
    if not needle:
        return True
    hay = json.dumps(event.get("payload") or {}) + " " + str(event.get("source") or "")
    found = str(needle).lower() in hay.lower()
    return (not found) if want.get("negate") else found


# ------------------------------------------------------------------ storage
# Postgres when available, else a JSON file. The API writes, the worker reads.

_pg = None


def _connect():
    global _pg
    try:
        import psycopg2  # noqa: PLC0415

        _pg = psycopg2.connect(PG_DSN, connect_timeout=3)
        _pg.autocommit = True
    except Exception:  # noqa: BLE001
        _pg = None
    return _pg


def _pg_get():
    global _pg
    if _pg is None:
        _connect()
    if _pg is not None:
        try:
            _pg.cursor().execute("SELECT 1")
        except Exception:  # noqa: BLE001
            _connect()
    return _pg


def ensure_schema() -> None:
    pg = _pg_get()
    if pg is None:
        return
    try:
        pg.cursor().execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id        bigserial PRIMARY KEY,
                ts        bigint NOT NULL,
                kind      text,
                source    text,
                payload   jsonb,
                consumed  boolean DEFAULT false
            )
            """
        )
        pg.cursor().execute(
            "CREATE INDEX IF NOT EXISTS events_pending_idx ON events (consumed, id)"
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("events schema: %s", exc)


# ------------------------------------------------------------- JSON fallback
def _read_file() -> list[dict]:
    try:
        data = json.loads(EVENTS_FILE.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_file(events: list[dict]) -> None:
    try:
        EVENTS_FILE.write_text(json.dumps(events[-MAX_FILE_EVENTS:], indent=1))
    except Exception:
        pass


# ------------------------------------------------------------------ public
def push(kind: str, payload: dict | None = None, source: str = "") -> int | None:
    """Record an incoming event. Returns its id (or None on failure)."""
    kind = (kind or "custom").strip().lower()[:60]
    payload = payload if isinstance(payload, dict) else {}
    pg = _pg_get()
    if pg is not None:
        try:
            cur = pg.cursor()
            cur.execute(
                "INSERT INTO events (ts, kind, source, payload, consumed) "
                "VALUES (%s, %s, %s, %s, false) RETURNING id",
                (int(time.time()), kind, source[:200], json.dumps(payload)[:20000]),
            )
            row = cur.fetchone()
            return row[0] if row else None
        except Exception as exc:  # noqa: BLE001
            log.warning("storing event failed, using file: %s", exc)
    events = _read_file()
    eid = (events[-1]["id"] + 1) if events else 1
    events.append({"id": eid, "ts": int(time.time()), "kind": kind,
                   "source": source[:200], "payload": payload, "consumed": False})
    _write_file(events)
    return eid


def pending(limit: int = 50) -> list[dict]:
    """Unconsumed events, oldest first."""
    pg = _pg_get()
    if pg is not None:
        try:
            cur = pg.cursor()
            cur.execute(
                "SELECT id, ts, kind, source, payload FROM events "
                "WHERE NOT consumed ORDER BY id LIMIT %s",
                (limit,),
            )
            return [
                {"id": r[0], "ts": r[1], "kind": r[2], "source": r[3], "payload": r[4]}
                for r in cur.fetchall()
            ]
        except Exception:  # noqa: BLE001
            pass
    return [e for e in _read_file() if not e.get("consumed")][:limit]


def consume(event_id: int) -> None:
    pg = _pg_get()
    if pg is not None:
        try:
            pg.cursor().execute("UPDATE events SET consumed = true WHERE id = %s", (event_id,))
            return
        except Exception:  # noqa: BLE001
            pass
    events = _read_file()
    for e in events:
        if e.get("id") == event_id:
            e["consumed"] = True
    _write_file(events)


def recent(limit: int = 30) -> list[dict]:
    """Latest events, for the dashboard."""
    pg = _pg_get()
    if pg is not None:
        try:
            cur = pg.cursor()
            cur.execute(
                "SELECT id, ts, kind, source, payload, consumed FROM events "
                "ORDER BY id DESC LIMIT %s",
                (limit,),
            )
            return [
                {"id": r[0], "ts": r[1], "kind": r[2], "source": r[3],
                 "payload": r[4], "consumed": r[5]}
                for r in cur.fetchall()
            ]
        except Exception:  # noqa: BLE001
            pass
    return list(reversed(_read_file()))[:limit]
