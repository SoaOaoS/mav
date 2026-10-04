#!/usr/bin/env python3
"""mav_api — backend of the Mav dashboard.

Small HTTP server (stdlib) that exposes the agent's state (jobs, Postgres
memory, watch, agents, health, metrics), lets you configure the model
provider, agents and MCP servers, and runs the chat through dashboard-owned
opencode sessions with SSE streaming.

No authentication: meant for a private host, reachable over VPN.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ------------------------------------------------------------------- config

PORT = int(os.environ.get("MAV_API_PORT", "8787"))
BIND = os.environ.get("MAV_API_BIND", "0.0.0.0")
TLS_PORT = int(os.environ.get("MAV_TLS_PORT", "0") or 0)
TLS_CERT = os.environ.get("MAV_TLS_CERT", "")
TLS_KEY = os.environ.get("MAV_TLS_KEY", "")

BOT_DIR = Path(os.environ.get("BOT_DIR", Path.home() / "bot"))
JOBS_FILE = BOT_DIR / "jobs.json"
JOBS_STATE = BOT_DIR / "jobs_state.json"
MEMORY_FILE = BOT_DIR / "memory.json"
STATIC_DIR = Path(os.environ.get("MAV_STATIC", Path(__file__).resolve().parent.parent))
ATTACH_DIR = Path(os.environ.get("MAV_ATTACH", "/tmp/mav-dashboard/attachments"))
PUSH_FILE = Path(os.environ.get("MAV_PUSH_FILE", BOT_DIR / "push_subs.json"))

OPENCODE_URL = os.environ.get("OPENCODE_URL", "http://127.0.0.1:4096").rstrip("/")
PG_DSN = os.environ.get(
    "PG_DSN", "host=127.0.0.1 port=5432 user=mav password=mav_secret dbname=mav"
)
# The helper used when none is picked: the everyday "assistant" (orchestrator).
DEFAULT_AGENT = os.environ.get("MAV_DASH_AGENT", "").strip() or "assistant"
DEFAULT_MODEL = os.environ.get("OPENCODE_MODEL", "").strip()
# Owner id: memory, facts and watch items are attached to it (kept from the
# chat id of older installs, so existing memory stays attached).
DEFAULT_CHAT_ID = int(os.environ.get("MAV_CHAT_ID", "0") or 0)
SESSIONS_META = BOT_DIR / "dash_sessions.json"
ENV_SERVER = Path(os.environ.get("MAV_ENV_SERVER", "/etc/mav-server.env"))
ENV_FILES = [
    Path(os.environ.get("MAV_ENV_BOT", "/etc/mav.env")),
    Path(os.environ.get("MAV_ENV_DASH", "/etc/mav-dashboard.env")),
]
WORKER_UNIT = os.environ.get("MAV_WORKER_UNIT", "mav-worker").strip()
VERSION_FILE = Path(os.environ.get("MAV_VERSION_FILE", "/etc/mav/version"))
MAV_REPO = os.environ.get("MAV_REPO", "SoaOaoS/mav").strip()
INSTALL_LOG = Path(os.environ.get("MAV_INSTALL_LOG", "/var/log/mav-install.log"))
MAV_CLI = os.environ.get("MAV_CLI", "/usr/local/bin/mav")
CATALOG_FILE = STATIC_DIR / "mcp-catalog.json"

# Shared modules live in the worker's folder (memory, RAG): make them importable
# both from an install (BOT_DIR) and from a checkout (../../bot).
for _p in (BOT_DIR, Path(__file__).resolve().parents[2] / "bot"):
    if (_p / "ocmemory.py").is_file() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
try:
    from ocmemory import Memory  # noqa: E402

    MEMORY = Memory(BOT_DIR / "memory.json", dsn=PG_DSN)
except Exception:  # noqa: BLE001
    MEMORY = None
try:
    from ocrag import RAG  # noqa: E402

    _RAG = None
except Exception:  # noqa: BLE001
    RAG = None
    _RAG = None
MEMORY_ENABLED = os.environ.get("MEMORY", "1") == "1"
MEMORY_TOP = int(os.environ.get("MEMORY_TOP", "3") or 3)

import mav_provider  # noqa: E402

# Agents offered in the dashboard selector.
# Everyday helpers shipped with Mav, in the order they are offered.
PRIMARY_AGENTS = ["assistant", "researcher", "writer", "planner", "money"]

# ------------------------------------------------------------------- helpers


def _json_default(o):
    return str(o)


def http_json(url: str, method: str = "GET", body=None, timeout: float = 8):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
        return json.loads(raw) if raw else None


def pg_query(sql: str, params: tuple = ()) -> list[dict]:
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(PG_DSN, connect_timeout=3)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if cur.description:
                rows = [dict(r) for r in cur.fetchall()]
                conn.commit()
                return rows
            conn.commit()
            return []
    finally:
        conn.close()


def pg_exec(sql: str, params: tuple = ()) -> None:
    import psycopg2

    conn = psycopg2.connect(PG_DSN, connect_timeout=3)
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def read_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def write_json(path: Path, data) -> None:
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    tmp.replace(path)
    # This file may be shared with the bot (running under another account).
    # The dashboard often runs as root: give ownership back so both can write.
    if path.name in ("push_subs.json", "dash_sessions.json", "jobs.json"):
        _chown_user(path)


def sys_metrics() -> dict:
    out: dict = {}
    try:
        fields = open("/proc/stat").readline().split()[1:]
        vals = [int(x) for x in fields]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        out["_cpu"] = (idle, sum(vals))
    except Exception:
        pass
    try:
        mem = {}
        for line in open("/proc/meminfo"):
            k, v = line.split(":", 1)
            mem[k] = int(v.strip().split()[0])
        total = mem.get("MemTotal", 1)
        avail = mem.get("MemAvailable", mem.get("MemFree", 0))
        out["mem_pct"] = round((total - avail) / total * 100)
    except Exception:
        pass
    try:
        u = shutil.disk_usage("/")
        out["disk_pct"] = round(u.used / u.total * 100)
    except Exception:
        pass
    try:
        out["load"] = round(float(open("/proc/loadavg").read().split()[0]), 2)
        out["uptime_s"] = int(float(open("/proc/uptime").read().split()[0]))
    except Exception:
        pass
    return out


_cpu_lock = threading.Lock()
_cpu_prev: tuple | None = None


def cpu_pct() -> int | None:
    global _cpu_prev
    cur = sys_metrics().get("_cpu")
    if not cur:
        return None
    with _cpu_lock:
        prev = _cpu_prev
        _cpu_prev = cur
    if prev is None:
        return None
    idle, total = cur
    pidle, ptotal = prev
    dt, di = total - ptotal, idle - pidle
    if dt <= 0:
        return None
    return round((1 - di / dt) * 100)


# --------------------------------------------------------------- engine config


def _opencode_config_path() -> Path:
    """Localise la config opencode quel que soit l'utilisateur qui lance le service
    (the service may run as root, whose HOME differs)."""
    env = os.environ.get("OPENCODE_CONFIG")
    if env:
        try:
            if Path(env).is_file():
                return Path(env)
        except OSError:
            pass
    home = os.environ.get("MAV_USER_HOME") or os.environ.get("BOT_HOME")
    candidates = []
    if home:
        candidates.append(Path(home) / ".config/opencode/opencode.json")
    candidates += [
        Path.home() / ".config/opencode/opencode.json",
        Path(os.path.expanduser("~")) / ".config/opencode/opencode.json",
    ]
    for c in candidates:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return candidates[0]


# ------------------------------------------------------------------- config
# Everything needed to let the user edit their own agent (AGENTS.md) and MCP
# servers from the dashboard, then restart the engine to apply.

# The systemd unit of the engine (installer default: mav-server; older installs
# may use opencode-server). Configurable, with auto-detection as a fallback.
SERVER_UNIT_EXPLICIT = os.environ.get("MAV_SERVER_UNIT", "").strip()
DEFAULT_SERVER_UNITS = ["mav-server", "opencode-server"]


def _config_dir() -> Path:
    # If OPENCODE_CONFIG points to a file, the config dir is its parent — even
    # if the file does not exist yet.
    env = os.environ.get("OPENCODE_CONFIG")
    if env:
        return Path(env).parent
    return _opencode_config_path().parent


def agents_path() -> Path:
    """Global AGENTS.md read by opencode (same dir as opencode.json)."""
    env = os.environ.get("MAV_AGENTS_MD")
    if env:
        return Path(env)
    return _config_dir() / "AGENTS.md"


def _run(cmd: list[str], timeout: float = 20) -> tuple[int, str]:
    import subprocess  # noqa: PLC0415

    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def server_unit() -> str:
    """Name of the systemd unit running the opencode engine."""
    if SERVER_UNIT_EXPLICIT:
        return SERVER_UNIT_EXPLICIT
    for u in DEFAULT_SERVER_UNITS:
        code, _ = _run(["systemctl", "cat", u], timeout=6)
        if code == 0:
            return u
    return DEFAULT_SERVER_UNITS[0]


def _unit_active(unit: str) -> bool:
    code, out = _run(["systemctl", "is-active", unit], timeout=6)
    return out.strip() == "active"


def engine_status() -> dict:
    """Live status of the agent engine + the services around it."""
    unit = server_unit()
    active = _unit_active(unit)
    health = {}
    try:
        health = http_json(f"{OPENCODE_URL}/global/health", timeout=4) or {}
    except Exception:
        health = {}
    online = bool(health.get("healthy"))
    # How many agents/MCP the engine currently knows about.
    n_agents = len(valid_agents())
    n_mcp = 0
    try:
        names = _engine_mcp_names()
        n_mcp = len(names)
    except Exception:
        n_mcp = 0
    return {
        "unit": unit,
        "active": active,
        "online": online,
        "version": health.get("version"),
        "agents": n_agents,
        "mcp": n_mcp,
        "model": DEFAULT_MODEL or provider_current().get("ref") or "",
        "url": OPENCODE_URL,
        "checked": int(time.time()),
        "pending": pending_changes(),
        "version": installed_version(),
    }


def _engine_mcp_names() -> list[str]:
    try:
        data = http_json(f"{OPENCODE_URL}/mcp", timeout=6)
    except Exception:
        return []
    if isinstance(data, dict):
        return list(data.keys())
    if isinstance(data, list):
        return [d.get("name") for d in data if isinstance(d, dict) and d.get("name")]
    return []


def mcp_status() -> dict:
    """Live connection status per MCP server, straight from the engine."""
    try:
        data = http_json(f"{OPENCODE_URL}/mcp", timeout=6)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _engine_error(detail: str, code: int) -> str:
    """Human message out of an opencode error body (JSON or plain)."""
    try:
        parsed = json.loads(detail)
        if isinstance(parsed, dict):
            msg = parsed.get("message") or parsed.get("error") or parsed.get("data")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()
            if msg is not None:
                return json.dumps(msg)[:300]
    except Exception:
        pass
    detail = (detail or "").strip()
    return detail[:300] if detail else f"engine returned {code}"


def _extract_oauth_code(raw: str) -> str:
    """Accept a bare code, a full callback URL, or a query string."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if "code=" in raw:
        query = urllib.parse.urlparse(raw).query
        if not query and "?" in raw:
            query = raw.split("?", 1)[1]
        if not query:
            query = raw
        vals = urllib.parse.parse_qs(query)
        if vals.get("code"):
            return vals["code"][0].strip()
    return raw


