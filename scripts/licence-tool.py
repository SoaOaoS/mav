#!/usr/bin/env python3
"""Issue and check Mav licence keys (vendor side).

    # once: a signing key pair (keep the private key secret, out of the repo)
    scripts/licence-tool.py keygen --out mav-licence-private.key
    # then set PUBLIC_KEY in dashboard/server/mav_licence.py to the printed value

    # issue a Mav Connect key for a customer, valid one year
    scripts/licence-tool.py issue --key mav-licence-private.key \\
        --email jane@example.com --plan connect --days 365

    # check any key against the built-in public key
    scripts/licence-tool.py check MAV1.xxxxx.yyyyy

Issuing is meant to be wired to the payment provider's "order paid" webhook
(see docs/BUSINESS.md); this tool is the manual and scripted path.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard" / "server"))
import mav_licence  # noqa: E402


def keygen(out: Path) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if out.exists():
        sys.exit(f"{out} exists — refusing to overwrite a signing key.")
    k = Ed25519PrivateKey.generate()
    raw = k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                          serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    out.write_text(base64.urlsafe_b64encode(raw).decode().rstrip("=") + "\n")
    os.chmod(out, 0o600)
    print("public key:", base64.urlsafe_b64encode(pub).decode().rstrip("="))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("keygen")
    g.add_argument("--out", type=Path, required=True)
    i = sub.add_parser("issue")
    i.add_argument("--key", type=Path, required=True, help="private key file")
    i.add_argument("--email", required=True)
    i.add_argument("--plan", default="connect", choices=sorted(mav_licence.PLANS))
    i.add_argument("--days", type=int, default=365, help="0 = never expires")
    c = sub.add_parser("check")
    c.add_argument("licence")
    a = ap.parse_args()

    if a.cmd == "keygen":
        keygen(a.out)
    elif a.cmd == "issue":
        payload = {"email": a.email, "plan": a.plan, "id": secrets.token_hex(6),
                   "iat": int(time.time())}
        if a.days:
            payload["exp"] = int(time.time()) + a.days * 86400
        print(mav_licence.sign(payload, a.key.read_text()))
    else:
        print(json.dumps(mav_licence.verify(a.licence), indent=2))


if __name__ == "__main__":
    main()
