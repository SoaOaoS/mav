"""Mail configuration and sending for the dashboard.

The credentials live in the same file as the mail helper the assistant uses
(``~/.config/opencode/mail.conf``), so a routine, the ``check_mail`` tool and
the dashboard all share one setup — configure it once, in the web app.

Everything here is best-effort and never logs or returns the password: the
dashboard shows whether a password exists, never its value.
"""

from __future__ import annotations

import imaplib
import os
import smtplib
from email.mime.text import MIMEText
from pathlib import Path

__all__ = ["load", "save", "status", "test", "send", "MAIL_CONF", "PRESETS", "REQUIRED"]

# Where the assistant reads its mail config. Overridable for tests/installs.
MAIL_CONF = Path(
    os.environ.get("MAV_MAIL_CONF", "/home/opencode/.config/opencode/mail.conf")
)

REQUIRED = ("MAIL_IMAP_SERVER", "MAIL_SMTP_SERVER", "MAIL_USER", "MAIL_PASS")

# Common providers, to pre-fill the form. `hint` is shown as a warning.
PRESETS = {
    "gmail": {
        "label": "Gmail / Google Workspace",
        "imap": "imap.gmail.com",
        "smtp": "smtp.gmail.com",
        "hint": "Gmail requires an App Password (2-Step Verification must be on) — never your normal password.",
    },
    "outlook": {
        "label": "Outlook / Microsoft 365",
        "imap": "outlook.office365.com",
        "smtp": "smtp.office365.com",
        "hint": "Microsoft 365 may require an app password or security defaults disabled.",
    },
    "fastmail": {
        "label": "Fastmail",
        "imap": "imap.fastmail.com",
        "smtp": "smtp.fastmail.com",
        "hint": "Create an app password in Fastmail settings.",
    },
    "other": {
        "label": "Other (IMAP/SMTP)",
        "imap": "",
        "smtp": "",
        "hint": "Enter your provider's IMAP and SMTP servers.",
    },
}


def load(path: Path | None = None) -> dict:
    p = Path(path or MAIL_CONF)
    cfg: dict[str, str] = {}
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001
        pass
    return cfg


def _chown_install_user(path: Path) -> None:
    """Give the file back to the install user (the worker runs as them)."""
    try:
        st = path.parent.stat()
        os.chown(path, st.st_uid, st.st_gid)
    except Exception:  # noqa: BLE001
        pass


def save(imap: str, smtp: str, user: str, password: str, path: Path | None = None) -> str:
    """Write the config (0600). The password is never logged or returned."""
    p = Path(path or MAIL_CONF)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Mav — mail access. Written from the dashboard (Settings → Mail).",
        f"MAIL_IMAP_SERVER={imap.strip()}",
        f"MAIL_SMTP_SERVER={smtp.strip()}",
        f"MAIL_USER={user.strip()}",
        f"MAIL_PASS={password}",
        "",
    ]
    p.write_text("\n".join(lines))
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    _chown_install_user(p)
    return str(p)


def forget(path: Path | None = None) -> None:
    """Remove the stored mail credentials."""
    p = Path(path or MAIL_CONF)
    try:
        p.unlink()
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001
        pass


def status(path: Path | None = None) -> dict:
    cfg = load(path)
    return {
        "configured": all(cfg.get(k) for k in REQUIRED),
        "imap": cfg.get("MAIL_IMAP_SERVER", ""),
        "smtp": cfg.get("MAIL_SMTP_SERVER", ""),
        "user": cfg.get("MAIL_USER", ""),
        "has_password": bool(cfg.get("MAIL_PASS")),
        "presets": [
            {"id": k, **{kk: vv for kk, vv in v.items() if kk in ("label", "imap", "smtp", "hint")}}
            for k, v in PRESETS.items()
        ],
    }


def test(
    imap: str,
    smtp: str,
    user: str,
    password: str,
    *,
    imap_port: int = 993,
    smtp_port: int = 465,
    timeout: int = 12,
) -> dict:
    """Try to log in to IMAP (read) and SMTP (send) without sending anything."""
    errors: list[str] = []
    imap_ok = False
    smtp_ok = False
    try:
        m = imaplib.IMAP4_SSL(imap, imap_port, timeout=timeout)
        m.login(user, password)
        m.select("inbox")
        m.logout()
        imap_ok = True
    except Exception as exc:  # noqa: BLE001
        errors.append(f"IMAP: {str(exc)[:160]}")
    try:
        with smtplib.SMTP_SSL(smtp, smtp_port, timeout=timeout) as s:
            s.login(user, password)
        smtp_ok = True
    except Exception as exc:  # noqa: BLE001
        errors.append(f"SMTP: {str(exc)[:160]}")
    return {"ok": imap_ok and smtp_ok, "imap_ok": imap_ok, "smtp_ok": smtp_ok, "errors": errors}


def send(
    to: str,
    subject: str,
    body: str,
    *,
    in_reply_to: str = "",
    references: list[str] | None = None,
    path: Path | None = None,
    timeout: int = 20,
) -> dict:
    """Send a plain-text reply through the configured SMTP server.

    When ``in_reply_to`` (the original Message-ID) is given, the message is sent
    as a threaded reply: ``In-Reply-To`` + ``References`` are set so clients
    (Gmail included) keep it in the same conversation.
    """
    cfg = load(path)
    user = (cfg.get("MAIL_USER") or "").strip()
    password = cfg.get("MAIL_PASS") or ""
    smtp = (cfg.get("MAIL_SMTP_SERVER") or "").strip()
    if not (user and password and smtp):
        return {"ok": False, "error": "Mail is not configured yet."}
    to = (to or "").strip()
    if not to or "@" not in to:
        return {"ok": False, "error": "Add a recipient first."}
    msg = MIMEText(body or "", "plain", "utf-8")
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = (subject or "").strip() or "(no subject)"
    if in_reply_to:
        # Keep the header exactly as received, angle brackets included.
        mid = in_reply_to.strip()
        msg["In-Reply-To"] = mid
        refs = list(references or [])
        if mid not in refs:
            refs.append(mid)
        msg["References"] = " ".join(refs)
    try:
        with smtplib.SMTP_SSL(smtp, 465, timeout=timeout) as s:
            s.login(user, password)
            s.send_message(msg)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}
    return {"ok": True, "to": to, "threaded": bool(in_reply_to)}
