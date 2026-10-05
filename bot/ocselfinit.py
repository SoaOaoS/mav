"""Mav gives itself the actions it needs to stay on top of your interests.

This is the control loop the user asked for: an interest is not just a label in
a table, it *produces a watchdog routine*. When Mav infers "you're into cyber",
it proposes — and, once trusted, creates — a scheduled watch that checks the
topic on its own, decides whether anything is worth mentioning, and only then
speaks. The AI is the engine of the action, not a passive recorder.

Design notes, so this stays honest and non-intrusive:

  - Only *watchable* interests spawn a routine: a like, not muted, with a real
    confidence, whose cadence is not off. A dislike never does.
  - Auto-generated routines are self-describing (``source: "interest"`` and
    ``interest_key``) so they can be told apart from hand-made ones, updated
    when the interest changes, and retired when it cools down or disappears.
  - A hand-made routine is never touched or shadowed.
  - If the user turns an auto routine off, that is a veto: reconciliation
    respects ``enabled: false`` and never flips it back on.
  - Three autonomy levels: ``off`` (observe only), ``suggest`` (propose, write
    nothing) and ``auto`` (create/update/retire by itself). Default: suggest.

The generation and the diff are pure; only ``reconcile`` touches jobs.json.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
from pathlib import Path

from ocinterests import CADENCE_DAYS, Interests  # noqa: F401

log = logging.getLogger("ocselfinit")

BOT_DIR = Path(os.environ.get("BOT_DIR", Path(__file__).resolve().parent))

# How often one watchdog actually re-checks the topic, per nudge cadence. The
# model itself then decides whether the run is worth a message (RAS otherwise),
# so a frequent check is not a frequent interruption.
CHECK_MINUTES = {
    "weekly": 1440,      # check daily
    "biweekly": 2880,    # every 2 days
    "monthly": 4320,     # every 3 days
    "quarterly": 10080,  # weekly
}
PINNED_CHECK_MINUTES = 360  # a pinned interest is checked every 6 h

AUTONOMY = ("off", "suggest", "auto")
DEFAULT_AGENT = os.environ.get("INTEREST_AGENT", "research")

__all__ = [
    "AUTONOMY", "CHECK_MINUTES", "watchable", "check_minutes", "routine_name",
    "watchdog_prompt", "routine_for", "plan_jobs", "reconcile",
]


# ------------------------------------------------------------------ generation


def watchable(interest: dict) -> bool:
    """Can this interest justify a watchdog routine?"""
    return (
        interest.get("polarity") == "like"
        and not interest.get("muted")
        and (interest.get("cadence") or "monthly") != "off"
        and not interest.get("conflicted")
        and float(interest.get("confidence") or 0) >= 0.2
    )


def check_minutes(interest: dict) -> int:
    if interest.get("pinned"):
        return PINNED_CHECK_MINUTES
    cadence = interest.get("cadence") or "monthly"
    return CHECK_MINUTES.get(cadence, 4320)


def routine_name(interest: dict) -> str:
    """A stable, readable name; the key already is a slug."""
    return ("veille-" + str(interest.get("key") or "interet"))[:60]


def watchdog_prompt(interest: dict) -> str:
    label = interest.get("label") or interest.get("key") or "?"
    cat = interest.get("category") or "other"
    query = interest.get("entity") or interest.get("label") or interest.get("key") or ""
    q = urllib.parse.quote(str(query))
    return (
        f"Veille automatique sur un centre d'intérêt : « {label} » (catégorie : {cat}).\n"
        f"Objectif : repérer ce qui bouge sur {label} et me le signaler si — et seulement si — "
        "ça vaut le coup.\n"
        f"1. Cherche l'actualité récente (dernières 24-72 h) : "
        f"https://news.google.com/rss/search?q={q}\n"
        "2. Ne retiens que des faits concrets et vérifiables : résultat de match, annonce, "
        "sortie, variation notable, promo, échéance.\n"
        "3. Si rien de nouveau ou d'important : réponds exactement « RAS ».\n"
        "4. Sinon : 2 à 4 puces très courtes — quoi, quand, et pourquoi ça compte pour moi. "
        "Mets le lien quand il y en a un.\n"
        "Ne me relance jamais sur un sujet que j'ai dit ne pas aimer, et ne radote pas : "
        "si je suis déjà au courant, réponds RAS."
    )


def routine_for(interest: dict) -> dict:
    """The jobs.json entry that watches this interest."""
    return {
        "name": routine_name(interest),
        "every_minutes": check_minutes(interest),
        "agent": DEFAULT_AGENT,
        "prompt": watchdog_prompt(interest),
        "enabled": True,
        "source": "interest",
        "interest_key": interest.get("key"),
        "created_by": "mav",
    }


# ------------------------------------------------------------------ reconcile


def _read_jobs(path: Path) -> list[dict]:
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except Exception as exc:  # noqa: BLE001
        log.warning("jobs.json unreadable for self-init: %s", exc)
        return []


def _write_jobs(path: Path, jobs: list[dict]) -> None:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(jobs, indent=1, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        log.warning("jobs.json not written by self-init: %s", exc)


def _same_as(existing: dict, want: dict) -> bool:
    return (
        existing.get("prompt") == want.get("prompt")
        and int(existing.get("every_minutes") or 0) == int(want.get("every_minutes") or 0)
        and (existing.get("agent") or "") == (want.get("agent") or "")
    )


def plan_jobs(interests: list[dict], jobs: list[dict]) -> dict:
    """Compute the create/update/retire diff without writing anything.

    Returns ``{"create": [...], "update": [...], "retire": [...],
    "keep": [...], "vetoed": [...]}`` where retired entries carry the existing
    job so a caller can show exactly what would be removed.
    """
    auto = {
        j.get("interest_key"): j
        for j in jobs
        if j.get("source") == "interest" and j.get("interest_key")
    }
    hand_names = {j.get("name") for j in jobs if j.get("source") != "interest"}

    create, update, keep, vetoed = [], [], [], []
    wanted_keys = set()
    for interest in interests:
        key = interest.get("key")
        if not watchable(interest):
            continue
        wanted_keys.add(key)
        want = routine_for(interest)
        existing = auto.get(key)
        if existing is None:
            if want["name"] in hand_names:
                continue  # never shadow a hand-made routine
            create.append(want)
            continue
        # A user who turned an auto routine off vetoed it: leave it alone.
        if not existing.get("enabled", True):
            vetoed.append(existing)
            continue
        if _same_as(existing, want):
            keep.append(existing)
        else:
            merged = dict(existing)
            merged.update({k: want[k] for k in ("prompt", "every_minutes", "agent")})
            update.append(merged)

    retire = []
    for key, job in auto.items():
        # A key still wanted (even a vetoed one: vetoes are kept above) stays;
        # only a watchdog whose interest cooled down or vanished is retired.
        if key in wanted_keys:
            continue
        retire.append(job)

    return {"create": create, "update": update, "retire": retire,
            "keep": keep, "vetoed": vetoed}


def reconcile(interests: "Interests", jobs_path: Path, *,
              autonomy: str = "suggest") -> dict:
    """Bring jobs.json in line with the current interests, per the autonomy level.

    ``off``     — compute the diff and report it, write nothing.
    ``suggest`` — same; the dashboard shows it as a proposal to accept.
    ``auto``    — apply create/update/retire.

    Returns the diff plus ``{"applied": bool, "autonomy": str, "counts": {...}}``.
    """
    autonomy = autonomy if autonomy in AUTONOMY else "suggest"
    jobs = _read_jobs(jobs_path)
    diff = plan_jobs(interests.list(include_muted=True), jobs)
    applied = False

    if autonomy == "auto" and any(diff[k] for k in ("create", "update", "retire")):
        retire_names = {j.get("name") for j in diff["retire"]}
        kept = [j for j in jobs if j.get("name") not in retire_names]
        # Update in place, then append the new ones.
        updated_by_name = {j["name"]: j for j in diff["update"]}
        kept = [updated_by_name.get(j.get("name"), j) for j in kept]
        existing_names = {j.get("name") for j in kept}
        for job in diff["create"]:
            if job["name"] not in existing_names:
                kept.append(job)
                existing_names.add(job["name"])
        _write_jobs(jobs_path, kept)
        applied = True
        log.info(
            "self-init applied: +%d ~%d -%d",
            len(diff["create"]), len(diff["update"]), len(diff["retire"]),
        )

    return {
        **diff,
        "applied": applied,
        "autonomy": autonomy,
        "counts": {
            "create": len(diff["create"]),
            "update": len(diff["update"]),
            "retire": len(diff["retire"]),
            "keep": len(diff["keep"]),
            "vetoed": len(diff["vetoed"]),
        },
    }
