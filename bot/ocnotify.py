"""Notifications proactives de Mav — Web Push + historique/dédup.

Objectif : permettre au bot (veille, jobs) de *venir vers* Raphaël, pas
seulement de répondre. Une seule logique, deux usages :

  - veille    (ocwatch)   : alerte quand un état change ;
  - jobs      (run_job)   : résumé court quand un rapport est prêt.

Les clés VAPID et les abonnements sont les mêmes que ceux du dashboard
(~/bot/vapid_private.pem, ~/bot/push_subs.json) : un abonnement pris dans
l'interface sert donc aussi au bot.

Postgres sert à deux choses :
  - table `notifications` : historique (futur centre de notifs) ;
  - dédoublonnage : un même `dedup_key` non relivré pendant un délai.

Tout est optionnel et silencieux : sans Postgres ou sans abonné, on ne plante
jamais — on n'envoie simplement pas.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("ocnotify")

BOT_DIR = Path(os.environ.get("BOT_DIR", Path(__file__).resolve().parent))
PUSH_FILE = Path(os.environ.get("PUSH_FILE", BOT_DIR / "push_subs.json"))
VAPID_PEM = BOT_DIR / "vapid_private.pem"

PG_DSN = os.environ.get(
    "PG_DSN",
    "host=127.0.0.1 port=5432 user=mav password=mav_secret dbname=mav",
)

# Délai anti-doublon par défaut (secondes) : 6 h.
DEDUP_WINDOW = int(os.environ.get("NOTIFY_DEDUP_WINDOW", "21600"))

# Heures calmes : pas de notification entre QUIET_START et QUIET_END (locales).
# Format "23-7". Mettre "0-0" pour désactiver.
_q = os.environ.get("NOTIFY_QUIET", "23-7")
try:
    _qs, _qe = (int(x) for x in _q.split("-", 1))
except Exception:  # noqa: BLE001
    _qs, _qe = 23, 7
QUIET_START, QUIET_END = _qs, _qe

# Contact VAPID (obligatoire pour le protocole Web Push) : renseigné par
# l'installeur via MAV_VAPID_SUB, sinon valeur neutre.
_VAPID_SUB = os.environ.get("MAV_VAPID_SUB") or "mailto:admin@localhost"
_vapid_obj = None


# --------------------------------------------------------------- postgres
_pg = None


def _connect():
    global _pg
    try:
        import psycopg2  # noqa: PLC0415

        _pg = psycopg2.connect(PG_DSN, connect_timeout=3)
        _pg.autocommit = True
    except Exception:  # noqa: BLE001
        _pg = None
    return _pg


def _pg_get():
    global _pg
    if _pg is None:
        _connect()
    if _pg is not None:
        try:
            _pg.cursor().execute("SELECT 1")
        except Exception:  # noqa: BLE001
            _connect()
    return _pg


def ensure_schema() -> None:
    """Crée la table d'historique si besoin (idempotent)."""
    pg = _pg_get()
    if pg is None:
        log.info("notifications : Postgres indisponible, historique désactivé")
        return
    try:
        cur = pg.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id        bigserial PRIMARY KEY,
                ts        bigint NOT NULL,
                chat_id   bigint,
                topic     text,
                title     text,
                body      text,
                dedup_key text,
                channels  text[],
                delivered boolean DEFAULT true
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS notifications_ts_idx ON notifications (ts DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS notifications_dedup_idx "
            "ON notifications (dedup_key, ts DESC)"
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("schéma notifications : %s", exc)


# --------------------------------------------------------------- préférences
def _pref(chat_id: int | None, key: str, default: str = "on") -> str:
    if chat_id is None:
        return default
    pg = _pg_get()
    if pg is None:
        return default
    try:
        cur = pg.cursor()
        cur.execute(
            "SELECT value FROM preferences WHERE chat_id = %s AND key = %s",
            (chat_id, key),
        )
        row = cur.fetchone()
        return (row[0] if row else default) or default
    except Exception:  # noqa: BLE001
        return default


def push_enabled(chat_id: int | None) -> bool:
    return _pref(chat_id, "notify.push", "on") != "off"


def telegram_enabled(chat_id: int | None) -> bool:
    return _pref(chat_id, "notify.telegram", "on") != "off"


def set_preference(chat_id: int, key: str, value: str) -> None:
    pg = _pg_get()
    if pg is None:
        return
    try:
        cur = pg.cursor()
        cur.execute(
            "INSERT INTO preferences (chat_id, key, value, ts) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (chat_id, key) DO UPDATE SET value = EXCLUDED.value, ts = EXCLUDED.ts",
            (chat_id, key, value, int(time.time())),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("préférence notify : %s", exc)


# --------------------------------------------------------------- heures calmes
def in_quiet_hours(now: time.struct_time | None = None) -> bool:
    if QUIET_START == QUIET_END:
        return False
    h = (now or time.localtime()).tm_hour
    if QUIET_START < QUIET_END:
        return QUIET_START <= h < QUIET_END
    # plage qui traverse minuit (ex. 23 -> 7)
    return h >= QUIET_START or h < QUIET_END


# --------------------------------------------------------------- dédup
def _seen_recently(dedup_key: str, window: int) -> bool:
    pg = _pg_get()
    if pg is None or not dedup_key:
        return False
    try:
        cur = pg.cursor()
        cur.execute(
            "SELECT 1 FROM notifications WHERE dedup_key = %s AND ts > %s LIMIT 1",
            (dedup_key, int(time.time()) - window),
        )
        return cur.fetchone() is not None
    except Exception:  # noqa: BLE001
        return False


def _record(chat_id, topic, title, body, dedup_key, channels, delivered) -> int | None:
    """Enregistre une notification dans l'historique. Retourne son id."""
    pg = _pg_get()
    if pg is None:
        return None
    try:
        cur = pg.cursor()
        cur.execute(
            "INSERT INTO notifications (ts, chat_id, topic, title, body, dedup_key, channels, delivered) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (int(time.time()), chat_id, topic, title, body, dedup_key, channels, delivered),
        )
        row = cur.fetchone()
        return row[0] if row else None
    except Exception as exc:  # noqa: BLE001
        log.warning("enregistrement notification : %s", exc)
        return None


def _update_record(nid: int, channels, delivered) -> None:
    pg = _pg_get()
    if pg is None or nid is None:
        return
    try:
        _pg.cursor().execute(
            "UPDATE notifications SET channels = %s, delivered = %s WHERE id = %s",
            (channels, delivered, nid),
        )
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------- push
def _subs() -> list[dict]:
    try:
        data = json.loads(PUSH_FILE.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_subs(subs: list[dict]) -> None:
    try:
        PUSH_FILE.write_text(json.dumps(subs))
    except Exception:
        # Le dashboard (root) possède parfois le fichier : on n'insiste pas.
        pass


def _vapid():
    """Objet Vapid signataire (chargé une fois)."""
    global _vapid_obj
    if _vapid_obj is None:
        from py_vapid import Vapid01  # noqa: PLC0415

        _vapid_obj = Vapid01.from_pem(VAPID_PEM.read_bytes())
    return _vapid_obj


def send_push(title: str, body: str, url: str = "./") -> int:
    """Envoie à tous les abonnés ; retire ceux qui sont réellement morts. 0 si aucun."""
    subs = _subs()
    if not subs or not VAPID_PEM.exists():
        return 0
    try:
        from pywebpush import webpush, WebPushException  # noqa: PLC0415
    except Exception:
        log.warning("pywebpush absent : push désactivé")
        return 0
    try:
        vapid = _vapid()
    except Exception as exc:  # noqa: BLE001
        log.warning("clé VAPID illisible : %s", exc)
        return 0
    payload = json.dumps({"title": title, "body": body, "url": url})
    sent, alive = 0, []
    for s in subs:
        try:
            webpush(
                subscription_info=s,
                data=payload,
                vapid_private_key=vapid,
                vapid_claims={"sub": _VAPID_SUB},
                ttl=86400,  # FCM garde le message 24 h si l'appareil dort
                headers={"Urgency": "high"},  # réveille l'appareil
                timeout=15,
            )
            sent += 1
            alive.append(s)
        except WebPushException as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            # 404/410 = abonnement expiré (définitif). Le reste = transitoire :
            # on garde l'abonné et on retentera.
            if code in (404, 410):
                log.info("abonnement push expiré (retiré): %s", code)
            else:
                log.warning("push échoué (code %s): %s", code, str(exc)[:200])
                alive.append(s)
        except Exception as exc:  # noqa: BLE001
            log.warning("push erreur inattendue : %s", str(exc)[:200])
            alive.append(s)
    if len(alive) != len(subs):
        _write_subs(alive)
    return sent


# --------------------------------------------------------------- API publique
def notify(
    title: str,
    body: str,
    *,
    chat_id: int | None = None,
    topic: str = "",
    url: str = "./",
    dedup_key: str | None = None,
    force: bool = False,
) -> dict:
    """Notifie Raphaël par Web Push, en respectant préférences, heures calmes
    et dédoublonnage. Retourne ce qui a été décidé (pour les logs/tests).

    Le canal Telegram reste géré par l'appelant (déjà en place) : ici on
    n'ajoute que le push et on trace l'historique.
    """
    result = {"push": 0, "skipped": None, "id": None}

    if dedup_key and _seen_recently(dedup_key, DEDUP_WINDOW) and not force:
        result["skipped"] = "dedup"
        return result

    if not force and in_quiet_hours():
        result["skipped"] = "quiet"
        result["id"] = _record(chat_id, topic, title, body, dedup_key, [], delivered=False)
        return result

    if not push_enabled(chat_id):
        result["skipped"] = "pref"
        return result

    # On enregistre d'abord pour obtenir l'id, puis on l'inclut dans le lien :
    # un clic sur la notif ouvrira le détail dans le dashboard.
    nid = _record(chat_id, topic, title, body, dedup_key, [], delivered=False)
    result["id"] = nid
    link = f"./?notif={nid}" if nid else url
    n = send_push(title, body, link)
    result["push"] = n
    _update_record(nid, ["push"] if n else [], bool(n))
    return result


def recent(limit: int = 30) -> list[dict]:
    """Historique récent des notifications (pour le dashboard)."""
    pg = _pg_get()
    if pg is None:
        return []
    try:
        cur = pg.cursor()
        cur.execute(
            "SELECT ts, topic, title, body, channels, delivered "
            "FROM notifications ORDER BY ts DESC LIMIT %s",
            (limit,),
        )
        return [
            {
                "ts": t, "topic": topic, "title": title, "body": body,
                "channels": ch or [], "delivered": d,
            }
            for t, topic, title, body, ch, d in cur.fetchall()
        ]
    except Exception:  # noqa: BLE001
        return []