def mcp_oauth_start(name: str) -> dict:
    """Begin the OAuth flow for a remote MCP server; returns the sign-in URL."""
    try:
        data = http_json(
            f"{OPENCODE_URL}/mcp/{urllib.parse.quote(name, safe='')}/auth",
            method="POST",
            timeout=20,
        )
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:
            pass
        return {"ok": False, "error": _engine_error(detail, exc.code)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    if not isinstance(data, dict) or not data.get("authorizationUrl"):
        return {"ok": False, "error": "the engine did not return a sign-in URL"}
    return {
        "ok": True,
        "authorizationUrl": data["authorizationUrl"],
        "oauthState": data.get("oauthState", ""),
    }


def mcp_oauth_callback(name: str, code: str) -> dict:
    """Finish the OAuth flow by handing the engine the authorization code."""
    code = _extract_oauth_code(code)
    if not code:
        return {"ok": False, "error": "paste the code you received"}
    try:
        data = http_json(
            f"{OPENCODE_URL}/mcp/{urllib.parse.quote(name, safe='')}/auth/callback",
            method="POST",
            body={"code": code},
            timeout=30,
        )
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:
            pass
        return {"ok": False, "error": _engine_error(detail, exc.code)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "status": data}


def mcp_oauth_remove(name: str) -> dict:
    """Forget the stored OAuth credentials of an MCP server."""
    try:
        http_json(
            f"{OPENCODE_URL}/mcp/{urllib.parse.quote(name, safe='')}/auth",
            method="DELETE",
            timeout=15,
        )
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:
            pass
        return {"ok": False, "error": _engine_error(detail, exc.code)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    return {"ok": True}



SECRET_HINTS = ("token", "key", "secret", "password", "authorization", "auth")


def _mask_secrets(obj):
    """Recursively mask values whose key looks like a secret, for display."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, str) and any(h in k.lower() for h in SECRET_HINTS):
                out[k] = "••••••••" if v else ""
            else:
                out[k] = _mask_secrets(v)
        return out
    if isinstance(obj, list):
        return [_mask_secrets(x) for x in obj]
    return obj


def _merge_secrets(new_obj, old_obj):
    """Keep the old secret when the client sent the masked placeholder back."""
    if isinstance(new_obj, dict) and isinstance(old_obj, dict):
        out = {}
        for k, v in new_obj.items():
            if (
                isinstance(v, str)
                and v == "••••••••"
                and isinstance(old_obj.get(k), str)
            ):
                out[k] = old_obj[k]
            else:
                out[k] = _merge_secrets(v, old_obj.get(k))
        return out
    if isinstance(new_obj, list) and isinstance(old_obj, list):
        return [
            _merge_secrets(v, old_obj[i] if i < len(old_obj) else None)
            for i, v in enumerate(new_obj)
        ]
    return new_obj


def _chown_user(path: Path) -> None:
    """Give the file back to the install user (the engine runs as that user,
    the dashboard may run as root)."""
    try:
        import grp  # noqa: PLC0415
        import pwd  # noqa: PLC0415

        user = os.environ.get("MAV_INSTALL_USER")
        home = os.environ.get("MAV_USER_HOME") or os.environ.get("BOT_HOME")
        uid = None
        if not user and home and Path(home).exists():
            uid = os.stat(home).st_uid
        elif not user:
            # Infer from the existing file, else its directory, else the
            # bot data dir (whose owner is the install user).
            for cand in (
                Path(os.environ.get("BOT_DIR", "")),
                path.parent,
                path,
            ):
                try:
                    if cand and str(cand) and Path(cand).exists():
                        uid = os.stat(cand).st_uid
                        break
                except Exception:
                    continue
        if user:
            rec = pwd.getpwnam(user)
            uid, gid = rec.pw_uid, rec.pw_gid
        elif uid is not None:
            rec = pwd.getpwuid(uid)
            gid = rec.pw_gid
        else:
            return
        os.chown(path, uid, gid)
        # Only tighten files; never strip the execute bit from a directory.
        if path.is_file():
            os.chmod(path, 0o664)
    except Exception:
        pass


def read_agents() -> dict:
    p = agents_path()
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "path": str(p), "text": ""}
    return {"path": str(p), "text": text, "exists": p.is_file()}


def write_agents(text: str) -> dict:
    p = agents_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # Back up the previous version (keep a couple of them).
        if p.is_file():
            try:
                bak = p.with_suffix(".md.bak")
                bak.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
                _chown_user(bak)
            except Exception:
                pass
        p.write_text(text, encoding="utf-8")
        _chown_user(p)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    mark_pending("Custom instructions")
    return {"ok": True, "path": str(p)}


def read_mcp() -> dict:
    """MCP servers from the opencode config, secrets masked."""
    p = _opencode_config_path()
    try:
        cfg = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "path": str(p), "mcp": {}}
    return {"path": str(p), "mcp": _mask_secrets(cfg.get("mcp", {}) or {})}


def _normalize_mcp_entry(name: str, entry: dict) -> tuple[dict, str | None]:
    """Return (normalized_entry, error). Accepts opencode's schema and coerces
    the common shapes people paste from other MCP clients.

    opencode requires: type local + command [] , or type remote + url, and it
    rejects anything else (breaking startup with 'Missing key mcp.<name>.enabled').
    """
    if not isinstance(entry, dict):
        return entry, f"{name}: must be an object"
    e = dict(entry)

    # A bare { "enabled": bool } is a valid opencode entry (disable a remote default).
    if set(e.keys()) == {"enabled"}:
        return e, None

    # Coerce common aliases.
    if "env" in e and "environment" not in e:
        e["environment"] = e.pop("env")
    t = str(e.get("type", "")).lower()
    if t in ("stdio", "subprocess", "process"):
        e["type"] = "local"
    elif t in ("http", "sse", "streamable-http"):
        e["type"] = "remote"

    # command string + args []  ->  command [string, *args]
    if isinstance(e.get("command"), str):
        args = e.pop("args", None)
        cmd = [e["command"]]
        if isinstance(args, list):
            cmd += [str(a) for a in args]
        elif args is not None:
            cmd.append(str(args))
        e["command"] = cmd

    t = e.get("type")
    if t == "local":
        if not isinstance(e.get("command"), list) or not e["command"]:
            return e, (
                f"{name}: a local server needs \"command\" as an array of strings "
                '(e.g. "command": ["npx", "-y", "pkg"]), not a string with "args".'
            )
    elif t == "remote":
        if not isinstance(e.get("url"), str) or not e["url"]:
            return e, f'{name}: a remote server needs a "url".'
    else:
        return e, (
            f'{name}: needs "type": "local" (with "command") or "type": "remote" '
            '(with "url"), or be just {"enabled": true|false}.'
        )

    # opencode versions expect `enabled` on configured servers; default it on.
    e.setdefault("enabled", True)
    # Keep only keys opencode understands.
    allowed = {
        "type", "command", "cwd", "environment", "enabled", "timeout",
        "url", "headers", "oauth",
    }
    e = {k: v for k, v in e.items() if k in allowed}
    return e, None


def _validate_mcp(mcp: dict) -> tuple[dict, list[str]]:
    """Normalize every entry; return (clean_mcp, errors)."""
    clean: dict = {}
    errors: list[str] = []
    for name, entry in (mcp or {}).items():
        if not isinstance(name, str) or not name.strip():
            errors.append("MCP server name must be a non-empty string.")
            continue
        norm, err = _normalize_mcp_entry(name, entry)
        if err:
            errors.append(err)
        clean[name] = norm
    return clean, errors


def write_mcp(mcp: dict) -> dict:
    """Replace the `mcp` key in opencode.json, preserving other settings.

    Validates and normalizes entries first: an invalid MCP config would make
    opencode refuse to start, so we refuse to save it and explain why."""
    p = _opencode_config_path()
    if not isinstance(mcp, dict):
        return {"ok": False, "error": "mcp must be an object"}
    clean, errors = _validate_mcp(mcp)
    if errors:
        return {"ok": False, "error": "Invalid MCP config:\n- " + "\n- ".join(errors)}
    try:
        cfg = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except Exception:
        cfg = {}
    old = cfg.get("mcp", {}) or {}
    # Normalize the existing entries too, so the merge stays consistent.
    old_clean, _ = _validate_mcp(old)
    cfg["mcp"] = _merge_secrets(clean, old_clean)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(p)
        _chown_user(p)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    mark_pending("Connections")
    return {"ok": True, "path": str(p)}


def restart_engine() -> dict:
    """Restart the engine without blocking: issue the restart and return
    immediately. The caller polls /api/config/engine until it is back.

    `systemctl` alone can take minutes because the bot holds a long-lived SSE
    connection, so the graceful stop waits. `--no-block` returns at once."""
    unit = server_unit()
    code, out = _run(["systemctl", "restart", "--no-block", unit], timeout=15)
    if code != 0:
        return {"ok": False, "error": out.strip(), "unit": unit}
    # The worker follows the engine's event stream and reads the model from
    # its env: restart it too so it picks up the new configuration.
    _run(["systemctl", "restart", "--no-block", WORKER_UNIT], timeout=15)
    _agents_cache["at"] = 0.0
    _pending.clear()
    return {"ok": True, "restarting": True, "unit": unit}


# ------------------------------------------------------- pending changes
# Changes to custom instructions, helpers, connections or keys only apply
# once the assistant restarts. We remember what changed (from the web app)
# and also compare file times with the engine's start time (edits by hand).

_pending: dict = {}  # label -> time of the change


def mark_pending(label: str) -> None:
    _pending[label] = time.time()


def engine_started_at() -> float | None:
    """Unix time the engine service last (re)started, or None."""
    code, out = _run(
        ["systemctl", "show", server_unit(), "-p", "ActiveEnterTimestampMonotonic", "--value"], timeout=6
    )
    try:
        mono = int(out.strip() or 0)
        if code != 0 or mono <= 0:
            return None
        btime = next(int(l.split()[1]) for l in open("/proc/stat") if l.startswith("btime"))
        return btime + mono / 1e6
    except Exception:  # noqa: BLE001
        return None


def _config_files() -> dict:
    files = {
        "Connections or model": _opencode_config_path(),
        "Custom instructions": agents_path(),
        "API keys": ENV_SERVER,
    }
    d = agents_dir()
    try:
        newest = max([d] + list(d.glob("*.md")), key=lambda p: p.stat().st_mtime)
        files["Helpers"] = newest
    except Exception:  # noqa: BLE001
        pass
    return files


def pending_changes() -> list[str]:
    started = engine_started_at()
    labels = set()
    if started:
        for label, path in _config_files().items():
            try:
                if Path(path).stat().st_mtime > started + 2:
                    labels.add(label)
            except Exception:  # noqa: BLE001
                continue
        labels |= {k for k, t in _pending.items() if t > started}
    else:
        labels |= set(_pending)
    # Precise labels from the web app win over the generic file one.
    if labels & {"Connections", "Model"}:
        labels.discard("Connections or model")
    return sorted(labels)


# ------------------------------------------------------------ versions
_release_cache: dict = {"at": 0.0, "data": None}


def installed_version() -> str:
    try:
        return VERSION_FILE.read_text().strip().splitlines()[0] or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _semver(v: str) -> tuple | None:
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)$", (v or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def latest_release(force: bool = False) -> dict | None:
    """Latest GitHub release (cached 6 h; 30 min after a failure)."""
    now = time.time()
    ttl = 6 * 3600 if _release_cache["data"] else 1800
    if not force and now - _release_cache["at"] < ttl:
        return _release_cache["data"]
    data = None
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{MAV_REPO}/releases/latest",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "mav"},
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            rel = json.loads(r.read().decode("utf-8", "replace"))
        data = {
            "tag": rel.get("tag_name", ""),
            "url": rel.get("html_url", ""),
            "notes": (rel.get("body") or "")[:4000],
            "published": rel.get("published_at", ""),
        }
    except Exception:  # noqa: BLE001
        data = None
    _release_cache.update(at=now, data=data)
    return data


def version_info(force: bool = False) -> dict:
    cur = installed_version()
    rel = latest_release(force)
    latest = (rel or {}).get("tag", "")
    a, b = _semver(latest), _semver(cur)
    # Installs that are not on a release (a branch, a clone) can always move
    # to the latest release.
    available = bool(a and (b is None or a > b)) and cur != latest
    return {
        "installed": cur,
        "latest": latest,
        "update_available": available,
        "release_url": (rel or {}).get("url", ""),
        "notes": (rel or {}).get("notes", "") if available else "",
        "updating": update_running(),
    }


def update_running() -> bool:
    code, out = _run(["systemctl", "is-active", "mav-update"], timeout=6)
    return out.strip() in ("active", "activating")


def start_update() -> dict:
    """Run `mav update` outside the web app's own service: the update restarts
    the web app, and must survive that."""
    if update_running():
        return {"ok": True, "already": True}
    if not Path(MAV_CLI).exists():
        return {"ok": False, "error": "The mav command is not installed — run: sudo mav update"}
    code, out = _run(
        ["systemd-run", "--unit=mav-update", "--collect", "--quiet",
         "--description=Mav update", MAV_CLI, "update", "--yes"],
        timeout=15,
    )
    if code != 0:
        return {"ok": False, "error": out.strip() or "could not start the update"}
    return {"ok": True}


def update_status() -> dict:
    lines = []
    try:
        with open(INSTALL_LOG, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 6000))
            raw = f.read().decode("utf-8", "replace").splitlines()
        lines = [l for l in raw if l.startswith("===")][-6:]
    except Exception:  # noqa: BLE001
        pass
    return {
        "running": update_running(),
        "installed": installed_version(),
        "steps": [l.split(" — ", 1)[-1] for l in lines],
    }


# ------------------------------------------------------- connections catalog
def _install_home() -> Path:
    return Path(os.environ.get("MAV_USER_HOME") or Path.home())


def find_runtime(name: str) -> str:
    """Absolute path of npx / uvx as the engine will need it (the engine's
    service has a minimal PATH, so ~/.local/bin is resolved here)."""
    home = _install_home()
    for d in [*os.environ.get("PATH", "").split(":"), str(home / ".local/bin"),
              str(home / ".cargo/bin"), "/usr/local/bin", "/usr/bin"]:
        p = Path(d) / name
        if d and p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return ""


def mcp_catalog() -> dict:
    try:
        cat = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        cat = {"items": []}
    installed = set((read_mcp().get("mcp") or {}).keys())
    runtimes = {r: bool(find_runtime(r)) for r in ("npx", "uvx")}
    for it in cat.get("items", []):
        it["installed"] = it["id"] in installed
        rt = it.get("runtime")
        it["ready"] = not rt or runtimes.get(rt, False)
    return {"items": cat.get("items", []), "runtimes": runtimes}


def _fill(value, values: dict):
    if isinstance(value, str):
        return re.sub(r"\{\{(\w+)\}\}", lambda m: str(values.get(m.group(1), "")), value)
    if isinstance(value, list):
        return [_fill(v, values) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, values) for k, v in value.items()}
    return value


def install_from_catalog(item_id: str, values: dict) -> dict:
    item = next((i for i in mcp_catalog()["items"] if i["id"] == item_id), None)
    if not item:
        return {"ok": False, "error": "Unknown connection."}
    values = {k: str(v).strip() for k, v in (values or {}).items()}
    for inp in item.get("inputs", []):
        if inp.get("required") and not values.get(inp["key"]):
            return {"ok": False, "error": f"{inp['label']} is required."}
    if "base_url" in values:
        values["base_url"] = values["base_url"].rstrip("/")
    entry: dict = {"type": item["type"], "enabled": True}
    if item["type"] == "local":
        cmd = _fill(item["command"], values)
        rt = item.get("runtime")
        if rt:
            path = find_runtime(rt)
            if not path:
                hint = {"npx": "sudo apt install nodejs npm",
                        "uvx": "curl -LsSf https://astral.sh/uv/install.sh | sh"}.get(rt, "")
                return {"ok": False, "error": f"This connection needs {rt}, which is not installed. Install it with: {hint}"}
            cmd[0] = path
        entry["command"] = cmd
        if item.get("environment"):
            entry["environment"] = _fill(item["environment"], values)
    else:
        entry["url"] = _fill(item["url"], values)
        if item.get("headers"):
            entry["headers"] = _fill(item["headers"], values)
    return add_mcp_entry(item_id, entry)


def add_mcp_entry(name: str, entry: dict) -> dict:
    """Add or replace one MCP server, keeping the others untouched."""
    p = _opencode_config_path()
    norm, err = _normalize_mcp_entry(name, entry)
    if err:
        return {"ok": False, "error": err}
    try:
        cfg = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except Exception:  # noqa: BLE001
        cfg = {}
    cfg.setdefault("mcp", {})[name] = norm
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(p)
        _chown_user(p)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    mark_pending("Connections")
    return {"ok": True, "name": name}


# --------------------------------------------------------------- provider
# Model provider, configured from Settings → Model. The logic is shared with
# install.sh (mav_provider.py), so both write exactly the same config.


def provider_current() -> dict:
    try:
        return mav_provider.current(_config_dir(), ENV_SERVER)
    except Exception as exc:  # noqa: BLE001
        return {"configured": bool(DEFAULT_MODEL), "ref": DEFAULT_MODEL, "error": str(exc)}


def provider_snapshot() -> dict:
    cur = provider_current()
    presets = [
        {"id": k, **{x: v[x] for x in ("label", "hint", "native", "base", "key", "model")}}
        for k, v in mav_provider.PRESETS.items()
    ]
    return {"current": cur, "presets": presets, "model": DEFAULT_MODEL}


def _stored_key(pid: str) -> str:
    return mav_provider.read_env(ENV_SERVER).get(mav_provider.env_name_for(pid), "")


def provider_test(payload: dict) -> dict:
    pid = (payload.get("provider") or "").strip()
    key = payload.get("api_key") or ""
    if not key:
        key = _stored_key(pid)  # test with the saved key when left blank
    return mav_provider.list_models(pid, payload.get("base_url") or "", key)


def provider_save(payload: dict) -> dict:
    global DEFAULT_MODEL
    pid = (payload.get("provider") or "").strip().lower()
    if pid == "custom":
        pid = (payload.get("custom_id") or "").strip().lower()
    key = payload.get("api_key")
    key = key if isinstance(key, str) and key.strip() else None  # blank = keep
    res = mav_provider.apply(
        _config_dir(), ENV_SERVER, pid, payload.get("model") or "",
        base_url=(payload.get("base_url") or "").strip(),
        api_key=key.strip() if key else None,
        env_files=ENV_FILES,
        name=(payload.get("name") or "").strip(),
    )
    if not res.get("ok"):
        return res
    DEFAULT_MODEL = res["ref"]
    _chown_user(_opencode_config_path())
    if payload.get("restart", True):
        res["restart"] = restart_engine()
    else:
        mark_pending("Model")
    return res


def config_snapshot() -> dict:
    """Everything the settings screen shows at once."""
    cfg = _opencode_config_path()
    return {
        "agents": read_agents(),
        "mcp": read_mcp(),
        "engine": engine_status(),
        "config_path": str(cfg),
        "model": DEFAULT_MODEL,
        "url": OPENCODE_URL,
    }


# --------------------------------------------------------------- agent files
# User-defined agents: one Markdown file (YAML frontmatter + prompt) per agent
# in ~/.config/opencode/agent/. The dashboard lists, creates, edits and
# deletes them; restarting the engine makes opencode pick them up.

def agents_dir() -> Path:
    env = os.environ.get("MAV_AGENTS_DIR")
    if env:
        return Path(env)
    return _config_dir() / "agent"


AGENT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


def _parse_frontmatter(text: str) -> dict:
    """Tiny YAML frontmatter reader (description/mode/model/… scalar keys)."""
    meta = {}
    if not text.startswith("---"):
        return meta
    end = text.find("\n---", 3)
    if end == -1:
        return meta
    for line in text[3:end].strip().splitlines():
        if ":" in line and not line.startswith((" ", "\t", "-")):
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta


def list_agent_files() -> dict:
    d = agents_dir()
    out = []
    try:
        files = sorted(d.glob("*.md"))
    except Exception:
        files = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        meta = _parse_frontmatter(text)
        out.append({
            "name": f.stem,
            "description": meta.get("description", ""),
            "mode": meta.get("mode", "subagent"),
            "model": meta.get("model", ""),
            "bytes": len(text),
        })
    return {"dir": str(d), "agents": out}


def read_agent_file(name: str) -> dict:
    if not AGENT_NAME_RE.match(name or ""):
        return {"error": "invalid name", "name": name, "text": ""}
    p = agents_dir() / f"{name}.md"
    try:
        return {"name": name, "path": str(p), "text": p.read_text(encoding="utf-8"), "exists": p.is_file()}
    except FileNotFoundError:
        return {"name": name, "path": str(p), "text": "", "exists": False}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "name": name, "text": ""}


def write_agent_file(name: str, text: str) -> dict:
    if not AGENT_NAME_RE.match(name or ""):
        return {"ok": False, "error": "invalid agent name (a-z, 0-9, - _)"}
    if not isinstance(text, str):
        return {"ok": False, "error": "text required"}
    d = agents_dir()
    p = d / f"{name}.md"
    try:
        d.mkdir(parents=True, exist_ok=True)
        if p.is_file():
            try:
                bak = p.with_suffix(".md.bak")
                bak.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
                _chown_user(bak)
            except Exception:
                pass
        p.write_text(text, encoding="utf-8")
        _chown_user(p)
        _chown_user(d)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    _agents_cache["at"] = 0.0
    mark_pending("Helpers")
    return {"ok": True, "name": name, "path": str(p)}


def delete_agent_file(name: str) -> dict:
    if not AGENT_NAME_RE.match(name or ""):
        return {"ok": False, "error": "invalid name"}
    p = agents_dir() / f"{name}.md"
    try:
        if p.is_file():
            p.unlink()
        _agents_cache["at"] = 0.0
        mark_pending("Helpers")
        return {"ok": True, "name": name}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


AGENT_TEMPLATE = """---
description: Short description of what this agent does
mode: subagent
---

You are <role>. <What you do and how.>

Rules:
- <rule>
- <rule>
"""




# ------------------------------------------------------------------- data


def get_status() -> dict:
    m = sys_metrics()
    try:
        health = http_json(f"{OPENCODE_URL}/global/health", timeout=4)
    except Exception:
        health = {"healthy": False}

    pg = False
    n_watch = n_conv = n_facts = 0
    try:
        pg_query("select 1")
        pg = True
        n_watch = pg_query("select count(*) c from watch_items")[0]["c"]
        n_conv = pg_query("select count(*) c from conversations")[0]["c"]
        n_facts = pg_query("select count(*) c from facts")[0]["c"]
    except Exception:
        pass

    jobs = read_json(JOBS_FILE, [])
    prov = provider_current()
    return {
        "mode": "live",
        "model": DEFAULT_MODEL or prov.get("ref") or "",
        "provider_configured": bool(prov.get("configured")),
        "memory_backend": "postgres" if pg else "file",
        "pending": pending_changes(),
        "mav_version": installed_version(),
        "agent_online": bool(health and health.get("healthy")),
        "version": (health or {}).get("version"),
        "cpu": cpu_pct() or m.get("load", 0),
        "mem_pct": m.get("mem_pct"),
        "disk_pct": m.get("disk_pct"),
        "load": m.get("load"),
        "uptime_s": m.get("uptime_s"),
        "postgres": pg,
        "jobs_active": sum(1 for j in jobs if j.get("enabled", True)),
        "jobs_total": len(jobs),
        "conversations": n_conv,
        "facts": n_facts,
        "watch_items": n_watch,
    }


def get_connections() -> list[dict]:
    conns = []
    try:
        h = http_json(f"{OPENCODE_URL}/global/health", timeout=4)
        ok = bool(h and h.get("healthy"))
        conns.append({"name": "Agent engine", "state": "ok" if ok else "off", "label": "online" if ok else "offline"})
    except Exception:
        conns.append({"name": "Agent engine", "state": "off", "label": "offline"})
    try:
        pg_query("select 1")
        conns.append({"name": "Memory (Postgres)", "state": "ok", "label": "connected"})
    except Exception:
        conns.append({"name": "Memory (Postgres)", "state": "off", "label": "offline"})
    worker = _unit_active(WORKER_UNIT)
    conns.append({"name": "Worker", "state": "ok" if worker else "warn", "label": "running" if worker else "stopped"})
    return conns


def get_jobs() -> dict:
    jobs = read_json(JOBS_FILE, [])
    state = read_json(JOBS_STATE, {})
    # routine name -> its chat, when it ran at least once
    head = PREFIX + ROUTINE_PREFIX
    chats = {
        str(s_.get("title", ""))[len(head):]: s_["id"]
        for s_ in _list_raw_sessions()
        if str(s_.get("title", "")).startswith(head)
    }
    out = []
    for j in jobs:
        out.append(
            {
                "name": j.get("name"),
                "description": j.get("description", ""),
                "time": j.get("time", ""),
                "every_minutes": j.get("every_minutes"),
                "days": j.get("days", []),
                "agent": j.get("agent", ""),
                "prompt": j.get("prompt", ""),
                "enabled": j.get("enabled", True),
                "last_run": state.get(j.get("name")),
                "running": j.get("name") in _running_jobs,
                "session": chats.get(j.get("name")),
            }
        )
    return {"jobs": out}


JOB_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,60}$")
JOB_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def save_job(payload: dict) -> dict:
    """Create or update a job (`original` = name before a rename)."""
    name = str(payload.get("name") or "").strip()
    if not JOB_NAME_RE.match(name):
        return {"ok": False, "error": "Give the automation a name (letters, digits, - _ .)."}
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        return {"ok": False, "error": "Write what Mav should do."}
    every = payload.get("every_minutes")
    try:
        every = int(every) if every not in (None, "", 0, "0") else 0
    except (TypeError, ValueError):
        return {"ok": False, "error": "The interval must be a number of minutes."}
    time_ = str(payload.get("time") or "").strip()
    if not every and not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", time_):
        return {"ok": False, "error": "Pick a time (HH:MM) or an interval."}
    days = [d for d in (payload.get("days") or []) if d in JOB_DAYS] or JOB_DAYS
    job = {
        "name": name,
        "description": str(payload.get("description") or "").strip()[:200],
        "prompt": prompt,
        "agent": str(payload.get("agent") or "").strip(),
        "days": days,
        "enabled": bool(payload.get("enabled", True)),
    }
    if every:
        job["every_minutes"] = max(5, every)
    else:
        job["time"] = time_
    jobs = read_json(JOBS_FILE, [])
    if not isinstance(jobs, list):
        jobs = []
    original = str(payload.get("original") or "").strip()
    if name != original and any(j.get("name") == name for j in jobs):
        return {"ok": False, "error": f"An automation named \"{name}\" already exists."}
    replaced = False
    for i, j in enumerate(jobs):
        if j.get("name") == (original or name):
            # Keep unknown keys (retries, chat_id…) from hand-edited files.
            keep = {k: v for k, v in j.items() if k not in ("time", "every_minutes")}
            jobs[i] = {**keep, **job}
            replaced = True
            break
    if not replaced:
        jobs.append(job)
    write_json(JOBS_FILE, jobs)
    _chown_user(JOBS_FILE)
    return {"ok": True, "job": job}


def delete_job(name: str) -> bool:
    jobs = read_json(JOBS_FILE, [])
    keep = [j for j in jobs if j.get("name") != name]
    if len(keep) == len(jobs):
        return False
    write_json(JOBS_FILE, keep)
    return True


_running_jobs: set = set()

# Each routine posts into its own dashboard chat, which the user can open and
# continue. The worker (scheduled runs) finds it by the same title.
ROUTINE_PREFIX = "Routine · "


def routine_session(name: str, agent: str = "") -> str:
    title = PREFIX + ROUTINE_PREFIX + name
    for s_ in _list_raw_sessions():
        if s_.get("title") == title:
            return s_["id"]
    sid = create_session(ROUTINE_PREFIX + name, agent)["id"]
    set_session_meta(sid, title_locked=True, titled=True, routine=name)
    return sid


def record_notification(topic: str, title: str, body: str, link: str = "") -> int | None:
    try:
        rows = pg_query(
            "insert into notifications (ts, chat_id, topic, title, body, channels, delivered, link) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
            (int(time.time()), DEFAULT_CHAT_ID, topic, title[:200], body[:2000], ["push"], True, link or None),
        )
        return rows[0]["id"] if rows else None
    except Exception:  # noqa: BLE001
        return None


def run_job_now(name: str) -> dict:
    """Run a routine now, in the background, exactly like a scheduled run:
    in the routine's chat, with memory, then a push + an inbox entry."""
    job = next((j for j in read_json(JOBS_FILE, []) if j.get("name") == name), None)
    if not job:
        return {"ok": False, "error": "Unknown routine."}
    if name in _running_jobs:
        return {"ok": False, "error": "Already running."}
    agent = job.get("agent", "") or DEFAULT_AGENT
    sid = routine_session(name, agent)

    def work():
        _running_jobs.add(name)
        try:
            text = ask(job.get("prompt", ""), agent, sid, raw_session=True, with_memory=True)
            summary = " ".join(re.sub(r"[*_`#>|]+", "", text or "").split())
            if len(summary) > 220:
                summary = summary[:217] + "…"
            if summary and not text.startswith("Error:"):
                link = f"./#chat/{sid}"
                record_notification("routine", f"🔁 {name}", summary, link)
                send_push(f"🔁 {name}", summary, link)
        except Exception:  # noqa: BLE001
            pass
        finally:
            _running_jobs.discard(name)

    threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "session": sid}


def set_job_enabled(name: str, enabled: bool) -> bool:
    jobs = read_json(JOBS_FILE, [])
    found = False
    for j in jobs:
        if j.get("name") == name:
            j["enabled"] = bool(enabled)
            found = True
    if found:
        write_json(JOBS_FILE, jobs)
    return found


def get_job_results(limit: int = 8) -> dict:
    """Latest report of each routine (the last answer in its chat)."""
    head = PREFIX + ROUTINE_PREFIX
    chats = []
    for s_ in _list_raw_sessions():
        title = str(s_.get("title", ""))
        if title.startswith(head):
            t = s_.get("time", {})
            chats.append({"id": s_["id"], "name": title[len(head):], "updated": t.get("updated") or t.get("created") or 0})
    chats.sort(key=lambda x: x["updated"], reverse=True)
    out = []
    for c in chats[:limit]:
        text = next((m["text"] for m in reversed(session_messages(c["id"])) if m["role"] == "mav"), "")
        if text:
            out.append({"name": c["name"], "updated": c["updated"], "text": text[:4000], "session": c["id"]})
    return {"results": out}


def get_memory(limit: int = 40) -> dict:
    def q(sql, params=()):
        try:
            return pg_query(sql, params)
        except Exception:
            return []

    return {
        "conversations": q(
            "select id, question, left(answer, 600) as answer, ts, source, agent "
            "from conversations order by ts desc limit %s",
            (limit,),
        ),
        "facts": q("select id, fact, source, ts from facts order by ts desc limit 200"),
        "preferences": q("select key, value, ts from preferences order by ts desc limit 20"),
        "backend": MEMORY.backend if MEMORY else "none",
        "enabled": MEMORY_ENABLED,
    }


def memory_action(action: str, payload: dict) -> dict:
    if action == "fact/add":
        fact = str(payload.get("fact") or "").strip()
        if not fact:
            return {"ok": False, "error": "Empty fact."}
        if MEMORY:
            return {"ok": MEMORY.add_fact(DEFAULT_CHAT_ID, fact, source="dashboard")}
        pg_exec(
            "insert into facts (chat_id, fact, source, ts) values (%s, %s, %s, %s)",
            (DEFAULT_CHAT_ID, fact[:500], "dashboard", int(time.time())),
        )
        return {"ok": True}
    if action == "fact/delete":
        pg_exec("delete from facts where id = %s", (int(payload.get("id") or 0),))
        return {"ok": True}
    if action == "exchange/delete":
        pg_exec("delete from conversations where id = %s", (int(payload.get("id") or 0),))
        return {"ok": True}
    if action == "forget":
        pg_exec("delete from conversations")
        if payload.get("facts"):
            pg_exec("delete from facts")
        return {"ok": True}
    return {"ok": False, "error": "unknown action"}


def get_watch() -> dict:
    try:
        items = pg_query(
            "select id, kind, target, last_state, last_checked, enabled from watch_items order by id desc"
        )
    except Exception:
        items = []
    return {"items": items}


def get_notifications(limit: int = 30) -> dict:
    """Historique des notifications proactives (veille + jobs)."""
    try:
        rows = pg_query(
            "select id, ts, topic, title, body, channels, delivered, link "
            "from notifications where topic is distinct from 'push_ack' "
            "order by ts desc limit %s",
            (limit,),
        )
    except Exception:
        rows = []
    return {"notifications": rows}


def get_notification(nid: int) -> dict:
    """One notification by id (to open its detail from the push)."""
    try:
        rows = pg_query(
            "select id, ts, topic, title, body, delivered, link from notifications where id = %s",
            (nid,),
        )
    except Exception:
        rows = []
    return {"notification": rows[0] if rows else None}


# --------------------------------------------------------------- debates
# Multi-agent debate threads are written by the opencode debate tools; the web
# app shows them live. Reading is best-effort: an absent file just means no
# debate has been opened yet.
def get_debates() -> dict:
    try:
        from ocdebates import list_threads  # noqa: PLC0415

        return {"debates": list_threads()}
    except Exception:  # noqa: BLE001
        return {"debates": []}


def get_debate(thread_id: str) -> dict:
    if not thread_id:
        return {"error": "missing id"}
    try:
        from ocdebates import get_thread  # noqa: PLC0415

        thread = get_thread(thread_id)
    except Exception:  # noqa: BLE001
        thread = None
    return {"debate": thread}


VALID_WATCH_KINDS = ["web", "price", "news"]


def watch_add(kind: str, target: str) -> bool:
    if kind not in VALID_WATCH_KINDS or not target.strip():
        return False
    pg_exec(
        "insert into watch_items (chat_id, kind, target, ts) values (%s, %s, %s, %s)",
        (DEFAULT_CHAT_ID, kind, target.strip()[:500], int(time.time())),
    )
    return True


def watch_remove(item_id: int) -> bool:
    pg_exec("delete from watch_items where id = %s", (item_id,))
    return True


def get_agents() -> dict:
    """Agents offered in the chat picker, with their description."""
    # Internal agents we do not offer in the selector.
    hidden = {"compaction", "title", "summary", "plan", "build"}
    try:
        agents = http_json(f"{OPENCODE_URL}/agent", timeout=6) or []
        details = {}
        for a in agents:
            if not isinstance(a, dict) or not a.get("name"):
                continue
            if a["name"] in hidden or a.get("hidden"):
                continue
            # Primary AND subagents: both work as the session agent for chat.
            if a.get("mode") not in ("primary", "subagent", "all", None):
                continue
            details[a["name"]] = {
                "description": (a.get("description") or "").strip()[:200],
                "mode": a.get("mode") or "all",
            }
        names = sorted(details)
        ordered = [n for n in PRIMARY_AGENTS if n in names] + [n for n in names if n not in PRIMARY_AGENTS]
        default = DEFAULT_AGENT if DEFAULT_AGENT in details else (ordered[0] if ordered else "")
        return {"agents": ordered or PRIMARY_AGENTS, "details": details, "default": default}
    except Exception:
        return {"agents": PRIMARY_AGENTS, "details": {}, "default": DEFAULT_AGENT}


# ------------------------------------------------------------------- search


def global_search(query: str) -> dict:
    q = query.strip()
    if not q:
        return {"documents": [], "conversations": [], "facts": []}
    docs, convs, facts = [], [], []
    try:
        docs = pg_query(
            "select title, left(body, 240) as excerpt, source, ts "
            "from documents where tsv @@ plainto_tsquery('french', %s) "
            "order by ts desc limit 8",
            (q,),
        )
    except Exception:
        pass
    try:
        convs = pg_query(
            "select question, left(answer, 240) as answer, ts from conversations "
            "where question ilike %s or answer ilike %s order by ts desc limit 8",
            (f"%{q}%", f"%{q}%"),
        )
    except Exception:
        pass
    try:
        facts = pg_query(
            "select fact, ts from facts where fact ilike %s order by ts desc limit 8",
            (f"%{q}%",),
        )
    except Exception:
        pass
    return {"documents": docs, "conversations": convs, "facts": facts}


# ------------------------------------------------------------------- chat

PREFIX = "dash: "
DEFAULT_TITLE = "New conversation"
LEGACY_TITLES = {"", DEFAULT_TITLE, "Nouvelle discussion"}

# Per-conversation metadata the engine does not keep: the agent the user is
# talking to, and whether the title was generated already.
_meta_lock = threading.Lock()


def session_meta(sid: str) -> dict:
    return (read_json(SESSIONS_META, {}) or {}).get(sid, {})


def set_session_meta(sid: str, **fields) -> None:
    if not sid:
        return
    with _meta_lock:
        meta = read_json(SESSIONS_META, {})
        if not isinstance(meta, dict):
            meta = {}
        meta.setdefault(sid, {}).update(fields)
        try:
            write_json(SESSIONS_META, meta)
        except Exception:  # noqa: BLE001
            pass


def drop_session_meta(sid: str) -> None:
    with _meta_lock:
        meta = read_json(SESSIONS_META, {})
        if isinstance(meta, dict) and meta.pop(sid, None) is not None:
            try:
                write_json(SESSIONS_META, meta)
            except Exception:  # noqa: BLE001
                pass


def _list_raw_sessions() -> list[dict]:
    try:
        return http_json(f"{OPENCODE_URL}/session", timeout=8) or []
    except Exception:
        return []


def _migrate_legacy() -> None:
    for s in _list_raw_sessions():
        if s.get("title") == "dashboard":
            try:
                http_json(f"{OPENCODE_URL}/session/{s['id']}", method="PATCH", body={"title": PREFIX + "First conversation"})
            except Exception:
                pass


def list_sessions() -> list[dict]:
    _migrate_legacy()
    meta = read_json(SESSIONS_META, {}) or {}
    jobs = read_json(JOBS_FILE, []) or []
    out = []
    for s in _list_raw_sessions():
        title = str(s.get("title", ""))
        if not title.startswith(PREFIX):
            continue
        # Job runs create "dash: job: <name>": these are not
        # discussions, on ne les met pas dans la liste.
        if title[len(PREFIX):].startswith("job:"):
            continue
        t = s.get("time", {})
        m = meta.get(s["id"], {})
        routine = title[len(PREFIX):].startswith(ROUTINE_PREFIX)
        agent = m.get("agent", "")
        if routine and not agent:
            name = title[len(PREFIX) + len(ROUTINE_PREFIX):]
            agent = next((j.get("agent", "") for j in jobs if j.get("name") == name), "")
        out.append({
            "id": s["id"],
            "title": title[len(PREFIX):] or DEFAULT_TITLE,
            "created": t.get("created"),
            "updated": t.get("updated") or t.get("created"),
            "agent": agent,
            "pinned": bool(m.get("pinned")),
            "routine": routine,
        })
    out.sort(key=lambda x: (x["pinned"], x.get("updated") or 0), reverse=True)
    return out


def create_session(title: str = "", agent: str = "") -> dict:
    name = (title or DEFAULT_TITLE).strip()[:80] or DEFAULT_TITLE
    res = http_json(f"{OPENCODE_URL}/session", method="POST", body={"title": PREFIX + name})
    agent = (agent or "").strip()
    if agent:
        set_session_meta(res["id"], agent=agent)
    return {"id": res["id"], "title": name, "agent": agent}


# ------------------------------------------------------------- auto titles
# After the first exchange, a short title is generated in the background from
# the question and the answer. A keyword title is shown meanwhile, and stays if
# the model is unavailable.

def quick_title(prompt: str) -> str:
    words = re.sub(r"\s+", " ", prompt.strip()).split(" ")
    title = " ".join(words[:7])
    if len(title) > 48:
        title = title[:47].rstrip() + "…"
    elif len(words) > 7:
        title += "…"
    return (title[:1].upper() + title[1:]) if title else DEFAULT_TITLE


def _clean_title(raw: str) -> str:
    line = next((l for l in (raw or "").strip().splitlines() if l.strip()), "")
    line = re.sub(r"^(title|titre)\s*[:：-]\s*", "", line.strip(), flags=re.I)
    line = line.strip(" \"'`*#.").strip()
    words = line.split()
    if not words or len(words) > 8:
        return ""
    return " ".join(words)[:48]


def quick_completion(instruction: str, agent: str = "", timeout: float = 90) -> str:
    """One-shot model call in a throwaway session (titles, fact extraction)."""
    tmp = None
    try:
        tmp = http_json(f"{OPENCODE_URL}/session", method="POST", body={"title": "mav-internal"}, timeout=10)["id"]
        body = {"parts": [{"type": "text", "text": instruction}], **_model_body()}
        if agent and agent in valid_agents():
            body["agent"] = agent
        res = http_json(f"{OPENCODE_URL}/session/{tmp}/message", method="POST", body=body, timeout=timeout)
        return _part_text((res or {}).get("parts") or [])
    except Exception:  # noqa: BLE001
        return ""
    finally:
        if tmp:
            delete_session(tmp)


# ------------------------------------------------------------- learned facts
# Like ChatGPT's memory: when a message says something about the user, durable
# facts are extracted in the background and saved (source "learned").

ABOUT_ME_RE = re.compile(
    r"\b(i|i'm|im|i've|i'd|my|mine|me|we|we're|our|us|je|j'|moi|mon|ma|mes|nous|notre|nos)\b",
    re.I,
)


def learn_facts(prompt: str) -> int:
    if not (MEMORY and MEMORY_ENABLED) or not ABOUT_ME_RE.search(prompt) or len(prompt) > 4000:
        return 0
    instruction = (
        "Extract durable personal facts about the user from their message below: "
        "things worth remembering in future conversations (where they live, job, "
        "family, health or diet, preferences, recurring constraints, goals). "
        "Ignore one-off requests and anything about other topics. Write each fact "
        "as a short third-person sentence starting with 'User', in the language "
        "of the message, one per line, each line starting with '- '. If there is "
        "nothing durable, reply exactly NONE.\n\n"
        f"Message: {prompt.strip()[:2000]}"
    )
    raw = quick_completion(instruction, timeout=120)
    if not raw or raw.strip().upper().startswith("NONE"):
        return 0
    known = [f["fact"].lower() for f in MEMORY.facts(DEFAULT_CHAT_ID, limit=200)]
    added = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith(("-", "•", "*")):
            continue
        fact = line.lstrip("-•* ").strip().rstrip(".")
        if len(fact) < 6 or len(fact) > 240:
            continue
        low = fact.lower()
        if any(low in k or k in low for k in known):
            continue
        if MEMORY.add_fact(DEFAULT_CHAT_ID, fact, source="learned"):
            known.append(low)
            added += 1
        if added >= 3:
            break
    return added


def generate_title(sid: str, prompt: str, answer: str) -> None:
    """Ask the model for a 2–5 word title in a throwaway session."""
    tmp = None
    try:
        tmp = http_json(f"{OPENCODE_URL}/session", method="POST", body={"title": "mav-title"}, timeout=10)["id"]
        instruction = (
            "Write a title of 2 to 5 words for the conversation below, in the "
            "language of the user's message. Reply with the title only: no "
            "quotes, no punctuation at the end, no explanation.\n\n"
            f"User: {prompt.strip()[:800]}\n\nAssistant: {answer.strip()[:800]}"
        )
        body = {"parts": [{"type": "text", "text": instruction}], **_model_body()}
        if "title" in valid_agents():
            body["agent"] = "title"
        res = http_json(f"{OPENCODE_URL}/session/{tmp}/message", method="POST", body=body, timeout=90)
        title = _clean_title(_part_text((res or {}).get("parts") or []))
        if title and session_meta(sid).get("title_locked") is not True:
            rename_session(sid, title)
            set_session_meta(sid, titled=True)
    except Exception:  # noqa: BLE001
        pass
    finally:
        if tmp:
            delete_session(tmp)


def rename_session(sid: str, title: str) -> bool:
    name = (title or "").strip()[:80]
    if not sid or not name:
        return False
    for verb in ("PATCH", "PUT"):
        try:
            http_json(f"{OPENCODE_URL}/session/{sid}", method=verb, body={"title": PREFIX + name})
            return True
        except Exception:
            continue
    return False


def delete_session(sid: str) -> bool:
    if not sid:
        return False
    try:
        http_json(f"{OPENCODE_URL}/session/{sid}", method="DELETE")
        drop_session_meta(sid)
        return True
    except Exception:
        return False


def session_title(sid: str) -> str:
    try:
        s = http_json(f"{OPENCODE_URL}/session/{sid}", timeout=6) or {}
        return str(s.get("title", ""))
    except Exception:
        return ""


def _part_text(parts: list) -> str:
    return "\n\n".join(
        (p.get("text") or "").strip()
        for p in (parts or [])
        if p.get("type") == "text" and not p.get("synthetic") and (p.get("text") or "").strip()
    )


def session_messages(sid: str) -> list[dict]:
    try:
        entries = http_json(f"{OPENCODE_URL}/session/{sid}/message", timeout=12) or []
    except Exception:
        return []
    msgs = []
    for e in entries:
        info = e.get("info") or {}
        role = info.get("role")
        if role not in ("user", "assistant"):
            continue
        text = _part_text(e.get("parts") or [])
        if not text:
            continue
        msg = {
            "role": "me" if role == "user" else "mav",
            "text": text,
            "ts": (info.get("time") or {}).get("created"),
        }
        if role == "assistant":
            # The agent that actually answered (field name varies by version).
            msg["agent"] = info.get("agent") or info.get("mode") or ""
        msgs.append(msg)
    return msgs


def export_session_markdown(sid: str) -> str:
    title = session_title(sid)[len(PREFIX):] or DEFAULT_TITLE
    lines = [f"# {title}", ""]
    for m in session_messages(sid):
        who = "You" if m["role"] == "me" else (f"Mav · {m['agent']}" if m.get("agent") else "Mav")
        lines.append(f"**{who}**" + (f" · {_ts(m['ts'])}" if m.get("ts") else ""))
        lines.append("")
        lines.append(m["text"])
        lines.append("")
    return "\n".join(lines)


def _ts(ms) -> str:
    try:
        return time.strftime("%d/%m %H:%M", time.localtime(int(ms) / 1000))
    except Exception:
        return ""


def _model_body() -> dict:
    if DEFAULT_MODEL and "/" in DEFAULT_MODEL:
        provider, model = DEFAULT_MODEL.split("/", 1)
        return {"model": {"providerID": provider, "modelID": model}}
    return {}


def _parts(prompt: str, files: list) -> list:
    parts: list[dict] = [{"type": "text", "text": prompt}]
    for f in files or []:
        parts.append({
            "type": "file",
            "url": f.get("url"),
            "mime": f.get("mime") or "application/octet-stream",
            "filename": f.get("filename") or "fichier",
        })
    return parts


def memory_context(prompt: str) -> str:
    """Facts + relevant past exchanges + indexed documents, for a new chat."""
    global _RAG
    blocks = []
    if MEMORY and MEMORY_ENABLED:
        try:
            b = MEMORY.context_block(DEFAULT_CHAT_ID, prompt, MEMORY_TOP)
            if b:
                blocks.append(b)
        except Exception:  # noqa: BLE001
            pass
    if RAG is not None:
        try:
            if _RAG is None:
                _RAG = RAG()
            b = _RAG.context_block(DEFAULT_CHAT_ID, prompt, MEMORY_TOP)
            if b:
                blocks.append(b)
        except Exception:  # noqa: BLE001
            pass
    return "\n\n".join(blocks)


def remember_exchange(prompt: str, answer: str, sid: str, agent: str) -> None:
    if MEMORY and MEMORY_ENABLED and answer:
        try:
            MEMORY.add(DEFAULT_CHAT_ID, prompt, answer, sid, source="dashboard", agent=agent)
        except Exception:  # noqa: BLE001
            pass


def save_upload(name: str, data_b64: str, mime: str = "") -> dict:
    ATTACH_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name or "fichier")[:120] or "fichier"
    dest = ATTACH_DIR / f"{int(time.time())}-{safe}"
    dest.write_bytes(base64.b64decode(data_b64))
    mt = mime or mimetypes.guess_type(safe)[0] or "application/octet-stream"
    if mt == "application/octet-stream":
        mt = _mime_from_ext(safe)
    # Persistent archive: attachments sent by the user remain
    # disponibles pour que Mav puisse les renvoyer plus tard.
    archived = archive_media(dest, safe, mt, source="upload")
    return {
        "url": f"file://{dest}",
        "mime": mt,
        "filename": safe,
        "media_id": archived.get("id") if archived else None,
        "media_path": archived.get("path") if archived else None,
    }


