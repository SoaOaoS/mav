/* Mav web app — The chat: messages, actions, briefing, composer, commands, attachments.
   One of the classic scripts index.html loads in order (3/12); they share
   one global scope, like the single app.js they came from. */

/* ================================================================
   6. Chat
   ================================================================ */
const messagesEl = $("#messages");

function setChatTitle(t) {
  state.chat.title = t || "";
  $("#chatTitle").textContent = t || "New chat";
  $("#chatTitle").classList.remove("is-generating");
  if (state.view === "chat") $("#topbarTitle").textContent = t || "Mav";
  document.title = t ? `${t} · Mav` : "Mav";
}

function newChat(agent, { push = true } = {}) {
  // Never abort a running answer — just move away from it.
  if (state.chat.id) detachStream(state.chat.id);
  if (agent) {
    state.preferredAgent = agent;
    store.set("mav-agent", agent);
  }
  state.chat = {
    id: null,
    title: "",
    agent: agent || state.preferredAgent || "",
    pinned: false,
    routine: false,
    messages: [],
  };
  setChatTitle("");
  updateChatActions();
  renderAgentPills();
  renderThread();
  refreshStreamingUI();
  go("chat", null, { push });
  setTimeout(() => $("#chatInput").focus(), 50);
}

// Detach the stream that belongs to the chat we are leaving: keep it in the
// map (it keeps flowing), but drop its DOM so another chat can render.
function detachStream(sid) {
  const st = streamOf(sid);
  if (!st) return;
  if (st.raf) cancelAnimationFrame(st.raf);
  st.raf = 0;
  if (st.thinking) st.thinking.remove();
  st.thinking = null;
  st.el = null; // the bubble is recreated on reattach / when we come back
}

async function openChat(id, { push = true } = {}) {
  if (!id) return newChat();
  if (state.chat.id && state.chat.id !== id) detachStream(state.chat.id);
  const c = state.convs.find((x) => x.id === id);
  state.chat = {
    id,
    title: c ? c.title : "",
    agent: c ? c.agent : "",
    pinned: !!(c && c.pinned),
    routine: !!(c && c.routine),
    messages: [],
  };
  setChatTitle(state.chat.title);
  renderAgentPills();
  updateChatActions();
  setEmpty(false);
  go("chat", null, { push });
  if (!LIVE) {
    state.chat.messages = (DEMO_CHATS.threads[id] || []).map((m) => ({ ...m }));
    return renderThread();
  }
  messagesEl.innerHTML = `<div class="thread"><div class="thinking-row">${dots()} Loading…</div></div>`;
  try {
    const s = await api.get(`session?id=${encodeURIComponent(id)}`);
    if (state.chat.id !== id) return;
    state.chat.title = s.title || state.chat.title;
    state.chat.agent = s.agent || state.chat.agent;
    const st0 = streamOf(id);
    // While an answer runs, its text belongs to the live bubble only.
    state.chat.messages =
      s.running || (st0 && !st0.done)
        ? dropOpenTurn(s.messages || [])
        : s.messages || [];
    setChatTitle(state.chat.title);
    renderAgentPills();
    renderThread();
    // If an answer is still running for this chat (we came back to it), show it
    // again exactly where it is — or reattach if the tab had detached earlier.
    const st = streamOf(id);
    if (st && !st.done) {
      st.el = null;
      paintStream(st);
      hydrateIcons();
    } else {
      reattach(id);
    }
  } catch (_) {
    renderThread();
    toast("Could not load this chat.", { error: true });
  }
  refreshStreamingUI();
}

function updateChatActions() {
  $("#chatActions").hidden = !state.chat.id;
  closeChatMenu();
  $("#pinBtn").classList.toggle("is-on", !!state.chat.pinned);
  $("#pinBtn span").textContent = state.chat.pinned ? "Unpin" : "Pin";
}

/* The chat's options (pin, summarise, download, delete) live in one menu. */
function closeChatMenu() {
  $("#chatMenu").hidden = true;
  $("#chatMenuBtn").setAttribute("aria-expanded", "false");
}
$("#chatMenuBtn").addEventListener("click", () => {
  const open = $("#chatMenu").hidden;
  $("#chatMenu").hidden = !open;
  $("#chatMenuBtn").setAttribute("aria-expanded", String(open));
});
$("#chatMenu").addEventListener("click", (e) => {
  if (e.target.closest("[role=menuitem]")) closeChatMenu();
});
document.addEventListener("mousedown", (e) => {
  if (!$("#chatMenu").hidden && !e.target.closest("#chatActions")) closeChatMenu();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#chatMenu").hidden) closeChatMenu();
});

