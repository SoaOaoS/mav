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

# Proactivity modules (shared with the worker): drafts proposed by Mav and the
# pure routine/condition helpers. All optional — the dashboard still works if
# only part of the package is present.
try:
    from ocdrafts import Drafts  # noqa: E402

    DRAFTS = Drafts(BOT_DIR / "drafts.json")
except Exception:  # noqa: BLE001
    DRAFTS = None
try:
    from ocactions import Actions  # noqa: E402

    ACTIONS = Actions(BOT_DIR / "actions.json")
except Exception:  # noqa: BLE001
    ACTIONS = None
try:
    import ocroutine_templates  # noqa: E402
    import ocroutine_nl  # noqa: E402

    ROUTINE_TEMPLATES = ocroutine_templates.TEMPLATES
except Exception:  # noqa: BLE001
    ocroutine_templates = None
    ocroutine_nl = None
    ROUTINE_TEMPLATES = []

# Interests: what the user cares about, and the watchdog routines Mav spawns
# from them. Optional, like the rest.
try:
    from ocinterests import Interests, CADENCES, CADENCE_DAYS, CATEGORIES, POLARITIES  # noqa: E402

    INTERESTS = Interests(BOT_DIR / "interests.json", chat_id=DEFAULT_CHAT_ID)
except Exception:  # noqa: BLE001
    INTERESTS = None
    CADENCES, CADENCE_DAYS, CATEGORIES, POLARITIES = (
        ("off", "weekly", "biweekly", "monthly", "quarterly"), {}, (), ("like", "dislike"))
try:
    import ocselfinit  # noqa: E402
except Exception:  # noqa: BLE001
    ocselfinit = None

import mav_auth  # noqa: E402

try:
    import ocbriefing  # noqa: E402
except Exception:  # noqa: BLE001
    ocbriefing = None

try:
    import ocusage  # noqa: E402

    USAGE = ocusage.Usage(BOT_DIR / "usage.json")
except Exception:  # noqa: BLE001
    ocusage = None
    USAGE = None


def record_usage(source: str, entries: list) -> None:
    """Add an answer's tokens/cost, and warn once at 80 % / 100 % of budget."""
    if USAGE is None:
        return
    try:
        USAGE.record_entries(source, entries)
        level = USAGE.alert_due()
    except Exception:  # noqa: BLE001
        return
    if level:
        b = USAGE.budget()
        title = "💸 Budget reached" if level >= 100 else "💸 80 % of your budget used"
        body = (f"${USAGE.month_cost():.2f} of ${b['monthly_usd']:.2f} this month."
                + (" New answers are paused until you raise it." if level >= 100 and b["action"] == "stop" else ""))
        try:
            record_notification("usage", title, body, "./#settings/usage")
            send_push(title, body, "./#settings/usage")
        except Exception:  # noqa: BLE001
            pass


def budget_blocked() -> bool:
    try:
        return bool(USAGE and USAGE.blocked())
    except Exception:  # noqa: BLE001
        return False
import mav_provider  # noqa: E402

# Sign-in (one owner password). MAV_AUTH=off disables it, e.g. behind your own
# authenticating proxy.
AUTH = mav_auth.Auth(
    Path(os.environ.get("MAV_AUTH_FILE", BOT_DIR / "auth.json")),
    enabled=os.environ.get("MAV_AUTH", "on").lower() not in ("off", "0", "false", "no"),
)

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
        "mav_version": installed_version(),
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
                "days_of_month": j.get("days_of_month", []),
                "last_day_of_month": bool(j.get("last_day_of_month")),
                "on_event": j.get("on_event"),
                "skip_if": j.get("skip_if"),
                "snooze_until": j.get("snooze_until", 0),
                "last_run": state.get(j.get("name")),
                "running": j.get("name") in _running_jobs,
                "session": chats.get(j.get("name")),
            }
        )
    return {"jobs": out}


JOB_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,60}$")
JOB_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def delete_job(name: str) -> bool:
    jobs = read_json(JOBS_FILE, [])
    keep = [j for j in jobs if j.get("name") != name]
    if len(keep) == len(jobs):
        return False
    write_json(JOBS_FILE, keep)
    return True


# ----------------------------------------------------------- proactivity
# Layers added on top of simple time-based routines: richer schedules (monthly,
# every-N-weeks), events/webhooks, conditions ("only if…"), ready-made
# templates, plus the drafts and background actions Mav produces on its own.

def _schedule_from_payload(payload: dict) -> dict:
    """Translate the web form's schedule fields into jobs.json keys."""
    every = payload.get("every_minutes")
    try:
        every = int(every) if every not in (None, "", 0, "0") else 0
    except (TypeError, ValueError):
        every = -1  # sentinel: invalid
    out: dict = {"every_minutes": every}
    if every < 0:
        return out
    if every:
        return out
    out["every_minutes"] = 0
    time_ = str(payload.get("time") or "").strip()
    if time_:
        out["time"] = time_
    mode = str(payload.get("schedule_mode") or "").strip().lower()
    if mode == "monthly":
        dom = payload.get("days_of_month") or []
        if isinstance(dom, str):
            dom = [d for d in re.split(r"[,\s]+", dom) if d]
        dom = [int(d) for d in dom if str(d).strip().isdigit()]
        last = bool(payload.get("last_day_of_month"))
        if not dom and not last:
            return {**out, "_error": "Choisis un jour du mois (ou le dernier jour)."}
        if dom:
            out["days_of_month"] = dom
        if last:
            out["last_day_of_month"] = True
        return out
    if mode == "event":
        kind = str(payload.get("event_kind") or "custom").strip()
        ev: dict = {"kind": kind}
        needle = str(payload.get("event_contains") or "").strip()
        if needle:
            ev["contains"] = needle
        out["on_event"] = ev
        return out
    days = [d for d in (payload.get("days") or []) if d in JOB_DAYS]
    out["days"] = days or JOB_DAYS
    return out


def _condition_from_payload(payload: dict) -> dict | None:
    """Build a ``skip_if`` block, or None when there is no condition."""
    ctype = str(payload.get("condition_type") or "").strip().lower()
    if not ctype or ctype == "none":
        return None
    cond: dict = {"type": ctype}
    value = payload.get("condition_value")
    if value not in (None, ""):
        cond["value"] = value
    source = str(payload.get("condition_source") or "").strip()
    if source:
        cond["source"] = source
    negate = payload.get("condition_negate")
    if negate in (True, "true", "on", 1, "1"):
        cond["negate"] = True
    if ctype == "number":
        op = str(payload.get("condition_op") or ">=").strip()
        cond["op"] = op if op in (">", "<", ">=", "<=", "==", "!=") else ">="
    return cond


def save_job(payload: dict) -> dict:
    """Create or update a routine (`original` = name before a rename).

    Extends the simple form with: monthly schedules, event triggers, a
    condition (`skip_if`) and snooze (`snooze_until`, an epoch second).
    """
    name = str(payload.get("name") or "").strip()
    if not JOB_NAME_RE.match(name):
        return {"ok": False, "error": "Give the automation a name (letters, digits, - _ .)."}
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        return {"ok": False, "error": "Write what Mav should do."}

    sched = _schedule_from_payload(payload)
    if sched.pop("_error", None):
        return {"ok": False, "error": sched.pop("_error", "Invalid schedule.")}
    if not sched.get("every_minutes") and not sched.get("on_event"):
        # A timed job needs a valid time; an event job does not.
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", str(sched.get("time") or "")):
            return {"ok": False, "error": "Pick a time (HH:MM), an interval, or an event."}

    job = {
        "name": name,
        "description": str(payload.get("description") or "").strip()[:200],
        "prompt": prompt,
        "agent": str(payload.get("agent") or "").strip(),
        "enabled": bool(payload.get("enabled", True)),
        **sched,
    }
    cond = _condition_from_payload(payload)
    if cond:
        job["skip_if"] = cond
    try:
        snooze = int(payload.get("snooze_until") or 0)
    except (TypeError, ValueError):
        snooze = 0
    if snooze > int(time.time()):
        job["snooze_until"] = snooze

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
            keep = {k: v for k, v in j.items() if k not in (
                "time", "every_minutes", "days", "days_of_month",
                "last_day_of_month", "on_event", "skip_if", "snooze_until",
            )}
            jobs[i] = {**keep, **job}
            replaced = True
            break
    if not replaced:
        jobs.append(job)
    write_json(JOBS_FILE, jobs)
    _chown_user(JOBS_FILE)
    return {"ok": True, "job": job}