# Sessions the user asked to stop (interrupt-and-reprocess): stream_answer
# aborts the engine as soon as it notices. A session id stays here only while
# its stream is winding down; the flag is consumed on the next answer.
INTERRUPTED: set[str] = set()


def request_interrupt(sid: str) -> bool:
    if not sid:
        return False
    INTERRUPTED.add(sid)
    return True


# --------------------------------------------------------------- media
# PERSISTENT media folder (survives reboots, unlike /tmp) + JSON index.
# Used to: (1) archive received attachments, (2) keep generated images,
# (3) let Mav resend any file by its id.
MEDIA_DIR = Path(os.environ.get("MAV_MEDIA", BOT_DIR / "mav-media"))
MEDIA_INDEX = MEDIA_DIR / "index.json"


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


def sync_media_dir() -> int:
    """Archive images present in /tmp/mav-dashboard that are not archived
    yet. Called before displaying media, so any generated image
    (Puppeteer screenshot, chart…) is persisted automatically."""
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


# --------------------------------------------------------------- assets
# Lets Mav send images in the chat. We serve an image file
# local via /api/asset?path=..., en n'autorisant que des images et une liste
# de racines, pour ne jamais exposer un fichier arbitraire.
ASSET_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".avif"}


def _asset_roots() -> list[Path]:
    roots = [MEDIA_DIR, ATTACH_DIR, Path("/tmp/mav-dashboard"), Path("/tmp/opencode")]
    if BOT_DIR.exists():
        roots.append(Path(BOT_DIR).resolve())
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


