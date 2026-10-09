/* Mav web app — Sending and streaming answers, tool steps, queued messages.
   One of the classic scripts index.html loads in order (4/12); they share
   one global scope, like the single app.js they came from. */

/* ---------- Sending (SSE streaming) ---------- */
// Every running answer lives in here, keyed by session id — independent of
// which chat is on screen. Leaving a chat detaches the DOM but the answer keeps
// streaming server-side and we can reattach at any time. Several chats run at
// once; the send/stop controls always reflect the *active* one.
const streams = new Map(); // sid -> stream state
const queues = new Map(); // sid -> [{text, files}]

function streamOf(sid) {
  return sid ? streams.get(sid) : null;
}
function isStreaming(sid) {
  const s = streamOf(sid);
  return !!(s && !s.done);
}
function anyStreaming() {
  for (const s of streams.values()) if (!s.done) return true;
  return false;
}
function queueFor(sid) {
  return sid ? queues.get(sid) || [] : [];
}
function refreshStreamingUI() {
  const running = isStreaming(state.chat.id);
  state.streaming = running;
  document.body.classList.toggle("is-thinking", running);
  $("#sendBtn").hidden = running;
  $("#stopBtn").hidden = !running;
  renderQueue();
}

function renderQueue() {
  const bar = $("#queueBar");
  if (!bar) return;
  const q = queueFor(state.chat.id);
  if (!q.length) {
    bar.hidden = true;
    bar.innerHTML = "";
    return;
  }
  bar.hidden = false;
  bar.innerHTML =
    `<span class="queue-label">${I("arrow")} queued</span>` +
    q
      .map(
        (m, i) =>
          `<span class="queue-chip"><span class="queue-text">${esc(
            m.text.slice(0, 60),
          )}</span><button class="queue-x" data-qi="${i}" title="Remove">${I(
            "x",
          )}</button></span>`,
      )
      .join("") +
    `<button class="queue-send" id="queueInterrupt">${I(
      "arrow",
    )} Send now</button>`;
}

function enqueueMessage(sid, text, files) {
  const q = queues.get(sid) || [];
  q.push({ text, files: files || [] });
  queues.set(sid, q);
  renderQueue();
  toast("Queued — “Send now” to interrupt and send.");
}

// Kept for the offline demo only; live streaming uses the per-session map.
function setStreaming(on) {
  state.streaming = on;
  document.body.classList.toggle("is-thinking", on);
  $("#sendBtn").hidden = on;
  $("#stopBtn").hidden = !on;
}

// Ask the server to stop the active answer. The partial text is deliberately
// kept (server sends done{interrupted}) — nothing already written disappears.
function stopActive() {
  const sid = state.chat.id;
  if (!sid) return;
  if (LIVE) api.post("run/stop", { id: sid }).catch(() => {});
  queues.set(sid, []);
  renderQueue();
}

$("#stopBtn").addEventListener("click", () => {
  stopActive();
  toast("Stopped.");
});

/* Queue bar interactions (remove / interrupt-and-send) */
document.addEventListener("click", (e) => {
  const x = e.target.closest("[data-qi]");
  if (x) {
    const q = queueFor(state.chat.id);
    q.splice(Number(x.dataset.qi), 1);
    queues.set(state.chat.id, q);
    renderQueue();
    return;
  }
  if (e.target.closest("#queueInterrupt")) {
    const sid = state.chat.id;
    if (sid && LIVE) api.post("run/stop", { id: sid }).catch(() => {});
  }
});

