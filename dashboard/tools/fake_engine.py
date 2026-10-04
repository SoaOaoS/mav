#!/usr/bin/env python3
"""A tiny stand-in for `opencode serve`, for dashboard development and tests.

Implements just the endpoints Mav uses (sessions, messages, prompt_async,
agents, health). Answers are canned: they echo the prompt, mention the agent,
and title requests get a short title. No model, no network.

    python3 dashboard/tools/fake_engine.py --port 4096
    OPENCODE_URL=http://127.0.0.1:4096 python3 dashboard/server/mav_api.py
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AGENTS = [
    {"name": "assistant", "mode": "primary", "description": "Your everyday assistant — answers directly, and calls in a helper when it helps"},
    {"name": "researcher", "mode": "all", "description": "Looks things up on the web, checks facts and compares options"},
    {"name": "writer", "mode": "all", "description": "Drafts and polishes emails, messages, posts and letters"},
    {"name": "planner", "mode": "all", "description": "Organises days, trips, projects and to-do lists"},
    {"name": "money", "mode": "all", "description": "Budgets, purchases, subscriptions and comparing offers"},
    {"name": "title", "mode": "primary", "hidden": True, "description": ""},
]

SESSIONS: dict[str, dict] = {}
MESSAGES: dict[str, list] = {}
PROMPTS: list[dict] = []  # every prompt body received (inspected by tests)
LOCK = threading.Lock()


def now_ms() -> int:
    return int(time.time() * 1000)


def reply_for(body: dict) -> str:
    texts = [p.get("text", "") for p in body.get("parts", []) if p.get("type") == "text"]
    visible = [p.get("text", "") for p in body.get("parts", []) if p.get("type") == "text" and not p.get("synthetic")]
    prompt = visible[-1] if visible else ""
    if prompt.startswith("Write a title of 2 to 5 words"):
        user = prompt.split("User:", 1)[-1].strip().split()
        return " ".join(w.capitalize() for w in user[:3]) or "Short chat"
    if prompt.startswith("Extract durable personal facts"):
        msg = prompt.split("Message:", 1)[-1].strip()
        return f"- User said: {msg[:80]}" if " I " in f" {msg} " else "NONE"
    memory = any("<memory>" in t for t in texts)
    agent = body.get("agent") or "default"
    return (
        f"**{agent}** here. You said: _{prompt[:200]}_\n\n"
        "- point one\n- point two\n\n```python\nprint('hello')\n```"
        + ("\n\n(I received your memory.)" if memory else "")
    )


def add_exchange(sid: str, body: dict, delay: float) -> dict:
    user = {
        "info": {"id": uuid.uuid4().hex, "role": "user", "time": {"created": now_ms()}},
        "parts": body.get("parts", []),
    }
    with LOCK:
        MESSAGES.setdefault(sid, []).append(user)
    time.sleep(delay)
    answer = {
        "info": {
            "id": uuid.uuid4().hex, "role": "assistant", "finish": "stop",
            "agent": body.get("agent") or "general", "time": {"created": now_ms()},
        },
        "parts": [{"type": "text", "text": reply_for(body)}],
    }
    with LOCK:
        MESSAGES[sid].append(answer)
        if sid in SESSIONS:
            SESSIONS[sid]["time"]["updated"] = now_ms()
    return answer


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def send(self, code, data):
        raw = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def parts(self):
        return [p for p in self.path.split("?")[0].split("/") if p]

    def do_GET(self):
        p = self.parts()
        if p == ["global", "health"]:
            return self.send(200, {"healthy": True, "version": "fake-1.0"})
        if p == ["agent"]:
            return self.send(200, AGENTS)
        if p == ["mcp"]:
            return self.send(200, {})
        if p == ["event"]:  # no live events: keep the stream open, quietly
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                while True:
                    self.wfile.write(b'data: {"type":"server.heartbeat"}\n\n')
                    self.wfile.flush()
                    time.sleep(10)
            except Exception:  # noqa: BLE001
                return
        if p == ["session"]:
            return self.send(200, list(SESSIONS.values()))
        if len(p) == 2 and p[0] == "session":
            s = SESSIONS.get(p[1])
            return self.send(200 if s else 404, s or {"error": "not found"})
        if len(p) == 3 and p[0] == "session" and p[2] == "message":
            return self.send(200, MESSAGES.get(p[1], []))
        return self.send(404, {"error": "not found"})

    def do_POST(self):
        p = self.parts()
        body = self.body()
        if p == ["session"]:
            sid = "ses_" + uuid.uuid4().hex[:12]
            SESSIONS[sid] = {"id": sid, "title": body.get("title", "New session"), "time": {"created": now_ms(), "updated": now_ms()}}
            MESSAGES[sid] = []
            return self.send(200, SESSIONS[sid])
        if len(p) == 3 and p[0] == "session" and p[1] in SESSIONS:
            sid = p[1]
            if p[2] == "prompt_async":
                PROMPTS.append(body)
                threading.Thread(target=add_exchange, args=(sid, body, 1.0), daemon=True).start()
                return self.send(200, {})
            if p[2] == "message":
                PROMPTS.append(body)
                return self.send(200, add_exchange(sid, body, 0.2))
            if p[2] == "abort":
                return self.send(200, True)
        return self.send(404, {"error": "not found"})

    def do_PATCH(self):
        p = self.parts()
        if len(p) == 2 and p[1] in SESSIONS:
            SESSIONS[p[1]].update({k: v for k, v in self.body().items() if k == "title"})
            return self.send(200, SESSIONS[p[1]])
        return self.send(404, {"error": "not found"})

    def do_DELETE(self):
        p = self.parts()
        if len(p) == 2:
            SESSIONS.pop(p[1], None)
            MESSAGES.pop(p[1], None)
            return self.send(200, True)
        return self.send(404, {"error": "not found"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4096)
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    srv.daemon_threads = True
    print(f"fake opencode engine on http://127.0.0.1:{a.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
