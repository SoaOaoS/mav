"""Usage, cost and budget: the store, and the web app recording real answers.

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

import ocusage  # noqa: E402
import mav_api  # noqa: E402


def entry(inp, out, cost, model="claude-x", provider="anthropic"):
    return {"info": {"role": "assistant", "tokens": {"input": inp, "output": out, "reasoning": 5,
                                                      "cache": {"read": 10, "write": 0}},
                     "cost": cost, "modelID": model, "providerID": provider}}


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.u = ocusage.Usage(Path(tempfile.mkdtemp()) / "usage.json")

    def test_tally(self):
        t = ocusage.tally([entry(100, 20, 0.01), entry(50, 10, 0.02)])
        self.assertEqual((t["input"], t["output"]), (170, 40))  # + cache reads, + reasoning
        self.assertAlmostEqual(t["cost"], 0.03)
        self.assertEqual(t["model"], "anthropic/claude-x")

    def test_speed_medians(self):
        self.assertEqual(self.u.speed_summary(), {"answers": 0})
        for ttft, total, steps, inp, cached in ((800, 3000, 1, 4000, 0), (1200, 5000, 2, 6000, 3000),
                                                 (30000, 60000, 4, 9000, 0)):
            self.u.record_speed("chat", ttft, total, steps, inp, cached)
        self.u.record_speed("routine", 99999, 99999, 9, 1, 0)  # routines are not chat speed
        sp = self.u.speed_summary()
        self.assertEqual(sp["answers"], 3)
        self.assertEqual(sp["ttft_ms"], 1200)        # the median, not the mean (10 667)
        self.assertEqual(sp["ttft_p90_ms"], 30000)
        self.assertEqual(sp["total_ms"], 5000)
        self.assertEqual(sp["input_tokens"], 6000)
        self.assertAlmostEqual(sp["steps"], 2.33, places=2)
        self.assertEqual(sp["cached_pct"], 15.8)
        self.assertEqual(ocusage.speed_stats([{"ttft": None, "total": 10}])["ttft_ms"], None)

    def test_speed_keeps_a_bounded_history(self):
        for i in range(ocusage.SPEED_KEEP + 20):
            self.u.record_speed("chat", i, i, 1)
        import json  # noqa: PLC0415
        self.assertEqual(len(json.loads(self.u.path.read_text())["speed"]), ocusage.SPEED_KEEP)

    def test_answer_metrics(self):
        m = mav_api.answer_metrics(100.0, 101.25, 104.0, [entry(1000, 50, 0)["info"], entry(200, 30, 0)["info"]])
        self.assertEqual((m["ttft_ms"], m["total_ms"], m["steps"]), (1250, 4000, 2))
        self.assertEqual((m["input_tokens"], m["cached_tokens"], m["output_tokens"]), (1220, 20, 90))
        self.assertIsNone(mav_api.answer_metrics(100.0, None, 101.0, [])["ttft_ms"])

    def test_summary_by_source(self):
        self.u.record_entries("chat", [entry(100, 20, 0.5)])
        self.u.record_entries("routine", [entry(10, 10, 0.25)])
        self.u.record_entries("background", [entry(1, 1, 0.0)])
        self.u.record("chat")  # nothing to count: ignored
        s = self.u.summary(7)
        self.assertAlmostEqual(s["cost"], 0.75)
        self.assertEqual(s["answers"], 3)
        self.assertEqual(s["by_source"]["chat"]["answers"], 1)
        self.assertAlmostEqual(s["by_source"]["routine"]["cost"], 0.25)
        self.assertEqual(len(s["days"]), 7)
        self.assertAlmostEqual(s["days"][-1]["cost"], 0.75)
        self.assertIn("anthropic/claude-x", s["models"])

    def test_budget_warn_and_stop(self):
        self.assertFalse(self.u.blocked())
        self.u.set_budget(1.0, "warn")
        self.u.record("chat", 1, 1, 0.85)
        self.assertEqual(self.u.alert_due(), 80)
        self.assertIsNone(self.u.alert_due())      # once per month
        self.u.record("chat", 1, 1, 0.2)
        self.assertFalse(self.u.blocked())         # warn never blocks
        self.assertEqual(self.u.alert_due(), 100)
        self.u.set_budget(1.0, "stop")
        self.assertTrue(self.u.blocked())
        self.u.set_budget(5.0, "stop")             # raising it unblocks
        self.assertFalse(self.u.blocked())
        with self.assertRaises(ValueError):
            self.u.set_budget(-1)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ApiUsageTest(unittest.TestCase):
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
        cls.saved = (mav_api.OPENCODE_URL, mav_api.ENGINE_EVENTS, mav_api.USAGE,
                     mav_api.send_push, mav_api.record_notification)
        mav_api.OPENCODE_URL = cls.url
        mav_api.ENGINE_EVENTS = mav_api.EngineEvents(cls.url)
        mav_api._agents_cache.update(at=0.0, names=set())
        mav_api.send_push = lambda *a, **k: 0
        mav_api.record_notification = lambda *a, **k: None

    def setUp(self):
        mav_api.USAGE = ocusage.Usage(Path(tempfile.mkdtemp()) / "usage.json")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        (mav_api.OPENCODE_URL, mav_api.ENGINE_EVENTS, mav_api.USAGE,
         mav_api.send_push, mav_api.record_notification) = cls.saved

    def session(self):
        return mav_api.http_json(f"{self.url}/session", method="POST", body={"title": "dash: t"})["id"]

    def test_answers_are_counted(self):
        mav_api.ask("hello there", "assistant", self.session(), raw_session=True)
        s = mav_api.USAGE.summary(1)
        self.assertEqual(s["by_source"]["routine"]["answers"], 1)
        self.assertGreater(s["cost"], 0)

    def test_stop_budget_refuses_new_answers(self):
        mav_api.USAGE.set_budget(0.5, "stop")
        mav_api.USAGE.record("chat", 1, 1, 1.0)
        out = mav_api.ask("hello", "assistant", self.session(), raw_session=True)
        self.assertTrue(out.startswith("Error:"))
        self.assertIn("budget", out)
        self.assertEqual(mav_api.quick_completion("anything"), "")

    def test_background_uses_the_small_model(self):
        mav_api.USAGE.set_small_model("fake/tiny-1")
        mav_api.quick_completion("Write a title")
        s = mav_api.USAGE.summary(1)
        self.assertEqual(s["by_source"]["background"]["answers"], 1)
        self.assertIn("fake/tiny-1", s["models"])


if __name__ == "__main__":
    unittest.main()
