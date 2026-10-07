"""Notification channels next to Web Push: ntfy, Gotify, Discord and Slack.

The web app edits the list (Settings → General), the worker reads it when it
notifies. It lives in ``BOT_DIR/channels.json`` (0600: it holds tokens and
webhook URLs)::

    {"public_url": "https://mav.example.org",
     "channels": [{"id": "c1a2b3", "type": "ntfy", "name": "Phone",
                   "enabled": true, "server": "https://ntfy.sh", "topic": "…",
                   "token": ""}]}

``payload()`` is pure (what to POST where), ``send()`` does the request,
``deliver()`` fans a notification out to the chosen channels. Nothing here
raises: a broken channel is logged and reported, never fatal.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger("occhannels")

BOT_DIR = Path(os.environ.get("BOT_DIR", Path(__file__).resolve().parent))
CHANNELS_FILE = Path(os.environ.get("MAV_CHANNELS_FILE", BOT_DIR / "channels.json"))
TIMEOUT = 10

TYPES = {
    "ntfy": {"label": "ntfy", "fields": ["server", "topic", "token"], "secrets": ["token"]},
    "gotify": {"label": "Gotify", "fields": ["server", "token"], "secrets": ["token"]},
    "discord": {"label": "Discord", "fields": ["webhook"], "secrets": ["webhook"]},
    "slack": {"label": "Slack", "fields": ["webhook"], "secrets": ["webhook"]},
}

# level → (ntfy 1..5, Gotify 0..10, Discord embed colour)
PRIORITY = {
    "critical": (5, 8, 0xC2412D),
    "important": (4, 6, 0xE8962E),
    "useful": (3, 4, 0x0F7A5C),
    "fyi": (2, 2, 0x8A9099),
}

_TOPIC = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_DISCORD = re.compile(r"^https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+$")
_SLACK = re.compile(r"^https://hooks\.slack\.com/services/[\w/]+$")
MASK = "••••"


# ------------------------------------------------------------------ storage
def load() -> dict:
    try:
        data = json.loads(CHANNELS_FILE.read_text())
    except Exception:  # noqa: BLE001
        data = {}
    chans = data.get("channels") if isinstance(data, dict) else None
    return {
        "public_url": str((data or {}).get("public_url") or "") if isinstance(data, dict) else "",
        "channels": [c for c in (chans or []) if isinstance(c, dict) and c.get("type") in TYPES],
    }


def _save(data: dict) -> None:
    CHANNELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CHANNELS_FILE.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, CHANNELS_FILE)


def _mask(value: str) -> str:
    return (MASK + value[-4:]) if value else ""


def public_view() -> dict:
    """The list for the web app: secrets masked, never sent back in clear."""
    data = load()
    out = []
    for c in data["channels"]:
        v = {k: c.get(k) for k in ("id", "type", "name", "enabled")}
        for f in TYPES[c["type"]]["fields"]:
            val = str(c.get(f) or "")
            v[f] = _mask(val) if f in TYPES[c["type"]]["secrets"] else val
        out.append(v)
    return {
        "public_url": data["public_url"],
        "channels": out,
        "types": {k: {"label": t["label"], "fields": t["fields"]} for k, t in TYPES.items()},
    }


def _http_url(value: str) -> str | None:
    u = urllib.parse.urlparse(value.strip())
    if u.scheme not in ("http", "https") or not u.netloc or u.username or u.password:
        return None
    return value.strip().rstrip("/")


def validate(c: dict) -> str | None:
    """None when the channel can be saved, otherwise a short reason."""
    t = c.get("type")
    if t not in TYPES:
        return "Unknown channel type."
    if t in ("ntfy", "gotify") and not _http_url(str(c.get("server") or "")):
        return "Enter the server address, e.g. https://ntfy.sh."
    if t == "ntfy" and not _TOPIC.match(str(c.get("topic") or "")):
        return "The topic can use letters, digits, - and _ (64 at most)."
    if t == "gotify" and not str(c.get("token") or "").strip():
        return "Paste the application token from Gotify."
    if t == "discord" and not _DISCORD.match(str(c.get("webhook") or "").strip()):
        return "Paste a Discord webhook URL (https://discord.com/api/webhooks/…)."
    if t == "slack" and not _SLACK.match(str(c.get("webhook") or "").strip()):
        return "Paste a Slack webhook URL (https://hooks.slack.com/services/…)."
    return None


def upsert(payload: dict) -> dict:
    """Add or update one channel. A masked secret keeps the stored one."""
    data = load()
    cid = str(payload.get("id") or "")
    old = next((c for c in data["channels"] if c.get("id") == cid), None) if cid else None
    t = payload.get("type") or (old or {}).get("type")
    if t not in TYPES:
        return {"ok": False, "error": "Unknown channel type."}
    ch = {"id": cid or secrets.token_hex(3), "type": t,
          "name": str(payload.get("name") or TYPES[t]["label"]).strip()[:40],
          "enabled": bool(payload.get("enabled", True))}
    for f in TYPES[t]["fields"]:
        val = str(payload.get(f) if payload.get(f) is not None else "").strip()
        if f in TYPES[t]["secrets"] and old and (not val or val.startswith(MASK)):
            val = str(old.get(f) or "")
        if f == "server" and val:
            val = _http_url(val) or val
        ch[f] = val
    err = validate(ch)
    if err:
        return {"ok": False, "error": err}
    data["channels"] = [ch if c is old else c for c in data["channels"]] if old else data["channels"] + [ch]
    if "public_url" in payload:
        pu = str(payload.get("public_url") or "").strip()
        data["public_url"] = (_http_url(pu) or "") if pu else ""
    _save(data)
    return {"ok": True, "id": ch["id"]}


def set_public_url(url: str) -> dict:
    data = load()
    pu = _http_url(url) if url.strip() else ""
    if pu is None:
        return {"ok": False, "error": "Use an http(s) address."}
    data["public_url"] = pu
    _save(data)
    return {"ok": True}


def remove(cid: str) -> dict:
    data = load()
    keep = [c for c in data["channels"] if c.get("id") != cid]
    if len(keep) == len(data["channels"]):
        return {"ok": False, "error": "No such channel."}
    data["channels"] = keep
    _save(data)
    return {"ok": True}


# ------------------------------------------------------------------ delivery
def absolute(link: str, public_url: str) -> str:
    """'./#chat/x' → 'https://host/#chat/x' when the public address is known."""
    if not link or link.startswith(("http://", "https://")):
        return link or public_url
    if not public_url:
        return ""
    return public_url.rstrip("/") + "/" + link.lstrip("./")


def payload(c: dict, title: str, body: str, url: str = "", level: str = "useful"):
    """(endpoint, headers, json body) for one channel. Pure, for tests."""
    p_ntfy, p_gotify, colour = PRIORITY.get(level, PRIORITY["useful"])
    t = c["type"]
    headers = {"Content-Type": "application/json", "User-Agent": "Mav"}
    if t == "ntfy":
        msg = {"topic": c["topic"], "title": title[:250], "message": body[:4000] or title,
               "priority": p_ntfy, "tags": ["mav"]}
        if url:
            msg["click"] = url
        if c.get("token"):
            headers["Authorization"] = f"Bearer {c['token']}"
        return c["server"].rstrip("/") + "/", headers, msg
    if t == "gotify":
        msg = {"title": title[:250], "message": body[:4000] or title, "priority": p_gotify}
        if url:
            msg["extras"] = {"client::notification": {"click": {"url": url}}}
        headers["X-Gotify-Key"] = c["token"]
        return c["server"].rstrip("/") + "/message", headers, msg
    if t == "discord":
        embed = {"title": title[:256], "description": body[:4000], "color": colour}
        if url:
            embed["url"] = url
        return c["webhook"], headers, {"username": "Mav", "embeds": [embed],
                                       "allowed_mentions": {"parse": []}}
    if t == "slack":
        text = f"*{title}*\n{body}"[:3000]
        if url:
            text += f"\n<{url}|Open in Mav>"
        return c["webhook"], headers, {"text": text}
    raise ValueError(t)


def send(c: dict, title: str, body: str, url: str = "", level: str = "useful") -> tuple[bool, str]:
    try:
        endpoint, headers, msg = payload(c, title, body, url, level)
        req = urllib.request.Request(endpoint, data=json.dumps(msg).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 (validated http/https)
            return 200 <= r.status < 300, f"HTTP {r.status}"
    except urllib.error.HTTPError as exc:
        return False, f"The server answered HTTP {exc.code}."
    except urllib.error.URLError as exc:
        return False, f"Can't reach the server ({getattr(exc.reason, 'strerror', None) or exc.reason})."
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:120]


def deliver(title: str, body: str, link: str = "", level: str = "useful",
            only: list[str] | None = None) -> list[str]:
    """Send to every enabled channel (or only those ids). Returns the ids reached."""
    data = load()
    url = absolute(link, data["public_url"])
    reached = []
    for c in data["channels"]:
        if not c.get("enabled", True) or (only is not None and c.get("id") not in only):
            continue
        ok, why = send(c, title, body, url, level)
        if ok:
            reached.append(c["id"])
        else:
            log.warning("channel %s (%s) failed: %s", c.get("name"), c.get("type"), why)
    return reached


def test(cid: str) -> dict:
    data = load()
    c = next((c for c in data["channels"] if c.get("id") == cid), None)
    if not c:
        return {"ok": False, "error": "No such channel."}
    ok, why = send(c, "Mav", "This is a test notification.", data["public_url"], "important")
    return {"ok": ok, "detail": why} if ok else {"ok": False, "error": why}
