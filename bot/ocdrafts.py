"""Drafts Mav prepares for the user to review and send.

When a routine notices something that needs an action (a mail to answer, a
follow-up to send, a note to file), Mav can propose a ready-to-send draft
instead of just reporting it. Drafts show up in the dashboard, where the user
edits/copies/discards them.

Storage is best-effort and falls back to a JSON file so a no-Docker install
still works (same graceful degradation as memory/notifications). The logic
here is pure CRUD, unit-tested without a database.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("ocdrafts")

BOT_DIR = Path(os.environ.get("BOT_DIR", Path(__file__).resolve().parent))
DRAFTS_FILE = Path(os.environ.get("DRAFTS_FILE", BOT_DIR / "drafts.json"))
PG_DSN = os.environ.get(
    "PG_DSN",
    "host=127.0.0.1 port=5432 user=mav password=mav_secret dbname=mav",
)

KINDS = ("reply", "message", "note", "plan", "other")
STATUSES = ("pending", "sent", "discarded")

__all__ = ["KINDS", "STATUSES", "Drafts"]


class Drafts:
    """Draft store: Postgres when reachable, a JSON file otherwise.

    Same public shape either way, so callers do not care which backend is
    live. ``backend`` tells which one is in use.
    """

    def __init__(self, path: Path | None = None):
        self.path = Path(path or DRAFTS_FILE)
        self._pg = None
        self.backend = "none"
        self._connect()

    def _connect(self) -> None:
        try:
            import psycopg2  # noqa: PLC0415

            self._pg = psycopg2.connect(PG_DSN, connect_timeout=3)
            self._pg.autocommit = True
            self.backend = "postgres"
        except Exception:  # noqa: BLE001
            self._pg = None
            self.backend = "file"

    def _ensure(self) -> None:
        if self._pg is None and self.backend == "postgres":
            self._connect()
        if self._pg is not None:
            try:
                self._pg.cursor().execute("SELECT 1")
            except Exception:  # noqa: BLE001
                self._connect()

    # ------------------------------------------------------------- file sink
    def _read_file(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _write_file(self, items: list[dict]) -> None:
        try:
            self.path.write_text(json.dumps(items[-200:], indent=1))
        except Exception:
            pass

    # --------------------------------------------------------------- public
    def add(self, chat_id: int, kind: str, title: str, body: str, source: str = "") -> int | None:
        kind = kind if kind in KINDS else "other"
        title = (title or "Brouillon")[:200]
        body = (body or "")[:20000]
        self._ensure()
        if self._pg is not None:
            try:
                cur = self._pg.cursor()
                cur.execute(
                    "INSERT INTO drafts (ts, chat_id, kind, title, body, status, source) "
                    "VALUES (%s, %s, %s, %s, %s, 'pending', %s) RETURNING id",
                    (int(time.time()), chat_id, kind, title, body, source[:200]),
                )
                row = cur.fetchone()
                return row[0] if row else None
            except Exception as exc:  # noqa: BLE001
                log.warning("storing draft failed, using file: %s", exc)
                self._pg = None
                self.backend = "file"
        items = self._read_file()
        did = (items[-1]["id"] + 1) if items else 1
        items.append({"id": did, "ts": int(time.time()), "chat_id": chat_id, "kind": kind,
                      "title": title, "body": body, "status": "pending", "source": source[:200]})
        self._write_file(items)
        return did

    def list(self, status: str = "pending", limit: int = 40) -> list[dict]:
        self._ensure()
        if self._pg is not None:
            try:
                cur = self._pg.cursor()
                if status and status != "all":
                    cur.execute(
                        "SELECT id, ts, kind, title, body, status, source FROM drafts "
                        "WHERE status = %s ORDER BY ts DESC LIMIT %s",
                        (status, limit),
                    )
                else:
                    cur.execute(
                        "SELECT id, ts, kind, title, body, status, source FROM drafts "
                        "ORDER BY ts DESC LIMIT %s",
                        (limit,),
                    )
                return [
                    {"id": r[0], "ts": r[1], "kind": r[2], "title": r[3],
                     "body": r[4], "status": r[5], "source": r[6]}
                    for r in cur.fetchall()
                ]
            except Exception:  # noqa: BLE001
                pass
        items = [d for d in self._read_file() if status in ("all", "") or d.get("status") == status]
        return list(reversed(items))[:limit]

    def get(self, draft_id: int) -> dict | None:
        return next((d for d in self.list("all", limit=500) if d["id"] == draft_id), None)

    def set_status(self, draft_id: int, status: str) -> bool:
        status = status if status in STATUSES else "pending"
        self._ensure()
        if self._pg is not None:
            try:
                self._pg.cursor().execute("UPDATE drafts SET status = %s WHERE id = %s", (status, draft_id))
                return True
            except Exception:  # noqa: BLE001
                pass
        items = self._read_file()
        for d in items:
            if d.get("id") == draft_id:
                d["status"] = status
        self._write_file(items)
        return True

    def delete(self, draft_id: int) -> bool:
        self._ensure()
        if self._pg is not None:
            try:
                self._pg.cursor().execute("DELETE FROM drafts WHERE id = %s", (draft_id,))
                return True
            except Exception:  # noqa: BLE001
                pass
        self._write_file([d for d in self._read_file() if d.get("id") != draft_id])
        return True
