"""Read messages and file proper replies.

Reads the same ``mail.conf`` as the assistant (``~/.config/opencode/mail.conf``
or ``MAV_MAIL_CONF``) and, given a message UID, builds a draft that replies to
it *in the thread*: the original ``Message-ID`` is kept so the send adds the
``In-Reply-To`` / ``References`` headers, and ``Reply-To`` is honoured when the
sender set one.

Used by the assistant's ``mail_reply_draft`` tool and by the routines, so a
draft is a real threaded reply — not a fresh email.
"""

from __future__ import annotations

import email
import imaplib
import os
import re
from email.header import decode_header
from pathlib import Path

from ocdrafts import Drafts

__all__ = ["load_config", "fetch_meta", "reply_subject", "make_reply_draft", "CONFIG"]

CONFIG = Path(os.environ.get("MAV_MAIL_CONF", "/home/opencode/.config/opencode/mail.conf"))

_EMAIL_RE = re.compile(r"<([^>]+)>")


def load_config() -> dict:
    cfg: dict[str, str] = {}
    try:
        for line in CONFIG.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    except Exception:  # noqa: BLE001
        pass
    return cfg


def _decode(s: str) -> str:
    if not s:
        return ""
    out = []
    for part, enc in decode_header(s):
        out.append(part.decode(enc or "utf-8", "replace") if isinstance(part, bytes) else part)
    return "".join(out)


def _addr(value: str) -> str:
    """The bare email address from a header like `Name <a@b.fr>`."""
    if not value:
        return ""
    m = _EMAIL_RE.search(value)
    return (m.group(1) if m else value).strip()


def fetch_meta(uid: str, cfg: dict | None = None) -> dict | None:
    """From / Reply-To / Subject / Message-ID / Date for a message UID."""
    cfg = cfg or load_config()
    if not all(cfg.get(k) for k in ("MAIL_IMAP_SERVER", "MAIL_USER", "MAIL_PASS")):
        return None
    m = imaplib.IMAP4_SSL(cfg["MAIL_IMAP_SERVER"], timeout=15)
    try:
        m.login(cfg["MAIL_USER"], cfg["MAIL_PASS"])
        m.select("inbox")
        typ, data = m.uid("fetch", str(uid).encode(), "(BODY.PEEK[])")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            return None
        msg = email.message_from_bytes(data[0][1])
        return {
            "from": _addr(_decode(msg["From"])),
            "reply_to": _addr(_decode(msg["Reply-To"])) or _addr(_decode(msg["From"])),
            "subject": _decode(msg["Subject"]),
            "message_id": (msg["Message-ID"] or "").strip(),
            "date": msg["Date"] or "",
        }
    finally:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass


def reply_subject(subject: str) -> str:
    s = (subject or "").strip()
    return s if re.match(r"^re\s*:", s, re.I) else (f"Re: {s}" if s else "Re:")


def make_reply_draft(uid: str, body: str, *, subject: str = "", chat_id: int = 0) -> dict:
    """Create a threaded-reply draft for the message `uid`."""
    meta = fetch_meta(uid)
    if not meta:
        return {"ok": False, "error": "Could not read that message (check mail config)."}
    to = meta["reply_to"] or meta["from"]
    if not to:
        return {"ok": False, "error": "No recipient found on that message."}
    subj = reply_subject(subject or meta["subject"])
    did = Drafts().add(
        chat_id,
        "reply",
        subj,
        body,
        "routine",
        to=to,
        subject=subj,
        message_id=meta["message_id"],
    )
    if did is None:
        return {"ok": False, "error": "Draft store unavailable."}
    return {"ok": True, "id": did, "to": to, "subject": subj, "in_reply_to": meta["message_id"]}
