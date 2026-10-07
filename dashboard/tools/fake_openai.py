#!/usr/bin/env python3
"""A tiny OpenAI-compatible model that records what the engine sends it.

Used to measure the prompt each helper costs (roadmap 2.1): point a real
opencode at it as a provider, ask each helper something, and read the log
(one JSON line per request: total bytes, tool names and their size, system
prompt size). It always answers "OK".

    python3 dashboard/tools/fake_openai.py 4988 /tmp/requests.log
    # opencode.json:
    # {"provider": {"fake": {"npm": "@ai-sdk/openai-compatible",
    #   "options": {"baseURL": "http://127.0.0.1:4988/v1", "apiKey": "x"},
    #   "models": {"m": {"name": "m"}}}}, "model": "fake/m"}
"""
import json, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
LOG = sys.argv[2]
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        req = json.loads(body or b"{}")
        tools = [t.get("function", {}).get("name") for t in req.get("tools") or []]
        sysmsg = "".join(m.get("content") if isinstance(m.get("content"), str) else json.dumps(m.get("content")) for m in req.get("messages", []) if m.get("role") == "system")
        with open(LOG, "a") as f:
            f.write(json.dumps({"bytes": len(body), "tools": tools, "tools_bytes": len(json.dumps(req.get("tools") or [])),
                                "system_bytes": len(sysmsg), "n_msgs": len(req.get("messages", [])),
                                "first_user": next((m.get("content") for m in req.get("messages", []) if m.get("role") == "user"), "")[:80] if isinstance(next((m.get("content") for m in req.get("messages", []) if m.get("role") == "user"), ""), str) else "parts"}) + "\n")
        self.send_response(200)
        if req.get("stream"):
            self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            for chunk in [{"choices":[{"index":0,"delta":{"role":"assistant","content":"OK"}}]},
                          {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":1,"total_tokens":11}}]:
                self.wfile.write(f"data: {json.dumps({'id':'x','object':'chat.completion.chunk','created':int(time.time()),'model':'m',**chunk})}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            out = json.dumps({"id":"x","object":"chat.completion","created":int(time.time()),"model":"m",
                              "choices":[{"index":0,"message":{"role":"assistant","content":"OK"},"finish_reason":"stop"}],
                              "usage":{"prompt_tokens":10,"completion_tokens":1,"total_tokens":11}}).encode()
            self.send_header("Content-Type","application/json"); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
