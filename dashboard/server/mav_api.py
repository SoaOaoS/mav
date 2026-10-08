"""mav_api — backend of the Mav dashboard.

Small HTTP server (stdlib) that exposes the agent's state (jobs, Postgres
memory, watch, agents, health, metrics), lets you configure the model
provider, agents and MCP servers, and runs the chat through dashboard-owned
opencode sessions with SSE streaming.

No authentication: meant for a private host, reachable over VPN.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import sys
import time
import types
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import mav_core
import mav_engine
import mav_routines
import mav_store
import mav_chat
import mav_stream
import mav_media

# The server is split by area (mav_core, mav_engine, mav_routines, mav_store,
# mav_chat, mav_stream, mav_media); this module is its entry point and HTTP
# handler. Every other name lives in exactly one of those modules, and
# `mav_api.<name>` still reaches it, for reading and assigning alike (tests
# and tools set mav_api.JOBS_FILE, mav_api.send_push…), so the split changes
# no behaviour.
_PARTS = (mav_core, mav_engine, mav_routines, mav_store, mav_chat, mav_stream, mav_media)
_OWNER = {name: part for part in _PARTS for name in part.__all__}


class _Facade(types.ModuleType):
    def __getattr__(self, name):
        part = _OWNER.get(name)
        if part is None:
            raise AttributeError(f"module 'mav_api' has no attribute {name!r}")
        return getattr(part, name)

    def __setattr__(self, name, value):
        part = _OWNER.get(name)
        if part is not None:
            setattr(part, name, value)
        else:
            super().__setattr__(name, value)


sys.modules[__name__].__class__ = _Facade


#!/usr/bin/env python3
"""mav_api — backend of the Mav dashboard.

Small HTTP server (stdlib) that exposes the agent's state (jobs, Postgres
memory, watch, agents, health, metrics), lets you configure the model
provider, agents and MCP servers, and runs the chat through dashboard-owned
opencode sessions with SSE streaming.

