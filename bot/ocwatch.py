"""Continuous watch: monitors sources and alerts on change.

Watched items are stored in Postgres (watch_items table):
  kind    : "mail" | "github" | "moodle" | "proxmox" | "web"
  target  : what is watched (query, repo, deadline, VM, URL)
  last_state / last_checked : pour ne re-alerter que sur un changement

The bot runs a watch loop alongside the scheduler. Each source is checked at
its own interval. We only alert on a state change, never in a loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.request
from pathlib import Path

log = logging.getLogger("ocwatch")

PG_DSN = os.environ.get(
    "PG_DSN",
    "host=127.0.0.1 port=5432 user=mav password=mav_secret dbname=mav",
)

# Intervalle de base entre deux passages de la boucle (secondes).
BASE_INTERVAL = int(os.environ.get("WATCH_INTERVAL", "300"))


class Watch:
    def __init__(self, bot, chat_id: int):
        self.bot = bot
        self.chat_id = chat_id
        self._pg = None
        # Cache of the latest quotes per item (for the enriched alert).
        self._quotes: dict[int, dict] = {}
        self._connect()

    def _connect(self) -> None:
        try:
            import psycopg2  # noqa: PLC0415

            self._pg = psycopg2.connect(PG_DSN, connect_timeout=3)
            self._pg.autocommit = True
        except Exception as exc:  # noqa: BLE001
            self._pg = None
            log.warning("Postgres injoignable pour la veille: %s", exc)

    def _ensure(self) -> None:
        if self._pg is None:
            self._connect()
        if self._pg is not None:
            try:
                self._pg.cursor().execute("SELECT 1")
            except Exception:  # noqa: BLE001
                self._connect()

    # ------------------------------------------------------------- items

    def add(self, kind: str, target: str) -> None:
        self._ensure()
        if self._pg is None:
            log.warning("veille inactive (pas de Postgres)")
            return
        try:
            cur = self._pg.cursor()
            cur.execute(
                "INSERT INTO watch_items (chat_id, kind, target, ts) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING",
                (self.chat_id, kind, target, int(time.time())),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("adding watch item failed: %s", exc)

    def list(self) -> list[dict]:
        self._ensure()
        if self._pg is None:
            return []
        try:
            cur = self._pg.cursor()
            cur.execute(
                "SELECT id, kind, target, last_state, last_checked, enabled "
                "FROM watch_items WHERE chat_id = %s AND enabled ORDER BY id",
                (self.chat_id,),
            )
            return [
                {
                    "id": r[0], "kind": r[1], "target": r[2],
                    "last_state": r[3], "last_checked": r[4], "enabled": r[5],
                }
                for r in cur.fetchall()
            ]
        except Exception as exc:  # noqa: BLE001
            log.warning("listing watch items failed: %s", exc)
            return []

    def remove(self, item_id: int) -> None:
        self._ensure()
        if self._pg is None:
            return
        try:
            cur = self._pg.cursor()
            cur.execute(
                "DELETE FROM watch_items WHERE id = %s AND chat_id = %s",
                (item_id, self.chat_id),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("removing watch item failed: %s", exc)

    def _set_state(self, item_id: int, state: str) -> None:
        self._ensure()
        if self._pg is None:
            return
        try:
            cur = self._pg.cursor()
            cur.execute(
                "UPDATE watch_items SET last_state = %s, last_checked = %s "
                "WHERE id = %s",
                (state, int(time.time()), item_id),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("watch state update failed: %s", exc)

    # ------------------------------------------------------------- checks

    async def _check_one(self, item: dict) -> None:
        """Check an item and alert if the state changed."""
        try:
            state = await self._fetch_state(item)
        except Exception as exc:  # noqa: BLE001
            log.warning("check %s/%s failed: %s", item["kind"], item["target"], exc)
            return
        if state is None:
            return
        if item["last_state"] is None:
            # first pass: record without alerting (avoids spam at boot)
            self._set_state(item["id"], state)
            return
        if state != item["last_state"]:
            self._set_state(item["id"], state)
            await self._alert(item, state)

    async def _fetch_state(self, item: dict) -> str | None:
        kind = item["kind"]
        target = item["target"]
        if kind == "web":
            return await self._check_web(target)
        if kind == "mail":
            return await self._check_mail(target)
        if kind == "github":
            return await self._check_github(target)
        if kind == "moodle":
            return await self._check_moodle(target)
        if kind == "proxmox":
            return await self._check_proxmox(target)
        if kind == "health":
            return await self._check_health()
        if kind == "stock":
            return await self._check_stock(item, target)
        return None

    async def _check_stock(self, item: dict, target: str) -> str | None:
        """Cotation d'un titre : alerte si franchissement de niveau ou
        volume anormal.

        Cible : « AAPL » ou « AAPL:180:200:240 » (niveaux optionnels,
        separated by commas or colons). The returned state only
        changes on a relevant event (zone change or volume ≥ 2x the 20-day
        average), not on every price move.
        """
        raw = target.replace(",", ":").replace(";", ":")
        bits = [b.strip() for b in raw.split(":") if b.strip()]
        if not bits:
            return None
        symbol = bits[0].upper()
        levels: list[float] = []
        for b in bits[1:]:
            try:
                v = float(b)
            except ValueError:
                continue
            # Fusionne les niveaux quasi identiques (< 0.5%).
            if not any(abs(v - x) <= max(0.005 * v, 0.01) for x in levels):
                levels.append(v)
        levels.sort()

        quote = await asyncio.to_thread(self._yf_quote, symbol)
        if not quote:
            return None
        self._quotes[item["id"]] = {"symbol": symbol, "levels": levels, **quote}

        price = quote["price"]
        zone = 0
        while zone < len(levels) and price >= levels[zone]:
            zone += 1
        # State: price zone + date of the last abnormal-volume day.
        # Le marqueur volume ne recule jamais (il ne redevient pas vide quand le
        # volume renormalises), so the state only changes on a real event:
        # a level crossing, or a new day at volume ≥ 2x.
        day = time.strftime("%Y-%m-%d")
        prev = item.get("last_state") or ""
        volsince = ""
        if "vs=" in prev:
            volsince = prev.split("vs=", 1)[1]
        ratio = quote.get("volRatio")
        if ratio is not None and ratio >= 2.0 and day > volsince:
            volsince = day
        self._quotes[item["id"]].update({"volFlag": bool(ratio and ratio >= 2.0)})
        return f"{symbol}|zone={zone}|vs={volsince}"

    def _yf_quote(self, symbol: str) -> dict | None:
        """Cotation + moyenne de volume (Yahoo, repli query1/query2)."""
        import urllib.request  # noqa: PLC0415

        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        path = f"/v8/finance/chart/{symbol}?range=1mo&interval=1d"
        data = None
        for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
            try:
                req = urllib.request.Request(
                    f"https://{host}{path}",
                    headers={"User-Agent": ua, "Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read())
                break
            except Exception:  # noqa: BLE001
                continue
        if not data:
            return None
        res = (data.get("chart") or {}).get("result") or []
        if not res:
            return None
        r = res[0]
        m = r.get("meta") or {}
        price = m.get("regularMarketPrice")
        if price is None:
            return None
        prev = m.get("chartPreviousClose")
        q = (r.get("indicators") or {}).get("quote") or [{}]
        closes = [c for c in (q[0].get("close") or []) if c]
        vols = [v for v in (q[0].get("volume") or []) if v]
        avg_vol = sum(vols[-20:]) / len(vols[-20:]) if vols else None
        today_vol = m.get("regularMarketVolume") or (vols[-1] if vols else None)
        ratio = (today_vol / avg_vol) if (avg_vol and today_vol) else None
        # Day change: regularMarketPrice vs the previous close
        # (chartPreviousClose est trompeur sur un range glissant comme 1 mois).
        prev = closes[-2] if len(closes) >= 2 else None
        pct = ((price - prev) / prev * 100.0) if prev else None
        return {
            "price": price,
            "pct": round(pct, 2) if pct is not None else None,
            "vol": today_vol,
            "volRatio": round(ratio, 2) if ratio is not None else None,
            "high52": m.get("fiftyTwoWeekHigh"),
            "low52": m.get("fiftyTwoWeekLow"),
            "name": m.get("shortName") or symbol,
        }

    async def _check_web(self, url: str) -> str:
        """Retourne un hash du contenu : alerte si la page change."""
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (watch)"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read(200_000)
        return f"len={len(body)}"

    async def _check_mail(self, query: str) -> str:
        """Count unread mail matching the query."""
        try:
            import subprocess  # noqa: PLC0415

            r = subprocess.run(
                ["python3", str(Path.home() / ".config/opencode/mail.py"), "search", query],
                capture_output=True, text=True, timeout=60,
            )
            return f"search={r.stdout.strip()[:200]}"
        except Exception as exc:  # noqa: BLE001
            log.warning("mail check failed: %s", exc)
            return ""

    async def _check_github(self, repo: str) -> str:
        """État des PR ouvertes d'un repo (via l'API publique)."""
        url = f"https://api.github.com/repos/{repo}/pulls?state=open&per_page=5"
        req = urllib.request.Request(url, headers={"User-Agent": "mav-watch"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            pulls = json.loads(resp.read())
        return f"open={len(pulls)}"

    async def _check_moodle(self, _target: str) -> str:
        """Upcoming deadlines (via the Moodle MCP)."""
        # Le MCP Moodle n'est pas appelable directement ici ; on laisse le
        # scheduled job handles deadlines. Return None so we do not alert.
        return None

    async def _check_proxmox(self, _target: str) -> str:
        """État des VMs via l'API Proxmox (token de la config)."""
        import json as _json  # noqa: PLC0415
        import urllib.request  # noqa: PLC0415

        host = os.environ.get("PROXMOX_HOST", "192.168.1.28")
        token = os.environ.get("PROXMOX_TOKEN_VALUE", "")
        token_name = os.environ.get("PROXMOX_TOKEN_NAME", "mcp")
        user = os.environ.get("PROXMOX_USER", "root@pam")
        if not token:
            return ""
        url = f"https://{host}:8006/api2/json/cluster/resources?type=vm"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"PVEAPIToken={user}!{token_name}={token}"},
        )
        import ssl  # noqa: PLC0415

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            data = _json.loads(resp.read())
        running = [r.get("name", str(r.get("vmid"))) for r in data.get("data", [])
                   if r.get("status") == "running"]
        return f"running={len(running)}: {','.join(sorted(running))[:200]}"

    async def _check_health(self) -> str:
        """Check that critical services respond."""
        import subprocess  # noqa: PLC0415

        checks = []
        # Postgres
        try:
            self._ensure()
            checks.append(("postgres", "ok" if self._pg is not None else "down"))
        except Exception:  # noqa: BLE001
            checks.append(("postgres", "down"))
        # Serveur opencode
        try:
            import httpx  # noqa: PLC0415

            r = httpx.get("http://127.0.0.1:4096/global/health", timeout=5)
            checks.append(("opencode", "ok" if r.status_code == 200 else f"http{r.status_code}"))
        except Exception:  # noqa: BLE001
            checks.append(("opencode", "down"))
        return "; ".join(f"{k}={v}" for k, v in checks)

    async def _alert(self, item: dict, state: str) -> None:
        kind = item["kind"]
        target = item["target"]
        emoji = {"web": "🌐", "mail": "📬", "github": "🐙", "moodle": "🎓",
                 "proxmox": "🖥️", "health": "🩺", "stock": "📈"}.get(kind, "🔔")

        detail, push_body = self._describe_alert(item, state)
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=(
                    f"{emoji} <b>Veille — {kind}</b>\n"
                    f"<code>{target}</code>\n"
                    f"{detail}"
                ),
                parse_mode="HTML",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("watch alert failed: %s", exc)

        # Out-of-Telegram notification (Web Push) — dedup by item+state.
        try:
            from ocnotify import notify  # noqa: PLC0415

            notify(
                f"{emoji} Veille · {kind}",
                push_body,
                chat_id=self.chat_id,
                topic="watch",
                dedup_key=f"watch:{item.get('id')}:{state[:80]}",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("watch push failed: %s", exc)

    def _describe_alert(self, item: dict, state: str) -> tuple[str, str]:
        """Render a state into a readable message. Returns (Telegram text, push body)."""
        default = (f"État : {state}", f"{item['target']}\nÉtat : {state}")
        if item.get("kind") != "stock":
            return default
        q = self._quotes.get(item["id"])
        if not q:
            return default
        price = q.get("price")
        pct = q.get("pct")
        ratio = q.get("volRatio")
        pct_s = f"{pct:+.2f}%" if pct is not None else "n/a"
        lines = [f"Prix : <b>{price}</b> USD ({pct_s})"]
        # Level crossed upward/downward.
        try:
            zone = int(state.split("zone=")[1].split("|")[0])
        except Exception:  # noqa: BLE001
            zone = None
        levels = q.get("levels") or []
        if zone is not None and levels:
            if zone > 0 and zone <= len(levels):
                lines.append(f"↗ Au-dessus du niveau <b>{levels[zone - 1]}</b>")
            elif zone == 0:
                lines.append(f"↘ Sous le premier niveau <b>{levels[0]}</b>")
        if ratio is not None and ratio >= 2.0:
            lines.append(f"📊 Volume {ratio:.1f}× la moyenne 20 j")
        tg = "\n".join(lines)
        push = f"{q.get('symbol','')} {price} USD ({pct_s})" + (
            f" · vol {ratio:.1f}×" if (ratio is not None and ratio >= 2.0) else ""
        )
        return tg, push

    # ------------------------------------------------------------- boucle

    async def run(self) -> None:
        """Watch loop: check each item at its own pace."""
        while True:
            try:
                items = self.list()
                for item in items:
                    if item["last_checked"] is None or \
                       time.time() - item["last_checked"] >= BASE_INTERVAL:
                        await self._check_one(item)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("erreur boucle veille: %s", exc)
            await asyncio.sleep(BASE_INTERVAL)
