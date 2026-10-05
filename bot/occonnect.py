"""Mav Connect — encrypted cloud backup (client side).

What is backed up: the Postgres database (memory, alerts, drafts,
interests…), the chat history kept by the engine, routines and settings,
the engine config (custom instructions, helpers, connections). Not the
licence, not the recovery key, not the service env files with API keys.

How: everything goes into one tar.gz, encrypted HERE with AES-256-GCM under
a key derived (scrypt) from the user's **recovery key**, then uploaded to
the Mav Connect service with the licence key as the credential. The service
only ever sees ciphertext; the recovery key never leaves this machine — so
restoring on a new machine needs it (the app shows it, to keep safe).

Format: b"MAVBK1" | salt(16) | nonce(12) | AES-GCM(ciphertext + tag).
"""

from __future__ import annotations

import base64
import fcntl
import io
import json
import os
import secrets
import socket
import tarfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

# The deployed Connect service (connect/README.md). MAV_CONNECT_URL overrides.
DEFAULT_CONNECT_URL = ""
MAGIC = b"MAVBK1"
MAX_ARCHIVE = 90 * 1024 * 1024
# BOT_DIR files never put in a backup (secrets that belong to this machine).
SKIP_BOT_FILES = {"connect.json", "licence.json", "connect.lock"}


def connect_url() -> str:
    return (os.environ.get("MAV_CONNECT_URL") or DEFAULT_CONNECT_URL).rstrip("/")


# ----------------------------------------------------------------- crypto
def _derive(recovery_key: str, salt: bytes) -> bytes:
    import hashlib

    norm = recovery_key.replace("-", "").replace(" ", "").upper().encode()
    return hashlib.scrypt(norm, salt=salt, n=2**15, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)


