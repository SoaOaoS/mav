#!/usr/bin/env python3
"""Mav background worker.

Runs everything that has to happen without the dashboard being open:
  - routines (jobs.json): each run happens in the routine's own chat in the
    dashboard ("Routine · <name>"), with what Mav remembers about you, then a
    push notification and an inbox entry link back to that chat;
  - "keep an eye on" (web pages, prices, news topics): a push alert only when
    something actually changes.

Chat itself goes through the dashboard (dashboard/server/mav_api.py).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
import time
from pathlib import Path

import httpx

from ocbus import EventBus
from ocjobs import Scheduler, load_jobs
from ocmemory import Memory
from ocnotify import ensure_schema, notify
from ocprogress import ProgressTracker, follow
from ocwatch import Watch

# --------------------------------------------------------------------- config

OPENCODE_URL = os.environ.get("OPENCODE_URL", "http://127.0.0.1:4096").rstrip("/")
OPENCODE_PASSWORD = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
OPENCODE_USERNAME = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")

MODEL = os.environ.get("OPENCODE_MODEL", "").strip()
DEFAULT_AGENT = os.environ.get("OPENCODE_AGENT", "").strip() or "assistant"

# The single owner of this Mav install: memory, watch items and preferences
# are attached to this id (older installs keep their previous id, and data).
OWNER_ID = int(os.environ.get("MAV_CHAT_ID", "0") or 0)

# Safety net: if no event arrives for this long, the job is considered stuck.
IDLE_TIMEOUT = float(os.environ.get("IDLE_TIMEOUT", "1800"))

BOT_DIR = Path(os.environ.get("BOT_DIR", Path(__file__).resolve().parent))
JOBS_FILE = Path(os.environ.get("JOBS_FILE", BOT_DIR / "jobs.json"))
JOBS_STATE = Path(os.environ.get("JOBS_STATE", BOT_DIR / "jobs_state.json"))

JOB_RETRIES = int(os.environ.get("JOB_RETRIES", "1"))
JOB_RETRY_DELAY = float(os.environ.get("JOB_RETRY_DELAY", "60"))

# Routine chats, shared with the dashboard (same title scheme).
CHAT_PREFIX = "dash: "
ROUTINE_PREFIX = "Routine · "

# Answers that mean "nothing to report": no push for those.
QUIET_ANSWERS = {"RAS", "RAS.", "NOTHING TO REPORT", "NOTHING TO REPORT.", "ALL CLEAR", "ALL CLEAR."}

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("mav-worker")

http: httpx.AsyncClient | None = None
bus: EventBus | None = None
memory = Memory(BOT_DIR / "memory.json")


# ------------------------------------------------------------- opencode calls


async def new_session(title: str) -> str:
    r = await http.post(f"{OPENCODE_URL}/session", json={"title": title}, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


async def routine_session(name: str) -> str:
    """The routine's chat in the dashboard, created on its first run."""
    title = CHAT_PREFIX + ROUTINE_PREFIX + name
    r = await http.get(f"{OPENCODE_URL}/session", timeout=30)
    r.raise_for_status()
    for s in r.json() or []:
        if s.get("title") == title:
            return s["id"]
    return await new_session(title)


async def agent_known(agent: str) -> bool:
    try:
        r = await http.get(f"{OPENCODE_URL}/agent", timeout=15)
        return any(a.get("name") == agent for a in r.json() or [])
    except Exception:  # noqa: BLE001
        return True


def extract_answer(payload: dict) -> str:
    texts = [
        (p.get("text") or "").strip()
        for p in payload.get("parts") or []
        if p.get("type") == "text" and not p.get("synthetic") and (p.get("text") or "").strip()
    ]
    return texts[-1] if texts else ""


async def last_assistant_text(session_id: str) -> str:
    r = await http.get(f"{OPENCODE_URL}/session/{session_id}/message", timeout=60)
    r.raise_for_status()
    for entry in reversed(r.json()):
        if (entry.get("info") or {}).get("role") == "assistant":
            text = extract_answer(entry)
            if text:
                return text
    return ""


