"""What Mav keeps: memory, notifications, drafts and mail, debates, interests,
search, usage and speed, channels, calendars and backups.

Part of the web app server (see mav_api.py).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import mav_core
import mav_engine
import mav_routines
import mav_stream
import mav_media


def backup_places() -> "mav_backup.Places":
    """Where this install keeps what a backup holds."""
    home = Path(os.environ.get("MAV_USER_HOME") or os.environ.get("BOT_HOME") or Path.home())
    data_home = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    return mav_core.mav_backup.Places(
        dsn=mav_core.PG_DSN, bot_dir=mav_core.BOT_DIR, config_dir=mav_core._config_dir(),
        storage_dir=data_home / "opencode" / "storage", env_server=mav_core.ENV_SERVER,
        version=mav_engine.installed_version(), runtime=mav_core.RUNTIME or "systemd", chown=mav_core._chown_user,
    )


def calendar_view() -> dict:
    """Connected calendars (secrets masked) and what is on today."""
    if mav_core.occalendar is None:
        return {"sources": [], "today": []}
    today = []
    try:
        today = [mav_core.occalendar.view(e) for e in mav_core.occalendar.today()]
    except Exception:  # noqa: BLE001
        pass
    return {"sources": mav_core.occalendar.public_view(), "today": today}


def calendar_action(action: str, payload: dict) -> dict:
    if mav_core.occalendar is None:
        return {"ok": False, "error": "Calendars unavailable."}
    if action == "test":
        return mav_core.occalendar.test(str(payload.get("id") or ""))
    if action == "save":
        res = mav_core.occalendar.upsert(payload)
    elif action == "delete":
        res = mav_core.occalendar.remove(str(payload.get("id") or ""))
    else:
        return {"ok": False, "error": "Unknown action."}
    if res.get("ok"):
        mav_core._chown_user(mav_core.occalendar.CALENDAR_FILE)  # the worker reads it as the install user
    return res


def channels_action(action: str, payload: dict) -> dict:
    """Settings → Notification channels (ntfy, Gotify, Discord, Slack)."""
    if mav_core.occhannels is None:
        return {"ok": False, "error": "Channels unavailable."}
    if action == "save":
        res = mav_core.occhannels.upsert(payload)
    elif action == "delete":
        res = mav_core.occhannels.remove(str(payload.get("id") or ""))
    elif action == "public-url":
        res = mav_core.occhannels.set_public_url(str(payload.get("public_url") or ""))
    elif action == "test":
        return mav_core.occhannels.test(str(payload.get("id") or ""))
    else:
        return {"ok": False, "error": "Unknown action."}
    if res.get("ok"):
        mav_core._chown_user(mav_core.occhannels.CHANNELS_FILE)  # the worker reads it as the install user
    return res


def record_usage(source: str, entries: list) -> None:
    """Add an answer's tokens/cost, and warn once at 80 % / 100 % of budget."""
    if mav_core.USAGE is None:
        return
    try:
        mav_core.USAGE.record_entries(source, entries)
        level = mav_core.USAGE.alert_due()
    except Exception:  # noqa: BLE001
        return
    if level:
        b = mav_core.USAGE.budget()
        title = "💸 Budget reached" if level >= 100 else "💸 80 % of your budget used"
        body = (f"${mav_core.USAGE.month_cost():.2f} of ${b['monthly_usd']:.2f} this month."
                + (" New answers are paused until you raise it." if level >= 100 and b["action"] == "stop" else ""))
        try:
            record_notification("usage", title, body, "./#settings/usage")
            mav_media.send_push(title, body, "./#settings/usage")
        except Exception:  # noqa: BLE001
            pass


