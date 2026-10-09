"""Conversations: sessions and their metadata, titles, learned facts, the
after-answer queue, messages, exports, memory context and uploads.

Part of the web app server (see mav_api.py).
"""

from __future__ import annotations

import base64
import mimetypes
import os
import re
import threading
import time
from pathlib import Path

import mav_core
import mav_engine
import mav_routines
import mav_store
import mav_stream
import mav_media


PREFIX = "dash: "


DEFAULT_TITLE = "New conversation"


LEGACY_TITLES = {"", DEFAULT_TITLE, "Nouvelle discussion"}


# Per-conversation metadata the engine does not keep: the agent the user is
# talking to, and whether the title was generated already.
_meta_lock = threading.Lock()


def session_meta(sid: str) -> dict:
    return (mav_core.read_json(mav_core.SESSIONS_META, {}) or {}).get(sid, {})


def set_session_meta(sid: str, **fields) -> None:
    if not sid:
        return
    with _meta_lock:
        meta = mav_core.read_json(mav_core.SESSIONS_META, {})
        if not isinstance(meta, dict):
            meta = {}
        meta.setdefault(sid, {}).update(fields)
        try:
            mav_core.write_json(mav_core.SESSIONS_META, meta)
        except Exception:  # noqa: BLE001
            pass


def drop_session_meta(sid: str) -> None:
    with _meta_lock:
        meta = mav_core.read_json(mav_core.SESSIONS_META, {})
        if isinstance(meta, dict) and meta.pop(sid, None) is not None:
            try:
                mav_core.write_json(mav_core.SESSIONS_META, meta)
            except Exception:  # noqa: BLE001
                pass


def session_owner(sid: str, title: str | None = None, meta: dict | None = None,
                  jobs: list | None = None) -> int:
    """The account a chat belongs to.

    Chats made in the app carry it in their metadata. Older ones are the
    owner's, except a routine's chat, which belongs to the routine's owner
    (the worker creates those, by title)."""
    m = session_meta(sid) if meta is None else meta
    if "user" in m:
        try:
            return int(m["user"])
        except (TypeError, ValueError):
            return mav_core.DEFAULT_CHAT_ID
    if title is None:
        title = session_title(sid)
    head = PREFIX + mav_routines.ROUTINE_PREFIX
    if title.startswith(head):
        return mav_routines.job_owner(title[len(head):], jobs)
    return mav_core.DEFAULT_CHAT_ID


def can_access(sid: str) -> bool:
    """May the current user open this chat? (No id: nothing to protect.)"""
    return not sid or session_owner(sid) == mav_core.uid()


def _list_raw_sessions() -> list[dict]:
    try:
        return mav_core.http_json(f"{mav_core.OPENCODE_URL}/session", timeout=8) or []
    except Exception:
        return []


_migrated = False


def _migrate_legacy(sessions: list[dict]) -> None:
    """Rename the very first dashboard chat (titled "dashboard"), once."""
    global _migrated
    if _migrated or not sessions:  # nothing listed (engine down): try again later
        return
    _migrated = True
    for s in sessions:
        if s.get("title") == "dashboard":
            try:
                mav_core.http_json(f"{mav_core.OPENCODE_URL}/session/{s['id']}", method="PATCH", body={"title": PREFIX + "First conversation"})
                s["title"] = PREFIX + "First conversation"
            except Exception:
                pass