def job_templates() -> dict:
    """Ready-made routines for the dashboard's two-click creation."""
    return {"templates": ROUTINE_TEMPLATES}


def template_to_job(template_id: str, *, name: str = "") -> dict:
    """Expand a template into a concrete job (not saved here)."""
    if not ocroutine_templates:
        return {"ok": False, "error": "Templates unavailable."}
    tpl = ocroutine_templates.get(template_id)
    if not tpl:
        return {"ok": False, "error": "Unknown template."}
    when = dict(tpl.get("when") or {})
    job = {
        "name": (name or tpl["label"])[:61].strip(),
        "description": tpl.get("description", "")[:200],
        "prompt": tpl["prompt"],
        "agent": tpl.get("agent", ""),
        "enabled": True,
    }
    job.update(when)
    if tpl.get("skip_if"):
        job["skip_if"] = dict(tpl["skip_if"])
    return {"ok": True, "job": job}


def detect_routine(text: str) -> dict:
    """Turn a chat sentence into a routine draft (multilingual)."""
    if not ocroutine_nl:
        return {"draft": None}
    draft = ocroutine_nl.detect(text)
    return {"draft": draft}


def get_proactivity() -> dict:
    """The user's proactivity preference + what is waiting per level."""
    level = "normal"
    try:
        rows = pg_query("select value from preferences where key = 'notify.proactivity' limit 1")
        if rows and rows[0].get("value"):
            level = rows[0]["value"]
    except Exception:  # noqa: BLE001
        pass
    counts = {"pending": 0, "low": 0}
    try:
        counts["pending"] = len(pg_query(
            "select 1 from notify_digest where not sent"
        ))
        counts["low"] = counts["pending"]
    except Exception:  # noqa: BLE001
        pass
    drafts = len(DRAFTS.list("pending", limit=200)) if DRAFTS else 0
    actions = ACTIONS.list("running", limit=200) if ACTIONS else []
    return {"level": level, "digest_pending": counts["pending"],
            "drafts_pending": drafts, "actions_running": len(actions)}


def set_proactivity(level: str) -> dict:
    level = (level or "normal").strip().lower()
    if level not in ("quiet", "normal", "chatty"):
        return {"ok": False, "error": "Level must be quiet, normal or chatty."}
    try:
        pg_exec(
            "insert into preferences (chat_id, key, value, ts) values (%s, 'notify.proactivity', %s, %s) "
            "on conflict (chat_id, key) do update set value = excluded.value, ts = excluded.ts",
            (DEFAULT_CHAT_ID, level, int(time.time())),
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}
    return {"ok": True, "level": level}


def snooze_job(name: str, until: int) -> bool:
    jobs = read_json(JOBS_FILE, [])
    found = False
    for j in jobs:
        if j.get("name") == name:
            if until > 0:
                j["snooze_until"] = until
            else:
                j.pop("snooze_until", None)
            found = True
    if found:
        write_json(JOBS_FILE, jobs)
    return found



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
    in the routine's chat, with memory, then a push + an inbox entry.

    It runs as a live answer (the run registry), so opening the routine's chat
    shows it being written instead of an empty chat."""
    job = next((j for j in read_json(JOBS_FILE, []) if j.get("name") == name), None)
    if not job:
        return {"ok": False, "error": "Unknown routine."}
    if name in _running_jobs:
        return {"ok": False, "error": "Already running."}
    agent = job.get("agent", "") or DEFAULT_AGENT
    sid = routine_session(name, agent)
    briefing = ocbriefing is not None and ocbriefing.is_briefing(job)
    context = briefing_context() if briefing else ""
    run = start_run(job.get("prompt", ""), sid, agent, raw_session=True,
                    with_memory=True, context=context)

    def work():
        _running_jobs.add(name)
        try:
            if run._thread:
                run._thread.join(timeout=1000)
            text = run.text
            summary = " ".join(re.sub(r"[*_`#>|]+", "", text or "").split())
            if len(summary) > 220:
                summary = summary[:217] + "…"
            if summary and run.status == "done":
                link = f"./#chat/{sid}"
                title = "☀️ Your briefing" if briefing else f"🔁 {name}"
                record_notification("briefing" if briefing else "routine", title, summary, link)
                send_push(title, summary, link)
        except Exception:  # noqa: BLE001
            pass
        finally:
            _running_jobs.discard(name)

    threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "session": sid}


# ------------------------------------------------------------ daily briefing


def briefing_context() -> str:
    """Everything the briefing should know, as hidden context."""
    if ocbriefing is None:
        return ""
    facts, notes, drafts, interests = [], [], 0, []
    if MEMORY and MEMORY_ENABLED:
        try:
            facts = MEMORY.facts(DEFAULT_CHAT_ID, limit=30)
        except Exception:  # noqa: BLE001
            facts = []
    try:
        notes = get_notifications(40).get("notifications") or []
    except Exception:  # noqa: BLE001
        notes = []
    try:
        rows = pg_query("select count(*) as n from drafts where status = 'pending'")
        drafts = int(rows[0]["n"]) if rows else 0
    except Exception:  # noqa: BLE001
        drafts = 0
    if INTERESTS is not None:
        try:
            interests = INTERESTS.list(include_muted=False)
        except Exception:  # noqa: BLE001
            interests = []
    return ocbriefing.build_context(
        facts=facts, notifications=notes, drafts=drafts, interests=interests,
    )


def briefing_job() -> dict | None:
    jobs = read_json(JOBS_FILE, [])
    return next((j for j in jobs if isinstance(j, dict) and j.get("kind") == "briefing"), None)


def get_briefing() -> dict:
    job = briefing_job()
    return {
        "available": ocbriefing is not None,
        "exists": bool(job),
        "enabled": bool(job and job.get("enabled", True)),
        "time": (job or {}).get("time") or (ocbriefing.DEFAULT_TIME if ocbriefing else "07:30"),
        "name": (job or {}).get("name") or (ocbriefing.NAME if ocbriefing else "Daily briefing"),
    }


def set_briefing(enabled: bool, time_hm: str = "") -> dict:
    """Turn the daily briefing on/off and set its time (a regular routine)."""
    if ocbriefing is None:
        return {"ok": False, "error": "Briefing unavailable."}
    if time_hm and not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", time_hm):
        return {"ok": False, "error": "Pick a time like 07:30."}
    jobs = read_json(JOBS_FILE, [])
    if not isinstance(jobs, list):
        jobs = []
    job = next((j for j in jobs if isinstance(j, dict) and j.get("kind") == "briefing"), None)
    if job is None:
        if not enabled:
            return {"ok": True, **get_briefing()}
        job = ocbriefing.default_job(time_hm or ocbriefing.DEFAULT_TIME, DEFAULT_AGENT)
        jobs.append(job)
    job["enabled"] = bool(enabled)
    if time_hm:
        job["time"] = time_hm
    write_json(JOBS_FILE, jobs)
    _chown_user(JOBS_FILE)
    return {"ok": True, **get_briefing()}


def run_briefing_now() -> dict:
    """"Brief me now": runs the briefing routine (created switched off if the
    daily schedule was never turned on, so it has its own chat)."""
    if ocbriefing is None:
        return {"ok": False, "error": "Briefing unavailable."}
    job = briefing_job()
    if job is None:
        job = ocbriefing.default_job(agent=DEFAULT_AGENT)
        job["enabled"] = False
        jobs = read_json(JOBS_FILE, [])
        jobs = jobs if isinstance(jobs, list) else []
        jobs.append(job)
        write_json(JOBS_FILE, jobs)
        _chown_user(JOBS_FILE)
    return run_job_now(job["name"])


ACTION_PREFIX = "Action · "


def start_action(prompt: str, name: str = "", agent: str = "") -> dict:
    """Run a long task in the background and deliver its result later.

    Unlike a routine, an action is a one-off: it gets its own chat, is tracked
    in the `actions` table while it runs, and pushes the answer when done.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "error": "Give the action something to do."}
    title = (name or prompt)[:60].strip() or "Action"
    agent = agent or DEFAULT_AGENT
    sid = create_session(ACTION_PREFIX + title, agent)["id"]
    set_session_meta(sid, title_locked=True, titled=True, action=title)
    aid = ACTIONS.add(DEFAULT_CHAT_ID, title, "task", f"./#chat/{sid}") if ACTIONS else None

    def work():
        if ACTIONS and aid:
            ACTIONS.update(aid, "running")
        try:
            text = ask(prompt, agent, sid, raw_session=True, with_memory=True)
            failed = not text or text.startswith("Error:")
            if ACTIONS and aid:
                ACTIONS.update(aid, "failed" if failed else "done", result=text or "")
            if not failed:
                summary = " ".join(re.sub(r"[*_`#>|]+", "", text).split())
                if len(summary) > 220:
                    summary = summary[:217] + "…"
                record_notification("action", f"✅ {title}", summary, f"./#chat/{sid}")
                send_push(f"✅ {title}", summary, f"./#chat/{sid}")
        except Exception as exc:  # noqa: BLE001
            if ACTIONS and aid:
                ACTIONS.update(aid, "failed", result=str(exc)[:500])

    threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "id": aid, "session": sid}


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