def answer_metrics(t_sent: float, t_first: float | None, t_end: float, entries: list) -> dict:
    """How long one answer took and what it cost in prompt: shown under the
    answer, kept for the Speed card in Usage."""
    steps = [e for e in entries if isinstance(e, dict)]
    cached = sum(int(((e.get("tokens") or {}).get("cache") or {}).get("read") or 0) for e in steps)
    sent = sum(int((e.get("tokens") or {}).get("input") or 0) for e in steps) + cached
    out = sum(int((e.get("tokens") or {}).get("output") or 0) + int((e.get("tokens") or {}).get("reasoning") or 0)
              for e in steps)
    return {
        "ttft_ms": int((t_first - t_sent) * 1000) if t_first else None,
        "total_ms": int((t_end - t_sent) * 1000),
        "steps": len(steps),
        "input_tokens": sent,
        "cached_tokens": cached,
        "output_tokens": out,
    }


def record_speed(source: str, m: dict) -> None:
    if mav_core.USAGE is None:
        return
    try:
        mav_core.USAGE.record_speed(source, m.get("ttft_ms"), m.get("total_ms") or 0, m.get("steps") or 0,
                           m.get("input_tokens") or 0, m.get("cached_tokens") or 0)
    except Exception:  # noqa: BLE001
        pass


def budget_blocked() -> bool:
    try:
        return bool(mav_core.USAGE and mav_core.USAGE.blocked())
    except Exception:  # noqa: BLE001
        return False


def record_notification(topic: str, title: str, body: str, link: str = "") -> int | None:
    try:
        rows = mav_core.pg_query(
            "insert into notifications (ts, chat_id, topic, title, body, channels, delivered, link) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
            (int(time.time()), mav_core.DEFAULT_CHAT_ID, topic, title[:200], body[:2000], ["push"], True, link or None),
        )
        return rows[0]["id"] if rows else None
    except Exception:  # noqa: BLE001
        return None


def get_memory(limit: int = 40) -> dict:
    def q(sql, params=()):
        try:
            return mav_core.pg_query(sql, params)
        except Exception:
            return []

    return {
        "conversations": q(
            "select id, question, left(answer, 600) as answer, ts, source, agent "
            "from conversations order by ts desc limit %s",
            (limit,),
        ),
        "facts": q("select id, fact, source, ts from facts order by ts desc limit 200"),
        "preferences": q("select key, value, ts from preferences order by ts desc limit 20"),
        "backend": mav_core.MEMORY.backend if mav_core.MEMORY else "none",
        "enabled": mav_core.MEMORY_ENABLED,
    }


def memory_action(action: str, payload: dict) -> dict:
    if action == "fact/add":
        fact = str(payload.get("fact") or "").strip()
        if not fact:
            return {"ok": False, "error": "Empty fact."}
        if mav_core.MEMORY:
            return {"ok": mav_core.MEMORY.add_fact(mav_core.DEFAULT_CHAT_ID, fact, source="dashboard")}
        mav_core.pg_exec(
            "insert into facts (chat_id, fact, source, ts) values (%s, %s, %s, %s)",
            (mav_core.DEFAULT_CHAT_ID, fact[:500], "dashboard", int(time.time())),
        )
        return {"ok": True}
    if action == "fact/delete":
        mav_core.pg_exec("delete from facts where id = %s", (int(payload.get("id") or 0),))
        return {"ok": True}
    if action == "exchange/delete":
        mav_core.pg_exec("delete from conversations where id = %s", (int(payload.get("id") or 0),))
        return {"ok": True}
    if action == "forget":
        mav_core.pg_exec("delete from conversations")
        if payload.get("facts"):
            mav_core.pg_exec("delete from facts")
        return {"ok": True}
    return {"ok": False, "error": "unknown action"}


def get_notifications(limit: int = 30) -> dict:
    """Historique des notifications proactives (veille + jobs)."""
    try:
        rows = mav_core.pg_query(
            "select id, ts, topic, title, body, channels, delivered, link "
            "from notifications where topic is distinct from 'push_ack' "
            "order by ts desc limit %s",
            (limit,),
        )
    except Exception:
        rows = []
    return {"notifications": rows}


