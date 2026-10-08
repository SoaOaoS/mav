"""Sign-in for the Mav web app: an owner and family members, signed cookies.

Stdlib only. Passwords are stored as salted PBKDF2-SHA256 hashes; a session
is an HMAC-signed cookie (no server-side session table), so restarts keep
people signed in. Every account has a generation counter that its cookies
carry: changing a password signs that account out everywhere at once.

The owner is the account created first; it keeps the top-level fields of
auth.json (older installs have only that). Members, added by the owner, live
under "members", each with an id of its own: that id is the `chat_id` their
chats, memory and routines are stored under.

Until a password is created the app stays open (as before this module
existed) and shows a "protect your Mav" screen; from then on every API call
needs a session. `mav password` resets it from the machine itself.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

COOKIE = "mav_session"
SESSION_DAYS = int(os.environ.get("MAV_SESSION_DAYS", "30"))
PBKDF2_ROUNDS = 240_000
MIN_PASSWORD = 8
MAX_MEMBERS = 20
NAME_RE = re.compile(r"^[^\W_][\w .'-]{0,31}$")

# Paths that never need a session: signing in itself, health for `mav
# doctor`, and webhooks (they carry their own token).
PUBLIC_API = ("/api/auth/", "/api/hooks/", "/api/health")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Auth:
    def __init__(self, path: Path, enabled: bool = True, owner_id: int = 0):
        self.path = Path(path)
        self.enabled = enabled
        self.owner_id = int(owner_id)
        self._lock = threading.Lock()
        self._fails: dict[str, list[float]] = {}

    # ------------------------------------------------------------- storage
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def _secret(self, data: dict) -> bytes:
        return _unb64(data["secret"])

    @staticmethod
    def _members(data: dict) -> list[dict]:
        m = data.get("members")
        return [x for x in m if isinstance(x, dict)] if isinstance(m, list) else []

    def _record(self, data: dict, uid: int | None) -> dict | None:
        """The stored account (owner = the top level), or None."""
        if uid is None or uid == self.owner_id:
            return data if data.get("hash") else None
        return next((m for m in self._members(data) if m.get("id") == uid), None)

    # ------------------------------------------------------------- password
    @staticmethod
    def _hash(password: str, salt: bytes) -> str:
        return _b64(hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS))

    def _new_hash(self, rec: dict, password: str) -> None:
        if len(password or "") < MIN_PASSWORD:
            raise ValueError(f"Use at least {MIN_PASSWORD} characters.")
        salt = secrets.token_bytes(16)
        rec.update(salt=_b64(salt), hash=self._hash(password, salt),
                   gen=int(rec.get("gen", 0)) + 1, changed=int(time.time()))

    def _matches(self, rec: dict | None, password: str) -> bool:
        if not rec or not rec.get("hash"):
            # Same work either way: the time taken says nothing about names.
            self._hash(password or "", b"\0" * 16)
            return False
        got = self._hash(password or "", _unb64(rec["salt"]))
        return hmac.compare_digest(got, rec["hash"])

    def configured(self) -> bool:
        return bool(self._load().get("hash"))

    def set_password(self, password: str, uid: int | None = None) -> None:
        """Set the owner's password (uid None) or a member's."""
        with self._lock:
            data = self._load()
            rec = data if uid is None or uid == self.owner_id else self._record(data, uid)
            if rec is None:
                raise ValueError("No such account.")
            self._new_hash(rec, password)
            data["secret"] = data.get("secret") or _b64(secrets.token_bytes(32))
            self._save(data)

    def check_password(self, password: str, uid: int | None = None) -> bool:
        return self._matches(self._record(self._load(), uid), password)

    def login(self, name: str, password: str) -> int | None:
        """The account id for this name and password. No name = the owner."""
        data = self._load()
        name = (name or "").strip().casefold()
        if not name or name == str(data.get("name") or "").casefold():
            rec = data if data.get("hash") else None
        else:
            rec = next((m for m in self._members(data)
                        if str(m.get("name", "")).casefold() == name), None)
        if not self._matches(rec, password):
            return None
        return self.owner_id if rec is data else int(rec["id"])

    # ------------------------------------------------------------- accounts
    def accounts(self) -> list[dict]:
        data = self._load()
        out = [{"id": self.owner_id, "name": data.get("name") or "", "role": "owner"}] if data.get("hash") else []
        out += [{"id": m["id"], "name": m.get("name", ""), "role": "member",
                 "created": m.get("created", 0)} for m in self._members(data)]
        return out

    def account(self, uid: int) -> dict | None:
        return next((a for a in self.accounts() if a["id"] == uid), None)

    def _check_name(self, data: dict, name: str, skip: int | None = None) -> str:
        name = " ".join((name or "").split())
        if not NAME_RE.match(name):
            raise ValueError("Use a name of 1 to 32 letters or digits.")
        taken = [str(data.get("name") or "")] if skip != self.owner_id else []
        taken += [str(m.get("name", "")) for m in self._members(data) if m.get("id") != skip]
        if name.casefold() in {t.casefold() for t in taken if t}:
            raise ValueError("Someone already has that name.")
        return name

    def add_member(self, name: str, password: str) -> dict:
        with self._lock:
            data = self._load()
            if not data.get("hash"):
                raise ValueError("Protect the app with the owner's password first.")
            members = self._members(data)
            if len(members) >= MAX_MEMBERS:
                raise ValueError(f"At most {MAX_MEMBERS} members.")
            rec = {"name": self._check_name(data, name)}
            self._new_hash(rec, password)
            # Ids never come back: a removed member's data cannot reach a new one.
            rec["id"] = max([self.owner_id, int(data.get("last_id") or 0)]
                            + [int(m.get("id", 0)) for m in members]) + 1
            rec["created"] = int(time.time())
            data["last_id"] = rec["id"]
            data["members"] = members + [rec]
            self._save(data)
            return {"id": rec["id"], "name": rec["name"], "role": "member", "created": rec["created"]}

    def rename(self, uid: int, name: str) -> str:
        with self._lock:
            data = self._load()
            rec = self._record(data, uid)
            if rec is None:
                raise ValueError("No such account.")
            rec["name"] = self._check_name(data, name, skip=uid)
            self._save(data)
            return rec["name"]

    def remove_member(self, uid: int) -> bool:
        if uid == self.owner_id:
            return False
        with self._lock:
            data = self._load()
            members = self._members(data)
            keep = [m for m in members if m.get("id") != uid]
            if len(keep) == len(members):
                return False
            data["members"] = keep
            self._save(data)
            return True

    # ------------------------------------------------------------- sessions
    def issue(self, uid: int | None = None) -> str:
        data = self._load()
        rec = self._record(data, uid) or data
        claims = {"g": rec.get("gen", 1), "exp": int(time.time()) + SESSION_DAYS * 86400,
                  "n": secrets.token_hex(4)}
        if uid is not None and uid != self.owner_id:
            claims["u"] = uid
        payload = _b64(json.dumps(claims).encode())
        sig = _b64(hmac.new(self._secret(data), payload.encode(), hashlib.sha256).digest())
        return f"{payload}.{sig}"

    def user_of(self, token: str) -> int | None:
        """The account a session cookie belongs to, or None if invalid."""
        if not token or "." not in token:
            return None
        data = self._load()
        if not data.get("secret"):
            return None
        payload, _, sig = token.partition(".")
        want = _b64(hmac.new(self._secret(data), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(want, sig):
            return None
        try:
            claims = json.loads(_unb64(payload))
            uid = int(claims.get("u", self.owner_id))
        except Exception:  # noqa: BLE001
            return None
        rec = self._record(data, uid)
        if rec is None or claims.get("g") != rec.get("gen") or claims.get("exp", 0) <= time.time():
            return None
        return uid

    def valid(self, token: str) -> bool:
        return self.user_of(token) is not None

    # ------------------------------------------------------------- requests
    @staticmethod
    def cookie_token(cookie_header: str) -> str:
        for part in (cookie_header or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return ""

    def allowed(self, path: str, cookie_header: str) -> bool:
        """May this request go through?"""
        if not self.enabled or not path.startswith("/api/"):
            return True
        if path.startswith(PUBLIC_API):
            return True
        if not self.configured():
            return True  # not protected yet: the app asks to set a password
        return self.valid(self.cookie_token(cookie_header))

    def current(self, cookie_header: str) -> int | None:
        """Who is making this request: an account id, or None (signed out).

        With sign-in off or not set up yet, everyone is the owner."""
        if not self.enabled or not self.configured():
            return self.owner_id
        return self.user_of(self.cookie_token(cookie_header))

    def state(self, cookie_header: str) -> dict:
        configured = self.configured()
        uid = self.current(cookie_header)
        acc = self.account(uid) if uid is not None and configured else None
        return {
            "enabled": self.enabled,
            "setup_needed": self.enabled and not configured,
            "authenticated": uid is not None,
            # Several accounts: the sign-in screen asks for a name too.
            "named": bool(self._members(self._load())),
            "user": acc or ({"id": self.owner_id, "name": "", "role": "owner"} if uid is not None else None),
        }

    @staticmethod
    def set_cookie(token: str, secure: bool, clear: bool = False) -> str:
        attrs = [f"{COOKIE}={'' if clear else token}", "Path=/", "HttpOnly", "SameSite=Lax",
                 f"Max-Age={0 if clear else SESSION_DAYS * 86400}"]
        if secure:
            attrs.append("Secure")
        return "; ".join(attrs)

    # ------------------------------------------------------------- brute force
    def throttled(self, who: str) -> float:
        """Seconds to wait before another attempt from `who` (0 = go ahead)."""
        now = time.time()
        recent = [t for t in self._fails.get(who, []) if now - t < 900]
        self._fails[who] = recent
        if len(recent) < 5:
            return 0.0
        return max(0.0, recent[-1] + min(2 ** (len(recent) - 5), 300) - now)

    def failed(self, who: str) -> None:
        now = time.time()
        if len(self._fails) > 1000:  # many addresses: forget the stale ones
            self._fails = {k: v for k, v in self._fails.items() if v and now - v[-1] < 900}
        self._fails.setdefault(who, []).append(now)

    def succeeded(self, who: str) -> None:
        self._fails.pop(who, None)


if __name__ == "__main__":  # `mav password` calls this
    import getpass
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("auth.json")
    pw = os.environ.get("MAV_NEW_PASSWORD") or getpass.getpass("New password for the Mav app: ")
    if not os.environ.get("MAV_NEW_PASSWORD"):
        if getpass.getpass("Again: ") != pw:
            sys.exit("The two passwords differ.")
    try:
        Auth(target).set_password(pw)
    except ValueError as exc:
        sys.exit(str(exc))
    print("Password set. Every device has to sign in again.")