function setEmpty(on) {
  $("#chat").classList.toggle("is-empty", on);
}
const dots = () =>
  `<span class="thinking-dots"><span></span><span></span><span></span></span>`;

/* Does this assistant message deserve a "Name · time" header? Yes only when it
   directly follows a user message (a fresh turn), when it is proactive
   (routine / interest / alert chats), or when it opens the thread. */
function threadMessageMeta(m, i, msgs, proactive) {
  if (m.role !== "mav") return false;
  if (proactive || i === 0) return true;
  const prev = msgs[i - 1];
  return !!prev && prev.role === "me";
}

function renderThread() {
  const msgs = state.chat.messages;
  if (!msgs.length) {
    setEmpty(true);
    const name = (state.status && state.status.user_name) || "";
    messagesEl.innerHTML = `<div class="welcome">
      <h1>${esc(greet())}${name ? ", " + esc(name) : ""}</h1>
    </div>`;
    refreshInbox();
    return;
  }
  setEmpty(false);
  messagesEl.innerHTML = `<div class="thread" id="thread"></div>`;
  const proactive = /^(Routine|Intérêt|Alerte) ·/.test(state.chat.title || "");
  let lastAgent = null;
  let lastDay = "";
  msgs.forEach((m, i) => {
    const day = m.ts ? dayStamp(m.ts) : "";
    if (day && day !== lastDay && i > 0) {
      appendDivider(esc(day), null, false);
      lastDay = day;
    } else if (day) {
      lastDay = day;
    }
    if (m.role === "mav") {
      const ag = m.agent || "";
      if (lastAgent && ag && ag !== lastAgent)
        appendDivider(
          `Now talking to <strong>${esc(agentDisplay(ag))}</strong>`,
          ag,
          false,
        );
      if (ag) lastAgent = ag;
    }
    appendMessage(m, {
      last: i === msgs.length - 1,
      scroll: false,
      meta: threadMessageMeta(m, i, msgs, proactive),
    });
  });
  scrollToBottom(true);
}
function dayStamp(ts) {
  const d = new Date(toMs(ts));
  const now = new Date();
  const same = (a, b) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();
  if (same(d, now)) return "Today";
  const y = new Date(now);
  y.setDate(now.getDate() - 1);
  if (same(d, y)) return "Yesterday";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}
function greet() {
  const h = new Date().getHours();
  return h < 5
    ? "Good night"
    : h < 12
      ? "Good morning"
      : h < 18
        ? "Good afternoon"
        : "Good evening";
}

function threadEl() {
  let t = $("#thread");
  if (!t) {
    setEmpty(false);
    messagesEl.innerHTML = `<div class="thread" id="thread"></div>`;
    t = $("#thread");
  }
  return t;
}

function appendMessage(
  m,
  { last = false, scroll = true, streaming = false, meta = null } = {},
) {
  const t = threadEl();
  t.querySelectorAll(".msg.is-last").forEach((x) =>
    x.classList.remove("is-last"),
  );
  const el = document.createElement("div");
  if (m.role === "me") {
    el.className = "msg me";
    el.innerHTML = `<div class="bubble"></div>`;
    el.querySelector(".bubble").textContent = m.text;
  } else {
    const ag = m.agent || currentAgent();
    el.className = `msg mav ${last ? "is-last" : ""} ${m.error ? "is-error" : ""} ${streaming ? "is-streaming" : ""} ${m.interrupted ? "is-interrupted" : ""}`;
    el.style.setProperty("--agent", agentColor(ag));
    // Name + time are shown only when they carry meaning: on the turn right
    // after yours, on a proactive message, or on the first one. Otherwise a
    // reloaded thread stays clean instead of stamping every bubble.
    const showMeta = meta === null ? true : meta;
    el.innerHTML = `${agentAvatar(ag)}
      <div class="body">
        ${showMeta ? `<div class="msg-meta"><span class="who">${esc(agentDisplay(ag))}</span>${m.ts ? `<span>${esc(fmtClock(m.ts))}</span>` : ""}</div>` : ""}
        <div class="msg-tools"></div>
        <div class="bubble"></div>
        ${m.recalled ? `<div class="recall-note">${I("brain")} Used ${m.recalled} thing${m.recalled > 1 ? "s" : ""} from memory</div>` : ""}
        ${m.interrupted ? `<div class="recall-note interrupted-note">${I("square")} Stopped by you — the rest was kept.</div>` : ""}
        <div class="msg-actions">
          <button class="icon-btn" data-act="copy" title="Copy">${I("copy")}</button>
          <button class="icon-btn" data-act="download" title="Download as Markdown">${I("download")}</button>
          <button class="icon-btn" data-act="retry" title="Regenerate">${I("refresh")}</button>
          <button class="icon-btn" data-act="speak" title="Read aloud">${I("volume")}</button>
          ${speedHtml(m.metrics)}
        </div>
      </div>`;
    el.querySelector(".bubble").innerHTML = mdToHtml(m.text || "");
    hydrateCharts(el);
    if (m.tools && m.tools.length)
      renderToolSteps(el.querySelector(".msg-tools"), m.tools);
  }
  el._msg = m;
  t.appendChild(el);
  if (scroll) scrollToBottom();
  return el;
}

