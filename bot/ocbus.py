"""Bus d'événements SSE d'opencode.

Une seule connexion à GET /event, reconnexion automatique, et distribution
des événements aux abonnés indexés par sessionID.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

log = logging.getLogger("ocbus")

# Le serveur émet server.heartbeat toutes les ~10s. Sans trafic pendant ce
# délai, la connexion est morte (serveur figé, réseau coupé) : on coupe et on
# reconnecte plutôt que d'attendre indéfiniment sur un socket zombie.
READ_TIMEOUT = 60.0


class EventBus:
    def __init__(self, http: httpx.AsyncClient, base_url: str):
        self.http = http
        self.base_url = base_url.rstrip("/")
        self._subs: dict[str, list[asyncio.Queue]] = {}
        self._task: asyncio.Task | None = None
        self.connected = asyncio.Event()

    # ---------------------------------------------------------------- abonnés

    def subscribe(self, session_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(session_id, []).append(q)
        return q

    def unsubscribe(self, session_id: str, q: asyncio.Queue) -> None:
        lst = self._subs.get(session_id, [])
        if q in lst:
            lst.remove(q)
        if not lst:
            self._subs.pop(session_id, None)

    def _dispatch(self, event: dict[str, Any]) -> None:
        props = event.get("properties") or {}
        sid = props.get("sessionID")
        if not sid:
            return
        for q in self._subs.get(sid, []):
            q.put_nowait(event)

    # ------------------------------------------------------------------ boucle

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            reason = "fin de flux"
            try:
                async with self.http.stream(
                    "GET",
                    f"{self.base_url}/event",
                    timeout=httpx.Timeout(
                        connect=10.0, read=READ_TIMEOUT, write=10.0, pool=10.0
                    ),
                ) as resp:
                    resp.raise_for_status()
                    self.connected.set()
                    backoff = 1.0
                    log.info("flux d'événements connecté")
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw:
                            continue
                        try:
                            self._dispatch(json.loads(raw))
                        except json.JSONDecodeError:
                            log.debug("ligne SSE illisible: %.80s", raw)
            except asyncio.CancelledError:
                self.connected.clear()
                raise
            except Exception as exc:  # noqa: BLE001
                reason = str(exc) or type(exc).__name__

            # Un serveur qui ferme proprement termine aiter_lines() sans lever
            # d'exception : sans ce traitement commun, on ne se reconnecterait
            # jamais et connected resterait à True indéfiniment.
            self.connected.clear()
            log.warning("flux coupé (%s), reconnexion dans %.0fs", reason, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
