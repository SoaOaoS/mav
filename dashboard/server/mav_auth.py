"""Sign-in for the Mav web app: one owner password, signed session cookies.

Stdlib only. The password is stored as a salted PBKDF2-SHA256 hash; a session
is an HMAC-signed cookie (no server-side session table), so restarts keep
people signed in. Changing the password bumps a generation counter that every
cookie carries: all other sessions are signed out at once.

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
import secrets
import threading
import time
from pathlib import Path

COOKIE = "mav_session"
SESSION_DAYS = int(os.environ.get("MAV_SESSION_DAYS", "30"))
PBKDF2_ROUNDS = 240_000
MIN_PASSWORD = 8

# Paths that never need a session: signing in itself, health for `mav
# doctor`, and webhooks (they carry their own token).
PUBLIC_API = ("/api/auth/", "/api/hooks/", "/api/health")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Auth:
    def __init__(self, path: Path, enabled: bool = True):
        self.path = Path(path)
        self.enabled = enabled
        self._lock = threading.Lock()
        self._fails: dict[str, list[float]] = {}

    # ------------------------------------------------------------- storage
    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
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

    # ------------------------------------------------------------- password
    @staticmethod
    def _hash(password: str, salt: bytes) -> str:
        return _b64(hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS))

    def configured(self) -> bool:
        return bool(self._load().get("hash"))

    def set_password(self, password: str) -> None:
        if len(password or "") < MIN_PASSWORD:
            raise ValueError(f"Use at least {MIN_PASSWORD} characters.")
        with self._lock:
            data = self._load()
            salt = secrets.token_bytes(16)
            data.update(
                salt=_b64(salt),
                hash=self._hash(password, salt),
                gen=int(data.get("gen", 0)) + 1,
                secret=data.get("secret") or _b64(secrets.token_bytes(32)),
                changed=int(time.time()),
            )
            self._save(data)

    def check_password(self, password: str) -> bool:
        data = self._load()
        if not data.get("hash"):
            return False
        got = self._hash(password or "", _unb64(data["salt"]))
        return hmac.compare_digest(got, data["hash"])

    # ------------------------------------------------------------- sessions
    def issue(self) -> str:
        data = self._load()
        payload = _b64(json.dumps(
            {"g": data.get("gen", 1), "exp": int(time.time()) + SESSION_DAYS * 86400,
             "n": secrets.token_hex(4)}
        ).encode())
        sig = _b64(hmac.new(self._secret(data), payload.encode(), hashlib.sha256).digest())
        return f"{payload}.{sig}"

    def valid(self, token: str) -> bool:
        if not token or "." not in token:
            return False
        data = self._load()
        if not data.get("secret"):
            return False
        payload, _, sig = token.partition(".")
        want = _b64(hmac.new(self._secret(data), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(want, sig):
            return False
        try:
            claims = json.loads(_unb64(payload))
        except Exception:  # noqa: BLE001
            return False
        return claims.get("g") == data.get("gen") and claims.get("exp", 0) > time.time()

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

    def state(self, cookie_header: str) -> dict:
        configured = self.configured()
        return {
            "enabled": self.enabled,
            "setup_needed": self.enabled and not configured,
            "authenticated": (not self.enabled) or (not configured)
            or self.valid(self.cookie_token(cookie_header)),
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
        self._fails.setdefault(who, []).append(time.time())

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