function appendDivider(html, agent, scroll = true) {
  const d = document.createElement("div");
  d.className = "divider";
  d.innerHTML = `<span>${agent ? agentAvatar(agent) + " " : ""}${html}</span>`;
  threadEl().appendChild(d);
  if (scroll) scrollToBottom();
}

function nearBottom() {
  return (
    messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight <
    140
  );
}
function scrollToBottom(force = false) {
  if (!(force || nearBottom())) return;
  // At once: a smooth scroll is still on its way when the answer grows or a
  // chart is drawn, and stops short of the bottom.
  messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: "instant" });
}
// What is drawn after the thread (images, charts) makes it taller: a reader
// who was at the bottom stays there.
let atBottom = true;
messagesEl.addEventListener("scroll", () => (atBottom = nearBottom()), { passive: true });
messagesEl.addEventListener("load", () => atBottom && scrollToBottom(true), true);
new ResizeObserver(() => atBottom && scrollToBottom(true)).observe(messagesEl);

/* Message actions + code copy */
messagesEl.addEventListener("click", async (e) => {
  const copy = e.target.closest(".code-copy");
  if (copy) {
    await copyText(
      copy.closest(".code-block").querySelector("code").textContent,
    );
    copy.innerHTML = `${I("check")} Copied`;
    setTimeout(() => (copy.innerHTML = `${I("copy")} Copy`), 1500);
    return;
  }
  const refresh = e.target.closest(".chart-refresh");
  if (refresh) {
    const fig = refresh.closest(".md-chart");
    if (fig) {
      fig.removeAttribute("data-loaded");
      fig.querySelector(".md-chart-plot").innerHTML =
        '<div class="md-chart-load">Loading chart…</div>';
      fig.dataset.loaded = "1";
      loadChart(fig);
    }
    return;
  }
  const act = e.target.closest("[data-act]");
  if (act) {
    const msg = act.closest(".msg")._msg;
    if (act.dataset.act === "copy") {
      await copyText(msg.text);
      toast("Copied.");
    } else if (act.dataset.act === "download") {
      downloadMessage(msg);
    } else if (act.dataset.act === "retry") {
      const lastUser = [...state.chat.messages]
        .reverse()
        .find((m) => m.role === "me");
      if (lastUser) send(lastUser.text);
    } else if (act.dataset.act === "speak") speak(msg.text, true);
    return;
  }
  const img = e.target.closest("img.md-img");
  if (img) openLightbox(img.src);
});

/* Suggestions on the new-chat screen */
$("#suggestions").addEventListener("click", (e) => {
  if (e.target.closest("[data-brief]")) return briefMe();
  const b = e.target.closest("[data-prompt], [data-fill]");
  if (!b) return;
  if (b.dataset.prompt) return send(b.dataset.prompt);
  const ta = $("#chatInput");
  ta.value = b.dataset.fill;
  autoGrow(ta);
  ta.focus();
});

/* The language of ready-made content (routine templates): the browser's. */
function uiLang() {
  return (navigator.language || "en").slice(0, 2).toLowerCase();
}

/* ---------- Daily briefing ----------
   "Brief me" runs the briefing routine now and opens its chat, where the
   answer streams in (the run is live server-side, openChat reattaches). */
