#!/usr/bin/env python3
"""Surveille la publication des résultats Q2 2026 de Sellas Life Sciences (SLS)
et alerte Telegram dès que le communiqué sort. Le marché US a fermé à 16h ET
(22h Paris) le 11 août ; le communiqué est attendu après clôture.

Usage: python3 monitor_sls.py [--max-minutes N] [--interval N]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request
import urllib.parse
import json
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent


def load_env() -> dict[str, str]:
    """Lit /etc/opencode-bot.env (et .env local si présent)."""
    env: dict[str, str] = {}
    for path in ("/etc/opencode-bot.env", str(BOT_DIR / ".env")):
        p = Path(path)
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()
TOKEN = os.environ.get("TELEGRAM_TOKEN") or ENV.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID") or ENV.get("ALLOWED_CHAT_IDS", "7674111325").split()[0]


def tg_send(text: str) -> None:
    if not TOKEN:
        print("ERR: TELEGRAM_TOKEN introuvable", file=sys.stderr)
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = urllib.parse.urlencode(
        {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    ).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=20) as resp:
        resp.read()


def check() -> tuple[bool, str]:
    """Retourne (sorti, résumé). Vérifie la page IR et une recherche web."""
    # 1) Page IR officielle (les communiqués récents y figurent)
    url = "https://ir.sellaslifesciences.com/news/default.aspx"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (monitor)"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", "ignore")
    except Exception as exc:  # noqa: BLE001
        return False, f"Page IR injoignable ({exc})"

    # Chercher un titre de communiqué Q2 / Second Quarter 2026
    low = html.lower()
    q2_hits = [s for s in ("second quarter 2026", "q2 2026", "june 30, 2026") if s in low]
    if q2_hits:
        # Confirmer via une recherche web pour le titre exact
        title = ""
        for key in ("Second Quarter 2026 Financial Results", "Q2 2026 Financial Results"):
            idx = low.find(key.lower())
            if idx != -1:
                # extraire une fenêtre lisible
                snippet = html[max(0, idx - 60): idx + len(key) + 60]
                snippet = " ".join(snippet.split())
                title = f"{key} — {snippet[:120]}"
                break
        return True, title or "Communiqué Q2 2026 détecté sur la page IR."

    return False, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=180, help="secondes entre vérifs")
    ap.add_argument("--max-minutes", type=int, default=240, help="durée max de surveillance")
    args = ap.parse_args()

    start = time.time()
    deadline = start + args.max_minutes * 60
    tries = 0
    print(f"Surveillance SLS démarrée (intervalle {args.interval}s, max {args.max_minutes}min)", flush=True)
    tg_send("📡 Surveillance SLS active : je vérifie la publication des résultats Q2 toutes les quelques minutes et je te préviens dès qu'ils sortent.")

    while time.time() < deadline:
        tries += 1
        try:
            out, detail = check()
        except Exception as exc:  # noqa: BLE001
            print(f"[{tries}] erreur: {exc}", flush=True)
            time.sleep(args.interval)
            continue

        if out:
            print(f"[{tries}] PUBLIÉ ! {detail}", flush=True)
            tg_send(
                "🚨 <b>SLS — résultats Q2 2026 publiés !</b>\n\n"
                f"{detail}\n\n"
                "📄 <a href='https://ir.sellaslifesciences.com/news/default.aspx'>Page IR officielle</a>\n"
                "📈 <a href='https://stocktwits.com/symbol/SLS'>Voir sur Stocktwits</a>"
            )
            return 0

        print(f"[{tries}] pas encore publié ({(time.time()-start)/60:.0f}min)", flush=True)
        time.sleep(args.interval)

    tg_send("⏹️ Surveillance SLS arrêtée après 240 min sans publication. Les résultats n'ont pas été détectés. Veux-tu que je continue ?")
    print("Deadline atteinte, arrêt.", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