# ------------------------------------------------------------------- charts
# Small Yahoo Finance proxy so the dashboard can draw sparkline charts without
# a browser CORS problem and without exposing an API key. A one-entry cache
# keeps a redraw (or a re-render on scroll) from hammering the upstream.

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


def resolve_download(name: str) -> "Path | None":
    """Resolve a downloadable file, tolerating a bare filename.

    An absolute path is used as-is (within an allowed root); a bare name is
    searched in the media archive, the attachments folder and the allowed
    roots so `[[file:rapport.md]]` works right after a file was produced.
    """
    name = urllib.parse.unquote(str(name or "")).strip()
    if not name:
        return None
    if name.startswith("file://"):
        name = name[len("file://"):]
    roots = _asset_roots()

    def allowed(p: Path) -> bool:
        if p.suffix.lower() not in DOWNLOAD_EXT or not p.is_file():
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
    search_dirs = [MEDIA_DIR, ATTACH_DIR, Path("/tmp/mav-dashboard"), Path("/tmp/opencode")]
    for d in search_dirs:
        cand = d / name
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


def ensure_session(sid: str = "", agent: str = "") -> str:
    if sid:
        return sid
    sessions = list_sessions()
    if sessions:
        return sessions[0]["id"]
    return create_session(agent=agent)["id"]


