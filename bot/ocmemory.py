"""Cross-session memory.

Stores every finished exchange, then finds the most relevant ones to inject
at the start of a new session.

Scoring is lexical (simplified TF-IDF), deliberately with no dependency and no
network call: no embeddings to host, nothing to reindex, and the behaviour
stays inspectable. Enough for a few hundred exchanges.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
import unicodedata
from pathlib import Path

log = logging.getLogger("ocmemory")

# FR + EN stop words: without these, "comment" and "the" dominate the score.
STOP = set(
    """le la les un une des du de au aux et ou mais donc or ni car que qui quoi
    dont ou a as ai est sont etre ete avoir eu pour par sur sous dans avec sans
    ce cet cette ces mon ton son nos vos leur il elle ils elles je tu nous vous
    on se sa ses lui y en pas ne plus moins tres bien fait faire comment
    pourquoi quand est-ce qu quel quelle quels quelles tout tous toute toutes
    the a an and or but so of to in on at for with without from by is are was
    were be been being have has had do does did not no yes this that these
    those it its he she they we you i my your his her their our what how why
    when where which who whom can could would should will shall may might must
    if then than as about into over under""".split()
)

WORD = re.compile(r"[a-z0-9_\-./]{3,}")
STEM_LEN = 6


def stem(word: str) -> str:
    """Troncature : rapproche migration/migrations, config/configurer.

    Crude but dependency-free, and the intended effect (tolerating plurals and
    flexions) est atteint sans le coût d'un vrai stemmer multilingue.
    """
    return word[:STEM_LEN] if len(word) > STEM_LEN else word


def normalise(text: str) -> list[str]:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return [stem(w) for w in WORD.findall(text) if w not in STOP]


class Memory:
    def __init__(self, path: Path, max_entries: int = 800):
        self.path = Path(path)
        self.max_entries = max_entries

    # ------------------------------------------------------------- stockage

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save(self, entries: list[dict]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(entries[-self.max_entries :], indent=1))
        except Exception as exc:  # noqa: BLE001
            log.warning("memory not persisted: %s", exc)

    def add(self, chat_id: int, question: str, answer: str, session_id: str) -> None:
        if not question.strip() or not answer.strip():
            return
        entries = self._load()
        entries.append(
            {
                "ts": int(time.time()),
                "chat": chat_id,
                "session": session_id,
                "q": question.strip()[:600],
                "a": answer.strip()[:1200],
            }
        )
        self._save(entries)

    def clear(self, chat_id: int) -> int:
        entries = self._load()
        keep = [e for e in entries if e.get("chat") != chat_id]
        removed = len(entries) - len(keep)
        self._save(keep)
        return removed

    def count(self, chat_id: int) -> int:
        return sum(1 for e in self._load() if e.get("chat") == chat_id)

    # ------------------------------------------------------------- retrieval

    def search(self, chat_id: int, query: str, top: int = 3) -> list[dict]:
        entries = [e for e in self._load() if e.get("chat") == chat_id]
        if not entries:
            return []

        q_terms = set(normalise(query))
        if not q_terms:
            return []

        # IDF sur le corpus de ce chat
        docs = [set(normalise(f"{e['q']} {e['a']}")) for e in entries]
        n = len(docs)
        idf = {
            t: math.log(1 + n / (1 + sum(1 for d in docs if t in d))) for t in q_terms
        }

        now = time.time()
        scored = []
        for entry, terms in zip(entries, docs):
            overlap = q_terms & terms
            if not overlap:
                continue
            score = sum(idf[t] for t in overlap)
            # Gentle decay: a 60-day-old exchange weighs roughly half
            age_days = (now - entry.get("ts", now)) / 86400
            score *= 1 / (1 + age_days / 60)
            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        # Seuil : sous 0.5 le rappel est du bruit et pollue le contexte
        return [e for s, e in scored[:top] if s >= 0.5]

    def context_block(self, chat_id: int, query: str, top: int = 3) -> str:
        hits = self.search(chat_id, query, top)
        if not hits:
            return ""
        lines = [
            "<contexte-anterieur>",
            "Excerpts from previous exchanges with this user, retrieved by",
            "automatiquement. Utilise-les s'ils sont pertinents, ignore-les sinon.",
            "Ne les commente pas explicitement.",
            "",
        ]
        for e in hits:
            when = time.strftime("%d/%m/%Y", time.localtime(e.get("ts", 0)))
            lines.append(f"[{when}] Q: {e['q'][:300]}")
            lines.append(f"          R: {e['a'][:500]}")
            lines.append("")
        lines.append("</contexte-anterieur>")
        return "\n".join(lines)
