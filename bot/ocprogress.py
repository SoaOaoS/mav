"""Turns a session's event stream into a readable status line.

Used by the worker to follow a routine run until the session is idle (and to
detect errors or a stuck session). Updates are rate-limited: rendered at most
once per interval, and only if the text changed.
"""

from __future__ import annotations

import asyncio
import html
import logging
import time

log = logging.getLogger("ocprogress")

EDIT_INTERVAL = 3.0  # seconds between status message edits

# Readable labels for common tools. MCP servers are prefixed by their
# name (github_*, notion_*); we handle them generically.
TOOL_LABELS = {
    "websearch": "searching the web",
    "webfetch": "reading a page",
    "read": "reading a file",
    "write": "writing file",
    "edit": "editing a file",
    "bash": "running a command",
    "grep": "searching the code",
    "glob": "listing files",
    "task": "delegating to a sub-agent",
    "todowrite": "updating the plan",
    "apply_patch": "applying a patch",
}


def tool_label(name: str) -> str:
    if name in TOOL_LABELS:
        return TOOL_LABELS[name]
    if "_" in name:
        server, _, rest = name.partition("_")
        return f"{server}: {rest.replace('_', ' ')}"
    return name


def human_delay(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


class ProgressTracker:
    """Accumulates a running session's state and produces the text to display."""

    def __init__(self, agent: str = "") -> None:
        self.agent = agent
        self.started = time.monotonic()
        self.current: str | None = None
        self.steps = 0
        self.tool_counts: dict[str, int] = {}
        self.last_tool: str | None = None
        self.compacting = False
        self.error: str | None = None
        self.done = False
        self.text_chars = 0

    # ------------------------------------------------------------- ingestion

    def feed(self, event: dict) -> None:
        etype = event.get("type", "")
        props = event.get("properties") or {}

        if etype == "session.next.step.started":
            self.steps += 1
            self.current = "thinking"
        elif etype == "session.next.tool.called":
            tool = props.get("tool", "?")
            self.last_tool = tool
            self.tool_counts[tool] = self.tool_counts.get(tool, 0) + 1
            self.current = tool_label(tool)
        elif etype == "session.next.tool.failed":
            self.current = f"{tool_label(props.get('tool', '?'))} — failed, retrying"
        elif etype in ("session.next.text.started", "session.next.text.delta"):
            self.current = "writing the answer"
            self.text_chars += len(props.get("delta", "") or "")
        elif etype == "session.next.reasoning.started":
            self.current = "thinking"
        elif etype == "session.next.compaction.started":
            self.compacting = True
            self.current = "compacting the context"
        elif etype == "session.next.compaction.ended":
            self.compacting = False
        elif etype == "session.next.retried":
            self.current = "retrying"
        elif etype == "session.error":
            err = props.get("error") or {}
            name = err.get("name") or err.get("_tag") or "error"
            self.error = str(name)
            self.done = True
        elif etype == "session.idle":
            self.done = True

    # --------------------------------------------------------------- render

    def render(self) -> str:
        elapsed = human_delay(time.monotonic() - self.started)
        if self.error:
            return f"⚠️ {html.escape(self.error)} — after {elapsed}"

        who = f"🤖 <b>{html.escape(self.agent)}</b>  ·  " if self.agent else ""
        head = f"{who}⏳ <b>{html.escape(self.current or 'starting')}</b>  ·  {elapsed}"

        detail = []
        if self.steps > 1:
            detail.append(f"{self.steps} steps")
        total_tools = sum(self.tool_counts.values())
        if total_tools:
            top = sorted(self.tool_counts.items(), key=lambda x: -x[1])[:3]
            detail.append(
                ", ".join(
                    f"{tool_label(t)} ×{n}" if n > 1 else tool_label(t) for t, n in top
                )
            )
        if self.compacting:
            detail.append("context saturated, compacting")

        if not detail:
            return head
        return head + "\n<i>" + html.escape(" · ".join(detail)) + "</i>"


async def follow(
    queue: asyncio.Queue,
    tracker: ProgressTracker,
    on_update,
    idle_timeout: float | None = None,
) -> ProgressTracker:
    """Consumes the event queue until session.idle.

    on_update(text) is called at most once every EDIT_INTERVAL seconds,
    and only if the rendering changed.
    """
    last_edit = 0.0
    last_text = ""

    while not tracker.done:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=idle_timeout)
        except asyncio.TimeoutError:
            tracker.error = "no events received (session stuck?)"
            tracker.done = True
            break

        tracker.feed(event)

        now = time.monotonic()
        if tracker.done:
            break
        if now - last_edit >= EDIT_INTERVAL:
            text = tracker.render()
            if text != last_text:
                last_text = text
                last_edit = now
                try:
                    await on_update(text)
                except Exception as exc:  # noqa: BLE001
                    log.debug("status edit skipped: %s", exc)

    return tracker
