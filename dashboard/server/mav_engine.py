"""The opencode engine as a service: its status, restart and pending changes,
connections (MCP), the model provider, helper files, versions and updates.

Part of the web app server (see mav_api.py).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import mav_core


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


# The systemd unit of the engine (installer default: mav-server; older installs
# may use opencode-server). Configurable, with auto-detection as a fallback.
SERVER_UNIT_EXPLICIT = os.environ.get("MAV_SERVER_UNIT", "").strip()


DEFAULT_SERVER_UNITS = ["mav-server", "opencode-server"]


def server_unit() -> str:
    """Name of the systemd unit running the opencode engine."""
    if mav_core.IN_DOCKER:
        return "engine (Docker)"
    if SERVER_UNIT_EXPLICIT:
        return SERVER_UNIT_EXPLICIT
    for u in DEFAULT_SERVER_UNITS:
        code, _ = mav_core._run(["systemctl", "cat", u], timeout=6)
        if code == 0:
            return u
    return DEFAULT_SERVER_UNITS[0]


def _unit_active(unit: str) -> bool:
    code, out = mav_core._run(["systemctl", "is-active", unit], timeout=6)
    return out.strip() == "active"


def engine_status() -> dict:
    """Live status of the agent engine + the services around it."""
    unit = server_unit()
    active = True if mav_core.IN_DOCKER else _unit_active(unit)
    health = {}
    try:
        health = mav_core.http_json(f"{mav_core.OPENCODE_URL}/global/health", timeout=4) or {}
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
        "model": mav_core.DEFAULT_MODEL or provider_current().get("ref") or "",
        "url": mav_core.OPENCODE_URL,
        "checked": int(time.time()),
        "pending": pending_changes(),
        "mav_version": installed_version(),
        "runtime": mav_core.RUNTIME or "systemd",
    }


def _engine_mcp_names() -> list[str]:
    try:
        data = mav_core.http_json(f"{mav_core.OPENCODE_URL}/mcp", timeout=6)
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
        data = mav_core.http_json(f"{mav_core.OPENCODE_URL}/mcp", timeout=6)
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
        data = mav_core.http_json(
            f"{mav_core.OPENCODE_URL}/mcp/{urllib.parse.quote(name, safe='')}/auth",
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
        data = mav_core.http_json(
            f"{mav_core.OPENCODE_URL}/mcp/{urllib.parse.quote(name, safe='')}/auth/callback",
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
        mav_core.http_json(
            f"{mav_core.OPENCODE_URL}/mcp/{urllib.parse.quote(name, safe='')}/auth",
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


def read_agents() -> dict:
    p = mav_core.agents_path()
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "path": str(p), "text": ""}
    return {"path": str(p), "text": text, "exists": p.is_file()}


def write_agents(text: str) -> dict:
    p = mav_core.agents_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # Back up the previous version (keep a couple of them).
        if p.is_file():
            try:
                bak = p.with_suffix(".md.bak")
                bak.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
                mav_core._chown_user(bak)
            except Exception:
                pass
        p.write_text(text, encoding="utf-8")
        mav_core._chown_user(p)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    mark_pending("Custom instructions")
    return {"ok": True, "path": str(p)}


def read_mcp() -> dict:
    """MCP servers from the opencode config, secrets masked."""
    p = mav_core._opencode_config_path()
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
    p = mav_core._opencode_config_path()
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
        mav_core._chown_user(p)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    mark_pending("Connections")
    return {"ok": True, "path": str(p)}


def restart_engine() -> dict:
    """Restart the engine without blocking: issue the restart and return
    immediately. The caller polls /api/config/engine until it is back.

    `systemctl` alone can take minutes because the bot holds a long-lived SSE
    connection, so the graceful stop waits. `--no-block` returns at once."""
    if mav_core.IN_DOCKER:
        try:
            mav_core.RESTART_FLAG.parent.mkdir(parents=True, exist_ok=True)
            mav_core.RESTART_FLAG.write_text(str(time.time()))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "unit": server_unit()}
        _agents_cache["at"] = 0.0
        _pending.clear()
        return {"ok": True, "restarting": True, "unit": server_unit()}
    unit = server_unit()
    code, out = mav_core._run(["systemctl", "restart", "--no-block", unit], timeout=15)
    if code != 0:
        return {"ok": False, "error": out.strip(), "unit": unit}
    # The worker follows the engine's event stream and reads the model from
    # its env: restart it too so it picks up the new configuration.
    mav_core._run(["systemctl", "restart", "--no-block", mav_core.WORKER_UNIT], timeout=15)
    _agents_cache["at"] = 0.0
    _pending.clear()
    return {"ok": True, "restarting": True, "unit": unit}


_pending: dict = {}  # label -> time of the change


def mark_pending(label: str) -> None:
    _pending[label] = time.time()


def engine_started_at() -> float | None:
    """Unix time the engine service last (re)started, or None."""
    if mav_core.IN_DOCKER:
        try:
            return float(mav_core.ENGINE_STARTED.read_text().strip())
        except Exception:  # noqa: BLE001
            return None
    code, out = mav_core._run(
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
        "Connections or model": mav_core._opencode_config_path(),
        "Custom instructions": mav_core.agents_path(),
        "API keys": mav_core.ENV_SERVER,
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


_release_cache: dict = {"at": 0.0, "data": None}


def installed_version() -> str:
    try:
        return mav_core.VERSION_FILE.read_text().strip().splitlines()[0] or "unknown"
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
            f"https://api.github.com/repos/{mav_core.MAV_REPO}/releases/latest",
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
        "runtime": mav_core.RUNTIME or "systemd",
    }


def update_running() -> bool:
    if mav_core.IN_DOCKER:
        return False
    code, out = mav_core._run(["systemctl", "is-active", "mav-update"], timeout=6)
    return out.strip() in ("active", "activating")


def start_update() -> dict:
    """Run `mav update` outside the web app's own service: the update restarts
    the web app, and must survive that."""
    if mav_core.IN_DOCKER:
        return {"ok": False, "docker": True, "error": mav_core.DOCKER_UPDATE_HINT}
    if update_running():
        return {"ok": True, "already": True}
    if not Path(mav_core.MAV_CLI).exists():
        return {"ok": False, "error": "The mav command is not installed — run: sudo mav update"}
    code, out = mav_core._run(
        ["systemd-run", "--unit=mav-update", "--collect", "--quiet",
         "--description=Mav update", mav_core.MAV_CLI, "update", "--yes"],
        timeout=15,
    )
    if code != 0:
        return {"ok": False, "error": out.strip() or "could not start the update"}
    return {"ok": True}


def update_status() -> dict:
    lines = []
    try:
        with open(mav_core.INSTALL_LOG, "rb") as f:
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
        cat = json.loads(mav_core.CATALOG_FILE.read_text(encoding="utf-8"))
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
    p = mav_core._opencode_config_path()
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
        mav_core._chown_user(p)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    mark_pending("Connections")
    return {"ok": True, "name": name}


def provider_current() -> dict:
    try:
        return mav_core.mav_provider.current(mav_core._config_dir(), mav_core.ENV_SERVER)
    except Exception as exc:  # noqa: BLE001
        return {"configured": bool(mav_core.DEFAULT_MODEL), "ref": mav_core.DEFAULT_MODEL, "error": str(exc)}


def provider_snapshot() -> dict:
    cur = provider_current()
    presets = [
        {"id": k, **{x: v[x] for x in ("label", "hint", "native", "base", "key", "model")}}
        for k, v in mav_core.mav_provider.PRESETS.items()
    ]
    return {"current": cur, "presets": presets, "model": mav_core.DEFAULT_MODEL}


def _stored_key(pid: str) -> str:
    return mav_core.mav_provider.read_env(mav_core.ENV_SERVER).get(mav_core.mav_provider.env_name_for(pid), "")


def provider_test(payload: dict) -> dict:
    pid = (payload.get("provider") or "").strip()
    key = payload.get("api_key") or ""
    if not key:
        key = _stored_key(pid)  # test with the saved key when left blank
    return mav_core.mav_provider.list_models(pid, payload.get("base_url") or "", key)


def provider_save(payload: dict) -> dict:
    pid = (payload.get("provider") or "").strip().lower()
    if pid == "custom":
        pid = (payload.get("custom_id") or "").strip().lower()
    key = payload.get("api_key")
    key = key if isinstance(key, str) and key.strip() else None  # blank = keep
    res = mav_core.mav_provider.apply(
        mav_core._config_dir(), mav_core.ENV_SERVER, pid, payload.get("model") or "",
        base_url=(payload.get("base_url") or "").strip(),
        api_key=key.strip() if key else None,
        env_files=mav_core.ENV_FILES,
        name=(payload.get("name") or "").strip(),
    )
    if not res.get("ok"):
        return res
    mav_core.DEFAULT_MODEL = res["ref"]
    mav_core._chown_user(mav_core._opencode_config_path())
    if payload.get("restart", True):
        res["restart"] = restart_engine()
    else:
        mark_pending("Model")
    return res


def config_snapshot() -> dict:
    """Everything the settings screen shows at once."""
    cfg = mav_core._opencode_config_path()
    return {
        "agents": read_agents(),
        "mcp": read_mcp(),
        "engine": engine_status(),
        "config_path": str(cfg),
        "model": mav_core.DEFAULT_MODEL,
        "url": mav_core.OPENCODE_URL,
    }


def agents_dir() -> Path:
    env = os.environ.get("MAV_AGENTS_DIR")
    if env:
        return Path(env)
    return mav_core._config_dir() / "agent"


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
    try:
        p = mav_core.inside(d, f"{name}.md")
        d.mkdir(parents=True, exist_ok=True)
        if p.is_file():
            try:
                bak = p.with_suffix(".md.bak")
                bak.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
                mav_core._chown_user(bak)
            except Exception:
                pass
        p.write_text(text, encoding="utf-8")
        mav_core._chown_user(p)
        mav_core._chown_user(d)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    _agents_cache["at"] = 0.0
    mark_pending("Helpers")
    return {"ok": True, "name": name, "path": str(p)}


def delete_agent_file(name: str) -> dict:
    if not AGENT_NAME_RE.match(name or ""):
        return {"ok": False, "error": "invalid name"}
    try:
        p = mav_core.inside(agents_dir(), f"{name}.md")
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


def get_status() -> dict:
    m = sys_metrics()
    try:
        health = mav_core.http_json(f"{mav_core.OPENCODE_URL}/global/health", timeout=4)
    except Exception:
        health = {"healthy": False}

    pg = False
    n_watch = n_conv = n_facts = 0
    try:
        mav_core.pg_query("select 1")
        pg = True
        n_watch = mav_core.pg_query("select count(*) c from watch_items")[0]["c"]
        n_conv = mav_core.pg_query("select count(*) c from conversations")[0]["c"]
        n_facts = mav_core.pg_query("select count(*) c from facts")[0]["c"]
    except Exception:
        pass

    jobs = mav_core.read_json(mav_core.JOBS_FILE, [])
    prov = provider_current()
    return {
        "mode": "live",
        "model": mav_core.DEFAULT_MODEL or prov.get("ref") or "",
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
        h = mav_core.http_json(f"{mav_core.OPENCODE_URL}/global/health", timeout=4)
        ok = bool(h and h.get("healthy"))
        conns.append({"name": "Agent engine", "state": "ok" if ok else "off", "label": "online" if ok else "offline"})
    except Exception:
        conns.append({"name": "Agent engine", "state": "off", "label": "offline"})
    try:
        mav_core.pg_query("select 1")
        conns.append({"name": "Memory (Postgres)", "state": "ok", "label": "connected"})
    except Exception:
        conns.append({"name": "Memory (Postgres)", "state": "off", "label": "offline"})
    worker = _unit_active(mav_core.WORKER_UNIT)
    conns.append({"name": "Worker", "state": "ok" if worker else "warn", "label": "running" if worker else "stopped"})
    return conns


def get_agents() -> dict:
    """Agents offered in the chat picker, with their description."""
    # Internal agents we do not offer in the selector.
    hidden = {"compaction", "title", "summary", "plan", "build"}
    try:
        agents = mav_core.http_json(f"{mav_core.OPENCODE_URL}/agent", timeout=6) or []
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
        ordered = [n for n in mav_core.PRIMARY_AGENTS if n in names] + [n for n in names if n not in mav_core.PRIMARY_AGENTS]
        default = mav_core.DEFAULT_AGENT if mav_core.DEFAULT_AGENT in details else (ordered[0] if ordered else "")
        return {"agents": ordered or mav_core.PRIMARY_AGENTS, "details": details, "default": default}
    except Exception:
        return {"agents": mav_core.PRIMARY_AGENTS, "details": {}, "default": mav_core.DEFAULT_AGENT}


_agents_cache: dict = {"at": 0.0, "names": set()}


def valid_agents() -> set:
    """Agent names actually recognized by the engine (60 s cache)."""
    now = time.time()
    if now - _agents_cache["at"] < 60 and _agents_cache["names"]:
        return _agents_cache["names"]
    names: set = set()
    try:
        data = mav_core.http_json(f"{mav_core.OPENCODE_URL}/agent", timeout=8) or []
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


__all__ = ['AGENT_NAME_RE', 'AGENT_TEMPLATE', 'DEFAULT_SERVER_UNITS', 'SECRET_HINTS', 'SERVER_UNIT_EXPLICIT', '_agents_cache', '_config_files', '_cpu_lock', '_cpu_prev', '_engine_error', '_engine_mcp_names', '_extract_oauth_code', '_fill', '_install_home', '_mask_secrets', '_merge_secrets', '_normalize_mcp_entry', '_parse_frontmatter', '_pending', '_release_cache', '_semver', '_stored_key', '_unit_active', '_validate_mcp', 'add_mcp_entry', 'agents_dir', 'config_snapshot', 'cpu_pct', 'delete_agent_file', 'engine_started_at', 'engine_status', 'find_runtime', 'get_agents', 'get_connections', 'get_status', 'install_from_catalog', 'installed_version', 'latest_release', 'list_agent_files', 'mark_pending', 'mcp_catalog', 'mcp_oauth_callback', 'mcp_oauth_remove', 'mcp_oauth_start', 'mcp_status', 'pending_changes', 'provider_current', 'provider_save', 'provider_snapshot', 'provider_test', 'read_agent_file', 'read_agents', 'read_mcp', 'restart_engine', 'server_unit', 'start_update', 'sys_metrics', 'update_running', 'update_status', 'valid_agents', 'version_info', 'write_agent_file', 'write_agents', 'write_mcp']
