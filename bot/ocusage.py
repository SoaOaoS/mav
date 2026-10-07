"""What Mav costs: tokens and money per day, a monthly budget, a cheap model.

The engine reports `tokens` and `cost` (USD, from its model price list) on
every assistant message. The web app and the worker add each answer here,
tagged by source (chat, routine, background). Stored in one small JSON file
(BOT_DIR/usage.json) shared by both processes under a file lock, so it works
without the database too.

Budget: a monthly amount in USD and what to do when it is reached — "warn"
(notify at 80 % and 100 %) or "stop" (also refuse new answers until the
next month, or until the budget is raised).
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

SOURCES = ("chat", "routine", "background")
KEEP_DAYS = 400


def _month(ts: float | None = None) -> str:
    return time.strftime("%Y-%m", time.localtime(ts or time.time()))


def _day(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts or time.time()))


def tally(entries: list[dict]) -> dict:
    """Sum the tokens and cost of engine assistant messages."""
    out = {"input": 0, "output": 0, "cost": 0.0, "model": ""}
    for e in entries or []:
        info = (e or {}).get("info") or e or {}
        tok = info.get("tokens") or {}
        cache = tok.get("cache") or {}
        out["input"] += int(tok.get("input") or 0) + int(cache.get("read") or 0)
        out["output"] += int(tok.get("output") or 0) + int(tok.get("reasoning") or 0)
        out["cost"] += float(info.get("cost") or 0)
        if info.get("modelID"):
            out["model"] = f"{info.get('providerID') or ''}/{info['modelID']}".strip("/")
    return out


SPEED_KEEP = 500  # answers whose timings are kept


def _median(values: list) -> float | None:
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    mid = len(v) // 2
    return v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2


def _p90(values: list) -> float | None:
    v = sorted(x for x in values if x is not None)
    return v[min(len(v) - 1, int(round(0.9 * (len(v) - 1))))] if v else None


def speed_stats(samples: list[dict]) -> dict:
    """Medians over answers: what "fast" means is the typical answer, not the mean
    (one slow web search must not hide that most answers got quicker)."""
    if not samples:
        return {"answers": 0}
    ins = [s.get("in", 0) for s in samples]
    cached = sum(s.get("cached", 0) for s in samples)
    total_in = sum(ins)
    return {
        "answers": len(samples),
        "ttft_ms": _median([s.get("ttft") for s in samples]),
        "ttft_p90_ms": _p90([s.get("ttft") for s in samples]),
        "total_ms": _median([s.get("total") for s in samples]),
        "steps": round(sum(s.get("steps", 0) for s in samples) / len(samples), 2),
        "input_tokens": _median(ins),
        "cached_pct": round(100 * cached / total_in, 1) if total_in else None,
    }


class Usage:
    def __init__(self, path: Path):
        self.path = Path(path)

    # ------------------------------------------------------------- storage
    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.with_suffix(".lock"), "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def _write(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    # ------------------------------------------------------------- record
    def record(self, source: str, input_tokens: int = 0, output_tokens: int = 0,
               cost: float = 0.0, model: str = "", ts: float | None = None) -> None:
        source = source if source in SOURCES else "chat"
        if not (input_tokens or output_tokens or cost):
            return
        with self._locked():
            data = self._read()
            days = data.setdefault("days", {})
            d = days.setdefault(_day(ts), {})
            s = d.setdefault(source, {"answers": 0, "input": 0, "output": 0, "cost": 0.0})
            s["answers"] += 1
            s["input"] += int(input_tokens)
            s["output"] += int(output_tokens)
            s["cost"] = round(s["cost"] + float(cost), 6)
            if model:
                models = data.setdefault("models", {})
                models[model] = round(float(models.get(model, 0.0)) + float(cost), 6)
            for old in sorted(days)[:-KEEP_DAYS]:
                days.pop(old, None)
            self._write(data)

    def record_entries(self, source: str, entries: list[dict]) -> dict:
        t = tally(entries)
        self.record(source, t["input"], t["output"], t["cost"], t["model"])
        return t

    # ------------------------------------------------------------- speed
    def record_speed(self, source: str, ttft_ms: int | None, total_ms: int, steps: int,
                     input_tokens: int = 0, cached_tokens: int = 0, ts: float | None = None) -> None:
        """One answer's timings: time to first word, total, steps, prompt size."""
        sample = {"ts": int(ts or time.time()), "src": source if source in SOURCES else "chat",
                  "ttft": int(ttft_ms) if ttft_ms is not None else None, "total": int(total_ms),
                  "steps": int(steps), "in": int(input_tokens), "cached": int(cached_tokens)}
        with self._locked():
            data = self._read()
            speed = data.setdefault("speed", [])
            speed.append(sample)
            del speed[:-SPEED_KEEP]
            self._write(data)

    def speed_summary(self, days: int = 30, source: str | None = "chat") -> dict:
        since = time.time() - days * 86400
        samples = [s for s in self._read().get("speed", [])
                   if s.get("ts", 0) >= since and (source is None or s.get("src") == source)]
        return speed_stats(samples)

    # ------------------------------------------------------------- reading
    def month_cost(self, month: str | None = None) -> float:
        month = month or _month()
        days = self._read().get("days", {})
        return round(sum(
            s.get("cost", 0.0) for day, by in days.items() if day.startswith(month)
            for s in by.values()
        ), 6)

    def summary(self, days: int = 30) -> dict:
        data = self._read()
        all_days = data.get("days", {})
        month = _month()
        series = []
        now = time.time()
        for i in range(days - 1, -1, -1):
            key = _day(now - i * 86400)
            by = all_days.get(key, {})
            series.append({
                "day": key,
                "cost": round(sum(s.get("cost", 0.0) for s in by.values()), 6),
                "tokens": sum(s.get("input", 0) + s.get("output", 0) for s in by.values()),
                "answers": sum(s.get("answers", 0) for s in by.values()),
            })
        by_source = {src: {"answers": 0, "tokens": 0, "cost": 0.0} for src in SOURCES}
        for day, by in all_days.items():
            if not day.startswith(month):
                continue
            for src, s in by.items():
                b = by_source.setdefault(src, {"answers": 0, "tokens": 0, "cost": 0.0})
                b["answers"] += s.get("answers", 0)
                b["tokens"] += s.get("input", 0) + s.get("output", 0)
                b["cost"] = round(b["cost"] + s.get("cost", 0.0), 6)
        cost = self.month_cost(month)
        budget = self.budget()
        return {
            "month": month,
            "cost": cost,
            "tokens": sum(b["tokens"] for b in by_source.values()),
            "answers": sum(b["answers"] for b in by_source.values()),
            "by_source": by_source,
            "days": series,
            "budget": budget,
            "used_pct": round(100 * cost / budget["monthly_usd"], 1) if budget["monthly_usd"] else None,
            "blocked": self.blocked(),
            "small_model": data.get("small_model", ""),
            "models": data.get("models", {}),
        }

    # ------------------------------------------------------------- budget
    def budget(self) -> dict:
        b = self._read().get("budget") or {}
        return {"monthly_usd": float(b.get("monthly_usd") or 0), "action": b.get("action") or "warn"}

    def set_budget(self, monthly_usd: float, action: str = "warn") -> dict:
        if monthly_usd < 0 or action not in ("warn", "stop"):
            raise ValueError("Budget must be ≥ 0 and the action warn or stop.")
        with self._locked():
            data = self._read()
            data["budget"] = {"monthly_usd": round(float(monthly_usd), 2), "action": action}
            self._write(data)
        return self.budget()

    def set_small_model(self, ref: str) -> None:
        with self._locked():
            data = self._read()
            data["small_model"] = (ref or "").strip()
            self._write(data)

    def small_model(self) -> str:
        return str(self._read().get("small_model") or "")

    def blocked(self) -> bool:
        """True when the budget says to stop and it is used up this month."""
        b = self.budget()
        return b["action"] == "stop" and b["monthly_usd"] > 0 and self.month_cost() >= b["monthly_usd"]

    def alert_due(self) -> int | None:
        """80 or 100 when that threshold was just crossed (once per month)."""
        b = self.budget()
        if not b["monthly_usd"]:
            return None
        pct = 100 * self.month_cost() / b["monthly_usd"]
        level = 100 if pct >= 100 else 80 if pct >= 80 else None
        if level is None:
            return None
        with self._locked():
            data = self._read()
            sent = data.setdefault("alerts", {})
            key = f"{_month()}:{level}"
            if sent.get(key):
                return None
            sent[key] = int(time.time())
            self._write(data)
        return level