/* ---------- Live tool activity (shown under the streaming answer) ---------- */
const TOOL_LABELS = {
  bash: "Running a command",
  read: "Reading a file",
  edit: "Editing a file",
  write: "Writing a file",
  grep: "Searching the code",
  glob: "Finding files",
  webfetch: "Reading a web page",
  websearch: "Searching the web",
  task: "Delegating to a helper",
};
function toolLabel(name, detail) {
  if (detail) {
    if (name === "task") return `${agentDisplay(detail)} is on it`;
    if (name === "webfetch") return `Reading ${detail}`;
    if (name === "websearch") return `Searching “${detail}”`;
  }
  if (TOOL_LABELS[name]) return TOOL_LABELS[name];
  const m = /^([a-z0-9]+)_(.+)$/.exec(name || "");
  if (m) return `${m[2].replace(/[_-]/g, " ")} · ${m[1]}`;
  return name || "tool";
}
/* Tool calls, one per row in the order they happened. Each row opens to
   show what was sent, what came back, when and how long it took. Rows are
   updated in place, so an open one stays open while the answer streams. */
function fmtSeconds(ms) {
  if (!(ms >= 0)) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;
  return `${Math.floor(ms / 60000)} min ${Math.round((ms % 60000) / 1000)} s`;
}
/* How long an answer took (shown with the message actions, 2.1). */
function speedHtml(mt) {
  if (!mt || mt.total_ms == null) return "";
  const parts = [];
  if (mt.ttft_ms != null) parts.push(`${fmtSeconds(mt.ttft_ms)} to first word`);
  parts.push(`${fmtSeconds(mt.total_ms)} in all`);
  if (mt.steps > 1) parts.push(`${mt.steps} steps`);
  if (mt.input_tokens) {
    const k = mt.input_tokens >= 1000 ? `${(mt.input_tokens / 1000).toFixed(1)}k` : mt.input_tokens;
    const cached = mt.cached_tokens ? `, ${Math.round((100 * mt.cached_tokens) / mt.input_tokens)} % cached` : "";
    parts.push(`${k} tokens read${cached}`);
  }
  return `<span class="msg-speed" title="How long this answer took">${esc(parts.join(" · "))}</span>`;
}
function fmtClockSec(ms) {
  return ms
    ? new Date(ms).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "";
}
const TOOL_STATUS = {
  pending: "Waiting",
  running: "Running",
  completed: "Done",
  error: "Failed",
};
function toolCommand(t) {
  // A shell command reads better as one line than inside JSON.
  try {
    const inp = JSON.parse(t.input || "");
    if (inp && typeof inp.command === "string") return `$ ${inp.command}`;
  } catch {}
  return "";
}
function toolStepBody(t) {
  const dur = t.start && t.end ? fmtSeconds(t.end - t.start) : "";
  const rows = [
    ["Tool", `<code>${esc(t.name)}</code>`],
    ["Status", esc(TOOL_STATUS[t.status] || t.status || "")],
    t.start ? ["Started", esc(fmtClockSec(t.start))] : null,
    dur ? ["Took", esc(dur)] : null,
    t.title ? ["Summary", esc(t.title)] : null,
  ].filter(Boolean);
  const cmd = toolCommand(t);
  const block = (label, text, cls = "") =>
    text
      ? `<div class="tool-sec"><div class="tool-sec-h">${label}</div><pre class="tool-pre ${cls}">${esc(text)}</pre></div>`
      : "";
  return `<dl class="tool-facts">${rows
    .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`)
    .join("")}</dl>
    ${cmd ? block("Command", cmd, "is-cmd") : ""}
    ${block("Input", t.input)}
    ${block("Output", t.output)}
    ${block("Error", t.error, "is-err")}
    ${!t.input && !t.output && !t.error ? `<p class="tool-empty">${t.status === "completed" ? "No details were reported for this step." : "Details appear as soon as the step reports them."}</p>` : ""}`;
}
function renderToolSteps(host, tools) {
  if (!host) return;
  if (!tools || !tools.length) {
    host.innerHTML = "";
    return;
  }
  const seen = new Set();
  tools.forEach((t, i) => {
    const id = String(t.id || t.name || i);
    seen.add(id);
    let row = [...host.children].find((c) => c.dataset.id === id);
    if (!row) {
      row = document.createElement("details");
      row.className = "tool-step";
      row.dataset.id = id;
      row.innerHTML = `<summary></summary><div class="tool-body"></div>`;
    }
    if (host.children[i] !== row) host.insertBefore(row, host.children[i] || null);
    const status = t.status || "running";
    const live = status === "running" || status === "pending";
    row.classList.toggle("is-run", live);
    row.classList.toggle("is-err", status === "error");
    row.classList.toggle("is-done", status === "completed");
    const took =
      t.start && t.end
        ? fmtSeconds(t.end - t.start)
        : live && t.start
          ? fmtSeconds(Date.now() - t.start)
          : "";
    const sig = JSON.stringify([t, took]);
    if (row._sig === sig) return;
    row._sig = sig;
    row.querySelector("summary").innerHTML = `<span class="tool-n">${i + 1}</span>
      <span class="tool-ico">${I(status === "error" ? "x" : status === "completed" ? "check" : "tool")}</span>
      <span class="tool-label">${esc(toolLabel(t.name, t.detail))}</span>
      <span class="tool-meta">${esc(took || TOOL_STATUS[status] || "")}</span>
      ${I("chevron").replace("data-i", 'class="tool-caret" data-i')}`;
    row.querySelector(".tool-body").innerHTML = toolStepBody(t);
  });
  [...host.children].forEach((c) => {
    if (!seen.has(c.dataset.id)) c.remove();
  });
}

async function send(raw, opts = {}) {
  const text = (raw || "").trim();
  if (text.startsWith("/") && runSlash(text)) return;
  if (state.pendingFiles.some((f) => f.loading))
    return toast("Wait for the upload to finish.");

  const hasFiles = opts.files ? opts.files.length : state.pendingFiles.length;
  if (!text && !hasFiles) return;
  if (state.view !== "chat") go("chat");

  // A message typed while THIS chat's answer runs joins the queue: it is sent
  // once the current answer settles, unless the user hits "Send now".
  const sidNow = state.chat.id;
  if (sidNow && isStreaming(sidNow) && !opts.force) {
    enqueueMessage(sidNow, text, opts.files || state.pendingFiles.slice());
    if (!opts.files) {
      state.pendingFiles = [];
      renderAttachments();
    }
    return;
  }

  const files = opts.files || state.pendingFiles.slice();
  state.pendingFiles = [];
  renderAttachments();

  const shown = text || files.map((f) => f.filename).join(", ");
  const userMsg = {
    role: "me",
    text:
      shown +
      (text && files.length
        ? `\n📎 ${files.map((f) => f.filename).join(", ")}`
        : ""),
    ts: Date.now(),
  };
  state.chat.messages.push(userMsg);
  appendMessage(userMsg);
  scrollToBottom(true);

  const agent = currentAgent();
  const routineDraft = detectRoutine(text);

  if (!LIVE) return demoReply(text, routineDraft);

  // A brand-new chat: create it first so it is ours (with its helper) before
  // the first word arrives.
  const wasNew = !state.chat.id;
  if (wasNew) {
    try {
      const s = await api.post("session/new", { agent });
      state.chat.id = s.id;
      state.chat.agent = agent;
      history.replaceState(null, "", `#chat/${s.id}`);
      updateChatActions();
    } catch (e) {
      return addError(
        "I couldn't start the chat — is the assistant running? See Settings → General → Advanced.",
      );
    }
  }
  const sid = state.chat.id;

  // Register the stream and hand it to the detached engine. send() returns
  // immediately; the answer keeps flowing even if this chat is left.
  const st = {
    sid,
    reply: { role: "mav", text: "", agent, ts: Date.now() },
    tools: [],
    files: files.length,
    thinking: null,
    el: null,
    raf: 0,
    seq: 0,
    done: false,
    error: null,
  };
  streams.set(sid, st);

  const qs = new URLSearchParams({
    prompt: text || "(see the attached files)",
    session: sid,
    agent,
  });
  if (files.length)
    qs.set(
      "files",
      JSON.stringify(
        files.map((f) => ({ url: f.url, mime: f.mime, filename: f.filename })),
      ),
    );

  showWaiting(st);
  attachStream(st, qs, { wasNew, prompt: text, routineDraft });
}