def abort_session(sid: str) -> None:
    try:
        http_json(f"{OPENCODE_URL}/session/{sid}/abort", method="POST")
    except Exception:
        pass


def interrupt_session(sid: str) -> dict:
    """Stop the current answer and let a queued message take over.

    Marks the session so the running stream aborts the engine itself (and does
    not remember the partial answer), then aborts immediately for responsiveness.
    """
    if not sid:
        return {"ok": False, "error": "missing id"}
    request_interrupt(sid)
    abort_session(sid)
    return {"ok": True}


_agents_cache: dict = {"at": 0.0, "names": set()}


def valid_agents() -> set:
    """Agent names actually recognized by the engine (60 s cache)."""
    now = time.time()
    if now - _agents_cache["at"] < 60 and _agents_cache["names"]:
        return _agents_cache["names"]
    names: set = set()
    try:
        data = http_json(f"{OPENCODE_URL}/agent", timeout=8) or []
        if isinstance(data, list):
            names = {a.get("name") for a in data if a.get("name")}
        elif isinstance(data, dict):
            names = set(data.keys())
    except Exception:
        pass
    if names:
        _agents_cache["at"] = now
        _agents_cache["names"] = names
    return names or _agents_cache["names"]


def stream_answer(
    prompt: str,
    sid: str,
    agent: str = "",
    files: list | None = None,
    raw_session: bool = False,
    with_memory: bool = False,
):
    """SSE answer, collected server-side: reliable and reasoning-free.

    We let the engine run the request, then poll the session messages until
    we get a finished assistant message. Only "text" parts are sent: tool
    steps and internal reasoning never appear. The end is detected on the
    `finish` field
    du message, pas sur un signal de flux qui peut se perdre.
    """
    sid = sid if raw_session else ensure_session(sid, agent)
    # Consume any stale interrupt mark so it cannot kill this new answer.
    if not raw_session:
        INTERRUPTED.discard(sid)
    body: dict = {"parts": _parts(prompt, files or [])}
    meta = {} if raw_session else session_meta(sid)
    # Explicit choice > the conversation's agent > the configured default.
    ag = agent or meta.get("agent") or DEFAULT_AGENT
    if not raw_session and agent and agent != meta.get("agent"):
        set_session_meta(sid, agent=agent)

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    if ag:
        known = valid_agents()
        if known and ag not in known:
            if agent and agent != DEFAULT_AGENT:
                yield sse("error", {"message": f"Unknown helper: {ag}. Restart the assistant if you just created it.", "session": sid})
                return
            ag = ""  # the default helper is not installed: let the engine pick
    if ag:
        body["agent"] = ag
    body.update(_model_body())

    # Instant keyword title while the real one is generated after the answer.
    needs_title = False
    if not raw_session and prompt.strip():
        try:
            current = session_title(sid)[len(PREFIX):]
            if current in LEGACY_TITLES:
                rename_session(sid, quick_title(prompt))
                needs_title = True
            elif not meta.get("titled") and not meta.get("title_locked"):
                needs_title = True
        except Exception:
            pass

    # Start marker: any message older than our prompt is ignored.
    try:
        before = http_json(f"{OPENCODE_URL}/session/{sid}/message", timeout=12) or []
    except Exception:
        before = []
    before_ids = {(e.get("info") or {}).get("id") for e in before}

    # Memory: injected at the start of a conversation only (afterwards the
    # conversation itself is the context). Synthetic, so it is not displayed.
    recalled = 0
    if (not raw_session and not before) or with_memory:
        ctx = memory_context(prompt)
        if ctx:
            recalled = ctx.count("] Q:") + ctx.count("\n- ")
            body["parts"].insert(0, {"type": "text", "text": ctx, "synthetic": True})

    try:
        http_json(f"{OPENCODE_URL}/session/{sid}/prompt_async", method="POST", body=body)
    except Exception as exc:  # noqa: BLE001
        yield sse("error", {"message": f"Could not start: {exc}", "session": sid})
        return

    yield sse("start", {"session": sid, "agent": ag, "recalled": recalled})

    deadline = time.time() + 900      # garde-fou global (15 min)
    idle_limit = 240                  # no real progress (4 min)
    last_progress = time.time()
    last_sig = None
    last_text = ""
    last_sent = ""
    accepted = False
    finished_text = None
    engine_error = None
    tools_state: dict = {}
    interrupted = False

    while time.time() < deadline and time.time() - last_progress < idle_limit:
        # Stop requested from another request (interrupt-and-reprocess): abort
        # the engine, keep whatever text we already have.
        if sid in INTERRUPTED:
            INTERRUPTED.discard(sid)
            interrupted = True
            try:
                http_json(f"{OPENCODE_URL}/session/{sid}/abort", method="POST", timeout=8)
            except Exception:  # noqa: BLE001
                pass
            break

        time.sleep(0.4)
        try:
            entries = http_json(f"{OPENCODE_URL}/session/{sid}/message", timeout=12) or []
        except Exception:
            continue
        if not entries:
            continue

        new_assistant = [
            e for e in entries
            if (e.get("info") or {}).get("id") not in before_ids
            and (e.get("info") or {}).get("role") == "assistant"
        ]
        if not new_assistant:
            continue
        accepted = True

        # Visible answer only: "text" parts, never reasoning.
        text = "\n\n".join(_part_text(e.get("parts") or []) for e in new_assistant).strip()

        last = new_assistant[-1]
        linfo = last.get("info") or {}
        # Progress signature: message count, finish state, visible answer
        # length, and current tool state (running/completed).
        tool_sig = tuple(
            (p.get("id"), (p.get("state") or {}).get("status"))
            for e in new_assistant
            for p in (e.get("parts") or [])
            if p.get("type") == "tool"
        )
        sig = (len(new_assistant), linfo.get("finish"), len(text), tool_sig)
        if sig != last_sig:
            last_sig = sig
            last_progress = time.time()

        # Surface tool/MCP activity so the web app can show it live.
        for e in new_assistant:
            for part in (e.get("parts") or []):
                if part.get("type") != "tool":
                    continue
                key = part.get("callID") or part.get("id")
                status = (part.get("state") or {}).get("status") or "running"
                if key and tools_state.get(key) != status:
                    tools_state[key] = status
                    yield sse("tool", {"name": part.get("tool") or "tool", "status": status})

        if text != last_text:
            last_text = text
            delta = text[len(last_sent):] if text.startswith(last_sent) else text
            last_sent = text
            if delta:
                yield sse("delta", {"delta": delta})

        if linfo.get("error"):
            err = linfo.get("error") or {}
            engine_error = (
                (err.get("data") or {}).get("message") or err.get("name") or "engine error"
            )

        last_has_text = bool(_part_text(last.get("parts") or []))
        finish = linfo.get("finish")
        # "tool-calls" = the model continues with tools; "None" = in progress.
        # Any other finish ("stop", "length", "error"…) is terminal.
        if finish is not None and finish != "tool-calls":
            finished_text = text or last_text
            break
        # Terminal error with no usable answer.
        if engine_error and finish is not None and not last_has_text:
            break

    # Interrupted on purpose: whatever text was shown stays, but this is not a
    # finished exchange, so it is not remembered as the answer.
    if interrupted:
        yield sse("done", {"session": sid, "text": last_text, "agent": ag, "interrupted": True})
        return
    if not accepted and not finished_text:
        yield sse("error", {"message": "The request could not be started.", "session": sid})
        return
    if engine_error and not finished_text:
        yield sse("error", {"message": str(engine_error), "session": sid})
        return

    final = finished_text or last_text
    yield sse("done", {"session": sid, "text": final, "agent": ag})

    if not raw_session and final:
        threading.Thread(
            target=remember_exchange, args=(prompt, final, sid, ag), daemon=True
        ).start()
        threading.Thread(target=learn_facts, args=(prompt,), daemon=True).start()
        if needs_title:
            threading.Thread(
                target=generate_title, args=(sid, prompt, final), daemon=True
            ).start()


