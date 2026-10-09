"""Chat answers end to end against the fake engine (no model, no database).

One turn = one message, however many steps or helpers the engine used; the
streamed text is exactly what a reload shows; the open turn is never shown
twice; live updates come from the engine's event stream.

Run: python3 -m unittest discover -s tests -v
"""

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
sys.path[:0] = [str(ROOT / "bot"), str(ROOT / "dashboard" / "server")]

import mav_api  # noqa: E402
import mav_chat  # noqa: E402


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
        # The turn keeps its tool calls, in the order they happened.
        self.assertEqual([t["name"] for t in msgs[1]["tools"]], ["task", "webfetch"])
        self.assertNotIn("tools", msgs[3])

    def test_tool_info_has_the_details(self):
        part = {"type": "tool", "callID": "c1", "tool": "bash", "state": {
            "status": "completed", "title": "List files",
            "input": {"command": "ls -la"}, "output": "x" * 5000,
            "time": {"start": 1000, "end": 2500}}}
        info = mav_api._tool_info(part)
        self.assertEqual((info["id"], info["name"], info["status"]), ("c1", "bash", "completed"))
        self.assertEqual((info["start"], info["end"]), (1000, 2500))
        self.assertIn('"command": "ls -la"', info["input"])
        self.assertLess(len(info["output"]), 4100)
        self.assertIn("more characters", info["output"])
        self.assertNotIn("error", info)
        # A step that has only just started stays small.
        self.assertEqual(set(mav_api._tool_info({"tool": "read", "state": {}})),
                         {"id", "name", "status", "detail"})

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


class AttachmentTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def part(self, name, mime, size=10):
        path = self.dir / name
        path.write_bytes(b"x" * size)
        return mav_chat._parts("look", [{"url": f"file://{path}", "mime": mime, "filename": name}])[1]

    def test_the_model_gets_only_what_it_takes(self):
        self.assertEqual(self.part("a.png", "image/png")["type"], "file")
        self.assertEqual(self.part("a.pdf", "application/pdf")["mime"], "application/pdf")
        # Text goes in as text, whatever its exact type.
        csv = self.part("a.csv", "text/csv")
        self.assertEqual((csv["type"], csv["mime"]), ("file", "text/plain"))
        self.assertEqual(self.part("a.json", "application/json")["mime"], "text/plain")

    def test_what_it_refuses_is_described_instead(self):
        docx = self.part("a.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertEqual(docx["type"], "text")
        self.assertTrue(docx["synthetic"])
        self.assertIn(str(self.dir / "a.docx"), docx["text"])
        self.assertIn("load_from_chat", docx["text"])
        big = self.part("big.jpg", "image/jpeg", size=mav_chat.MAX_IMAGE_BYTES + 1)
        self.assertEqual(big["type"], "text")
        self.assertEqual(self.part("huge.txt", "text/plain", size=mav_chat.MAX_TEXT_BYTES + 1)["type"], "text")


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
        done_tools = [d for d in tools if d["status"] == "completed"]
        self.assertEqual([d["name"] for d in done_tools], ["task", "webfetch"])
        self.assertIn("researcher", done_tools[0]["input"])
        self.assertTrue(done_tools[1]["output"].startswith("# Answer"))
        self.assertEqual(done_tools[1]["end"] - done_tools[1]["start"], 420)
        # How long it took, sent just before "done" (roadmap 2.1).
        self.assertEqual(kinds[-2], "metrics")
        m = events[-2][1]
        self.assertEqual(m["steps"], 2)
        # "Let me look into that." comes first; the whole answer waits on the
        # 0.6 s helper step.
        self.assertGreaterEqual(m["ttft_ms"], 0)
        self.assertGreater(m["total_ms"], 600)
        self.assertGreater(m["total_ms"], m["ttft_ms"])
        self.assertGreater(m["input_tokens"], 0)

        # A second turn: the page shows exactly what was streamed, once each.
        events2 = self.run_turn(sid, "research again")
        msgs = mav_api.session_messages(sid)
        self.assertEqual([m["role"] for m in msgs], ["me", "mav", "me", "mav"])
        self.assertEqual(msgs[1]["text"], done)
        self.assertEqual(msgs[3]["text"], events2[-1][1]["text"])

    def test_a_refused_attachment_is_an_error_at_once(self):
        # The provider refuses the file: the step ends with an error and no
        # finish. The person sees why within seconds, not after the idle limit.
        sid = self.session()
        t = time.monotonic()
        events = [mav_api._parse_sse(c) for c in mav_api.stream_answer(
            "what is in it?", sid, "assistant", raw_session=True,
            files=[{"url": "https://example.org/a.zip", "mime": "application/zip", "filename": "a.zip"}])]
        self.assertLess(time.monotonic() - t, 15)
        self.assertEqual(events[-1][0], "error")
        self.assertIn("not supported", events[-1][1]["message"])

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
