"""Configuration, optional modules and small shared helpers (paths, Postgres,
JSON files, subprocesses). Imported first by every other module.

Part of the web app server (see mav_api.py).
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


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


# Files people send in the chat (not under /tmp: the web app may run as root).
ATTACH_DIR = Path(os.environ.get("MAV_ATTACH", BOT_DIR / "attachments"))


PUSH_FILE = Path(os.environ.get("MAV_PUSH_FILE", BOT_DIR / "push_subs.json"))


OPENCODE_URL = os.environ.get("OPENCODE_URL", "http://127.0.0.1:4096").rstrip("/")


PG_DSN = os.environ.get(
    "PG_DSN", "host=127.0.0.1 port=5432 user=mav password=mav_secret dbname=mav"
)


# The helper used when none is picked: the everyday "assistant" (orchestrator).
DEFAULT_AGENT = os.environ.get("MAV_DASH_AGENT", "").strip() or "assistant"


DEFAULT_MODEL = os.environ.get("OPENCODE_MODEL", "").strip()


# The engine's password (opencode's OPENCODE_SERVER_PASSWORD): every call to
# OPENCODE_URL carries it, so nothing else that reaches the engine (the
# assistant's own web fetch included) can read the chats.
if os.environ.get("OPENCODE_SERVER_PASSWORD"):
    _engine_auth = urllib.request.HTTPPasswordMgrWithPriorAuth()
    _engine_auth.add_password(None, OPENCODE_URL, os.environ.get("OPENCODE_SERVER_USERNAME", "opencode"),
                              os.environ["OPENCODE_SERVER_PASSWORD"], is_authenticated=True)
    urllib.request.install_opener(
        urllib.request.build_opener(urllib.request.HTTPBasicAuthHandler(_engine_auth)))


# Owner id: memory, facts and watch items are attached to it (kept from the
# chat id of older installs, so existing memory stays attached).
DEFAULT_CHAT_ID = int(os.environ.get("MAV_CHAT_ID", "0") or 0)


# Who the current request (or the work it started) is for: the owner's id or
# a family member's (mav_auth). Per thread, set by the HTTP handler; work
# handed to another thread carries it along through `spawn`.
_who = threading.local()


def uid() -> int:
    return getattr(_who, "uid", DEFAULT_CHAT_ID)


def is_owner() -> bool:
    return uid() == DEFAULT_CHAT_ID


@contextlib.contextmanager
def as_user(user: int):
    prev = getattr(_who, "uid", None)
    _who.uid = int(user)
    try:
        yield
    finally:
        if prev is None:
            del _who.uid
        else:
            _who.uid = prev


def mine(col: str = "chat_id") -> tuple[str, tuple]:
    """SQL condition for the current user's rows. The owner also keeps rows
    with no owner (older installs, system notices)."""
    if is_owner():
        return f"({col} = %s or {col} is null)", (DEFAULT_CHAT_ID,)
    return f"{col} = %s", (uid(),)


def spawn(target, *args, **kwargs) -> threading.Thread:
    """Start `target` in a daemon thread, as the current user."""
    user = uid()

    def run():
        with as_user(user):
            target(*args, **kwargs)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


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


try:
    import occhannels  # noqa: E402

    occhannels.CHANNELS_FILE = Path(os.environ.get("MAV_CHANNELS_FILE", BOT_DIR / "channels.json"))
except Exception:  # noqa: BLE001
    occhannels = None


import mav_backup  # noqa: E402


try:
    import occalendar  # noqa: E402

    occalendar.CALENDAR_FILE = Path(os.environ.get("MAV_CALENDAR_FILE", BOT_DIR / "calendar.json"))
except Exception:  # noqa: BLE001
    occalendar = None


import mav_provider  # noqa: E402


# Sign-in (the owner and family members). MAV_AUTH=off disables it, e.g. behind your own
# authenticating proxy.
AUTH = mav_auth.Auth(
    Path(os.environ.get("MAV_AUTH_FILE", BOT_DIR / "auth.json")),
    enabled=os.environ.get("MAV_AUTH", "on").lower() not in ("off", "0", "false", "no"),
    owner_id=DEFAULT_CHAT_ID,
)


# Agents offered in the dashboard selector.
# Everyday helpers shipped with Mav, in the order they are offered.
PRIMARY_AGENTS = ["assistant", "researcher", "writer", "planner", "money"]


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


# A few Postgres connections kept open and shared by the request threads,
# instead of a new one (TCP + auth) for every query.
_pg_pool = None
_pg_pool_dsn = ""
_pg_pool_lock = threading.Lock()
PG_POOL_MAX = int(os.environ.get("MAV_PG_POOL", "8"))


def _pg_get_pool():
    import psycopg2.pool

    global _pg_pool, _pg_pool_dsn
    with _pg_pool_lock:
        if _pg_pool is None or _pg_pool_dsn != PG_DSN:
            if _pg_pool is not None:
                _pg_pool.closeall()
            # psycopg2 keeps at most `minconn` idle connections (it closes the
            # others when they come back): two warm ones, up to PG_POOL_MAX.
            _pg_pool = psycopg2.pool.ThreadedConnectionPool(
                min(2, PG_POOL_MAX), PG_POOL_MAX, PG_DSN, connect_timeout=3)
            _pg_pool_dsn = PG_DSN
        return _pg_pool


def _pg_drop_pool(pool) -> None:
    """Forget a pool whose connections the server dropped (it restarted)."""
    global _pg_pool
    with _pg_pool_lock:
        if _pg_pool is pool:
            _pg_pool = None
    try:
        pool.closeall()
    except Exception:  # noqa: BLE001
        pass


def _pg_run(sql: str, params: tuple, fetch: bool):
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool

    for attempt in (1, 2):
        pool = _pg_get_pool()
        try:
            conn, pooled = pool.getconn(), True
        except psycopg2.pool.PoolError:  # all busy: one more, just for this query
            conn, pooled = psycopg2.connect(PG_DSN, connect_timeout=3), False
        broken = False
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()] if fetch and cur.description else []
            conn.commit()
            return rows
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            # The server dropped the connection (restart, idle timeout): start
            # over once with fresh ones.
            broken = True
            if attempt == 2:
                raise
            if pooled:
                _pg_drop_pool(pool)
        except Exception:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                broken = True
            raise
        finally:
            if pooled:
                try:
                    pool.putconn(conn, close=broken or bool(conn.closed))
                except Exception:  # noqa: BLE001  (the pool was closed meanwhile)
                    conn.close()
            else:
                conn.close()
    return []


def pg_query(sql: str, params: tuple = ()) -> list[dict]:
    return _pg_run(sql, params, fetch=True)


def pg_exec(sql: str, params: tuple = ()) -> None:
    _pg_run(sql, params, fetch=False)


def inside(root: Path, name: str) -> Path:
    """`root/name`, refusing any name that would land outside `root` (a
    "..", an absolute path, a symlink pointing away)."""
    base = os.path.realpath(root)
    full = os.path.realpath(os.path.join(base, name))
    if not full.startswith(base + os.sep):
        raise ValueError("path outside its folder")
    return Path(full)


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


# In Docker (docker/entrypoint.sh) there is no systemd: the engine and worker
# containers restart their process when the web app touches a flag file.
RUNTIME = os.environ.get("MAV_RUNTIME", "").strip().lower()


IN_DOCKER = RUNTIME == "docker"


RESTART_FLAG = Path(os.environ.get("MAV_RESTART_FLAG", "/data/run/engine.restart"))


ENGINE_STARTED = Path(os.environ.get("MAV_ENGINE_STARTED", "/data/run/engine.started"))


DOCKER_UPDATE_HINT = (
    "Mav runs in Docker: update it from the machine with "
    "`docker compose pull && docker compose up -d`."
)


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


__all__ = ['inside', 'PG_POOL_MAX', '_pg_pool', '_pg_pool_dsn', '_pg_pool_lock', '_pg_run', '_pg_get_pool', '_pg_drop_pool', '_who', 'as_user', 'is_owner', 'mine', 'spawn', 'uid', 'ACTIONS', 'ATTACH_DIR', 'AUTH', 'Actions', 'BIND', 'BOT_DIR', 'CADENCES', 'CADENCE_DAYS', 'CATALOG_FILE', 'CATEGORIES', 'DEFAULT_AGENT', 'DEFAULT_CHAT_ID', 'DEFAULT_MODEL', 'DOCKER_UPDATE_HINT', 'DRAFTS', 'Drafts', 'ENGINE_STARTED', 'ENV_FILES', 'ENV_SERVER', 'INSTALL_LOG', 'INTERESTS', 'IN_DOCKER', 'Interests', 'JOBS_FILE', 'JOBS_STATE', 'MAV_CLI', 'MAV_REPO', 'MEMORY', 'MEMORY_ENABLED', 'MEMORY_FILE', 'MEMORY_TOP', 'Memory', 'OPENCODE_URL', 'PG_DSN', 'POLARITIES', 'PORT', 'PRIMARY_AGENTS', 'PUSH_FILE', 'RAG', 'RESTART_FLAG', 'ROUTINE_TEMPLATES', 'RUNTIME', 'SESSIONS_META', 'STATIC_DIR', 'TLS_CERT', 'TLS_KEY', 'TLS_PORT', 'USAGE', 'VERSION_FILE', 'WORKER_UNIT', '_RAG', '_chown_user', '_config_dir', '_json_default', '_opencode_config_path', '_p', '_run', 'agents_path', 'http_json', 'mav_auth', 'mav_backup', 'mav_provider', 'ocbriefing', 'occalendar', 'occhannels', 'ocroutine_nl', 'ocroutine_templates', 'ocselfinit', 'ocusage', 'pg_exec', 'pg_query', 'read_json', 'write_json']
