"""The daily briefing: its context, its routine, and a run end to end.

Run: python3 -m unittest discover -s tests -v
"""

import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "bot"), str(ROOT / "dashboard" / "server")]

import ocbriefing  # noqa: E402
import ocjobs  # noqa: E402
import mav_api  # noqa: E402


class ContextTest(unittest.TestCase):
    def test_context_gathers_and_filters(self):
        now = 1_800_000_000
        ctx = ocbriefing.build_context(
            facts=[{"fact": "User lives in Lyon"}],
            notifications=[
                {"ts": now - 3600, "topic": "watch", "title": "Price drop", "body": "Shoes 59 €"},
                {"ts": now - 3 * 86400, "topic": "watch", "title": "Old alert", "body": "x"},
                {"ts": now - 600, "topic": "briefing", "title": "☀️ Your briefing", "body": "y"},
            ],
            drafts=2,
            interests=[{"label": "Jazz"}, {"label": "Muted thing", "muted": True}],
            now=now,
        )
        self.assertIn("<daily-briefing>", ctx)
        self.assertIn("User lives in Lyon", ctx)
        self.assertIn("Price drop", ctx)
        self.assertNotIn("Old alert", ctx)           # older than 24 h
        self.assertNotIn("Your briefing", ctx)       # never brief about the briefing
        self.assertIn("2 draft(s)", ctx)
        self.assertIn("Jazz", ctx)
        self.assertNotIn("Muted thing", ctx)

    def test_empty_sources(self):
        ctx = ocbriefing.build_context()
        self.assertIn("(nothing yet)", ctx)
        self.assertIn("(none)", ctx)

    def test_default_job_is_a_valid_routine(self):
        job = ocbriefing.default_job("06:45")
        self.assertTrue(ocjobs.validate(job))
        self.assertTrue(ocbriefing.is_briefing(job))
        self.assertEqual(job["time"], "06:45")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BriefingApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        port = free_port()
        cls.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "dashboard/tools/fake_engine.py"), "--port", str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        cls.url = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(f"{cls.url}/global/health", timeout=1)
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.1)
        cls.saved = (mav_api.OPENCODE_URL, mav_api.ENGINE_EVENTS, mav_api.JOBS_FILE,
                     mav_api.send_push, mav_api.record_notification)
        mav_api.OPENCODE_URL = cls.url
        mav_api.ENGINE_EVENTS = mav_api.EngineEvents(cls.url)
        mav_api.JOBS_FILE = Path(tempfile.mkdtemp()) / "jobs.json"
        mav_api._agents_cache.update(at=0.0, names=set())
        cls.pushed = []
        mav_api.send_push = lambda title, body, link="": cls.pushed.append((title, body, link))
        mav_api.record_notification = lambda *a, **k: None

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        (mav_api.OPENCODE_URL, mav_api.ENGINE_EVENTS, mav_api.JOBS_FILE,
         mav_api.send_push, mav_api.record_notification) = cls.saved

    def test_settings_and_run(self):
        self.assertFalse(mav_api.get_briefing()["exists"])
        self.assertFalse(mav_api.set_briefing(True, "25:00")["ok"])
        res = mav_api.set_briefing(True, "06:30")
        self.assertTrue(res["ok"] and res["enabled"])
        self.assertEqual(mav_api.get_briefing()["time"], "06:30")
        res = mav_api.set_briefing(False)
        self.assertFalse(res["enabled"])
        self.assertTrue(res["exists"])  # kept, so its chat and history stay

        run = mav_api.run_briefing_now()
        self.assertTrue(run["ok"])
        sid = run["session"]
        for _ in range(100):
            if self.pushed:
                break
            time.sleep(0.1)
        self.assertEqual(self.pushed[0][0], "☀️ Your briefing")
        msgs = mav_api.session_messages(sid)
        self.assertEqual(msgs[0]["text"], ocbriefing.VISIBLE_PROMPT)  # context stays hidden
        self.assertIn("(I received your briefing.)", msgs[-1]["text"])


if __name__ == "__main__":
    unittest.main()