def get_notification(nid: int) -> dict:
    """One notification by id (to open its detail from the push)."""
    try:
        rows = mav_core.pg_query(
            "select id, ts, topic, title, body, delivered, link from notifications where id = %s",
            (nid,),
        )
    except Exception:
        rows = []
    return {"notification": rows[0] if rows else None}


def get_drafts(status: str = "pending") -> dict:
    status = status if status in ("pending", "sent", "discarded", "all") else "pending"
    items = mav_core.DRAFTS.list(status, limit=100) if mav_core.DRAFTS else []
    return {"drafts": items, "backend": mav_core.DRAFTS.backend if mav_core.DRAFTS else "none"}


def draft_action(action: str, payload: dict) -> dict:
    if not mav_core.DRAFTS:
        return {"ok": False, "error": "Drafts unavailable."}
    if action == "status":
        return {"ok": mav_core.DRAFTS.set_status(int(payload.get("id") or 0), str(payload.get("status") or "pending"))}
    if action == "delete":
        return {"ok": mav_core.DRAFTS.delete(int(payload.get("id") or 0))}
    if action == "add":
        title = str(payload.get("title") or "").strip()
        body = str(payload.get("body") or "").strip()
        if not title or not body:
            return {"ok": False, "error": "Title and body required."}
        did = mav_core.DRAFTS.add(
            mav_core.DEFAULT_CHAT_ID,
            str(payload.get("kind") or "other"),
            title,
            body,
            "dashboard",
            to=str(payload.get("to") or ""),
            subject=str(payload.get("subject") or ""),
        )
        return {"ok": did is not None, "id": did}
    if action == "edit":
        did = int(payload.get("id") or 0)
        ok = mav_core.DRAFTS.update(
            did,
            title=payload.get("title"),
            body=payload.get("body"),
            to=payload.get("to"),
            subject=payload.get("subject"),
        )
        return {"ok": ok}
    return {"ok": False, "error": "unknown action"}


def send_draft(draft_id: int) -> dict:
    """Send a draft as an email through the configured mail (Settings → Mail)."""
    d = mav_core.DRAFTS.get(draft_id) if mav_core.DRAFTS else None
    if not d:
        return {"ok": False, "error": "Unknown draft."}
    to = str(d.get("email_to") or "").strip()
    if not to:
        return {"ok": False, "error": "No recipient on this draft — add one in Edit."}
    try:
        import mav_mail  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Mail module unavailable: {str(exc)[:120]}"}
    res = mav_mail.send(
        to,
        d.get("email_subject") or d.get("title") or "",
        d.get("body") or "",
        in_reply_to=str(d.get("message_id") or ""),
    )
    if res.get("ok"):
        mav_core.DRAFTS.set_status(draft_id, "sent")
    return res


def get_actions() -> dict:
    items = mav_core.ACTIONS.list("all", limit=100) if mav_core.ACTIONS else []
    return {"actions": items, "backend": mav_core.ACTIONS.backend if mav_core.ACTIONS else "none"}


def mail_config() -> dict:
    """Mail status (no password!) + providers to pre-fill the form."""
    try:
        import mav_mail  # noqa: PLC0415

        return mav_mail.status()
    except Exception as exc:  # noqa: BLE001
        return {"configured": False, "error": str(exc)[:200], "presets": []}


def mail_save(payload: dict) -> dict:
    try:
        import mav_mail  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}
    imap = str(payload.get("imap") or "").strip()
    smtp = str(payload.get("smtp") or "").strip()
    user = str(payload.get("user") or "").strip()
    password = str(payload.get("password") or "")
    if not (imap and smtp and user and password):
        # A blank password keeps the stored one (like the model provider form).
        cur = mav_mail.load()
        password = password or cur.get("MAIL_PASS", "")
        if not (imap and smtp and user and password):
            return {"ok": False, "error": "Fill in the servers, your address and the password."}
    mav_mail.save(imap, smtp, user, password)
    return {"ok": True}