def list_sessions() -> list[dict]:
    raw = _list_raw_sessions()
    _migrate_legacy(raw)
    meta = mav_core.read_json(mav_core.SESSIONS_META, {}) or {}
    jobs = mav_core.read_json(mav_core.JOBS_FILE, []) or []
    active = {r["session"] for r in mav_stream.runs_view() if r["status"] == "running"}
    me = mav_core.uid()
    out = []
    for s in raw:
        title = str(s.get("title", ""))
        if not title.startswith(PREFIX):
            continue
        # Job runs create "dash: job: <name>": these are not
        # discussions, on ne les met pas dans la liste.
        if title[len(PREFIX):].startswith("job:"):
            continue
        t = s.get("time", {})
        m = meta.get(s["id"], {})
        if session_owner(s["id"], title, m, jobs) != me:
            continue
        routine = title[len(PREFIX):].startswith(mav_routines.ROUTINE_PREFIX)
        agent = m.get("agent", "")
        if routine and not agent:
            name = title[len(PREFIX) + len(mav_routines.ROUTINE_PREFIX):]
            agent = next((j.get("agent", "") for j in jobs if j.get("name") == name), "")
        out.append({
            "id": s["id"],
            "title": title[len(PREFIX):] or DEFAULT_TITLE,
            "created": t.get("created"),
            "updated": t.get("updated") or t.get("created"),
            "agent": agent,
            "pinned": bool(m.get("pinned")),
            "routine": routine,
            "running": s["id"] in active,
        })
    out.sort(key=lambda x: (x["pinned"], x.get("updated") or 0), reverse=True)
    return out


def create_session(title: str = "", agent: str = "") -> dict:
    name = (title or DEFAULT_TITLE).strip()[:80] or DEFAULT_TITLE
    res = mav_core.http_json(f"{mav_core.OPENCODE_URL}/session", method="POST", body={"title": PREFIX + name})
    agent = (agent or "").strip()
    set_session_meta(res["id"], user=mav_core.uid(), **({"agent": agent} if agent else {}))
    return {"id": res["id"], "title": name, "agent": agent}


def quick_title(prompt: str) -> str:
    words = re.sub(r"\s+", " ", prompt.strip()).split(" ")
    title = " ".join(words[:7])
    if len(title) > 48:
        title = title[:47].rstrip() + "…"
    elif len(words) > 7:
        title += "…"
    return (title[:1].upper() + title[1:]) if title else DEFAULT_TITLE


def _clean_title(raw: str) -> str:
    line = next((l for l in (raw or "").strip().splitlines() if l.strip()), "")
    line = re.sub(r"^(title|titre)\s*[:：-]\s*", "", line.strip(), flags=re.I)
    line = line.strip(" \"'`*#.").strip()
    words = line.split()
    if not words or len(words) > 8:
        return ""
    return " ".join(words)[:48]


def quick_completion(instruction: str, agent: str = "", timeout: float = 90) -> str:
    """One-shot model call in a throwaway session (titles, fact extraction)."""
    if mav_store.budget_blocked():
        return ""
    tmp = None
    try:
        tmp = mav_core.http_json(f"{mav_core.OPENCODE_URL}/session", method="POST", body={"title": "mav-internal"}, timeout=10)["id"]
        body = {"parts": [{"type": "text", "text": instruction}], **_model_body(small=True)}
        if agent and agent in mav_engine.valid_agents():
            body["agent"] = agent
        res = mav_core.http_json(f"{mav_core.OPENCODE_URL}/session/{tmp}/message", method="POST", body=body, timeout=timeout)
        mav_store.record_usage("background", [res or {}])
        return _part_text((res or {}).get("parts") or [])
    except Exception:  # noqa: BLE001
        return ""
    finally:
        if tmp:
            delete_session(tmp)


ABOUT_ME_RE = re.compile(
    r"\b(i|i'm|im|i've|i'd|my|mine|me|we|we're|our|us|je|j'|moi|mon|ma|mes|nous|notre|nos)\b",
    re.I,
)


def learn_facts(prompt: str) -> int:
    if not (mav_core.MEMORY and mav_core.MEMORY_ENABLED) or not ABOUT_ME_RE.search(prompt) or len(prompt) > 4000:
        return 0
    instruction = (
        "Extract durable personal facts about the user from their message below: "
        "things worth remembering in future conversations (where they live, job, "
        "family, health or diet, preferences, recurring constraints, goals). "
        "Ignore one-off requests and anything about other topics. Write each fact "
        "as a short third-person sentence starting with 'User', in the language "
        "of the message, one per line, each line starting with '- '. If there is "
        "nothing durable, reply exactly NONE.\n\n"
        f"Message: {prompt.strip()[:2000]}"
    )
    return save_learned_facts(quick_completion(instruction, timeout=120))


