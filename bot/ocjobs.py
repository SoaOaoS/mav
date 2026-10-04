"""Scheduled runs.

jobs.json file (editable from the dashboard, Automations page):

[
  {
    "name": "brief",
    "time": "08:00",
    "days": ["mon","tue","wed","thu","fri"],
    "agent": "research",
    "prompt": "Summarize the open PRs on my repos and the failing CI.",
    "enabled": true
  },
  {
    "name": "loyer",
    "time": "09:00",
    "days_of_month": [1, 15],     # fixed days of the month
    "prompt": "Remind me to pay the rent."
  },
  {
    "name": "revue mensuelle",
    "time": "18:00",
    "last_day_of_month": true,    # last day of every month
    "prompt": "Monthly review."
  }
]

Deliberately not full cron: a time (or an interval), days, and the two
monthly shapes above are enough for everyday automations, and the format stays
readable without documentation. `skip_if` (see bot/occonditions.py) turns a job
into a conditional one: it is skipped when the condition is not met.
"""

from __future__ import annotations

import asyncio
import calendar
import json
import logging
import re
import time as _time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("ocjobs")

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def load_jobs(path: Path) -> list[dict]:
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return []
    except Exception as exc:  # noqa: BLE001
        log.error("jobs.json unreadable: %s", exc)
        return []
    if not isinstance(data, list):
        log.error("jobs.json must contain a list")
        return []
    return [j for j in data if validate(j)]


def plain_summary(answer: str, limit: int = 220) -> str:
    """Strip to a short, plain-text summary for notifications.

    Answers may carry dashboard-only directives ([[chart:SPY:1mo]],
    [[file:rapport.md]]) and images; those must not leak into the plain-text
    notification and inbox summary, which cannot render them.
    """
    text = re.sub(r"\[\[(?:chart|file|download):[^\]]*\]\]", " ", answer or "", flags=re.I)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = " ".join(re.sub(r"[*_`#>|]+", "", text).split())
    if limit and len(text) > limit:
        text = text[: limit - 3].rstrip() + "…"
    return text


def interval(job: dict) -> int:
    """Repeat interval in minutes (0 = runs at a fixed time instead)."""
    try:
        return max(0, int(job.get("every_minutes") or 0))
    except (TypeError, ValueError):
        return 0


def days_of_week(job: dict) -> list[str]:
    """The weekday filter (empty = every day, so monthly jobs apply too)."""
    raw = job.get("days")
    if raw is None:
        raw = job.get("days_of_week")
    return [d for d in (raw or []) if d in DAYS]


def days_of_month(job: dict) -> list[int]:
    """Fixed days of the month (1…31), ignored when empty."""
    out = []
    for d in job.get("days_of_month") or []:
        try:
            d = int(d)
        except (TypeError, ValueError):
            continue
        if 1 <= d <= 31:
            out.append(d)
    return out


def last_day_of_month(job: dict) -> bool:
    return bool(job.get("last_day_of_month"))


def monthly(job: dict) -> bool:
    return bool(days_of_month(job) or last_day_of_month(job))


def _matches_day(job: dict, now: datetime) -> bool:
    """Weekday rules and, when given, monthly rules (both must fit)."""
    dom, last, dow = days_of_month(job), last_day_of_month(job), days_of_week(job)
    if not dom and not last:
        return not dow or DAYS[now.weekday()] in dow
    if dow and DAYS[now.weekday()] not in dow:
        return False
    in_month = now.day in dom or (
        last and now.day == calendar.monthrange(now.year, now.month)[1]
    )
    return in_month


def on_event(job: dict) -> bool:
    """An event-triggered job has no time: it runs when the event arrives."""
    return bool(job.get("on_event"))


def validate(job: dict) -> bool:
    name = job.get("name", "?")
    if not job.get("name"):
        log.error("job without a name")
        return False
    if not interval(job) and not on_event(job) and not TIME_RE.match(str(job.get("time", ""))):
        log.error("job %s: invalid 'time' (expected HH:MM)", name)
        return False
    if not job.get("prompt"):
        log.error("job %s: empty 'prompt'", name)
        return False
    raw_days = job.get("days", job.get("days_of_week")) or []
    bad = [d for d in raw_days if d not in DAYS]
    if bad:
        log.error("job %s: unknown days %s", name, bad)
        return False
    raw_dom = job.get("days_of_month")
    if raw_dom is not None and not days_of_month(job) and raw_dom:
        log.error("job %s: 'days_of_month' must list days 1…31", name)
        return False
    return True


def snoozed(job: dict, now: datetime | None = None) -> bool:
    """A snoozed routine keeps its definition but does not fire until then."""
    try:
        until = int(job.get("snooze_until") or 0)
    except (TypeError, ValueError):
        until = 0
    if until <= 0:
        return False
    current = now.timestamp() if now else _time.time()
    return until > current


def due(job: dict, now: datetime, last_run: str | None) -> bool:
    if not job.get("enabled", True):
        return False
    if on_event(job):
        return False  # event jobs are fired by the events loop, never by the clock
    if snoozed(job, now):
        return False
    if not _matches_day(job, now):
        return False
    every = interval(job)
    if every:
        if not last_run:
            return True
        try:
            last = datetime.strptime(last_run, "%Y-%m-%d %H:%M")
        except ValueError:
            return True
        return (now - last).total_seconds() >= every * 60 - 30
    if now.strftime("%H:%M") != job["time"]:
        return False
    return last_run != now.strftime("%Y-%m-%d %H:%M")


class Scheduler:
    """Loops once a minute and fires due jobs.

    The last-run state is persisted: a restart at 08:00:30 must not replay the
    08:00 brief.
    """

    def __init__(self, jobs_path: Path, state_path: Path, runner):
        self.jobs_path = Path(jobs_path)
        self.state_path = Path(state_path)
        self.runner = runner  # async (job) -> None
        self._task: asyncio.Task | None = None

    def _state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text())
        except Exception:
            return {}

    def _mark(self, name: str, stamp: str) -> None:
        state = self._state()
        state[name] = stamp
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(state, indent=1))
        except Exception as exc:  # noqa: BLE001
            log.warning("scheduler state not persisted: %s", exc)

    async def _tick(self) -> None:
        now = datetime.now()
        state = self._state()
        for job in load_jobs(self.jobs_path):
            name = job["name"]
            if due(job, now, state.get(name)):
                self._mark(name, now.strftime("%Y-%m-%d %H:%M"))
                log.info("firing job %s", name)
                asyncio.create_task(self._safe_run(job))

    async def _safe_run(self, job: dict) -> None:
        try:
            await self.runner(job)
        except Exception:  # noqa: BLE001
            log.exception("job %s failed", job.get("name"))

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("scheduler loop error")
            # Realign on the start of the next minute
            await asyncio.sleep(60 - datetime.now().second % 60)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