/* Before the first word: the reply is already on screen, with its helper,
   and says what is going on (and for how long), so a slow start never looks
   like a crash. */
const WAIT_LINES = [
  [0, "Thinking"],
  [8, "Still thinking"],
  [25, "Working on it, this one takes a moment"],
  [90, "Taking longer than usual"],
];
function waitLabel(st, s) {
  let label = st.files ? "Reading your file" : WAIT_LINES[0][1];
  for (const [at, l] of WAIT_LINES) if (at && s >= at) label = l;
  if (st.tools.some((t) => t.status === "running" || t.status === "pending"))
    label = s >= 90 ? "Taking longer than usual" : "Working";
  return label;
}
function paintWaiting(st, bubble) {
  const s = Math.floor((Date.now() - st.reply.ts) / 1000);
  let row = bubble.querySelector(".thinking-row.is-wait");
  if (!row) {
    bubble.innerHTML = `<div class="thinking-row is-wait">${dots()}<span class="wait-label"></span><span class="wait-time"></span></div>`;
    row = bubble.firstElementChild;
  }
  // Updated in place: the animations keep running smoothly.
  const label = `${waitLabel(st, s)}…`;
  const time = s >= 3 ? fmtSeconds(s * 1000) : "";
  const lab = row.querySelector(".wait-label");
  const tim = row.querySelector(".wait-time");
  if (lab.textContent !== label) lab.textContent = label;
  if (tim.textContent !== time) tim.textContent = time;
}
function showWaiting(st) {
  refreshStreamingUI();
  paintStream(st);
  clearInterval(st.tick);
  st.tick = setInterval(() => {
    if (st.done || st.reply.text) return clearInterval(st.tick);
    paintStream(st);
  }, 1000);
}

