#!/usr/bin/env python3
"""mav_api — backend du dashboard Mav.

Small HTTP server (stdlib) that exposes the agent's real state read-only
(jobs, Postgres memory, watch, agents, health, metrics) plus a chat that
goes through a dashboard-dedicated opencode session, with SSE streaming.

No authentication: meant for a private host, reachable over VPN.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import shutil
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
DEFAULT_AGENT = os.environ.get("MAV_DASH_AGENT", "").strip()
DEFAULT_MODEL = os.environ.get("OPENCODE_MODEL", "").strip()
# Chat id used to attach new watch items to the Telegram bot.
# 0 by default: the installer sets the real value via MAV_CHAT_ID.
DEFAULT_CHAT_ID = int(os.environ.get("MAV_CHAT_ID", "0") or 0)

# Agents offered in the dashboard selector.
PRIMARY_AGENTS = ["general", "dev", "finance", "ops", "research", "reviewer", "writer"]

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
    if path.name == "push_subs.json":
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


# --------------------------------------------------------------- proxmox


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
        "model": DEFAULT_MODEL,
        "url": OPENCODE_URL,
        "checked": int(time.time()),
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
    return {"ok": True, "restarting": True, "unit": unit}


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
    return {"ok": True, "name": name, "path": str(p)}


def delete_agent_file(name: str) -> dict:
    if not AGENT_NAME_RE.match(name or ""):
        return {"ok": False, "error": "invalid name"}
    p = agents_dir() / f"{name}.md"
    try:
        if p.is_file():
            p.unlink()
        _agents_cache["at"] = 0.0
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




def _proxmox_conf() -> dict:
    """Read Proxmox credentials from the opencode config, without exposing them."""
    try:
        cfg = json.loads(_opencode_config_path().read_text())
        env = cfg.get("mcp", {}).get("proxmox", {}).get("environment", {})
        return {
            "host": env.get("PROXMOX_HOST", ""),
            "user": env.get("PROXMOX_USER", "root@pam"),
            "token_name": env.get("PROXMOX_TOKEN_NAME", "mcp"),
            "token": env.get("PROXMOX_TOKEN_VALUE", ""),
        }
    except Exception:
        return {}


def proxmox_query(path: str) -> dict:
    conf = _proxmox_conf()
    if not conf.get("token"):
        return {}
    url = f"https://{conf['host']}:8006/api2/json{path}"
    req = urllib.request.Request(url)
    req.add_header(
        "Authorization",
        f"PVEAPIToken={conf['user']}!{conf['token_name']}={conf['token']}",
    )
    import ssl

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=6, context=ctx) as r:
        return json.loads(r.read().decode()).get("data", {})


def get_proxmox() -> dict:
    try:
        nodes = proxmox_query("/nodes")
        vms = proxmox_query("/cluster/resources?type=vm")
    except Exception:
        return {"available": False, "nodes": [], "vms": []}

    out_nodes = []
    for n in nodes or []:
        out_nodes.append(
            {
                "name": n.get("node"),
                "status": n.get("status"),
                "cpu": round((n.get("cpu") or 0) * 100),
                "mem_used": n.get("mem"),
                "mem_total": n.get("maxmem"),
                "mem_pct": round((n.get("mem") or 0) / (n.get("maxmem") or 1) * 100),
                "disk_used": n.get("disk"),
                "disk_total": n.get("maxdisk"),
                "uptime": n.get("uptime"),
            }
        )
    running = [v for v in (vms or []) if v.get("status") == "running"]
    out_vms = [
        {
            "vmid": v.get("vmid"),
            "name": v.get("name"),
            "type": v.get("type"),
            "node": v.get("node"),
            "status": v.get("status"),
            "cpu": round((v.get("cpu") or 0) * 100),
            "mem": v.get("mem"),
            "maxmem": v.get("maxmem"),
            "uptime": v.get("uptime"),
        }
        for v in (vms or [])
    ]
    return {
        "available": True,
        "nodes": out_nodes,
        "vms": out_vms,
        "running": len(running),
        "total": len(out_vms),
    }


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
    return {
        "mode": "live",
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
        conns.append({"name": "Moteur opencode", "state": "ok" if ok else "off", "label": "en ligne" if ok else "hors ligne"})
    except Exception:
        conns.append({"name": "Moteur opencode", "state": "off", "label": "hors ligne"})
    try:
        pg_query("select 1")
        conns.append({"name": "Memory store", "state": "ok", "label": "connected"})
    except Exception:
        conns.append({"name": "Memory store", "state": "off", "label": "offline"})
    docker_ok = Path("/var/run/docker.sock").exists()
    conns.append({"name": "Docker", "state": "ok" if docker_ok else "warn", "label": "present" if docker_ok else "unknown"})
    conns.append({"name": "Telegram", "state": "ok", "label": "pont actif"})
    px = get_proxmox()
    conns.append({"name": "Proxmox", "state": "ok" if px.get("available") else "warn", "label": "connected" if px.get("available") else "unavailable"})
    return conns


def get_jobs() -> dict:
    jobs = read_json(JOBS_FILE, [])
    state = read_json(JOBS_STATE, {})
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
                "enabled": j.get("enabled", True),
                "last_run": state.get(j.get("name")),
            }
        )
    return {"jobs": out}


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


JOB_PREFIX = "job-"


def get_job_results(limit: int = 8) -> dict:
    """Latest results produced by scheduled jobs.

    Le bot lance chaque job dans une session « job-<nom> » (distincte du
    dashboard and Telegram). We read the most recent assistant answer
    de ces sessions pour l'afficher sur l'accueil.
    """
    try:
        sessions = http_json(f"{OPENCODE_URL}/session", timeout=8) or []
    except Exception:
        return {"results": []}

    jobs = {j.get("name"): j for j in read_json(JOBS_FILE, [])}
    job_sessions = []
    for s in sessions:
        title = str(s.get("title", ""))
        if not title.startswith(JOB_PREFIX):
            continue
        t = s.get("time", {})
        job_sessions.append({
            "id": s["id"],
            "name": title[len(JOB_PREFIX):],
            "updated": t.get("updated") or t.get("created") or 0,
        })
    job_sessions.sort(key=lambda x: x.get("updated") or 0, reverse=True)

    out = []
    seen = set()
    for js in job_sessions:
        name = js["name"]
        if name in seen:
            continue
        seen.add(name)
        text = ""
        try:
            for m in reversed(session_messages(js["id"])):
                if m["role"] == "mav" and m.get("text"):
                    text = m["text"]
                    break
        except Exception:
            pass
        if not text:
            continue
        meta = jobs.get(name, {})
        out.append({
            "name": name,
            "description": meta.get("description", ""),
            "time": meta.get("time", ""),
            "updated": js["updated"],
            "text": text[:4000],
            "session": js["id"],
        })
        if len(out) >= limit:
            break
    return {"results": out}


def get_memory(limit: int = 20) -> dict:
    def q(sql, params=()):
        try:
            return pg_query(sql, params)
        except Exception:
            return []

    return {
        "conversations": q("select question, answer, ts from conversations order by ts desc limit %s", (limit,)),
        "facts": q("select fact, source, ts from facts order by ts desc limit 20"),
        "preferences": q("select key, value, ts from preferences order by ts desc limit 20"),
    }


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
            "select ts, topic, title, body, channels, delivered "
            "from notifications order by ts desc limit %s",
            (limit,),
        )
    except Exception:
        rows = []
    return {"notifications": rows}


def get_notification(nid: int) -> dict:
    """One notification by id (to open its detail from the push)."""
    try:
        rows = pg_query(
            "select id, ts, topic, title, body, delivered from notifications where id = %s",
            (nid,),
        )
    except Exception:
        rows = []
    return {"notification": rows[0] if rows else None}


VALID_WATCH_KINDS = ["web", "mail", "github", "moodle", "proxmox", "health", "stock"]


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
    # Internal agents we do not offer in the selector.
    hidden = {"compaction", "title", "summary", "plan", "build"}
    try:
        agents = http_json(f"{OPENCODE_URL}/agent", timeout=6) or []
        names = sorted(
            a["name"]
            for a in agents
            if isinstance(a, dict)
            and a.get("name")
            and a["name"] not in hidden
            and not a.get("hidden")
            # On propose primaires ET subagents : ils fonctionnent comme agent
            # de session pour le chat.
            and a.get("mode") in ("primary", "subagent", "all", None)
        )
        ordered = [n for n in PRIMARY_AGENTS if n in names] + [n for n in names if n not in PRIMARY_AGENTS]
        return {"agents": ordered or PRIMARY_AGENTS}
    except Exception:
        return {"agents": PRIMARY_AGENTS}


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


# ------------------------------------------------------------------- markets

# Default indices/symbols offered in the dashboard.
MARKET_SYMBOLS = [
    "SPY", "QQQ", "DIA", "IWM", "GLD", "SLV", "USO", "TLT", "VIX",
    "NVDA", "AAPL", "MSFT", "TSLA", "BTC-USD", "ETH-USD",
    "^GSPC", "^IXIC", "^DJI", "^FCHI", "^GDAXI",
]

_YF_HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
_YF_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _yf(path: str) -> dict:
    last = None
    for host in _YF_HOSTS:
        url = f"https://{host}{path}"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": _YF_UA,
                    "Accept": "application/json,text/plain,*/*",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            with urllib.request.urlopen(req, timeout=12) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            last = exc
            continue
    raise last or RuntimeError("yahoo indisponible")


def get_quote(symbol: str) -> dict:
    """Dernier prix et variation d'un symbole (Yahoo Finance)."""
    sym = symbol.strip().upper()
    data = _yf(f"/v8/finance/chart/{urllib.parse.quote(sym)}?range=5d&interval=1d")
    res = (data.get("chart", {}).get("result") or [None])[0]
    if not res:
        return {"symbol": sym, "error": "introuvable"}
    meta = res.get("meta", {})
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    change = None
    pct = None
    if price is not None and prev:
        change = round(price - prev, 4)
        pct = round((price - prev) / prev * 100, 2)
    return {
        "symbol": sym,
        "name": meta.get("shortName") or meta.get("symbol") or sym,
        "currency": meta.get("currency"),
        "price": price,
        "prev": prev,
        "change": change,
        "pct": pct,
    }