def save_learned_facts(raw: str) -> int:
    """Store the '- User …' lines of a model reply as learned facts."""
    if not (mav_core.MEMORY and mav_core.MEMORY_ENABLED):
        return 0
    if not raw or raw.strip(" :\n").upper().startswith("NONE"):
        return 0
    known = [f["fact"].lower() for f in mav_core.MEMORY.facts(mav_core.uid(), limit=200)]
    added = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith(("-", "•", "*")):
            continue
        fact = line.lstrip("-•* ").strip().rstrip(".")
        if len(fact) < 6 or len(fact) > 240:
            continue
        low = fact.lower()
        if any(low in k or k in low for k in known):
            continue
        if mav_core.MEMORY.add_fact(mav_core.uid(), fact, source="learned"):
            known.append(low)
            added += 1
        if added >= 3:
            break
    return added


def learn_interests(prompt: str) -> int:
    """Detect the user's interests/likes/dislikes in their message.

    Pure, dependency-free and explainable (regex + scoring in ocinterests), so
    it costs nothing and never invents a fact. Every hit keeps its evidence. A
    statement that contradicts a recorded interest is flagged, not silently
    flipped — Mav stops pushing until the user settles it.
    """
    if mav_core.INTERESTS is None or not prompt or len(prompt) > 4000:
        return 0
    if not mav_core.is_owner():
        return 0  # the interest profile is the owner's
    try:
        return mav_core.INTERESTS.learn_from_text(prompt, source="chat")
    except Exception:  # noqa: BLE001
        return 0


def generate_title(sid: str, prompt: str, answer: str) -> None:
    """Ask the model for a 2–5 word title in a throwaway session."""
    tmp = None
    try:
        tmp = mav_core.http_json(f"{mav_core.OPENCODE_URL}/session", method="POST", body={"title": "mav-title"}, timeout=10)["id"]
        instruction = (
            "Write a title of 2 to 5 words for the conversation below, in the "
            "language of the user's message. Reply with the title only: no "
            "quotes, no punctuation at the end, no explanation.\n\n"
            f"User: {prompt.strip()[:800]}\n\nAssistant: {answer.strip()[:800]}"
        )
        body = {"parts": [{"type": "text", "text": instruction}], **_model_body(small=True)}
        if "title" in mav_engine.valid_agents():
            body["agent"] = "title"
        if mav_store.budget_blocked():
            return
        res = mav_core.http_json(f"{mav_core.OPENCODE_URL}/session/{tmp}/message", method="POST", body=body, timeout=90)
        mav_store.record_usage("background", [res or {}])
        title = _clean_title(_part_text((res or {}).get("parts") or []))
        if title and session_meta(sid).get("title_locked") is not True:
            rename_session(sid, title)
            set_session_meta(sid, titled=True)
    except Exception:  # noqa: BLE001
        pass
    finally:
        if tmp:
            delete_session(tmp)


_after_q: list[tuple] = []


_after_cv = threading.Condition()


_after_thread: threading.Thread | None = None


AFTER_IDLE_WAIT = float(os.environ.get("MAV_AFTER_IDLE_WAIT", "120"))


def _engine_busy() -> bool:
    with mav_stream._runs_lock:
        return any(r.status == "running" for r in mav_stream.RUNS.values())


def wants_facts(prompt: str) -> bool:
    text = (prompt or "").strip()
    return bool(
        mav_core.MEMORY and mav_core.MEMORY_ENABLED and 15 <= len(text) <= 4000 and ABOUT_ME_RE.search(text)
    )


def schedule_after_answer(sid: str, prompt: str, answer: str, needs_title: bool) -> None:
    facts = wants_facts(prompt)
    if not (needs_title or facts):
        return
    global _after_thread
    with _after_cv:
        _after_q.append((mav_core.uid(), (sid, prompt, answer, needs_title, facts)))
        if _after_thread is None or not _after_thread.is_alive():
            _after_thread = threading.Thread(target=_after_worker, daemon=True)
            _after_thread.start()
        _after_cv.notify()


