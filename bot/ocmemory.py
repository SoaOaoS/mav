"""Cross-session memory, stored in Postgres.

Two kinds of memory:
  - exchanges (`conversations` table): every finished question/answer from
    the dashboard. The most relevant ones are injected at
    the start of a new session.
  - facts (`facts` table): durable things to always remember ("I live in
    Lyon", "my main repo is foo/bar"), added with /remember or from the
    dashboard. They are always injected, before the recalled exchanges.

Retrieval uses Postgres full-text search (no embeddings to host, nothing to
reindex) with a gentle recency decay. If Postgres is unreachable, memory falls
back to a local JSON file with a dependency-free lexical scorer, so the bot
keeps working; the file is migrated into Postgres as soon as it is reachable.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
import unicodedata
from pathlib import Path

log = logging.getLogger("ocmemory")

PG_DSN = os.environ.get(
    "PG_DSN", "host=127.0.0.1 port=5432 user=mav password=mav_secret dbname=mav"
)

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

# The memory block is injected at the start of a new chat: keep it bounded so it
# never crowds out the actual conversation, however much the user has said.
# Facts get a share, recalled exchanges the rest.
MEMORY_BUDGET = int(os.environ.get("MEMORY_BUDGET", "4000") or 4000)
FACTS_BUDGET = max(600, int(MEMORY_BUDGET * 0.4))


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _norm_fact(text: str) -> str:
    """Fold a fact to a comparable key: no accents, punctuation or spacing."""
    lowered = fold(text)
    return re.sub(r"[^a-z0-9]+", " ", lowered).strip()


def _dedupe_facts(facts: list[str]) -> list[str]:
    """Drop duplicate facts, keeping the most recent occurrence.

    Input is ordered newest-first (as `facts()` returns it): an older entry is a
    duplicate if a newer one contains it, or is contained by it. Returns the
    surviving fact texts, still newest-first.
    """
    seen: list[str] = []
    out: list[str] = []
    for raw in facts:
        fact = " ".join(str(raw).split())
        if not fact:
            continue
        key = _norm_fact(fact)
        if not key or any(key == s or key in s or s in key for s in seen):
            continue
        seen.append(key)
        out.append(fact)
    return out

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          bigserial PRIMARY KEY,
    chat_id     bigint  NOT NULL,
    session_id  text    NOT NULL,
    question    text    NOT NULL,
    answer      text    NOT NULL,
    ts          bigint  NOT NULL
);
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS source text;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS agent  text;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('simple', question || ' ' || answer)) STORED;
CREATE INDEX IF NOT EXISTS idx_conv_chat ON conversations (chat_id);
CREATE INDEX IF NOT EXISTS idx_conv_ts   ON conversations (ts);
CREATE INDEX IF NOT EXISTS idx_conv_tsv  ON conversations USING gin (tsv);

CREATE TABLE IF NOT EXISTS facts (
    id       bigserial PRIMARY KEY,
    chat_id  bigint NOT NULL,
    fact     text   NOT NULL,
    source   text,
    ts       bigint NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_chat ON facts (chat_id);
"""


def stem(word: str) -> str:
    """Truncation: brings migration/migrations, config/configure together.

    Crude but dependency-free; tolerating plurals and inflections is enough.
    """
    return word[:STEM_LEN] if len(word) > STEM_LEN else word


def fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def normalise(text: str) -> list[str]:
    return [stem(w) for w in WORD.findall(fold(text)) if w not in STOP]


def ts_terms(text: str, limit: int = 24) -> list[str]:
    """Prefix terms for to_tsquery('simple', ...).

    Only [a-z0-9] survive, so anything built from this is a valid tsquery."""
    terms = []
    for w in WORD.findall(fold(text)):
        if w in STOP:
            continue
        w = re.sub(r"[^a-z0-9]", "", stem(w))
        if len(w) >= 3 and w not in terms:
            terms.append(w)
    return terms[:limit]


def ts_query(text: str) -> str:
    """OR-query: keeps recall high, at the cost of precision."""
    return " | ".join(f"{t}:*" for t in ts_terms(text))


def ts_query_and(text: str, min_terms: int = 2) -> str:
    """AND-query over the most meaningful terms, for precision.

    Returns "" when there are not enough distinct terms to be worth an AND
    (a single term would be as broad as the OR query)."""
    terms = ts_terms(text, limit=8)
    if len(terms) < min_terms:
        return ""
    return " & ".join(f"{t}:*" for t in terms)


