"""Plans and licence keys: Mav Free and Mav Pro.

Mav stays open source and fully usable for free. Free has generous limits on
the things that run on their own (routines, "keep an eye on" items); Pro lifts
them. Nothing that already exists is ever switched off: going over a limit
only blocks creating *new* items.

A licence key is checked offline — no call home, no account server:

    MAV1.<base64url(JSON payload)>.<base64url(Ed25519 signature)>

The payload says who it is for, which plan, and until when. The public key is
built in (override with MAV_LICENCE_PUBKEY); keys are issued with
`scripts/licence-tool.py` and the matching private key, which never ships.
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

# Public half of the signing key (Ed25519, raw, base64url).
PUBLIC_KEY = os.environ.get("MAV_LICENCE_PUBKEY", "XzZKcHvh7D5w-Jyh-qcoYFvkJ4nab1fHLIRSBf9ltcE")
CHECKOUT_URL = os.environ.get("MAV_CHECKOUT_URL", "https://soaoaos.github.io/mav/pricing.html")
PREFIX = "MAV1"

# None = unlimited. The daily briefing is never counted: it is free for all.
PLANS = {
    "free": {"label": "Free", "routines": 5, "watch": 5},
    "pro": {"label": "Pro", "routines": None, "watch": None},
}
PRO_PERKS = [
    "Unlimited routines",
    "Unlimited “keep an eye on” items",
    "Priority support and early features",
    "Funds Mav’s development — thank you",
]


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(payload: dict, private_key_b64: str) -> str:
    """Issue a key (vendor side; needs the private key)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: PLC0415

    body = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    key = Ed25519PrivateKey.from_private_bytes(_b64d(private_key_b64.strip()))
    sig = _b64e(key.sign(f"{PREFIX}.{body}".encode()))
    return f"{PREFIX}.{body}.{sig}"


def verify(key: str, public_key_b64: str | None = None, now: float | None = None) -> dict:
    """{valid, plan, email, expires, reason} for a licence key."""
    out = {"valid": False, "plan": "free", "email": "", "expires": None, "reason": ""}
    key = (key or "").strip()
    parts = key.split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        out["reason"] = "This does not look like a Mav licence key."
        return out
    try:
        from cryptography.exceptions import InvalidSignature  # noqa: PLC0415
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        out["reason"] = "Licence check unavailable (the cryptography package is missing)."
        return out
    try:
        sig = _b64d(parts[2])
        # One spelling per key: base64 leaves spare bits in the last character,
        # so a re-encoded (canonical) signature must match what was pasted.
        if _b64e(sig) != parts[2]:
            raise InvalidSignature()
        pub = Ed25519PublicKey.from_public_bytes(_b64d(public_key_b64 or PUBLIC_KEY))
        pub.verify(sig, f"{parts[0]}.{parts[1]}".encode())
        payload = json.loads(_b64d(parts[1]))
    except InvalidSignature:
        out["reason"] = "This licence key is not valid."
        return out
    except Exception:  # noqa: BLE001
        out["reason"] = "This licence key is damaged — copy it again in full."
        return out
    plan = payload.get("plan") if payload.get("plan") in PLANS else "free"
    exp = payload.get("exp")
    out.update(plan=plan, email=str(payload.get("email") or ""), expires=exp,
               id=str(payload.get("id") or ""))
    if exp and float(exp) < (now or time.time()):
        out.update(plan="free", reason="This licence has expired — renew it to keep Pro.")
        out["expired"] = True
        return out
    out["valid"] = True
    return out


class Licence:
    def __init__(self, path: Path):
        self.path = Path(path)

    def key(self) -> str:
        try:
            return str(json.loads(self.path.read_text()).get("key") or "")
        except Exception:  # noqa: BLE001
            return ""

    def save(self, key: str) -> dict:
        info = verify(key)
        if not info["valid"]:
            return {"ok": False, "error": info["reason"]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"key": key.strip(), "added": int(time.time())}))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)
        return {"ok": True, **info}

    def remove(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def current(self) -> dict:
        key = self.key()
        if not key:
            return {"valid": False, "plan": "free", "email": "", "expires": None, "reason": ""}
        return verify(key)

    def plan(self) -> str:
        return self.current()["plan"]

    def limit(self, what: str) -> int | None:
        return PLANS[self.plan()].get(what)

    def allows(self, what: str, current_count: int) -> bool:
        """May one more `what` be created when `current_count` exist?"""
        lim = self.limit(what)
        return lim is None or current_count < lim