def ask(
    prompt: str,
    agent: str = "",
    sid: str = "",
    files: list | None = None,
    raw_session: bool = False,
    with_memory: bool = False,
) -> str:
    """Blocking version (routines, summaries, fallback)."""
    last = ""
    for chunk in stream_answer(prompt, sid, agent, files, raw_session=raw_session, with_memory=with_memory):
        if not chunk.startswith("event: delta"):
            if chunk.startswith("event: done"):
                try:
                    return json.loads(chunk.split("data: ", 1)[1]).get("text") or last
                except Exception:
                    return last
            if chunk.startswith("event: error"):
                try:
                    return f"Error: {json.loads(chunk.split('data: ', 1)[1]).get('message')}"
                except Exception:
                    return "Engine error."
            continue
        try:
            last += json.loads(chunk.split("data: ", 1)[1]).get("delta", "")
        except Exception:
            pass
    return last


# ------------------------------------------------------------------- push

_vapid_lock = threading.Lock()


def _vapid_keys() -> tuple[str, str]:
    """Return (private_key_pem, public_key_b64url). Create them on demand."""
    key_file = BOT_DIR / "vapid_private.pem"
    pub_file = BOT_DIR / "vapid_public.txt"
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
    subs = read_json(PUSH_FILE, [])
    if not isinstance(subs, list):
        subs = []
    endpoint = sub.get("endpoint")
    if not endpoint:
        return False
    subs = [s for s in subs if s.get("endpoint") != endpoint]
    subs.append(sub)
    write_json(PUSH_FILE, subs)
    return True


