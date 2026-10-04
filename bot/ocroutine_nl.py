"""Turn a sentence into a routine draft — in several languages.

The dashboard's "say it in a chat" detection used to be English-only
(`every morning`, `on mondays`…). This module is the shared, tested core: it
understands English, French and Spanish, and returns a plain draft the web app
(when a chat creates a routine) and the API can use directly:

    {"mode": "daily"|"weekly"|"interval", "time": "HH:MM",
     "days": ["mon"…], "every_minutes": 0, "what": "…", "lang": "fr"}

Design choices:

* No dependency on the engine, Postgres or the network: pure functions, so it
  is unit-tested in CI.
* Word boundaries are explicit and accented characters are accepted, because
  French/Spanish recurrences carry accents (``tous les jours``, ``cada día``).
* When nothing recurring is recognised, ``detect`` returns ``None`` — the
  caller must not turn a one-off question into an automation.
"""

from __future__ import annotations

import re

__all__ = ["detect", "draft", "LANGUAGES"]

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# Language tables: weekday words, and the "every X" patterns. Keeping this per
# language (rather than one giant regex) makes it obvious how to add one.
LANGUAGES: dict[str, dict] = {
    "en": {
        "days": {
            "monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu",
            "friday": "fri", "saturday": "sat", "sunday": "sun",
        },
        "part_of_day": {
            "morning": "08:00", "noon": "12:00", "lunch": "12:00",
            "afternoon": "15:00", "evening": "19:00", "night": "21:00",
        },
        "weekdays": ["weekday", "weekdays"],
        "weekend": ["weekend", "weekends"],
        "recur": re.compile(
            r"\b(every|each)\s+(day|morning|evening|night|afternoon|week|weekday|weekend|hour"
            r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
            r"|\d+\s*h(?:ours?|rs?)?)s?\b"
            r"|\b(daily|weekly|hourly)\b"
            r"|\bon\s+(mondays?|tuesdays?|wednesdays?|thursdays?|fridays?|saturdays?|sundays?|weekdays?)\b",
            re.I,
        ),
        "weekly": re.compile(r"\b(every|each)\s+week\b|\bweekly\b", re.I),
        "interval": re.compile(r"\b(?:every|each)\s+(\d+)\s*h(?:ours?|rs?)?\b", re.I),
        "hourly": re.compile(r"\b(?:every|each)\s+hour\b|\bhourly\b", re.I),
        "at": re.compile(r"\bat\s+(\d{1,2})(?:[:h.](\d{2}))?\s*(am|pm)?\b", re.I),
        "strip": re.compile(
            r"\b(every|each|on)\b|\b(daily|weekly|hourly)\b"
            r"|\b(day|morning|evening|night|afternoon|week|weekday|weekend|hour)s?\b"
            r"|\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b",
            re.I,
        ),
    },
    "fr": {
        "days": {
            "lundi": "mon", "mardi": "tue", "mercredi": "wed", "jeudi": "thu",
            "vendredi": "fri", "samedi": "sat", "dimanche": "sun",
        },
        "part_of_day": {
            "matin": "08:00", "matinée": "08:00", "midi": "12:00", "déjeuner": "12:00",
            "après-midi": "15:00", "aprèm": "15:00", "soir": "19:00",
            "soirée": "19:00", "nuit": "21:00",
        },
        "weekdays": ["jour ouvré", "jours ouvrés", "jours ouvrables", "semaine"],
        "weekend": ["week-end", "weekend", "weekends"],
        "recur": re.compile(
            r"\b(tous?\s+les|chaque|toutes?\s+les)\s+"
            r"(jours?|matins?|matinées?|soirs?|soirées?|nuits?|après-midis?|semaines?|week-?ends?|heures?"
            r"|lundis?|mardis?|mercredis?|jeudis?|vendredis?|samedis?|dimanches?|\d+\s*h(?:eures?)?)\b"
            r"|\b(quotidien(?:ne)?|hebdomadaire|horaire)\b"
            r"|\b(le|les)\s+(lundis?|mardis?|mercredis?|jeudis?|vendredis?|samedis?|dimanches?)\b",
            re.I,
        ),
        "weekly": re.compile(r"\b(tous?\s+les|chaque)\s+semaines?\b|\bhebdomadaire\b", re.I),
        "interval": re.compile(r"\b(?:tous?\s+les|toutes?\s+les|chaque)\s+(\d+)\s*h(?:eures?)?\b", re.I),
        "hourly": re.compile(r"\b(toutes?\s+les|chaque)\s+heures?\b|\bhoraire\b", re.I),
        "at": re.compile(r"\b(?:à|a|vers)\s+(\d{1,2})\s*(?:[:h.](\d{2}))?\s*h?\b", re.I),
        "strip": re.compile(
            r"\b(tous?|toutes?|les|chaque|le|la|à|a|vers)\b"
            r"|\b(quotidien(?:ne)?|hebdomadaire|horaire)\b"
            r"|\b(jours?|matins?|matinées?|soirs?|soirées?|nuits?|après-midis?|semaines?|week-?ends?|heures?)\b"
            r"|\b(lundis?|mardis?|mercredis?|jeudis?|vendredis?|samedis?|dimanches?)\b"
            r"|\b\d{1,2}\s*h(?:\d{2})?\b",
            re.I,
        ),
    },
    "es": {
        "days": {
            "lunes": "mon", "martes": "tue", "miércoles": "wed", "miercoles": "wed",
            "jueves": "thu", "viernes": "fri", "sábado": "sat", "sabado": "sat",
            "domingo": "sun",
        },
        "part_of_day": {
            "mañana": "08:00", "manana": "08:00", "mediodía": "12:00", "mediodia": "12:00",
            "almuerzo": "12:00", "tarde": "15:00", "noche": "21:00",
        },
        "weekdays": ["día laborable", "días laborables", "entre semana"],
        "weekend": ["fin de semana", "fines de semana"],
        "recur": re.compile(
            r"\b(todos?\s+los|cada)\s+"
            r"(días?|mañanas?|tardes?|noches?|semanas?|horas?|fines?\s+de\s+semana|\d+\s*h(?:oras?)?)\b"
            r"|\b(diariamente|semanal(?:mente)?|cada\s+hora)\b"
            r"|\b(los|el)\s+(lunes|martes|miércoles|miercoles|jueves|viernes|sábados?|sabados?|domingos?)\b",
            re.I,
        ),
        "weekly": re.compile(r"\b(todos?\s+los|cada)\s+semanas?\b|\bsemanal(?:mente)?\b", re.I),
        "interval": re.compile(r"\b(?:todos?\s+los|cada)\s+(\d+)\s*h(?:oras?)?\b", re.I),
        "hourly": re.compile(r"\b(cada|todas?\s+las)\s+horas?\b|\bcada\s+hora\b", re.I),
        "at": re.compile(r"\b(?:a|las)\s+(\d{1,2})(?:[:h.](\d{2}))?\s*h?\b", re.I),
        "strip": re.compile(
            r"\b(todos?|todas?|los|las|cada|el|la|a)\b"
            r"|\b(diariamente|semanal(?:mente)?|cada\s+hora)\b"
            r"|\b(días?|mañanas?|tardes?|noches?|semanas?|horas?|fines?\s+de\s+semana)\b"
            r"|\b(lunes|martes|miércoles|miercoles|jueves|viernes|sábados?|sabados?|domingos?)\b",
            re.I,
        ),
    },
}