def _after_worker() -> None:
    while True:
        with _after_cv:
            while not _after_q:
                if not _after_cv.wait(timeout=300):
                    return
            user, job = _after_q.pop(0)
        # Let the engine finish whatever the person is waiting on (bounded).
        waited = 0.0
        while _engine_busy() and waited < AFTER_IDLE_WAIT:
            time.sleep(1.0)
            waited += 1.0
        try:
            with mav_core.as_user(user):
                after_answer(*job)
        except Exception:  # noqa: BLE001
            pass


def after_answer(sid: str, prompt: str, answer: str, needs_title: bool, facts: bool) -> None:
    if needs_title and not facts:
        return generate_title(sid, prompt, answer)
    if facts and not needs_title:
        learn_facts(prompt)
        return
    instruction = (
        "Two short tasks about the conversation below.\n"
        "1. On the first line write `TITLE: ` followed by a title of 2 to 5 "
        "words in the language of the user's message (no quotes, no final "
        "punctuation).\n"
        "2. Then write `FACTS:` and, one per line starting with '- ', the "
        "durable personal facts about the user stated in their message "
        "(where they live, job, family, health or diet, preferences, "
        "recurring constraints, goals), each a short third-person sentence "
        "starting with 'User', in the language of the message. Ignore one-off "
        "requests. If there is none, write `FACTS: NONE`.\n\n"
        f"User: {prompt.strip()[:2000]}\n\nAssistant: {answer.strip()[:800]}"
    )
    raw = quick_completion(instruction, timeout=120)
    if not raw:
        return
    title_line = next((l for l in raw.splitlines() if l.strip().upper().startswith("TITLE")), "")
    title = _clean_title(title_line.split(":", 1)[-1] if ":" in title_line else "")
    if title and session_meta(sid).get("title_locked") is not True:
        rename_session(sid, title)
        set_session_meta(sid, titled=True)
    _, _, fact_block = raw.partition("FACTS")
    save_learned_facts(fact_block)


def rename_session(sid: str, title: str) -> bool:
    name = (title or "").strip()[:80]
    if not sid or not name:
        return False
    for verb in ("PATCH", "PUT"):
        try:
            mav_core.http_json(f"{mav_core.OPENCODE_URL}/session/{sid}", method=verb, body={"title": PREFIX + name})
            return True
        except Exception:
            continue
    return False


def delete_session(sid: str) -> bool:
    if not sid:
        return False
    try:
        mav_core.http_json(f"{mav_core.OPENCODE_URL}/session/{sid}", method="DELETE")
        drop_session_meta(sid)
        return True
    except Exception:
        return False


def session_title(sid: str) -> str:
    try:
        s = mav_core.http_json(f"{mav_core.OPENCODE_URL}/session/{sid}", timeout=6) or {}
        return str(s.get("title", ""))
    except Exception:
        return ""


def _part_text(parts: list) -> str:
    return "\n\n".join(
        (p.get("text") or "").strip()
        for p in (parts or [])
        if p.get("type") == "text" and not p.get("synthetic") and (p.get("text") or "").strip()
    )


def session_messages(sid: str, entries: list | None = None) -> list[dict]:
    """The chat as the person sees it: one bubble per turn.

    The engine stores a turn as several assistant entries — one per step
    (thinking, calling a tool or a helper, then the answer). Shown one by one,
    a reloaded chat would repeat "Assistant · 10:42" for every step of the same
    answer, so consecutive assistant entries are merged into one message (same
    text the live stream showed). A user entry carrying only hidden parts (the
    injected memory, an internal continuation) does not split the turn.
    """
    if entries is None:
        try:
            entries = mav_core.http_json(f"{mav_core.OPENCODE_URL}/session/{sid}/message", timeout=12) or []
        except Exception:
            return []
    msgs: list[dict] = []
    for e in entries:
        info = e.get("info") or {}
        role = info.get("role")
        if role not in ("user", "assistant"):
            continue
        parts = e.get("parts") or []
        text = _part_text(parts)
        tools = [mav_stream._tool_info(p) for p in parts if p.get("type") == "tool"] if role == "assistant" else []
        if not text and not tools:
            continue
        ts = (info.get("time") or {}).get("created")
        if role == "user":
            msgs.append({"role": "me", "text": text, "ts": ts})
            continue
        # The agent that actually answered (field name varies by version).
        agent = info.get("agent") or info.get("mode") or ""
        prev = msgs[-1] if msgs else None
        if prev and prev["role"] == "mav":
            if text:
                prev["text"] = f"{prev['text']}\n\n{text}" if prev["text"] else text
            prev["agent"] = prev.get("agent") or agent
            if tools:
                prev.setdefault("tools", []).extend(tools)
            continue
        msg = {"role": "mav", "text": text, "ts": ts, "agent": agent}
        if tools:
            msg["tools"] = tools
        msgs.append(msg)
    return msgs