def get_drafts(status: str = "pending") -> dict:
    status = status if status in ("pending", "sent", "discarded", "all") else "pending"
    items = DRAFTS.list(status, limit=100) if DRAFTS else []
    return {"drafts": items, "backend": DRAFTS.backend if DRAFTS else "none"}


def draft_action(action: str, payload: dict) -> dict:
    if not DRAFTS:
        return {"ok": False, "error": "Drafts unavailable."}
    if action == "status":
        return {"ok": DRAFTS.set_status(int(payload.get("id") or 0), str(payload.get("status") or "pending"))}
    if action == "delete":
        return {"ok": DRAFTS.delete(int(payload.get("id") or 0))}
    if action == "add":
        title = str(payload.get("title") or "").strip()
        body = str(payload.get("body") or "").strip()
        if not title or not body:
            return {"ok": False, "error": "Title and body required."}
        did = DRAFTS.add(
            DEFAULT_CHAT_ID,
            str(payload.get("kind") or "other"),
            title,
            body,
            "dashboard",
            to=str(payload.get("to") or ""),
            subject=str(payload.get("subject") or ""),
        )
        return {"ok": did is not None, "id": did}
    if action == "edit":
        did = int(payload.get("id") or 0)
        ok = DRAFTS.update(
            did,
            title=payload.get("title"),
            body=payload.get("body"),
            to=payload.get("to"),
            subject=payload.get("subject"),
        )
        return {"ok": ok}
    return {"ok": False, "error": "unknown action"}


def send_draft(draft_id: int) -> dict:
    """Send a draft as an email through the configured mail (Settings → Mail)."""
    d = DRAFTS.get(draft_id) if DRAFTS else None
    if not d:
        return {"ok": False, "error": "Unknown draft."}
    to = str(d.get("email_to") or "").strip()
    if not to:
        return {"ok": False, "error": "No recipient on this draft — add one in Edit."}
    try:
        import mav_mail  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Mail module unavailable: {str(exc)[:120]}"}
    res = mav_mail.send(
        to,
        d.get("email_subject") or d.get("title") or "",
        d.get("body") or "",
        in_reply_to=str(d.get("message_id") or ""),
    )
    if res.get("ok"):
        DRAFTS.set_status(draft_id, "sent")
    return res


def get_actions() -> dict:
    items = ACTIONS.list("all", limit=100) if ACTIONS else []
    return {"actions": items, "backend": ACTIONS.backend if ACTIONS else "none"}


def get_events(limit: int = 30) -> dict:
    try:
        from ocevents import recent  # noqa: PLC0415

        return {"events": recent(limit)}
    except Exception:  # noqa: BLE001
        return {"events": []}


def hook_event(kind: str, payload: dict, token: str = "") -> dict:
    """Record an incoming event and (best-effort) kick the worker."""
    try:
        from ocevents import ensure_schema, push  # noqa: PLC0415

        ensure_schema()
        # Optional shared-secret guard, configured in Settings → Proactivity.
        want = ""
        try:
            rows = pg_query("select value from preferences where key = 'hooks.token' limit 1")
            want = (rows[0].get("value") or "") if rows else ""
        except Exception:  # noqa: BLE001
            want = ""
        if want and token != want:
            return {"ok": False, "error": "bad token"}
        eid = push(kind, payload)
        return {"ok": eid is not None, "id": eid}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


def mail_config() -> dict:
    """Mail status (no password!) + providers to pre-fill the form."""
    try:
        import mav_mail  # noqa: PLC0415

        return mav_mail.status()
    except Exception as exc:  # noqa: BLE001
        return {"configured": False, "error": str(exc)[:200], "presets": []}


def mail_save(payload: dict) -> dict:
    try:
        import mav_mail  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}
    imap = str(payload.get("imap") or "").strip()
    smtp = str(payload.get("smtp") or "").strip()
    user = str(payload.get("user") or "").strip()
    password = str(payload.get("password") or "")
    if not (imap and smtp and user and password):
        # A blank password keeps the stored one (like the model provider form).
        cur = mav_mail.load()
        password = password or cur.get("MAIL_PASS", "")
        if not (imap and smtp and user and password):
            return {"ok": False, "error": "Fill in the servers, your address and the password."}
    mav_mail.save(imap, smtp, user, password)
    return {"ok": True}


def mail_reply_draft(payload: dict) -> dict:
    """File a threaded reply for a message UID — server-side, so it uses the
    dashboard's Postgres (the single writer) and the shared mail config."""
    uid = str(payload.get("uid") or "").strip()
    body = str(payload.get("body") or "").strip()
    if not uid or not body:
        return {"ok": False, "error": "uid and body required."}
    try:
        from ocmail import make_reply_draft  # noqa: PLC0415

        return make_reply_draft(uid, body, subject=str(payload.get("subject") or ""),
                                chat_id=DEFAULT_CHAT_ID)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:250]}


def mail_forget() -> dict:
    try:
        import mav_mail  # noqa: PLC0415

        mav_mail.forget()
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


def mail_test(payload: dict) -> dict:
    try:
        import mav_mail  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}
    cur = mav_mail.load()
    password = str(payload.get("password") or "") or cur.get("MAIL_PASS", "")
    res = mav_mail.test(
        str(payload.get("imap") or cur.get("MAIL_IMAP_SERVER") or "").strip(),
        str(payload.get("smtp") or cur.get("MAIL_SMTP_SERVER") or "").strip(),
        str(payload.get("user") or cur.get("MAIL_USER") or "").strip(),
        password,
    )
    return res


