"""Backup and restore, from the web app (Settings → General → Backup).

A backup is one ``.tar.gz``::

    manifest.json              format, version, date, what is inside
    db/<table>.csv             every Mav table (COPY … CSV HEADER)
    bot/…                      routines, password, keys, usage, media…
    opencode-config/…          model, helpers, connections, instructions
    opencode-storage/…         chat history (optional)
    config/server.env          API keys

It works the same with the installer and with Docker: the database goes
through psycopg2 (no pg_dump needed), files are read where the running app
finds them. Restoring checks every entry (no absolute path, no "..", regular
files only, known folders), saves a backup of the current state first, then
replaces the tables in one transaction.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable

FORMAT = 1
TABLES = (
    "conversations", "facts", "preferences", "watch_items", "documents",
    "notifications", "events", "notify_digest", "drafts", "actions", "interests",
)
MAX_FILE = 50 * 1024 * 1024          # a single file larger than this is skipped
MAX_UPLOAD = 512 * 1024 * 1024       # a backup larger than this is refused
KEEP_SAFETY = 3                      # pre-restore backups kept in bot/backups
_SKIP_DIRS = {"venv", "__pycache__", "node_modules", "backups", ".git"}
_SKIP_SUFFIX = {".py", ".pyc", ".log", ".tmp"}
_SKIP_NAMES = {"requirements.txt", "README.md"}
ROOTS = ("db", "bot", "opencode-config", "opencode-storage", "config")


@dataclass
class Places:
    """Where the running install keeps things."""
    dsn: str
    bot_dir: Path
    config_dir: Path
    storage_dir: Path
    env_server: Path
    version: str = ""
    runtime: str = ""
    chown: Callable[[Path], None] | None = None
    skipped: list = field(default_factory=list)


# ------------------------------------------------------------------ helpers
def _connect(dsn: str):
    import psycopg2  # noqa: PLC0415

    return psycopg2.connect(dsn, connect_timeout=5)


def _columns(cur, table: str) -> list[str]:
    """Columns that can be written back (generated ones are rebuilt)."""
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s AND is_generated = 'NEVER' "
        "ORDER BY ordinal_position",
        (table,),
    )
    return [r[0] for r in cur.fetchall()]


def _walk(root: Path, places: Places):
    """Files under root worth saving: data, never code or caches."""
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            p = Path(dirpath) / name
            if name in _SKIP_NAMES or p.suffix in _SKIP_SUFFIX or p.is_symlink() or not p.is_file():
                continue
            if p.stat().st_size > MAX_FILE:
                places.skipped.append(str(p.relative_to(root)))
                continue
            yield p


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = int(time.time())
    info.mode = 0o600
    tar.addfile(info, io.BytesIO(data))


# ------------------------------------------------------------------ create
def create(places: Places, out, *, include_chats: bool = True) -> dict:
    """Write a backup to the binary file object `out`. Returns its manifest."""
    manifest = {
        "format": FORMAT, "app": "mav", "version": places.version, "runtime": places.runtime,
        "created": int(time.time()), "tables": {}, "parts": [], "skipped": [],
    }
    with tarfile.open(fileobj=out, mode="w:gz", compresslevel=6) as tar:
        # The database, table by table.
        try:
            conn = _connect(places.dsn)
        except Exception as exc:  # noqa: BLE001
            manifest["db_error"] = str(exc)[:200]
            conn = None
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    for table in TABLES:
                        cols = _columns(cur, table)
                        if not cols:
                            continue
                        buf = io.StringIO()
                        col_sql = ", ".join(f'"{c}"' for c in cols)
                        cur.copy_expert(f'COPY (SELECT {col_sql} FROM "{table}" ORDER BY 1) TO STDOUT WITH CSV HEADER', buf)
                        data = buf.getvalue().encode()
                        _add_bytes(tar, f"db/{table}.csv", data)
                        manifest["tables"][table] = max(cur.rowcount, 0)
                manifest["parts"].append("db")
            finally:
                conn.close()

        def add_tree(root: Path, prefix: str) -> None:
            n = 0
            for p in _walk(root, places):
                tar.add(str(p), arcname=f"{prefix}/{p.relative_to(root).as_posix()}", recursive=False)
                n += 1
            if n:
                manifest["parts"].append(prefix)

        add_tree(places.bot_dir, "bot")
        add_tree(places.config_dir, "opencode-config")
        if include_chats:
            add_tree(places.storage_dir, "opencode-storage")
        if places.env_server.is_file():
            tar.add(str(places.env_server), arcname="config/server.env", recursive=False)
            manifest["parts"].append("config")
        manifest["skipped"] = places.skipped[:50]
        _add_bytes(tar, "manifest.json", json.dumps(manifest, indent=2).encode())
    return manifest


# ------------------------------------------------------------------ restore
class BackupError(ValueError):
    pass


def _safe_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = []
    for m in tar.getmembers():
        path = PurePosixPath(m.name)
        if m.isdir():
            continue
        if not m.isfile():
            raise BackupError(f"Unexpected entry in the backup: {m.name}")
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise BackupError(f"Unsafe path in the backup: {m.name}")
        if path.parts[0] not in ROOTS and m.name != "manifest.json":
            raise BackupError(f"Unknown part in the backup: {m.name}")
        if path.parts[0] == "config" and m.name != "config/server.env":
            raise BackupError(f"Unknown file in the backup: {m.name}")
        if path.parts[0] == "db" and (len(path.parts) != 2 or path.stem not in TABLES or path.suffix != ".csv"):
            raise BackupError(f"Unknown table in the backup: {m.name}")
        members.append(m)
    return members


def inspect(data: bytes) -> dict:
    """The manifest of a backup, after checking it is one."""
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            _safe_members(tar)
            f = tar.extractfile("manifest.json")
            manifest = json.loads(f.read()) if f else None
    except BackupError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BackupError("This file is not a Mav backup.") from exc
    if not isinstance(manifest, dict) or manifest.get("app") != "mav":
        raise BackupError("This file is not a Mav backup.")
    if int(manifest.get("format") or 0) > FORMAT:
        raise BackupError("This backup comes from a newer Mav: update first.")
    return manifest


def _write(dest: Path, data: bytes, places: Places) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".restore-")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.chmod(tmp, 0o600)
    os.replace(tmp, dest)
    if places.chown:
        places.chown(dest)


def _restore_tables(places: Places, tables: dict[str, bytes]) -> dict:
    if not tables:
        return {}
    conn = _connect(places.dsn)
    counts = {}
    try:
        with conn, conn.cursor() as cur:
            present = {t: _columns(cur, t) for t in tables}
            present = {t: c for t, c in present.items() if c}
            if present:
                cur.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in present) + " RESTART IDENTITY")
            for table, cols in present.items():
                data = tables[table]
                header = data.split(b"\n", 1)[0].decode().strip()
                names = [h.strip().strip('"') for h in header.split(",")] if header else []
                if not names:
                    continue
                unknown = [n for n in names if n not in cols]
                if unknown:
                    raise BackupError(f"Table {table} has unknown columns: {', '.join(unknown)}")
                col_sql = ", ".join(f'"{c}"' for c in names)
                cur.copy_expert(f'COPY "{table}" ({col_sql}) FROM STDIN WITH CSV HEADER', io.BytesIO(data))
                counts[table] = cur.rowcount
                if "id" in names:
                    cur.execute(
                        f"SELECT setval(pg_get_serial_sequence('\"{table}\"', 'id'), "
                        f'coalesce((SELECT max(id) FROM "{table}"), 0) + 1, false)'
                    )
    finally:
        conn.close()
    return counts


def restore(places: Places, data: bytes) -> dict:
    """Replace the current state with a backup. Saves the current state first."""
    if len(data) > MAX_UPLOAD:
        raise BackupError("This backup is too large.")
    manifest = inspect(data)

    # A safety copy of what we are about to replace.
    safety_dir = places.bot_dir / "backups"
    safety_dir.mkdir(parents=True, exist_ok=True)
    safety = safety_dir / time.strftime("pre-restore-%Y%m%d-%H%M%S.tar.gz")
    with open(safety, "wb") as fh:
        create(places, fh, include_chats=True)
    os.chmod(safety, 0o600)
    for old in sorted(safety_dir.glob("pre-restore-*.tar.gz"))[:-KEEP_SAFETY]:
        old.unlink(missing_ok=True)

    tables: dict[str, bytes] = {}
    writes: list[tuple[Path, bytes]] = []
    targets = {
        "bot": places.bot_dir,
        "opencode-config": places.config_dir,
        "opencode-storage": places.storage_dir,
    }
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in _safe_members(tar):
            path = PurePosixPath(m.name)
            f = tar.extractfile(m)
            blob = f.read() if f else b""
            if path.parts[0] == "db":
                tables[path.stem] = blob
            elif path.parts[0] == "config":
                writes.append((places.env_server, blob))
            elif path.parts[0] in targets:
                writes.append((targets[path.parts[0]].joinpath(*path.parts[1:]), blob))
    # The database first, in one transaction: if it fails, no file has moved.
    counts = _restore_tables(places, tables) if tables else {}
    for dest, blob in writes:
        _write(dest, blob, places)
    return {
        "ok": True, "files": len(writes), "tables": counts, "safety": safety.name,
        "from": {"version": manifest.get("version"), "created": manifest.get("created")},
    }


def safety_copies(places: Places) -> list[dict]:
    d = places.bot_dir / "backups"
    return [
        {"name": p.name, "size": p.stat().st_size, "ts": int(p.stat().st_mtime)}
        for p in sorted(d.glob("pre-restore-*.tar.gz"), reverse=True)
    ] if d.is_dir() else []


def copy_to(src: Path, out) -> None:
    with open(src, "rb") as fh:
        shutil.copyfileobj(fh, out)
