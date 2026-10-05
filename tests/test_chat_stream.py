"""Chat answers end to end against the fake engine (no model, no database).

One turn = one message, however many steps or helpers the engine used; the
streamed text is exactly what a reload shows; the open turn is never shown
twice; live updates come from the engine's event stream.

Run: python3 -m unittest discover -s tests -v
"""

import socket
import subprocess
import sys
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "bot"), str(ROOT / "dashboard" / "server")]

import mav_api  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def entry(role, text, finish="stop", agent="assistant", synthetic=False, tool=None):
    parts = [{"type": "text", "text": text, "synthetic": synthetic}] if text else []
    if tool:
        parts.append({"type": "tool", "tool": tool, "state": {"status": "completed"}})
    return {"info": {"id": f"{role}-{text}", "role": role, "finish": finish,
                     "agent": agent, "time": {"created": 1}}, "parts": parts}


class GroupingTest(unittest.TestCase):
    def test_steps_of_one_turn_are_one_message(self):
        entries = [
            entry("user", "plan my trip"),
            entry("assistant", "Let me check.", finish="tool-calls", tool="task"),
            entry("assistant", "", finish="tool-calls", tool="webfetch"),
            entry("assistant", "Here is the plan."),
            entry("user", "thanks"),
            entry("assistant", "You're welcome."),
        ]
        msgs = mav_api.session_messages("x", entries)
        self.assertEqual([m["role"] for m in msgs], ["me", "mav", "me", "mav"])
        self.assertEqual(msgs[1]["text"], "Let me check.\n\nHere is the plan.")
        self.assertEqual(msgs[1]["agent"], "assistant")

    def test_hidden_user_parts_do_not_split_a_turn(self):
        entries = [
            entry("user", "hi"),
            entry("assistant", "Step one."),
            entry("user", "<memory>…</memory>", synthetic=True),
            entry("assistant", "Step two."),
        ]
        msgs = mav_api.session_messages("x", entries)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[1]["text"], "Step one.\n\nStep two.")

    def test_open_turn_is_dropped(self):
        msgs = [{"role": "me", "text": "a"}, {"role": "mav", "text": "partial"}]
        self.assertEqual(mav_api._drop_open_turn(msgs), msgs[:1])
        self.assertEqual(mav_api._drop_open_turn(msgs[:1]), msgs[:1])

    def test_tool_detail(self):
        task = {"tool": "task", "state": {"input": {"subagent_type": "researcher"}}}
        fetch = {"tool": "webfetch", "state": {"input": {"url": "https://example.org/a"}}}
        self.assertEqual(mav_api._tool_detail(task), "researcher")
        self.assertEqual(mav_api._tool_detail(fetch), "example.org")
        self.assertEqual(mav_api._tool_detail({"tool": "read"}), "")


class StreamTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        port = free_port()
        cls.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "dashboard/tools/fake_engine.py"),
             "--port", str(port), "--word-delay", "0.01"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        cls.url = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(f"{cls.url}/global/health", timeout=1)
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.1)
        cls.saved = (mav_api.OPENCODE_URL, mav_api.ENGINE_EVENTS, dict(mav_api._limit_ok))
        mav_api.OPENCODE_URL = cls.url
        mav_api.ENGINE_EVENTS = mav_api.EngineEvents(cls.url)
        mav_api._limit_ok.update(known=False, ok=False)
        mav_api._agents_cache.update(at=0.0, names=set())

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        mav_api.OPENCODE_URL, mav_api.ENGINE_EVENTS, limit = cls.saved
        mav_api._limit_ok.update(limit)

    def session(self) -> str:
        return mav_api.http_json(f"{self.url}/session", method="POST", body={"title": "dash: t"})["id"]

    def run_turn(self, sid, prompt):
        events = []
        for chunk in mav_api.stream_answer(prompt, sid, "assistant", raw_session=True):
            events.append(mav_api._parse_sse(chunk))
        return events

    def test_multi_step_answer_streams_as_one_message(self):
        mav_api.ENGINE_EVENTS.start()
        for _ in range(50):
            if mav_api.ENGINE_EVENTS.connected:
                break
            time.sleep(0.05)
        self.assertTrue(mav_api.ENGINE_EVENTS.connected, "event stream not used")

        sid = self.session()
        events = self.run_turn(sid, "research trains to Lyon")
        kinds = [e for e, _ in events]
        self.assertEqual(kinds[0], "start")
        self.assertEqual(kinds[-1], "done")
        self.assertNotIn("error", kinds)
        streamed = "".join(d.get("delta", "") for e, d in events if e == "delta")
        done = events[-1][1]["text"]
        self.assertEqual(streamed, done)
        tools = [d for e, d in events if e == "tool"]
        self.assertEqual(tools[0]["detail"], "researcher")

        # A second turn: the page shows exactly what was streamed, once each.
        events2 = self.run_turn(sid, "research again")
        msgs = mav_api.session_messages(sid)
        self.assertEqual([m["role"] for m in msgs], ["me", "mav", "me", "mav"])
        self.assertEqual(msgs[1]["text"], done)
        self.assertEqual(msgs[3]["text"], events2[-1][1]["text"])

    def test_limit_window_is_detected(self):
        sid = self.session()
        self.run_turn(sid, "hello there")
        full = mav_api.http_json(f"{self.url}/session/{sid}/message")
        mav_api._limit_ok.update(known=False, ok=False)
        url = mav_api._messages_url(sid, full)
        self.assertTrue(mav_api._limit_ok["ok"])
        self.assertIn("limit=", url)

    def test_ask_returns_the_whole_answer(self):
        sid = self.session()
        text = mav_api.ask("research something", "assistant", sid, raw_session=True)
        self.assertTrue(text.startswith("Let me look into that."))
        self.assertIn("print('hello')", text)


class AfterAnswerTest(unittest.TestCase):
    def test_one_call_for_title_and_facts(self):
        calls, renamed, saved = [], [], []
        orig = (mav_api.quick_completion, mav_api.rename_session,
                mav_api.set_session_meta, mav_api.save_learned_facts)
        mav_api.quick_completion = lambda instr, **k: calls.append(instr) or (
            "TITLE: Moving To Lyon\nFACTS:\n- User lives in Lyon")
        mav_api.rename_session = lambda sid, t: renamed.append(t) or True
        mav_api.set_session_meta = lambda sid, **k: None
        mav_api.save_learned_facts = lambda raw: saved.append(raw) or 1
        try:
            mav_api.after_answer("s1", "I live in Lyon now", "Nice!", True, True)
        finally:
            (mav_api.quick_completion, mav_api.rename_session,
             mav_api.set_session_meta, mav_api.save_learned_facts) = orig
        self.assertEqual(len(calls), 1)
        self.assertEqual(renamed, ["Moving To Lyon"])
        self.assertIn("- User lives in Lyon", saved[0])


if __name__ == "__main__":
    unittest.main()