def draft_notify(draft_id: int) -> dict:
    """Turn a pending draft into a notification, so it reaches the phone."""
    d = DRAFTS.get(draft_id) if DRAFTS else None
    if not d:
        return {"ok": False, "error": "Unknown draft."}
    try:
        from ocnotify import notify  # noqa: PLC0415

        res = notify(
            f"✍️ Brouillon prêt · {d['title']}",
            (d.get("body") or "")[:600],
            chat_id=DEFAULT_CHAT_ID,
            topic="draft",
            level="important",
            dedup_key=f"draft:{draft_id}",
        )
        DRAFTS.set_status(draft_id, "sent")
        return {"ok": True, "notify": res}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


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


# ----------------------------------------------------------------- interests


def interests_autonomy() -> str:
    """How much latitude Mav has to spawn its own watchdogs."""
    level = "suggest"
    try:
        rows = pg_query("select value from preferences where key = 'interests.autonomy' limit 1")
        if rows and rows[0].get("value"):
            level = rows[0]["value"]
    except Exception:  # noqa: BLE001
        pass
    return level if level in ("off", "suggest", "auto") else "suggest"


def set_interests_autonomy(level: str) -> dict:
    level = (level or "suggest").strip().lower()
    if level not in ("off", "suggest", "auto"):
        return {"ok": False, "error": "Level must be off, suggest or auto."}
    pg_exec(
        "insert into preferences (chat_id, key, value, ts) values (%s, 'interests.autonomy', %s, %s) "
        "on conflict (chat_id, key) do update set value = excluded.value, ts = excluded.ts",
        (DEFAULT_CHAT_ID, level, int(time.time())),
    )
    return {"ok": True, "level": level}


def _selfinit_diff() -> dict:
    if INTERESTS is None or ocselfinit is None:
        return {"create": [], "update": [], "retire": [], "keep": [], "counts": {}}
    try:
        return ocselfinit.reconcile(INTERESTS, JOBS_FILE, autonomy="suggest")
    except Exception as exc:  # noqa: BLE001
        return {"create": [], "update": [], "retire": [], "keep": [],
                "counts": {}, "error": str(exc)[:200]}


def get_interests() -> dict:
    """The interest profile, the self-init proposal, and the knobs to steer it."""
    items = INTERESTS.list(include_muted=True) if INTERESTS else []
    now = int(time.time())
    for it in items:
        due = int(it.get("next_due") or 0)
        it["due_in_days"] = round((due - now) / 86400, 1) if due else None
    diff = _selfinit_diff()
    return {
        "interests": items,
        "backend": INTERESTS.backend if INTERESTS else "none",
        "autonomy": interests_autonomy(),
        "categories": list(CATEGORIES),
        "cadences": list(CADENCES),
        "cadence_days": CADENCE_DAYS,
        "selfinit": diff,
    }


def add_interest(payload: dict) -> dict:
    if INTERESTS is None:
        return {"ok": False, "error": "Interests unavailable."}
    label = str(payload.get("label") or "").strip()
    if not label:
        return {"ok": False, "error": "A label is required."}
    rec = INTERESTS.add(
        label,
        polarity=str(payload.get("polarity") or "like"),
        category=str(payload.get("category") or "other"),
        entity=str(payload.get("entity") or ""),
        cadence=str(payload.get("cadence") or ""),
        source="dashboard",
    )
    return {"ok": rec is not None, "interest": rec}


def update_interest(payload: dict) -> dict:
    if INTERESTS is None:
        return {"ok": False, "error": "Interests unavailable."}
    key = str(payload.get("key") or "").strip()
    if not key:
        return {"ok": False, "error": "A key is required."}
    fields = {}
    for f in ("pinned", "muted", "cadence", "polarity", "label", "category", "notes"):
        if f in payload:
            fields[f] = payload[f]
    if payload.get("resolve_conflict"):
        fields["resolve_conflict"] = True
    rec = INTERESTS.update(key, **fields)
    return {"ok": rec is not None, "interest": rec}


def delete_interest(key: str) -> dict:
    if INTERESTS is None:
        return {"ok": False, "error": "Interests unavailable."}
    return {"ok": INTERESTS.delete(key)}


def interest_feedback(key: str, positive: bool) -> dict:
    if INTERESTS is None:
        return {"ok": False, "error": "Interests unavailable."}
    rec = INTERESTS.feedback(key, positive)
    return {"ok": rec is not None, "interest": rec}


def interest_context(key: str) -> dict:
    """Open a chat about one interest: recent news + a prompt to work with.

    This is how a nudge becomes a conversation — Mav brings the topic, the user
    takes it from there.
    """
    if INTERESTS is None:
        return {"ok": False, "error": "Interests unavailable."}
    interest = INTERESTS.get(key)
    if not interest:
        return {"ok": False, "error": "Unknown interest."}
    label = interest.get("label") or key
    sid = routine_session(f"Intérêt · {label}")
    # Best-effort headline context so the chat does not start from nothing.
    try:
        from ocwatch import news_items  # noqa: PLC0415

        query = interest.get("entity") or interest.get("label") or key
        heads = news_items(query)[:5]
    except Exception:  # noqa: BLE001
        heads = []
    lines = [
        f"Contexte : « {label} » fait partie des centres d'intérêt de l'utilisateur "
        f"(catégorie {interest.get('category') or 'autre'}, suivi {interest.get('cadence') or 'mensuel'}).",
        "Actualité récente à creuser :",
    ]
    lines += [f"- {h.get('title')} ({h.get('link')})" for h in heads] or ["- (rien de frais)"]
    lines.append("Ouvre la conversation sur ce sujet : dis-moi ce qui bouge et pose-moi une question.")
    prompt = "\n".join(lines)
    try:
        answer = ask(prompt, DEFAULT_AGENT, sid, raw_session=True, with_memory=False)
        if answer and not answer.startswith("Error:"):
            return {"ok": True, "session": sid, "answer": answer}
        return {"ok": True, "session": sid, "answer": ""}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200], "session": sid}


def selfinit_apply() -> dict:
    """Force Mav to bring its watchdogs in line now (regardless of autonomy)."""
    if INTERESTS is None or ocselfinit is None:
        return {"ok": False, "error": "Self-init unavailable."}
    try:
        res = ocselfinit.reconcile(INTERESTS, JOBS_FILE, autonomy="auto")
        return {"ok": True, **res}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


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
    active = {r["session"] for r in runs_view() if r["status"] == "running"}
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
            "running": s["id"] in active,
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
    if budget_blocked():
        return ""
    tmp = None
    try:
        tmp = http_json(f"{OPENCODE_URL}/session", method="POST", body={"title": "mav-internal"}, timeout=10)["id"]
        body = {"parts": [{"type": "text", "text": instruction}], **_model_body(small=True)}
        if agent and agent in valid_agents():
            body["agent"] = agent
        res = http_json(f"{OPENCODE_URL}/session/{tmp}/message", method="POST", body=body, timeout=timeout)
        record_usage("background", [res or {}])
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
    return save_learned_facts(quick_completion(instruction, timeout=120))


def save_learned_facts(raw: str) -> int:
    """Store the '- User …' lines of a model reply as learned facts."""
    if not (MEMORY and MEMORY_ENABLED):
        return 0
    if not raw or raw.strip(" :\n").upper().startswith("NONE"):
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


def learn_interests(prompt: str) -> int:
    """Detect the user's interests/likes/dislikes in their message.

    Pure, dependency-free and explainable (regex + scoring in ocinterests), so
    it costs nothing and never invents a fact. Every hit keeps its evidence. A
    statement that contradicts a recorded interest is flagged, not silently
    flipped — Mav stops pushing until the user settles it.
    """
    if INTERESTS is None or not prompt or len(prompt) > 4000:
        return 0
    try:
        return INTERESTS.learn_from_text(prompt, source="chat")
    except Exception:  # noqa: BLE001
        return 0


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
        body = {"parts": [{"type": "text", "text": instruction}], **_model_body(small=True)}
        if "title" in valid_agents():
            body["agent"] = "title"
        if budget_blocked():
            return
        res = http_json(f"{OPENCODE_URL}/session/{tmp}/message", method="POST", body=body, timeout=90)
        record_usage("background", [res or {}])
        title = _clean_title(_part_text((res or {}).get("parts") or []))
        if title and session_meta(sid).get("title_locked") is not True:
            rename_session(sid, title)
            set_session_meta(sid, titled=True)
    except Exception:  # noqa: BLE001
        pass
    finally:
        if tmp:
            delete_session(tmp)