/* Render one buffered event into the stream's reply + DOM (if on screen). */
function paintStream(st) {
  if (st.raf) return;
  st.raf = requestAnimationFrame(() => {
    st.raf = 0;
    if (state.chat.id !== st.sid) return; // shown elsewhere; buffer keeps it
    const live = !!st.el && document.body.contains(st.el);
    if (!live) {
      st.thinking && st.thinking.remove();
      st.thinking = null;
      st.el = appendMessage(st.reply, { last: true, streaming: !st.done });
    }
    if (st.el) {
      const stick = nearBottom();
      const bubble = st.el.querySelector(".bubble");
      const waiting = !st.reply.text && !st.done;
      st.el.classList.toggle("is-waiting", waiting);
      if (waiting) paintWaiting(st, bubble);
      else bubble.innerHTML = mdToHtml(st.reply.text || "");
      hydrateCharts(st.el);
      renderToolSteps(st.el.querySelector(".msg-tools"), st.tools);
      if (stick) scrollToBottom(true);
    }
  });
}

function applyEvent(st, ev, d) {
  if (ev === "start") {
    if (d.recalled) st.reply.recalled = d.recalled;
    if (d.agent) {
      st.reply.agent = d.agent;
      st.agent = d.agent;
    }
  } else if (ev === "delta") {
    st.reply.text += d.delta || "";
    paintStream(st);
  } else if (ev === "reset") {
    // The answer was rewritten (not just extended): replace, never append.
    st.reply.text = d.text || "";
    paintStream(st);
  } else if (ev === "tool") {
    const key = d.id || d.name;
    const i = st.tools.findIndex((t) => (t.id || t.name) === key);
    const entry = {
      ...(i >= 0 ? st.tools[i] : {}),
      ...d,
      id: key,
      detail: d.detail || "",
      status: d.status || "running",
    };
    if (i >= 0) st.tools[i] = entry;
    else st.tools.push(entry);
    st.reply.tools = st.tools; // kept on the message once the answer ends
    paintStream(st);
  } else if (ev === "metrics") {
    st.reply.metrics = d;
    const acts = st.el && st.el.querySelector(".msg-actions");
    if (acts && !acts.querySelector(".msg-speed")) acts.insertAdjacentHTML("beforeend", speedHtml(d));
  } else if (ev === "done") {
    if (!st.reply.text && d.text) st.reply.text = d.text;
    st.reply.interrupted = !!d.interrupted;
    st.done = true;
  } else if (ev === "error") {
    st.error = d.message || "Something went wrong.";
    st.done = true;
  }
}

