"""Mav's code tools (dashboard/tools/mav_code.py): the MCP server that runs code
and commands, and the setting that turns it on in a self-hosted Mav.

Run: python3 -m unittest tests.test_code_tool -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_security import Server  # noqa: E402

import mav_api  # noqa: E402

TOOL = Path(__file__).resolve().parents[1] / "dashboard" / "tools" / "mav_code.py"


class McpClient:
    """mav_code.py over stdio, the way the engine talks to it."""

    def __init__(self, env: dict):
        self.proc = subprocess.Popen([sys.executable, str(TOOL)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     env=env, text=True)
        self.next = 0

    def call(self, method: str, params: dict | None = None) -> dict:
        self.next += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.next, "method": method,
                                          "params": params or {}}) + "\n")
        self.proc.stdin.flush()
        reply = json.loads(self.proc.stdout.readline())
        assert reply["id"] == self.next, reply
        return reply

    def tool(self, tool_name: str, **args) -> tuple[str, bool]:
        res = self.call("tools/call", {"name": tool_name, "arguments": args})["result"]
        return res["content"][0]["text"], res["isError"]

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=10)


class LocalCodeTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.work, self.files, self.attach = self.dir / "code", self.dir / "mav-files", self.dir / "attachments"
        self.attach.mkdir()
        env = {"PATH": os.environ["PATH"], "HOME": str(self.dir), "MAV_CODE_DIR": str(self.work),
               "MAV_FILES": str(self.files), "MAV_ATTACH": str(self.attach),
               "ANTHROPIC_API_KEY": "sk-secret", "DATABASE_URL": "postgres://x", "PGPASSWORD": "pw"}
        self.mcp = McpClient(env)

    def tearDown(self):
        self.mcp.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_handshake_and_tools(self):
        init = self.mcp.call("initialize", {"protocolVersion": "2025-06-18"})["result"]
        self.assertEqual(init["serverInfo"]["name"], "mav-code")
        self.assertIn("this machine", init["instructions"])
        names = {t["name"] for t in self.mcp.call("tools/list")["result"]["tools"]}
        self.assertEqual(names, {"run_command", "run_python", "write_file", "read_file", "list_files",
                                 "save_to_chat", "load_from_chat"})
        self.assertIn("error", self.mcp.call("tools/call", {"name": "rm_rf", "arguments": {}}))
        self.assertIn("error", self.mcp.call("no/such"))

    def test_runs_code_in_its_folder_without_the_secrets(self):
        out, err = self.mcp.tool("run_python", code="import os\nprint(6 * 7, os.getcwd())\n"
                                                     "print(sorted(k for k in os.environ if 'KEY' in k or 'PG' in k or 'DATABASE' in k))")
        self.assertFalse(err)
        self.assertIn("exit code: 0", out)
        self.assertIn(f"42 {self.work}", out)
        self.assertIn("[]", out)
        out, _ = self.mcp.tool("run_command", command="echo oops >&2; exit 3")
        self.assertIn("exit code: 3", out)
        self.assertIn("oops", out)

    def test_files_round_trip(self):
        self.assertFalse(self.mcp.tool("write_file", path="data/a.csv", content="x,y\n1,2\n")[1])
        self.assertEqual(self.mcp.tool("read_file", path="/work/data/a.csv")[0], "x,y\n1,2\n")
        self.assertIn("data/a.csv", self.mcp.tool("list_files")[0])
        # To the chat, under a clean name, and back.
        out, err = self.mcp.tool("save_to_chat", path="data/a.csv", name="../Budget 2026.csv")
        self.assertFalse(err)
        self.assertIn("[[file:Budget 2026.csv]]", out)
        self.assertEqual((self.files / "Budget 2026.csv").read_text(), "x,y\n1,2\n")
        (self.attach / "photo.txt").write_text("shared")
        self.assertFalse(self.mcp.tool("load_from_chat", name="photo.txt", path="in/p.txt")[1])
        self.assertEqual((self.work / "in" / "p.txt").read_text(), "shared")
        out, err = self.mcp.tool("load_from_chat", name="nope.txt")
        self.assertTrue(err)
        self.assertIn("photo.txt", out)

    def test_stays_in_the_workspace(self):
        for path in ("/etc/passwd", "../outside.txt", "a/../../b"):
            out, err = self.mcp.tool("write_file", path=path, content="x")
            self.assertTrue(err, path)
            self.assertIn("workspace", out)
        self.assertFalse((self.dir / "outside.txt").exists())
        # A link out of the folder is not followed either.
        self.work.mkdir(exist_ok=True)
        (self.work / "out").symlink_to(self.dir)
        self.assertTrue(self.mcp.tool("read_file", path="out/attachments/x")[1])

    def test_a_runaway_command_is_stopped(self):
        out, err = self.mcp.tool("run_command", command="sleep 30 & sleep 30", timeout_seconds=1)
        self.assertFalse(err)
        self.assertIn("took too long", out)


class _Sandbox(BaseHTTPRequestHandler):
    """A stand-in for Mav Cloud's /code endpoints."""

    files: dict = {}
    seen: list = []

    def log_message(self, *a):
        pass

    def _reply(self, status, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _ok(self):
        self.seen.append((self.command, self.path, self.headers.get("Authorization")))
        if self.headers.get("Authorization") != "Bearer t0k":
            self._reply(401, {"error": "Not signed in."})
            return False
        return True

    def do_POST(self):
        if self._ok():
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self._reply(200, {"exit_code": 0, "stdout": f"ran: {body['command']}", "stderr": "", "timed_out": False})

    def do_PUT(self):
        if self._ok():
            self.files[self.path.split("path=", 1)[1]] = self.rfile.read(int(self.headers["Content-Length"]))
            self._reply(200, {"ok": True})

    def do_GET(self):
        if self._ok():
            data = self.files.get(self.path.split("path=", 1)[1])
            self._reply(200, data, "application/octet-stream") if data is not None else \
                self._reply(404, {"error": "No such file."})


class RemoteCodeTest(unittest.TestCase):
    def test_goes_through_the_sandbox(self):
        srv = HTTPServer(("127.0.0.1", 0), _Sandbox)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        tmp = Path(tempfile.mkdtemp())
        mcp = McpClient({"PATH": os.environ["PATH"], "HOME": str(tmp), "MAV_FILES": str(tmp / "files"),
                         "MAV_CODE_URL": f"http://127.0.0.1:{srv.server_address[1]}/code", "MAV_CODE_TOKEN": "t0k"})
        try:
            self.assertIn("sandbox", mcp.call("initialize")["result"]["instructions"])
            out, err = mcp.tool("run_python", code="print(1)")
            self.assertFalse(err)
            self.assertIn("ran: python3 .mav/run.py", out)
            self.assertEqual(_Sandbox.files[".mav/run.py"], b"print(1)")
            mcp.tool("write_file", path="r.txt", content="report")
            self.assertIn("[[file:r.txt]]", mcp.tool("save_to_chat", path="r.txt")[0])
            self.assertEqual((tmp / "files" / "r.txt").read_text(), "report")
            out, err = mcp.tool("read_file", path="missing.txt")
            self.assertTrue(err)
            self.assertIn("No such file", out)
            self.assertTrue(all(auth == "Bearer t0k" for _, _, auth in _Sandbox.seen))
        finally:
            mcp.close()
            srv.shutdown()
            shutil.rmtree(tmp, ignore_errors=True)


class CodeSettingTest(Server):
    def test_the_owner_turns_it_on_and_off(self):
        cfg = Path(tempfile.mkdtemp()) / "opencode.json"
        cfg.write_text(json.dumps({"model": "x/y", "mcp": {"other": {"type": "remote", "url": "https://e.x"}}}))
        eng = mav_api.mav_engine
        with mock.patch.object(eng.mav_core, "_opencode_config_path", return_value=cfg), \
             mock.patch.object(eng, "CODE_IN_CLOUD", False), \
             mock.patch.object(eng, "restart_engine", return_value={"ok": True}) as restart:
            self.assertFalse(self.req("GET", "/api/config/code")[1]["enabled"])
            st, res, _ = self.req("POST", "/api/config/code", {"enabled": True})
            self.assertEqual(st, 200)
            self.assertTrue(res["enabled"])
            saved = json.loads(cfg.read_text())
            self.assertEqual(saved["model"], "x/y")
            self.assertIn("other", saved["mcp"])
            self.assertEqual(saved["mcp"]["code"]["command"][1], str(eng.CODE_TOOL))
            self.assertTrue(eng.CODE_TOOL.is_file())
            st, res, _ = self.req("POST", "/api/config/code", {"enabled": False})
            self.assertFalse(res["enabled"])
            self.assertNotIn("code", json.loads(cfg.read_text())["mcp"])
            self.assertEqual(restart.call_count, 2)
        shutil.rmtree(cfg.parent, ignore_errors=True)

    def test_in_the_cloud_it_is_the_platforms(self):
        with mock.patch.object(mav_api.mav_engine, "CODE_IN_CLOUD", True), \
             mock.patch.object(mav_api.mav_engine, "write_mcp") as write:
            st, res, _ = self.req("POST", "/api/config/code", {"enabled": False})
            self.assertEqual(st, 400)
            self.assertIn("sandbox", res["error"])
            write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