async def run_prompt(session_id: str, prompt: str, agent: str) -> tuple[str, ProgressTracker]:
    """Send the prompt, follow the session until idle, return the answer."""
    queue = bus.subscribe(session_id)
    tracker = ProgressTracker(agent)
    body: dict = {"parts": [{"type": "text", "text": prompt}]}
    # Routines know what Mav remembers about you (facts + related exchanges).
    try:
        ctx = memory.context_block(OWNER_ID, prompt)
        if ctx:
            body["parts"].insert(0, {"type": "text", "text": ctx, "synthetic": True})
    except Exception as exc:  # noqa: BLE001
        log.debug("memory unavailable: %s", exc)
    if MODEL and "/" in MODEL:
        provider, model = MODEL.split("/", 1)
        body["model"] = {"providerID": provider, "modelID": model}
    if agent:
        body["agent"] = agent

    async def ignore(_text: str) -> None:
        return None

    try:
        r = await http.post(
            f"{OPENCODE_URL}/session/{session_id}/prompt_async", json=body, timeout=30
        )
        r.raise_for_status()
        await follow(queue, tracker, ignore, idle_timeout=IDLE_TIMEOUT)
        if tracker.error:
            return "", tracker
        return await last_assistant_text(session_id), tracker
    finally:
        bus.unsubscribe(session_id, queue)


# ------------------------------------------------------------- scheduled jobs


async def run_job(job: dict) -> None:
    name = job["name"]
    agent = job.get("agent") or DEFAULT_AGENT
    if not await agent_known(agent):
        agent = ""
    session_id = await routine_session(name)
    log.info("routine %s -> chat %s (helper %s)", name, session_id, agent or "default")

    answer, tracker = await run_prompt(session_id, job["prompt"], agent)

    if tracker.error:
        retries = int(job.get("retries", JOB_RETRIES))
        if retries > 0:
            log.warning("routine %s failed (%s), retrying in %.0fs", name, tracker.error, JOB_RETRY_DELAY)
            await asyncio.sleep(JOB_RETRY_DELAY)
            await run_job(dict(job, retries=retries - 1))
            return
        notify(
            f"⚠️ {name} failed",
            str(tracker.error)[:200],
            chat_id=OWNER_ID,
            topic="routine",
            url=f"./#chat/{session_id}",
            dedup_key=f"routine-fail:{name}:{time.strftime('%Y-%m-%d')}",
        )
        return

    if not answer or answer.strip().upper() in QUIET_ANSWERS:
        log.info("routine %s: nothing to report", name)
        return

    summary = " ".join(re.sub(r"[*_`#>|]+", "", answer).split())
    if len(summary) > 220:
        summary = summary[:217].rstrip() + "…"
    notify(
        f"🔁 {name}",
        summary,
        chat_id=OWNER_ID,
        topic="routine",
        url=f"./#chat/{session_id}",
        dedup_key=f"routine:{name}:{time.strftime('%Y-%m-%d %H:%M')}",
    )


# ---------------------------------------------------------------- lifecycle


async def main() -> None:
    global http, bus
    auth = (OPENCODE_USERNAME, OPENCODE_PASSWORD) if OPENCODE_PASSWORD else None
    http = httpx.AsyncClient(auth=auth, timeout=60)
    bus = EventBus(http, OPENCODE_URL)
    bus.start()

    try:
        ensure_schema()
    except Exception as exc:  # noqa: BLE001
        log.warning("notifications schema unavailable: %s", exc)

    try:
        r = await http.get(f"{OPENCODE_URL}/global/health", timeout=10)
        log.info("opencode engine: %s", r.json())
    except Exception as exc:  # noqa: BLE001
        log.warning("engine unreachable at %s: %s (will keep retrying)", OPENCODE_URL, exc)

    async def runner(job: dict) -> None:
        await run_job(job)

    scheduler = Scheduler(JOBS_FILE, JOBS_STATE, runner)
    scheduler.start()
    watch = Watch(OWNER_ID)
    watch_task = asyncio.create_task(watch.run())
    log.info("worker ready: %d routine(s), owner %s", len(load_jobs(JOBS_FILE)), OWNER_ID)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    await stop.wait()

    log.info("stopping")
    watch_task.cancel()
    await scheduler.stop()
    await bus.stop()
    await http.aclose()


if __name__ == "__main__":
    asyncio.run(main())