/* Consume an SSE response into `st` until it ends (or the tab leaves). */
async function consume(st, url, ctl) {
  const resp = await fetch(url, {
    headers: { Accept: "text/event-stream" },
    signal: ctl && ctl.signal,
  });
  if (!resp.ok || !resp.body) throw new Error("stream unavailable");
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    let chunk;
    try {
      chunk = await reader.read();
    } catch (_) {
      break; // detached or network hiccup: the server run continues
    }
    if (chunk.done) break;
    buf += decoder.decode(chunk.value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let ev = "";
      const data = [];
      block.split("\n").forEach((l) => {
        if (l.startsWith("event:")) ev = l.slice(6).trim();
        else if (l.startsWith("data:")) data.push(l.slice(5).trim());
      });
      // Keep-alive comments are not events: counting them would shift the
      // resume cursor and replay (= duplicate) part of the answer.
      if (!ev) continue;
      let d = {};
      try {
        d = JSON.parse(data.join("\n") || "{}");
      } catch (_) {}
      st.seq += 1;
      applyEvent(st, ev, d);
      if (st.done) break;
    }
    if (st.done) break;
  }
  try {
    reader.cancel();
  } catch (_) {}
}

/* Run one answer to completion and settle its stream. */
async function attachStream(st, qs, opts = {}) {
  const url = `/api/stream?${qs.toString()}`;
  const ctl = new AbortController();
  st.ctl = ctl;
  try {
    await consume(st, url, ctl);
  } catch (e) {
    if (e && e.name === "AbortError") {
      // We detached on purpose: the server run continues.
      st.ctl = null;
      return;
    }
  }
  st.ctl = null;
  // The connection dropped mid-answer (phone asleep, Wi-Fi switch): the run
  // goes on server-side, so pick it up where we left off rather than settle
  // a half answer — that half answer plus the full one was the double reply.
  if (!st.done) await resumeStream(st);
  finalizeStream(st, opts);
}

async function resumeStream(st) {
  for (const wait of [500, 1500, 4000, 8000]) {
    if (st.done) return;
    await new Promise((r) => setTimeout(r, wait));
    try {
      const url = `/api/stream?session=${encodeURIComponent(st.sid)}&from=${st.seq}`;
      await consume(st, url, null);
    } catch (_) {
      // run gone or server unreachable: try again, then give up below
    }
  }
  if (!st.done) {
    st.done = true;
    st.resync = true; // let the thread reload from the server
  }
}

// On returning to the tab (phone woke up, other app closed), make sure every
// chat that is working server-side is reflected here again.
async function syncRunning() {
  if (!LIVE) return;
  let runs = [];
  try {
    runs = (await api.get("runs")).runs || [];
  } catch (_) {
    return;
  }
  const active = new Set(
    runs.filter((r) => r.status === "running").map((r) => r.session),
  );
  // A run we thought was live but the server already finished: settle it.
  for (const [sid, st] of [...streams]) {
    if (!st.done && !active.has(sid) && sid !== state.chat.id) {
      st.done = true;
      streams.delete(sid);
    }
  }
  const cur = state.chat.id;
  if (cur && active.has(cur) && !isStreaming(cur)) reattach(cur);
  refreshStreamingUI();
  renderConvList();
}
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) syncRunning();
});
window.addEventListener("online", syncRunning);

