"""Answering: the engine's event stream, the run registry that keeps an
answer going when the page leaves, and the streamed answer itself.

Part of the web app server (see mav_api.py).
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import mav_core
import mav_engine
import mav_store
import mav_chat


RUN_TTL = int(os.environ.get("MAV_RUN_TTL", "180"))  # keep finished runs this long


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class Run:
    """One in-flight (or just-finished) answer, observable by any subscriber."""

    def __init__(self, sid: str, prompt: str, agent: str, files: list, *,
                 raw_session: bool = False, with_memory: bool = False, context: str = ""):
        self.sid = sid or ""
        self.context = context
        self.prompt = prompt
        self.agent = agent
        self.files = files or []
        self.raw_session = raw_session
        self.with_memory = with_memory
        self.events: list[tuple[str, dict]] = []
        self.text = ""
        self.agent_out = agent
        self.recalled = 0
        self.tools: list[dict] = []
        self.metrics: dict = {}
        self.status = "running"  # running | done | error
        self.interrupted = False
        self.error: str | None = None
        self.started = time.time()
        self.updated = self.started
        self._cv = threading.Condition()
        self._thread: threading.Thread | None = None
        self.user = mav_core.uid()

    # ---- producer side -------------------------------------------------
    def start(self) -> None:
        # Looked up here (not in __init__) so a caller/test can swap `_work`;
        # the answer is written as the person who asked for it.
        self._thread = mav_core.spawn(lambda: self._work())

    def _emit(self, event: str, data: dict) -> None:
        with self._cv:
            self.events.append((event, data))
            if event == "start":
                self.agent_out = data.get("agent") or self.agent_out
                self.recalled = int(data.get("recalled") or 0)
            elif event == "delta":
                self.text += data.get("delta") or ""
            elif event == "reset":
                self.text = data.get("text") or ""
            elif event == "tool":
                name = data.get("name") or "tool"
                key = data.get("id") or name
                status = data.get("status") or "running"
                entry = next((t for t in self.tools if t.get("id", t.get("name")) == key), None)
                if not entry:
                    entry = {"id": key, "name": name, "status": status,
                             "detail": data.get("detail") or ""}
                    self.tools.append(entry)
                entry["status"] = status
                for k in ("title", "input", "output", "error", "start", "end"):
                    if data.get(k):
                        entry[k] = data[k]
            elif event == "done":
                if not self.text and data.get("text"):
                    self.text = data.get("text") or ""
                self.interrupted = bool(data.get("interrupted"))
                self.status = "done"
            elif event == "metrics":
                self.metrics = data
            elif event == "error":
                self.error = data.get("message") or "engine error"
                self.status = "error"
            self.updated = time.time()
            self._cv.notify_all()

    def _work(self) -> None:
        try:
            for chunk in stream_answer(
                self.prompt, self.sid, self.agent, self.files,
                raw_session=self.raw_session, with_memory=self.with_memory,
                context=self.context,
            ):
                event, data = _parse_sse(chunk)
                if event:
                    self._emit(event, data)
        except Exception as exc:  # noqa: BLE001
            self._emit("error", {"message": str(exc)[:300], "session": self.sid})
        finally:
            with self._cv:
                if self.status == "running":
                    self.status = "done"
                self.updated = time.time()
                self._cv.notify_all()

    # ---- consumer side -------------------------------------------------
    def snapshot(self) -> dict:
        with self._cv:
            return {
                "session": self.sid, "text": self.text, "tools": list(self.tools),
                "status": self.status, "interrupted": self.interrupted,
                "agent": self.agent_out, "recalled": self.recalled,
                "error": self.error, "seq": len(self.events), "metrics": self.metrics,
            }

    def follow(self, from_seq: int = 0):
        """Yield the events a client has not seen, then live events until done."""
        i = max(0, int(from_seq))
        while True:
            with self._cv:
                if i >= len(self.events) and self.status == "running":
                    self._cv.wait(timeout=20)
                pending = self.events[i:]
                i = len(self.events)
                done = self.status != "running"
            if pending:
                for event, data in pending:
                    yield _sse(event, data)
                continue
            if done:
                return
            yield ": ping\n\n"  # keep-alive so proxies do not drop the stream


def _parse_sse(block: str) -> tuple[str, dict]:
    event = ""
    data: list[str] = []
    for line in (block or "").split("\n"):
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
    if not event:
        return "", {}
    try:
        return event, json.loads("\n".join(data) or "{}")
    except Exception:  # noqa: BLE001
        return event, {}


RUNS: dict[str, Run] = {}


_runs_lock = threading.Lock()


def _run_cleanup() -> None:
    now = time.time()
    with _runs_lock:
        for sid, run in list(RUNS.items()):
            if run.status != "running" and now - run.updated > RUN_TTL:
                RUNS.pop(sid, None)


def start_run(prompt: str, sid: str, agent: str = "", files: list | None = None, *,
              raw_session: bool = False, with_memory: bool = False,
              context: str = "") -> Run:
    """Start (or restart) the answer for a session and return its Run."""
    _run_cleanup()
    run = Run(sid, prompt, agent, files or [], raw_session=raw_session,
              with_memory=with_memory, context=context)
    with _runs_lock:
        RUNS[sid] = run
    run.start()
    return run


def get_run(sid: str) -> Run | None:
    _run_cleanup()
    with _runs_lock:
        return RUNS.get(sid)


def runs_view() -> list[dict]:
    _run_cleanup()
    me = mav_core.uid()
    with _runs_lock:
        runs = [r for r in RUNS.values() if r.user == me]
    out = []
    for r in runs:
        out.append({
            "session": r.sid, "status": r.status, "agent": r.agent_out,
            "started": r.started, "updated": r.updated,
            "interrupted": r.interrupted, "error": r.error,
            "text_len": len(r.text), "tools": len(r.tools),
        })
    out.sort(key=lambda x: x["updated"], reverse=True)
    return out


def stop_run(sid: str) -> dict:
    """Ask a run to stop; the partial answer is kept, not discarded."""
    if not sid:
        return {"ok": False, "error": "missing id"}
    request_interrupt(sid)
    abort_session(sid)
    return {"ok": True}


def request_interrupt(sid: str) -> bool:
    if not sid:
        return False
    mav_chat.INTERRUPTED.add(sid)
    return True


def ensure_session(sid: str = "", agent: str = "") -> str:
    if sid:
        return sid
    sessions = mav_chat.list_sessions()
    if sessions:
        return sessions[0]["id"]
    return mav_chat.create_session(agent=agent)["id"]


def abort_session(sid: str) -> None:
    try:
        mav_core.http_json(f"{mav_core.OPENCODE_URL}/session/{sid}/abort", method="POST")
    except Exception:
        pass


def interrupt_session(sid: str) -> dict:
    """Stop the current answer and let a queued message take over.

    Marks the session so the running stream aborts the engine itself (and does
    not remember the partial answer), then aborts immediately for responsiveness.
    """
    if not sid:
        return {"ok": False, "error": "missing id"}
    request_interrupt(sid)
    abort_session(sid)
    return {"ok": True}


class EngineEvents:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.connected = False
        self._lock = threading.Lock()
        self._marks: dict[str, int] = {}
        self._cv = threading.Condition(self._lock)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    @staticmethod
    def session_of(event: dict) -> str:
        props = event.get("properties") or {}
        return (
            props.get("sessionID")
            or (props.get("info") or {}).get("sessionID")
            or (props.get("part") or {}).get("sessionID")
            or ""
        )

    def _bump(self, sid: str) -> None:
        with self._cv:
            self._marks[sid] = self._marks.get(sid, 0) + 1
            self._cv.notify_all()

    def mark(self, sid: str) -> int:
        with self._lock:
            return self._marks.get(sid, 0)

    def wait(self, sid: str, seen: int, timeout: float) -> int:
        """Block until something happens in `sid` (or timeout); new mark."""
        with self._cv:
            if self._marks.get(sid, 0) == seen:
                self._cv.wait(timeout)
            return self._marks.get(sid, 0)

    def _loop(self) -> None:
        backoff = 1.0
        while True:
            try:
                req = urllib.request.Request(
                    f"{self.base_url}/event", headers={"Accept": "text/event-stream"}
                )
                with urllib.request.urlopen(req, timeout=60) as r:
                    self.connected = True
                    backoff = 1.0
                    data: list[str] = []
                    for raw in r:
                        line = raw.decode("utf-8", "replace").rstrip("\r\n")
                        if line.startswith("data:"):
                            data.append(line[5:].strip())
                            continue
                        if line or not data:
                            continue
                        try:
                            event = json.loads("\n".join(data))
                        except Exception:  # noqa: BLE001
                            event = {}
                        data = []
                        sid = self.session_of(event) if isinstance(event, dict) else ""
                        if sid:
                            self._bump(sid)
            except Exception:  # noqa: BLE001
                pass
            self.connected = False
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


ENGINE_EVENTS = EngineEvents(mav_core.OPENCODE_URL)


# Does the engine honour ?limit= (newest N messages)? Checked once, lazily.
_limit_ok: dict = {"known": False, "ok": False}


MSG_WINDOW = 80


def _messages_url(sid: str, full: list | None = None) -> str:
    """Messages URL for polling, limited to the newest entries when supported."""
    base = f"{mav_core.OPENCODE_URL}/session/{sid}/message"
    if not _limit_ok["known"] and full:
        try:
            tail = mav_core.http_json(f"{base}?limit=1", timeout=8) or []
            if len(full) > 1:  # with a single message, first == last: no answer
                last_full = (full[-1].get("info") or {}).get("id")
                _limit_ok["ok"] = (
                    len(tail) == 1 and (tail[0].get("info") or {}).get("id") == last_full
                )
                _limit_ok["known"] = True
        except Exception:  # noqa: BLE001
            _limit_ok.update(known=True, ok=False)
    return f"{base}?limit={MSG_WINDOW}" if _limit_ok["ok"] else base


def _tool_detail(part: dict) -> str:
    """A human hint for a tool step: which helper, which page, which search."""
    state = part.get("state") or {}
    inp = state.get("input") or {}
    if part.get("tool") == "task":
        return str(inp.get("subagent_type") or inp.get("agent") or "")
    if inp.get("url"):
        return urllib.parse.urlparse(str(inp["url"])).netloc or ""
    if inp.get("query"):
        return str(inp["query"])[:60]
    return ""


TOOL_TEXT_MAX = 4000


def _clip(value, limit: int = TOOL_TEXT_MAX) -> str:
    """A tool input/output as readable text, cut to a sane size."""
    if value in (None, "", {}, []):
        return ""
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            value = str(value)
    value = value.strip()
    if len(value) > limit:
        value = value[:limit].rstrip() + f"\n… ({len(value) - limit} more characters)"
    return value


def _tool_info(part: dict) -> dict:
    """Everything the web app shows about one tool call, in one dict.

    Optional keys (input, output, error, title, start, end) are only set when
    the engine reported them, so a step that has just started stays small.
    """
    state = part.get("state") or {}
    info = {
        "id": part.get("callID") or part.get("id") or part.get("tool") or "tool",
        "name": part.get("tool") or "tool",
        "status": state.get("status") or "running",
        "detail": _tool_detail(part),
    }
    extra = {
        "title": str(state.get("title") or "")[:200],
        "input": _clip(state.get("input")),
        "output": _clip(state.get("output")),
        "error": _clip(state.get("error"), 1500),
    }
    times = state.get("time") or {}
    for k in ("start", "end"):
        try:
            if times.get(k):
                extra[k] = int(times[k])
        except (TypeError, ValueError):
            pass
    info.update({k: v for k, v in extra.items() if v})
    return info


def stream_answer(
    prompt: str,
    sid: str,
    agent: str = "",
    files: list | None = None,
    raw_session: bool = False,
    with_memory: bool = False,
    context: str = "",
):
    """SSE answer, collected server-side: reliable and reasoning-free.

    We let the engine run the request, then poll the session messages until
    we get a finished assistant message. Only "text" parts are sent: tool
    steps and internal reasoning never appear. The end is detected on the
    `finish` field
    du message, pas sur un signal de flux qui peut se perdre.
    """
    sid = sid if raw_session else ensure_session(sid, agent)
    # Consume any stale interrupt mark so it cannot kill this new answer.
    if not raw_session:
        mav_chat.INTERRUPTED.discard(sid)
    body: dict = {"parts": mav_chat._parts(prompt, files or [])}
    meta = {} if raw_session else mav_chat.session_meta(sid)
    # Explicit choice > the conversation's agent > the configured default.
    ag = agent or meta.get("agent") or mav_core.DEFAULT_AGENT
    if not raw_session and agent and agent != meta.get("agent"):
        mav_chat.set_session_meta(sid, agent=agent)

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    if ag:
        known = mav_engine.valid_agents()
        if known and ag not in known:
            if agent and agent != mav_core.DEFAULT_AGENT:
                yield sse("error", {"message": f"Unknown helper: {ag}. Restart the assistant if you just created it.", "session": sid})
                return
            ag = ""  # the default helper is not installed: let the engine pick
    if ag:
        body["agent"] = ag
    body.update(mav_chat._model_body())

    if mav_store.budget_blocked():
        b = mav_core.USAGE.budget()
        yield sse("error", {"message": (
            f"Your monthly budget (${b['monthly_usd']:.2f}) is used up. Raise it in "
            "Settings → Usage, or wait until next month."), "session": sid})
        return

    # Instant keyword title while the real one is generated after the answer.
    needs_title = False
    if not raw_session and prompt.strip():
        try:
            current = mav_chat.session_title(sid)[len(mav_chat.PREFIX):]
            if current in mav_chat.LEGACY_TITLES:
                mav_chat.rename_session(sid, mav_chat.quick_title(prompt))
                needs_title = True
            elif not meta.get("titled") and not meta.get("title_locked"):
                needs_title = True
        except Exception:
            pass

    # Start marker: any message older than our prompt is ignored.
    try:
        before = mav_core.http_json(f"{mav_core.OPENCODE_URL}/session/{sid}/message", timeout=12) or []
    except Exception:
        before = []
    before_ids = {(e.get("info") or {}).get("id") for e in before}

    # Memory: injected at the start of a conversation only (afterwards the
    # conversation itself is the context). Synthetic, so it is not displayed.
    recalled = 0
    if (not raw_session and not before) or with_memory:
        ctx = mav_chat.memory_context(prompt)
        if ctx:
            recalled = ctx.count("] Q:") + ctx.count("\n- ")
            body["parts"].insert(0, {"type": "text", "text": ctx, "synthetic": True})

    # Extra hidden context from the caller (e.g. the daily briefing's data).
    if context:
        body["parts"].insert(0, {"type": "text", "text": context, "synthetic": True})

    t_sent = time.time()  # speed is measured from here (2.1: time to first word)
    try:
        mav_core.http_json(f"{mav_core.OPENCODE_URL}/session/{sid}/prompt_async", method="POST", body=body)
    except Exception as exc:  # noqa: BLE001
        yield sse("error", {"message": f"Could not start: {exc}", "session": sid})
        return

    yield sse("start", {"session": sid, "agent": ag, "recalled": recalled})
    t_first: float | None = None

    deadline = time.time() + 900      # overall guard (15 min)
    idle_limit = 240                  # no real progress (4 min)
    last_progress = time.time()
    last_sig = None
    last_text = ""
    last_sent = ""
    accepted = False
    finished_text = None
    engine_error = None
    tools_state: dict = {}
    interrupted = False
    # Text of every assistant entry of this turn, by id, in order: a window of
    # the newest messages can scroll an early step out, its text stays here.
    texts: dict[str, str] = {}
    turn_info: dict[str, dict] = {}  # tokens and cost of every step
    url = _messages_url(sid, before)
    ENGINE_EVENTS.start()
    mark = ENGINE_EVENTS.mark(sid)
    heard = False
    pause = 0.15

    while time.time() < deadline and time.time() - last_progress < idle_limit:
        # Stop requested from another request (interrupt-and-reprocess): abort
        # the engine, keep whatever text we already have.
        if sid in mav_chat.INTERRUPTED:
            mav_chat.INTERRUPTED.discard(sid)
            interrupted = True
            try:
                mav_core.http_json(f"{mav_core.OPENCODE_URL}/session/{sid}/abort", method="POST", timeout=8)
            except Exception:  # noqa: BLE001
                pass
            break

        # Wait for the engine to say something about this chat. With the event
        # stream that is instant; a slow safety poll still runs in case an event
        # is missed. Without it, poll with a backoff (0.15 s → 1.2 s).
        if ENGINE_EVENTS.connected:
            # Long safety poll once this chat's events are seen flowing; short
            # until then, in case this engine version names them differently.
            new_mark = ENGINE_EVENTS.wait(sid, mark, 1.5 if heard else 0.4)
            if new_mark != mark:
                heard = True
                time.sleep(0.08)  # let a burst of tokens land in one read
                new_mark = ENGINE_EVENTS.mark(sid)
            mark = new_mark
        else:
            time.sleep(pause)
            pause = min(pause * 1.4, 1.2)
        try:
            entries = mav_core.http_json(url, timeout=12) or []
        except Exception:
            continue
        if not entries:
            continue

        new_assistant = [
            e for e in entries
            if (e.get("info") or {}).get("id") not in before_ids
            and (e.get("info") or {}).get("role") == "assistant"
        ]
        if not new_assistant:
            continue
        accepted = True
        for e in new_assistant:
            turn_info[(e.get("info") or {}).get("id") or ""] = e.get("info") or {}

        # Visible answer only: "text" parts, never reasoning.
        for e in new_assistant:
            texts[(e.get("info") or {}).get("id") or ""] = mav_chat._part_text(e.get("parts") or [])
        text = "\n\n".join(t for t in texts.values() if t).strip()

        last = new_assistant[-1]
        linfo = last.get("info") or {}
        # Progress signature: message count, finish state, visible answer
        # length, and current tool state (running/completed).
        tool_sig = tuple(
            (p.get("id"), (p.get("state") or {}).get("status"))
            for e in new_assistant
            for p in (e.get("parts") or [])
            if p.get("type") == "tool"
        )
        sig = (len(texts), linfo.get("finish"), len(text), tool_sig)
        if sig != last_sig:
            last_sig = sig
            last_progress = time.time()
            pause = 0.15

        # Surface tool/MCP activity so the web app can show it live — with the
        # helper's name when the assistant delegates.
        for e in new_assistant:
            for part in (e.get("parts") or []):
                if part.get("type") != "tool":
                    continue
                key = part.get("callID") or part.get("id")
                if not key:
                    continue
                tool = _tool_info(part)
                sig_ = (tool["status"], len(tool.get("input", "")),
                        len(tool.get("output", "")), tool.get("end"))
                if tools_state.get(key) != sig_:
                    tools_state[key] = sig_
                    yield sse("tool", tool)

        if text != last_text:
            last_text = text
            delta = text[len(last_sent):] if text.startswith(last_sent) else text
            if not text.startswith(last_sent):
                yield sse("reset", {"text": text})
                delta = ""
            last_sent = text
            if delta:
                if t_first is None:
                    t_first = time.time()
                yield sse("delta", {"delta": delta})

        if linfo.get("error"):
            err = linfo.get("error") or {}
            engine_error = (
                (err.get("data") or {}).get("message") or err.get("name") or "engine error"
            )

        last_has_text = bool(mav_chat._part_text(last.get("parts") or []))
        finish = linfo.get("finish")
        # "tool-calls" = the model continues with tools; "None" = in progress.
        # Any other finish ("stop", "length", "error"…) is terminal.
        if finish is not None and finish != "tool-calls":
            finished_text = text or last_text
            break
        # Terminal error with no usable answer.
        if engine_error and finish is not None and not last_has_text:
            break

    if turn_info:
        source = "routine" if raw_session else "chat"
        mav_store.record_usage(source, list(turn_info.values()))
        metrics = mav_store.answer_metrics(t_sent, t_first, time.time(), list(turn_info.values()))
        mav_store.record_speed(source, metrics)
        yield sse("metrics", metrics)

    # Interrupted on purpose: whatever text was shown stays, but this is not a
    # finished exchange, so it is not remembered as the answer.
    if interrupted:
        yield sse("done", {"session": sid, "text": last_text, "agent": ag, "interrupted": True})
        return
    if not accepted and not finished_text:
        yield sse("error", {"message": "The request could not be started.", "session": sid})
        return
    if engine_error and not finished_text:
        yield sse("error", {"message": str(engine_error), "session": sid})
        return

    final = finished_text or last_text
    yield sse("done", {"session": sid, "text": final, "agent": ag})

    if not raw_session and final:
        # Cheap, local work right away; model calls (title, learned facts) go
        # through one queue that waits for the engine to be idle, so they never
        # slow down the answer the person is waiting for.
        mav_core.spawn(mav_chat.remember_exchange, prompt, final, sid, ag)
        mav_core.spawn(mav_chat.learn_interests, prompt)
        mav_chat.schedule_after_answer(sid, prompt, final, needs_title)


def ask(
    prompt: str,
    agent: str = "",
    sid: str = "",
    files: list | None = None,
    raw_session: bool = False,
    with_memory: bool = False,
    context: str = "",
) -> str:
    """Blocking version (routines, summaries, fallback)."""
    last = ""
    for chunk in stream_answer(prompt, sid, agent, files, raw_session=raw_session,
                               with_memory=with_memory, context=context):
        if chunk.startswith("event: reset"):
            try:
                last = json.loads(chunk.split("data: ", 1)[1]).get("text") or ""
            except Exception:
                pass
            continue
        if not chunk.startswith("event: delta"):
            if chunk.startswith("event: done"):
                try:
                    return json.loads(chunk.split("data: ", 1)[1]).get("text") or last
                except Exception:
                    return last
            if chunk.startswith("event: error"):
                try:
                    return f"Error: {json.loads(chunk.split('data: ', 1)[1]).get('message')}"
                except Exception:
                    return "Engine error."
            continue
        try:
            last += json.loads(chunk.split("data: ", 1)[1]).get("delta", "")
        except Exception:
            pass
    return last


__all__ = ['ENGINE_EVENTS', 'EngineEvents', 'MSG_WINDOW', 'RUNS', 'RUN_TTL', 'Run', 'TOOL_TEXT_MAX', '_clip', '_limit_ok', '_messages_url', '_parse_sse', '_run_cleanup', '_runs_lock', '_sse', '_tool_detail', '_tool_info', 'abort_session', 'ask', 'ensure_session', 'get_run', 'interrupt_session', 'request_interrupt', 'runs_view', 'start_run', 'stop_run', 'stream_answer']