# ------------------------------------------------- after-answer model calls
# One worker, one call at a time, and only while no answer is being written:
# on a local model (one GPU) or a rate-limited key, a title or a fact
# extraction running next to the next answer is what made replies feel slow.
# When both a title and facts are wanted, a single call does both.

_after_q: list[tuple] = []
_after_cv = threading.Condition()
_after_thread: threading.Thread | None = None
AFTER_IDLE_WAIT = float(os.environ.get("MAV_AFTER_IDLE_WAIT", "120"))


def _engine_busy() -> bool:
    with _runs_lock:
        return any(r.status == "running" for r in RUNS.values())


def wants_facts(prompt: str) -> bool:
    text = (prompt or "").strip()
    return bool(
        MEMORY and MEMORY_ENABLED and 15 <= len(text) <= 4000 and ABOUT_ME_RE.search(text)
    )


def schedule_after_answer(sid: str, prompt: str, answer: str, needs_title: bool) -> None:
    facts = wants_facts(prompt)
    if not (needs_title or facts):
        return
    global _after_thread
    with _after_cv:
        _after_q.append((sid, prompt, answer, needs_title, facts))
        if _after_thread is None or not _after_thread.is_alive():
            _after_thread = threading.Thread(target=_after_worker, daemon=True)
            _after_thread.start()
        _after_cv.notify()


def _after_worker() -> None:
    while True:
        with _after_cv:
            while not _after_q:
                if not _after_cv.wait(timeout=300):
                    return
            job = _after_q.pop(0)
        # Let the engine finish whatever the person is waiting on (bounded).
        waited = 0.0
        while _engine_busy() and waited < AFTER_IDLE_WAIT:
            time.sleep(1.0)
            waited += 1.0
        try:
            after_answer(*job)
        except Exception:  # noqa: BLE001
            pass


def after_answer(sid: str, prompt: str, answer: str, needs_title: bool, facts: bool) -> None:
    if needs_title and not facts:
        return generate_title(sid, prompt, answer)
    if facts and not needs_title:
        learn_facts(prompt)
        return
    instruction = (
        "Two short tasks about the conversation below.\n"
        "1. On the first line write `TITLE: ` followed by a title of 2 to 5 "
        "words in the language of the user's message (no quotes, no final "
        "punctuation).\n"
        "2. Then write `FACTS:` and, one per line starting with '- ', the "
        "durable personal facts about the user stated in their message "
        "(where they live, job, family, health or diet, preferences, "
        "recurring constraints, goals), each a short third-person sentence "
        "starting with 'User', in the language of the message. Ignore one-off "
        "requests. If there is none, write `FACTS: NONE`.\n\n"
        f"User: {prompt.strip()[:2000]}\n\nAssistant: {answer.strip()[:800]}"
    )
    raw = quick_completion(instruction, timeout=120)
    if not raw:
        return
    title_line = next((l for l in raw.splitlines() if l.strip().upper().startswith("TITLE")), "")
    title = _clean_title(title_line.split(":", 1)[-1] if ":" in title_line else "")
    if title and session_meta(sid).get("title_locked") is not True:
        rename_session(sid, title)
        set_session_meta(sid, titled=True)
    _, _, fact_block = raw.partition("FACTS")
    save_learned_facts(fact_block)


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


def session_messages(sid: str, entries: list | None = None) -> list[dict]:
    """The chat as the person sees it: one bubble per turn.

    The engine stores a turn as several assistant entries — one per step
    (thinking, calling a tool or a helper, then the answer). Shown one by one,
    a reloaded chat would repeat "Assistant · 10:42" for every step of the same
    answer, so consecutive assistant entries are merged into one message (same
    text the live stream showed). A user entry carrying only hidden parts (the
    injected memory, an internal continuation) does not split the turn.
    """
    if entries is None:
        try:
            entries = http_json(f"{OPENCODE_URL}/session/{sid}/message", timeout=12) or []
        except Exception:
            return []
    msgs: list[dict] = []
    for e in entries:
        info = e.get("info") or {}
        role = info.get("role")
        if role not in ("user", "assistant"):
            continue
        text = _part_text(e.get("parts") or [])
        if not text:
            continue
        ts = (info.get("time") or {}).get("created")
        if role == "user":
            msgs.append({"role": "me", "text": text, "ts": ts})
            continue
        # The agent that actually answered (field name varies by version).
        agent = info.get("agent") or info.get("mode") or ""
        prev = msgs[-1] if msgs else None
        if prev and prev["role"] == "mav":
            prev["text"] = f"{prev['text']}\n\n{text}"
            prev["agent"] = prev.get("agent") or agent
            continue
        msgs.append({"role": "mav", "text": text, "ts": ts, "agent": agent})
    return msgs


def _drop_open_turn(msgs: list[dict]) -> list[dict]:
    """Remove the answer still being written (the live stream shows it)."""
    out = list(msgs)
    while out and out[-1]["role"] == "mav":
        out.pop()
    return out


def summarize_session(sid: str) -> str:
    """Key points of a chat, written in a throwaway session.

    Asking inside the chat itself would leave the request and the summary in
    the conversation (shown on reload, and fed back to the model).
    """
    msgs = session_messages(sid)
    if not msgs:
        return "Nothing to summarise yet."
    lines, budget = [], 12000
    for m in reversed(msgs):  # the most recent part matters most
        who = "User" if m["role"] == "me" else "Assistant"
        line = f"{who}: {m['text'].strip()[:2000]}"
        budget -= len(line)
        if budget < 0:
            break
        lines.append(line)
    transcript = "\n\n".join(reversed(lines))
    out = quick_completion(
        "Summarize this conversation in a few key points (decisions, facts, "
        "open questions), in the language it is written in. Reply with the "
        "summary only.\n\n" + transcript,
        timeout=120,
    )
    return out or "The summary could not be written — is the assistant running?"


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


def _model_body(small: bool = False) -> dict:
    """The model to use; `small` = background work (titles, facts, summaries),
    which goes to the cheaper model chosen in Settings → Usage, if any."""
    ref = DEFAULT_MODEL
    if small and USAGE is not None:
        try:
            ref = USAGE.small_model() or ref
        except Exception:  # noqa: BLE001
            pass
    if ref and "/" in ref:
        provider, model = ref.split("/", 1)
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


# --------------------------------------------------------------- run registry
# A chat answer is no longer owned by the HTTP request that started it. Each
# generation runs in its own thread, appends its events to a buffer, and any
# client can attach to the buffer — replaying what it missed and following live.
# That is what lets the tab be closed, the phone go to sleep, or several chats
# stream at once without losing anything.

