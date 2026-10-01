"""RAG léger : recherche plein-texte dans les documents indexés (Postgres).

Utilise le full-text search natif de Postgres (tsvector + GIN), sans
embeddings à héberger ni service externe. Suffisant pour retrouver des
extraits pertinents dans les docs (Notion, mails, code) et les injecter
dans le contexte d'une session.
"""

from __future__ import annotations

import logging
import os
import time

log = logging.getLogger("ocrag")

PG_DSN = os.environ.get(
    "PG_DSN",
    "host=127.0.0.1 port=5432 user=mav password=mav_secret dbname=mav",
)


class RAG:
    def __init__(self):
        self._pg = None
        self._connect()

    def _connect(self) -> None:
        try:
            import psycopg2  # noqa: PLC0415

            self._pg = psycopg2.connect(PG_DSN, connect_timeout=3)
            self._pg.autocommit = True
        except Exception as exc:  # noqa: BLE001
            self._pg = None
            log.warning("Postgres injoignable pour le RAG: %s", exc)

    def _ensure(self) -> None:
        if self._pg is None:
            self._connect()
        if self._pg is not None:
            try:
                self._pg.cursor().execute("SELECT 1")
            except Exception:  # noqa: BLE001
                self._connect()

    def index(self, chat_id: int, title: str, body: str, source: str = "") -> None:
        """Indexe un document pour la recherche plein-texte."""
        if not title.strip() or not body.strip():
            return
        self._ensure()
        if self._pg is None:
            return
        try:
            cur = self._pg.cursor()
            cur.execute(
                "INSERT INTO documents (chat_id, title, body, source, ts) "
                "VALUES (%s, %s, %s, %s, %s)",
                (chat_id, title.strip()[:300], body.strip()[:20000],
                 source[:200], int(time.time())),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("indexation RAG échouée: %s", exc)

    def search(self, chat_id: int, query: str, top: int = 3) -> list[dict]:
        """Retourne les documents les plus pertinents pour la requête."""
        self._ensure()
        if self._pg is None:
            return []
        try:
            cur = self._pg.cursor()
            cur.execute(
                "SELECT title, body, source, ts, "
                "ts_rank(tsv, plainto_tsquery('french', %s)) AS rank "
                "FROM documents WHERE chat_id = %s "
                "AND tsv @@ plainto_tsquery('french', %s) "
                "ORDER BY rank DESC LIMIT %s",
                (query, chat_id, query, top),
            )
            return [
                {"title": r[0], "body": r[1], "source": r[2], "ts": r[3]}
                for r in cur.fetchall()
            ]
        except Exception as exc:  # noqa: BLE001
            log.warning("recherche RAG échouée: %s", exc)
            return []

    def context_block(self, chat_id: int, query: str, top: int = 3) -> str:
        """Bloc de contexte à injecter dans une session, si des docs matchent."""
        hits = self.search(chat_id, query, top)
        if not hits:
            return ""
        lines = [
            "<documents-pertinents>",
            "Extraits de documents indexés, retrouvés par recherche plein-texte.",
            "Utilise-les s'ils répondent à la question, ignore-les sinon.",
            "",
        ]
        for h in hits:
            when = time.strftime("%d/%m/%Y", time.localtime(h.get("ts", 0)))
            lines.append(f"[{when}] {h['title']}")
            if h.get("source"):
                lines.append(f"    source: {h['source']}")
            lines.append(f"    {h['body'][:400]}")
            lines.append("")
        lines.append("</documents-pertinents>")
        return "\n".join(lines)