async function briefMe() {
  if (!needLive()) return;
  try {
    const r = await api.post("briefing/run");
    if (!r.ok) throw new Error(r.error || "Could not start the briefing.");
    await loadConvs();
    openChat(r.session);
  } catch (ex) {
    toast(ex.message, { error: true });
  }
}
async function loadBriefing() {
  if (!LIVE) return;
  try {
    const b = await api.get("briefing");
    $("#briefingRow").hidden = !b.available;
    $("#briefingToggle").setAttribute("aria-checked", String(!!b.enabled));
    $("#briefingTime").value = b.time || "07:30";
  } catch (_) {}
}
async function saveBriefing() {
  if (!needLive()) return;
  const enabled = $("#briefingToggle").getAttribute("aria-checked") === "true";
  try {
    const r = await api.post("briefing", {
      enabled,
      time: $("#briefingTime").value,
    });
    if (!r.ok) throw new Error(r.error);
    toast(enabled ? `Briefing every day at ${r.time}.` : "Daily briefing off.");
    loadRoutines();
  } catch (ex) {
    toast(ex.message || "Could not save.", { error: true });
  }
}
$("#briefingToggle").addEventListener("click", () => {
  const on = $("#briefingToggle").getAttribute("aria-checked") !== "true";
  $("#briefingToggle").setAttribute("aria-checked", String(on));
  saveBriefing();
});
$("#briefingTime").addEventListener("change", () => {
  if ($("#briefingToggle").getAttribute("aria-checked") === "true") saveBriefing();
});

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (_) {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}