RUN_TTL = int(os.environ.get("MAV_RUN_TTL", "180"))  # keep finished runs this long


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class Run:
    """One in-flight (or just-finished) answer, observable by any subscriber."""

    def __init__(self, sid: str, prompt: str, agent: str, files: list, *,
                 raw_session: bool = False, with_memory: bool = False, context: str = ""):
        self.sid = sid or ""
        self.context = context
        self.prompt = prompt
        self.agent = agent
        self.files = files or []
        self.raw_session = raw_session
        self.with_memory = with_memory
        self.events: list[tuple[str, dict]] = []
        self.text = ""
        self.agent_out = agent
        self.recalled = 0
        self.tools: list[dict] = []
        self.status = "running"  # running | done | error
        self.interrupted = False
        self.error: str | None = None
        self.started = time.time()
        self.updated = self.started
        self._cv = threading.Condition()
        self._thread: threading.Thread | None = None

    # ---- producer side -------------------------------------------------
    def start(self) -> None:
        # Built here (not in __init__) so a caller/test can swap `_work`.
        self._thread = threading.Thread(target=self._work, daemon=True)
        self._thread.start()

    def _emit(self, event: str, data: dict) -> None:
        with self._cv:
            self.events.append((event, data))
            if event == "start":
                self.agent_out = data.get("agent") or self.agent_out
                self.recalled = int(data.get("recalled") or 0)
            elif event == "delta":
                self.text += data.get("delta") or ""
            elif event == "reset":
                self.text = data.get("text") or ""
            elif event == "tool":
                name = data.get("name") or "tool"
                key = data.get("id") or name
                status = data.get("status") or "running"
                entry = next((t for t in self.tools if t.get("id", t.get("name")) == key), None)
                if entry:
                    entry["status"] = status
                else:
                    self.tools.append({"id": key, "name": name, "status": status,
                                       "detail": data.get("detail") or ""})
            elif event == "done":
                if not self.text and data.get("text"):
                    self.text = data.get("text") or ""
                self.interrupted = bool(data.get("interrupted"))
                self.status = "done"
            elif event == "error":
                self.error = data.get("message") or "engine error"
                self.status = "error"
            self.updated = time.time()
            self._cv.notify_all()

    def _work(self) -> None:
        try:
            for chunk in stream_answer(
                self.prompt, self.sid, self.agent, self.files,
                raw_session=self.raw_session, with_memory=self.with_memory,
                context=self.context,
            ):
                event, data = _parse_sse(chunk)
                if event:
                    self._emit(event, data)
        except Exception as exc:  # noqa: BLE001
            self._emit("error", {"message": str(exc)[:300], "session": self.sid})
        finally:
            with self._cv:
                if self.status == "running":
                    self.status = "done"
                self.updated = time.time()
                self._cv.notify_all()

    # ---- consumer side -------------------------------------------------
    def snapshot(self) -> dict:
        with self._cv:
            return {
                "session": self.sid, "text": self.text, "tools": list(self.tools),
                "status": self.status, "interrupted": self.interrupted,
                "agent": self.agent_out, "recalled": self.recalled,
                "error": self.error, "seq": len(self.events),
            }

    def follow(self, from_seq: int = 0):
        """Yield the events a client has not seen, then live events until done."""
        i = max(0, int(from_seq))
        while True:
            with self._cv:
                if i >= len(self.events) and self.status == "running":
                    self._cv.wait(timeout=20)
                pending = self.events[i:]
                i = len(self.events)
                done = self.status != "running"
            if pending:
                for event, data in pending:
                    yield _sse(event, data)
                continue
            if done:
                return
            yield ": ping\n\n"  # keep-alive so proxies do not drop the stream


def _parse_sse(block: str) -> tuple[str, dict]:
    event = ""
    data: list[str] = []
    for line in (block or "").split("\n"):
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
    if not event:
        return "", {}
    try:
        return event, json.loads("\n".join(data) or "{}")
    except Exception:  # noqa: BLE001
        return event, {}


RUNS: dict[str, Run] = {}
_runs_lock = threading.Lock()


def _run_cleanup() -> None:
    now = time.time()
    with _runs_lock:
        for sid, run in list(RUNS.items()):
            if run.status != "running" and now - run.updated > RUN_TTL:
                RUNS.pop(sid, None)


def start_run(prompt: str, sid: str, agent: str = "", files: list | None = None, *,
              raw_session: bool = False, with_memory: bool = False,
              context: str = "") -> Run:
    """Start (or restart) the answer for a session and return its Run."""
    _run_cleanup()
    run = Run(sid, prompt, agent, files or [], raw_session=raw_session,
              with_memory=with_memory, context=context)
    with _runs_lock:
        RUNS[sid] = run
    run.start()
    return run


def get_run(sid: str) -> Run | None:
    _run_cleanup()
    with _runs_lock:
        return RUNS.get(sid)


def runs_view() -> list[dict]:
    _run_cleanup()
    with _runs_lock:
        runs = list(RUNS.values())
    out = []
    for r in runs:
        out.append({
            "session": r.sid, "status": r.status, "agent": r.agent_out,
            "started": r.started, "updated": r.updated,
            "interrupted": r.interrupted, "error": r.error,
            "text_len": len(r.text), "tools": len(r.tools),
        })
    out.sort(key=lambda x: x["updated"], reverse=True)
    return out


def stop_run(sid: str) -> dict:
    """Ask a run to stop; the partial answer is kept, not discarded."""
    if not sid:
        return {"ok": False, "error": "missing id"}
    request_interrupt(sid)
    abort_session(sid)
    return {"ok": True}


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


# ----------------------------------------------------------- engine events
# Waking up on the engine's own event stream (GET /event) instead of re-reading
# the whole conversation every 0.4 s: a word written by the model reaches the
# browser right away, and a long chat (with big tool outputs) is no longer
# re-downloaded several times a second. Without the event stream, polling
# falls back to a gentle backoff.


class EngineEvents:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.connected = False
        self._lock = threading.Lock()
        self._marks: dict[str, int] = {}
        self._cv = threading.Condition(self._lock)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    @staticmethod
    def session_of(event: dict) -> str:
        props = event.get("properties") or {}
        return (
            props.get("sessionID")
            or (props.get("info") or {}).get("sessionID")
            or (props.get("part") or {}).get("sessionID")
            or ""
        )

    def _bump(self, sid: str) -> None:
        with self._cv:
            self._marks[sid] = self._marks.get(sid, 0) + 1
            self._cv.notify_all()

    def mark(self, sid: str) -> int:
        with self._lock:
            return self._marks.get(sid, 0)

    def wait(self, sid: str, seen: int, timeout: float) -> int:
        """Block until something happens in `sid` (or timeout); new mark."""
        with self._cv:
            if self._marks.get(sid, 0) == seen:
                self._cv.wait(timeout)
            return self._marks.get(sid, 0)

    def _loop(self) -> None:
        backoff = 1.0
        while True:
            try:
                req = urllib.request.Request(
                    f"{self.base_url}/event", headers={"Accept": "text/event-stream"}
                )
                with urllib.request.urlopen(req, timeout=60) as r:
                    self.connected = True
                    backoff = 1.0
                    data: list[str] = []
                    for raw in r:
                        line = raw.decode("utf-8", "replace").rstrip("\r\n")
                        if line.startswith("data:"):
                            data.append(line[5:].strip())
                            continue
                        if line or not data:
                            continue
                        try:
                            event = json.loads("\n".join(data))
                        except Exception:  # noqa: BLE001
                            event = {}
                        data = []
                        sid = self.session_of(event) if isinstance(event, dict) else ""
                        if sid:
                            self._bump(sid)
            except Exception:  # noqa: BLE001
                pass
            self.connected = False
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


ENGINE_EVENTS = EngineEvents(OPENCODE_URL)

# Does the engine honour ?limit= (newest N messages)? Checked once, lazily.
_limit_ok: dict = {"known": False, "ok": False}
MSG_WINDOW = 80


def _messages_url(sid: str, full: list | None = None) -> str:
    """Messages URL for polling, limited to the newest entries when supported."""
    base = f"{OPENCODE_URL}/session/{sid}/message"
    if not _limit_ok["known"] and full:
        try:
            tail = http_json(f"{base}?limit=1", timeout=8) or []
            if len(full) > 1:  # with a single message, first == last: no answer
                last_full = (full[-1].get("info") or {}).get("id")
                _limit_ok["ok"] = (
                    len(tail) == 1 and (tail[0].get("info") or {}).get("id") == last_full
                )
                _limit_ok["known"] = True
        except Exception:  # noqa: BLE001
            _limit_ok.update(known=True, ok=False)
    return f"{base}?limit={MSG_WINDOW}" if _limit_ok["ok"] else base


