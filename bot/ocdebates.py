"""Multi-agent debate threads, as written by the opencode debate tools.

The debate tools (new thread / post / read) live in the opencode configuration
and store every thread in a JSON file. This module only *reads* that file so the
web app can show a debate live, instead of only forwarding it to the
notification channel.

Layout of the file: ``{ "<thread id>": [ {id, thread, author, text, ts}, … ] }``.
The first message is written by "system" and holds the title and the question.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

# Where the file lives: MAV_DEBATE_FILE wins (tests, odd setups); otherwise the
# opencode config of the install user (~/.config/opencode/debates/threads.json).
# The dashboard runs as root, so we derive the home from BOT_DIR rather than
# from Path.home().
def _default_file() -> Path:
    explicit = os.environ.get("MAV_DEBATE_FILE")
    if explicit:
        return Path(explicit)
    home = os.environ.get("MAV_USER_HOME")
    if home:
        return Path(home) / ".config/opencode/debates/threads.json"
    bot_dir = Path(os.environ.get("BOT_DIR", Path.home() / "bot"))
    return bot_dir.parent / ".config/opencode/debates/threads.json"


DEBATE_FILE = _default_file()


def _load() -> dict:
    try:
        data = json.loads(DEBATE_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _parse_intro(messages: list[dict]) -> tuple[str, str]:
    """Pull the title and the question out of the first system message."""
    title, question = "", ""
    for m in messages:
        if m.get("author") != "system":
            continue
        text = str(m.get("text") or "").strip()
        # Written as "**title**\n\nQuestion : question".
        if text.startswith("**") and "**" in text[2:]:
            end = text.index("**", 2)
            title = text[2:end].strip()
            rest = text[end + 2:].strip()
            question = rest.split(":", 1)[1].strip() if ":" in rest else rest
        else:
            title = text.splitlines()[0].strip() if text else ""
            question = text
        break
    return title or "Debate", question


def _ts(m: dict) -> int:
    """Epoch seconds from an ISO timestamp (the tools store strings)."""
    raw = m.get("ts")
    if isinstance(raw, (int, float)):
        return int(raw)
    try:
        return int(time.mktime(time.strptime(str(raw)[:19], "%Y-%m-%dT%H:%M:%S")))
    except Exception:  # noqa: BLE001
        return 0


def list_threads() -> list[dict]:
    """One summary per thread, most recent first."""
    threads = _load()
    out = []
    for tid, messages in threads.items():
        if not isinstance(messages, list) or not messages:
            continue
        title, question = _parse_intro(messages)
        authors = []
        for m in messages:
            a = m.get("author") or "agent"
            if a not in authors:
                authors.append(a)
        last = messages[-1]
        out.append({
            "id": tid,
            "title": title,
            "question": question,
            "messages": len(messages),
            "authors": authors,
            "last_author": last.get("author") or "agent",
            "last_ts": _ts(last),
        })
    out.sort(key=lambda t: t["last_ts"], reverse=True)
    return out


def get_thread(thread_id: str) -> dict | None:
    """Full thread: title, question and the ordered messages."""
    messages = _load().get(thread_id)
    if not isinstance(messages, list) or not messages:
        return None
    title, question = _parse_intro(messages)
    return {
        "id": thread_id,
        "title": title,
        "question": question,
        "messages": [
            {
                "id": m.get("id"),
                "author": m.get("author") or "agent",
                "text": m.get("text") or "",
                "ts": _ts(m),
            }
            for m in messages
        ],
    }