def _drop_open_turn(msgs: list[dict]) -> list[dict]:
    """Remove the answer still being written (the live stream shows it)."""
    out = list(msgs)
    while out and out[-1]["role"] == "mav":
        out.pop()
    return out


def summarize_session(sid: str) -> str:
    """Key points of a chat, written in a throwaway session.

    Asking inside the chat itself would leave the request and the summary in
    the conversation (shown on reload, and fed back to the model).
    """
    msgs = session_messages(sid)
    if not msgs:
        return "Nothing to summarise yet."
    lines, budget = [], 12000
    for m in reversed(msgs):  # the most recent part matters most
        who = "User" if m["role"] == "me" else "Assistant"
        line = f"{who}: {m['text'].strip()[:2000]}"
        budget -= len(line)
        if budget < 0:
            break
        lines.append(line)
    transcript = "\n\n".join(reversed(lines))
    out = quick_completion(
        "Summarize this conversation in a few key points (decisions, facts, "
        "open questions), in the language it is written in. Reply with the "
        "summary only.\n\n" + transcript,
        timeout=120,
    )
    return out or "The summary could not be written — is the assistant running?"


def export_session_markdown(sid: str) -> str:
    title = session_title(sid)[len(PREFIX):] or DEFAULT_TITLE
    lines = [f"# {title}", ""]
    for m in session_messages(sid):
        who = "You" if m["role"] == "me" else (f"Mav · {m['agent']}" if m.get("agent") else "Mav")
        lines.append(f"**{who}**" + (f" · {_ts(m['ts'])}" if m.get("ts") else ""))
        lines.append("")
        lines.append(m["text"])
        lines.append("")
    return "\n".join(lines)


def _ts(ms) -> str:
    try:
        return time.strftime("%d/%m %H:%M", time.localtime(int(ms) / 1000))
    except Exception:
        return ""


def _model_body(small: bool = False) -> dict:
    """The model to use; `small` = background work (titles, facts, summaries),
    which goes to the cheaper model chosen in Settings → Usage, if any."""
    ref = mav_core.DEFAULT_MODEL
    if small and mav_core.USAGE is not None:
        try:
            ref = mav_core.USAGE.small_model() or ref
        except Exception:  # noqa: BLE001
            pass
    if ref and "/" in ref:
        provider, model = ref.split("/", 1)
        return {"model": {"providerID": provider, "modelID": model}}
    return {}


# What a model takes as an attachment: images (up to ~5 MB once encoded) and
# PDFs. Text files go in as text. Anything else (Word, Excel, archives, big
# images) is refused by the model, so the turn would fail: it is described
# instead, with its path, for the assistant to open with its tools.
MODEL_IMAGES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_IMAGE_BYTES = 3_750_000
MAX_TEXT_BYTES = 400_000
TEXT_MIMES = {"application/json", "application/xml", "application/yaml", "application/javascript",
              "application/x-sh", "application/sql", "image/svg+xml"}


def _attachment_part(f: dict) -> dict:
    url = f.get("url") or ""
    mime = (f.get("mime") or "application/octet-stream").split(";")[0].strip().lower()
    name = f.get("filename") or "fichier"
    path = Path(url[len("file://"):]) if url.startswith("file://") else None
    try:
        size = path.stat().st_size if path else None
    except OSError:
        size = None
    if path is None or mime == "application/pdf" or (mime in MODEL_IMAGES and (size or 0) <= MAX_IMAGE_BYTES):
        return {"type": "file", "url": url, "mime": mime, "filename": name}
    if (mime.startswith("text/") or mime in TEXT_MIMES) and (size or 0) <= MAX_TEXT_BYTES:
        return {"type": "file", "url": url, "mime": "text/plain", "filename": name}
    kb = f", {round(size / 1024)} KB" if size is not None else ""
    return {"type": "text", "synthetic": True, "text": (
        f"[The user attached the file \"{name}\" ({mime}{kb}). It is saved at {path} and cannot be "
        "shown to you directly: open or convert it with your tools (with the code sandbox, copy it in "
        f"first with load_from_chat, name \"{path.name}\") before answering about its content.]")}


