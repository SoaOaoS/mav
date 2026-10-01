#!/usr/bin/env python3
"""Pont opencode <-> Telegram, version asynchrone.

Differences from v1:
  - prompt_async + flux SSE : plus aucun timeout HTTP, progression en direct
  - cross-session memory injected automatically
  - scheduled runs pushed to Telegram

Commandes :
  /ask <question>   ask a question (or just type)
  /new              nouvelle session
  /agent [nom]      afficher ou changer d'agent
  /stop             interrompre la tâche en cours
  /memory           memory status
  /forget           clear this chat's memory
  /jobs             list scheduled runs
  /run <name>       trigger a job immediately
  /session          identifiant de session
  /id               identifiant de ce chat
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path

import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ocbus import EventBus
from ocformat import TG_HARD, TG_LIMIT, format_for_telegram, split_markdown
from ocjobs import Scheduler, load_jobs
from ocmemory import Memory
from ocnotify import notify as notify_push
from ocprogress import ProgressTracker, follow
from ocrag import RAG
from ocwatch import Watch

# --------------------------------------------------------------------- config

TOKEN = os.environ["TELEGRAM_TOKEN"]

ALLOWED = {
    int(x)
    for x in os.environ.get("ALLOWED_CHAT_IDS", "").replace(",", " ").split()
    if x.strip()
}

# Allowlist of channels where /clear is allowed. Empty = /clear disabled everywhere.
CLEAR_ALLOWED = {
    int(x)
    for x in os.environ.get("CLEAR_ALLOWED_CHAT_IDS", "").replace(",", " ").split()
    if x.strip()
}

OPENCODE_URL = os.environ.get("OPENCODE_URL", "http://127.0.0.1:4096").rstrip("/")
OPENCODE_PASSWORD = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
OPENCODE_USERNAME = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")

MODEL = os.environ.get("OPENCODE_MODEL", "").strip()
DEFAULT_AGENT = os.environ.get("OPENCODE_AGENT", "").strip()

FORMAT = os.environ.get("FORMAT", "html").lower()
ANSWER_MODE = os.environ.get("ANSWER_MODE", "last").lower()
PLAIN_TEXT_IS_ASK = os.environ.get("PLAIN_TEXT_IS_ASK", "1") == "1"
SHOW_PROGRESS = os.environ.get("SHOW_PROGRESS", "1") == "1"

# Safety net: if no event arrives within this delay, we give up. It is no
# longer a request timeout, only a stuck-detection.
IDLE_TIMEOUT = float(os.environ.get("IDLE_TIMEOUT", "1800"))

MEMORY_ENABLED = os.environ.get("MEMORY", "1") == "1"
MEMORY_TOP = int(os.environ.get("MEMORY_TOP", "3"))

BOT_DIR = Path(os.environ.get("BOT_DIR", Path(__file__).resolve().parent))
STATE_FILE = Path(os.environ.get("STATE_FILE", BOT_DIR / "sessions.json"))
MEMORY_FILE = Path(os.environ.get("MEMORY_FILE", BOT_DIR / "memory.json"))
JOBS_FILE = Path(os.environ.get("JOBS_FILE", BOT_DIR / "jobs.json"))
JOBS_STATE = Path(os.environ.get("JOBS_STATE", BOT_DIR / "jobs_state.json"))

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("opencode-bot")

http: httpx.AsyncClient | None = None
bus: EventBus | None = None
memory = Memory(MEMORY_FILE)
rag = RAG()
scheduler: Scheduler | None = None
watch: Watch | None = None
locks: dict[int, asyncio.Lock] = {}

# ----------------------------------------------------------------- chat state


def load_state() -> dict[str, dict]:
    try:
        raw = json.loads(STATE_FILE.read_text())
    except Exception:
        return {}
    return {k: (v if isinstance(v, dict) else {"session": v}) for k, v in raw.items()}


def save_state(state: dict[str, dict]) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=1))
    except Exception as exc:  # noqa: BLE001
        log.warning("state not persisted: %s", exc)


def chat_state(chat_id: int) -> dict:
    return load_state().get(str(chat_id), {})


def update_chat(chat_id: int, **fields) -> None:
    state = load_state()
    state.setdefault(str(chat_id), {}).update(fields)
    save_state(state)


def track_message(chat_id: int, message_id: int) -> None:
    """Remember a message sent by the bot so /clear can delete it."""
    state = load_state()
    chat = state.setdefault(str(chat_id), {})
    ids = chat.setdefault("messages", [])
    if message_id not in ids:
        ids.append(message_id)
        chat["messages"] = ids[-500:]  # cap to avoid unbounded growth
    save_state(state)


def agent_for(chat_id: int) -> str:
    return chat_state(chat_id).get("agent", DEFAULT_AGENT)


async def session_alive(session_id: str) -> bool:
    try:
        r = await http.get(f"{OPENCODE_URL}/session/{session_id}", timeout=15)
        return r.status_code == 200
    except Exception:
        return False


async def new_session(title: str) -> str:
    r = await http.post(f"{OPENCODE_URL}/session", json={"title": title}, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


async def get_session(chat_id: int, force_new: bool = False) -> tuple[str, bool]:
    """Retourne (session_id, est_nouvelle)."""
    existing = chat_state(chat_id).get("session")
    if not force_new and existing and await session_alive(existing):
        return existing, False
    sid = await new_session(f"telegram-{chat_id}")
    update_chat(chat_id, session=sid)
    log.info("chat %s -> session %s", chat_id, sid)
    return sid, True


# ------------------------------------------------------------ appels opencode


async def list_agents() -> list[str]:
    try:
        r = await http.get(f"{OPENCODE_URL}/agent", timeout=15)
        r.raise_for_status()
        return sorted(
            a["name"]
            for a in r.json()
            if isinstance(a, dict)
            and a.get("name")
            and a.get("mode") in (None, "all", "primary")
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("liste des agents indisponible: %s", exc)
        return []


def extract_answer(payload: dict) -> str:
    parts = payload.get("parts") or []
    texts = [
        (p.get("text") or "").strip()
        for p in parts
        if p.get("type") == "text"
        and not p.get("synthetic")
        and (p.get("text") or "").strip()
    ]
    if not texts:
        return ""
    return texts[-1] if ANSWER_MODE == "last" else "\n\n".join(texts)


async def last_assistant_text(session_id: str) -> str:
    """Fetch the final answer once the session is idle."""
    r = await http.get(f"{OPENCODE_URL}/session/{session_id}/message", timeout=60)
    r.raise_for_status()
    for entry in reversed(r.json()):
        if (entry.get("info") or {}).get("role") == "assistant":
            text = extract_answer(entry)
            if text:
                return text
    return ""


async def command_async(
    session_id: str, command: str, arguments: str, agent: str | None = None
) -> None:
    body: dict = {"command": command, "arguments": arguments}
    if agent:
        body["agent"] = agent
    r = await http.post(
        f"{OPENCODE_URL}/session/{session_id}/command", json=body, timeout=30
    )
    r.raise_for_status()


async def prompt_async(
    session_id: str, prompt: str, agent: str, files: list[dict] | None = None
) -> None:
    parts: list[dict] = [{"type": "text", "text": prompt}]
    for f in files or []:
        parts.append(
            {
                "type": "file",
                "url": f["url"],
                "mime": f.get("mime", "application/octet-stream"),
                "filename": f.get("filename", "fichier"),
            }
        )
    body: dict = {"parts": parts}
    if MODEL and "/" in MODEL:
        provider, model = MODEL.split("/", 1)
        body["model"] = {"providerID": provider, "modelID": model}
    if agent:
        body["agent"] = agent
    r = await http.post(
        f"{OPENCODE_URL}/session/{session_id}/prompt_async", json=body, timeout=30
    )
    r.raise_for_status()


async def abort(session_id: str) -> None:
    await http.post(f"{OPENCODE_URL}/session/{session_id}/abort", timeout=15)


# --------------------------------------------------------------- attachments

ATTACH_DIR = Path(os.environ.get("ATTACH_DIR", "/tmp/opencode/attachments"))


def guess_mime(name: str) -> str:
    ext = Path(name).suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".csv": "text/csv",
        ".md": "text/markdown",
        ".json": "application/json",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(ext, "application/octet-stream")


async def download_attachment(
    bot, file_id: str, filename: str, mime: str
) -> dict | None:
    """Download a Telegram file and return an opencode attachment."""
    try:
        f = await bot.get_file(file_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("get_file failed: %s", exc)
        return None
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename) or "fichier"
    ATTACH_DIR.mkdir(parents=True, exist_ok=True)
    dest = ATTACH_DIR / safe
    try:
        await f.download_to_drive(dest)
    except Exception as exc:  # noqa: BLE001
        log.warning("download failed: %s", exc)
        return None
    return {
        "url": f"file://{dest}",
        "mime": mime or guess_mime(safe),
        "filename": safe,
    }


def collect_attachments(update: Update) -> list[dict]:
    """Extract attachments (photo/document) from a Telegram message."""
    msg = update.message
    if not msg:
        return []
    out = []
    if msg.document:
        d = msg.document
        out.append(
            {
                "file_id": d.file_id,
                "filename": d.file_name or "document",
                "mime": d.mime_type or "",
            }
        )
    if msg.photo:
        # the largest resolution comes last
        p = msg.photo[-1]
        out.append({"file_id": p.file_id, "filename": "photo.jpg", "mime": "image/jpeg"})
    return out


# --------------------------------------------------------------------- envoi


def authorized(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and (not ALLOWED or chat.id in ALLOWED))


async def send_answer(bot, chat_id: int, text: str, reply_to: int | None = None) -> None:
    if FORMAT == "plain":
        for chunk in split_markdown(text, TG_LIMIT):
            sent = await bot.send_message(chat_id=chat_id, text=chunk)
            track_message(chat_id, sent.message_id)
        return
    for chunk in format_for_telegram(text):
        try:
            sent = await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_to_message_id=reply_to,
            )
            track_message(chat_id, sent.message_id)
        except BadRequest as exc:
            log.warning("HTML rejected (%s), falling back to plain text", exc)
            plain = re.sub(r"<[^>]+>", "", chunk)
            plain = plain.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
            sent = await bot.send_message(chat_id=chat_id, text=plain[:TG_HARD])
            track_message(chat_id, sent.message_id)
        reply_to = None  # only reply to the first chunk


async def send_bot(bot, chat_id: int, text: str, **kwargs) -> None:
    """Envoie un message du bot et le tracke pour /clear."""
    sent = await bot.send_message(chat_id=chat_id, text=text, **kwargs)
    track_message(chat_id, sent.message_id)


# ------------------------------------------------------------- flux principal


async def run_prompt(
    bot,
    chat_id: int,
    prompt: str,
    session_id: str,
    agent: str,
    status_msg=None,
    files: list[dict] | None = None,
) -> tuple[str, ProgressTracker]:
    """Run the prompt, follow progress, return the final answer."""
    queue = bus.subscribe(session_id)
    tracker = ProgressTracker()

    async def on_update(text: str) -> None:
        if status_msg is not None:
            await status_msg.edit_text(text, parse_mode=ParseMode.HTML)

    try:
        await prompt_async(session_id, prompt, agent, files)
        await follow(queue, tracker, on_update, idle_timeout=IDLE_TIMEOUT)
        if tracker.error:
            return "", tracker
        answer = await last_assistant_text(session_id)
        return answer, tracker
    finally:
        bus.unsubscribe(session_id, queue)


async def run_command(
    bot,
    chat_id: int,
    command: str,
    arguments: str,
    session_id: str,
    agent: str | None = None,
    status_msg=None,
) -> tuple[str, ProgressTracker]:
    """Run an opencode command, follow progress, return the answer."""
    queue = bus.subscribe(session_id)
    tracker = ProgressTracker()

    async def on_update(text: str) -> None:
        if status_msg is not None:
            await status_msg.edit_text(text, parse_mode=ParseMode.HTML)

    try:
        await command_async(session_id, command, arguments, agent)
        await follow(queue, tracker, on_update, idle_timeout=IDLE_TIMEOUT)
        if tracker.error:
            return "", tracker
        answer = await last_assistant_text(session_id)
        return answer, tracker
    finally:
        bus.unsubscribe(session_id, queue)


async def handle_debate(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        await update.message.reply_text(
            f"Not authorized. This chat id: {update.effective_chat.id}"
        )
        return

    question = " ".join(ctx.args).strip()
    if not question:
        await update.message.reply_text("Usage : /debate <question>")
        return

    chat_id = update.effective_chat.id
    lock = locks.setdefault(chat_id, asyncio.Lock())
    if lock.locked():
        await update.message.reply_text(
            "A task is already running. Use /stop to interrupt it."
        )
        return

    async with lock:
        session_id, is_new = await get_session(chat_id)
        status_msg = None
        if SHOW_PROGRESS:
            status_msg = await update.message.reply_text(
                "🗣️ <b>starting the debate</b>…", parse_mode=ParseMode.HTML
            )
            track_message(chat_id, status_msg.message_id)
        try:
            answer, tracker = await run_command(
                ctx.bot, chat_id, "debate", question, session_id, status_msg=status_msg
            )
        except httpx.HTTPStatusError as exc:
            log.error("erreur HTTP /command debate: %s", exc)
            if status_msg:
                await status_msg.edit_text(
                    f"⚠️ opencode returned {exc.response.status_code}"
                )
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("debate command failed")
            if status_msg:
                await status_msg.edit_text(f"⚠️ {type(exc).__name__}: {exc}")
            return

        if status_msg:
            try:
                await status_msg.delete()
            except Exception:  # noqa: BLE001
                pass

        if tracker and tracker.error:
            await send_bot(ctx.bot, chat_id, f"⚠️ {tracker.error}")
            return
        if not answer:
            await send_bot(ctx.bot, chat_id, "(the debate returned nothing)")
            return
        await send_answer(ctx.bot, chat_id, answer, reply_to=update.message.message_id)


async def handle_ask(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        await update.message.reply_text(
            f"Not authorized. This chat id: {update.effective_chat.id}"
        )
        return

    text = update.message.text or ""
    prompt = " ".join(ctx.args).strip() if text.startswith("/ask") else text.strip()
    has_attachment = bool(collect_attachments(update))
    if not prompt and not has_attachment:
        await update.message.reply_text("Usage : /ask <question>")
        return

    chat_id = update.effective_chat.id
    lock = locks.setdefault(chat_id, asyncio.Lock())
    if lock.locked():
        await update.message.reply_text(
            "A task is already running. Use /stop to interrupt it."
        )
        return

    async with lock:
        session_id, is_new = await get_session(chat_id)

        # Attachments (photo/document): download before the prompt.
        attachments = collect_attachments(update)
        files: list[dict] = []
        if attachments:
            for a in attachments:
                f = await download_attachment(ctx.bot, a["file_id"], a["filename"], a["mime"])
                if f:
                    files.append(f)
            if files:
                prompt += (
                    "\n\n(attachment(s) provided by the user: "
                    + ", ".join(f["filename"] for f in files)
                    + ")"
                )
        if not prompt.strip():
            prompt = "Analyse the provided attachment and answer."

        # Memory: only inject at the start of a session, otherwise the
        # contexte de la conversation en cours suffit et l'injection parasite.
        full_prompt = prompt
        recalled = 0
        if MEMORY_ENABLED and is_new:
            block = memory.context_block(chat_id, prompt, MEMORY_TOP)
            if block:
                recalled = block.count("] Q:")
                full_prompt = f"{block}\n\n{prompt}"
            # RAG: indexed documents relevant to the question.
            doc_block = rag.context_block(chat_id, prompt, MEMORY_TOP)
            if doc_block:
                full_prompt = f"{doc_block}\n\n{full_prompt}"

        status_msg = None
        if SHOW_PROGRESS:
            intro = "⏳ <b>starting</b>"
            if recalled:
                intro += f"\n<i>{recalled} previous exchange(s) recalled</i>"
            status_msg = await update.message.reply_text(
                intro, parse_mode=ParseMode.HTML
            )
            track_message(chat_id, status_msg.message_id)

        try:
            answer, tracker = await run_prompt(
                ctx.bot, chat_id, full_prompt, session_id, agent_for(chat_id), status_msg,
                files=files,
            )
        except httpx.HTTPStatusError as exc:
            answer, tracker = "", None
            log.error("erreur HTTP: %s", exc)
            if status_msg:
                await status_msg.edit_text(
                    f"⚠️ opencode returned {exc.response.status_code}"
                )
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("prompt failed")
            if status_msg:
                await status_msg.edit_text(f"⚠️ {type(exc).__name__}: {exc}")
            return

        if status_msg:
            try:
                await status_msg.delete()
            except Exception:  # noqa: BLE001
                pass

        if tracker and tracker.error:
            await send_bot(ctx.bot, chat_id, f"⚠️ {tracker.error}")
            return
        if not answer:
            await send_bot(ctx.bot, chat_id, "(no textual answer produced)")
            return

        await send_answer(ctx.bot, chat_id, answer, reply_to=update.message.message_id)

        if MEMORY_ENABLED:
            memory.add(chat_id, prompt, answer, session_id)


# --------------------------------------------------------------- scheduled jobs

# Number of automatic retries when a job fails.
JOB_RETRIES = int(os.environ.get("JOB_RETRIES", "1"))
JOB_RETRY_DELAY = float(os.environ.get("JOB_RETRY_DELAY", "60"))


async def run_job(job: dict) -> None:
    chat_id = job["chat_id"]
    session_id = await new_session(f"job-{job['name']}")
    log.info("job %s -> session %s", job["name"], session_id)

    app = job["_app"]
    answer, tracker = await run_prompt(
        app.bot, chat_id, job["prompt"], session_id, job.get("agent", DEFAULT_AGENT)
    )

    header = f"🕗 <b>{job['name']}</b>"
    if tracker and tracker.error:
        # Self-healing: retry once after a short delay.
        retries = int(job.get("retries", JOB_RETRIES))
        if retries > 0:
            log.warning("job %s failed (%s), retrying in %.0fs",
                        job["name"], tracker.error, JOB_RETRY_DELAY)
            await asyncio.sleep(JOB_RETRY_DELAY)
            retry_job = dict(job, retries=retries - 1)
            await run_job(retry_job)
            return
        await send_bot(
            app.bot,
            chat_id,
            f"{header}\n⚠️ {tracker.error}\n<i>(failed after {JOB_RETRIES + 1} attempt(s))</i>",
            parse_mode=ParseMode.HTML,
        )
        return
    if not answer:
        return

    # A watch job replying "RAS" (nothing to report) must not spam: skip it.
    if answer.strip().upper() in ("RAS", "RAS.", "RIEN À SIGNALER", "TOUT EST NORMAL"):
        log.info("job %s : RAS, pas d'envoi", job["name"])
        return

    # Telegram channel (can be disabled via /notify telegram off).
    try:
        from ocnotify import telegram_enabled  # noqa: PLC0415

        if telegram_enabled(chat_id):
            await send_bot(app.bot, chat_id, header, parse_mode=ParseMode.HTML)
            await send_answer(app.bot, chat_id, answer)
    except Exception as exc:  # noqa: BLE001
        log.warning("job Telegram send failed: %s", exc)

    # Web Push: short summary (the full report stays in the dashboard).
    try:
        import time as _time  # noqa: PLC0415

        summary = " ".join(answer.strip().split())
        if len(summary) > 220:
            summary = summary[:217].rstrip() + "…"
        notify_push(
            f"🕗 {job['name']}",
            summary,
            chat_id=chat_id,
            topic="job",
            dedup_key=f"job:{job['name']}:{_time.strftime('%Y-%m-%d')}",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("job push failed: %s", exc)


# ---------------------------------------------------------------- commandes


async def cmd_id(update: Update, _ctx) -> None:
    await update.message.reply_text(f"chat id : {update.effective_chat.id}")


async def cmd_start(update: Update, _ctx) -> None:
    if not authorized(update):
        await update.message.reply_text(
            f"Not authorized. This chat id: {update.effective_chat.id}"
        )
        return
    await update.message.reply_text(
        "opencode est en ligne.\n\n"
        "/ask <question> — poser une question\n"
        "/new — nouvelle session\n"
        "/agent [nom] — changer d'agent\n"
        "/stop — interrompre\n"
        "/memory — memory status\n"
        "/forget — clear memory\n"
        "/clear — effacer les messages du bot dans ce chat\n"
        "/jobs — scheduled runs\n"
        + ("\nUn message simple suffit, sans commande." if PLAIN_TEXT_IS_ASK else "")
    )


async def cmd_new(update: Update, _ctx) -> None:
    if not authorized(update):
        return
    sid, _ = await get_session(update.effective_chat.id, force_new=True)
    await update.message.reply_text(f"Nouvelle session : {sid}")


async def cmd_session(update: Update, _ctx) -> None:
    if not authorized(update):
        return
    sid, _ = await get_session(update.effective_chat.id)
    await update.message.reply_text(sid)


async def cmd_agent(update: Update, ctx) -> None:
    if not authorized(update):
        return
    chat_id = update.effective_chat.id
    available = await list_agents()
    if not ctx.args:
        current = agent_for(chat_id) or "(server default)"
        await update.message.reply_text(
            f"Agent actuel : {current}\n"
            f"Disponibles : {', '.join(available) or 'inconnu'}\n\n"
            "/agent <name> to switch, /agent default to reset."
        )
        return
    name = ctx.args[0].strip()
    if name in ("default", "reset", "-"):
        update_chat(chat_id, agent="")
        await update.message.reply_text("Agent reset.")
        return
    if available and name not in available:
        await update.message.reply_text(
            f"Agent inconnu : {name}\nDisponibles : {', '.join(available)}"
        )
        return
    update_chat(chat_id, agent=name)
    await update.message.reply_text(f"Agent : {name}. /new pour une session propre.")


async def cmd_stop(update: Update, _ctx) -> None:
    if not authorized(update):
        return
    sid = chat_state(update.effective_chat.id).get("session")
    if not sid:
        await update.message.reply_text("Rien en cours.")
        return
    try:
        await abort(sid)
        await update.message.reply_text("Interrompu.")
    except Exception as exc:  # noqa: BLE001
        await update.message.reply_text(f"Échec de l'interruption : {exc}")


async def cmd_memory(update: Update, _ctx) -> None:
    if not authorized(update):
        return
    chat_id = update.effective_chat.id
    n = memory.count(chat_id)
    state = "on" if MEMORY_ENABLED else "off"
    await update.message.reply_text(
        f"Memory {state}: {n} exchange(s) stored.\n"
        f"The {MEMORY_TOP} most relevant are injected at the start of a "
        "nouvelle session.\n\n/forget pour tout effacer."
    )


async def cmd_forget(update: Update, _ctx) -> None:
    if not authorized(update):
        return
    removed = memory.clear(update.effective_chat.id)
    await update.message.reply_text(f"{removed} exchange(s) cleared.")


async def cmd_clear(update: Update, ctx) -> None:
    if not authorized(update):
        return
    chat_id = update.effective_chat.id

    if not CLEAR_ALLOWED:
        await update.message.reply_text(
            "/clear is disabled: no allowlist configured "
            "(variable CLEAR_ALLOWED_CHAT_IDS)."
        )
        return
    if chat_id not in CLEAR_ALLOWED:
        await update.message.reply_text(
            f"/clear is restricted to allowed channels. {chat_id} is not "
            "dans l'allowlist."
        )
        return

    ids = list(chat_state(chat_id).get("messages", []))
    confirm = (ctx.args and ctx.args[0].lower() in ("confirm", "yes", "oui")) or None

    if not confirm:
        n = len(ids)
        if n == 0:
            await update.message.reply_text("No bot message to delete.")
            return
        await update.message.reply_text(
            f"⚠️ Effacer {n} message(s) du bot dans ce channel ?\n"
            "Irreversible. Reply /clear confirm to proceed."
        )
        return

    deleted = 0
    failed = 0
    for mid in ids:
        try:
            await update.message.chat.delete_message(mid)
            deleted += 1
        except BadRequest:
            failed += 1  # too old (>48h), already deleted, or not deletable
        except Exception:  # noqa: BLE001
            failed += 1
    if ids:
        update_chat(chat_id, messages=[])
    msg = (
        f"Deleted {deleted} bot message(s)."
        + (f" ({failed} introuvable(s)/trop ancien(s))" if failed else "")
    )
    await update.message.reply_text(msg)


async def cmd_jobs(update: Update, _ctx) -> None:
    if not authorized(update):
        return
    jobs = load_jobs(JOBS_FILE)
    if not jobs:
        await update.message.reply_text(
            f"No scheduled run.\nExpected file: {JOBS_FILE}"
        )
        return
    lines = []
    for j in jobs:
        mark = "" if j.get("enabled", True) else " (disabled)"
        days = ",".join(j.get("days", ["tous"]))
        lines.append(f"• {j['name']} — {j['time']} [{days}]{mark}")
    await update.message.reply_text(
        "Scheduled runs:\n" + "\n".join(lines) + "\n\n/run <name> to trigger."
    )


async def cmd_run(update: Update, ctx) -> None:
    if not authorized(update):
        return
    if not ctx.args:
        await update.message.reply_text("Usage : /run <nom du job>")
        return
    name = ctx.args[0]
    job = next((j for j in load_jobs(JOBS_FILE) if j["name"] == name), None)
    if not job:
        await update.message.reply_text(f"Job inconnu : {name}")
        return
    await update.message.reply_text(f"Lancement de {name}…")
    job = dict(job, _app=ctx.application, chat_id=update.effective_chat.id)
    asyncio.create_task(run_job(job))


# ---------------------------------------------------------------- veille


async def cmd_notify(update: Update, ctx) -> None:
    """Manage proactive notifications: /notify [push|telegram] [on|off]."""
    if not authorized(update):
        return
    chat_id = update.effective_chat.id
    args = [a.lower() for a in (ctx.args or [])]
    if not args:
        from ocnotify import push_enabled, telegram_enabled  # noqa: PLC0415

        state = lambda b: "on" if b else "off"
        await update.message.reply_text(
            "Notifications :\n"
            f"• Web Push : {state(push_enabled(chat_id))}\n"
            f"• Telegram : {state(telegram_enabled(chat_id))}\n\n"
            "/notify push on|off — notifications hors app\n"
            "/notify telegram on|off — messages Telegram\n"
            "Heures calmes : 23h–7h (pas de push)."
        )
        return
    if len(args) < 2 or args[0] not in ("push", "telegram") or args[1] not in ("on", "off"):
        await update.message.reply_text("Usage : /notify push|telegram on|off")
        return
    from ocnotify import set_preference  # noqa: PLC0415

    set_preference(chat_id, f"notify.{args[0]}", args[1])
    await update.message.reply_text(f"Notifications {args[0]} : {args[1]}.")


async def cmd_watch(update: Update, ctx) -> None:
    """Manage the watch list: /watch, /watch add <kind> <target>, /watch rm <id>."""
    if not authorized(update):
        return
    chat_id = update.effective_chat.id
    if watch is None:
        await update.message.reply_text("Veille inactive (Postgres injoignable).")
        return

    args = ctx.args or []
    if not args:
        items = watch.list()
        if not items:
            await update.message.reply_text(
                "No watched item.\n"
                "/watch add web <url> — alerte si la page change\n"
                "/watch add mail <query> — watch your mail\n"
                "/watch add github <owner/repo> — PR ouvertes\n"
                "/watch add stock <SYMBOLE>[:niveaux] — franchissement + volume\n"
                "   ex. /watch add stock AAPL:180:200:240\n"
                "/watch rm <id> — retirer un item"
            )
            return
        lines = [
            f"• {i['id']} — {i['kind']} : {i['target']}"
            for i in items
        ]
        await update.message.reply_text("Veille active :\n" + "\n".join(lines))
        return

    if args[0] == "add" and len(args) >= 3:
        kind, target = args[1], " ".join(args[2:])
        if kind not in ("web", "mail", "github", "moodle", "proxmox", "health", "stock"):
            await update.message.reply_text(
                f"Type inconnu : {kind}. Types : web, mail, github, moodle, proxmox, health, stock."
            )
            return
        watch.add(kind, target)
        await update.message.reply_text(f"Watch added: {kind} → {target}")
        return

    if args[0] in ("rm", "remove", "del") and len(args) >= 2:
        try:
            item_id = int(args[1])
        except ValueError:
            await update.message.reply_text("ID invalide.")
            return
        watch.remove(item_id)
        await update.message.reply_text(f"Item {item_id} removed.")
        return

    await update.message.reply_text(
        "Usage : /watch (liste) | /watch add <kind> <target> | /watch rm <id>"
    )


async def cmd_rag(update: Update, ctx) -> None:
    """Index or search documents: /rag index <title> <text> | /rag <query>."""
    if not authorized(update):
        return
    chat_id = update.effective_chat.id
    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "Usage :\n"
            "/rag <query> — search indexed documents\n"
            "/rag index <titre> <texte> — indexe un document"
        )
        return

    if args[0] == "index" and len(args) >= 3:
        title = args[1]
        body = " ".join(args[2:])
        rag.index(chat_id, title, body, source="telegram")
        await update.message.reply_text(f"Document indexed: {title}")
        return

    query = " ".join(args)
    hits = rag.search(chat_id, query, top=5)
    if not hits:
        await update.message.reply_text(f"No document found for: {query}")
        return
    lines = []
    for h in hits:
        when = time.strftime("%d/%m/%Y", time.localtime(h.get("ts", 0)))
        lines.append(f"• [{when}] {h['title']}\n  {h['body'][:200]}")
    await update.message.reply_text(
        f"Documents pertinents pour « {query} » :\n\n" + "\n".join(lines)
    )


# ---------------------------------------------------------------- cycle de vie


async def on_startup(app: Application) -> None:
    global http, bus, scheduler, watch
    auth = (OPENCODE_USERNAME, OPENCODE_PASSWORD) if OPENCODE_PASSWORD else None
    http = httpx.AsyncClient(auth=auth, timeout=60)

    bus = EventBus(http, OPENCODE_URL)
    bus.start()

    # Table d'historique des notifications (idempotent, silencieux si PG absent).
    try:
        from ocnotify import ensure_schema  # noqa: PLC0415

        ensure_schema()
        log.info("notifications: schema ready")
    except Exception as exc:  # noqa: BLE001
        log.warning("notifications schema unavailable: %s", exc)

    try:
        r = await http.get(f"{OPENCODE_URL}/global/health", timeout=10)
        log.info("serveur opencode : %s", r.json())
        log.info("agents : %s", ", ".join(await list_agents()) or "aucun")
    except Exception as exc:  # noqa: BLE001
        log.warning("serveur injoignable sur %s : %s", OPENCODE_URL, exc)

    async def runner(job: dict) -> None:
        await run_job(dict(job, _app=app))

    scheduler = Scheduler(JOBS_FILE, JOBS_STATE, runner)
    scheduler.start()
    jobs = load_jobs(JOBS_FILE)

    # Continuous watch: one loop per allowed chat.
    for cid in ALLOWED:
        w = Watch(app.bot, cid)
        if w.list() or True:  # start the loop even with no item (ready to add)
            watch = w
            asyncio.create_task(w.run())
            log.info("veille active pour chat %s", cid)
            break

    log.info("memory: %s | jobs: %d", "on" if MEMORY_ENABLED else "off", len(jobs))


async def on_shutdown(_app: Application) -> None:
    if scheduler:
        await scheduler.stop()
    if bus:
        await bus.stop()
    if http:
        await http.aclose()


def main() -> None:
    if not ALLOWED:
        log.warning(
            "ALLOWED_CHAT_IDS est vide : n'importe qui trouvant ce bot pilote "
            "opencode sur cette machine."
        )

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )
    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("session", cmd_session))
    app.add_handler(CommandHandler("agent", cmd_agent))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("memory", cmd_memory))
    app.add_handler(CommandHandler("forget", cmd_forget))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("jobs", cmd_jobs))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("notify", cmd_notify))
    app.add_handler(CommandHandler("rag", cmd_rag))
    app.add_handler(CommandHandler("ask", handle_ask))
    app.add_handler(CommandHandler("debate", handle_debate))
    if PLAIN_TEXT_IS_ASK:
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ask))
    # Messages with an attachment (photo/document): treat them as a
    # question, an optional caption serving as the prompt.
    app.add_handler(
        MessageHandler(
            (filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND, handle_ask
        )
    )

    log.info("listening on Telegram, opencode at %s", OPENCODE_URL)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
