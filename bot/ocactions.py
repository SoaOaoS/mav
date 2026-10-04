"""Background actions: launch a long task, come back with the result later.

A user asks something that takes a while ("research this and write me a page",
"monitor this and tell me when it's done"). Instead of blocking the chat, Mav
records an action, runs it in the background, and delivers the result as a
notification/inbox entry. This module is the record store; the actual work is
run by the dashboard (a thread) or the worker, exactly like a routine.

Same graceful degradation as drafts: Postgres when reachable, a JSON file
otherwise.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("ocactions")

BOT_DIR = Path(os.environ.get("BOT_DIR", Path(__file__).resolve().parent))
ACTIONS_FILE = Path(os.environ.get("ACTIONS_FILE", BOT_DIR / "actions.json"))
PG_DSN = os.environ.get(
    "PG_DSN",
    "host=127.0.0.1 port=5432 user=mav password=mav_secret dbname=mav",
)

STATUSES = ("queued", "running", "done", "failed")

__all__ = ["STATUSES", "Actions"]


class Actions:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or ACTIONS_FILE)
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
            self.path.write_text(json.dumps(items[-200:], indent=1))
        except Exception:
            pass

    def add(self, chat_id: int, name: str, kind: str = "task", link: str = "") -> int | None:
        self._ensure()
        now = int(time.time())
        if self._pg is not None:
            try:
                cur = self._pg.cursor()
                cur.execute(
                    "INSERT INTO actions (ts, chat_id, name, kind, status, link, updated) "
                    "VALUES (%s, %s, %s, %s, 'queued', %s, %s) RETURNING id",
                    (now, chat_id, (name or "Action")[:200], kind[:40], link[:300], now),
                )
                row = cur.fetchone()
                return row[0] if row else None
            except Exception as exc:  # noqa: BLE001
                log.warning("storing action failed, using file: %s", exc)
                self._pg = None
                self.backend = "file"
        items = self._read_file()
        aid = (items[-1]["id"] + 1) if items else 1
        items.append({"id": aid, "ts": now, "chat_id": chat_id, "name": (name or "Action")[:200],
                      "kind": kind[:40], "status": "queued", "result": None,
                      "link": link[:300], "updated": now})
        self._write_file(items)
        return aid

    def list(self, status: str = "all", limit: int = 40) -> list[dict]:
        self._ensure()
        if self._pg is not None:
            try:
                cur = self._pg.cursor()
                if status and status != "all":
                    cur.execute(
                        "SELECT id, ts, name, kind, status, result, link, updated, chat_id "
                        "FROM actions WHERE status = %s ORDER BY ts DESC LIMIT %s",
                        (status, limit),
                    )
                else:
                    cur.execute(
                        "SELECT id, ts, name, kind, status, result, link, updated, chat_id "
                        "FROM actions ORDER BY ts DESC LIMIT %s",
                        (limit,),
                    )
                return [
                    {"id": r[0], "ts": r[1], "name": r[2], "kind": r[3], "status": r[4],
                     "result": r[5], "link": r[6], "updated": r[7], "chat_id": r[8]}
                    for r in cur.fetchall()
                ]
            except Exception:  # noqa: BLE001
                pass
        items = [a for a in self._read_file() if status in ("all", "") or a.get("status") == status]
        return list(reversed(items))[:limit]

    def update(self, action_id: int, status: str, result: str | None = None, link: str | None = None) -> bool:
        status = status if status in STATUSES else "running"
        self._ensure()
        now = int(time.time())
        if self._pg is not None:
            try:
                self._pg.cursor().execute(
                    "UPDATE actions SET status = %s, result = coalesce(%s, result), "
                    "link = coalesce(%s, link), updated = %s WHERE id = %s",
                    (status, (result or "")[:20000] or None, link, now, action_id),
                )
                return True
            except Exception:  # noqa: BLE001
                pass
        items = self._read_file()
        for a in items:
            if a.get("id") == action_id:
                a["status"] = status
                if result is not None:
                    a["result"] = result[:20000]
                if link is not None:
                    a["link"] = link
                a["updated"] = now
        self._write_file(items)
        return True

    def get(self, action_id: int) -> dict | None:
        return next((a for a in self.list("all", limit=500) if a["id"] == action_id), None)
