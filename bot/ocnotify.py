"""Proactive notifications for Mav — Web Push + history/dedup.

Goal: let the worker (watch, jobs) *reach out* to the user, not only reply.
One logic, two uses:

  - watch  (ocwatch): alert when a state changes;
  - jobs   (run_job): short summary when a report is ready.

VAPID keys and subscriptions are the same as the dashboard's
(~/bot/vapid_private.pem, ~/bot/push_subs.json): a subscription taken in the
web UI therefore also serves the bot.

Postgres serves two purposes:
  - `notifications` table: history (future notification center);
  - deduplication: the same `dedup_key` not redelivered within a window.

Everything is optional and silent: without Postgres or without a subscriber,
it never crashes — it simply does not send.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("ocnotify")

BOT_DIR = Path(os.environ.get("BOT_DIR", Path(__file__).resolve().parent))
PUSH_FILE = Path(os.environ.get("PUSH_FILE", BOT_DIR / "push_subs.json"))
VAPID_PEM = BOT_DIR / "vapid_private.pem"

PG_DSN = os.environ.get(
    "PG_DSN",
    "host=127.0.0.1 port=5432 user=mav password=mav_secret dbname=mav",
)

# Default anti-duplicate window (seconds): 6 h.
DEDUP_WINDOW = int(os.environ.get("NOTIFY_DEDUP_WINDOW", "21600"))

# Quiet hours: no notification between QUIET_START and QUIET_END (local time).
# Format "23-7". Use "0-0" to disable.
_q = os.environ.get("NOTIFY_QUIET", "23-7")
try:
    _qs, _qe = (int(x) for x in _q.split("-", 1))
except Exception:  # noqa: BLE001
    _qs, _qe = 23, 7
QUIET_START, QUIET_END = _qs, _qe

# VAPID contact (required by the Web Push protocol): set by
# the installer via MAV_VAPID_SUB, otherwise a neutral value.
_VAPID_SUB = os.environ.get("MAV_VAPID_SUB") or "mailto:admin@localhost"
_vapid_obj = None


# --------------------------------------------------------------- postgres
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
    """Create the history table if needed (idempotent)."""
    pg = _pg_get()
    if pg is None:
        log.info("notifications: Postgres unavailable, history disabled")
        return
    try:
        cur = pg.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id        bigserial PRIMARY KEY,
                ts        bigint NOT NULL,
                chat_id   bigint,
                topic     text,
                title     text,
                body      text,
                dedup_key text,
                channels  text[],
                delivered boolean DEFAULT true
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS notifications_ts_idx ON notifications (ts DESC)"
        )
        cur.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS link text")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS notifications_dedup_idx "
            "ON notifications (dedup_key, ts DESC)"
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("notifications schema: %s", exc)


# ------------------------------------------------------------- preferences
def _pref(chat_id: int | None, key: str, default: str = "on") -> str:
    if chat_id is None:
        return default
    pg = _pg_get()
    if pg is None:
        return default
    try:
        cur = pg.cursor()
        cur.execute(
            "SELECT value FROM preferences WHERE chat_id = %s AND key = %s",
            (chat_id, key),
        )
        row = cur.fetchone()
        return (row[0] if row else default) or default
    except Exception:  # noqa: BLE001
        return default


def push_enabled(chat_id: int | None) -> bool:
    return _pref(chat_id, "notify.push", "on") != "off"


def proactivity(chat_id: int | None) -> str:
    """How chatty the user wants Mav: quiet | normal | chatty."""
    val = (_pref(chat_id, "notify.proactivity", "normal") or "normal").strip().lower()
    return val if val in ("quiet", "normal", "chatty") else "normal"


def set_preference(chat_id: int, key: str, value: str) -> None:
    pg = _pg_get()
    if pg is None:
        return
    try:
        cur = pg.cursor()
        cur.execute(
            "INSERT INTO preferences (chat_id, key, value, ts) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (chat_id, key) DO UPDATE SET value = EXCLUDED.value, ts = EXCLUDED.ts",
            (chat_id, key, value, int(time.time())),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("notify preference: %s", exc)


# --------------------------------------------------------------- quiet hours
def in_quiet_hours(now: time.struct_time | None = None) -> bool:
    if QUIET_START == QUIET_END:
        return False
    h = (now or time.localtime()).tm_hour
    if QUIET_START < QUIET_END:
        return QUIET_START <= h < QUIET_END
    # range spanning midnight (e.g. 23 -> 7)
    return h >= QUIET_START or h < QUIET_END


# ----------------------------------------------------------------- dedup
def _seen_recently(dedup_key: str, window: int) -> bool:
    pg = _pg_get()
    if pg is None or not dedup_key:
        return False
    try:
        cur = pg.cursor()
        cur.execute(
            "SELECT 1 FROM notifications WHERE dedup_key = %s AND ts > %s LIMIT 1",
            (dedup_key, int(time.time()) - window),
        )
        return cur.fetchone() is not None
    except Exception:  # noqa: BLE001
        return False


def _record(chat_id, topic, title, body, dedup_key, channels, delivered, link=None) -> int | None:
    """Record a notification in the history (the dashboard inbox). Returns its id."""
    pg = _pg_get()
    if pg is None:
        return None
    try:
        cur = pg.cursor()
        cur.execute(
            "INSERT INTO notifications (ts, chat_id, topic, title, body, dedup_key, channels, delivered, link) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (int(time.time()), chat_id, topic, title, body, dedup_key, channels, delivered, link),
        )
        row = cur.fetchone()
        return row[0] if row else None
    except Exception as exc:  # noqa: BLE001
        log.warning("recording notification: %s", exc)
        return None


def _update_record(nid: int, channels, delivered) -> None:
    pg = _pg_get()
    if pg is None or nid is None:
        return
    try:
        pg.cursor().execute(
            "UPDATE notifications SET channels = %s, delivered = %s WHERE id = %s",
            (channels, delivered, nid),
        )
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------- push
def _subs() -> list[dict]:
    try:
        data = json.loads(PUSH_FILE.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_subs(subs: list[dict]) -> None:
    try:
        PUSH_FILE.write_text(json.dumps(subs))
    except Exception:
        # The dashboard (root) sometimes owns the file: do not insist.
        pass


def _vapid():
    """Vapid signer object (loaded once)."""
    global _vapid_obj
    if _vapid_obj is None:
        from py_vapid import Vapid01  # noqa: PLC0415

        _vapid_obj = Vapid01.from_pem(VAPID_PEM.read_bytes())
    return _vapid_obj


def send_push(title: str, body: str, url: str = "./") -> int:
    """Send to all subscribers; drop the truly dead ones. 0 if none."""
    subs = _subs()
    if not subs or not VAPID_PEM.exists():
        return 0
    try:
        from pywebpush import webpush, WebPushException  # noqa: PLC0415
    except Exception:
        log.warning("pywebpush missing: push disabled")
        return 0
    try:
        vapid = _vapid()
    except Exception as exc:  # noqa: BLE001
        log.warning("unreadable VAPID key: %s", exc)
        return 0
    payload = json.dumps({"title": title, "body": body, "url": url})
    sent, alive = 0, []
    for s in subs:
        try:
            webpush(
                subscription_info=s,
                data=payload,
                vapid_private_key=vapid,
                vapid_claims={"sub": _VAPID_SUB},
                ttl=86400,  # FCM garde le message 24 h si l'appareil dort
                headers={"Urgency": "high"},  # wake the device
                timeout=15,
            )
            sent += 1
            alive.append(s)
        except WebPushException as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            # 404/410 = expired subscription (permanent). Anything else = transient:
            # keep the subscriber and retry later.
            if code in (404, 410):
                log.info("expired push subscription (removed): %s", code)
            else:
                log.warning("push failed (code %s): %s", code, str(exc)[:200])
                alive.append(s)
        except Exception as exc:  # noqa: BLE001
            log.warning("unexpected push error: %s", str(exc)[:200])
            alive.append(s)
    if len(alive) != len(subs):
        _write_subs(alive)
    return sent


# --------------------------------------------------------------- digest
# Alerts below the user's proactivity bar are not pushed; they are collected and
# sent as one digest (see flush_digest), so "more proactive" never means
# "more noise".


def collect(chat_id, topic, title, body, level) -> None:
    pg = _pg_get()
    if pg is None:
        return
    try:
        pg.cursor().execute(
            "INSERT INTO notify_digest (ts, chat_id, topic, title, body, level, sent) "
            "VALUES (%s, %s, %s, %s, %s, %s, false)",
            (int(time.time()), chat_id, topic, title[:200], body[:2000], level),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("digest collect: %s", exc)


def digest_pending(chat_id) -> list[dict]:
    pg = _pg_get()
    if pg is None:
        return []
    try:
        cur = pg.cursor()
        cur.execute(
            "SELECT ts, topic, title, body, level FROM notify_digest "
            "WHERE NOT sent AND chat_id IS NOT DISTINCT FROM %s ORDER BY ts",
            (chat_id,),
        )
        return [
            {"ts": r[0], "topic": r[1], "title": r[2], "body": r[3], "level": r[4]}
            for r in cur.fetchall()
        ]
    except Exception:  # noqa: BLE001
        return []


def digest_mark_sent(chat_id) -> None:
    pg = _pg_get()
    if pg is None:
        return
    try:
        pg.cursor().execute(
            "UPDATE notify_digest SET sent = true WHERE chat_id IS NOT DISTINCT FROM %s",
            (chat_id,),
        )
    except Exception:  # noqa: BLE001
        pass


def flush_digest(chat_id, *, force: bool = True) -> dict:
    """Send everything collected since the last digest as one push."""
    items = digest_pending(chat_id)
    if not items:
        return {"push": 0, "count": 0, "skipped": "empty"}
    lines = [f"• {it['title']}: {it['body']}" for it in items[:20]]
    more = f"\n+{len(items) - 20} autres" if len(items) > 20 else ""
    title = f"🗞️ Récap · {len(items)} chose(s)"
    res = notify(title, "\n".join(lines)[:2000] + more, chat_id=chat_id,
                 topic="digest", force=force, level="important")
    digest_mark_sent(chat_id)
    res["count"] = len(items)
    return res


# --------------------------------------------------------------- public API
def notify(
    title: str,
    body: str,
    *,
    chat_id: int | None = None,
    topic: str = "",
    url: str = "./",
    dedup_key: str | None = None,
    force: bool = False,
    level: str | None = None,
    digest: bool = True,
    channels: list[str] | None = None,
) -> dict:
    """Notify via Web Push, honouring preferences, quiet hours, deduplication
    and the user's proactivity level. Returns what was decided (for logs/tests).

    Every notification is also recorded in the history shown by the
    dashboard (its inbox), even when the push itself is skipped. `url` is
    where tapping it leads (e.g. a routine's chat); by default the dashboard
    opens a chat about the notification.

    `level` is one of critical/important/useful/fyi. When omitted it is
    inferred from the text (bot/ocpriority.py). Anything below the proactivity
    bar is recorded but not pushed, and — when `digest` — collected for the
    next recap instead of being lost.

    `channels` picks where it goes: "push" (Web Push) and/or channel ids from
    Settings (ntfy, Gotify, Discord, Slack — bot/occhannels.py). None means
    everywhere: Web Push and every enabled channel.
    """
    link = url if url and url != "./" else None
    result = {"push": 0, "skipped": None, "id": None}

    try:
        from ocpriority import classify  # noqa: PLC0415

        lvl = level or classify(f"{title} {body}", topic=topic)["level"]
    except Exception:  # noqa: BLE001
        lvl = level or "useful"
    result["level"] = lvl

    if dedup_key and _seen_recently(dedup_key, DEDUP_WINDOW) and not force:
        result["skipped"] = "dedup"
        return result

    # Quiet hours and the user's push preference: record, never push.
    quiet = in_quiet_hours()
    if not force and (quiet or not push_enabled(chat_id)):
        result["skipped"] = "quiet" if quiet else "pref"
        result["id"] = _record(chat_id, topic, title, body, dedup_key, [], False, link)
        return result

    # Proactivity bar: below it, keep for the digest rather than pushing now.
    if force:
        below = False
    else:
        try:
            from ocpriority import should_push  # noqa: PLC0415

            below = not should_push(lvl, proactivity(chat_id))
        except Exception:  # noqa: BLE001
            below = False
    if below:
        result["skipped"] = "below-level"
        result["id"] = _record(chat_id, topic, title, body, dedup_key, [], False, link)
        if digest:
            collect(chat_id, topic, title, body, lvl)
        return result

    # Record first to get the id, then put it in the link: tapping the
    # notification opens it in the dashboard.
    nid = _record(chat_id, topic, title, body, dedup_key, [], False, link)
    result["id"] = nid
    target = link or (f"./?notif={nid}" if nid else url)
    if channels == ["none"]:
        # "Nowhere but the inbox" only means something once other channels
        # exist; routines saved without any (an early form bug) keep Web Push.
        try:
            import occhannels  # noqa: PLC0415

            if not occhannels.load()["channels"]:
                channels = None
        except Exception:  # noqa: BLE001
            channels = None
    n = send_push(title, body, target) if channels is None or "push" in channels else 0
    result["push"] = n
    reached = ["push"] if n else []
    try:
        import occhannels  # noqa: PLC0415

        only = None if channels is None else [c for c in channels if c != "push"]
        extra = occhannels.deliver(title, body, target, lvl, only) if only != [] else []
    except Exception as exc:  # noqa: BLE001
        log.warning("channels: %s", exc)
        extra = []
    result["channels"] = extra
    reached += extra
    _update_record(nid, reached, bool(reached))
    return result


def recent(limit: int = 30) -> list[dict]:
    """Recent notification history (for the dashboard)."""
    pg = _pg_get()
    if pg is None:
        return []
    try:
        cur = pg.cursor()
        cur.execute(
            "SELECT ts, topic, title, body, channels, delivered "
            "FROM notifications ORDER BY ts DESC LIMIT %s",
            (limit,),
        )
        return [
            {
                "ts": t, "topic": topic, "title": title, "body": body,
                "channels": ch or [], "delivered": d,
            }
            for t, topic, title, body, ch, d in cur.fetchall()
        ]
    except Exception:  # noqa: BLE001
        return []