/* Reattach to a run already in progress on the server (tab came back). */
async function reattach(sid) {
  if (!LIVE || isStreaming(sid)) return;
  let runs = [];
  try {
    runs = (await api.get("runs")).runs || [];
  } catch (_) {
    return;
  }
  const r = runs.find((x) => x.session === sid && x.status === "running");
  if (!r) return;
  const st = {
    sid,
    reply: { role: "mav", text: "", agent: r.agent || "", ts: Date.now() },
    tools: [],
    thinking: null,
    el: null,
    raf: 0,
    seq: 0,
    done: false,
    error: null,
  };
  streams.set(sid, st);
  showWaiting(st);
  const url = `/api/stream?session=${encodeURIComponent(sid)}&from=0`;
  try {
    await consume(st, url, null);
  } catch (_) {
    // Could not reattach (run gone): drop it silently — the thread reloads.
    streams.delete(sid);
    refreshStreamingUI();
    return;
  }
  if (!st.done) await resumeStream(st);
  finalizeStream(st, {});
}

/* The thread minus the answer of the turn in progress (after the last "me"). */
function dropOpenTurn(msgs) {
  const out = msgs.slice();
  while (out.length && out[out.length - 1].role === "mav") out.pop();
  return out;
}

async function reloadThread(sid) {
  try {
    const s = await api.get(`session?id=${encodeURIComponent(sid)}`);
    if (state.chat.id !== sid) return;
    state.chat.messages = s.messages || [];
    renderThread();
  } catch (_) {}
}

async function finalizeStream(st, opts = {}) {
  const { wasNew = false, prompt = "", routineDraft = null } = opts;
  st.done = true;
  if (st.raf) cancelAnimationFrame(st.raf);
  clearInterval(st.tick);
  st.raf = 0;
  if (st.thinking) st.thinking.remove();
  streams.delete(st.sid);
  const onScreen = state.chat.id === st.sid;
  if (onScreen && st.el) st.el.remove();
  const reply = st.reply;
  if (onScreen && st.resync) {
    // We lost the stream for good: the server has the real answer.
    reloadThread(st.sid);
  } else if (st.error && !reply.text) {
    if (onScreen) addError(st.error);
  } else {
    if (!reply.text) reply.text = "_(no answer)_";
    // Push into the thread only if this chat is on screen; otherwise the thread
    // is reloaded from the server next time it is opened (no duplicate). One
    // turn = one answer: anything already shown for this turn is replaced.
    if (onScreen) {
      const msgs = state.chat.messages;
      const trimmed = dropOpenTurn(msgs);
      state.chat.messages = trimmed;
      if (trimmed.length !== msgs.length) renderThread();
      state.chat.messages.push(reply);
      st.replyEl = appendMessage(reply, { last: true, meta: true });
      if (S.speak) speak(reply.text);
      if (routineDraft) offerRoutine(routineDraft);
    }
  }
  refreshStreamingUI();
  renderConvList();
  await loadConvs();
  if (wasNew && !st.error) watchForTitle(st.sid);

  // A queued message takes over: either after an interrupt, or simply the next
  // queued message once this answer has settled.
  const q = queueFor(st.sid);
  const next = q.shift();
  queues.set(st.sid, q);
  renderQueue();
  if (next) sendQueued(st.sid, next);
  if (!st.error && prompt && ABOUT_ME_RE.test(prompt))
    watchForMemory(st.sid, st.replyEl);
  if (document.hidden && !st.error && reply.text)
    notifyLocal(agentDisplay(reply.agent), reply.text);
}

/* Send a queued message as its own detached run, even if its chat is not on
   screen. The message is stored server-side by starting the prompt directly. */
function sendQueued(sid, item) {
  if (state.chat.id === sid && state.view === "chat")
    return send(item.text, { files: item.files, force: true });
  const st = {
    sid,
    reply: { role: "mav", text: "", agent: "", ts: Date.now() },
    tools: [],
    thinking: null,
    el: null,
    raf: 0,
    seq: 0,
    done: false,
    error: null,
  };
  streams.set(sid, st);
  const agent = (state.convs.find((c) => c.id === sid) || {}).agent || "";
  const qs = new URLSearchParams({
    prompt: item.text || "(see the attached files)",
    session: sid,
    agent,
  });
  if (item.files && item.files.length)
    qs.set(
      "files",
      JSON.stringify(
        item.files.map((f) => ({
          url: f.url,
          mime: f.mime,
          filename: f.filename,
        })),
      ),
    );
  attachStream(st, qs, { prompt: item.text });
}