def push_unsubscribe(endpoint: str) -> bool:
    subs = read_json(PUSH_FILE, [])
    subs = [s for s in subs if s.get("endpoint") != endpoint]
    write_json(PUSH_FILE, subs)
    return True


def send_push(title: str, body: str, url: str = "./") -> int:
    try:
        from py_vapid import Vapid01
        from pywebpush import webpush, WebPushException
    except Exception:
        return 0
    if not PUSH_FILE.exists():
        return 0
    try:
        pem, _ = _vapid_keys()
        vapid = Vapid01.from_pem(pem.encode())
    except Exception:
        return 0
    subs = read_json(PUSH_FILE, [])
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
    write_json(PUSH_FILE, alive)
    return sent


# Watch and notification pushing are handled by the worker
# (`~/bot/ocnotify.py` + `ocwatch.py`), with dedup and quiet hours.
# The dashboard only provides VAPID keys, stores subscriptions and
# exposes the history (`/api/notifications`).


# ------------------------------------------------------------------- server


class ThreadedHTTPServer(ThreadingHTTPServer):
    """HTTP/1.1 server with keep-alive and a large listen backlog.

    By default http.server stays on HTTP/1.0 (one connection per request) and
    accepts only 5 pending connections — on a cold load, a browser opens
    several in parallel and can get refused/timed out. So we enable keep-alive
    and widen the backlog.
    """

    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128
    protocol_version = "HTTP/1.1"


