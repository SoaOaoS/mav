"""Turn interests into outreach: come back to the user about what they love.

This is the part that actually *acts* on a profile. For each interest that is
due, it looks for something fresh and concrete to say (a news item about it),
and — when there is one — Mav reaches out first: a notification plus a chat
opened in the dashboard, so the user can pick the conversation up.

Honesty rules baked in:
  - a bare interest with no news never triggers a "how about it?" nudge: Mav
    only speaks when it has a reason (``MIN_MATCH``);
  - the same story is never pushed twice (``last_ref`` on the interest);
  - a disliked topic is never pushed (``should_pursue`` refuses it);
  - every outreach is recorded, so a bad guess can be corrected in one tap.

The decision layer (``matches``, ``headline_for``) is pure and unit-tested; the
delivery layer reuses the existing notification + session plumbing.
"""

from __future__ import annotations

import logging
import os
import re
import time
import unicodedata

log = logging.getLogger("ocpursuit")

# How many recent headlines to consider per interest.
NEWS_WINDOW = int(os.environ.get("PURSUIT_NEWS_WINDOW", "12"))
# Minimum relevance for a headline to count as "about" the interest.
MIN_MATCH = float(os.environ.get("PURSUIT_MIN_MATCH", "0.5"))
# Never reach out about the same interest more than once per this many hours.
MIN_GAP_HOURS = float(os.environ.get("PURSUIT_MIN_GAP_HOURS", "20"))

# Words too generic to prove relevance on their own.
_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "des", "les", "une",
    "aux", "par", "sur", "dans", "pour", "avec", "chez", "plus", "news", "vs",
}

__all__ = ["tokens", "matches", "headline_for", "plain", "plan", "pursue_once"]


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", str(text or "").lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def tokens(text: str, *, min_len: int = 3) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9]+", _fold(text)):
        if len(w) >= min_len and w not in _STOP:
            out.add(w)
    return out


def _interest_terms(interest: dict) -> set[str]:
    """The terms that identify an interest: its entity/ticker, or its label."""
    entity = str(interest.get("entity") or "").strip()
    terms = tokens(entity) if entity else set()
    label = str(interest.get("label") or interest.get("key") or "")
    if not terms:
        terms = tokens(label)
    # Keep the label's own tokens too: "PSG" should match, but so should "Paris".
    terms |= tokens(label)
    return {t for t in terms if t not in _STOP}


def matches(interest: dict, text: str) -> float:
    """Relevance in [0, 1] of `text` to `interest`.

    Fraction of the interest's identifying terms found in the text, but a
    single strong term (an uppercase entity / ticker) is enough on its own,
    which is how tickers and team acronyms actually show up in headlines.
    """
    terms = _interest_terms(interest)
    if not terms:
        return 0.0
    hay = _fold(text)
    hay_tokens = tokens(text) | {str(text or "")}
    found = {t for t in terms if t in hay_tokens}
    if not found:
        return 0.0
    entity = str(interest.get("entity") or "").strip()
    if entity and _fold(entity) in hay:
        return 1.0
    return round(len(found) / max(1, len(terms)), 4)


def headline_for(interest: dict, items: list[dict],
                 *, seen_ref: str = "") -> dict | None:
    """The freshest headline genuinely about `interest`, or None.

    `items` are ``{title, link, id}`` (see ocwatch.news_items). Skips the
    already-pushed story (`seen_ref`) and anything below ``MIN_MATCH``.
    """
    if not items:
        return None
    best = None
    best_score = 0.0
    for it in items:
        ref = str(it.get("id") or it.get("link") or "")
        if ref and ref == seen_ref:
            continue
        score = matches(interest, it.get("title") or "")
        if score >= MIN_MATCH and score > best_score:
            best, best_score = it, score
    if not best:
        return None
    return {
        "title": (best.get("title") or "").strip(),
        "link": (best.get("link") or "").strip(),
        "ref": str(best.get("id") or best.get("link") or ""),
        "score": best_score,
    }


def plain(text: str) -> str:
    """A one-line, notification-safe rendering (no markdown noise)."""
    text = re.sub(r"[*_`#>|]+", "", str(text or ""))
    return " ".join(text.split())


def _compose(interest: dict, hit: dict) -> tuple[str, str]:
    label = interest.get("label") or interest.get("key") or "?"
    title = f"✨ {label}"
    body = hit["title"]
    if len(body) > 200:
        body = body[:197] + "…"
    return title, body


def plan(interests, news_fetcher, *, now: int | None = None) -> list[tuple[dict, dict]]:
    """The pure decision pass: ``[(interest, hit), …]`` worth reaching out about.

    Fetches news for each due interest, keeps only a genuinely matching, not
    already-pushed story, and drops anything inside the minimum gap. No side
    effects, so it is trivially testable and safe to run in the worker.
    """
    now = now or int(time.time())
    chosen: list[tuple[dict, dict]] = []
    for interest in interests.due(now):
        last = int(interest.get("last_pursued") or 0)
        if last and now - last < MIN_GAP_HOURS * 3600:
            continue
        query = interest.get("entity") or interest.get("label") or interest.get("key")
        try:
            items = news_fetcher(query) or []
        except Exception as exc:  # noqa: BLE001
            log.warning("pursuit news for %s failed: %s", interest.get("key"), exc)
            items = []
        hit = headline_for(interest, items[:NEWS_WINDOW],
                           seen_ref=interest.get("last_ref") or "")
        if hit:
            chosen.append((interest, hit))
    return chosen


def mark_pursued(interests, interest: dict, hit: dict) -> None:
    """Record that we acted on an interest: advance the clock and remember the
    story so it is never pushed twice."""
    try:
        interests.touch(interest["key"], pursued=True)
        fresh = interests.get(interest["key"])
        if fresh:
            fresh["last_ref"] = hit.get("ref") or ""
            interests._upsert(fresh)
    except Exception as exc:  # noqa: BLE001
        log.warning("pursuit mark failed: %s", exc)


def pursue_once(*, interests, notify, session_factory=None, news_fetcher,
                chat_id: int = 0, now: int | None = None) -> list[dict]:
    """One synchronous pass: plan, then deliver each outreach.

    ``session_factory(interest, hit) -> session_id`` is optional; when it
    returns one, the notification links straight to that chat. Returns the list
    of outbound entries (for logging/tests).
    """
    out: list[dict] = []
    for interest, hit in plan(interests, news_fetcher, now=now):
        title, body = _compose(interest, hit)
        url = "./"
        sid = ""
        if session_factory is not None:
            try:
                sid = session_factory(interest, hit) or ""
                if sid:
                    url = f"./#chat/{sid}"
            except Exception as exc:  # noqa: BLE001
                log.warning("pursuit session for %s failed: %s", interest.get("key"), exc)

        result = {}
        try:
            result = notify(title, body, url=url, topic="pursuit", level="useful")
        except TypeError:
            # Older notify signature without kwargs (kept tolerant on purpose).
            result = notify(title, body)
        except Exception as exc:  # noqa: BLE001
            log.warning("pursuit notify failed: %s", exc)
            result = {}

        mark_pursued(interests, interest, hit)
        out.append({
            "key": interest["key"], "label": interest.get("label"),
            "hit": hit, "session": sid, "notification": result,
        })
    return out