def mail_reply_draft(payload: dict) -> dict:
    """File a threaded reply for a message UID — server-side, so it uses the
    dashboard's Postgres (the single writer) and the shared mail config."""
    uid = str(payload.get("uid") or "").strip()
    body = str(payload.get("body") or "").strip()
    if not uid or not body:
        return {"ok": False, "error": "uid and body required."}
    try:
        from ocmail import make_reply_draft  # noqa: PLC0415

        return make_reply_draft(uid, body, subject=str(payload.get("subject") or ""),
                                chat_id=mav_core.DEFAULT_CHAT_ID)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:250]}


def mail_forget() -> dict:
    try:
        import mav_mail  # noqa: PLC0415

        mav_mail.forget()
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


def mail_test(payload: dict) -> dict:
    try:
        import mav_mail  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}
    cur = mav_mail.load()
    password = str(payload.get("password") or "") or cur.get("MAIL_PASS", "")
    res = mav_mail.test(
        str(payload.get("imap") or cur.get("MAIL_IMAP_SERVER") or "").strip(),
        str(payload.get("smtp") or cur.get("MAIL_SMTP_SERVER") or "").strip(),
        str(payload.get("user") or cur.get("MAIL_USER") or "").strip(),
        password,
    )
    return res


def draft_notify(draft_id: int) -> dict:
    """Turn a pending draft into a notification, so it reaches the phone."""
    d = mav_core.DRAFTS.get(draft_id) if mav_core.DRAFTS else None
    if not d:
        return {"ok": False, "error": "Unknown draft."}
    try:
        from ocnotify import notify  # noqa: PLC0415

        res = notify(
            f"✍️ Brouillon prêt · {d['title']}",
            (d.get("body") or "")[:600],
            chat_id=mav_core.DEFAULT_CHAT_ID,
            topic="draft",
            level="important",
            dedup_key=f"draft:{draft_id}",
        )
        mav_core.DRAFTS.set_status(draft_id, "sent")
        return {"ok": True, "notify": res}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


# Multi-agent debate threads are written by the opencode debate tools; the web
# app shows them live. Reading is best-effort: an absent file just means no
# debate has been opened yet.
def get_debates() -> dict:
    try:
        from ocdebates import list_threads  # noqa: PLC0415

        return {"debates": list_threads()}
    except Exception:  # noqa: BLE001
        return {"debates": []}


def get_debate(thread_id: str) -> dict:
    if not thread_id:
        return {"error": "missing id"}
    try:
        from ocdebates import get_thread  # noqa: PLC0415

        thread = get_thread(thread_id)
    except Exception:  # noqa: BLE001
        thread = None
    return {"debate": thread}


def interests_autonomy() -> str:
    """How much latitude Mav has to spawn its own watchdogs."""
    level = "suggest"
    try:
        rows = mav_core.pg_query("select value from preferences where key = 'interests.autonomy' limit 1")
        if rows and rows[0].get("value"):
            level = rows[0]["value"]
    except Exception:  # noqa: BLE001
        pass
    return level if level in ("off", "suggest", "auto") else "suggest"


def set_interests_autonomy(level: str) -> dict:
    level = (level or "suggest").strip().lower()
    if level not in ("off", "suggest", "auto"):
        return {"ok": False, "error": "Level must be off, suggest or auto."}
    mav_core.pg_exec(
        "insert into preferences (chat_id, key, value, ts) values (%s, 'interests.autonomy', %s, %s) "
        "on conflict (chat_id, key) do update set value = excluded.value, ts = excluded.ts",
        (mav_core.DEFAULT_CHAT_ID, level, int(time.time())),
    )
    return {"ok": True, "level": level}