class Handler(BaseHTTPRequestHandler):
    server_version = "mav-api/0.2"
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code: int, payload, ctype="application/json"):
        if isinstance(payload, (dict, list)):
            data = json.dumps(payload, ensure_ascii=False, default=_json_default).encode()
        else:
            data = payload if isinstance(payload, bytes) else str(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _sse_open(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def _params(self) -> dict:
        _, _, query = self.path.partition("?")
        out = {}
        if query:
            for pair in query.split("&"):
                k, _, v = pair.partition("=")
                out[k] = urllib.parse.unquote_plus(v)
        return out

    def do_GET(self):
        path, _, _ = self.path.partition("?")
        p = self._params()
        try:
            if path == "/api/status":
                return self._send(200, get_status())
            if path == "/api/jobs":
                return self._send(200, get_jobs())
            if path == "/api/job-results":
                return self._send(200, get_job_results())
            if path == "/api/memory":
                return self._send(200, get_memory())
            if path == "/api/watch":
                return self._send(200, get_watch())
            if path == "/api/notifications":
                return self._send(200, get_notifications())
            if path == "/api/notification":
                return self._send(200, get_notification(int(p.get("id", 0) or 0)))
            if path == "/api/debates":
                return self._send(200, get_debates())
            if path == "/api/debate":
                return self._send(200, get_debate(p.get("id", "")))
            if path == "/api/agents":
                return self._send(200, get_agents())
            if path == "/api/connections":
                return self._send(200, {"connections": get_connections()})
            if path == "/api/health":
                return self._send(200, {"ok": True, "ts": int(time.time())})
            if path == "/api/config":
                return self._send(200, config_snapshot())
            if path == "/api/config/agents":
                return self._send(200, read_agents())
            if path == "/api/config/mcp":
                return self._send(200, read_mcp())
            if path == "/api/config/engine":
                return self._send(200, engine_status())
            if path == "/api/config/provider":
                return self._send(200, provider_snapshot())
            if path == "/api/config/mcp/catalog":
                return self._send(200, mcp_catalog())
            if path == "/api/config/mcp/status":
                return self._send(200, {"status": mcp_status()})
            if path == "/api/version":
                return self._send(200, version_info(p.get("refresh") == "1"))
            if path == "/api/update/status":
                return self._send(200, update_status())
            if path == "/api/config/agent-files":
                return self._send(200, list_agent_files())
            if path == "/api/config/agent-file":
                return self._send(200, read_agent_file(p.get("name", "")))
            if path == "/api/sessions":
                return self._send(200, {"sessions": list_sessions()})
            if path == "/api/session":
                sid = p.get("id", "")
                if not sid:
                    return self._send(400, {"error": "missing id"})
                return self._send(200, {
                    "id": sid,
                    "title": session_title(sid)[len(PREFIX):],
                    "agent": session_meta(sid).get("agent", ""),
                    "messages": session_messages(sid),
                })
            if path == "/api/session/export":
                sid = p.get("id", "")
                md = export_session_markdown(sid)
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="mav-conversation.md"')
                data = md.encode()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/api/search":
                return self._send(200, global_search(p.get("q", "")))
            if path == "/api/push/key":
                return self._send(200, {"key": push_public_key()})
            if path == "/api/asset":
                res = serve_asset(p.get("path", ""))
                if not res:
                    return self._send(404, "asset not found", "text/plain")
                data, mime = res
                return self._send(200, data, mime)
            if path == "/api/chart":
                try:
                    return self._send(200, chart_data(p.get("symbol", ""), p.get("range", "1mo")))
                except Exception:
                    return self._send(404, {"error": "chart unavailable"})
            if path == "/api/download":
                res = download_response(p.get("path", ""))
                if not res:
                    return self._send(404, "file not found", "text/plain")
                data, mime, fname = res
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header(
                    "Content-Disposition",
                    'attachment; filename="' + fname.replace('"', "") + '"',
                )
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/api/media":
                sync_media_dir()
                return self._send(200, list_media())
            if path == "/api/media/find":
                sync_media_dir()
                return self._send(200, {"media": find_media(p.get("q", ""))})
            if path == "/api/media/get":
                mid = p.get("id", "")
                hit = next((i for i in _media_load() if i.get("id") == mid), None)
                if not hit:
                    return self._send(404, "media not found", "text/plain")
                res = serve_asset(hit["path"])
                if not res:
                    return self._send(404, "media not found", "text/plain")
                data, mime = res
                return self._send(200, data, mime)
            if path == "/api/media/by-name":
                name = p.get("name", "")
                hits = find_media(name)
                if not hits:
                    return self._send(404, "media not found", "text/plain")
                res = serve_asset(hits[0]["path"])
                if not res:
                    return self._send(404, "media not found", "text/plain")
                data, mime = res
                return self._send(200, data, mime)
            if path == "/api/stream":
                return self._stream(p)
            return self._static(path)
        except Exception as exc:  # noqa: BLE001
            return self._send(500, {"error": str(exc)})

    def _stream(self, p: dict):
        prompt = p.get("prompt", "").strip()
        if not prompt:
            return self._send(400, {"error": "missing prompt"})
        files = []
        if p.get("files"):
            try:
                raw = json.loads(p["files"])
                for item in raw:
                    if isinstance(item, str):
                        files.append(_guess_file({"url": item}))
                    elif isinstance(item, dict):
                        files.append(_guess_file(item))
            except Exception:
                pass
        self._sse_open()
        try:
            for chunk in stream_answer(prompt, p.get("session", ""), p.get("agent", ""), files):
                self.wfile.write(chunk.encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001
            try:
                self.wfile.write(f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n".encode())
            except Exception:
                pass

    def do_POST(self):
        path, _, _ = self.path.partition("?")
        payload = self._body()
        try:
            if path == "/api/ask":
                prompt = (payload.get("prompt") or "").strip()
                if not prompt:
                    return self._send(400, {"error": "missing prompt"})
                return self._send(200, {"answer": ask(prompt, payload.get("agent", ""), payload.get("session", ""), payload.get("files"))})
            if path == "/api/session/new":
                return self._send(200, create_session(payload.get("title", ""), payload.get("agent", "")))
            if path == "/api/session/rename":
                ok = rename_session(payload.get("id", ""), payload.get("title", ""))
                if ok:  # a title chosen by the user is never auto-replaced
                    set_session_meta(payload.get("id", ""), title_locked=True, titled=True)
                return self._send(200 if ok else 400, {"ok": ok})
            if path == "/api/session/agent":
                set_session_meta(payload.get("id", ""), agent=(payload.get("agent") or "").strip())
                return self._send(200, {"ok": True})
            if path == "/api/session/pin":
                set_session_meta(payload.get("id", ""), pinned=bool(payload.get("pinned")))
                return self._send(200, {"ok": True})
            if path == "/api/session/delete":
                ok = delete_session(payload.get("id", ""))
                return self._send(200 if ok else 400, {"ok": ok})
            if path == "/api/session/abort":
                abort_session(payload.get("id", ""))
                return self._send(200, {"ok": True})
            if path == "/api/session/interrupt":
                return self._send(200, interrupt_session(payload.get("id", "")))
            if path == "/api/session/summary":
                sid = payload.get("id", "")
                s = ask("Summarize this conversation in a few key points.", "summary", sid, raw_session=True)
                return self._send(200, {"summary": s})
            if path == "/api/job/toggle":
                ok = set_job_enabled(payload.get("name", ""), bool(payload.get("enabled")))
                return self._send(200 if ok else 404, {"ok": ok})
            if path == "/api/job/run":
                res = run_job_now(payload.get("name", ""))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/job/save":
                res = save_job(payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/job/delete":
                ok = delete_job(payload.get("name", ""))
                return self._send(200 if ok else 404, {"ok": ok})
            if path.startswith("/api/memory/"):
                res = memory_action(path[len("/api/memory/"):], payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/config/provider":
                res = provider_save(payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/config/provider/test":
                return self._send(200, provider_test(payload))
            if path == "/api/config/mcp/install":
                res = install_from_catalog(payload.get("id", ""), payload.get("values") or {})
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/config/mcp/oauth/start":
                res = mcp_oauth_start(payload.get("name", ""))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/config/mcp/oauth/callback":
                res = mcp_oauth_callback(payload.get("name", ""), payload.get("code", ""))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/config/mcp/oauth/remove":
                res = mcp_oauth_remove(payload.get("name", ""))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/update":
                res = start_update()
                return self._send(200 if res.get("ok") else 500, res)
            if path == "/api/watch/add":
                ok = watch_add(payload.get("kind", ""), payload.get("target", ""))
                return self._send(200 if ok else 400, {"ok": ok})
            if path == "/api/watch/remove":
                ok = watch_remove(int(payload.get("id", 0)))
                return self._send(200, {"ok": ok})
            if path == "/api/upload":
                f = save_upload(payload.get("name", "fichier"), payload.get("data", ""), payload.get("mime", ""))
                return self._send(200, f)
            if path == "/api/push/subscribe":
                # Record the device for diagnostics (headless vs real phone).
                try:
                    payload["_ua"] = self.headers.get("User-Agent", "")[:200]
                except Exception:
                    pass
                ok = push_subscribe(payload)
                return self._send(200, {"ok": ok})
            if path == "/api/push/unsubscribe":
                ok = push_unsubscribe(payload.get("endpoint", ""))
                return self._send(200, {"ok": ok})
            if path == "/api/push/test":
                n = send_push("Mav", "This is a test notification.")
                return self._send(200, {"sent": n})
            if path == "/api/push/ack":
                # Service worker acknowledgement: proves the push actually
                # reached the device (delivery diagnostics).
                try:
                    pg_exec(
                        "insert into notifications (ts, chat_id, topic, title, body, channels, delivered) "
                        "values (%s, %s, %s, %s, %s, %s, %s)",
                        (int(time.time()), None, "push_ack",
                         str(payload.get("title", ""))[:200],
                         str(payload.get("body", ""))[:500],
                         ["ack"], True),
                    )
                except Exception:
                    pass
                return self._send(200, {"ok": True})
            if path == "/api/config/agents":
                text = payload.get("text")
                if not isinstance(text, str):
                    return self._send(400, {"error": "text required"})
                res = write_agents(text)
                return self._send(200 if res.get("ok") else 500, res)
            if path == "/api/config/mcp":
                res = write_mcp(payload.get("mcp"))
                return self._send(200 if res.get("ok") else 500, res)
            if path == "/api/config/restart":
                res = restart_engine()
                return self._send(200, res)
            if path == "/api/config/agent-file":
                res = write_agent_file(
                    (payload.get("name") or "").strip(),
                    payload.get("text", ""),
                )
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/config/agent-file/delete":
                res = delete_agent_file((payload.get("name") or "").strip())
                return self._send(200 if res.get("ok") else 400, res)
            return self._send(404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001
            return self._send(500, {"error": str(exc)})

    def _static(self, path: str):
        if path == "/":
            path = "/index.html"
        rel = path.lstrip("/").replace("..", "")
        if rel.endswith((".key", ".csr", ".srl")):
            return self._send(404, "not found", "text/plain")
        if rel.startswith("certs/") and rel not in ("certs/ca.crt", "certs/ca.cer"):
            return self._send(404, "not found", "text/plain")
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            return self._send(404, "not found", "text/plain")
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".webmanifest": "application/manifest+json",
            ".json": "application/json",
            ".ico": "image/x-icon",
            ".crt": "application/x-x509-ca-cert",
            ".cer": "application/x-x509-ca-cert",
            ".pem": "application/x-pem-file",
        }.get(target.suffix, "application/octet-stream")
        return self._send(200, target.read_bytes(), ctype)


def ensure_schema() -> None:
    """Columns added after the first release (idempotent, silent without PG)."""
    try:
        pg_exec(
            "CREATE TABLE IF NOT EXISTS notifications (id bigserial PRIMARY KEY, ts bigint NOT NULL, "
            "chat_id bigint, topic text, title text, body text, dedup_key text, channels text[], "
            "delivered boolean DEFAULT true)"
        )
        pg_exec("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS link text")
    except Exception:  # noqa: BLE001
        pass


def main():
    import ssl

    ensure_schema()

    srv = ThreadedHTTPServer((BIND, PORT), Handler)
    print(f"mav-api listening on http://{BIND}:{PORT} (static: {STATIC_DIR})", flush=True)

    if TLS_PORT and TLS_CERT and TLS_KEY:
        try:
            tsrv = ThreadedHTTPServer((BIND, TLS_PORT), Handler)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(TLS_CERT, TLS_KEY)
            tsrv.socket = ctx.wrap_socket(tsrv.socket, server_side=True)
            threading.Thread(target=tsrv.serve_forever, daemon=True).start()
            print(f"mav-api listening on https://{BIND}:{TLS_PORT}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"TLS unavailable: {exc}", flush=True)

    srv.serve_forever()


if __name__ == "__main__":
    main()