def get_quotes(symbols: list[str]) -> dict:
    out = []
    for s in symbols[:24]:
        try:
            q = get_quote(s)
        except Exception:
            q = {"symbol": s, "error": "indisponible"}
        out.append(q)
    return {"quotes": out}


def get_chart(symbol: str, range_: str = "1mo", interval: str = "1d") -> dict:
    """OHLC series + volume for a chart (Yahoo Finance)."""
    sym = symbol.strip().upper()
    allowed_ranges = {"1d": ("5m", "1d"), "5d": ("30m", "5d"), "1mo": ("1d", "1mo"),
                      "3mo": ("1d", "3mo"), "6mo": ("1d", "6mo"), "1y": ("1d", "1y"),
                      "2y": ("1wk", "2y"), "5y": ("1wk", "5y")}
    if range_ in allowed_ranges:
        interval = allowed_ranges[range_][0]
    path = (
        f"/v8/finance/chart/{urllib.parse.quote(sym)}"
        f"?range={urllib.parse.quote(range_)}&interval={urllib.parse.quote(interval)}"
    )
    data = _yf(path)
    res = (data.get("chart", {}).get("result") or [None])[0]
    if not res:
        return {"symbol": sym, "error": "introuvable"}
    meta = res.get("meta", {})
    ts = res.get("timestamp") or []
    quote = (res.get("indicators", {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    vols = quote.get("volume") or []

    candles = []
    for i, t in enumerate(ts):
        c = closes[i] if i < len(closes) else None
        o = opens[i] if i < len(opens) else None
        h = highs[i] if i < len(highs) else None
        lo = lows[i] if i < len(lows) else None
        if c is None or o is None or h is None or lo is None:
            continue
        row = {"time": int(t), "open": round(o, 4), "high": round(h, 4),
               "low": round(lo, 4), "close": round(c, 4)}
        if i < len(vols) and vols[i] is not None:
            row["volume"] = int(vols[i])
        candles.append(row)

    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    pct = round((price - prev) / prev * 100, 2) if (price and prev) else None
    return {
        "symbol": sym,
        "name": meta.get("shortName") or sym,
        "currency": meta.get("currency"),
        "price": price,
        "pct": pct,
        "candles": candles,
    }


# ------------------------------------------------------------------- chat

PREFIX = "dash: "
DEFAULT_TITLE = "Nouvelle discussion"


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
        out.append({
            "id": s["id"],
            "title": title[len(PREFIX):] or DEFAULT_TITLE,
            "created": t.get("created"),
            "updated": t.get("updated") or t.get("created"),
        })
    out.sort(key=lambda x: x.get("updated") or 0, reverse=True)
    return out


def create_session(title: str = "", agent: str = "") -> dict:
    name = (title or DEFAULT_TITLE).strip()[:80] or DEFAULT_TITLE
    body = {"title": PREFIX + name}
    if agent and agent in PRIMARY_AGENTS:
        body["agent"] = agent
    res = http_json(f"{OPENCODE_URL}/session", method="POST", body=body)
    return {"id": res["id"], "title": name}


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
        msgs.append({
            "role": "me" if role == "user" else "mav",
            "text": text,
            "ts": (info.get("time") or {}).get("created"),
        })
    return msgs


def export_session_markdown(sid: str) -> str:
    title = session_title(sid)[len(PREFIX):] or DEFAULT_TITLE
    lines = [f"# {title}", ""]
    for m in session_messages(sid):
        who = "Vous" if m["role"] == "me" else "Mav"
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


# Le moteur refuse application/octet-stream : on devine un type utile depuis
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


def stream_answer(prompt: str, sid: str, agent: str = "", files: list | None = None):
    """SSE answer, collected server-side: reliable and reasoning-free.

    We let the engine run the request, then poll the session messages until
    we get a finished assistant message. Only "text" parts are sent: tool
    steps and internal reasoning never appear. The end is detected on the
    `finish` field
    du message, pas sur un signal de flux qui peut se perdre.
    """
    sid = ensure_session(sid, agent)
    body: dict = {"parts": _parts(prompt, files or [])}
    ag = agent or DEFAULT_AGENT

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    if ag:
        known = valid_agents()
        if known and ag not in known:
            yield sse("error", {"message": f"Agent inconnu : {ag}", "session": sid})
            return
        body["agent"] = ag
    body.update(_model_body())

    # Auto-title: the first time we write into a conversation still
    # named by default, its title becomes the start of the message.
    try:
        if prompt.strip():
            current = session_title(sid)[len(PREFIX):]
            if current in ("", DEFAULT_TITLE):
                auto = " ".join(prompt.strip().split())[:48]
                if len(prompt.strip()) > 48:
                    auto += "…"
                rename_session(sid, auto)
    except Exception:
        pass

    # Start marker: any message older than our prompt is ignored.
    try:
        before = http_json(f"{OPENCODE_URL}/session/{sid}/message", timeout=12) or []
    except Exception:
        before = []
    before_ids = {(e.get("info") or {}).get("id") for e in before}

    try:
        http_json(f"{OPENCODE_URL}/session/{sid}/prompt_async", method="POST", body=body)
    except Exception as exc:  # noqa: BLE001
        yield sse("error", {"message": f"Impossible de lancer : {exc}", "session": sid})
        return

    yield sse("start", {"session": sid})

    deadline = time.time() + 900      # garde-fou global (15 min)
    idle_limit = 240                  # no real progress (4 min)
    last_progress = time.time()
    last_sig = None
    last_text = ""
    last_sent = ""
    accepted = False
    finished_text = None
    engine_error = None

    while time.time() < deadline and time.time() - last_progress < idle_limit:
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

        if text != last_text:
            last_text = text
            delta = text[len(last_sent):] if text.startswith(last_sent) else text
            last_sent = text
            if delta:
                yield sse("delta", {"delta": delta})

        if linfo.get("error"):
            err = linfo.get("error") or {}
            engine_error = (
                (err.get("data") or {}).get("message") or err.get("name") or "erreur du moteur"
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

    if not accepted and not finished_text:
        yield sse("error", {"message": "The request could not be started.", "session": sid})
        return
    if engine_error and not finished_text:
        yield sse("error", {"message": str(engine_error), "session": sid})
        return

    yield sse("done", {"session": sid, "text": finished_text or last_text})


def ask(prompt: str, agent: str = "", sid: str = "", files: list | None = None) -> str:
    """Version bloquante (utile pour les scripts / fallback)."""
    last = ""
    for chunk in stream_answer(prompt, sid, agent, files):
        if not chunk.startswith("event: delta"):
            if chunk.startswith("event: done"):
                try:
                    return json.loads(chunk.split("data: ", 1)[1]).get("text") or last
                except Exception:
                    return last
            if chunk.startswith("event: error"):
                try:
                    return f"Erreur : {json.loads(chunk.split('data: ', 1)[1]).get('message')}"
                except Exception:
                    return "Erreur du moteur."
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


# Watch and notification pushing are now handled by the Telegram bot
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
            if path == "/api/agents":
                return self._send(200, get_agents())
            if path == "/api/connections":
                return self._send(200, {"connections": get_connections()})
            if path == "/api/proxmox":
                return self._send(200, get_proxmox())
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
            if path == "/api/config/agent-files":
                return self._send(200, list_agent_files())
            if path == "/api/config/agent-file":
                return self._send(200, read_agent_file(p.get("name", "")))
            if path == "/api/sessions":
                return self._send(200, {"sessions": list_sessions()})
            if path == "/api/session":
                sid = p.get("id", "")
                if not sid:
                    return self._send(400, {"error": "id manquant"})
                return self._send(200, {"id": sid, "title": session_title(sid)[len(PREFIX):], "messages": session_messages(sid)})
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
            if path == "/api/chart":
                return self._send(200, get_chart(p.get("symbol", "SPY"), p.get("range", "1mo")))
            if path == "/api/asset":
                res = serve_asset(p.get("path", ""))
                if not res:
                    return self._send(404, "asset introuvable", "text/plain")
                data, mime = res
                return self._send(200, data, mime)
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
                    return self._send(404, "media introuvable", "text/plain")
                res = serve_asset(hit["path"])
                if not res:
                    return self._send(404, "media introuvable", "text/plain")
                data, mime = res
                return self._send(200, data, mime)
            if path == "/api/media/by-name":
                name = p.get("name", "")
                hits = find_media(name)
                if not hits:
                    return self._send(404, "media introuvable", "text/plain")
                res = serve_asset(hits[0]["path"])
                if not res:
                    return self._send(404, "media introuvable", "text/plain")
                data, mime = res
                return self._send(200, data, mime)
            if path == "/api/quotes":
                syms = [s for s in (p.get("symbols") or "").split(",") if s.strip()]
                return self._send(200, get_quotes(syms or MARKET_SYMBOLS))
            if path == "/api/stream":
                return self._stream(p)
            return self._static(path)
        except Exception as exc:  # noqa: BLE001
            return self._send(500, {"error": str(exc)})

    def _stream(self, p: dict):
        prompt = p.get("prompt", "").strip()
        if not prompt:
            return self._send(400, {"error": "prompt manquant"})
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
                    return self._send(400, {"error": "prompt manquant"})
                return self._send(200, {"answer": ask(prompt, payload.get("agent", ""), payload.get("session", ""), payload.get("files"))})
            if path == "/api/session/new":
                return self._send(200, create_session(payload.get("title", ""), payload.get("agent", "")))
            if path == "/api/session/rename":
                ok = rename_session(payload.get("id", ""), payload.get("title", ""))
                return self._send(200 if ok else 400, {"ok": ok})
            if path == "/api/session/delete":
                ok = delete_session(payload.get("id", ""))
                return self._send(200 if ok else 400, {"ok": ok})
            if path == "/api/session/abort":
                abort_session(payload.get("id", ""))
                return self._send(200, {"ok": True})
            if path == "/api/session/summary":
                sid = payload.get("id", "")
                s = ask("Summarize this conversation in a few key points.", "summary", sid)
                return self._send(200, {"summary": s})
            if path == "/api/job/toggle":
                ok = set_job_enabled(payload.get("name", ""), bool(payload.get("enabled")))
                return self._send(200 if ok else 404, {"ok": ok})
            if path == "/api/job/run":
                name = payload.get("name", "")
                job = next((j for j in read_json(JOBS_FILE, []) if j.get("name") == name), None)
                if not job:
                    return self._send(404, {"error": "job inconnu"})
                sess = create_session(f"job: {name}", job.get("agent", "research"))
                return self._send(200, {"session": sess["id"], "title": sess["title"]})
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
                n = send_push("Mav", "Ceci est une notification de test.")
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
                    return self._send(400, {"error": "text requis"})
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


def main():
    import ssl

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
            print(f"TLS indisponible: {exc}", flush=True)

    srv.serve_forever()


if __name__ == "__main__":
    main()
