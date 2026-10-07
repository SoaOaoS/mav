"""The first-run welcome, end to end in a real browser (fake engine).

Skipped when Playwright (and a Chromium) is not installed. Locally:
    pip install playwright && playwright install chromium
    python3 -m unittest tests.test_e2e_onboarding -v
"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    from playwright.sync_api import sync_playwright
except Exception:  # noqa: BLE001
    sync_playwright = None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait(url: str) -> None:
    for _ in range(80):
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
    return None  # let Playwright use its own download


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class OnboardingE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        (cls.tmp / "cfg").mkdir()
        (cls.tmp / "server.env").touch()
        ep, ap = free_port(), free_port()
        cls.procs = [subprocess.Popen(
            [sys.executable, str(ROOT / "dashboard/tools/fake_engine.py"), "--port", str(ep)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
        env = {**os.environ,
               "OPENCODE_URL": f"http://127.0.0.1:{ep}", "MAV_STATIC": str(ROOT / "dashboard"),
               "BOT_DIR": str(cls.tmp), "MAV_API_PORT": str(ap), "MAV_API_BIND": "127.0.0.1",
               "OPENCODE_CONFIG": str(cls.tmp / "cfg" / "opencode.json"),
               "MAV_ENV_SERVER": str(cls.tmp / "server.env"),
               "PG_DSN": "host=127.0.0.1 port=1 user=x dbname=x connect_timeout=1"}
        cls.procs.append(subprocess.Popen(
            [sys.executable, "mav_api.py"], cwd=ROOT / "dashboard" / "server", env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        cls.url = f"http://127.0.0.1:{ap}/"
        wait(f"http://127.0.0.1:{ep}/global/health")
        wait(cls.url + "api/health")

    @classmethod
    def tearDownClass(cls):
        for p in cls.procs:
            p.terminate()
            p.wait(5)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_welcome_flow(self):
        with sync_playwright() as pw:
            try:
                b = pw.chromium.launch(executable_path=chromium_path())
            except Exception as exc:  # noqa: BLE001
                self.skipTest(f"no Chromium: {exc}")
            pg = b.new_page()
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(self.url)
            pg.request.post(self.url + "api/auth/setup", data={"password": "e2e-password-123"})
            pg.goto(self.url)
            pg.wait_for_selector("#welcome:not([hidden])", timeout=8000)

            # 1. model: Ollama needs no key
            pg.click('[data-obprov="ollama"]')
            pg.fill("#obModel", "llama3.1")
            pg.click("#obNext")
            pg.wait_for_selector('.ob-step[data-ob="2"]:not([hidden])', timeout=8000)
            # 2. about you
            pg.fill("#obCity", "Toulouse")
            pg.select_option("#obLang", "en")
            pg.click("#obNext")
            pg.wait_for_selector('.ob-step[data-ob="3"]:not([hidden])', timeout=8000)
            # 3. routines: briefing (on by default) + the first template
            pg.locator("#obRoutines input[type=checkbox]").first.check()
            pg.click("#obNext")
            pg.wait_for_selector('.ob-step[data-ob="4"]:not([hidden])', timeout=8000)
            self.assertIn("2 routines", pg.inner_text("#obSummary"))
            # 4. first briefing opens its chat
            pg.click("#obNext")
            pg.wait_for_function("location.hash.startsWith('#chat/')", timeout=8000)
            self.assertTrue(pg.locator("#welcome").is_hidden())

            # Done once: a reload does not show it again.
            pg.reload()
            pg.wait_for_timeout(1500)
            self.assertTrue(pg.locator("#welcome").is_hidden())
            self.assertEqual(errors, [])
            b.close()
