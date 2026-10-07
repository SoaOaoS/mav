"""The daily briefing: one short message that starts (or ends) the day.

It gathers what Mav already knows — facts about you, today's calendar, the
alerts and routine reports of the last day, drafts waiting for you, your
interests — and hands
it to the model as hidden context, with one visible line ("Brief me on my
day"). The model adds what only it can fetch (the weather where you live).

Shared by the worker (scheduled) and the web app ("Brief me now"). The
gathering is pure and tolerant: any missing source is simply left out.
"""

from __future__ import annotations

import time
from datetime import datetime

KIND = "briefing"
NAME = "Daily briefing"
VISIBLE_PROMPT = "Brief me on my day."
DEFAULT_TIME = "07:30"

INSTRUCTIONS = """\
Write my daily briefing from the context below. Rules:
- Start with a one-line greeting for {when} ({date}).
- Weather: if you know where I live (facts), look up today's forecast there
  and give it in one line (temperature range, rain or not, what to wear).
  If you do not know where I live, skip it and ask me once at the end.
- "Today": my calendar below, in time order (skip if empty). Point out a
  tight gap or an early start; never invent events.
- "Happened since yesterday": the alerts and routine reports below, one line
  each, most important first. Skip the section if there are none.
- "Needs you": drafts waiting for my approval and anything that calls for an
  action. Skip if nothing.
- One short "Worth a look" item tied to my interests, only if you have
  something concrete.
- At most ~12 short lines, skimmable, no filler. Write in the language of my
  facts and past messages (English if unsure).
"""


def _ago(ts: int, now: float) -> str:
    h = int((now - ts) // 3600)
    return "just now" if h < 1 else f"{h} h ago"


def build_context(
    *,
    facts: list[dict] | None = None,
    notifications: list[dict] | None = None,
    drafts: int = 0,
    interests: list[dict] | None = None,
    events: list[str] | None = None,
    now: float | None = None,
    window_h: int = 24,
) -> str:
    """The hidden context block for the model (plain text)."""
    now = now or time.time()
    dt = datetime.fromtimestamp(now)
    when = "this morning" if dt.hour < 12 else "this afternoon" if dt.hour < 18 else "this evening"
    lines = [
        "<daily-briefing>",
        INSTRUCTIONS.format(when=when, date=dt.strftime("%A %d %B %Y")),
    ]

    facts = [f.get("fact") for f in (facts or []) if f.get("fact")]
    lines.append("## What I know about you")
    lines += [f"- {f}" for f in facts[:15]] or ["- (nothing yet)"]

    if events is not None:  # only when a calendar is connected
        lines.append("")
        lines.append("## Today's calendar")
        lines += events or ["- (nothing scheduled)"]

    recent = [
        n for n in (notifications or [])
        if now - int(n.get("ts") or 0) <= window_h * 3600
        and n.get("topic") != KIND  # never brief about the previous briefing
    ]
    lines.append("")
    lines.append(f"## Alerts and routine reports (last {window_h} h)")
    if recent:
        for n in recent[:12]:
            body = " ".join(str(n.get("body") or "").split())[:200]
            lines.append(f"- [{_ago(int(n.get('ts') or 0), now)}] {n.get('title') or ''}: {body}")
    else:
        lines.append("- (none)")

    lines.append("")
    lines.append("## Waiting for you")
    lines.append(f"- {drafts} draft(s) to approve" if drafts else "- (nothing)")

    labels = [i.get("label") or i.get("key") for i in (interests or []) if not i.get("muted")]
    if labels:
        lines.append("")
        lines.append("## Your interests")
        lines.append("- " + ", ".join(str(x) for x in labels[:8]))

    lines.append("</daily-briefing>")
    return "\n".join(lines)


def is_briefing(job: dict) -> bool:
    return (job or {}).get("kind") == KIND


def default_job(time_hm: str = DEFAULT_TIME, agent: str = "assistant") -> dict:
    """The routine that sends the briefing every day."""
    return {
        "name": NAME,
        "kind": KIND,
        "description": "Weather, what happened, what needs you — every day.",
        "prompt": VISIBLE_PROMPT,
        "agent": agent,
        "enabled": True,
        "time": time_hm,
        "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    }
