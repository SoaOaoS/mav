"""Plans and licence keys: Mav (free) and Mav Connect.

Mav is open source and free without limits on your own machine — nothing in
this module restricts what the app does. Mav Connect is a subscription to
services that run on Mav's infrastructure (encrypted cloud backup first,
then remote access and the mobile app); its licence key is what those
services check, server-side. That is the part a patched install cannot fake.

A licence key is also checked offline here, to show the plan in the app:

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

# Mav itself has no limits, on any plan. Plans differ only by the services
# they include (see CONNECT_SERVICES). "pro" keys (first edition) = Connect.
PLANS = {
    "free": {"label": "Mav", "services": []},
    "connect": {"label": "Connect", "services": ["backup"]},
    "business": {"label": "Business", "services": ["backup"]},
}
ALIASES = {"pro": "connect"}
CONNECT_SERVICES = [
    {"id": "backup", "label": "Encrypted cloud backup", "status": "live",
     "detail": "Daily, encrypted on this machine before it leaves — restore anywhere."},
    {"id": "remote", "label": "Secure remote access", "status": "soon",
     "detail": "Your Mav at your own address, from anywhere, without opening a port."},
    {"id": "mobile", "label": "Native mobile app", "status": "soon",
     "detail": "Real iPhone and Android notifications, widgets, share to Mav."},
    {"id": "support", "label": "Priority support", "status": "live",
     "detail": "Answers from the people who build Mav."},
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
    plan = ALIASES.get(payload.get("plan"), payload.get("plan"))
    plan = plan if plan in PLANS else "free"
    exp = payload.get("exp")
    out.update(plan=plan, email=str(payload.get("email") or ""), expires=exp,
               id=str(payload.get("id") or ""))
    if exp and float(exp) < (now or time.time()):
        out.update(plan="free", reason="This licence has expired — renew Mav Connect to keep its services.")
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

    def has(self, service: str) -> bool:
        """Does the current licence include this Connect service?"""
        return service in PLANS[self.plan()]["services"]
