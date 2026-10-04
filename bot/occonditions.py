"""Conditions attached to a routine: run it only when something is true.

A routine can carry a ``skip_if`` block. When the condition is not met, the
scheduler skips that run — the prompt is never sent to the model, so a
conditional routine ("only tell me if it's going to rain") costs nothing when
there is nothing to say.

The format stays readable in jobs.json:

    { "skip_if": { "type": "text_contains", "source": "…", "value": "RAIN" } }

Supported types (all pure, no network in the predicate itself):

    always / never        — trivial, for tests and templates
    text_contains         — value in source (or not, with `negate`)
    text_matches          — regular expression over source
    number                — numeric comparison of source
    weekday               — source is a weekday name ("mon"…"sun", or "weekend")
    exists                — source is non-empty

`source` is a literal string written by the user (e.g. a marker a routine
prints), or left empty. Live-data sources (weather, a price, an inbox) are not
resolved by the worker yet: a condition without a ``source`` therefore does not
block the run — the routine's own prompt is responsible for replying RAS when
there is nothing to report. The evaluator is ready for those sources when they
land; the pure logic and its tests stay valid.
"""

from __future__ import annotations

import re

__all__ = ["should_run", "evaluate", "TYPES"]

TYPES = (
    "always", "never", "text_contains", "text_matches", "number", "weekday", "exists",
)

_WEEKEND = {"sat", "sun"}
_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def _as_number(text: str) -> float | None:
    m = _NUM_RE.search(str(text or ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return None


def evaluate(cond: dict, *, source: str = "", weekday: str = "") -> bool:
    """True when the run is allowed. Unknown/empty conditions allow the run."""
    if not cond or not isinstance(cond, dict):
        return True
    ctype = str(cond.get("type") or "always").lower()
    negate = bool(cond.get("negate"))
    value = cond.get("value")
    src = cond.get("source") if cond.get("source") is not None else source
    src = str(src)

    if ctype == "always":
        ok = True
    elif ctype == "never":
        ok = False
    elif ctype == "exists":
        ok = bool(src.strip())
    elif ctype == "text_contains":
        ok = str(value or "").lower() in src.lower()
    elif ctype == "text_matches":
        try:
            ok = re.search(str(value or ""), src, re.I) is not None
        except re.error:
            ok = True
    elif ctype == "number":
        num, target = _as_number(src), _as_number(str(value))
        op = str(cond.get("op") or ">=")
        if num is None or target is None:
            ok = True
        elif op == ">":
            ok = num > target
        elif op == "<":
            ok = num < target
        elif op == "<=":
            ok = num <= target
        elif op == "==":
            ok = num == target
        elif op == "!=":
            ok = num != target
        else:
            ok = num >= target
    elif ctype == "weekday":
        day = (weekday or "").lower()[:3]
        wanted = {str(value or "").lower()}
        if wanted & {"weekend", "sat-sun"}:
            ok = day in _WEEKEND
        elif wanted & {"weekday", "weekdays"}:
            ok = bool(day) and day not in _WEEKEND
        else:
            ok = day in {w[:3] for w in wanted}
    else:
        ok = True

    return (not ok) if negate else ok


def should_run(job: dict, *, source: str = "", weekday: str = "") -> bool:
    """Convenience wrapper over the job's ``skip_if`` block."""
    return evaluate(job.get("skip_if") or {}, source=source, weekday=weekday)