def _parts(prompt: str, files: list) -> list:
    parts: list[dict] = [{"type": "text", "text": prompt}]
    parts += [_attachment_part(f) for f in files or []]
    return parts


def memory_context(prompt: str) -> str:
    """Facts + relevant past exchanges + indexed documents, for a new chat."""
    blocks = []
    if mav_core.MEMORY and mav_core.MEMORY_ENABLED:
        try:
            b = mav_core.MEMORY.context_block(mav_core.uid(), prompt, mav_core.MEMORY_TOP)
            if b:
                blocks.append(b)
        except Exception:  # noqa: BLE001
            pass
    if mav_core.RAG is not None and mav_core.is_owner():  # indexed documents are the owner's
        try:
            if mav_core._RAG is None:
                mav_core._RAG = mav_core.RAG()
            b = mav_core._RAG.context_block(mav_core.DEFAULT_CHAT_ID, prompt, mav_core.MEMORY_TOP)
            if b:
                blocks.append(b)
        except Exception:  # noqa: BLE001
            pass
    return "\n\n".join(blocks)


def remember_exchange(prompt: str, answer: str, sid: str, agent: str) -> None:
    if mav_core.MEMORY and mav_core.MEMORY_ENABLED and answer:
        try:
            mav_core.MEMORY.add(mav_core.uid(), prompt, answer, sid, source="dashboard", agent=agent)
        except Exception:  # noqa: BLE001
            pass


def save_upload(name: str, data_b64: str, mime: str = "") -> dict:
    mav_core.ATTACH_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name or "fichier")[:120] or "fichier"
    dest = mav_core.inside(mav_core.ATTACH_DIR, f"{int(time.time())}-{safe}")
    dest.write_bytes(base64.b64decode(data_b64))
    mt = mime or mimetypes.guess_type(safe)[0] or "application/octet-stream"
    if mt == "application/octet-stream":
        mt = mav_media._mime_from_ext(safe)
    # Persistent archive: attachments sent by the user remain
    # disponibles pour que Mav puisse les renvoyer plus tard.
    archived = mav_media.archive_media(dest, safe, mt, source="upload")
    return {
        "url": f"file://{dest}",
        "mime": mt,
        "filename": safe,
        "media_id": archived.get("id") if archived else None,
        "media_path": archived.get("path") if archived else None,
    }


# Sessions the user asked to stop (interrupt-and-reprocess): stream_answer
# aborts the engine as soon as it notices. A session id stays here only while
# its stream is winding down; the flag is consumed on the next answer.
INTERRUPTED: set[str] = set()


__all__ = ['_migrated', 'can_access', 'session_owner', 'ABOUT_ME_RE', 'AFTER_IDLE_WAIT', 'DEFAULT_TITLE', 'INTERRUPTED', 'LEGACY_TITLES', 'PREFIX', '_after_cv', '_after_q', '_after_thread', '_after_worker', '_clean_title', '_drop_open_turn', '_engine_busy', '_list_raw_sessions', '_meta_lock', '_migrate_legacy', '_model_body', '_part_text', '_parts', '_ts', 'after_answer', 'create_session', 'delete_session', 'drop_session_meta', 'export_session_markdown', 'generate_title', 'learn_facts', 'learn_interests', 'list_sessions', 'memory_context', 'quick_completion', 'quick_title', 'remember_exchange', 'rename_session', 'save_learned_facts', 'save_upload', 'schedule_after_answer', 'session_messages', 'session_meta', 'session_title', 'set_session_meta', 'summarize_session', 'wants_facts']