function addError(msg) {
  appendMessage(
    { role: "mav", text: msg, agent: currentAgent(), error: true },
    { last: true },
  );
}

/* Mav learns facts about you in the background (when you talk about
   yourself): show "Memory updated" under the answer when it does. */
const ABOUT_ME_RE =
  /\b(i|i'm|im|i've|my|me|we|our|je|j'|moi|mon|ma|mes|nous|notre)\b/i;
// One watcher at a time: a newer answer takes over, so a fact learned from an
// earlier message is never announced twice (or under the wrong answer).
let memoryWatch = 0;
async function watchForMemory(sid, bubble) {
  const base = state.status && Number(state.status.facts);
  if (!Number.isFinite(base)) return;
  const token = ++memoryWatch;
  for (const wait of [4000, 8000, 15000, 30000]) {
    await new Promise((r) => setTimeout(r, wait));
    if (token !== memoryWatch) return;
    let st;
    try {
      st = await api.get("status");
    } catch (_) {
      return;
    }
    renderStatus(st);
    if (Number(st.facts) > base) {
      if (state.chat.id !== sid) return;
      const last =
        bubble && document.body.contains(bubble)
          ? bubble
          : [...$$(".msg.mav")].pop();
      if (!last || last.querySelector(".memory-updated")) return;
      const note = document.createElement("button");
      note.className = "recall-note memory-updated";
      note.innerHTML = `${I("brain")} Memory updated`;
      note.title =
        "Mav learned something about you — manage it on the Memory page";
      note.addEventListener("click", () => go("memory"));
      last
        .querySelector(".body")
        .insertBefore(note, last.querySelector(".msg-actions"));
      return;
    }
  }
}

/* The title is generated by the server after the first answer: poll briefly. */
function watchForTitle(sid) {
  const quick = state.chat.title;
  $("#chatTitle").classList.add("is-generating");
  let n = 0;
  const tick = async () => {
    n++;
    await loadConvs();
    const c = state.convs.find((x) => x.id === sid);
    if ((c && c.title !== quick) || n >= 6) {
      $("#chatTitle").classList.remove("is-generating");
      return;
    }
    setTimeout(tick, 2500);
  };
  setTimeout(tick, 2000);
}

function demoReply(text, draft) {
  const a = currentAgent();
  const ans = demoAnswerFor(text);
  const start = Date.now();
  const reply = { role: "mav", agent: a, ts: start, text: "", tools: [] };
  setStreaming(true);
  const el = appendMessage(reply, { last: true, meta: true, streaming: true });
  const host = el.querySelector(".msg-tools");
  const steps = ans.tools.map((t, i) => ({ ...t, start: start + i * 500, end: start + i * 500 + Math.min(t.end - t.start, 900) }));
  steps.forEach((t, i) => {
    setTimeout(() => {
      reply.tools.push({ ...t, status: "running", end: undefined, output: "" });
      renderToolSteps(host, reply.tools);
    }, 250 + i * 500);
    setTimeout(() => {
      reply.tools[i] = t;
      renderToolSteps(host, reply.tools);
    }, 650 + i * 500);
  });
  const words = ans.text.split(/(\s+)/);
  const t0 = 400 + steps.length * 500;
  let n = 0;
  const tick = () => {
    n = Math.min(words.length, n + 6);
    reply.text = words.slice(0, n).join("");
    el.querySelector(".bubble").innerHTML = mdToHtml(reply.text);
    if (nearBottom()) scrollToBottom(true);
    if (n < words.length) return setTimeout(tick, 30);
    hydrateCharts(el);
    el.classList.remove("is-streaming");
    state.chat.messages.push(reply);
    if (!state.chat.title)
      setChatTitle(text.split(/\s+/).slice(0, 4).join(" ") || "Demo chat");
    setStreaming(false);
    if (draft) offerRoutine(draft);
  };
  setTimeout(tick, t0);
}
