"""Exécutions programmées.

Fichier jobs.json :

[
  {
    "name": "brief",
    "time": "08:00",
    "days": ["mon","tue","wed","thu","fri"],
    "chat_id": 123456789,
    "agent": "research",
    "prompt": "Résume l'état des PR ouvertes sur mes repos et les CI en échec.",
    "enabled": true
  }
]

Volontairement pas de cron complet : une heure et des jours suffisent pour un
brief quotidien, et le format reste lisible sans documentation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path

log = logging.getLogger("ocjobs")

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def load_jobs(path: Path) -> list[dict]:
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return []
    except Exception as exc:  # noqa: BLE001
        log.error("jobs.json illisible: %s", exc)
        return []
    if not isinstance(data, list):
        log.error("jobs.json doit contenir une liste")
        return []
    return [j for j in data if validate(j)]


def validate(job: dict) -> bool:
    name = job.get("name", "?")
    if not TIME_RE.match(str(job.get("time", ""))):
        log.error("job %s : champ 'time' invalide (attendu HH:MM)", name)
        return False
    if not isinstance(job.get("chat_id"), int):
        log.error("job %s : 'chat_id' manquant ou non entier", name)
        return False
    if not job.get("prompt"):
        log.error("job %s : 'prompt' vide", name)
        return False
    bad = [d for d in job.get("days", DAYS) if d not in DAYS]
    if bad:
        log.error("job %s : jours inconnus %s", name, bad)
        return False
    return True


def due(job: dict, now: datetime, last_run: str | None) -> bool:
    if not job.get("enabled", True):
        return False
    if DAYS[now.weekday()] not in job.get("days", DAYS):
        return False
    if now.strftime("%H:%M") != job["time"]:
        return False
    return last_run != now.strftime("%Y-%m-%d %H:%M")


class Scheduler:
    """Boucle une fois par minute et déclenche les jobs échus.

    L'état des dernières exécutions est persisté : un redémarrage à 08:00:30
    ne doit pas rejouer le brief de 08:00.
    """

    def __init__(self, jobs_path: Path, state_path: Path, runner):
        self.jobs_path = Path(jobs_path)
        self.state_path = Path(state_path)
        self.runner = runner  # async (job) -> None
        self._task: asyncio.Task | None = None

    def _state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text())
        except Exception:
            return {}

    def _mark(self, name: str, stamp: str) -> None:
        state = self._state()
        state[name] = stamp
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(state, indent=1))
        except Exception as exc:  # noqa: BLE001
            log.warning("état du planificateur non persisté: %s", exc)

    async def _tick(self) -> None:
        now = datetime.now()
        state = self._state()
        for job in load_jobs(self.jobs_path):
            name = job["name"]
            if due(job, now, state.get(name)):
                self._mark(name, now.strftime("%Y-%m-%d %H:%M"))
                log.info("déclenchement du job %s", name)
                asyncio.create_task(self._safe_run(job))

    async def _safe_run(self, job: dict) -> None:
        try:
            await self.runner(job)
        except Exception:  # noqa: BLE001
            log.exception("job %s en échec", job.get("name"))

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("erreur dans la boucle du planificateur")
            # Se recale sur le début de la minute suivante
            await asyncio.sleep(60 - datetime.now().second % 60)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