/* Save any answer as a local Markdown file (works standalone, no server). */
function safeFileName(s) {
  return (
    String(s || "mav")
      .replace(/[^\w\-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "mav"
  );
}
function downloadMessage(msg) {
  const text = msg && msg.text ? msg.text : "";
  if (!text) return;
  const stamp = new Date((msg && msg.ts) || Date.now())
    .toISOString()
    .slice(0, 10);
  const base = safeFileName((String(text).split("\n")[0] || "").slice(0, 50));
  const blob = new Blob([text + "\n"], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${stamp}-${base}.md`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

function openLightbox(src) {
  const lb = document.createElement("div");
  lb.className = "lightbox";
  lb.innerHTML = `<img alt="" src="${esc(src)}">`;
  lb.addEventListener("click", () => lb.remove());
  document.body.appendChild(lb);
}

/* Inline rename */
const titleEl = $("#chatTitle");
function startRename() {
  if (!state.chat.id || !LIVE) return;
  titleEl.contentEditable = "true";
  titleEl.focus();
  document.getSelection().selectAllChildren(titleEl);
}
async function commitRename(save) {
  if (titleEl.contentEditable !== "true") return;
  titleEl.contentEditable = "false";
  const name = titleEl.textContent.trim();
  if (!save || !name || name === state.chat.title)
    return setChatTitle(state.chat.title);
  try {
    await api.post("session/rename", { id: state.chat.id, title: name });
    setChatTitle(name);
    loadConvs();
  } catch (_) {
    setChatTitle(state.chat.title);
    toast("Rename failed.", { error: true });
  }
}
titleEl.addEventListener("click", startRename);
titleEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    commitRename(true);
  } else if (e.key === "Escape") {
    e.preventDefault();
    commitRename(false);
  } else if (
    titleEl.contentEditable !== "true" &&
    (e.key === "F2" || e.key === " ")
  ) {
    e.preventDefault();
    startRename();
  }
});
titleEl.addEventListener("blur", () => commitRename(true));

/* Header actions */
$("#pinBtn").addEventListener("click", async () => {
  if (!state.chat.id || !needLive()) return;
  state.chat.pinned = !state.chat.pinned;
  updateChatActions();
  await api
    .post("session/pin", { id: state.chat.id, pinned: state.chat.pinned })
    .catch(() => {});
  loadConvs();
});
$("#exportBtn").addEventListener("click", () => {
  if (!state.chat.id || !needLive()) return;
  window.location.href = `/api/session/export?id=${encodeURIComponent(state.chat.id)}`;
});
$("#summaryBtn").addEventListener("click", async () => {
  if (!state.chat.id || !needLive()) return;
  const done = toast("Summarising…", { duration: 60000 });
  try {
    const r = await api.post("session/summary", { id: state.chat.id });
    done();
    modal.open({
      title: "Summary",
      body: `<div class="bubble">${mdToHtml(r.summary || "…")}</div>`,
      actions: [
        { label: "Copy", run: () => copyText(r.summary || "") },
        { label: "Close", kind: "btn-primary" },
      ],
    });
  } catch (_) {
    done();
    toast("Summary failed.", { error: true });
  }
});
$("#deleteChatBtn").addEventListener(
  "click",
  () => state.chat.id && deleteChat(state.chat.id),
);

async function deleteChat(id) {
  if (!needLive()) return;
  const c = state.convs.find((x) => x.id === id);
  const ok = await confirmDialog(
    "Delete this chat?",
    `“${c ? c.title : "This chat"}” will be deleted for good.`,
    "Delete",
  );
  if (!ok) return;
  try {
    await api.post("session/delete", { id });
    state.convs = state.convs.filter((x) => x.id !== id);
    if (state.chat.id === id) newChat();
    renderConvList();
    toast("Chat deleted.");
  } catch (_) {
    toast("Delete failed.", { error: true });
  }
}

/* ---------- Composer ---------- */
function autoGrow(ta) {
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, window.innerHeight * 0.4) + "px";
}
const chatInput = $("#chatInput");
chatInput.addEventListener("input", () => autoGrow(chatInput));
chatInput.addEventListener("keydown", (e) => {
  if (!$("#slashMenu").hidden && slashKey(e)) return;
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    $("#chatForm").requestSubmit();
  }
});
$("#chatForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = chatInput.value;
  if (!text.trim() && !state.pendingFiles.length) return;
  chatInput.value = "";
  autoGrow(chatInput);
  hideSlash();
  // send() runs slash commands immediately and queues a normal message while
  // an answer is streaming (interrupt with "Send now").
  send(text);
});

/* ---------- Slash commands ---------- */
const SLASH = [
  { cmd: "/new", desc: "Start a new chat", run: () => newChat() },
  {
    cmd: "/helper",
    arg: "<name>",
    desc: "Switch who you talk to",
    run: (a) => {
      const name = a.trim().toLowerCase();
      if (!name)
        return openAgentMenu($("#composerAgent"), currentAgent(), (x) =>
          switchAgent(x),
        );
      if (state.agents.length && !state.agents.includes(name))
        return toast(`Unknown helper: ${name}`, { error: true });
      switchAgent(name);
    },
  },
  {
    cmd: "/remember",
    arg: "<fact>",
    desc: "Save something about you to memory",
    run: async (a) => {
      if (!a.trim()) return toast("Usage: /remember <something about you>");
      if (!needLive()) return;
      try {
        await api.post("memory/fact/add", { fact: a.trim() });
        toast("Got it — I'll remember that.", {
          action: { label: "View memory", run: () => go("memory") },
        });
      } catch (e) {
        toast(e.message, { error: true });
      }
    },
  },
  {
    cmd: "/routine",
    arg: "<what, when>",
    desc: "Make Mav do something on a schedule",
    run: (a) => editRoutine(a.trim() ? draftRoutine(a.trim()) : null),
  },
  {
    cmd: "/watch",
    arg: "<url or topic>",
    desc: "Keep an eye on a page, a price or a topic",
    run: (a) => {
      go("routines", "watch");
      if (a.trim()) {
        setWatchKind(/^https?:/i.test(a.trim()) ? "web" : "news");
        $("#watchTarget").value = a.trim();
      }
      $("#watchTarget").focus();
    },
  },
  {
    cmd: "/rename",
    arg: "<title>",
    desc: "Rename this chat",
    run: async (a) => {
      if (!state.chat.id) return toast("Send a message first.");
      if (!a.trim()) return startRename();
      await api
        .post("session/rename", { id: state.chat.id, title: a.trim() })
        .catch(() => {});
      setChatTitle(a.trim());
      loadConvs();
    },
  },
  {
    cmd: "/brief",
    desc: "Your briefing: weather, what happened, what needs you",
    run: () => briefMe(),
  },
  {
    cmd: "/summary",
    desc: "Summarise this chat",
    run: () => $("#summaryBtn").click(),
  },
  {
    cmd: "/export",
    desc: "Download this chat",
    run: () => $("#exportBtn").click(),
  },
  { cmd: "/help", desc: "Shortcuts and commands", run: () => showHelp() },
];
let slashFocus = 0;
function matchingSlash(v) {
  const word = v.split(/\s/)[0].toLowerCase();
  return SLASH.filter((s) => s.cmd.startsWith(word));
}
function showSlash() {
  const v = chatInput.value;
  if (!v.startsWith("/") || v.includes("\n") || v.includes(" "))
    return hideSlash();
  const items = matchingSlash(v);
  if (!items.length) return hideSlash();
  slashFocus = Math.min(slashFocus, items.length - 1);
  $("#slashMenu").innerHTML = items
    .map(
      (
        s,
        i,
      ) => `<button type="button" class="slash-item ${i === slashFocus ? "is-focus" : ""}" data-cmd="${s.cmd}">
        <code>${s.cmd}${s.arg ? " " + esc(s.arg) : ""}</code><span>${esc(s.desc)}</span></button>`,
    )
    .join("");
  $("#slashMenu").hidden = false;
}
function hideSlash() {
  $("#slashMenu").hidden = true;
  slashFocus = 0;
}
function pickSlash(s) {
  hideSlash();
  if (s.arg) {
    chatInput.value = s.cmd + " ";
    chatInput.focus();
  } else {
    chatInput.value = "";
    s.run("");
  }
}
function slashKey(e) {
  const items = matchingSlash(chatInput.value);
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    slashFocus =
      (slashFocus + (e.key === "ArrowDown" ? 1 : -1) + items.length) %
      items.length;
    showSlash();
    return true;
  }
  if (e.key === "Tab" || e.key === "Enter") {
    e.preventDefault();
    if (items[slashFocus]) pickSlash(items[slashFocus]);
    return true;
  }
  if (e.key === "Escape") {
    hideSlash();
    return true;
  }
  return false;
}
chatInput.addEventListener("input", showSlash);
$("#slashMenu").addEventListener("mousedown", (e) => {
  const b = e.target.closest("[data-cmd]");
  if (!b) return;
  e.preventDefault();
  pickSlash(SLASH.find((x) => x.cmd === b.dataset.cmd));
});
function runSlash(text) {
  const m = text.trim().match(/^(\/\w+)\s*([\s\S]*)$/);
  if (!m) return false;
  const s =
    SLASH.find((x) => x.cmd === m[1].toLowerCase()) ||
    (m[1].toLowerCase() === "/agent" ? SLASH[1] : null);
  if (!s) return false;
  s.run(m[2] || "");
  return true;
}

/* ---------- Attachments ---------- */
$("#chatFileInput").addEventListener("change", (e) => {
  [...e.target.files].forEach(uploadFile);
  e.target.value = "";
});
function uploadFile(f) {
  if (f.size > 25e6)
    return toast(`${f.name} is too large (25 MB max).`, { error: true });
  const entry = { filename: f.name, mime: f.type, url: "", loading: true };
  state.pendingFiles.push(entry);
  renderAttachments();
  const reader = new FileReader();
  reader.onload = async () => {
    const b64 = String(reader.result).split(",")[1];
    if (LIVE) {
      try {
        Object.assign(
          entry,
          await api.post("upload", { name: f.name, data: b64, mime: f.type }),
        );
      } catch (_) {
        state.pendingFiles = state.pendingFiles.filter((x) => x !== entry);
        toast(`Upload failed: ${f.name}`, { error: true });
      }
    }
    entry.loading = false;
    renderAttachments();
  };
  reader.readAsDataURL(f);
}
function renderAttachments() {
  const box = $("#chatAttachments");
  box.innerHTML = state.pendingFiles
    .map(
      (f, i) =>
        `<span class="att-chip ${f.loading ? "is-loading" : ""}">${I("paperclip")} ${esc(f.filename)} <button type="button" data-rm-att="${i}" aria-label="Remove">${I("x")}</button></span>`,
    )
    .join("");
  box.hidden = !state.pendingFiles.length;
}
$("#chatAttachments").addEventListener("click", (e) => {
  const rm = e.target.closest("[data-rm-att]");
  if (!rm) return;
  state.pendingFiles.splice(Number(rm.dataset.rmAtt), 1);
  renderAttachments();
});
$("#view-chat").addEventListener("dragover", (e) => e.preventDefault());
$("#view-chat").addEventListener("drop", (e) => {
  e.preventDefault();
  [...(e.dataTransfer.files || [])].forEach(uploadFile);
});
document.addEventListener("paste", (e) => {
  const files = [...((e.clipboardData && e.clipboardData.files) || [])];
  if (files.length && state.view === "chat") {
    e.preventDefault();
    files.forEach(uploadFile);
  }
});