def _selfinit_diff() -> dict:
    if mav_core.INTERESTS is None or mav_core.ocselfinit is None:
        return {"create": [], "update": [], "retire": [], "keep": [], "counts": {}}
    try:
        return mav_core.ocselfinit.reconcile(mav_core.INTERESTS, mav_core.JOBS_FILE, autonomy="suggest")
    except Exception as exc:  # noqa: BLE001
        return {"create": [], "update": [], "retire": [], "keep": [],
                "counts": {}, "error": str(exc)[:200]}


def get_interests() -> dict:
    """The interest profile, the self-init proposal, and the knobs to steer it."""
    items = mav_core.INTERESTS.list(include_muted=True) if mav_core.INTERESTS else []
    now = int(time.time())
    for it in items:
        due = int(it.get("next_due") or 0)
        it["due_in_days"] = round((due - now) / 86400, 1) if due else None
    diff = _selfinit_diff()
    return {
        "interests": items,
        "backend": mav_core.INTERESTS.backend if mav_core.INTERESTS else "none",
        "autonomy": interests_autonomy(),
        "categories": list(mav_core.CATEGORIES),
        "cadences": list(mav_core.CADENCES),
        "cadence_days": mav_core.CADENCE_DAYS,
        "selfinit": diff,
    }


def add_interest(payload: dict) -> dict:
    if mav_core.INTERESTS is None:
        return {"ok": False, "error": "Interests unavailable."}
    label = str(payload.get("label") or "").strip()
    if not label:
        return {"ok": False, "error": "A label is required."}
    rec = mav_core.INTERESTS.add(
        label,
        polarity=str(payload.get("polarity") or "like"),
        category=str(payload.get("category") or "other"),
        entity=str(payload.get("entity") or ""),
        cadence=str(payload.get("cadence") or ""),
        source="dashboard",
    )
    return {"ok": rec is not None, "interest": rec}


def update_interest(payload: dict) -> dict:
    if mav_core.INTERESTS is None:
        return {"ok": False, "error": "Interests unavailable."}
    key = str(payload.get("key") or "").strip()
    if not key:
        return {"ok": False, "error": "A key is required."}
    fields = {}
    for f in ("pinned", "muted", "cadence", "polarity", "label", "category", "notes"):
        if f in payload:
            fields[f] = payload[f]
    if payload.get("resolve_conflict"):
        fields["resolve_conflict"] = True
    rec = mav_core.INTERESTS.update(key, **fields)
    return {"ok": rec is not None, "interest": rec}


def delete_interest(key: str) -> dict:
    if mav_core.INTERESTS is None:
        return {"ok": False, "error": "Interests unavailable."}
    return {"ok": mav_core.INTERESTS.delete(key)}


def interest_feedback(key: str, positive: bool) -> dict:
    if mav_core.INTERESTS is None:
        return {"ok": False, "error": "Interests unavailable."}
    rec = mav_core.INTERESTS.feedback(key, positive)
    return {"ok": rec is not None, "interest": rec}


def interest_context(key: str) -> dict:
    """Open a chat about one interest: recent news + a prompt to work with.

    This is how a nudge becomes a conversation — Mav brings the topic, the user
    takes it from there.
    """
    if mav_core.INTERESTS is None:
        return {"ok": False, "error": "Interests unavailable."}
    interest = mav_core.INTERESTS.get(key)
    if not interest:
        return {"ok": False, "error": "Unknown interest."}
    label = interest.get("label") or key
    sid = mav_routines.routine_session(f"Intérêt · {label}")
    # Best-effort headline context so the chat does not start from nothing.
    try:
        from ocwatch import news_items  # noqa: PLC0415

        query = interest.get("entity") or interest.get("label") or key
        heads = news_items(query)[:5]
    except Exception:  # noqa: BLE001
        heads = []
    lines = [
        f"Contexte : « {label} » fait partie des centres d'intérêt de l'utilisateur "
        f"(catégorie {interest.get('category') or 'autre'}, suivi {interest.get('cadence') or 'mensuel'}).",
        "Actualité récente à creuser :",
    ]
    lines += [f"- {h.get('title')} ({h.get('link')})" for h in heads] or ["- (rien de frais)"]
    lines.append("Ouvre la conversation sur ce sujet : dis-moi ce qui bouge et pose-moi une question.")
    prompt = "\n".join(lines)
    try:
        answer = mav_stream.ask(prompt, mav_core.DEFAULT_AGENT, sid, raw_session=True, with_memory=False)
        if answer and not answer.startswith("Error:"):
            return {"ok": True, "session": sid, "answer": answer}
        return {"ok": True, "session": sid, "answer": ""}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200], "session": sid}