def encrypt(data: bytes, recovery_key: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    return MAGIC + salt + nonce + AESGCM(_derive(recovery_key, salt)).encrypt(nonce, data, MAGIC)


def decrypt(blob: bytes, recovery_key: str) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 28:
        raise ValueError("This is not a Mav backup.")
    salt = blob[len(MAGIC):len(MAGIC) + 16]
    nonce = blob[len(MAGIC) + 16:len(MAGIC) + 28]
    try:
        return AESGCM(_derive(recovery_key, salt)).decrypt(nonce, blob[len(MAGIC) + 28:], MAGIC)
    except InvalidTag:
        raise ValueError("Wrong recovery key (or a damaged backup).") from None


def new_recovery_key() -> str:
    """24 base32 characters in groups of 4 — easy to write down."""
    raw = base64.b32encode(secrets.token_bytes(15)).decode().rstrip("=")
    return "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


# ----------------------------------------------------------------- service
class ConnectError(Exception):
    pass


def _call(method: str, path: str, licence_key: str, body: bytes | None = None,
          timeout: float = 120) -> bytes:
    base = connect_url()
    if not base:
        raise ConnectError("Mav Connect is not set up on this machine yet.")
    if not licence_key:
        raise ConnectError("Add your Mav Connect licence key first (Settings → Plan).")
    req = urllib.request.Request(f"{base}{path}", data=body, method=method)
    req.add_header("Authorization", f"Bearer {licence_key}")
    if body is not None:
        req.add_header("Content-Type", "application/octet-stream")
        req.add_header("Content-Length", str(len(body)))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        try:
            msg = json.loads(exc.read().decode()).get("error") or ""
        except Exception:  # noqa: BLE001
            msg = ""
        raise ConnectError({
            401: f"Mav Connect refused the licence key ({msg or 'invalid'}).",
            413: "This backup is too large for your Mav Connect space.",
        }.get(exc.code, f"Mav Connect answered HTTP {exc.code}{': ' + msg if msg else ''}.")) from None
    except Exception as exc:  # noqa: BLE001
        raise ConnectError(f"Cannot reach Mav Connect: {getattr(exc, 'reason', exc)}") from None


# ----------------------------------------------------------------- backups
class Backup:
    def __init__(self, bot_dir: Path, dsn: str = "", home: Path | None = None):
        self.bot_dir = Path(bot_dir)
        self.dsn = dsn
        self.home = Path(home or os.environ.get("MAV_USER_HOME") or Path.home())
        self.state_path = self.bot_dir / "connect.json"

    # ---- local state (recovery key, last backup) -------------------------
    def _state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text())
        except Exception:  # noqa: BLE001
            return {}

    def _save_state(self, data: dict) -> None:
        self.bot_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        os.chmod(tmp, 0o600)
        tmp.replace(self.state_path)

    def recovery_key(self) -> str:
        st = self._state()
        if not st.get("recovery_key"):
            st["recovery_key"] = new_recovery_key()
            self._save_state(st)
        return st["recovery_key"]

    def last(self) -> dict:
        return self._state().get("last") or {}

    def licence_key(self) -> str:
        try:
            return str(json.loads((self.bot_dir / "licence.json").read_text()).get("key") or "")
        except Exception:  # noqa: BLE001
            return ""

    @contextmanager
    def _lock(self):
        self.bot_dir.mkdir(parents=True, exist_ok=True)
        with open(self.bot_dir / "connect.lock", "a+") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ConnectError("A backup or restore is already running.") from None
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    # ---- what goes in ----------------------------------------------------
    def _dirs(self) -> dict[str, Path]:
        return {
            "bot": self.bot_dir,
            "opencode-config": self.home / ".config" / "opencode",
            "opencode-data": self.home / ".local" / "share" / "opencode" / "storage",
        }

    def _dump_db(self, tar: tarfile.TarFile) -> list[str]:
        if not self.dsn:
            return []
        try:
            import psycopg2
        except Exception:  # noqa: BLE001
            return []
        try:
            conn = psycopg2.connect(self.dsn, connect_timeout=5)
        except Exception:  # noqa: BLE001
            return []
        tables = []
        try:
            cur = conn.cursor()
            cur.execute(
                "select table_name from information_schema.tables "
                "where table_schema = 'public' and table_type = 'BASE TABLE' order by table_name"
            )
            for (name,) in cur.fetchall():
                buf = io.BytesIO()
                cur.copy_expert(f'COPY public."{name}" TO STDOUT WITH (FORMAT csv, HEADER true)', buf)
                _add_bytes(tar, f"db/{name}.csv", buf.getvalue())
                tables.append(name)
        finally:
            conn.close()
        return tables

    def build_archive(self) -> tuple[bytes, dict]:
        buf = io.BytesIO()
        manifest = {"format": 1, "created": int(time.time()), "host": socket.gethostname(),
                    "tables": [], "dirs": {}}
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            manifest["tables"] = self._dump_db(tar)
            for label, root in self._dirs().items():
                if not root.is_dir():
                    continue
                count = 0
                for path in sorted(root.rglob("*")):
                    if not path.is_file() or path.is_symlink():
                        continue
                    rel = path.relative_to(root)
                    if label == "bot" and (
                        rel.parts[0] in ("venv", "__pycache__", "mav-media") or rel.suffix == ".py"
                        or rel.name in SKIP_BOT_FILES or rel.suffix in (".tmp", ".lock")
                    ):
                        continue
                    tar.add(str(path), arcname=f"files/{label}/{rel}", recursive=False)
                    count += 1
                manifest["dirs"][label] = count
            _add_bytes(tar, "manifest.json", json.dumps(manifest).encode())
        data = buf.getvalue()
        if len(data) > MAX_ARCHIVE:
            raise ConnectError(f"The backup is {len(data) // 2**20} MB — over the 90 MB a backup can hold.")
        return data, manifest

    # ---- cloud -----------------------------------------------------------
    def status(self) -> dict:
        return json.loads(_call("GET", "/v1/status", self.licence_key(), timeout=20))

    def backup_now(self) -> dict:
        with self._lock():
            started = time.time()
            archive, manifest = self.build_archive()
            blob = encrypt(archive, self.recovery_key())
            res = json.loads(_call("PUT", "/v1/backups", self.licence_key(), blob, timeout=600))
            last = {"at": int(time.time()), "id": res.get("id"), "size": len(blob),
                    "seconds": round(time.time() - started, 1), "tables": len(manifest["tables"])}
            st = self._state()
            st["last"] = last
            self._save_state(st)
            return last

    def due(self, hours: float = 20) -> bool:
        """Daily backup due? (with a licence and a configured service)"""
        if not (connect_url() and self.licence_key()):
            return False
        return time.time() - int(self.last().get("at") or 0) >= hours * 3600

    def restore(self, backup_id: str, recovery_key: str = "") -> dict:
        """Put a backup back in place. Restart Mav afterwards."""
        with self._lock():
            blob = _call("GET", f"/v1/backups/{backup_id}", self.licence_key(), timeout=600)
            archive = decrypt(blob, recovery_key or self.recovery_key())
            return self.restore_archive(archive, recovery_key)

    def restore_archive(self, archive: bytes, recovery_key: str = "") -> dict:
        dirs = self._dirs()
        restored_files, tables = 0, []
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            for m in tar.getmembers():
                if not m.isfile():
                    continue
                parts = Path(m.name).parts
                if len(parts) >= 3 and parts[0] == "files" and parts[1] in dirs:
                    rel = Path(*parts[2:])
                    if ".." in rel.parts or rel.is_absolute():
                        continue  # never write outside the target folders
                    dest = dirs[parts[1]] / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(tar.extractfile(m).read())
                    restored_files += 1
                elif len(parts) == 2 and parts[0] == "db" and parts[1].endswith(".csv"):
                    tables.append((parts[1][:-4], tar.extractfile(m).read()))
        self._restore_db(tables)
        if recovery_key:
            # The machine adopts the key the backup was made with.
            st = self._state()
            st["recovery_key"] = recovery_key
            self._save_state(st)
        return {"ok": True, "files": restored_files, "tables": [t for t, _ in tables],
                "restart": True}

    def _restore_db(self, tables: list[tuple[str, bytes]]) -> None:
        if not tables or not self.dsn:
            return
        import psycopg2

        conn = psycopg2.connect(self.dsn, connect_timeout=5)
        try:
            cur = conn.cursor()
            cur.execute("select table_name from information_schema.tables where table_schema = 'public'")
            existing = {r[0] for r in cur.fetchall()}
            for name, data in tables:
                if name not in existing or not name.replace("_", "").isalnum():
                    continue
                cur.execute(f'TRUNCATE public."{name}" CASCADE')
                cur.copy_expert(f'COPY public."{name}" FROM STDIN WITH (FORMAT csv, HEADER true)',
                                io.BytesIO(data))
                # Serial ids continue after the restored rows.
                cur.execute(
                    "select column_name from information_schema.columns where table_schema = 'public' "
                    "and table_name = %s and column_default like 'nextval(%%'", (name,))
                for (col,) in cur.fetchall():
                    cur.execute(
                        f'select setval(pg_get_serial_sequence(%s, %s), '
                        f'coalesce((select max("{col}") from public."{name}"), 0) + 1, false)',
                        (f"public.{name}", col))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = int(time.time())
    info.mode = 0o600
    tar.addfile(info, io.BytesIO(data))
