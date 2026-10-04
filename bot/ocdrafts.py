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
    def add(
        self,
        chat_id: int,
        kind: str,
        title: str,
        body: str,
        source: str = "",
        to: str = "",
        subject: str = "",
        message_id: str = "",
    ) -> int | None:
        kind = kind if kind in KINDS else "other"
        title = (title or "Brouillon")[:200]
        body = (body or "")[:20000]
        to = (to or "")[:320]
        subject = (subject or "")[:320]
        message_id = (message_id or "")[:998]
        self._ensure()
        if self._pg is not None:
            try:
                cur = self._pg.cursor()
                cur.execute(
                    "INSERT INTO drafts (ts, chat_id, kind, title, body, status, source, email_to, email_subject, message_id) "
                    "VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s) RETURNING id",
                    (int(time.time()), chat_id, kind, title, body, source[:200], to, subject, message_id),
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
                      "title": title, "body": body, "status": "pending", "source": source[:200],
                      "email_to": to, "email_subject": subject, "message_id": message_id})
        self._write_file(items)
        return did

    _COLS = "id, ts, kind, title, body, status, source, email_to, email_subject, message_id"

    @staticmethod
    def _row(r) -> dict:
        return {
            "id": r[0], "ts": r[1], "kind": r[2], "title": r[3], "body": r[4],
            "status": r[5], "source": r[6],
            "email_to": r[7] if len(r) > 7 else "", "email_subject": r[8] if len(r) > 8 else "",
            "message_id": r[9] if len(r) > 9 else "",
        }

    def list(self, status: str = "pending", limit: int = 40) -> list[dict]:
        self._ensure()
        if self._pg is not None:
            try:
                cur = self._pg.cursor()
                if status and status != "all":
                    cur.execute(
                        f"SELECT {self._COLS} FROM drafts WHERE status = %s ORDER BY ts DESC LIMIT %s",
                        (status, limit),
                    )
                else:
                    cur.execute(
                        f"SELECT {self._COLS} FROM drafts ORDER BY ts DESC LIMIT %s",
                        (limit,),
                    )
                return [self._row(r) for r in cur.fetchall()]
            except Exception:  # noqa: BLE001
                pass
        items = [d for d in self._read_file() if status in ("all", "") or d.get("status") == status]
        return list(reversed(items))[:limit]

    def update(
        self, draft_id: int, *, title=None, body=None, to=None, subject=None, message_id=None
    ) -> bool:
        """Edit a draft in place (used by the 'Edit' button in the dashboard)."""
        self._ensure()
        fields, values = [], []
        if title is not None:
            fields.append("title = %s"); values.append(str(title)[:200])
        if body is not None:
            fields.append("body = %s"); values.append(str(body)[:20000])
        if to is not None:
            fields.append("email_to = %s"); values.append(str(to)[:320])
        if subject is not None:
            fields.append("email_subject = %s"); values.append(str(subject)[:320])
        if message_id is not None:
            fields.append("message_id = %s"); values.append(str(message_id)[:998])
        if not fields:
            return False
        if self._pg is not None:
            try:
                self._pg.cursor().execute(
                    f"UPDATE drafts SET {', '.join(fields)} WHERE id = %s", (*values, draft_id)
                )
                return True
            except Exception:  # noqa: BLE001
                pass
        items = self._read_file()
        for d in items:
            if d.get("id") == draft_id:
                if title is not None:
                    d["title"] = str(title)[:200]
                if body is not None:
                    d["body"] = str(body)[:20000]
                if to is not None:
                    d["email_to"] = str(to)[:320]
                if subject is not None:
                    d["email_subject"] = str(subject)[:320]
                if message_id is not None:
                    d["message_id"] = str(message_id)[:998]
        self._write_file(items)
        return True

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