def selfinit_apply() -> dict:
    """Force Mav to bring its watchdogs in line now (regardless of autonomy)."""
    if mav_core.INTERESTS is None or mav_core.ocselfinit is None:
        return {"ok": False, "error": "Self-init unavailable."}
    try:
        res = mav_core.ocselfinit.reconcile(mav_core.INTERESTS, mav_core.JOBS_FILE, autonomy="auto")
        return {"ok": True, **res}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


def global_search(query: str) -> dict:
    q = query.strip()
    if not q:
        return {"documents": [], "conversations": [], "facts": []}
    docs, convs, facts = [], [], []
    try:
        docs = mav_core.pg_query(
            "select title, left(body, 240) as excerpt, source, ts "
            "from documents where tsv @@ plainto_tsquery('french', %s) "
            "order by ts desc limit 8",
            (q,),
        )
    except Exception:
        pass
    try:
        convs = mav_core.pg_query(
            "select question, left(answer, 240) as answer, ts from conversations "
            "where question ilike %s or answer ilike %s order by ts desc limit 8",
            (f"%{q}%", f"%{q}%"),
        )
    except Exception:
        pass
    try:
        facts = mav_core.pg_query(
            "select fact, ts from facts where fact ilike %s order by ts desc limit 8",
            (f"%{q}%",),
        )
    except Exception:
        pass
    return {"documents": docs, "conversations": convs, "facts": facts}


def ensure_schema() -> None:
    """Columns added after the first release (idempotent, silent without PG)."""
    try:
        mav_core.pg_exec(
            "CREATE TABLE IF NOT EXISTS notifications (id bigserial PRIMARY KEY, ts bigint NOT NULL, "
            "chat_id bigint, topic text, title text, body text, dedup_key text, channels text[], "
            "delivered boolean DEFAULT true)"
        )
        mav_core.pg_exec("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS link text")
        # Email drafts: recipient and subject, added with the Mail feature.
        mav_core.pg_exec("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS email_to text")
        mav_core.pg_exec("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS email_subject text")
        # The original Message-ID, so the reply threads in the mailbox.
        mav_core.pg_exec("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS message_id text")
        # Interests profile (what the user cares about) and the watchdog routines
        # Mav spawns from it.
        if mav_core.INTERESTS is not None:
            try:
                mav_core.INTERESTS._ensure()
                if mav_core.INTERESTS._pg is not None:
                    mav_core.INTERESTS._pg.cursor().execute(
                        "ALTER TABLE interests ADD COLUMN IF NOT EXISTS last_ref text"
                    )
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass


__all__ = ['_selfinit_diff', 'add_interest', 'answer_metrics', 'backup_places', 'budget_blocked', 'calendar_action', 'calendar_view', 'channels_action', 'delete_interest', 'draft_action', 'draft_notify', 'ensure_schema', 'get_actions', 'get_debate', 'get_debates', 'get_drafts', 'get_interests', 'get_memory', 'get_notification', 'get_notifications', 'global_search', 'interest_context', 'interest_feedback', 'interests_autonomy', 'mail_config', 'mail_forget', 'mail_reply_draft', 'mail_save', 'mail_test', 'memory_action', 'record_notification', 'record_speed', 'record_usage', 'selfinit_apply', 'send_draft', 'set_interests_autonomy', 'update_interest']
