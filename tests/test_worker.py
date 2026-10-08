"""The worker runs a routine end to end against the fake engine.

A routine's answer must reach a notification (a missing import once crashed
every routine right before it), and a routine must finish even when the end
is never announced on the event stream.

Run: python3 -m unittest discover -s tests -v
"""

import asyncio
import os
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
os.environ.setdefault("BOT_DIR", tempfile.mkdtemp())
# No database in unit tests: fail fast instead of waiting on a connection.
os.environ.setdefault("PG_DSN", "host=127.0.0.1 port=1 user=x dbname=x connect_timeout=1")

import httpx  # noqa: E402

import mav_worker  # noqa: E402
from ocbus import EventBus  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class WorkerRoutineTest(unittest.TestCase):
    def setUp(self):
        port = free_port()
        self.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "dashboard/tools/fake_engine.py"), "--port", str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.url = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(f"{self.url}/global/health", timeout=1)
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.1)
        self.sent = []
        self.saved = (mav_worker.OPENCODE_URL, mav_worker.notify, mav_worker.memory,
                      mav_worker.briefing_context)
        mav_worker.OPENCODE_URL = self.url
        mav_worker.notify = lambda title, body, **kw: self.sent.append((title, body, kw))

        class NoMemory:
            def context_block(self, *a, **k):
                return ""

        mav_worker.memory = NoMemory()

    def tearDown(self):
        self.proc.terminate()
        self.proc.wait(5)
        (mav_worker.OPENCODE_URL, mav_worker.notify, mav_worker.memory,
         mav_worker.briefing_context) = self.saved

    async def _run(self, job, with_bus=True, poll_every=None):
        mav_worker.http = httpx.AsyncClient(timeout=30)
        mav_worker.bus = EventBus(mav_worker.http, self.url if with_bus else "http://127.0.0.1:1")
        mav_worker.bus.start()
        orig_poll = mav_worker.poll_until_done
        if poll_every:
            mav_worker.poll_until_done = lambda sid, before, tr: orig_poll(sid, before, tr, every=poll_every)
        try:
            if with_bus:
                await asyncio.wait_for(mav_worker.bus.connected.wait(), 5)
            await asyncio.wait_for(mav_worker.run_job(job), 30)
        finally:
            mav_worker.poll_until_done = orig_poll
            await mav_worker.bus.stop()
            await mav_worker.http.aclose()

    def test_routine_answer_is_notified(self):
        asyncio.run(self._run({"name": "Morning", "prompt": "Good morning", "agent": "assistant"}))
        self.assertEqual(len(self.sent), 1)
        title, body, kw = self.sent[0]
        self.assertIn("Morning", title)
        self.assertIn("Good morning", body)
        self.assertTrue(kw["url"].startswith("./#chat/"))

    def test_scheduled_briefing_has_its_context(self):
        mav_worker.briefing_context = lambda *_: "<daily-briefing>\nctx\n</daily-briefing>"
        import ocbriefing

        asyncio.run(self._run(ocbriefing.default_job()))
        title, body, kw = self.sent[0]
        self.assertEqual(title, "☀️ Your briefing")
        self.assertEqual(kw["topic"], "briefing")
        self.assertIn("received your briefing", body)

    def test_routine_finishes_without_events(self):
        start = time.time()
        asyncio.run(self._run({"name": "Quiet", "prompt": "hello", "agent": "assistant"},
                              with_bus=False, poll_every=0.3))
        self.assertLess(time.time() - start, 15)
        self.assertEqual(len(self.sent), 1)


if __name__ == "__main__":
    unittest.main()
