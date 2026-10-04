"""How much does this alert deserve to reach the user?

More proactivity is only useful if Mav can *rank* what it finds, otherwise it
just sends more. This module gives every notification a level:

    critical  — money, security, a missed deadline, a failure that matters
    important — decisions, appointments, things that need a reply today
    useful    — reports and changes worth knowing
    fyi       — background noise, kept in history but not pushed

The classifier is a cheap, local, explainable heuristic (no model call), so it
is instant and works even when the engine is down. It is intentionally
conservative: when unsure it returns ``useful`` rather than over-alerting.
"""

from __future__ import annotations

import re

__all__ = ["LEVELS", "RANK", "classify", "level_of", "rank"]

LEVELS = ("fyi", "useful", "important", "critical")
RANK = {lvl: i for i, lvl in enumerate(LEVELS)}

# Keyword signals, strongest first. Both languages (Mav is used in FR/EN).
_CRITICAL = re.compile(
    r"\b(urgent|asap|immediately|critical|critique|failure|failed|échec|erreur 5\d\d|"
    r"fraud|fraude|sécurité|security|breach|fuite|paiement refusé|payment failed|"
    r"deadline (today|missed)|aujourd'hui dernier délai|expiré|expired|"
    r"overdraft|découvert|impayé|unpaid)\b",
    re.I,
)
_IMPORTANT = re.compile(
    r"\b(important|attention|today|aujourd'hui|demain|tomorrow|réunion|meeting|"
    r"rendez-vous|appointment|deadline|échéance|rappel|reminder|reply|répondre|"
    r"prévenir|alert|alerte|confirm|couvre-feu|avant \d+h|dans \d+ ?(min|h))\b",
    re.I,
)
_USEFUL = re.compile(
    r"\b(rapport|report|bilan|recap|récap|résumé|summary|update|mise à jour|"
    r"nouveau|new|changed|variation|prix|price|headline|actualité)\b",
    re.I,
)


def classify(text: str, *, topic: str = "", default: str = "useful") -> dict:
    """Return ``{"level", "score", "why"}`` for a notification title+body."""
    hay = f"{topic} {text or ''}"[:2000]
    if _CRITICAL.search(hay):
        return {"level": "critical", "score": 3, "why": "urgent/security keyword"}
    if _IMPORTANT.search(hay):
        return {"level": "important", "score": 2, "why": "time-sensitive keyword"}
    if _USEFUL.search(hay):
        return {"level": "useful", "score": 1, "why": "report/change keyword"}
    return {"level": default, "score": RANK.get(default, 1), "why": "default"}


def level_of(text: str, **kw) -> str:
    return classify(text, **kw)["level"]


def rank(level: str) -> int:
    return RANK.get(str(level or "").lower(), 1)


# How chatty each proactivity level is: the minimum rank that earns a push.
PUSH_FLOOR = {"quiet": RANK["critical"], "normal": RANK["important"], "chatty": RANK["fyi"]}


def should_push(level: str, proactivity: str) -> bool:
    """Does `level` clear the bar set by the user's proactivity preference?"""
    floor = PUSH_FLOOR.get(str(proactivity or "normal").lower(), RANK["important"])
    return rank(level) >= floor