def _tool_detail(part: dict) -> str:
    """A human hint for a tool step: which helper, which page, which search."""
    state = part.get("state") or {}
    inp = state.get("input") or {}
    if part.get("tool") == "task":
        return str(inp.get("subagent_type") or inp.get("agent") or "")
    if inp.get("url"):
        return urllib.parse.urlparse(str(inp["url"])).netloc or ""
    if inp.get("query"):
        return str(inp["query"])[:60]
    return ""


def stream_answer(
    prompt: str,
    sid: str,
    agent: str = "",
    files: list | None = None,
    raw_session: bool = False,
    with_memory: bool = False,
    context: str = "",
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

    if budget_blocked():
        b = USAGE.budget()
        yield sse("error", {"message": (
            f"Your monthly budget (${b['monthly_usd']:.2f}) is used up. Raise it in "
            "Settings → Usage, or wait until next month."), "session": sid})
        return

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

    # Extra hidden context from the caller (e.g. the daily briefing's data).
    if context:
        body["parts"].insert(0, {"type": "text", "text": context, "synthetic": True})

    try:
        http_json(f"{OPENCODE_URL}/session/{sid}/prompt_async", method="POST", body=body)
    except Exception as exc:  # noqa: BLE001
        yield sse("error", {"message": f"Could not start: {exc}", "session": sid})
        return

    yield sse("start", {"session": sid, "agent": ag, "recalled": recalled})

    deadline = time.time() + 900      # overall guard (15 min)
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
    # Text of every assistant entry of this turn, by id, in order: a window of
    # the newest messages can scroll an early step out, its text stays here.
    texts: dict[str, str] = {}
    turn_info: dict[str, dict] = {}  # tokens and cost of every step
    url = _messages_url(sid, before)
    ENGINE_EVENTS.start()
    mark = ENGINE_EVENTS.mark(sid)
    heard = False
    pause = 0.15

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

        # Wait for the engine to say something about this chat. With the event
        # stream that is instant; a slow safety poll still runs in case an event
        # is missed. Without it, poll with a backoff (0.15 s → 1.2 s).
        if ENGINE_EVENTS.connected:
            # Long safety poll once this chat's events are seen flowing; short
            # until then, in case this engine version names them differently.
            new_mark = ENGINE_EVENTS.wait(sid, mark, 1.5 if heard else 0.4)
            if new_mark != mark:
                heard = True
                time.sleep(0.08)  # let a burst of tokens land in one read
                new_mark = ENGINE_EVENTS.mark(sid)
            mark = new_mark
        else:
            time.sleep(pause)
            pause = min(pause * 1.4, 1.2)
        try:
            entries = http_json(url, timeout=12) or []
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
        for e in new_assistant:
            turn_info[(e.get("info") or {}).get("id") or ""] = e.get("info") or {}

        # Visible answer only: "text" parts, never reasoning.
        for e in new_assistant:
            texts[(e.get("info") or {}).get("id") or ""] = _part_text(e.get("parts") or [])
        text = "\n\n".join(t for t in texts.values() if t).strip()

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
        sig = (len(texts), linfo.get("finish"), len(text), tool_sig)
        if sig != last_sig:
            last_sig = sig
            last_progress = time.time()
            pause = 0.15

        # Surface tool/MCP activity so the web app can show it live — with the
        # helper's name when the assistant delegates.
        for e in new_assistant:
            for part in (e.get("parts") or []):
                if part.get("type") != "tool":
                    continue
                key = part.get("callID") or part.get("id")
                status = (part.get("state") or {}).get("status") or "running"
                if key and tools_state.get(key) != status:
                    tools_state[key] = status
                    yield sse("tool", {
                        "id": key, "name": part.get("tool") or "tool",
                        "status": status, "detail": _tool_detail(part),
                    })

        if text != last_text:
            last_text = text
            delta = text[len(last_sent):] if text.startswith(last_sent) else text
            if not text.startswith(last_sent):
                yield sse("reset", {"text": text})
                delta = ""
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

    if turn_info:
        record_usage("routine" if raw_session else "chat", list(turn_info.values()))

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
        # Cheap, local work right away; model calls (title, learned facts) go
        # through one queue that waits for the engine to be idle, so they never
        # slow down the answer the person is waiting for.
        threading.Thread(
            target=remember_exchange, args=(prompt, final, sid, ag), daemon=True
        ).start()
        threading.Thread(target=learn_interests, args=(prompt,), daemon=True).start()
        schedule_after_answer(sid, prompt, final, needs_title)


def ask(
    prompt: str,
    agent: str = "",
    sid: str = "",
    files: list | None = None,
    raw_session: bool = False,
    with_memory: bool = False,
    context: str = "",
) -> str:
    """Blocking version (routines, summaries, fallback)."""
    last = ""
    for chunk in stream_answer(prompt, sid, agent, files, raw_session=raw_session,
                               with_memory=with_memory, context=context):
        if chunk.startswith("event: reset"):
            try:
                last = json.loads(chunk.split("data: ", 1)[1]).get("text") or ""
            except Exception:
                pass
            continue
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

    def _send(self, code: int, payload, ctype="application/json", headers=None):
        if isinstance(payload, (dict, list)):
            data = json.dumps(payload, ensure_ascii=False, default=_json_default).encode()
        else:
            data = payload if isinstance(payload, bytes) else str(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    # ---- sign-in -------------------------------------------------------
    def _guard(self, path: str) -> bool:
        """False (and a 401 sent) when this API call needs a session."""
        if AUTH.allowed(path, self.headers.get("Cookie", "")):
            return True
        self._send(401, {"error": "sign in required", "auth": True})
        return False

    def _secure(self) -> bool:
        return bool(getattr(self.server, "is_tls", False)) or (
            self.headers.get("X-Forwarded-Proto", "") == "https"
        )

    def _auth_post(self, path: str, payload: dict):
        who = self.client_address[0] if self.client_address else "?"
        cookie = self.headers.get("Cookie", "")
        if path == "/api/auth/logout":
            return self._send(200, {"ok": True}, headers={
                "Set-Cookie": AUTH.set_cookie("", self._secure(), clear=True)})
        if path == "/api/auth/setup":
            if AUTH.configured():
                return self._send(409, {"error": "A password is already set. Sign in instead."})
            try:
                AUTH.set_password(payload.get("password", ""))
            except ValueError as exc:
                return self._send(400, {"error": str(exc)})
            return self._send(200, {"ok": True}, headers={
                "Set-Cookie": AUTH.set_cookie(AUTH.issue(), self._secure())})
        if path == "/api/auth/login":
            wait = AUTH.throttled(who)
            if wait:
                return self._send(429, {"error": f"Too many attempts. Try again in {int(wait) + 1} s."})
            if not AUTH.check_password(payload.get("password", "")):
                AUTH.failed(who)
                return self._send(401, {"error": "Wrong password."})
            AUTH.succeeded(who)
            return self._send(200, {"ok": True}, headers={
                "Set-Cookie": AUTH.set_cookie(AUTH.issue(), self._secure())})
        if path == "/api/auth/password":
            if AUTH.configured() and not AUTH.valid(AUTH.cookie_token(cookie)):
                return self._send(401, {"error": "sign in required", "auth": True})
            if AUTH.configured() and not AUTH.check_password(payload.get("current", "")):
                AUTH.failed(who)
                return self._send(400, {"error": "The current password is wrong."})
            try:
                AUTH.set_password(payload.get("password", ""))
            except ValueError as exc:
                return self._send(400, {"error": str(exc)})
            # Every other device is signed out; this one gets a fresh session.
            return self._send(200, {"ok": True}, headers={
                "Set-Cookie": AUTH.set_cookie(AUTH.issue(), self._secure())})
        return self._send(404, {"error": "not found"})

    def _sse_open(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
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
        if not self._guard(path):
            return
        try:
            if path == "/api/auth/state":
                return self._send(200, AUTH.state(self.headers.get("Cookie", "")))
            if path == "/api/health":
                return self._send(200, {"ok": True})
            if path == "/api/briefing":
                return self._send(200, get_briefing())
            if path == "/api/usage":
                if USAGE is None:
                    return self._send(200, {"available": False})
                return self._send(200, {"available": True, **USAGE.summary(int(p.get("days") or 30))})
            if path == "/api/status":
                return self._send(200, get_status())
            if path == "/api/jobs":
                return self._send(200, get_jobs())
            if path == "/api/job-templates":
                return self._send(200, job_templates())
            if path == "/api/job-results":
                return self._send(200, get_job_results())
            if path == "/api/proactivity":
                return self._send(200, get_proactivity())
            if path == "/api/drafts":
                return self._send(200, get_drafts(p.get("status", "pending")))
            if path == "/api/actions":
                return self._send(200, get_actions())
            if path == "/api/events":
                return self._send(200, get_events(int(p.get("limit", 30) or 30)))
            if path == "/api/mail/status":
                return self._send(200, mail_config())
            if path == "/api/memory":
                return self._send(200, get_memory())
            if path == "/api/watch":
                return self._send(200, get_watch())
            if path == "/api/interests":
                return self._send(200, get_interests())
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
                run = get_run(sid)
                running = bool(run and run.status == "running")
                msgs = session_messages(sid)
                if running:
                    # The answer in progress belongs to the live stream: sending
                    # it here too is what showed the last answer twice.
                    msgs = _drop_open_turn(msgs)
                return self._send(200, {
                    "id": sid,
                    "title": session_title(sid)[len(PREFIX):],
                    "agent": session_meta(sid).get("agent", ""),
                    "messages": msgs,
                    "running": running,
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
            if path == "/api/runs":
                return self._send(200, {"runs": runs_view()})
            if path == "/api/stream":
                return self._stream(p)
            return self._static(path)
        except Exception as exc:  # noqa: BLE001
            return self._send(500, {"error": str(exc)})

    def _stream(self, p: dict):
        """Start a new answer, or attach to the one already running.

        A reconnect (the tab came back, the phone woke up) passes no prompt and
        a `from` cursor: the events it missed are replayed from the run buffer,
        then the live stream continues. Leaving never aborts the generation —
        only an explicit stop does.
        """
        sid = p.get("session", "")
        from_seq = int(p.get("from") or 0)
        prompt = (p.get("prompt") or "").strip()
        run = get_run(sid) if sid else None

        if not prompt and not run:
            return self._send(400, {"error": "missing prompt"})
        if prompt and (run is None or run.status != "running"):
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
            run = start_run(prompt, sid, p.get("agent", ""), files)
        elif prompt and run.status == "running":
            # A message while this session already runs is queued by the client;
            # never silently replace a live generation.
            return self._send(409, {"error": "already running", "session": sid})

        self._sse_open()
        try:
            for chunk in run.follow(from_seq):
                self.wfile.write(chunk.encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # The client left: the run keeps going. It will be reattachable.
            pass
        except Exception as exc:  # noqa: BLE001
            try:
                self.wfile.write(_sse("error", {"message": str(exc)}).encode())
            except Exception:
                pass

    def do_POST(self):
        path, _, _ = self.path.partition("?")
        payload = self._body()
        if not self._guard(path):
            return
        try:
            if path.startswith("/api/auth/"):
                return self._auth_post(path, payload)
            if path == "/api/briefing":
                return self._send(200, set_briefing(bool(payload.get("enabled")),
                                                    str(payload.get("time") or "")))
            if path == "/api/briefing/run":
                return self._send(200, run_briefing_now())
            if path == "/api/usage/budget":
                if USAGE is None:
                    return self._send(400, {"error": "Usage tracking unavailable."})
                try:
                    b = USAGE.set_budget(float(payload.get("monthly_usd") or 0),
                                         str(payload.get("action") or "warn"))
                except (TypeError, ValueError) as exc:
                    return self._send(400, {"error": str(exc)})
                return self._send(200, {"ok": True, "budget": b})
            if path == "/api/usage/small-model":
                if USAGE is None:
                    return self._send(400, {"error": "Usage tracking unavailable."})
                ref = str(payload.get("model") or "").strip()
                if ref and "/" not in ref:
                    return self._send(400, {"error": "Use provider/model, e.g. anthropic/claude-haiku-4-5."})
                USAGE.set_small_model(ref)
                return self._send(200, {"ok": True, "small_model": ref})
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
            if path == "/api/run/stop":
                return self._send(200, stop_run(payload.get("id", "")))
            if path == "/api/session/summary":
                sid = payload.get("id", "")
                s = summarize_session(sid)
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
            if path == "/api/job/template":
                res = template_to_job(payload.get("id", ""), name=payload.get("name", ""))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/job/snooze":
                try:
                    until = int(payload.get("until") or 0)
                except (TypeError, ValueError):
                    until = 0
                ok = snooze_job(payload.get("name", ""), until)
                return self._send(200 if ok else 404, {"ok": ok})
            if path == "/api/job/delete":
                ok = delete_job(payload.get("name", ""))
                return self._send(200 if ok else 404, {"ok": ok})
            if path == "/api/routine/detect":
                return self._send(200, detect_routine(payload.get("text", "")))
            if path == "/api/proactivity":
                res = set_proactivity(payload.get("level", ""))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/drafts/add":
                res = draft_action("add", payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/drafts/status":
                res = draft_action("status", payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/drafts/delete":
                res = draft_action("delete", payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/drafts/notify":
                res = draft_notify(int(payload.get("id") or 0))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/drafts/edit":
                res = draft_action("edit", payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/drafts/send":
                res = send_draft(int(payload.get("id") or 0))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/mail/save":
                res = mail_save(payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/mail/test":
                return self._send(200, mail_test(payload))
            if path == "/api/mail/forget":
                return self._send(200, mail_forget())
            if path == "/api/mail/reply-draft":
                res = mail_reply_draft(payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/hooks/event":
                res = hook_event(
                    payload.get("kind", "custom"),
                    payload.get("payload") or payload,
                    str(payload.get("token") or ""),
                )
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/actions/start":
                res = start_action(
                    payload.get("prompt", ""),
                    payload.get("name", ""),
                    payload.get("agent", ""),
                )
                return self._send(200 if res.get("ok") else 400, res)
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
            if path == "/api/interests/add":
                res = add_interest(payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/interests/update":
                res = update_interest(payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/interests/delete":
                return self._send(200, delete_interest(str(payload.get("key") or "")))
            if path == "/api/interests/feedback":
                return self._send(200, interest_feedback(
                    str(payload.get("key") or ""), bool(payload.get("positive"))))
            if path == "/api/interests/open":
                res = interest_context(str(payload.get("key") or ""))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/interests/autonomy":
                res = set_interests_autonomy(str(payload.get("level") or ""))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/interests/apply":
                res = selfinit_apply()
                return self._send(200 if res.get("ok") else 400, res)
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
        # Email drafts: recipient and subject, added with the Mail feature.
        pg_exec("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS email_to text")
        pg_exec("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS email_subject text")
        # The original Message-ID, so the reply threads in the mailbox.
        pg_exec("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS message_id text")
        # Interests profile (what the user cares about) and the watchdog routines
        # Mav spawns from it.
        if INTERESTS is not None:
            try:
                INTERESTS._ensure()
                if INTERESTS._pg is not None:
                    INTERESTS._pg.cursor().execute(
                        "ALTER TABLE interests ADD COLUMN IF NOT EXISTS last_ref text"
                    )
            except Exception:  # noqa: BLE001
                pass
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
            tsrv.is_tls = True  # session cookies get the Secure flag
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
