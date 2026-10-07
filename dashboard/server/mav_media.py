"""Files: the media archive, assets and downloads (with the sensitive-file
rules), charts, and Web Push.

Part of the web app server (see mav_api.py).
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import mav_core


# PERSISTENT media folder (survives reboots, unlike /tmp) + JSON index.
# Used to: (1) archive received attachments, (2) keep generated images,
# (3) let Mav resend any file by its id.
MEDIA_DIR = Path(os.environ.get("MAV_MEDIA", mav_core.BOT_DIR / "mav-media"))


MEDIA_INDEX = MEDIA_DIR / "index.json"


def _files_dir() -> Path:
    """Where the helpers write the files they hand you ([[file:name]]).

    The engine runs in ~/workspace, so the folder sits there: the helpers can
    write `mav-files/<name>` and nothing else (see agents/*.md).
    """
    if os.environ.get("MAV_FILES"):
        return Path(os.environ["MAV_FILES"])
    home = os.environ.get("MAV_USER_HOME") or os.environ.get("BOT_HOME")
    if home:
        return Path(home) / "workspace" / "mav-files"
    return mav_core.BOT_DIR / "mav-files"


FILES_DIR = _files_dir()


def _media_load() -> list:
    try:
        data = json.loads(MEDIA_INDEX.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _media_save(items: list) -> None:
    try:
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = MEDIA_INDEX.with_suffix(".tmp")
        tmp.write_text(json.dumps(items[-500:], ensure_ascii=False, indent=1))
        tmp.replace(MEDIA_INDEX)
    except Exception:
        pass


def archive_media(src: Path, name: str, mime: str, source: str = "", size: int = 0, mtime: int = 0) -> dict | None:
    """Copy a file into the persistent media folder and index it."""
    try:
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", name or "fichier")[:120] or "fichier"
        media_id = f"{int(time.time() * 1000)}-{safe}"
        dest = MEDIA_DIR / media_id
        if Path(src).resolve() != dest.resolve():
            dest.write_bytes(Path(src).read_bytes())
        try:
            st = Path(src).stat()
            size = size or st.st_size
            mtime = mtime or int(st.st_mtime)
        except Exception:
            pass
        entry = {
            "id": media_id,
            "name": safe,
            "mime": mime,
            "source": source,
            "ts": int(time.time()),
            "size": size,
            "mtime": mtime,
            "path": str(dest),
        }
        items = _media_load()
        items = [i for i in items if i.get("id") != media_id]
        items.append(entry)
        _media_save(items)
        return entry
    except Exception:
        return None


def list_media(limit: int = 60) -> dict:
    items = _media_load()
    items.sort(key=lambda x: x.get("ts", 0), reverse=True)
    return {"media": items[:limit]}


def find_media(query: str) -> list:
    """Find media by name (case-insensitive)."""
    q = (query or "").strip().lower()
    if not q:
        return []
    items = _media_load()
    hits = [i for i in items if q in str(i.get("name", "")).lower()]
    hits.sort(key=lambda x: x.get("ts", 0), reverse=True)
    return hits


def sync_files_dir() -> int:
    """Archive the files the helpers wrote in FILES_DIR (any safe type), so a
    shared file stays downloadable even after the folder is cleaned."""
    if not FILES_DIR.is_dir():
        return 0
    items = _media_load()
    known = {(i.get("name"), i.get("size"), i.get("mtime")) for i in items}
    added = 0
    try:
        for f in sorted(FILES_DIR.iterdir()):
            if not f.is_file() or is_sensitive(f):
                continue
            st = f.stat()
            safe = re.sub(r"[^A-Za-z0-9._-]", "_", f.name)[:120]
            if (safe, st.st_size, int(st.st_mtime)) in known:
                continue
            mime = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            if archive_media(f, f.name, mime, "mav", size=st.st_size, mtime=int(st.st_mtime)):
                known.add((safe, st.st_size, int(st.st_mtime)))
                added += 1
    except Exception:
        pass
    return added


def sync_media_dir() -> int:
    """Archive images present in /tmp/mav-dashboard that are not archived
    yet. Called before displaying media, so any generated image
    (Puppeteer screenshot, chart…) is persisted automatically."""
    sync_files_dir()
    src_dir = Path("/tmp/mav-dashboard")
    if not src_dir.is_dir():
        return 0
    # Dedup by (name, size, mtime): the same file is archived only
    # once, even if its name stays identical across generations.
    items = _media_load()
    known = {(i.get("name"), i.get("size"), i.get("mtime")) for i in items}
    added = 0
    try:
        for f in src_dir.iterdir():
            if not f.is_file() or f.suffix.lower() not in ASSET_EXT:
                continue
            try:
                st = f.stat()
            except Exception:
                continue
            key = (f.name, st.st_size, int(st.st_mtime))
            if key in known:
                continue
            if archive_media(f, f.name, mimetypes.guess_type(f.name)[0] or "image/png", "generated", size=st.st_size, mtime=int(st.st_mtime)):
                known.add(key)
                added += 1
    except Exception:
        pass
    return added


# Lets Mav send images in the chat. We serve an image file
# local via /api/asset?path=..., en n'autorisant que des images et une liste
# de racines, pour ne jamais exposer un fichier arbitraire.
ASSET_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".avif"}


def _asset_roots() -> list[Path]:
    roots = [FILES_DIR, MEDIA_DIR, mav_core.ATTACH_DIR, Path("/tmp/mav-dashboard"), Path("/tmp/opencode")]
    if mav_core.BOT_DIR.exists():
        roots.append(Path(mav_core.BOT_DIR).resolve())
    # Optional roots, specific to the user's installation.
    for env in ("MAV_USER_HOME", "BOT_HOME"):
        home = os.environ.get(env)
        if home and Path(home).is_dir():
            roots += [Path(home) / "workspace", Path(home) / "Downloads"]
    return roots


ASSET_ROOTS = _asset_roots()


def serve_asset(path: str):
    """Return (bytes, mime) if the path is an allowed image, else None."""
    if not path:
        return None
    raw = urllib.parse.unquote(str(path))
    if raw.startswith("file://"):
        raw = raw[len("file://"):]
    try:
        p = Path(raw).resolve()
    except Exception:
        return None
    if p.suffix.lower() not in ASSET_EXT or not p.is_file():
        return None
    allowed = False
    for root in ASSET_ROOTS:
        try:
            if str(p).startswith(str(Path(root).resolve())):
                allowed = True
                break
        except Exception:
            continue
    if not allowed:
        return None
    try:
        data = p.read_bytes()
    except Exception:
        return None
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return data, mime


_YAHOO_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


_CHART_TTL = 120.0


_chart_cache: dict = {}


def _yahoo_closes(symbol: str, rng: str):
    """Return (closes, meta) for a symbol/range from Yahoo, or raise."""
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + urllib.parse.quote(symbol)
        + "?interval=1d&range=" + urllib.parse.quote(rng)
    )
    req = urllib.request.Request(
        url, headers={"User-Agent": _YAHOO_UA, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        payload = json.load(r)
    res = (payload.get("chart") or {}).get("result") or []
    if not res:
        raise ValueError("no data")
    meta = res[0].get("meta") or {}
    quotes = ((res[0].get("indicators") or {}).get("quote") or [{}])[0]
    closes = [
        float(c)
        for c in (quotes.get("close") or [])
        if isinstance(c, (int, float))
    ]
    if not closes:
        raise ValueError("no close")
    return closes, meta


def chart_data(symbol: str, rng: str = "1mo") -> dict:
    """Chart payload for the dashboard: name, price, variation and a series."""
    symbol = (symbol or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9.^=_:-]{1,24}", symbol):
        raise ValueError("bad symbol")
    valid = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"}
    if rng not in valid:
        rng = "1mo"
    ck = (symbol, rng)
    now = time.time()
    hit = _chart_cache.get(ck)
    if hit and now - hit[0] < _CHART_TTL:
        return hit[1]
    closes, meta = _yahoo_closes(symbol, rng)
    first, last = closes[0], closes[-1]
    prev = closes[-2] if len(closes) > 1 else first
    pct = (last - first) / first * 100 if first else 0.0
    day = (last - prev) / prev * 100 if prev else 0.0
    out = {
        "symbol": symbol,
        "name": meta.get("shortName") or meta.get("symbol") or symbol,
        "currency": meta.get("currency") or "",
        "price": last,
        "prev": prev,
        "change_pct": day,
        "range_pct": pct,
        "series": closes,
    }
    _chart_cache[ck] = (now, out)
    return out


# Downloadable documents, code and archives. Only these extensions are
# served, and only from the same roots as the image asset route.
# Mime hints purely to serve a good Content-Type. Any other extension still
# downloads (application/octet-stream): the gate is the *denylist* below, not
# this map.
DOWNLOAD_EXT = {
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".json": "application/json",
    ".html": "text/html; charset=utf-8",
    ".xml": "application/xml",
    ".yaml": "text/yaml; charset=utf-8",
    ".yml": "text/yaml; charset=utf-8",
    ".py": "text/x-python; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".ts": "text/typescript; charset=utf-8",
    ".sh": "text/x-shellscript; charset=utf-8",
    ".sql": "application/sql",
    ".log": "text/plain; charset=utf-8",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".zip": "application/zip",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


# Sensitive files: never downloadable, whatever the extension. The point is to
# let Mav hand you *any* file it produced (any type), while keeping secrets
# (env files, keys, credentials, mail config…) out of reach.
SENSITIVE_NAMES = {
    ".netrc", ".git-credentials", ".npmrc", ".pypirc", ".htpasswd", ".pgpass",
    "mail.conf", "mav.env", "mav-dashboard.env", "mav-server.env",
    "push_subs.json", "auth.json", "credentials.json",
    # SSH private keys (their .pub halves are fine)
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "id_ecdsa_sk", "id_ed25519_sk",
}


SENSITIVE_EXTS = {
    ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".ppk",
    ".asc", ".gpg", ".kdbx", ".env",
}


SENSITIVE_WORDS = ("secret", "credential", "password", "passwd", "token", "apikey", "api_key")


def is_sensitive(p: "Path") -> bool:
    """True for files that must never be served (env, keys, credentials…)."""
    name = p.name.lower()
    if name in SENSITIVE_NAMES:
        return True
    # .env and friends: ".env", ".env.local", "prod.env"…
    if name == ".env" or name.endswith(".env") or name.startswith(".env."):
        return True
    if p.suffix.lower() in SENSITIVE_EXTS:
        return True
    if any(w in name for w in SENSITIVE_WORDS):
        return True
    # A dotfile is private by convention: do not serve it unless it is a
    # harmless, explicitly wanted type (e.g. a generated .md/.csv).
    if name.startswith(".") and p.suffix.lower() not in (".md", ".txt", ".csv", ".json", ".html", ".svg"):
        return True
    return False


def resolve_download(name: str) -> "Path | None":
    """Resolve a downloadable file of *any* type, except sensitive ones.

    An absolute path is used as-is (within an allowed root); a bare name is
    searched in the media archive, the attachments folder and the allowed
    roots so `[[file:rapport.xlsx]]` works right after a file was produced.
    """
    name = urllib.parse.unquote(str(name or "")).strip()
    if not name:
        return None
    if name.startswith("file://"):
        name = name[len("file://"):]
    roots = _asset_roots()

    def allowed(p: Path) -> bool:
        if not p.is_file():
            return False
        if is_sensitive(p):
            return False
        try:
            rp = str(p.resolve())
        except Exception:
            return False
        return any(rp.startswith(str(Path(r).resolve())) for r in roots)

    p = Path(name)
    if p.is_absolute():
        try:
            return p.resolve() if allowed(p) else None
        except Exception:
            return None
    # Bare filename: look in the usual output folders first, then anywhere.
    search_dirs = [FILES_DIR, MEDIA_DIR, mav_core.ATTACH_DIR, Path("/tmp/mav-dashboard"), Path("/tmp/opencode")]
    for d in search_dirs:
        cand = d / name
        if allowed(cand):
            return cand.resolve()
    # A file Mav shared earlier and that was since removed from its folder:
    # serve the archived copy (the newest one with that name).
    base = Path(name).name
    for item in sorted(_media_load(), key=lambda x: x.get("ts", 0), reverse=True):
        if item.get("name") == re.sub(r"[^A-Za-z0-9._-]", "_", base) and item.get("path"):
            cand = Path(item["path"])
            if allowed(cand):
                return cand.resolve()
    for r in roots:
        cand = Path(r) / name
        if allowed(cand):
            return cand.resolve()
    try:
        for r in roots:
            for found in Path(r).rglob(name):
                if allowed(found):
                    return found.resolve()
    except Exception:
        pass
    return None


def download_response(path_str: str):
    """Return (bytes, mime, filename) for a downloadable file, or None."""
    p = resolve_download(path_str)
    if p is None:
        return None
    try:
        data = p.read_bytes()
    except Exception:
        return None
    mime = DOWNLOAD_EXT.get(p.suffix.lower()) or mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return data, mime, p.name


# The engine refuses application/octet-stream: guess a useful type from
# the extension, for cases where the browser announces nothing (local files).
_EXT_MIME = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".html": "text/html",
    ".xml": "text/xml",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".py": "text/x-python",
    ".js": "text/javascript",
    ".ts": "text/typescript",
    ".sh": "text/x-shellscript",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _mime_from_ext(name: str) -> str:
    return _EXT_MIME.get(Path(name).suffix.lower(), "text/plain")


def _guess_file(item: dict) -> dict:
    """Fill in an attachment (mime/name) from its local URL."""
    url = item.get("url") or ""
    path = url[len("file://"):] if url.startswith("file://") else url
    name = item.get("filename") or Path(path).name
    mime = item.get("mime") or ""
    if not mime or mime == "application/octet-stream":
        mime = mimetypes.guess_type(name)[0] or _mime_from_ext(name)
        if mime == "application/octet-stream":
            mime = _mime_from_ext(name)
    return {"url": url, "mime": mime, "filename": name}


_vapid_lock = threading.Lock()


def _vapid_keys() -> tuple[str, str]:
    """Return (private_key_pem, public_key_b64url). Create them on demand."""
    key_file = mav_core.BOT_DIR / "vapid_private.pem"
    pub_file = mav_core.BOT_DIR / "vapid_public.txt"
    if key_file.exists() and pub_file.exists():
        return key_file.read_text(), pub_file.read_text().strip()
    with _vapid_lock:
        if key_file.exists() and pub_file.exists():
            return key_file.read_text(), pub_file.read_text().strip()
        from cryptography.hazmat.primitives import serialization
        from py_vapid import Vapid01

        v = Vapid01()
        v.generate_keys()
        pem = v.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        raw = v.public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        pub = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        key_file.write_text(pem)
        key_file.chmod(0o600)
        pub_file.write_text(pub)
        return pem, pub


def push_public_key() -> str:
    return _vapid_keys()[1]


def push_subscribe(sub: dict) -> bool:
    subs = mav_core.read_json(mav_core.PUSH_FILE, [])
    if not isinstance(subs, list):
        subs = []
    endpoint = sub.get("endpoint")
    if not endpoint:
        return False
    subs = [s for s in subs if s.get("endpoint") != endpoint]
    subs.append(sub)
    mav_core.write_json(mav_core.PUSH_FILE, subs)
    return True


def push_unsubscribe(endpoint: str) -> bool:
    subs = mav_core.read_json(mav_core.PUSH_FILE, [])
    subs = [s for s in subs if s.get("endpoint") != endpoint]
    mav_core.write_json(mav_core.PUSH_FILE, subs)
    return True


def send_push(title: str, body: str, url: str = "./") -> int:
    try:
        from py_vapid import Vapid01
        from pywebpush import webpush, WebPushException
    except Exception:
        return 0
    if not mav_core.PUSH_FILE.exists():
        return 0
    try:
        pem, _ = _vapid_keys()
        vapid = Vapid01.from_pem(pem.encode())
    except Exception:
        return 0
    subs = mav_core.read_json(mav_core.PUSH_FILE, [])
    sent = 0
    alive = []
    payload = json.dumps({"title": title, "body": body, "url": url})
    for s in subs:
        try:
            webpush(
                subscription_info=s,
                data=payload,
                vapid_private_key=vapid,
                vapid_claims={"sub": os.environ.get("MAV_VAPID_SUB") or "mailto:admin@localhost"},
                ttl=86400,
                headers={"Urgency": "high"},
                timeout=15,
            )
            sent += 1
            alive.append(s)
        except WebPushException as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            if code in (404, 410):
                pass  # subscription permanently expired: drop it
            else:
                alive.append(s)  # transient error: keep the subscriber
        except Exception:
            alive.append(s)
    mav_core.write_json(mav_core.PUSH_FILE, alive)
    return sent


__all__ = ['ASSET_EXT', 'ASSET_ROOTS', 'DOWNLOAD_EXT', 'FILES_DIR', 'MEDIA_DIR', 'MEDIA_INDEX', 'SENSITIVE_EXTS', 'SENSITIVE_NAMES', 'SENSITIVE_WORDS', '_CHART_TTL', '_EXT_MIME', '_YAHOO_UA', '_asset_roots', '_chart_cache', '_files_dir', '_guess_file', '_media_load', '_media_save', '_mime_from_ext', '_vapid_keys', '_vapid_lock', '_yahoo_closes', 'archive_media', 'chart_data', 'download_response', 'find_media', 'is_sensitive', 'list_media', 'push_public_key', 'push_subscribe', 'push_unsubscribe', 'resolve_download', 'send_push', 'serve_asset', 'sync_files_dir', 'sync_media_dir']