No authentication: meant for a private host, reachable over VPN.
"""


class ThreadedHTTPServer(ThreadingHTTPServer):
    """HTTP/1.1 server with keep-alive and a large listen backlog.

    By default http.server stays on HTTP/1.0 (one connection per request) and
    accepts only 5 pending connections — on a cold load, a browser opens
    several in parallel and can get refused/timed out. So we enable keep-alive
    and widen the backlog.
    """

    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128
    protocol_version = "HTTP/1.1"


# What a family member may call. Everything else is the owner's: the model,
# connections, helpers, backup, updates, email, interests, usage, channels…
MEMBER_GET = frozenset({
    "/api/auth/state", "/api/health", "/api/status", "/api/version", "/api/agents",
    "/api/briefing", "/api/onboarding", "/api/jobs", "/api/job-templates", "/api/job-results",
    "/api/proactivity", "/api/memory", "/api/watch", "/api/notifications", "/api/notification",
    "/api/sessions", "/api/session", "/api/session/export", "/api/search", "/api/runs",
    "/api/stream", "/api/push/key", "/api/asset", "/api/chart", "/api/download", "/api/media",
    "/api/media/find", "/api/media/get", "/api/media/by-name", "/api/channels", "/api/calendar",
})
MEMBER_POST = frozenset({
    "/api/onboarding", "/api/onboarding/profile", "/api/onboarding/routines", "/api/briefing",
    "/api/briefing/run", "/api/ask", "/api/session/new", "/api/session/rename", "/api/session/agent",
    "/api/session/pin", "/api/session/delete", "/api/session/abort", "/api/session/interrupt",
    "/api/session/summary", "/api/run/stop", "/api/job/toggle", "/api/job/run", "/api/job/save",
    "/api/job/template", "/api/job/snooze", "/api/job/delete", "/api/routine/detect",
    "/api/proactivity", "/api/watch/add", "/api/watch/remove", "/api/upload", "/api/push/subscribe",
    "/api/push/unsubscribe", "/api/push/test", "/api/push/ack",
})
MEMBER_POST_PREFIXES = ("/api/auth/", "/api/memory/")

# Mav Cloud's included plan: the platform gives Mav its model and pays for
# it, so nobody here may change the model, the key or the background model.
MODEL_MANAGED = os.environ.get("MAV_MODEL_MANAGED", "").lower() in ("1", "true", "yes")
MODEL_POST = frozenset({"/api/config/provider", "/api/config/provider/test", "/api/usage/small-model"})

# Calls about one chat, and where they carry its id: only its owner may.
SESSION_GET = {"/api/session": "id", "/api/session/export": "id", "/api/stream": "session"}
SESSION_POST = {"/api/session/rename": "id", "/api/session/agent": "id", "/api/session/pin": "id",
                "/api/session/delete": "id", "/api/session/abort": "id",
                "/api/session/interrupt": "id", "/api/session/summary": "id",
                "/api/run/stop": "id", "/api/ask": "session"}


# The largest request body read into memory (JSON with base64 uploads); a
# backup restore has its own, larger limit (mav_backup.MAX_UPLOAD).
MAX_BODY = int(os.environ.get("MAV_MAX_BODY", str(64 * 1024 * 1024)))

# Who may embed or script the pages: only Mav itself (fonts from Google;
# images from anywhere, as answers can show them).
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob: https:; media-src 'self' data: blob:; "
       "connect-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
       "frame-ancestors 'none'")


class Handler(BaseHTTPRequestHandler):
    server_version = "mav-api/0.2"
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code: int, payload, ctype="application/json", headers=None):
        if isinstance(payload, (dict, list)):
            data = json.dumps(payload, ensure_ascii=False, default=mav_core._json_default).encode()
        else:
            data = payload if isinstance(payload, bytes) else str(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Frame-Options", "DENY")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    # ---- sign-in -------------------------------------------------------
    def _guard(self, path: str) -> bool:
        """False (and a 401 sent) when this API call needs a session."""
        if mav_core.AUTH.allowed(path, self.headers.get("Cookie", "")):
            return True
        # A refused request may leave a body unread: never reuse this connection.
        self.close_connection = True
        self._send(401, {"error": "sign in required", "auth": True})
        return False

    def _cross_site(self, path: str) -> bool:
        """True (and a 403 sent) for a browser request made from another site.

        The session cookie is SameSite=Lax, which still rides along a
        top-level GET from another site: enough to start an answer through
        /api/stream. Browsers say where a request comes from (Sec-Fetch-Site,
        Origin); webhooks and scripts send neither and are not affected."""
        if path.startswith("/api/hooks/"):
            return False
        site = self.headers.get("Sec-Fetch-Site", "")
        origin = self.headers.get("Origin", "")
        foreign = site in ("cross-site", "same-site")
        if not foreign and origin and origin != "null":
            host = urllib.parse.urlparse(origin).netloc
            foreign = host != self.headers.get("Host", "")
        if foreign:
            self.close_connection = True
            self._send(403, {"error": "cross-site request refused"})
        return foreign

    def _who(self) -> int:
        """The account this request is for (the owner when sign-in is off)."""
        uid = mav_core.AUTH.current(self.headers.get("Cookie", ""))
        return mav_core.DEFAULT_CHAT_ID if uid is None else uid

    def _permitted(self, method: str, path: str, params: dict) -> bool:
        """False (and a 403/404 sent) when the current user may not do this."""
        if not path.startswith("/api/"):
            return True
        if MODEL_MANAGED and method == "POST" and path in MODEL_POST:
            self._send(403, {"error": "The model is included in your plan and managed by Mav Cloud."})
            return False
        if not mav_core.is_owner():
            allowed = (path in MEMBER_GET) if method == "GET" else (
                path in MEMBER_POST or path.startswith(MEMBER_POST_PREFIXES))
            if not allowed:
                self._send(403, {"error": "Only the owner of this Mav can do that."})
                return False
        key = (SESSION_GET if method == "GET" else SESSION_POST).get(path)
        if key and not mav_chat.can_access(str(params.get(key) or "")):
            # Someone else's chat looks like one that does not exist.
            self._send(404, {"error": "not found"})
            return False
        return True

    def _secure(self) -> bool:
        return bool(getattr(self.server, "is_tls", False)) or (
            self.headers.get("X-Forwarded-Proto", "") == "https"
        )

    def _auth_post(self, path: str, payload: dict):
        who = self.client_address[0] if self.client_address else "?"
        cookie = self.headers.get("Cookie", "")
        if path == "/api/auth/logout":
            return self._send(200, {"ok": True}, headers={
                "Set-Cookie": mav_core.AUTH.set_cookie("", self._secure(), clear=True)})
        if path == "/api/auth/setup":
            if mav_core.AUTH.configured():
                return self._send(409, {"error": "A password is already set. Sign in instead."})
            try:
                mav_core.AUTH.set_password(payload.get("password", ""))
            except ValueError as exc:
                return self._send(400, {"error": str(exc)})
            return self._send(200, {"ok": True}, headers={
                "Set-Cookie": mav_core.AUTH.set_cookie(mav_core.AUTH.issue(), self._secure())})
        if path == "/api/auth/login":
            wait = mav_core.AUTH.throttled(who)
            if wait:
                return self._send(429, {"error": f"Too many attempts. Try again in {int(wait) + 1} s."})
            uid = mav_core.AUTH.login(str(payload.get("name") or ""), str(payload.get("password") or ""))
            if uid is None:
                mav_core.AUTH.failed(who)
                return self._send(401, {"error": "Wrong name or password." if mav_core.AUTH.state("")["named"]
                                        else "Wrong password."})
            mav_core.AUTH.succeeded(who)
            return self._send(200, {"ok": True}, headers={
                "Set-Cookie": mav_core.AUTH.set_cookie(mav_core.AUTH.issue(uid), self._secure())})
        if path == "/api/auth/password":
            uid = mav_core.AUTH.user_of(mav_core.AUTH.cookie_token(cookie))
            if mav_core.AUTH.configured() and uid is None:
                return self._send(401, {"error": "sign in required", "auth": True})
            if mav_core.AUTH.configured():
                wait = mav_core.AUTH.throttled(who)
                if wait:
                    return self._send(429, {"error": f"Too many attempts. Try again in {int(wait) + 1} s."})
                if not mav_core.AUTH.check_password(str(payload.get("current") or ""), uid):
                    mav_core.AUTH.failed(who)
                    return self._send(400, {"error": "The current password is wrong."})
            try:
                mav_core.AUTH.set_password(str(payload.get("password") or ""), uid)
            except ValueError as exc:
                return self._send(400, {"error": str(exc)})
            # Every other device is signed out; this one gets a fresh session.
            return self._send(200, {"ok": True}, headers={
                "Set-Cookie": mav_core.AUTH.set_cookie(mav_core.AUTH.issue(uid), self._secure())})
        return self._send(404, {"error": "not found"})

    def _family_post(self, path: str, payload: dict):
        """The owner manages the family: add, rename, reset, remove."""
        auth = mav_core.AUTH
        try:
            uid = int(payload.get("id") or 0)
        except (TypeError, ValueError):
            uid = 0
        try:
            if path == "/api/family/add":
                return self._send(200, {"ok": True, "member": auth.add_member(
                    str(payload.get("name") or ""), str(payload.get("password") or ""))})
            if path == "/api/family/rename":
                return self._send(200, {"ok": True, "name": auth.rename(uid, str(payload.get("name") or ""))})
            if path == "/api/family/password":
                if uid == mav_core.DEFAULT_CHAT_ID:
                    return self._send(400, {"error": "Change your own password under Password."})
                auth.set_password(str(payload.get("password") or ""), uid)
                return self._send(200, {"ok": True})
            if path == "/api/family/remove":
                if not auth.remove_member(uid):
                    return self._send(404, {"error": "No such member."})
                return self._send(200, {"ok": True, "removed": mav_store.forget_account(uid)})
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})
        return self._send(404, {"error": "not found"})

    def _restore(self):
        """Replace everything with an uploaded backup (raw .tar.gz body).

        Needs a session *and* the password again (X-Mav-Password): a restore
        rewrites the API keys, the helpers and the password itself.
        """
        # A refusal leaves the upload unread: never reuse this connection.
        self.close_connection = True
        if not self._guard("/api/backup/restore"):
            return
        if not mav_core.is_owner():
            return self._send(403, {"error": "Only the owner of this Mav can do that."})
        who = self.client_address[0] if self.client_address else "?"
        if mav_core.AUTH.configured():
            wait = mav_core.AUTH.throttled(who)
            if wait:
                return self._send(429, {"error": f"Too many attempts. Try again in {int(wait) + 1} s."})
            if not mav_core.AUTH.check_password(self.headers.get("X-Mav-Password", "")):
                mav_core.AUTH.failed(who)
                return self._send(403, {"error": "Wrong password."})
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            n = 0
        if n <= 0 or n > mav_core.mav_backup.MAX_UPLOAD:
            return self._send(413 if n > 0 else 400, {"error": "Send a Mav backup (.tar.gz)."})
        data = self.rfile.read(n)
        try:
            res = mav_core.mav_backup.restore(mav_store.backup_places(), data)
        except mav_core.mav_backup.BackupError as exc:
            return self._send(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            return self._send(500, {"error": f"Restore failed: {exc}"})
        res["restart"] = mav_engine.restart_engine()
        return self._send(200, res)

    def _sse_open(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _params(self) -> dict:
        _, _, query = self.path.partition("?")
        out = {}
        if query:
            for pair in query.split("&"):
                k, _, v = pair.partition("=")
                out[k] = urllib.parse.unquote_plus(v)
        return out

    def do_GET(self):
        path, _, _ = self.path.partition("?")
        p = self._params()
        if not self._guard(path):
            return
        # The one GET that acts: starting an answer.
        if path == "/api/stream" and p.get("prompt") and self._cross_site(path):
            return
        with mav_core.as_user(self._who()):
            if self._permitted("GET", path, p):
                self._get(path, p)

    def _get(self, path: str, p: dict):
        try:
            if path == "/api/auth/state":
                return self._send(200, {**mav_core.AUTH.state(self.headers.get("Cookie", "")),
                                        "model_managed": MODEL_MANAGED})
            if path == "/api/health":
                return self._send(200, {"ok": True})
            if path == "/api/briefing":
                return self._send(200, mav_routines.get_briefing())
            if path == "/api/onboarding":
                return self._send(200, mav_routines.get_onboarding())
            if path == "/api/usage":
                if mav_core.USAGE is None:
                    return self._send(200, {"available": False})
                days = int(p.get("days") or 30)
                return self._send(200, {"available": True, **mav_core.USAGE.summary(days),
                                        "speed": mav_core.USAGE.speed_summary(days)})
            if path == "/api/status":
                return self._send(200, mav_engine.get_status())
            if path == "/api/jobs":
                return self._send(200, mav_routines.get_jobs())
            if path == "/api/job-templates":
                return self._send(200, mav_routines.job_templates(p.get("lang", "en")))
            if path == "/api/job-results":
                return self._send(200, mav_routines.get_job_results())
            if path == "/api/proactivity":
                return self._send(200, mav_routines.get_proactivity())
            if path == "/api/drafts":
                return self._send(200, mav_store.get_drafts(p.get("status", "pending")))
            if path == "/api/actions":
                return self._send(200, mav_store.get_actions())
            if path == "/api/events":
                return self._send(200, mav_routines.get_events(int(p.get("limit", 30) or 30)))
            if path == "/api/mail/status":
                return self._send(200, mav_store.mail_config())
            if path == "/api/memory":
                return self._send(200, mav_store.get_memory())
            if path == "/api/watch":
                return self._send(200, mav_routines.get_watch())
            if path == "/api/interests":
                return self._send(200, mav_store.get_interests())
            if path == "/api/notifications":
                return self._send(200, mav_store.get_notifications())
            if path == "/api/notification":
                return self._send(200, mav_store.get_notification(int(p.get("id", 0) or 0)))
            if path == "/api/debates":
                return self._send(200, mav_store.get_debates())
            if path == "/api/debate":
                return self._send(200, mav_store.get_debate(p.get("id", "")))
            if path == "/api/agents":
                return self._send(200, mav_engine.get_agents())
            if path == "/api/connections":
                return self._send(200, {"connections": mav_engine.get_connections()})
            if path == "/api/health":
                return self._send(200, {"ok": True, "ts": int(time.time())})
            if path == "/api/config":
                return self._send(200, mav_engine.config_snapshot())
            if path == "/api/config/agents":
                return self._send(200, mav_engine.read_agents())
            if path == "/api/config/mcp":
                return self._send(200, mav_engine.read_mcp())
            if path == "/api/config/engine":
                return self._send(200, mav_engine.engine_status())
            if path == "/api/config/code":
                return self._send(200, mav_engine.code_state())
            if path == "/api/config/provider":
                return self._send(200, mav_engine.provider_snapshot())
            if path == "/api/config/mcp/catalog":
                return self._send(200, mav_engine.mcp_catalog())
            if path == "/api/config/mcp/status":
                return self._send(200, {"status": mav_engine.mcp_status()})
            if path == "/api/version":
                return self._send(200, mav_engine.version_info(p.get("refresh") == "1"))
            if path == "/api/update/status":
                return self._send(200, mav_engine.update_status())
            if path == "/api/config/agent-files":
                return self._send(200, mav_engine.list_agent_files())
            if path == "/api/config/agent-file":
                return self._send(200, mav_engine.read_agent_file(p.get("name", "")))
            if path == "/api/sessions":
                return self._send(200, {"sessions": mav_chat.list_sessions()})
            if path == "/api/session":
                sid = p.get("id", "")
                if not sid:
                    return self._send(400, {"error": "missing id"})
                run = mav_stream.get_run(sid)
                running = bool(run and run.status == "running")
                msgs = mav_chat.session_messages(sid)
                if running:
                    # The answer in progress belongs to the live stream: sending
                    # it here too is what showed the last answer twice.
                    msgs = mav_chat._drop_open_turn(msgs)
                return self._send(200, {
                    "id": sid,
                    "title": mav_chat.session_title(sid)[len(mav_chat.PREFIX):],
                    "agent": mav_chat.session_meta(sid).get("agent", ""),
                    "messages": msgs,
                    "running": running,
                })
            if path == "/api/session/export":
                sid = p.get("id", "")
                md = mav_chat.export_session_markdown(sid)
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="mav-conversation.md"')
                data = md.encode()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/api/search":
                return self._send(200, mav_store.global_search(p.get("q", "")))
            if path == "/api/push/key":
                return self._send(200, {"key": mav_media.push_public_key()})
            if path == "/api/backup":
                buf = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
                mav_core.mav_backup.create(mav_store.backup_places(), buf, include_chats=p.get("chats", "1") != "0")
                size = buf.tell()
                buf.seek(0)
                self.send_response(200)
                self.send_header("Content-Type", "application/gzip")
                self.send_header("Content-Disposition",
                                 'attachment; filename="mav-backup-' + time.strftime("%Y%m%d-%H%M") + '.tar.gz"')
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                shutil.copyfileobj(buf, self.wfile)
                return
            if path == "/api/backup/safety":
                return self._send(200, {"copies": mav_core.mav_backup.safety_copies(mav_store.backup_places())})
            if path == "/api/calendar":
                return self._send(200, mav_store.calendar_view())
            if path == "/api/webhook":
                return self._send(200, {"token": mav_routines.hook_token()})
            if path == "/api/family":
                return self._send(200, {"accounts": mav_core.AUTH.accounts(),
                                        "enabled": mav_core.AUTH.enabled and mav_core.AUTH.configured()})
            if path == "/api/channels":
                if mav_core.occhannels is None or not mav_core.is_owner():
                    return self._send(200, {"channels": [], "types": {}, "public_url": ""})
                return self._send(200, mav_core.occhannels.public_view())
            if path == "/api/asset":
                res = mav_media.serve_asset(p.get("path", ""))
                if not res:
                    return self._send(404, "asset not found", "text/plain")
                data, mime = res
                return self._send(200, data, mime)
            if path == "/api/chart":
                try:
                    return self._send(200, mav_media.chart_data(p.get("symbol", ""), p.get("range", "1mo")))
                except Exception:
                    return self._send(404, {"error": "chart unavailable"})
            if path == "/api/download":
                mav_media.sync_files_dir()
                res = mav_media.download_response(p.get("path", ""))
                if not res:
                    return self._send(404, "file not found", "text/plain")
                data, mime, fname = res
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header(
                    "Content-Disposition",
                    'attachment; filename="' + fname.replace('"', "") + '"',
                )
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/api/media":
                mav_media.sync_media_dir()
                return self._send(200, mav_media.list_media())
            if path == "/api/media/find":
                mav_media.sync_media_dir()
                return self._send(200, {"media": mav_media.find_media(p.get("q", ""))})
            if path == "/api/media/get":
                mid = p.get("id", "")
                hit = next((i for i in mav_media._media_load() if i.get("id") == mid), None)
                if not hit:
                    return self._send(404, "media not found", "text/plain")
                res = mav_media.serve_asset(hit["path"])
                if not res:
                    return self._send(404, "media not found", "text/plain")
                data, mime = res
                return self._send(200, data, mime)
            if path == "/api/media/by-name":
                name = p.get("name", "")
                hits = mav_media.find_media(name)
                if not hits:
                    return self._send(404, "media not found", "text/plain")
                res = mav_media.serve_asset(hits[0]["path"])
                if not res:
                    return self._send(404, "media not found", "text/plain")
                data, mime = res
                return self._send(200, data, mime)
            if path == "/api/runs":
                return self._send(200, {"runs": mav_stream.runs_view()})
            if path == "/api/stream":
                return self._stream(p)
            return self._static(path)
        except Exception as exc:  # noqa: BLE001
            return self._send(500, {"error": str(exc)})

    def _stream(self, p: dict):
        """Start a new answer, or attach to the one already running.

        A reconnect (the tab came back, the phone woke up) passes no prompt and
        a `from` cursor: the events it missed are replayed from the run buffer,
        then the live stream continues. Leaving never aborts the generation —
        only an explicit stop does.
        """
        sid = p.get("session", "")
        from_seq = int(p.get("from") or 0)
        prompt = (p.get("prompt") or "").strip()
        run = mav_stream.get_run(sid) if sid else None

        if not prompt and not run:
            return self._send(400, {"error": "missing prompt"})
        if prompt and (run is None or run.status != "running"):
            files = []
            if p.get("files"):
                try:
                    raw = json.loads(p["files"])
                    for item in raw:
                        if isinstance(item, str):
                            files.append(mav_media._guess_file({"url": item}))
                        elif isinstance(item, dict):
                            files.append(mav_media._guess_file(item))
                except Exception:
                    pass
            run = mav_stream.start_run(prompt, sid, p.get("agent", ""), files)
        elif prompt and run.status == "running":
            # A message while this session already runs is queued by the client;
            # never silently replace a live generation.
            return self._send(409, {"error": "already running", "session": sid})

        self._sse_open()
        try:
            for chunk in run.follow(from_seq):
                self.wfile.write(chunk.encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # The client left: the run keeps going. It will be reattachable.
            pass
        except Exception as exc:  # noqa: BLE001
            try:
                self.wfile.write(mav_stream._sse("error", {"message": str(exc)}).encode())
            except Exception:
                pass

    def do_POST(self):
        path, _, _ = self.path.partition("?")
        if path == "/api/backup/restore":
            if self._cross_site(path):
                return
            with mav_core.as_user(self._who()):
                return self._restore()
        # Nothing is read from a request that is not allowed in.
        if not self._guard(path) or self._cross_site(path):
            return
        try:
            size = int(self.headers.get("Content-Length", 0))
        except ValueError:
            size = 0
        if size > MAX_BODY:
            self.close_connection = True
            return self._send(413, {"error": "Too large."})
        payload = self._body()
        with mav_core.as_user(self._who()):
            if self._permitted("POST", path, payload):
                self._post(path, payload)

    def _post(self, path: str, payload: dict):
        try:
            if path.startswith("/api/auth/"):
                return self._auth_post(path, payload)
            if path.startswith("/api/family/"):
                return self._family_post(path, payload)
            if path == "/api/onboarding":
                return self._send(200, mav_routines.set_onboarding(bool(payload.get("done", True))))
            if path == "/api/onboarding/profile":
                return self._send(200, mav_routines.onboarding_profile(payload))
            if path == "/api/onboarding/routines":
                res = mav_routines.onboarding_routines(payload)
                return self._send(200 if res.get("created") or res.get("ok") else 400, res)
            if path == "/api/briefing":
                return self._send(200, mav_routines.set_briefing(bool(payload.get("enabled")),
                                                    str(payload.get("time") or "")))
            if path == "/api/briefing/run":
                return self._send(200, mav_routines.run_briefing_now())
            if path == "/api/usage/budget":
                if mav_core.USAGE is None:
                    return self._send(400, {"error": "Usage tracking unavailable."})
                try:
                    b = mav_core.USAGE.set_budget(float(payload.get("monthly_usd") or 0),
                                         str(payload.get("action") or "warn"))
                except (TypeError, ValueError) as exc:
                    return self._send(400, {"error": str(exc)})
                return self._send(200, {"ok": True, "budget": b})
            if path == "/api/usage/small-model":
                if mav_core.USAGE is None:
                    return self._send(400, {"error": "Usage tracking unavailable."})
                ref = str(payload.get("model") or "").strip()
                if ref and "/" not in ref:
                    return self._send(400, {"error": "Use provider/model, e.g. anthropic/claude-haiku-4-5."})
                mav_core.USAGE.set_small_model(ref)
                return self._send(200, {"ok": True, "small_model": ref})
            if path == "/api/ask":
                prompt = (payload.get("prompt") or "").strip()
                if not prompt:
                    return self._send(400, {"error": "missing prompt"})
                return self._send(200, {"answer": mav_stream.ask(prompt, payload.get("agent", ""), payload.get("session", ""), payload.get("files"))})
            if path == "/api/session/new":
                return self._send(200, mav_chat.create_session(payload.get("title", ""), payload.get("agent", "")))
            if path == "/api/session/rename":
                ok = mav_chat.rename_session(payload.get("id", ""), payload.get("title", ""))
                if ok:  # a title chosen by the user is never auto-replaced
                    mav_chat.set_session_meta(payload.get("id", ""), title_locked=True, titled=True)
                return self._send(200 if ok else 400, {"ok": ok})
            if path == "/api/session/agent":
                mav_chat.set_session_meta(payload.get("id", ""), agent=(payload.get("agent") or "").strip())
                return self._send(200, {"ok": True})
            if path == "/api/session/pin":
                mav_chat.set_session_meta(payload.get("id", ""), pinned=bool(payload.get("pinned")))
                return self._send(200, {"ok": True})
            if path == "/api/session/delete":
                ok = mav_chat.delete_session(payload.get("id", ""))
                return self._send(200 if ok else 400, {"ok": ok})
            if path == "/api/session/abort":
                mav_stream.abort_session(payload.get("id", ""))
                return self._send(200, {"ok": True})
            if path == "/api/session/interrupt":
                return self._send(200, mav_stream.interrupt_session(payload.get("id", "")))
            if path == "/api/run/stop":
                return self._send(200, mav_stream.stop_run(payload.get("id", "")))
            if path == "/api/session/summary":
                sid = payload.get("id", "")
                s = mav_chat.summarize_session(sid)
                return self._send(200, {"summary": s})
            if path == "/api/job/toggle":
                ok = mav_routines.set_job_enabled(payload.get("name", ""), bool(payload.get("enabled")))
                return self._send(200 if ok else 404, {"ok": ok})
            if path == "/api/job/run":
                res = mav_routines.run_job_now(payload.get("name", ""))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/job/save":
                res = mav_routines.save_job(payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/job/template":
                res = mav_routines.template_to_job(payload.get("id", ""), name=payload.get("name", ""),
                                      lang=str(payload.get("lang") or "en"))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/job/snooze":
                try:
                    until = int(payload.get("until") or 0)
                except (TypeError, ValueError):
                    until = 0
                ok = mav_routines.snooze_job(payload.get("name", ""), until)
                return self._send(200 if ok else 404, {"ok": ok})
            if path == "/api/job/delete":
                ok = mav_routines.delete_job(payload.get("name", ""))
                return self._send(200 if ok else 404, {"ok": ok})
            if path == "/api/routine/detect":
                return self._send(200, mav_routines.detect_routine(payload.get("text", "")))
            if path == "/api/proactivity":
                res = mav_routines.set_proactivity(payload.get("level", ""))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/drafts/add":
                res = mav_store.draft_action("add", payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/drafts/status":
                res = mav_store.draft_action("status", payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/drafts/delete":
                res = mav_store.draft_action("delete", payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/drafts/notify":
                res = mav_store.draft_notify(int(payload.get("id") or 0))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/drafts/edit":
                res = mav_store.draft_action("edit", payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/drafts/send":
                res = mav_store.send_draft(int(payload.get("id") or 0))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/mail/save":
                res = mav_store.mail_save(payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/mail/test":
                return self._send(200, mav_store.mail_test(payload))
            if path == "/api/mail/forget":
                return self._send(200, mav_store.mail_forget())
            if path == "/api/mail/reply-draft":
                res = mav_store.mail_reply_draft(payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/webhook/new":
                res = mav_routines.new_hook_token()
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/hooks/event":
                res = mav_routines.hook_event(
                    payload.get("kind", "custom"),
                    payload.get("payload") or payload,
                    str(payload.get("token") or ""),
                    signed_in=mav_core.AUTH.current(self.headers.get("Cookie", "")) is not None,
                )
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/actions/start":
                res = mav_routines.start_action(
                    payload.get("prompt", ""),
                    payload.get("name", ""),
                    payload.get("agent", ""),
                )
                return self._send(200 if res.get("ok") else 400, res)
            if path.startswith("/api/memory/"):
                res = mav_store.memory_action(path[len("/api/memory/"):], payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/config/provider":
                res = mav_engine.provider_save(payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/config/provider/test":
                return self._send(200, mav_engine.provider_test(payload))
            if path == "/api/config/code":
                res = mav_engine.code_set(bool(payload.get("enabled")))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/config/mcp/install":
                res = mav_engine.install_from_catalog(payload.get("id", ""), payload.get("values") or {})
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/config/mcp/oauth/start":
                res = mav_engine.mcp_oauth_start(payload.get("name", ""))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/config/mcp/oauth/callback":
                res = mav_engine.mcp_oauth_callback(payload.get("name", ""), payload.get("code", ""))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/config/mcp/oauth/remove":
                res = mav_engine.mcp_oauth_remove(payload.get("name", ""))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/update":
                res = mav_engine.start_update()
                return self._send(200 if res.get("ok") else 500, res)
            if path == "/api/interests/add":
                res = mav_store.add_interest(payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/interests/update":
                res = mav_store.update_interest(payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/interests/delete":
                return self._send(200, mav_store.delete_interest(str(payload.get("key") or "")))
            if path == "/api/interests/feedback":
                return self._send(200, mav_store.interest_feedback(
                    str(payload.get("key") or ""), bool(payload.get("positive"))))
            if path == "/api/interests/open":
                res = mav_store.interest_context(str(payload.get("key") or ""))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/interests/autonomy":
                res = mav_store.set_interests_autonomy(str(payload.get("level") or ""))
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/interests/apply":
                res = mav_store.selfinit_apply()
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/watch/add":
                ok = mav_routines.watch_add(payload.get("kind", ""), payload.get("target", ""))
                return self._send(200 if ok else 400, {"ok": ok})
            if path == "/api/watch/remove":
                ok = mav_routines.watch_remove(int(payload.get("id", 0)))
                return self._send(200, {"ok": ok})
            if path == "/api/upload":
                f = mav_chat.save_upload(payload.get("name", "fichier"), payload.get("data", ""), payload.get("mime", ""))
                return self._send(200, f)
            if path == "/api/push/subscribe":
                # Record the device for diagnostics (headless vs real phone).
                try:
                    payload["_ua"] = self.headers.get("User-Agent", "")[:200]
                except Exception:
                    pass
                ok = mav_media.push_subscribe(payload)
                return self._send(200, {"ok": ok})
            if path.startswith("/api/calendar/"):
                res = mav_store.calendar_action(path[len("/api/calendar/"):], payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path.startswith("/api/channels/"):
                res = mav_store.channels_action(path[len("/api/channels/"):], payload)
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/push/unsubscribe":
                ok = mav_media.push_unsubscribe(payload.get("endpoint", ""))
                return self._send(200, {"ok": ok})
            if path == "/api/push/test":
                n = mav_media.send_push("Mav", "This is a test notification.")
                return self._send(200, {"sent": n})
            if path == "/api/push/ack":
                # Service worker acknowledgement: proves the push actually
                # reached the device (delivery diagnostics).
                try:
                    mav_core.pg_exec(
                        "insert into notifications (ts, chat_id, topic, title, body, channels, delivered) "
                        "values (%s, %s, %s, %s, %s, %s, %s)",
                        (int(time.time()), mav_core.uid(), "push_ack",
                         str(payload.get("title", ""))[:200],
                         str(payload.get("body", ""))[:500],
                         ["ack"], True),
                    )
                except Exception:
                    pass
                return self._send(200, {"ok": True})
            if path == "/api/config/agents":
                text = payload.get("text")
                if not isinstance(text, str):
                    return self._send(400, {"error": "text required"})
                res = mav_engine.write_agents(text)
                return self._send(200 if res.get("ok") else 500, res)
            if path == "/api/config/mcp":
                res = mav_engine.write_mcp(payload.get("mcp"))
                return self._send(200 if res.get("ok") else 500, res)
            if path == "/api/config/restart":
                res = mav_engine.restart_engine()
                return self._send(200, res)
            if path == "/api/config/agent-file":
                res = mav_engine.write_agent_file(
                    (payload.get("name") or "").strip(),
                    payload.get("text", ""),
                )
                return self._send(200 if res.get("ok") else 400, res)
            if path == "/api/config/agent-file/delete":
                res = mav_engine.delete_agent_file((payload.get("name") or "").strip())
                return self._send(200 if res.get("ok") else 400, res)
            return self._send(404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001
            return self._send(500, {"error": str(exc)})

    # What the web app is made of; nothing else in its folder is served
    # (the server's code, tools, keys, dotfiles).
    STATIC_TYPES = {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".webmanifest": "application/manifest+json",
        ".json": "application/json",
        ".ico": "image/x-icon",
        ".crt": "application/x-x509-ca-cert",
        ".cer": "application/x-x509-ca-cert",
        ".pem": "application/x-pem-file",
    }

    def _static(self, path: str):
        if path == "/":
            path = "/index.html"
        rel = urllib.parse.unquote(path).lstrip("/")
        parts = rel.split("/")
        if parts[0] in ("server", "tools") or any(x.startswith(".") for x in parts):
            return self._send(404, "not found", "text/plain")
        if parts[0] == "certs" and rel not in ("certs/ca.crt", "certs/ca.cer"):
            return self._send(404, "not found", "text/plain")
        try:
            target = mav_core.inside(mav_core.STATIC_DIR, rel)
        except ValueError:
            return self._send(404, "not found", "text/plain")
        ctype = self.STATIC_TYPES.get(target.suffix)
        if not ctype or not target.is_file():
            return self._send(404, "not found", "text/plain")
        return self._send(200, target.read_bytes(), ctype)


def main():
    import ssl

    mav_store.ensure_schema()

    srv = ThreadedHTTPServer((mav_core.BIND, mav_core.PORT), Handler)
    print(f"mav-api listening on http://{mav_core.BIND}:{mav_core.PORT} (static: {mav_core.STATIC_DIR})", flush=True)

    if mav_core.TLS_PORT and mav_core.TLS_CERT and mav_core.TLS_KEY:
        try:
            tsrv = ThreadedHTTPServer((mav_core.BIND, mav_core.TLS_PORT), Handler)
            tsrv.is_tls = True  # session cookies get the Secure flag
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(mav_core.TLS_CERT, mav_core.TLS_KEY)
            tsrv.socket = ctx.wrap_socket(tsrv.socket, server_side=True)
            threading.Thread(target=tsrv.serve_forever, daemon=True).start()
            print(f"mav-api listening on https://{mav_core.BIND}:{mav_core.TLS_PORT}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"TLS unavailable: {exc}", flush=True)

    srv.serve_forever()


if __name__ == "__main__":
    main()
