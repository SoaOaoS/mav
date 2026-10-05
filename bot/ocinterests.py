"""What the user actually cares about, and how sure Mav is.

A profile is only useful if it is honest. This module does not guess a taste
from a single word and then act on it forever: every interest carries the
**evidence** that produced it (the sentence, when, where), a **confidence**
score, and can be **contradicted**. An interest the user later pushes back on
("actually I can't stand that team") does not silently stay true — the
contradiction is recorded, the confidence drops, and pursuit stops until the
user settles it.

Two polarities are supported:
  - ``like``    — something to bring up, watch, and come back to;
  - ``dislike`` — an aversion. Crucially, a ``dislike`` *suppresses* a matching
                  ``like``: the bot must never proactively push a topic the
                  user said they hate.

Scoring is a small, explainable model (no embeddings, no model call):
  - a ``score`` in [0, 1]: how strong the pull is;
  - a ``confidence`` in [0, 1]: how sure we are, driven by explicit vs observed
    evidence;
  - a time decay so enthusiasm cools off if never engaged with;
  - a per-interest ``cadence`` (off/weekly/biweekly/monthly) that, combined with
    the score, decides when the interest is due for a nudge.

Storage is Postgres when reachable (shared with the rest of Mav), a JSON file
otherwise, so a no-Docker install still works. The scoring and detection logic
is pure and unit-tested without a database.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import unicodedata
from pathlib import Path

log = logging.getLogger("ocinterests")

BOT_DIR = Path(os.environ.get("BOT_DIR", Path(__file__).resolve().parent))
INTERESTS_FILE = Path(os.environ.get("INTERESTS_FILE", BOT_DIR / "interests.json"))
PG_DSN = os.environ.get(
    "PG_DSN",
    "host=127.0.0.1 port=5432 user=mav password=mav_secret dbname=mav",
)

# Cadences, from silent to occasional. "off" is explicit: keep the interest but
# never reach out. The number is the nominal number of days between nudges.
CADENCES = ("off", "weekly", "biweekly", "monthly", "quarterly")
CADENCE_DAYS = {"off": 0, "weekly": 7, "biweekly": 14, "monthly": 30, "quarterly": 90}
POLARITIES = ("like", "dislike")

# How long a strong pull takes to halve when never engaged with (days).
HALF_LIFE_DAYS = 120.0

# Confidence: explicit statements count for a lot, observations for little.
EXPLICIT_WEIGHT = 0.45
OBSERVED_WEIGHT = 0.12
AFFIRM_WEIGHT = 0.15  # a 👍 on a topic strengthens belief in it

CATEGORIES = (
    "sport", "finance", "tech", "travel", "music", "food",
    "games", "culture", "place", "person", "other",
)

__all__ = [
    "CADENCES", "CADENCE_DAYS", "POLARITIES", "CATEGORIES",
    "CATEGORY_PATTERNS", "slugify", "detect_observations", "decay",
    "blend_score", "confidence_of", "pick_cadence", "next_due_for",
    "should_pursue", "Interests",
]


def _now() -> int:
    return int(time.time())


def fold(text: str) -> str:
    text = unicodedata.normalize("NFD", str(text or "").lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def slugify(text: str) -> str:
    """A stable key for an interest: "Paris Saint-Germain" -> "paris-saint-germain"."""
    s = re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")
    return s[:80] or "interest"


# ------------------------------------------------------------------ detection
# Language is deliberately FR + EN (Mav is used in both), with a couple of
# ES/IT cues because the NL routine detector already covers those.

_LIKE = re.compile(
    r"(?:j'(?:aime|adore|kiffe|apprecie)\b)"
    r"|(?:je suis (?:un )?fan de\b)|(?:je supporte\b)|(?:je suis pour\b)"
    r"|(?:ca m'interesse\b)|(?:je m'interesse (?:a|au|aux)\b)"
    r"|(?:i (?:love|like|adore|enjoy)\b)|(?:i'?m a (?:big )?fan of\b)"
    r"|(?:i support\b)|(?:i'?m into\b)|(?:fan of\b)"
    r"|(?:me gusta\b)|(?:soy fan de\b)",
    re.I,
)
_DISLIKE = re.compile(
    r"(?:je (?:deteste|hais|peux pas blairer|supporte pas|n'aime pas)\b)"
    r"|(?:je ne supporte pas\b)|(?:j'en ai marre de\b)|(?:pas fan de\b)"
    r"|(?:i (?:hate|dislike|despise)\b)|(?:i can'?t stand\b)"
    r"|(?:i (?:do not|don'?t) (?:like|care for)\b)|(?:not a fan of\b)"
    r"|(?:no me gusta\b)|(?:odio\b)",
    re.I,
)

# Category from the words around the interest. First match wins.
CATEGORY_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("sport", re.compile(
        r"\b(foot|football|match|equipe|team|ligue|champions league|psg|om\b|ol\b|"
        r"real madrid|barca|barça|mars\b|nba|lakers|celtics|warriors|knicks|"
        r"yankees|juventus|bayern|liverpool|chelsea|arsenal|tennis|f1|formule 1|"
        r"rugby|cyclisme|premier league|liga|serie a|bundesliga|nfl|top 14)\b", re.I)),
    ("finance", re.compile(
        r"\b(action|actions|bourse|ticker|crypto|bitcoin|ethereum|eth|btc|etf|"
        r"nasdaq|sp500|s&p|dow jones|cac 40|marche|marché|stock|trading|dividende)\b", re.I)),
    ("tech", re.compile(
        r"\b(python|rust|golang|\bgo\b|javascript|typescript|react|linux|kubernetes|"
        r"docker|gitlab|github|\bai\b|\bia\b|llm|neural|devops|cloud|self-?host)\b", re.I)),
    ("games", re.compile(
        r"\b(jeu|jeux|gaming|playstation|xbox|nintendo|steam|zelda|minecraft|"
        r"e-?sport|twitch|ps5)\b", re.I)),
    ("music", re.compile(
        r"\b(musique|album|concert|groupe|chanteur|chanteuse|rap|rock|jazz|"
        r"festival|spotify|playlist|dj)\b", re.I)),
    ("food", re.compile(
        r"\b(cuisine|recette|resto|restaurant|vin|biere|bière|gastronomie|"
        r"fromage|pizza|food)\b", re.I)),
    ("travel", re.compile(
        r"\b(voyage|voyages|travel|trip|vacances|week-?end|road ?trip|randonnee|"
        r"randonnée|trek|montagne|ski)\b", re.I)),
    ("culture", re.compile(
        r"\b(film|films|serie|série|cinema|cinéma|livre|livres|roman|expo|"
        r"musee|musée|theatre|théâtre|podcast)\b", re.I)),
]

# A place is often introduced by a preposition ("à Lyon", "de Bordeaux").
_PLACE = re.compile(
    r"\b(?:a|à|au|aux|de|du|des|en|a|from|in|to)\s+([A-ZÀ-Ý][\wÀ-ÿ'.-]{2,}(?:\s+[A-ZÀ-Ý][\wÀ-ÿ'.-]{2,})?)"
)
# A ticker-like token: 2-5 uppercase letters (not a common word).
_ENTITY = re.compile(r"\b([A-Z]{2,5})\b")
_ENTITY_STOP = {
    "JE", "TU", "IL", "ON", "LE", "LA", "LES", "UN", "UNE", "DES", "ET", "OU",
    "EN", "DE", "DU", "AU", "AUX", "THE", "AND", "FOR", "YOU", "MOT", "PAS",
    "OK", "RSI", "IA", "AI", "F1", "TV", "US", "FR", "EU",
}


def _category(hay: str) -> str:
    for name, pat in CATEGORY_PATTERNS:
        if pat.search(hay):
            return name
    return "other"


_ARTICLES = (
    "le", "la", "les", "l", "un", "une", "des", "du", "de", "the", "a", "an",
    "mon", "ma", "mes", "ton", "ta", "tes", "son", "sa", "ses",
)


def _clean_entity(raw: str) -> str:
    """Trim connective and leading article words from a captured noun phrase."""
    raw = " ".join(str(raw or "").split())
    raw = re.split(
        r"\s+(?:et|ou|mais|car|parce|qui|que|dont|and|or|but|because|which)\b",
        raw, maxsplit=1, flags=re.I,
    )[0]
    words = raw.split()
    while words and fold(words[0]).strip("'’") in _ARTICLES:
        words.pop(0)
    return " ".join(words).strip(" .,;:!?\'\"-")[:80]


def detect_observations(text: str) -> list[dict]:
    """Candidate interests in a sentence, with the evidence that supports them.

    Pure and conservative: one clause should yield one candidate. Each result is
    ``{key,label,entity,category,polarity,strength,snippet}`` where ``strength``
    in [0,1] reflects how explicit the statement is.
    """
    text = str(text or "")
    if not text.strip():
        return []
    hay = fold(text)
    out: list[dict] = []
    seen: set[str] = set()

    # Split roughly into clauses so "j'aime X mais je déteste Y" yields two.
    clauses = re.split(r"[.;!?\n]|\bmais\b|\bpar contre\b|\bhowever\b|\bbut\b", text)

    for clause in clauses:
        chay = fold(clause)
        polar = "like" if _LIKE.search(chay) else ("dislike" if _DISLIKE.search(chay) else "")
        if not polar:
            continue
        # The interesting noun phrase: after "fan de/j'aime/…", else the clause.
        m = re.search(
            r"(?:fan de|interesse a|interesse au|interesse aux|aime|adore|kiffe|"
            r"supporte|deteste|hais|marre de|love|like|adore|fan of|support|hate|"
            r"can'?t stand|into|dislike)\s+(.+)",
            chay,
        )
        phrase = _clean_entity(m.group(1) if m else clause)
        if not phrase or len(phrase) < 3:
            continue

        # Entity: a ticker-like token, otherwise a captured place.
        entity = ""
        em = _ENTITY.search(clause)
        if em and em.group(1) not in _ENTITY_STOP:
            entity = em.group(1)
        else:
            pm = _PLACE.search(clause)
            if pm:
                entity = _clean_entity(pm.group(1))

        label = _clean_entity(phrase.title() if phrase.lower() == phrase else phrase) or phrase
        key = slugify(entity or phrase)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "key": key,
            "label": label,
            "entity": entity,
            "category": _category(clause),
            "polarity": polar,
            "strength": 0.9,  # an explicit statement is a strong signal
            "snippet": " ".join(clause.split())[:200],
        })
    return out


# ------------------------------------------------------------------ scoring


def decay(score: float, last_engaged: int | None, now: int | None = None,
          half_life_days: float = HALF_LIFE_DAYS) -> float:
    """Exponential cooling of a score since it was last engaged with.

    An interest never touched for one half-life keeps half its pull. Time
    unknown means no decay.
    """
    if not last_engaged or not half_life_days:
        return float(score)
    now = now or _now()
    days = max(0.0, (now - int(last_engaged)) / 86400.0)
    return float(score) * (0.5 ** (days / half_life_days))


def blend_score(old: float, strength: float, *, kind: str = "explicit") -> float:
    """Fold one new observation into an existing score (in [0, 1]).

    Explicit statements pull harder than quiet observations; the result is
    asymptotic towards 1 so repetition cannot run it away.
    """
    old = max(0.0, min(1.0, float(old)))
    strength = max(0.0, min(1.0, float(strength)))
    w = EXPLICIT_WEIGHT if kind == "explicit" else OBSERVED_WEIGHT
    inc = w * strength
    return round(min(1.0, old + (1.0 - old) * inc), 4)


def confidence_of(explicit: int, observed: int = 0, *, affirm: int = 0,
                  conflicted: bool = False) -> float:
    """How sure we are, in [0, 1]. Independent pieces of evidence accumulate
    (each one closes part of the remaining doubt), but a single line never makes
    it certain; a contradiction caps it hard."""
    c = 1.0 - ((1.0 - EXPLICIT_WEIGHT) ** max(0, explicit)) * (
        (1.0 - OBSERVED_WEIGHT) ** max(0, observed))
    c += AFFIRM_WEIGHT * max(0, affirm)
    c = max(0.0, min(1.0, c))
    if conflicted:
        c = min(c, 0.25)
    return round(c, 4)


def pick_cadence(score: float, confidence: float) -> str:
    """A sensible default rhythm for an interest nobody has tuned yet."""
    if confidence < 0.2:
        return "quarterly"
    if score >= 0.75 and confidence >= 0.5:
        return "weekly"
    if score >= 0.55:
        return "biweekly"
    return "monthly"


def next_due_for(cadence: str, now: int | None = None, *,
                 last_pursued: int | None = None) -> int:
    """Timestamp at which the interest is next worth a nudge (0 when off)."""
    days = CADENCE_DAYS.get(cadence, 30)
    if not days:
        return 0
    base = last_pursued or (now or _now())
    return int(base) + days * 86400


def should_pursue(interest: dict, now: int | None = None) -> tuple[bool, str]:
    """Whether this interest is worth reaching out about now, and why.

    Refuses on: muted, cadence off, a dislike, a conflicted interest, low
    confidence, or not yet due. The reason is returned for the dashboard and
    logs (the honest part: every "no" is explainable).
    """
    now = now or _now()
    if interest.get("polarity") == "dislike":
        return False, "aversion"
    if interest.get("muted"):
        return False, "muted"
    if (interest.get("cadence") or "monthly") == "off":
        return False, "cadence off"
    if interest.get("conflicted"):
        return False, "conflicted evidence"
    if float(interest.get("confidence") or 0) < 0.2:
        return False, "low confidence"
    due = int(interest.get("next_due") or 0)
    if due and now < due:
        return False, "not due"
    return True, "due"


# ------------------------------------------------------------------ storage


SCHEMA = """
CREATE TABLE IF NOT EXISTS interests (
    id          bigserial PRIMARY KEY,
    chat_id     bigint  NOT NULL,
    key         text    NOT NULL,
    label       text    NOT NULL,
    entity      text,
    category    text,
    polarity    text    DEFAULT 'like',
    score       real    DEFAULT 0.5,
    confidence  real    DEFAULT 0.3,
    cadence     text    DEFAULT 'monthly',
    pinned      boolean DEFAULT false,
    muted       boolean DEFAULT false,
    conflicted  boolean DEFAULT false,
    source      text,
    evidence    jsonb,
    notes       text,
    created     bigint,
    updated     bigint,
    last_engaged bigint,
    last_pursued bigint,
    next_due    bigint,
    last_ref    text,
    UNIQUE (chat_id, key)
);
CREATE INDEX IF NOT EXISTS interests_chat_idx ON interests (chat_id);
CREATE INDEX IF NOT EXISTS interests_due_idx  ON interests (chat_id, next_due);
"""

_COLS = (
    "id, key, label, entity, category, polarity, score, confidence, cadence, "
    "pinned, muted, conflicted, source, evidence, notes, created, updated, "
    "last_engaged, last_pursued, next_due, last_ref"
)


def _row(r) -> dict:
    return {
        "id": r[0], "key": r[1], "label": r[2], "entity": r[3], "category": r[4],
        "polarity": r[5], "score": r[6], "confidence": r[7], "cadence": r[8],
        "pinned": r[9], "muted": r[10], "conflicted": r[11], "source": r[12],
        "evidence": r[13] or [], "notes": r[14], "created": r[15],
        "updated": r[16], "last_engaged": r[17], "last_pursued": r[18],
        "next_due": r[19], "last_ref": r[20] if len(r) > 20 else "",
    }


class Interests:
    """Interest store: Postgres when reachable, a JSON file otherwise.

    Same public shape either way; ``backend`` says which is live.
    """

    def __init__(self, path: Path | None = None, chat_id: int = 0):
        self.path = Path(path or INTERESTS_FILE)
        self.chat_id = chat_id
        self._pg = None
        self.backend = "none"
        self._connect()

    # ------------------------------------------------------------- backends
    def _connect(self) -> None:
        try:
            import psycopg2  # noqa: PLC0415

            self._pg = psycopg2.connect(PG_DSN, connect_timeout=3)
            self._pg.autocommit = True
            with self._pg.cursor() as cur:
                cur.execute(SCHEMA)
            self.backend = "postgres"
        except Exception:  # noqa: BLE001
            self._pg = None
            self.backend = "file"

    def _ensure(self) -> None:
        if self._pg is not None:
            try:
                self._pg.cursor().execute("SELECT 1")
            except Exception:  # noqa: BLE001
                self._connect()

    def _read_file(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _write_file(self, items: list[dict]) -> None:
        try:
            self.path.write_text(json.dumps(items[-500:], indent=1))
        except Exception:
            pass

    # ------------------------------------------------------------- read
    def list(self, *, include_muted: bool = True) -> list[dict]:
        self._ensure()
        if self._pg is not None:
            try:
                cur = self._pg.cursor()
                where = "" if include_muted else " AND NOT muted"
                cur.execute(
                    f"SELECT {_COLS} FROM interests WHERE chat_id = %s{where} "
                    "ORDER BY pinned DESC, score DESC",
                    (self.chat_id,),
                )
                return [_row(r) for r in cur.fetchall()]
            except Exception:  # noqa: BLE001
                pass
        items = [i for i in self._read_file() if i.get("chat_id") in (0, self.chat_id)]
        if not include_muted:
            items = [i for i in items if not i.get("muted")]
        return sorted(items, key=lambda i: (not i.get("pinned"), -(i.get("score") or 0)))

    def get(self, key: str) -> dict | None:
        k = slugify(key)
        return next((i for i in self.list() if i.get("key") == k), None)

    def due(self, now: int | None = None) -> list[dict]:
        """Interests that clear every gate and are worth a nudge now."""
        out = []
        for i in self.list(include_muted=False):
            ok, _why = should_pursue(i, now)
            if ok:
                out.append(i)
        return out

    # ------------------------------------------------------------- write
    def observe(self, obs: dict, *, source: str = "chat") -> dict | None:
        """Record one detected observation, updating an existing interest.

        Handles the honest cases: a new observation strengthens or weakens the
        score, adds to the evidence trail, and a statement that contradicts the
        recorded polarity flips it and marks the interest ``conflicted`` until
        the user settles it — so Mav stops pushing something it is unsure about.
        """
        key = slugify(obs.get("key") or obs.get("label") or "")
        if not key or key == "interest":
            return None
        polarity = obs.get("polarity") if obs.get("polarity") in POLARITIES else "like"
        now = _now()
        existing = self.get(key)
        snippet = str(obs.get("snippet") or "")[:200]
        evidence_item = {"ts": now, "source": source, "snippet": snippet,
                         "polarity": polarity, "strength": obs.get("strength", 0.9)}

        if existing is None:
            score = blend_score(0.0, obs.get("strength", 0.9))
            conf = confidence_of(1 if source != "observed" else 0, 1 if source == "observed" else 0)
            cadence = "off" if polarity == "dislike" else pick_cadence(score, conf)
            rec = {
                "chat_id": self.chat_id, "key": key,
                "label": str(obs.get("label") or key)[:120],
                "entity": str(obs.get("entity") or "")[:80],
                "category": str(obs.get("category") or "other")[:40],
                "polarity": polarity, "score": score, "confidence": conf,
                "cadence": cadence, "pinned": False, "muted": False,
                "conflicted": False, "source": source,
                "evidence": [evidence_item], "notes": "",
                "created": now, "updated": now, "last_engaged": now,
                "last_pursued": 0, "next_due": next_due_for(cadence, now),
            }
            self._upsert(rec)
            return rec

        ev = list(existing.get("evidence") or [])
        ev.append(evidence_item)
        ev = ev[-25:]

        conflicted = bool(existing.get("conflicted"))
        new_polarity = existing.get("polarity") or "like"
        score = float(existing.get("score") or 0.0)
        if polarity == new_polarity:
            score = blend_score(score, obs.get("strength", 0.9), kind="explicit")
        else:
            # Contradiction: do not flip silently, record the doubt.
            conflicted = True
            score = round(max(0.0, min(1.0, score * 0.6)), 4)

        explicit = sum(1 for e in ev if e.get("source") != "observed")
        observed = len(ev) - explicit
        conf = confidence_of(explicit, observed, conflicted=conflicted)
        cadence = existing.get("cadence") or pick_cadence(score, conf)

        rec = dict(existing)
        rec.update({
            "label": str(obs.get("label") or existing.get("label") or key)[:120],
            "entity": str(obs.get("entity") or existing.get("entity") or "")[:80],
            "category": str(obs.get("category") or existing.get("category") or "other")[:40],
            "polarity": new_polarity,
            "score": score,
            "confidence": conf,
            "cadence": cadence,
            "conflicted": conflicted,
            "evidence": ev,
            "updated": now,
            "last_engaged": now,
            "next_due": next_due_for(cadence, now),
        })
        self._upsert(rec)
        return rec

    def add(self, label: str, *, polarity: str = "like", category: str = "other",
            entity: str = "", cadence: str = "", source: str = "manual") -> dict | None:
        """Explicitly add an interest (dashboard). High confidence by nature."""
        label = " ".join(str(label or "").split())[:120]
        if not label:
            return None
        key = slugify(entity or label)
        polarity = polarity if polarity in POLARITIES else "like"
        now = _now()
        score = 0.9 if polarity == "like" else 0.2
        conf = confidence_of(explicit=1)
        cadence = cadence if cadence in CADENCES else (
            "off" if polarity == "dislike" else pick_cadence(score, conf))
        rec = {
            "chat_id": self.chat_id, "key": key, "label": label,
            "entity": str(entity or "")[:80], "category": str(category or "other")[:40],
            "polarity": polarity, "score": score, "confidence": conf,
            "cadence": cadence, "pinned": False, "muted": False, "conflicted": False,
            "source": source, "notes": "",
            "evidence": [{"ts": now, "source": source, "snippet": "added by the user",
                          "polarity": polarity, "strength": 1.0}],
            "created": now, "updated": now, "last_engaged": now,
            "last_pursued": 0, "next_due": next_due_for(cadence, now),
        }
        self._upsert(rec)
        return rec

    def update(self, key: str, **fields) -> dict | None:
        """Touch one interest: pin/mute/cadence/notes/polarity/label."""
        existing = self.get(key)
        if not existing:
            return None
        now = _now()
        rec = dict(existing)
        if "pinned" in fields:
            rec["pinned"] = bool(fields["pinned"])
        if "muted" in fields:
            rec["muted"] = bool(fields["muted"])
        if fields.get("cadence") in CADENCES:
            rec["cadence"] = fields["cadence"]
            rec["next_due"] = next_due_for(rec["cadence"], now,
                                           last_pursued=rec.get("last_pursued"))
        if fields.get("polarity") in POLARITIES:
            rec["polarity"] = fields["polarity"]
        if fields.get("label"):
            rec["label"] = " ".join(str(fields["label"]).split())[:120]
        if fields.get("category"):
            rec["category"] = str(fields["category"])[:40]
        if fields.get("notes") is not None:
            rec["notes"] = str(fields["notes"])[:2000]
        # Editing an interest is an explicit act of the user: it settles any
        # previous contradiction.
        if fields.get("resolve_conflict"):
            rec["conflicted"] = False
            rec["score"] = 0.8
            rec["confidence"] = confidence_of(explicit=2)
        rec["updated"] = now
        self._upsert(rec)
        return rec

    def touch(self, key: str, *, engaged: bool = False, pursued: bool = False) -> None:
        """Mark an interest as engaged with (user came back) or just nudged."""
        existing = self.get(key)
        if not existing:
            return
        now = _now()
        rec = dict(existing)
        if engaged:
            rec["last_engaged"] = now
            rec["score"] = blend_score(rec.get("score") or 0.0, 1.0, kind="explicit")
            rec["confidence"] = confidence_of(explicit=2)
            rec["conflicted"] = False
        if pursued:
            rec["last_pursued"] = now
            rec["next_due"] = next_due_for(rec.get("cadence") or "monthly", now)
        rec["updated"] = now
        self._upsert(rec)

    def feedback(self, key: str, positive: bool) -> dict | None:
        """👍/👎 on a nudge: learn from it instead of guessing."""
        existing = self.get(key)
        if not existing:
            return None
        now = _now()
        rec = dict(existing)
        ev = list(rec.get("evidence") or [])
        ev.append({"ts": now, "source": "feedback",
                   "snippet": "👍" if positive else "👎",
                   "polarity": "like" if positive else "dislike", "strength": 1.0})
        rec["evidence"] = ev[-25:]
        if positive:
            rec["score"] = blend_score(rec.get("score") or 0.0, 1.0, kind="explicit")
            rec["confidence"] = confidence_of(explicit=2)
            rec["last_engaged"] = now
        else:
            # A down-vote is a clear "back off": mute it, it can be re-enabled.
            rec["score"] = round(max(0.0, (rec.get("score") or 0.0) * 0.5), 4)
            rec["confidence"] = round((rec.get("confidence") or 0.0) * 0.7, 4)
            rec["muted"] = True
            rec["cadence"] = "off"
        rec["updated"] = now
        self._upsert(rec)
        return rec

    def delete(self, key: str) -> bool:
        k = slugify(key)
        self._ensure()
        if self._pg is not None:
            try:
                with self._pg.cursor() as cur:
                    cur.execute(
                        "DELETE FROM interests WHERE chat_id = %s AND key = %s",
                        (self.chat_id, k),
                    )
                return True
            except Exception:  # noqa: BLE001
                pass
        items = [i for i in self._read_file()
                 if not (i.get("key") == k and i.get("chat_id") in (0, self.chat_id))]
        self._write_file(items)
        return True

    # ------------------------------------------------------------- internals
    def _upsert(self, rec: dict) -> None:
        self._ensure()
        if self._pg is not None:
            try:
                with self._pg.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO interests
                          (chat_id, key, label, entity, category, polarity, score,
                           confidence, cadence, pinned, muted, conflicted, source,
                           evidence, notes, created, updated, last_engaged,
                           last_pursued, next_due, last_ref)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (chat_id, key) DO UPDATE SET
                          label = EXCLUDED.label, entity = EXCLUDED.entity,
                          category = EXCLUDED.category, polarity = EXCLUDED.polarity,
                          score = EXCLUDED.score, confidence = EXCLUDED.confidence,
                          cadence = EXCLUDED.cadence, pinned = EXCLUDED.pinned,
                          muted = EXCLUDED.muted, conflicted = EXCLUDED.conflicted,
                          evidence = EXCLUDED.evidence, notes = EXCLUDED.notes,
                          updated = EXCLUDED.updated,
                          last_engaged = EXCLUDED.last_engaged,
                          last_pursued = EXCLUDED.last_pursued,
                          next_due = EXCLUDED.next_due,
                          last_ref = EXCLUDED.last_ref
                        """,
                        (
                            rec.get("chat_id", self.chat_id), rec["key"], rec["label"],
                            rec.get("entity", ""), rec.get("category", "other"),
                            rec.get("polarity", "like"), rec.get("score", 0.5),
                            rec.get("confidence", 0.3), rec.get("cadence", "monthly"),
                            bool(rec.get("pinned")), bool(rec.get("muted")),
                            bool(rec.get("conflicted")), rec.get("source", ""),
                            json.dumps(rec.get("evidence") or []),
                            rec.get("notes", ""), rec.get("created", _now()),
                            rec.get("updated", _now()), rec.get("last_engaged", 0),
                            rec.get("last_pursued", 0), rec.get("next_due", 0),
                            rec.get("last_ref", ""),
                        ),
                    )
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("interest upsert failed, using file: %s", exc)
                self._pg = None
                self.backend = "file"
        items = self._read_file()
        rec = dict(rec)
        rec.setdefault("chat_id", self.chat_id)
        items = [i for i in items if i.get("key") != rec["key"]]
        items.append(rec)
        self._write_file(items)

    def learn_from_text(self, text: str, *, source: str = "chat") -> int:
        """Detect and record every interest in `text`. Returns how many stuck."""
        n = 0
        for obs in detect_observations(text):
            if self.observe(obs, source=source):
                n += 1
        return n