class Memory:
    def __init__(self, path: Path, max_entries: int = 800, dsn: str | None = None):
        self.path = Path(path)
        self.max_entries = max_entries
        self.dsn = dsn or PG_DSN
        self._conn = None
        self._down_until = 0.0
        self._ready = False

    # ------------------------------------------------------------- postgres

    def _pg(self):
        """Live connection, or None. Backs off for a minute after a failure so
        an unreachable database never slows every message down."""
        if self._conn is not None and not self._conn.closed:
            return self._conn
        if time.time() < self._down_until:
            return None
        try:
            import psycopg2  # noqa: PLC0415

            self._conn = psycopg2.connect(self.dsn, connect_timeout=3)
            self._conn.autocommit = True
            if not self._ready:
                with self._conn.cursor() as cur:
                    cur.execute(SCHEMA)
                self._ready = True
                self._migrate_json()
            return self._conn
        except Exception as exc:  # noqa: BLE001
            log.warning("memory: Postgres unavailable (%s), using %s", exc, self.path)
            self._conn = None
            self._down_until = time.time() + 60
            return None

    def _q(self, sql: str, params: tuple = (), fetch: bool = True):
        conn = self._pg()
        if conn is None:
            raise RuntimeError("postgres unavailable")
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if fetch and cur.description:
                    cols = [d[0] for d in cur.description]
                    return [dict(zip(cols, r)) for r in cur.fetchall()]
                return []
        except Exception:
            # Broken connection: drop it, the next call reconnects.
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None
            raise

    @property
    def backend(self) -> str:
        return "postgres" if self._pg() is not None else "file"

    def _migrate_json(self) -> None:
        """Move exchanges from the legacy JSON file into Postgres, once."""
        entries = self._load()
        if not entries:
            return
        try:
            with self._conn.cursor() as cur:
                for e in entries:
                    cur.execute(
                        "INSERT INTO conversations "
                        "(chat_id, session_id, question, answer, ts, source) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (
                            int(e.get("chat", 0)),
                            str(e.get("session", "")),
                            e.get("q", ""),
                            e.get("a", ""),
                            int(e.get("ts", time.time())),
                            e.get("source", "legacy"),
                        ),
                    )
            self.path.rename(self.path.with_suffix(".json.migrated"))
            log.info("memory: migrated %d exchanges from %s to Postgres", len(entries), self.path)
        except Exception as exc:  # noqa: BLE001
            log.warning("memory: JSON migration failed: %s", exc)

    # ------------------------------------------------------------- file fallback

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

    # ------------------------------------------------------------- exchanges

    def add(
        self,
        chat_id: int,
        question: str,
        answer: str,
        session_id: str,
        source: str = "dashboard",
        agent: str = "",
    ) -> None:
        q, a = question.strip(), answer.strip()
        if not q or not a:
            return
        try:
            self._q(
                "INSERT INTO conversations "
                "(chat_id, session_id, question, answer, ts, source, agent) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (chat_id, session_id, q[:4000], a[:8000], int(time.time()), source, agent or None),
                fetch=False,
            )
            return
        except Exception as exc:  # noqa: BLE001
            log.debug("memory add via file: %s", exc)
        entries = self._load()
        entries.append(
            {
                "ts": int(time.time()),
                "chat": chat_id,
                "session": session_id,
                "q": q[:600],
                "a": a[:1200],
                "source": source,
            }
        )
        self._save(entries)

    def clear(self, chat_id: int) -> int:
        """Forget the exchanges of a chat (facts are kept: /forget facts)."""
        removed = 0
        try:
            rows = self._q(
                "WITH d AS (DELETE FROM conversations WHERE chat_id = %s RETURNING 1) "
                "SELECT count(*) AS n FROM d",
                (chat_id,),
            )
            removed = int(rows[0]["n"]) if rows else 0
        except Exception:  # noqa: BLE001
            pass
        entries = self._load()
        keep = [e for e in entries if e.get("chat") != chat_id]
        if len(keep) != len(entries):
            removed += len(entries) - len(keep)
            self._save(keep)
        return removed

    def count(self, chat_id: int) -> int:
        try:
            rows = self._q(
                "SELECT count(*) AS n FROM conversations WHERE chat_id = %s", (chat_id,)
            )
            return int(rows[0]["n"]) if rows else 0
        except Exception:  # noqa: BLE001
            return sum(1 for e in self._load() if e.get("chat") == chat_id)

    # ------------------------------------------------------------- facts

    def add_fact(self, chat_id: int, fact: str, source: str = "dashboard") -> bool:
        fact = " ".join(fact.split())[:500]
        if not fact:
            return False
        try:
            dup = self._q(
                "SELECT 1 FROM facts WHERE chat_id = %s AND lower(fact) = lower(%s) LIMIT 1",
                (chat_id, fact),
            )
            if dup:
                return True
            self._q(
                "INSERT INTO facts (chat_id, fact, source, ts) VALUES (%s, %s, %s, %s)",
                (chat_id, fact, source, int(time.time())),
                fetch=False,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("fact not stored: %s", exc)
            return False

    def facts(self, chat_id: int, limit: int = 20) -> list[dict]:
        try:
            return self._q(
                "SELECT id, fact, ts FROM facts WHERE chat_id = %s ORDER BY ts DESC LIMIT %s",
                (chat_id, limit),
            )
        except Exception:  # noqa: BLE001
            return []

    def clear_facts(self, chat_id: int) -> int:
        try:
            rows = self._q(
                "WITH d AS (DELETE FROM facts WHERE chat_id = %s RETURNING 1) "
                "SELECT count(*) AS n FROM d",
                (chat_id,),
            )
            return int(rows[0]["n"]) if rows else 0
        except Exception:  # noqa: BLE001
            return 0

    # ------------------------------------------------------------- retrieval

    _SEARCH_SQL = """
        SELECT question AS q, answer AS a, ts,
               ts_rank(tsv, to_tsquery('simple', %s))
                 / (1 + (extract(epoch FROM now()) - ts) / 86400.0 / 60) AS score
        FROM conversations
        WHERE chat_id = %s AND tsv @@ to_tsquery('simple', %s)
        ORDER BY score DESC
        LIMIT %s
    """

    def search(self, chat_id: int, query: str, top: int = 3) -> list[dict]:
        # Precision first: require the meaningful terms to co-occur. Fall back
        # to a broad OR only when the strict query finds nothing, so a
        # loosely-related exchange never crowds out a relevant one.
        strict = ts_query_and(query)
        broad = ts_query(query)
        if not broad:
            return []
        try:
            for pq in ([strict, broad] if strict else [broad]):
                rows = self._q(
                    self._SEARCH_SQL, (pq, chat_id, pq, top)
                )
                # Below this, recall is noise and pollutes the context.
                hits = [r for r in rows if (r.get("score") or 0) >= 0.005]
                if hits:
                    return hits
            return []
        except Exception as exc:  # noqa: BLE001
            log.debug("memory search via file: %s", exc)
        return self._search_file(chat_id, query, top)

    def _search_file(self, chat_id: int, query: str, top: int) -> list[dict]:
        entries = [e for e in self._load() if e.get("chat") == chat_id]
        q_terms = set(normalise(query))
        if not entries or not q_terms:
            return []
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
        return [e for s, e in scored[:top] if s >= 0.5]

    def context_block(self, chat_id: int, query: str, top: int = 3) -> str:
        fact_rows = self.facts(chat_id, limit=20)
        hits = self.search(chat_id, query, top)
        # Deduplicate near-identical facts (they tend to pile up over time).
        facts = _dedupe_facts([f["fact"] for f in fact_rows])
        if not facts and not hits:
            return ""

        # Facts are durable and always useful: give them the first share of the
        # budget, most recent first. Recalled exchanges fill what is left.
        fact_lines: list[str] = []
        used = 0
        for f in facts:
            line = f"- {_clip(f, 240)}"
            if used + len(line) + 1 > FACTS_BUDGET:
                break
            fact_lines.append(line)
            used += len(line) + 1

        exchange_lines: list[str] = []
        for e in hits:
            when = time.strftime("%Y-%m-%d", time.localtime(e.get("ts", 0)))
            chunk = (
                f"[{when}] Q: {_clip(e.get('q', ''), 300)}",
                f"           A: {_clip(e.get('a', ''), 500)}",
                "",
            )
            size = sum(len(c) + 1 for c in chunk)
            if used + size > MEMORY_BUDGET:
                break
            exchange_lines.extend(chunk)
            used += size

        if not fact_lines and not exchange_lines:
            return ""
        lines = [
            "<memory>",
            "Things you know about this user, retrieved automatically from past",
            "conversations. Use them when relevant, ignore them otherwise, and do",
            "not comment on them explicitly.",
            "",
        ]
        if fact_lines:
            lines.append("Facts:")
            lines.extend(fact_lines)
            lines.append("")
        if exchange_lines:
            lines.extend(exchange_lines)
        lines.append("</memory>")
        return "\n".join(lines)

    def recalled_count(self, block: str) -> int:
        return block.count("] Q:") + (block.count("\n- ") if "Facts:" in block else 0)