# Order matters: the first language that recognises a recurrence wins. Accents
# make French/Spanish detections unambiguous, so this is only a tie-break.
_ORDER = ("fr", "en", "es")


def detect_language(text: str) -> str:
    """Best-effort language of a recurrence sentence (for the draft only)."""
    for lang in _ORDER:
        if LANGUAGES[lang]["recur"].search(text):
            return lang
    return "en"


def _clock(raw_h: str, raw_m: str | None, meridiem: str | None) -> str | None:
    try:
        h = int(raw_h)
    except (TypeError, ValueError):
        return None
    if meridiem:
        meridiem = meridiem.lower()
        if meridiem == "pm" and h < 12:
            h += 12
        if meridiem == "am" and h == 12:
            h = 0
    if not 0 <= h < 24:
        return None
    return f"{h:02d}:{(raw_m or '00')}"


def _looks_recurring(text: str) -> bool:
    return any(LANGUAGES[l]["recur"].search(text) for l in LANGUAGES)


def detect(text: str) -> dict | None:
    """A routine draft if the sentence describes something recurring, else None."""
    if not text or len(text) > 400 or text.startswith("/"):
        return None
    if not _looks_recurring(text):
        return None
    return draft(text)


def draft(text: str) -> dict:
    """Parse a recurrence sentence into a routine draft.

    Always returns a draft (use :func:`detect` to know whether the sentence
    looks recurring): a plain "summarise my day" gives a sensible daily 09:00.
    """
    lang = detect_language(text)
    table = LANGUAGES[lang]
    low = text.lower()

    out = {
        "mode": "daily",
        "time": "09:00",
        "days": list(DAYS),
        "every_minutes": 0,
        "lang": lang,
    }

    # Scheduling fragments are removed from "what" as they are recognised, so
    # the resulting prompt keeps only the actual request.
    consumed: list[str] = []

    # 1. Interval ("every 2 hours", "toutes les 3 heures", "cada 2 horas").
    m = table["interval"].search(low)
    if m:
        out["mode"] = "interval"
        out["every_minutes"] = max(5, int(m.group(1)) * 60)
        out["days"] = list(DAYS)
        consumed.append(m.group(0))
    elif (m := table["hourly"].search(low)):
        out["mode"] = "interval"
        out["every_minutes"] = 60
        out["days"] = list(DAYS)
        consumed.append(m.group(0))
    else:
        # 2. Weekdays mentioned in the sentence (plural tolerated: "lundis").
        found = [v for w, v in table["days"].items() if re.search(rf"\b{w}s?\b", low)]
        if any(w in low for w in table["weekdays"]):
            out["days"] = ["mon", "tue", "wed", "thu", "fri"]
            consumed += [w for w in table["weekdays"] if w in low]
        elif any(w in low for w in table["weekend"]):
            out["days"] = ["sat", "sun"]
            consumed += [w for w in table["weekend"] if w in low]
        elif found:
            out["days"] = sorted(set(found), key=DAYS.index)
        elif (m := table["weekly"].search(low)):
            out["days"] = ["mon"]
            consumed.append(m.group(0))
        out["mode"] = "daily" if len(out["days"]) == 7 else "weekly"

    # 3. Time: named part of day first, then an explicit "at 7:30".
    for word, hhmm in table["part_of_day"].items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            out["time"] = hhmm
            consumed.append(word)
            break
    m = table["at"].search(low)
    if m:
        groups = m.re.groups
        clock = _clock(
            m.group(1),
            m.group(2) if groups >= 2 else None,
            m.group(3) if groups >= 3 else None,
        )
        if clock:
            out["time"] = clock
            consumed.append(m.group(0))

    # 4. What to do = the sentence without the scheduling words. Fragments that
    #    were recognised (and only those) are removed, so nothing useful is lost.
    what = text
    for frag in sorted(set(consumed), key=len, reverse=True):
        what = re.sub(re.escape(frag), " ", what, flags=re.I)
    what = re.sub(r"\s+", " ", what).strip(" ,;:-.")
    out["what"] = what or text.strip()
    return out
