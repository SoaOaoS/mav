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
from datetime import datetime
from pathlib import Path

import httpx

import ocevents
from ocbus import EventBus
from occonditions import should_run
from ocjobs import DAYS, Scheduler, load_jobs
from ocmemory import Memory
from ocnotify import ensure_schema, flush_digest, notify
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

# Digest: collect alerts below the proactivity bar and send one recap per day
# at this hour (0-23), instead of a dozen small pushes. DIGEST_HOUR=0 disables.
DIGEST_HOUR = int(os.environ.get("DIGEST_HOUR", "19"))
DIGEST_STATE = BOT_DIR / "digest_state.json"

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


def _resolve_condition(job: dict) -> tuple[bool, str]:
    """Evaluate a routine's ``skip_if`` without touching the model.

    The `source` is the condition's own literal when present; otherwise an
    empty source makes Mav run anyway (unknown = do not silently skip a
    report), except for an explicit "only if X" which is skipped when unknown.
    """
    cond = job.get("skip_if")
    if not cond:
        return True, ""
    source = str(cond.get("source") or "")
    day = DAYS[datetime.now().weekday()]
    try:
        ok = should_run(job, source=source, weekday=day)
    except Exception as exc:  # noqa: BLE001
        log.warning("condition for %s failed (%s), running anyway", job.get("name"), exc)
        ok = True
    why = "" if ok else f"condition {cond.get('type', '?')} not met"
    return ok, why


async def run_job(job: dict) -> None:
    name = job["name"]
    ok, why = _resolve_condition(job)
    if not ok:
        log.info("routine %s skipped: %s", name, why)
        return
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

    # Directives ([[chart:…]], [[file:…]]) and images are rendered in the
    # routine chat but cannot show in plain-text notifications: drop them.
    summary = plain_summary(answer)
    notify(
        f"🔁 {name}",
        summary,
        chat_id=OWNER_ID,
        topic="routine",
        url=f"./#chat/{session_id}",
        dedup_key=f"routine:{name}:{time.strftime('%Y-%m-%d %H:%M')}",
    )


# ---------------------------------------------------------------- events


async def run_events_once() -> int:
    """Fire every routine subscribed to the events received since last tick.

    Events are consumed even when no routine matches, so they do not pile up.
    Returns how many routines were launched.
    """
    events = ocevents.pending()
    if not events:
        return 0
    jobs = load_jobs(JOBS_FILE)
    fired = 0
    for event in events:
        for job in jobs:
            if job.get("enabled", True) and ocevents.matches(job, event):
                log.info("event %s/%s -> routine %s", event.get("kind"), event.get("id"), job["name"])
                asyncio.create_task(_safe_run_job(job))
                fired += 1
        ocevents.consume(event["id"])
    return fired


async def _safe_run_job(job: dict) -> None:
    try:
        await run_job(job)
    except Exception:  # noqa: BLE001
        log.exception("event-triggered routine %s failed", job.get("name"))


async def events_loop() -> None:
    while True:
        try:
            await run_events_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("events loop error")
        await asyncio.sleep(30)


# ---------------------------------------------------------------- digest


def _digest_time(now: datetime) -> bool:
    if DIGEST_HOUR <= 0 or now.hour != DIGEST_HOUR:
        return False
    try:
        import json  # noqa: PLC0415

        last = json.loads(DIGEST_STATE.read_text()).get("last")
    except Exception:
        last = None
    return last != now.strftime("%Y-%m-%d")


def _mark_digest(now: datetime) -> None:
    try:
        import json  # noqa: PLC0415

        DIGEST_STATE.write_text(json.dumps({"last": now.strftime("%Y-%m-%d")}))
    except Exception:
        pass


async def digest_loop() -> None:
    """Once a day, send the collected low-priority alerts as one recap."""
    while True:
        try:
            now = datetime.now()
            if _digest_time(now):
                res = flush_digest(OWNER_ID)
                _mark_digest(now)
                if res.get("count"):
                    log.info("digest sent: %d item(s)", res["count"])
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("digest loop error")
        await asyncio.sleep(60)


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

    try:
        ocevents.ensure_schema()
    except Exception as exc:  # noqa: BLE001
        log.warning("events schema unavailable: %s", exc)

    scheduler = Scheduler(JOBS_FILE, JOBS_STATE, runner)
    scheduler.start()
    watch = Watch(OWNER_ID)
    watch_task = asyncio.create_task(watch.run())
    events_task = asyncio.create_task(events_loop())
    digest_task = asyncio.create_task(digest_loop())
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
    events_task.cancel()
    digest_task.cancel()
    await scheduler.stop()
    await bus.stop()
    await http.aclose()


if __name__ == "__main__":
    asyncio.run(main())
