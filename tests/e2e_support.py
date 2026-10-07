"""Shared set-up for the browser tests: a fake engine, the real web app on a
throwaway folder, and Chromium through Playwright.

Not a test module itself (no test_ prefix). Playwright missing → the tests
using it skip; in CI it is installed (see .github/workflows/ci.yml).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "e2e-password-123"

try:
    from playwright.sync_api import sync_playwright
except Exception:  # noqa: BLE001
    sync_playwright = None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait(url: str, tries: int = 100) -> None:
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except urllib.error.HTTPError:
            return  # up, just not happy with us
        except Exception:  # noqa: BLE001
            time.sleep(0.1)


def chromium_path() -> str | None:
    for p in (os.environ.get("MAV_E2E_CHROMIUM"), "/opt/pw-browsers/chromium"):
        if p and Path(p).exists():
            return p
    return None  # Playwright's own download


class Stack:
    """Fake engine + mav_api on a temp BOT_DIR. Use as a context manager."""

    def __init__(self, engine_args: tuple = (), env: dict | None = None, model: str = "ollama/llama3.1"):
        self.engine_args = engine_args
        self.extra_env = env or {}
        self.model = model

    def __enter__(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "cfg").mkdir()
        (self.tmp / "server.env").touch()
        if self.model:  # a model is set, so the chat is open (no "Connect a model")
            (self.tmp / "cfg" / "opencode.json").write_text('{"model": "%s"}' % self.model)
        ep, ap = free_port(), free_port()
        self.procs = [subprocess.Popen(
            [sys.executable, str(ROOT / "dashboard/tools/fake_engine.py"), "--port", str(ep), *self.engine_args],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
        env = {**os.environ,
               "OPENCODE_URL": f"http://127.0.0.1:{ep}", "MAV_STATIC": str(ROOT / "dashboard"),
               "BOT_DIR": str(self.tmp), "MAV_API_PORT": str(ap), "MAV_API_BIND": "127.0.0.1",
               "OPENCODE_CONFIG": str(self.tmp / "cfg" / "opencode.json"),
               "MAV_ENV_SERVER": str(self.tmp / "server.env"),
               "PG_DSN": "host=127.0.0.1 port=1 user=x dbname=x connect_timeout=1",
               **self.extra_env}
        self.log = open(self.tmp / "api.log", "w")  # noqa: SIM115
        self.procs.append(subprocess.Popen(
            [sys.executable, "mav_api.py"], cwd=ROOT / "dashboard" / "server", env=env,
            stdout=self.log, stderr=subprocess.STDOUT))
        self.url = f"http://127.0.0.1:{ap}/"
        wait(f"http://127.0.0.1:{ep}/global/health")
        wait(self.url + "api/health")
        return self

    def __exit__(self, *exc):
        for p in self.procs:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
        self.log.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


def launch(pw):
    return pw.chromium.launch(executable_path=chromium_path())


def signed_in(browser, stack: Stack, **ctx):
    """A browser context with a session, the welcome flow already done."""
    context = browser.new_context(**ctx)
    req = context.request
    req.post(stack.url + "api/auth/setup", data={"password": PASSWORD})
    req.post(stack.url + "api/auth/login", data={"password": PASSWORD})
    req.post(stack.url + "api/onboarding", data={"done": True})
    return context


def watch_errors(page) -> list:
    errors: list = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    return errors
