/* ============================================================
   Mav — dashboard
   LIVE mode talks to mav_api.py (/api/*), with SSE streaming for chat.
   Falls back to a small demo mode when the API is unreachable.
   ============================================================ */

/* ================================================================
   1. Utilities
   ================================================================ */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
const escapeHtml = esc;

const store = {
  get(k, d = null) {
    try {
      const v = localStorage.getItem(k);
      return v == null ? d : v;
    } catch (_) {
      return d;
    }
  },
  set(k, v) {
    try {
      if (v == null) localStorage.removeItem(k);
      else localStorage.setItem(k, v);
    } catch (_) {}
  },
};

/* Icons: stroke SVGs (Lucide-style), injected into <i data-i="name">. */
const ICON_PATHS = {
  home: '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
  chat: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>',
  bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
  brain:
    '<path d="M9 3a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 1V5a2 2 0 0 0-3-2zM15 3a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 1"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  server:
    '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>',
  settings:
    '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  bell: '<path d="M6 8a6 6 0 1 1 12 0c0 7 3 8 3 8H3s3-1 3-8"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  moon: '<path d="M21 13A9 9 0 1 1 11 3a7 7 0 0 0 10 10z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  paperclip:
    '<path d="m21 11-8.5 8.5a5 5 0 0 1-7-7L14 4a3.5 3.5 0 0 1 5 5l-8.5 8.5a2 2 0 0 1-3-3L15 7"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  "arrow-up": '<path d="M12 19V5M5 12l7-7 7 7"/>',
  square: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>',
  pin: '<path d="M12 17v5M9 3h6l-1 6 4 4H6l4-4z"/>',
  sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  download: '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
  check: '<path d="M5 12.5 10 17 19 7"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 6.3M20 4v7h-7"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
  play: '<path d="M7 4v16l13-8z"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  chart: '<path d="M3 3v18h18"/><path d="m7 15 4-4 3 3 5-6"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  plug: '<path d="M9 2v6M15 2v6M6 8h12v3a6 6 0 0 1-12 0zM12 17v5"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M17 6l3 3"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  tool: '<path d="M14.7 6.3a4 4 0 0 0 5 5L21 13l-8 8-3-3 8-8-1.3-1.3a4 4 0 0 0-5-5L14 2z"/>',
  power: '<path d="M12 2v10M6.3 6.3a8 8 0 1 0 11.4 0"/>',
  volume: '<path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16 9a4 4 0 0 1 0 6M19 6a8 8 0 0 1 0 12"/>',
  tag: '<path d="M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9z"/><circle cx="7.5" cy="7.5" r="1.5"/>',
  news: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 8h10M7 12h10M7 16h6"/>',
};
function icon(name, cls = "") {
  const p = ICON_PATHS[name] || ICON_PATHS.sparkle;
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="${cls}" aria-hidden="true">${p}</svg>`;
}
function hydrateIcons(root = document) {
  root.querySelectorAll("i[data-i]").forEach((el) => {
    if (el.dataset.done === el.dataset.i) return;
    el.innerHTML = icon(el.dataset.i);
    el.dataset.done = el.dataset.i;
  });
}
const I = (name) => `<i data-i="${name}">${icon(name)}</i>`;

/* Time formatting */
function toMs(ts) {
  if (!ts) return 0;
  return ts > 1e12 ? ts : ts * 1000;
}
function fmtClock(ts) {
  const ms = toMs(ts);
  if (!ms) return "";
  return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function fmtRel(ts) {
  const ms = toMs(ts);
  if (!ms) return "";
  const s = (Date.now() - ms) / 1000;
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400 && new Date(ms).getDate() === new Date().getDate())
    return fmtClock(ms);
  if (s < 2 * 86400) return "yesterday";
  if (s < 7 * 86400)
    return new Date(ms).toLocaleDateString([], { weekday: "long" });
  return new Date(ms).toLocaleDateString([], { day: "numeric", month: "short" });
}
function dayGroup(ts) {
  const ms = toMs(ts);
  if (!ms) return "Older";
  const d = new Date(ms);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = (today - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000;
  if (diff <= 0) return "Today";
  if (diff <= 1) return "Yesterday";
  if (diff <= 7) return "Previous 7 days";
  if (diff <= 30) return "Previous 30 days";
  return "Older";
}
function fmtBytes(b) {
  if (!b) return "—";
  const g = b / 1e9;
  return g >= 1 ? `${g.toFixed(1)} GB` : `${Math.round(b / 1e6)} MB`;
}
function fmtUptime(s) {
  if (!s) return "—";
  const d = Math.floor(s / 86400),
    h = Math.floor((s % 86400) / 3600);
  return d > 0 ? `${d}d ${h}h` : `${h}h`;
}
const DAY_NAMES = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };
const ALL_DAYS = Object.keys(DAY_NAMES);
function fmtDays(days) {
  if (!days || !days.length || days.length === 7) return "every day";
  const wk = ["mon", "tue", "wed", "thu", "fri"];
  if (days.length === 5 && wk.every((d) => days.includes(d))) return "weekdays";
  if (days.length === 2 && days.includes("sat") && days.includes("sun")) return "weekends";
  return days.map((d) => DAY_NAMES[d] || d).join(", ");
}

/* Agent identity: a stable colour + initial per agent name. */
function agentColor(name) {
  const fixed = {
    assistant: "#2f6f5e",
    researcher: "#2f6fb0",
    writer: "#a8457a",
    planner: "#b8693a",
    money: "#3f8f4f",
  };
  if (fixed[name]) return fixed[name];
  let h = 0;
  for (const c of String(name || "mav")) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h} 45% 45%)`;
}
function agentDisplay(name) {
  if (!name) return "Assistant";
  return name
    .split(/[-_]/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
function agentAvatar(name, cls = "") {
  const n = name || "mav";
  return `<span class="agent-av ${cls}" style="--agent:${agentColor(name)}" aria-hidden="true">${esc((n[0] || "m").toUpperCase())}</span>`;
}

/* Toasts (with an optional action button). */
function toast(msg, opts = {}) {
  const box = $("#toasts");
  const el = document.createElement("div");
  el.className = "toast" + (opts.error ? " is-err" : "");
  el.innerHTML = `<span>${esc(msg)}</span>`;
  if (opts.action) {
    const b = document.createElement("button");
    b.textContent = opts.action.label;
    b.addEventListener("click", () => {
      opts.action.run();
      remove();
    });
    el.appendChild(b);
  }
  box.appendChild(el);
  const remove = () => {
    el.classList.add("is-leaving");
    setTimeout(() => el.remove(), 200);
  };
  setTimeout(remove, opts.duration || (opts.action ? 7000 : 2800));
  while (box.children.length > 3) box.firstChild.remove();
  return remove;
}

/* Modal dialogs (replaces window.prompt / confirm). */
const modal = {
  onClose: null,
  open({ title, body, actions = [], size = "", onClose = null }) {
    $("#modalTitle").textContent = title || "";
    const b = $("#modalBody");
    b.innerHTML = "";
    if (typeof body === "string") b.innerHTML = body;
    else if (body) b.appendChild(body);
    const foot = $("#modalFoot");
    foot.innerHTML = "";
    actions.forEach((a) => {
      const btn = document.createElement("button");
      btn.className = `btn ${a.kind || "btn-ghost"} ${a.left ? "left" : ""}`;
      btn.textContent = a.label;
      if (a.id) btn.id = a.id;
      btn.addEventListener("click", async () => {
        if (a.run) {
          const r = await a.run(btn);
          if (r === false) return;
        }
        modal.close();
      });
      foot.appendChild(btn);
    });
    $(".modal-box").className = "modal-box" + (size ? ` is-${size}` : "");
    this.onClose = onClose;
    $("#modal").hidden = false;
    hydrateIcons(b);
    setTimeout(() => {
      const f = b.querySelector("input, textarea, select") || foot.querySelector(".btn-primary");
      if (f) f.focus();
    }, 30);
  },
  close() {
    if ($("#modal").hidden) return;
    $("#modal").hidden = true;
    const cb = this.onClose;
    this.onClose = null;
    if (cb) cb();
  },
};
$("#modalClose").addEventListener("click", () => modal.close());
$("#modal").addEventListener("mousedown", (e) => {
  if (e.target.id === "modal") modal.close();
});

function confirmDialog(title, text, okLabel = "Confirm", danger = true) {
  return new Promise((resolve) => {
    let done = false;
    modal.open({
      title,
      size: "small",
      body: `<p>${esc(text)}</p>`,
      actions: [
        { label: "Cancel", run: () => { done = true; resolve(false); } },
        { label: okLabel, kind: danger ? "btn-danger" : "btn-primary", run: () => { done = true; resolve(true); } },
      ],
      onClose: () => { if (!done) resolve(false); },
    });
  });
}

/* API */
let LIVE = false;
const api = {
  async get(path) {
    const r = await fetch(`/api/${path}`, { headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(`/api/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    let data = null;
    try {
      data = await r.json();
    } catch (_) {}
    if (!r.ok) {
      const err = new Error((data && data.error) || `HTTP ${r.status}`);
      err.data = data;
      throw err;
    }
    return data;
  },
};
function needLive() {
  if (LIVE) return true;
  toast("Not available in the demo — open Mav from your own server.");
  return false;
}

/* ================================================================
   2. State
   ================================================================ */
const state = {
  status: null,
  agents: [],
  agentInfo: {},
  defaultAgent: "",
  preferredAgent: store.get("mav-agent", ""),
  convs: [],
  chat: { id: null, title: "", agent: "", pinned: false, routine: false, messages: [] },
  streaming: false,
  pendingFiles: [],
  jobs: [],
  memory: { conversations: [], facts: [], preferences: [] },
  inbox: [],
  view: "chat",
};

function currentAgent() {
  return state.chat.agent || state.preferredAgent || state.defaultAgent || state.agents[0] || "";
}
function agentDesc(name) {
  return (state.agentInfo[name] && state.agentInfo[name].description) || "";
}

/* ================================================================
   3. Navigation (hash routing: #chat/<id>, #routines, #settings/model…)
   ================================================================ */
const VIEW_TITLES = { chat: "Mav", routines: "Routines", memory: "Memory", settings: "Settings" };

function go(view, sub, { push = true } = {}) {
  if (!$(`#view-${view}`)) view = "chat";
  state.view = view;
  $$(".nav-item").forEach((b) => b.classList.toggle("is-active", b.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("is-active", v.id === `view-${view}`));
  $("#topbarTitle").textContent = view === "chat" ? state.chat.title || "Mav" : VIEW_TITLES[view];
  closeDrawer();
  if (view === "settings") openSettingsTab(sub || currentSettingsTab());
  if (view === "memory") loadMemory();
  if (view === "routines") openRoutinesTab(sub || currentRoutinesTab());
  if (view === "chat" && !state.chat.id) refreshInbox();
  if (push) {
    const h = view === "chat" ? (state.chat.id ? `#chat/${state.chat.id}` : "#") : sub ? `#${view}/${sub}` : `#${view}`;
    if ((location.hash || "#") !== h) history.pushState(null, "", h === "#" ? location.pathname : h);
  }
  renderConvList();
}

window.addEventListener("popstate", () => route());
function route() {
  const [view, arg] = location.hash.replace(/^#/, "").split("/");
  if (!view || view === "chat") {
    if (arg && arg !== state.chat.id) openChat(decodeURIComponent(arg), { push: false });
    else if (!arg && state.chat.id) newChat(null, { push: false });
    else go("chat", null, { push: false });
    return;
  }
  // Old links from the previous layout.
  const alias = { home: "chat", jobs: "routines", watch: "routines" };
  go(alias[view] || view, view === "watch" ? "watch" : arg, { push: false });
}

document.addEventListener("click", (e) => {
  const g = e.target.closest("[data-goto]");
  if (!g) return;
  const [view, sub] = g.dataset.goto.split(":");
  go(view, sub);
});
$$(".nav-item").forEach((b) => b.addEventListener("click", () => go(b.dataset.view)));

/* Mobile drawer */
function openDrawer() {
  document.body.classList.add("drawer-open");
  $("#scrim").hidden = false;
}
function closeDrawer() {
  document.body.classList.remove("drawer-open");
  $("#scrim").hidden = true;
}
$("#menuBtn").addEventListener("click", openDrawer);
$("#sidebarClose").addEventListener("click", closeDrawer);
$("#scrim").addEventListener("click", closeDrawer);
$("#topbarNew").addEventListener("click", () => newChat());
$("#newChat").addEventListener("click", () => newChat());

/* Theme */
function applyTheme(mode) {
  if (mode === "light" || mode === "dark") document.documentElement.dataset.theme = mode;
  else delete document.documentElement.dataset.theme;
  store.set("mav-theme", mode === "auto" ? null : mode);
  const dark = mode === "dark" || (mode !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  $("#themeToggle").innerHTML = I(dark ? "sun" : "moon");
  $$("#themeSeg button").forEach((b) => b.classList.toggle("is-active", b.dataset.themeSet === (mode || "auto")));
}
$("#themeToggle").addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(dark ? "light" : "dark");
});
$$("#themeSeg button").forEach((b) => b.addEventListener("click", () => applyTheme(b.dataset.themeSet)));
applyTheme(store.get("mav-theme", "auto") || "auto");

/* ================================================================
   4. Helper (agent) picker
   ================================================================ */
let agentMenuCtx = null;

function pillHtml(name, small) {
  return `${agentAvatar(name, small ? "sm" : "")}<span>${esc(agentDisplay(name))}</span>${I("chevron").replace("data-i", 'class="caret" data-i')}`;
}
function renderAgentPills() {
  const a = currentAgent();
  $("#chatAgent").innerHTML = pillHtml(a);
  $("#composerAgent").innerHTML = pillHtml(a, true);
}

function openAgentMenu(anchor, current, onPick) {
  const menu = $("#agentMenu");
  if (!menu.hidden && agentMenuCtx && agentMenuCtx.anchor === anchor) return closeAgentMenu();
  agentMenuCtx = { anchor, onPick };
  const list = state.agents.length ? state.agents : [""];
  menu.innerHTML =
    `<div class="menu-title">Talk to</div>` +
    list
      .map(
        (a) => `<button class="agent-opt" data-agent="${esc(a)}">
          ${agentAvatar(a)}
          <span class="meta"><strong>${esc(agentDisplay(a))}${a === state.defaultAgent ? " <small>· default</small>" : ""}</strong>
          <span>${esc(agentDesc(a) || "")}</span></span>
          ${a === current ? I("check").replace("data-i", 'class="check" data-i') : ""}
        </button>`,
      )
      .join("") +
    `<button class="agent-opt" data-goto="settings:helpers">${I("plus")}<span class="meta"><strong>Create a helper…</strong></span></button>`;
  menu.hidden = false;
  const r = anchor.getBoundingClientRect();
  const w = menu.offsetWidth;
  const h = menu.offsetHeight;
  let top = r.bottom + 6;
  if (top + h > window.innerHeight - 12) top = Math.max(12, r.top - h - 6);
  menu.style.left = `${Math.max(12, Math.min(r.left, window.innerWidth - w - 12))}px`;
  menu.style.top = `${top}px`;
  anchor.classList.add("is-open");
}
function closeAgentMenu() {
  $("#agentMenu").hidden = true;
  if (agentMenuCtx) agentMenuCtx.anchor.classList.remove("is-open");
  agentMenuCtx = null;
}
$("#agentMenu").addEventListener("click", (e) => {
  const opt = e.target.closest("[data-agent]");
  if (opt && agentMenuCtx) agentMenuCtx.onPick(opt.dataset.agent);
  closeAgentMenu();
});
document.addEventListener("mousedown", (e) => {
  if ($("#agentMenu").hidden) return;
  if (e.target.closest("#agentMenu") || (agentMenuCtx && agentMenuCtx.anchor.contains(e.target))) return;
  closeAgentMenu();
});
["#chatAgent", "#composerAgent"].forEach((s) =>
  $(s).addEventListener("click", (e) => openAgentMenu(e.currentTarget, currentAgent(), (a) => switchAgent(a))),
);

async function switchAgent(name) {
  if (name === currentAgent()) return;
  state.chat.agent = name;
  state.preferredAgent = name;
  store.set("mav-agent", name);
  renderAgentPills();
  if (state.chat.id && LIVE) {
    api.post("session/agent", { id: state.chat.id, agent: name }).catch(() => {});
    const c = state.convs.find((x) => x.id === state.chat.id);
    if (c) c.agent = name;
    renderConvList();
  }
  if (state.chat.messages.length) appendDivider(`Now talking to <strong>${esc(agentDisplay(name))}</strong>`, name);
  else renderThread();
}

/* ================================================================
   5. Chats (sidebar)
   ================================================================ */
function renderConvList() {
  const box = $("#convList");
  const q = ($("#convFilter").value || "").trim().toLowerCase();
  const list = state.convs.filter((c) => !q || c.title.toLowerCase().includes(q));
  if (!list.length) {
    box.innerHTML = `<div class="conv-empty">${q ? "No match." : "Your chats will appear here."}</div>`;
    return;
  }
  let html = "";
  let group = null;
  for (const c of list) {
    const g = c.pinned ? "Pinned" : dayGroup(c.updated);
    if (g !== group) {
      html += `<div class="conv-group">${g}</div>`;
      group = g;
    }
    const active = state.view === "chat" && c.id === state.chat.id;
    html += `<div class="conv-item ${active ? "is-active" : ""} ${c._new ? "is-new" : ""}" data-id="${esc(c.id)}" role="button" tabindex="0" title="${esc(c.title)} · ${esc(agentDisplay(c.agent || state.defaultAgent))}">
      ${c.routine ? `<span class="agent-av sm routine-av">${I("bolt")}</span>` : agentAvatar(c.agent || state.defaultAgent, "sm")}
      <span class="ctitle">${esc(c.title)}</span>
      ${c.pinned ? I("pin").replace("data-i", 'class="cpin" data-i') : ""}
      <button class="cdel" data-del="${esc(c.id)}" title="Delete">${I("trash")}</button>
    </div>`;
    c._new = false;
  }
  box.innerHTML = html;
}
$("#convFilter").addEventListener("input", renderConvList);
$("#convList").addEventListener("click", (e) => {
  const del = e.target.closest("[data-del]");
  if (del) {
    e.stopPropagation();
    deleteChat(del.dataset.del);
    return;
  }
  const item = e.target.closest(".conv-item");
  if (item) openChat(item.dataset.id);
});
$("#convList").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.classList.contains("conv-item")) openChat(e.target.dataset.id);
});

async function loadConvs() {
  if (!LIVE) return renderConvList();
  try {
    const prev = new Map(state.convs.map((c) => [c.id, c.title]));
    state.convs = (await api.get("sessions")).sessions || [];
    state.convs.forEach((c) => {
      if (prev.has(c.id) && prev.get(c.id) !== c.title) c._new = true;
    });
  } catch (_) {}
  renderConvList();
  const cur = state.convs.find((c) => c.id === state.chat.id);
  if (cur && cur.title !== state.chat.title && $("#chatTitle").contentEditable !== "true") setChatTitle(cur.title);
}

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
  if (state.streaming) stopStreaming();
  if (agent) {
    state.preferredAgent = agent;
    store.set("mav-agent", agent);
  }
  state.chat = { id: null, title: "", agent: agent || state.preferredAgent || "", pinned: false, routine: false, messages: [] };
  setChatTitle("");
  updateChatActions();
  renderAgentPills();
  renderThread();
  go("chat", null, { push });
  setTimeout(() => $("#chatInput").focus(), 50);
}

async function openChat(id, { push = true } = {}) {
  if (!id) return newChat();
  if (state.streaming && id !== state.chat.id) stopStreaming();
  const c = state.convs.find((x) => x.id === id);
  state.chat = { id, title: c ? c.title : "", agent: c ? c.agent : "", pinned: !!(c && c.pinned), routine: !!(c && c.routine), messages: [] };
  setChatTitle(state.chat.title);
  renderAgentPills();
  updateChatActions();
  setEmpty(false);
  go("chat", null, { push });
  if (!LIVE) return renderThread();
  messagesEl.innerHTML = `<div class="thread"><div class="thinking-row">${dots()} Loading…</div></div>`;
  try {
    const s = await api.get(`session?id=${encodeURIComponent(id)}`);
    if (state.chat.id !== id) return;
    state.chat.title = s.title || state.chat.title;
    state.chat.agent = s.agent || state.chat.agent;
    state.chat.messages = s.messages || [];
    setChatTitle(state.chat.title);
    renderAgentPills();
    renderThread();
  } catch (_) {
    renderThread();
    toast("Could not load this chat.", { error: true });
  }
}

function updateChatActions() {
  const has = !!state.chat.id;
  ["#pinBtn", "#summaryBtn", "#exportBtn", "#deleteChatBtn"].forEach((s) => ($(s).hidden = !has));
  $("#pinBtn").classList.toggle("is-on", !!state.chat.pinned);
  $("#pinBtn").title = state.chat.pinned ? "Unpin" : "Pin";
}

function setEmpty(on) {
  $("#chat").classList.toggle("is-empty", on);
}
const dots = () => `<span class="thinking-dots"><span></span><span></span><span></span></span>`;

function renderThread() {
  const msgs = state.chat.messages;
  if (!msgs.length) {
    setEmpty(true);
    const a = currentAgent();
    const name = (state.status && state.status.user_name) || "";
    messagesEl.innerHTML = `<div class="welcome">
      <h1>${esc(greet())}${name ? ", " + esc(name) : ""}</h1>
      <p class="welcome-who">${agentAvatar(a, "sm")} <span>You're talking to <strong>${esc(agentDisplay(a))}</strong>${agentDesc(a) ? " — " + esc(lowerFirst(agentDesc(a))) : ""}</span></p>
    </div>`;
    refreshInbox();
    return;
  }
  setEmpty(false);
  messagesEl.innerHTML = `<div class="thread" id="thread"></div>`;
  let lastAgent = null;
  msgs.forEach((m, i) => {
    if (m.role === "mav") {
      const ag = m.agent || "";
      if (lastAgent && ag && ag !== lastAgent) appendDivider(`Now talking to <strong>${esc(agentDisplay(ag))}</strong>`, ag, false);
      if (ag) lastAgent = ag;
    }
    appendMessage(m, { last: i === msgs.length - 1, scroll: false });
  });
  scrollToBottom(true);
}
function lowerFirst(s) {
  return s ? s[0].toLowerCase() + s.slice(1) : s;
}
function greet() {
  const h = new Date().getHours();
  return h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
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

function appendMessage(m, { last = false, scroll = true, streaming = false } = {}) {
  const t = threadEl();
  t.querySelectorAll(".msg.is-last").forEach((x) => x.classList.remove("is-last"));
  const el = document.createElement("div");
  if (m.role === "me") {
    el.className = "msg me";
    el.innerHTML = `<div class="bubble"></div>`;
    el.querySelector(".bubble").textContent = m.text;
  } else {
    const ag = m.agent || currentAgent();
    el.className = `msg mav ${last ? "is-last" : ""} ${m.error ? "is-error" : ""} ${streaming ? "is-streaming" : ""}`;
    el.style.setProperty("--agent", agentColor(ag));
    el.innerHTML = `${agentAvatar(ag)}
      <div class="body">
        <div class="msg-meta"><span class="who">${esc(agentDisplay(ag))}</span>${m.ts ? `<span>${esc(fmtClock(m.ts))}</span>` : ""}</div>
        <div class="bubble"></div>
        ${m.recalled ? `<div class="recall-note">${I("brain")} Used ${m.recalled} thing${m.recalled > 1 ? "s" : ""} from memory</div>` : ""}
        <div class="msg-actions">
          <button class="icon-btn" data-act="copy" title="Copy">${I("copy")}</button>
          <button class="icon-btn" data-act="retry" title="Regenerate">${I("refresh")}</button>
          <button class="icon-btn" data-act="speak" title="Read aloud">${I("volume")}</button>
        </div>
      </div>`;
    el.querySelector(".bubble").innerHTML = mdToHtml(m.text || "");
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
  return messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 140;
}
function scrollToBottom(force = false) {
  if (force || nearBottom()) messagesEl.scrollTop = messagesEl.scrollHeight;
}

/* Message actions + code copy */
messagesEl.addEventListener("click", async (e) => {
  const copy = e.target.closest(".code-copy");
  if (copy) {
    await copyText(copy.closest(".code-block").querySelector("code").textContent);
    copy.innerHTML = `${I("check")} Copied`;
    setTimeout(() => (copy.innerHTML = `${I("copy")} Copy`), 1500);
    return;
  }
  const act = e.target.closest("[data-act]");
  if (act) {
    const msg = act.closest(".msg")._msg;
    if (act.dataset.act === "copy") {
      await copyText(msg.text);
      toast("Copied.");
    } else if (act.dataset.act === "retry") {
      const lastUser = [...state.chat.messages].reverse().find((m) => m.role === "me");
      if (lastUser) send(lastUser.text);
    } else if (act.dataset.act === "speak") speak(msg.text, true);
    return;
  }
  const img = e.target.closest("img.md-img");
  if (img) openLightbox(img.src);
});

/* Suggestions on the new-chat screen */
$("#suggestions").addEventListener("click", (e) => {
  const b = e.target.closest("[data-prompt], [data-fill]");
  if (!b) return;
  if (b.dataset.prompt) return send(b.dataset.prompt);
  const ta = $("#chatInput");
  ta.value = b.dataset.fill;
  autoGrow(ta);
  ta.focus();
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
  if (!save || !name || name === state.chat.title) return setChatTitle(state.chat.title);
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
  } else if (titleEl.contentEditable !== "true" && (e.key === "F2" || e.key === " ")) {
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
  await api.post("session/pin", { id: state.chat.id, pinned: state.chat.pinned }).catch(() => {});
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
      actions: [{ label: "Copy", run: () => copyText(r.summary || "") }, { label: "Close", kind: "btn-primary" }],
    });
  } catch (_) {
    done();
    toast("Summary failed.", { error: true });
  }
});
$("#deleteChatBtn").addEventListener("click", () => state.chat.id && deleteChat(state.chat.id));

async function deleteChat(id) {
  if (!needLive()) return;
  const c = state.convs.find((x) => x.id === id);
  const ok = await confirmDialog("Delete this chat?", `“${c ? c.title : "This chat"}” will be deleted for good.`, "Delete");
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
  if (state.streaming) return;
  if (!text.trim() && !state.pendingFiles.length) return;
  chatInput.value = "";
  autoGrow(chatInput);
  hideSlash();
  send(text);
});

/* ---------- Slash commands ---------- */
const SLASH = [
  { cmd: "/new", desc: "Start a new chat", run: () => newChat() },
  {
    cmd: "/helper", arg: "<name>", desc: "Switch who you talk to",
    run: (a) => {
      const name = a.trim().toLowerCase();
      if (!name) return openAgentMenu($("#composerAgent"), currentAgent(), (x) => switchAgent(x));
      if (state.agents.length && !state.agents.includes(name)) return toast(`Unknown helper: ${name}`, { error: true });
      switchAgent(name);
    },
  },
  {
    cmd: "/remember", arg: "<fact>", desc: "Save something about you to memory",
    run: async (a) => {
      if (!a.trim()) return toast("Usage: /remember <something about you>");
      if (!needLive()) return;
      try {
        await api.post("memory/fact/add", { fact: a.trim() });
        toast("Got it — I'll remember that.", { action: { label: "View memory", run: () => go("memory") } });
      } catch (e) {
        toast(e.message, { error: true });
      }
    },
  },
  {
    cmd: "/routine", arg: "<what, when>", desc: "Make Mav do something on a schedule",
    run: (a) => editRoutine(a.trim() ? draftRoutine(a.trim()) : null),
  },
  {
    cmd: "/watch", arg: "<url or topic>", desc: "Keep an eye on a page, a price or a topic",
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
    cmd: "/rename", arg: "<title>", desc: "Rename this chat",
    run: async (a) => {
      if (!state.chat.id) return toast("Send a message first.");
      if (!a.trim()) return startRename();
      await api.post("session/rename", { id: state.chat.id, title: a.trim() }).catch(() => {});
      setChatTitle(a.trim());
      loadConvs();
    },
  },
  { cmd: "/summary", desc: "Summarise this chat", run: () => $("#summaryBtn").click() },
  { cmd: "/export", desc: "Download this chat", run: () => $("#exportBtn").click() },
  { cmd: "/help", desc: "Shortcuts and commands", run: () => showHelp() },
];
let slashFocus = 0;
function matchingSlash(v) {
  const word = v.split(/\s/)[0].toLowerCase();
  return SLASH.filter((s) => s.cmd.startsWith(word));
}
function showSlash() {
  const v = chatInput.value;
  if (!v.startsWith("/") || v.includes("\n") || v.includes(" ")) return hideSlash();
  const items = matchingSlash(v);
  if (!items.length) return hideSlash();
  slashFocus = Math.min(slashFocus, items.length - 1);
  $("#slashMenu").innerHTML = items
    .map(
      (s, i) => `<button type="button" class="slash-item ${i === slashFocus ? "is-focus" : ""}" data-cmd="${s.cmd}">
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
    slashFocus = (slashFocus + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
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
  const s = SLASH.find((x) => x.cmd === m[1].toLowerCase()) || (m[1].toLowerCase() === "/agent" ? SLASH[1] : null);
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
  if (f.size > 25e6) return toast(`${f.name} is too large (25 MB max).`, { error: true });
  const entry = { filename: f.name, mime: f.type, url: "", loading: true };
  state.pendingFiles.push(entry);
  renderAttachments();
  const reader = new FileReader();
  reader.onload = async () => {
    const b64 = String(reader.result).split(",")[1];
    if (LIVE) {
      try {
        Object.assign(entry, await api.post("upload", { name: f.name, data: b64, mime: f.type }));
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

/* ---------- Sending (SSE streaming) ---------- */
let streamCtl = null;

function setStreaming(on) {
  state.streaming = on;
  document.body.classList.toggle("is-thinking", on);
  $("#sendBtn").hidden = on;
  $("#stopBtn").hidden = !on;
}
function stopStreaming() {
  if (streamCtl) streamCtl.abort();
  streamCtl = null;
  if (state.chat.id && LIVE) api.post("session/abort", { id: state.chat.id }).catch(() => {});
  setStreaming(false);
}
$("#stopBtn").addEventListener("click", () => {
  stopStreaming();
  toast("Stopped.");
});

async function send(raw) {
  const text = (raw || "").trim();
  if (text.startsWith("/") && runSlash(text)) return;
  if (state.pendingFiles.some((f) => f.loading)) return toast("Wait for the upload to finish.");
  if (!text && !state.pendingFiles.length) return;
  if (state.view !== "chat") go("chat");

  const files = state.pendingFiles.slice();
  state.pendingFiles = [];
  renderAttachments();

  const shown = text || files.map((f) => f.filename).join(", ");
  const userMsg = { role: "me", text: shown + (text && files.length ? `\n📎 ${files.map((f) => f.filename).join(", ")}` : ""), ts: Date.now() };
  state.chat.messages.push(userMsg);
  appendMessage(userMsg);
  scrollToBottom(true);

  const agent = currentAgent();
  const routineDraft = detectRoutine(text);

  if (!LIVE) return demoReply(text, routineDraft);

  setStreaming(true);
  const thinking = document.createElement("div");
  thinking.className = "msg mav";
  thinking.style.setProperty("--agent", agentColor(agent));
  thinking.innerHTML = `${agentAvatar(agent)}<div class="body"><div class="msg-meta"><span class="who">${esc(agentDisplay(agent))}</span></div>
    <div class="thinking-row">${dots()} thinking…</div></div>`;
  threadEl().appendChild(thinking);
  scrollToBottom(true);

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
      thinking.remove();
      setStreaming(false);
      return addError("I couldn't start the chat — is the assistant running? See Settings → General → Advanced.");
    }
  }

  const qs = new URLSearchParams({ prompt: text || "(see the attached files)", session: state.chat.id, agent });
  if (files.length) qs.set("files", JSON.stringify(files.map((f) => ({ url: f.url, mime: f.mime, filename: f.filename }))));

  const reply = { role: "mav", text: "", agent, ts: Date.now() };
  let el = null;
  let error = null;
  let finished = false;
  let raf = 0;
  streamCtl = new AbortController();
  const sid = state.chat.id;

  try {
    const resp = await fetch(`/api/stream?${qs}`, { headers: { Accept: "text/event-stream" }, signal: streamCtl.signal });
    if (!resp.ok || !resp.body) throw new Error("stream unavailable");
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    const paint = () => {
      raf = 0;
      if (!el) {
        thinking.remove();
        el = appendMessage(reply, { last: true, streaming: true });
      } else {
        const stick = nearBottom();
        el.querySelector(".bubble").innerHTML = mdToHtml(reply.text);
        if (stick) scrollToBottom(true);
      }
    };
    while (!finished) {
      let chunk;
      try {
        chunk = await reader.read();
      } catch (_) {
        break;
      }
      if (chunk.done) break;
      buf += decoder.decode(chunk.value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        let ev = "message";
        const data = [];
        block.split("\n").forEach((l) => {
          if (l.startsWith("event:")) ev = l.slice(6).trim();
          else if (l.startsWith("data:")) data.push(l.slice(5).trim());
        });
        let d = {};
        try {
          d = JSON.parse(data.join("\n") || "{}");
        } catch (_) {}
        if (ev === "start") {
          if (d.recalled) reply.recalled = d.recalled;
          if (d.agent) reply.agent = d.agent;
        } else if (ev === "delta") {
          reply.text += d.delta || "";
          if (!raf) raf = requestAnimationFrame(paint);
        } else if (ev === "done") {
          if (!reply.text && d.text) reply.text = d.text;
          finished = true;
        } else if (ev === "error") {
          error = d.message || "Something went wrong.";
          finished = true;
        }
      }
    }
    try {
      reader.cancel();
    } catch (_) {}
  } catch (e) {
    error = e.name === "AbortError" ? (reply.text ? null : "Stopped.") : "Connection lost.";
  }

  if (state.chat.id !== sid) {
    if (raf) cancelAnimationFrame(raf);
    setStreaming(false);
    return; // the user moved to another chat meanwhile
  }
  // A paint may still be queued (the whole answer can arrive in one chunk).
  if (raf) cancelAnimationFrame(raf);
  raf = 0;
  thinking.remove();
  if (el) el.remove();
  if (error && !reply.text) {
    addError(error);
  } else {
    if (!reply.text) reply.text = "_(no answer)_";
    state.chat.messages.push(reply);
    appendMessage(reply, { last: true });
    if (S.speak) speak(reply.text);
    if (routineDraft) offerRoutine(routineDraft);
  }
  setStreaming(false);
  streamCtl = null;
  await loadConvs();
  if (wasNew && !error) watchForTitle(sid);
  if (!error && ABOUT_ME_RE.test(text)) watchForMemory(sid);
  if (document.hidden && !error) notifyLocal(agentDisplay(reply.agent), reply.text);
}

function addError(msg) {
  appendMessage({ role: "mav", text: msg, agent: currentAgent(), error: true }, { last: true });
}

/* Mav learns facts about you in the background (when you talk about
   yourself): show "Memory updated" under the answer when it does. */
const ABOUT_ME_RE = /\b(i|i'm|im|i've|my|me|we|our|je|j'|moi|mon|ma|mes|nous|notre)\b/i;
async function watchForMemory(sid) {
  const base = state.status && Number(state.status.facts);
  if (!Number.isFinite(base)) return;
  for (const wait of [4000, 8000, 15000]) {
    await new Promise((r) => setTimeout(r, wait));
    let st;
    try {
      st = await api.get("status");
    } catch (_) {
      return;
    }
    renderStatus(st);
    if (Number(st.facts) > base) {
      if (state.chat.id !== sid) return;
      const last = [...$$(".msg.mav")].pop();
      if (!last) return;
      const note = document.createElement("button");
      note.className = "recall-note memory-updated";
      note.innerHTML = `${I("brain")} Memory updated`;
      note.title = "Mav learned something about you — manage it on the Memory page";
      note.addEventListener("click", () => go("memory"));
      last.querySelector(".body").insertBefore(note, last.querySelector(".msg-actions"));
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
  setStreaming(true);
  setTimeout(() => {
    const reply = {
      role: "mav",
      agent: a,
      ts: Date.now(),
      text: `This is the **demo**. On your own server, **${agentDisplay(a)}** would answer:\n\n> ${text || "(attachment)"}\n\nTip: type \`/\` for commands.`,
    };
    state.chat.messages.push(reply);
    appendMessage(reply, { last: true });
    if (!state.chat.title) setChatTitle(text.split(/\s+/).slice(0, 4).join(" ") || "Demo chat");
    setStreaming(false);
    if (draft) offerRoutine(draft);
  }, 600);
}

/* ================================================================
   7. Markdown (zero dependency, HTML-escaped first)
   ================================================================ */
function splitRow(line) {
  let s = String(line).trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}
function isTableSep(line) {
  const cells = splitRow(line);
  return cells.length > 0 && cells.every((c) => /^:?-{2,}:?$/.test(c));
}
function renderTable(lines) {
  const header = splitRow(lines[0]);
  const aligns = splitRow(lines[1]).map((c) =>
    /^:-+:$/.test(c) ? "center" : /^-+:$/.test(c) ? "right" : "",
  );
  const cls = (i) => (aligns[i] ? ` class="md-${aligns[i]}"` : "");
  const th = header.map((c, i) => `<th${cls(i)}>${inline(c)}</th>`).join("");
  const rows = lines
    .slice(2)
    .map(splitRow)
    .map((r) => "<tr>" + header.map((_, i) => `<td${cls(i)}>${inline(r[i] == null ? "" : r[i])}</td>`).join("") + "</tr>")
    .join("");
  return `<div class="md-table-wrap"><table class="md-table"><thead><tr>${th}</tr></thead><tbody>${rows}</tbody></table></div>`;
}
function inline(s) {
  let t = escapeHtml(s);
  t = t.replace(/`([^`\n]+)`/g, '<code class="md-inline">$1</code>');
  t = t.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  t = t.replace(/__([^_\n]+)__/g, "<strong>$1</strong>");
  t = t.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  t = t.replace(/(^|[^_\w])_([^_\n]+)_(?!\w)/g, "$1<em>$2</em>");
  t = t.replace(/~~([^~\n]+)~~/g, "<del>$1</del>");
  t = t.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, src) => {
    const rawSrc = src.replace(/&amp;/g, "&");
    const url = /^(https?:|data:image)/i.test(rawSrc)
      ? rawSrc
      : /^media:/i.test(rawSrc)
        ? "/api/media/by-name?name=" + encodeURIComponent(rawSrc.slice(6))
        : "/api/asset?path=" + encodeURIComponent(rawSrc);
    return `<img class="md-img" src="${escapeHtml(url)}" alt="${alt}" loading="lazy">`;
  });
  t = t.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  t = t.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>');
  return t;
}
function mdToHtml(src) {
  let text = String(src == null ? "" : src);
  const codeBlocks = [];
  const codeHtml = (lang, code) =>
    `<div class="code-block"><div class="code-head"><span>${escapeHtml(lang || "code")}</span><button type="button" class="code-copy">${I("copy")} Copy</button></div><pre class="md-code"><code>${escapeHtml(code.replace(/\n$/, ""))}</code></pre></div>`;
  text = text.replace(/```([\w+-]*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    codeBlocks.push(codeHtml(lang, code));
    return `\u0000CODE${codeBlocks.length - 1}\u0000`;
  });
  // Streaming: an unterminated fence still renders as code.
  text = text.replace(/```([\w+-]*)\n([\s\S]*)$/, (_, lang, code) => {
    codeBlocks.push(codeHtml(lang, code));
    return `\u0000CODE${codeBlocks.length - 1}\u0000`;
  });

  const renderTableAt = (lines, i) => {
    if (!/^\s*\|.*\|\s*$/.test(lines[i])) return null;
    if (i + 1 >= lines.length || !isTableSep(lines[i + 1])) return null;
    const block = [];
    let j = i;
    while (j < lines.length && /^\s*\|.*\|\s*$/.test(lines[j])) block.push(lines[j++]);
    return { html: renderTable(block), next: j };
  };

  const renderBlocks = (lines) => {
    let out = "";
    let para = [];
    const flush = () => {
      if (para.length) out += `<p class="md-p">${para.join("<br>")}</p>`;
      para = [];
    };
    let i = 0;
    while (i < lines.length) {
      const raw = lines[i];
      const line = raw.trim();
      if (!line) {
        flush();
        i++;
        continue;
      }
      let m = line.match(/^\u0000CODE(\d+)\u0000$/);
      if (m) {
        flush();
        out += codeBlocks[Number(m[1])] || "";
        i++;
        continue;
      }
      m = raw.match(/^(#{1,6})\s+(.*)$/);
      if (m) {
        flush();
        const lvl = Math.min(m[1].length + 1, 6);
        out += `<h${lvl} class="md-h">${inline(m[2])}</h${lvl}>`;
        i++;
        continue;
      }
      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(raw)) {
        flush();
        out += '<hr class="md-hr">';
        i++;
        continue;
      }
      const t = renderTableAt(lines, i);
      if (t) {
        flush();
        out += t.html;
        i = t.next;
        continue;
      }
      if (/^\s*>\s?/.test(raw)) {
        flush();
        const inner = [];
        let j = i;
        while (j < lines.length && /^\s*>\s?/.test(lines[j])) inner.push(lines[j++].replace(/^\s*>\s?/, ""));
        out += `<blockquote class="md-quote">${renderBlocks(inner)}</blockquote>`;
        i = j;
        continue;
      }
      if (/^(\s*)([-*+]|\d+[.)])\s+/.test(raw)) {
        flush();
        const items = [];
        let j = i;
        while (j < lines.length && /^(\s*)([-*+]|\d+[.)])\s+/.test(lines[j])) {
          const mm = lines[j].match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
          items.push({ indent: mm[1].replace(/\t/g, "    ").length, ordered: /^\d/.test(mm[2]), text: mm[3] });
          j++;
        }
        out += renderList(items);
        i = j;
        continue;
      }
      para.push(inline(raw));
      i++;
    }
    flush();
    return out;
  };
  return renderBlocks(text.split("\n")).replace(/\u0000CODE(\d+)\u0000/g, (_, i) => codeBlocks[Number(i)] || "");
}
function renderList(items) {
  const root = { children: [] };
  const stack = [{ indent: -1, node: root }];
  for (const it of items) {
    while (stack.length > 1 && it.indent <= stack[stack.length - 1].indent) stack.pop();
    const node = { ordered: it.ordered, text: it.text, children: [] };
    stack[stack.length - 1].node.children.push(node);
    stack.push({ indent: it.indent, node });
  }
  const walk = (nodes) => {
    let out = "";
    let i = 0;
    while (i < nodes.length) {
      const ordered = nodes[i].ordered;
      let j = i;
      while (j < nodes.length && nodes[j].ordered === ordered) j++;
      const tag = ordered ? "ol" : "ul";
      out += `<${tag} class="md-list">`;
      for (let k = i; k < j; k++) {
        let txt = nodes[k].text;
        const task = txt.match(/^\[( |x|X)\]\s+(.*)$/);
        const body = task ? `${task[1] === " " ? "☐" : "☑"} ${inline(task[2])}` : inline(txt);
        out += `<li>${body}${nodes[k].children.length ? walk(nodes[k].children) : ""}</li>`;
      }
      out += `</${tag}>`;
      i = j;
    }
    return out;
  };
  return walk(root.children);
}

/* ================================================================
   8. Status + proactive inbox (on the new-chat screen)
   ================================================================ */
function renderStatus(st) {
  state.status = st;
  if (!st) return;
  renderPending(st.pending || []);
  $("#onboard").hidden = !(st.mode === "live" && st.provider_configured === false);
  const dot = $("#engineChipDot");
  dot.className = "dot " + (st.mode !== "live" ? "warn" : st.agent_online ? "ok" : "off");
  const model = st.model ? st.model.split("/").pop() : "no model yet";
  $("#engineChipText").textContent = st.mode !== "live" ? "Demo" : st.agent_online ? model : "Assistant offline";
  $("#engineChip").title = st.mode !== "live" ? "Demo mode" : st.agent_online ? `Model: ${st.model || "—"}` : "The assistant is not responding";
}
$("#engineChip").addEventListener("click", () =>
  go("settings", state.status && state.status.provider_configured === false ? "model" : state.status && !state.status.agent_online ? "general" : "model"),
);

const TOPIC_ICON = { routine: "bolt", job: "bolt", watch: "eye" };
async function refreshInbox() {
  if (!LIVE) return renderInbox(state.inbox);
  try {
    state.inbox = (await api.get("notifications")).notifications || [];
  } catch (_) {}
  renderInbox(state.inbox);
}
function renderInbox(items) {
  const week = Date.now() - 7 * 86400e3;
  const list = (items || []).filter((x) => toMs(x.ts) > week).slice(0, 4);
  $("#inboxWrap").hidden = !list.length;
  $("#inbox").innerHTML = list
    .map(
      (x, i) => `<li class="inbox-item">
        <span class="inbox-ico">${I(TOPIC_ICON[x.topic] || "bell")}</span>
        <span class="what"><strong>${esc(x.title || "Notification")}</strong><span>${esc((x.body || "").replace(/[*_`#>|]+/g, "").replace(/\s+/g, " "))}</span></span>
        <span class="inbox-side"><span class="t">${esc(fmtRel(x.ts))}</span>
        <button class="btn btn-ghost btn-sm" data-more="${i}">Tell me more</button></span>
      </li>`,
    )
    .join("");
  $("#inbox")._items = list;
}
$("#inbox").addEventListener("click", (e) => {
  const b = e.target.closest("[data-more]");
  if (!b) return;
  tellMeMore($("#inbox")._items[Number(b.dataset.more)]);
});
async function tellMeMore(n) {
  if (!n) return;
  const m = (n.link || "").match(/#chat\/([^&?#]+)/);
  if (m) {
    await openChat(decodeURIComponent(m[1]));
    send("Tell me more about your latest report — what matters and what should I do?");
    return;
  }
  if (n.id) return openNotifById(n.id);
  newChat();
  send(`Tell me more about this: ${n.title}\n\n${n.body}`);
}

/* ================================================================
   9. Routines
   ================================================================ */
function jobMode(j) {
  if (j.every_minutes) return "hours";
  return j.days && j.days.length && j.days.length < 7 ? "weekly" : "daily";
}
function jobWhen(j) {
  const mode = jobMode(j);
  if (mode === "hours") {
    const h = Math.max(1, Math.round(Number(j.every_minutes) / 60));
    return h === 1 ? "every hour" : `every ${h} hours`;
  }
  return mode === "daily" ? `every day at ${j.time}` : `${fmtDays(j.days)} at ${j.time}`;
}
function currentRoutinesTab() {
  const a = $("[data-rtab].is-active");
  return a ? a.dataset.rtab : "routines";
}
function openRoutinesTab(tab) {
  if (!$(`#rpanel-${tab}`)) tab = "routines";
  $$("[data-rtab]").forEach((t) => t.classList.toggle("is-active", t.dataset.rtab === tab));
  $$(".rpanel").forEach((p) => p.classList.toggle("is-active", p.id === `rpanel-${tab}`));
  if (tab === "watch") loadWatch();
  else loadRoutines();
}
$$("[data-rtab]").forEach((t) =>
  t.addEventListener("click", () => {
    openRoutinesTab(t.dataset.rtab);
    history.replaceState(null, "", `#routines/${t.dataset.rtab}`);
  }),
);

async function loadRoutines() {
  if (LIVE) {
    try {
      state.jobs = (await api.get("jobs")).jobs || [];
    } catch (_) {}
  }
  renderRoutines();
}
function renderRoutines() {
  const jobs = state.jobs;
  $("#navRoutinesCount").textContent = jobs.filter((j) => j.enabled).length || "";
  const box = $("#routineList");
  if (!jobs.length) {
    box.innerHTML = `<div class="empty-state"><strong>No routine yet</strong>
      Mav can do things for you on a schedule — a morning briefing, a weekly meal plan, a reminder every Friday.
      <div class="suggest">${ROUTINE_IDEAS.map((r, i) => `<button class="chip" data-idea="${i}">${esc(r.label)}</button>`).join("")}</div></div>`;
    return;
  }
  box.innerHTML = jobs
    .map(
      (j, i) => `<div class="job ${j.enabled ? "" : "is-off"}">
      ${agentAvatar(j.agent || state.defaultAgent)}
      <div class="jmain">
        <div class="jtitle">${esc(j.name)} ${j.running ? `<span class="badge warn">${dots()} running</span>` : ""}</div>
        <div class="jdesc">${esc(j.description || j.prompt || "")}</div>
        <div class="jsched"><span class="badge">${I("clock")} ${esc(jobWhen(j))}</span>
          <span class="badge">${esc(agentDisplay(j.agent || state.defaultAgent))}</span>
          ${j.last_run ? `<span>last run ${esc(j.last_run)}</span>` : ""}</div>
      </div>
      <div class="jacts">
        ${j.session ? `<button class="btn btn-ghost btn-sm" data-open-chat="${esc(j.session)}">${I("chat")} Open chat</button>` : ""}
        <button class="btn btn-ghost btn-sm" data-run="${i}">${I("play")} Run now</button>
        <button class="icon-btn" data-edit-job="${i}" title="Edit">${I("edit")}</button>
        <button class="switch" role="switch" aria-checked="${j.enabled ? "true" : "false"}" data-toggle="${i}" title="${j.enabled ? "Pause" : "Turn on"}"></button>
      </div></div>`,
    )
    .join("");
}
const ROUTINE_IDEAS = [
  { label: "☀️ Morning briefing", draft: { name: "Morning briefing", prompt: "Give me a short morning briefing: today's weather where I live, and 3 headlines worth knowing. Keep it under 120 words.", mode: "daily", time: "07:30", agent: "researcher" } },
  { label: "🥗 Weekly meal plan", draft: { name: "Weekly meal plan", prompt: "Plan 5 simple dinners for this week, with a shopping list grouped by aisle. Take what you know about my diet into account.", mode: "weekly", days: ["sun"], time: "10:00", agent: "planner" } },
  { label: "🧾 Friday money check", draft: { name: "Friday money check", prompt: "Remind me to review this week's spending, and ask me 3 quick questions to keep my budget on track.", mode: "weekly", days: ["fri"], time: "18:00", agent: "money" } },
];
$("#routineList").addEventListener("click", async (e) => {
  const idea = e.target.closest("[data-idea]");
  if (idea) return editRoutine(ROUTINE_IDEAS[Number(idea.dataset.idea)].draft);
  const oc = e.target.closest("[data-open-chat]");
  if (oc) return openChat(oc.dataset.openChat);
  const ed = e.target.closest("[data-edit-job]");
  if (ed) return editRoutine(state.jobs[Number(ed.dataset.editJob)], true);
  const run = e.target.closest("[data-run]");
  const tog = e.target.closest("[data-toggle]");
  if ((!run && !tog) || !needLive()) return;
  if (run) {
    const j = state.jobs[Number(run.dataset.run)];
    try {
      const r = await api.post("job/run", { name: j.name });
      toast(`“${j.name}” is running — you'll get a notification.`, r.session ? { action: { label: "Open its chat", run: () => openChat(r.session) } } : {});
      setTimeout(loadRoutines, 600);
      pollRoutineDone(j.name);
    } catch (err) {
      toast(err.message, { error: true });
    }
  } else {
    const j = state.jobs[Number(tog.dataset.toggle)];
    try {
      await api.post("job/toggle", { name: j.name, enabled: !j.enabled });
      toast(!j.enabled ? "Routine on." : "Routine paused.");
      loadRoutines();
    } catch (_) {
      toast("Failed.", { error: true });
    }
  }
});
function pollRoutineDone(name, n = 0) {
  setTimeout(async () => {
    await loadRoutines();
    const j = state.jobs.find((x) => x.name === name);
    if (j && j.running && n < 150) return pollRoutineDone(name, n + 1);
    if (j && !j.running) {
      await loadConvs();
      toast(`“${name}” is done.`, j.session ? { action: { label: "Read it", run: () => openChat(j.session) } } : {});
    }
  }, 4000);
}
$("#routineNew").addEventListener("click", () => editRoutine(null));

/* Turn "every morning at 7, give me the weather" into a routine draft. */
const WEEKDAYS = { monday: "mon", tuesday: "tue", wednesday: "wed", thursday: "thu", friday: "fri", saturday: "sat", sunday: "sun" };
const RECUR_RE = /\b(every|each)\s+(day|morning|evening|night|afternoon|week|weekday|weekend|hour|\d+\s*h(ours?)?|monday|tuesday|wednesday|thursday|friday|saturday|sunday|mondays|tuesdays|wednesdays|thursdays|fridays|saturdays|sundays)\b|\b(daily|weekly|hourly)\b|\bon\s+(mondays|tuesdays|wednesdays|thursdays|fridays|saturdays|sundays|weekdays)\b/i;
function detectRoutine(text) {
  if (!text || text.length > 400 || text.startsWith("/")) return null;
  return RECUR_RE.test(text) ? draftRoutine(text) : null;
}
function draftRoutine(text) {
  const t = text.toLowerCase();
  const d = { mode: "daily", time: "09:00", days: [...ALL_DAYS], hours: 0 };
  let m;
  if ((m = t.match(/every\s+(\d+)\s*h(ours?)?/))) {
    d.mode = "hours";
    d.hours = Number(m[1]);
  } else if (/\b(every|each)\s+hour\b|\bhourly\b/.test(t)) {
    d.mode = "hours";
    d.hours = 1;
  }
  const days = Object.entries(WEEKDAYS).filter(([w]) => t.includes(w)).map(([, v]) => v);
  if (/weekdays?\b/.test(t)) d.days = ["mon", "tue", "wed", "thu", "fri"];
  else if (/weekends?\b/.test(t)) d.days = ["sat", "sun"];
  else if (days.length) d.days = days;
  else if (/\b(every|each)\s+week\b|\bweekly\b/.test(t)) d.days = ["mon"];
  if (d.mode !== "hours" && d.days.length < 7) d.mode = "weekly";
  const parts = [
    { re: /\bmorning\b/, h: "08:00" },
    { re: /\b(noon|lunch(time)?)\b/, h: "12:00" },
    { re: /\bafternoon\b/, h: "15:00" },
    { re: /\bevening\b/, h: "19:00" },
    { re: /\bnight\b/, h: "21:00" },
  ];
  parts.forEach((p) => {
    if (p.re.test(t)) d.time = p.h;
  });
  const tm =
    t.match(/\bat\s+(\d{1,2})(?:[:h.](\d{2}))?\s*(am|pm)?\b/) ||
    t.match(/\b(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)\b/) ||
    t.match(/\b(\d{1,2})[:h](\d{2})\b/);
  if (tm) {
    let h = Number(tm[1]);
    if (tm[3] === "pm" && h < 12) h += 12;
    if (tm[3] === "am" && h === 12) h = 0;
    if (h < 24) d.time = `${String(h).padStart(2, "0")}:${tm[2] || "00"}`;
  }
  // What to do = the sentence without the scheduling words.
  let what = text
    .replace(/\b(every|each)\s+(\d+\s*h(ours?)?|day|morning|evening|night|afternoon|week|weekday|weekend|hour|monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b/gi, "")
    .replace(/\b(daily|weekly|hourly)\b/gi, "")
    .replace(/\bon\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekday)s?\b/gi, "")
    .replace(/\bat\s+\d{1,2}(?:[:h.]\d{2})?\s*(am|pm)?\b/gi, "")
    .replace(/\b\d{1,2}(?:[:.]\d{2})?\s*(am|pm)\b/gi, "")
    .replace(/\s{2,}/g, " ")
    .replace(/^[\s,.:;-]+|[\s,.:;-]+$/g, "");
  const remind = what.match(/^(please\s+)?remind me (to |about |that )?(.*)$/i);
  d.prompt = remind
    ? `Send me a short, friendly reminder: ${remind[3]}. One or two sentences.`
    : what.charAt(0).toUpperCase() + what.slice(1);
  const nameSrc = remind ? remind[3] : what;
  d.name = (nameSrc.split(/\s+/).slice(0, 4).join(" ") || "Routine").replace(/[^\w\s.-]/g, "").trim();
  d.name = d.name.charAt(0).toUpperCase() + d.name.slice(1);
  d.agent = currentAgent();
  return d;
}
function draftWhen(d) {
  return d.mode === "hours" ? (d.hours === 1 ? "every hour" : `every ${d.hours} hours`) : d.mode === "weekly" ? `${fmtDays(d.days)} at ${d.time}` : `every day at ${d.time}`;
}
function uniqueRoutineName(name, original = "") {
  const taken = new Set(state.jobs.map((j) => j.name).filter((n) => n !== original));
  if (!taken.has(name)) return name;
  let i = 2;
  while (taken.has(`${name} ${i}`)) i++;
  return `${name} ${i}`;
}
function draftToJob(d) {
  const job = { name: uniqueRoutineName(d.name, d.original || ""), prompt: d.prompt, agent: d.agent || "", enabled: true, description: d.description || "" };
  if (d.mode === "hours") job.every_minutes = Math.max(1, d.hours) * 60;
  else {
    job.time = d.time;
    job.days = d.mode === "weekly" ? d.days : [...ALL_DAYS];
  }
  return job;
}
function offerRoutine(d) {
  const card = document.createElement("div");
  card.className = "offer";
  card.innerHTML = `<div class="offer-ico">${I("bolt")}</div>
    <div class="offer-main"><strong>Make this a routine?</strong>
      <span>${esc(draftWhen(d))} · ${esc(agentDisplay(d.agent))} — “${esc(d.prompt.slice(0, 120))}”</span></div>
    <div class="offer-acts">
      <button class="btn btn-primary btn-sm" data-o="create">Create routine</button>
      <button class="btn btn-ghost btn-sm" data-o="edit">Edit…</button>
      <button class="icon-btn" data-o="no" title="Dismiss">${I("x")}</button>
    </div>`;
  card.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-o]");
    if (!b) return;
    if (b.dataset.o === "no") return card.remove();
    if (b.dataset.o === "edit") return editRoutine(d);
    if (!needLive()) return;
    try {
      await api.post("job/save", draftToJob(d));
      card.innerHTML = `<div class="offer-ico">${I("check")}</div><div class="offer-main"><strong>Routine created</strong><span>${esc(d.name)} — ${esc(draftWhen(d))}. You'll get a notification each time.</span></div>
        <div class="offer-acts"><button class="btn btn-ghost btn-sm" data-goto="routines">See routines</button></div>`;
      loadRoutines();
    } catch (err) {
      toast(err.message, { error: true });
    }
  });
  threadEl().appendChild(card);
  scrollToBottom();
}

function editRoutine(src, existing = false) {
  const isNew = !existing;
  let d;
  if (!src) d = { name: "", prompt: "", agent: state.preferredAgent || state.defaultAgent, mode: "daily", time: "08:00", days: [...ALL_DAYS], hours: 4 };
  else if (existing) {
    const mode = jobMode(src);
    d = { ...src, mode, hours: mode === "hours" ? Math.max(1, Math.round(src.every_minutes / 60)) : 4, days: src.days && src.days.length ? src.days : [...ALL_DAYS], time: src.time || "08:00" };
  } else d = { hours: 4, days: [...ALL_DAYS], time: "08:00", ...src };
  if (state.view !== "routines" && !existing) go("routines", "routines");
  const form = document.createElement("form");
  form.className = "form";
  form.innerHTML = `
    <div class="field"><label>What should Mav do?</label>
      <textarea name="prompt" required placeholder="e.g. Tell me if I need an umbrella today, and what to wear.">${esc(d.prompt || "")}</textarea>
      <small>Write it like a message to Mav. If there's nothing worth telling you, it stays quiet.</small></div>
    <div class="field"><span class="field-label">When</span>
      <div class="segmented" data-modes>
        <button type="button" data-m="daily">Every day</button><button type="button" data-m="weekly">Some days</button><button type="button" data-m="hours">Every few hours</button>
      </div></div>
    <div class="when-row">
      <div class="field" data-f="time"><label>At</label><input type="time" name="time" value="${esc(d.time)}"></div>
      <div class="field" data-f="days"><span class="field-label">On</span><div class="days">${ALL_DAYS.map((x) => `<button type="button" data-day="${x}" class="${d.days.includes(x) ? "is-on" : ""}">${DAY_NAMES[x]}</button>`).join("")}</div></div>
      <div class="field" data-f="hours"><label>Every</label><div class="row"><input type="number" min="1" max="72" name="hours" value="${esc(d.hours)}" style="width:90px"> <span>hours</span></div></div>
    </div>
    <div class="field-grid">
      <div class="field"><label>Helper</label><select name="agent">${state.agents
        .map((a) => `<option ${a === (d.agent || state.defaultAgent) ? "selected" : ""} value="${esc(a)}">${esc(agentDisplay(a))}</option>`)
        .join("")}</select></div>
      <div class="field"><label>Name</label><input name="name" value="${esc(d.name || "")}" placeholder="Morning briefing"></div>
    </div>`;
  let mode = d.mode;
  const setMode = (x) => {
    mode = x;
    form.querySelectorAll("[data-m]").forEach((b) => b.classList.toggle("is-active", b.dataset.m === x));
    form.querySelector('[data-f="time"]').hidden = x === "hours";
    form.querySelector('[data-f="days"]').hidden = x !== "weekly";
    form.querySelector('[data-f="hours"]').hidden = x !== "hours";
  };
  setMode(mode);
  form.addEventListener("click", (e) => {
    const b = e.target.closest("[data-m]");
    if (b) setMode(b.dataset.m);
    const day = e.target.closest("[data-day]");
    if (day) day.classList.toggle("is-on");
  });
  form.addEventListener("submit", (e) => e.preventDefault());
  const save = async (btn) => {
    if (!needLive()) return false;
    const fd = new FormData(form);
    const prompt = String(fd.get("prompt") || "").trim();
    let name = String(fd.get("name") || "").trim();
    if (!name) name = prompt.split(/\s+/).slice(0, 4).join(" ").replace(/[^\w\s.-]/g, "").trim() || "Routine";
    const job = draftToJob({
      original: existing ? d.name : "",
      name, prompt, agent: fd.get("agent"), mode, time: fd.get("time"),
      hours: Number(fd.get("hours") || 1),
      days: [...form.querySelectorAll("[data-day].is-on")].map((b) => b.dataset.day),
      description: existing ? d.description : "",
    });
    if (mode === "weekly" && !job.days.length) {
      toast("Pick at least one day.", { error: true });
      return false;
    }
    job.original = existing ? d.name : "";
    job.enabled = existing ? d.enabled !== false : true;
    btn.disabled = true;
    try {
      await api.post("job/save", job);
      toast(isNew ? "Routine created — you'll get a notification each time it runs." : "Routine saved.");
      loadRoutines();
      return true;
    } catch (err) {
      btn.disabled = false;
      toast(err.message, { error: true });
      return false;
    }
  };
  const actions = [];
  if (existing)
    actions.push({
      label: "Delete", kind: "btn-danger", left: true,
      run: async () => {
        if (!(await confirmDialog("Delete this routine?", `“${d.name}” will stop running. Its chat is kept.`, "Delete"))) return false;
        await api.post("job/delete", { name: d.name }).catch(() => {});
        toast("Routine deleted.");
        loadRoutines();
      },
    });
  actions.push({ label: "Cancel" }, { label: isNew ? "Create routine" : "Save", kind: "btn-primary", run: save });
  modal.open({ title: isNew ? "New routine" : `Routine “${d.name}”`, body: form, actions });
}

/* ================================================================
   10. Keep an eye on
   ================================================================ */
const WATCH_KINDS = {
  web: { ph: "https://example.com/page", hint: "You'll get an alert when the text of the page changes.", ico: "globe", label: "Page" },
  price: { ph: "https://shop.example.com/product", hint: "Mav reads the price on the page and alerts you when it changes — or only when it drops below your target.", ico: "tag", label: "Price" },
  news: { ph: "a topic, e.g. “Lyon public transport strike”", hint: "You'll get the new headlines about this topic as they come out.", ico: "news", label: "News" },
};
let watchKind = "web";
function setWatchKind(k) {
  watchKind = k;
  $$("#watchKinds [data-kind]").forEach((b) => b.classList.toggle("is-active", b.dataset.kind === k));
  $("#watchTarget").placeholder = WATCH_KINDS[k].ph;
  $("#watchHint").textContent = WATCH_KINDS[k].hint;
  $("#watchBelow").hidden = k !== "price";
}
$("#watchKinds").addEventListener("click", (e) => {
  const b = e.target.closest("[data-kind]");
  if (b) setWatchKind(b.dataset.kind);
});
setWatchKind("web");
async function loadWatch() {
  if (!LIVE) return renderWatch({ items: [] });
  try {
    renderWatch(await api.get("watch"));
  } catch (_) {}
}
function renderWatch(w) {
  const items = ((w && w.items) || []).filter((x) => WATCH_KINDS[x.kind]);
  $("#watchList").innerHTML = items.length
    ? items
        .map((x) => {
          const k = WATCH_KINDS[x.kind];
          const [target, below] = String(x.target).split("|");
          const price = (x.last_state || "").match(/price=([0-9.]+)/);
          return `<div class="wcard"><div class="wtop">${I(k.ico)} ${esc(k.label)}
            <button class="icon-btn" data-rm="${x.id}" title="Stop">${I("trash")}</button></div>
            <div class="wtarget">${/^https?:/.test(target) ? `<a href="${esc(target)}" target="_blank" rel="noopener">${esc(target.replace(/^https?:\/\/(www\.)?/, "").slice(0, 70))}</a>` : esc(target)}</div>
            <div class="wstate"><span class="dot ${x.last_state ? "ok" : ""}"></span>
              ${price ? `Now ${esc(price[1])}${below ? ` · alert below ${esc(below)}` : ""} · ` : below ? `Alert below ${esc(below)} · ` : ""}
              ${x.last_checked ? `checked ${esc(fmtRel(x.last_checked))}` : "first check soon"}</div></div>`;
        })
        .join("")
    : `<div class="empty-state"><strong>Nothing yet</strong>Paste a page, a product or a topic above — Mav checks it regularly and pings you when it changes.</div>`;
}
$("#watchForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!needLive()) return;
  let target = $("#watchTarget").value.trim();
  if (!target) return $("#watchTarget").focus();
  if (watchKind !== "news" && !/^https?:\/\//i.test(target)) target = "https://" + target;
  const below = $("#watchBelow").value.trim();
  if (watchKind === "price" && below) target += `|${below}`;
  try {
    await api.post("watch/add", { kind: watchKind, target });
    $("#watchTarget").value = "";
    $("#watchBelow").value = "";
    toast("Got it — Mav will keep an eye on it.");
    loadWatch();
  } catch (_) {
    toast("Could not add it.", { error: true });
  }
});
$("#watchList").addEventListener("click", async (e) => {
  const rm = e.target.closest("[data-rm]");
  if (!rm || !needLive()) return;
  await api.post("watch/remove", { id: Number(rm.dataset.rm) }).catch(() => {});
  toast("Stopped.");
  loadWatch();
});

/* ================================================================
   11. Memory
   ================================================================ */
$$("[data-mtab]").forEach((t) =>
  t.addEventListener("click", () => {
    $$("[data-mtab]").forEach((x) => x.classList.toggle("is-active", x === t));
    $$(".mpanel").forEach((p) => p.classList.toggle("is-active", p.id === `mpanel-${t.dataset.mtab}`));
  }),
);
async function loadMemory() {
  if (LIVE) {
    try {
      state.memory = await api.get("memory");
    } catch (_) {}
  }
  renderMemory();
}
function renderMemory() {
  const m = state.memory;
  const b = $("#memoryBackend");
  b.className = "badge " + (m.backend === "postgres" ? "ok" : "warn");
  b.textContent = m.backend === "postgres" ? "Memory on" : LIVE ? "Database offline" : "Demo";
  const facts = m.facts || [];
  $("#factCount").textContent = facts.length || "";
  $("#exCount").textContent = (m.conversations || []).length || "";
  $("#factList").innerHTML = facts.length
    ? facts
        .map(
          (f) => `<li><span class="ltext"><strong>${esc(f.fact)}</strong>
          <span class="lmeta">${esc(fmtRel(f.ts))}</span></span>
          <button class="icon-btn" data-del-fact="${f.id}" title="Forget">${I("trash")}</button></li>`,
        )
        .join("")
    : `<li class="empty">Nothing yet. Tell Mav about yourself above, or type <code>/remember …</code> in any chat.</li>`;
  renderExchanges(m.conversations || []);
}
function renderExchanges(list, isSearch = false) {
  $("#exchangeList").innerHTML = list.length
    ? list
        .map(
          (c) => `<li><span class="ltext"><strong>${esc(c.question || c.title || c.fact || "")}</strong>
          <span>${esc(c.answer || c.excerpt || "")}</span>
          <span class="lmeta">${esc(fmtRel(c.ts))}${c.agent ? " · " + esc(agentDisplay(c.agent)) : ""}${c.kind ? " · " + esc(c.kind) : ""}</span></span>
          ${c.id && !isSearch ? `<button class="icon-btn" data-del-ex="${c.id}" title="Forget">${I("trash")}</button>` : ""}</li>`,
        )
        .join("")
    : `<li class="empty">${isSearch ? "No result." : "Your past chats are remembered here and brought back when they're relevant."}</li>`;
}
$("#factForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const v = $("#factInput").value.trim();
  if (!v || !needLive()) return;
  try {
    await api.post("memory/fact/add", { fact: v });
    $("#factInput").value = "";
    toast("Got it — I'll remember that.");
    loadMemory();
  } catch (err) {
    toast(err.message, { error: true });
  }
});
document.addEventListener("click", async (e) => {
  const f = e.target.closest("[data-del-fact]");
  const x = e.target.closest("[data-del-ex]");
  if ((!f && !x) || !needLive()) return;
  await api.post(f ? "memory/fact/delete" : "memory/exchange/delete", { id: Number(f ? f.dataset.delFact : x.dataset.delEx) }).catch(() => {});
  toast("Forgotten.");
  loadMemory();
});
$("#forgetAll").addEventListener("click", async () => {
  if (!needLive()) return;
  if (!(await confirmDialog("Clear chat memory?", "Mav will stop recalling your past chats. What it knows about you (above) is kept.", "Clear"))) return;
  await api.post("memory/forget", {}).catch(() => {});
  toast("Chat memory cleared.");
  loadMemory();
});
let memTimer = null;
$("#memorySearch").addEventListener("input", (e) => {
  const q = e.target.value.trim();
  clearTimeout(memTimer);
  memTimer = setTimeout(async () => {
    if (!q) return renderExchanges(state.memory.conversations || []);
    if (!LIVE) return;
    try {
      const r = await api.get(`search?q=${encodeURIComponent(q)}`);
      renderExchanges(
        [...(r.conversations || []), ...(r.facts || []).map((f) => ({ ...f, kind: "about you" })), ...(r.documents || []).map((d) => ({ ...d, kind: "document" }))],
        true,
      );
    } catch (_) {}
  }, 250);
});

/* ================================================================
   12. Settings
   ================================================================ */
function currentSettingsTab() {
  const a = $("[data-stab].is-active");
  return a ? a.dataset.stab : "model";
}
function openSettingsTab(tab) {
  if (tab === "agents") tab = "helpers";
  if (tab === "system" || tab === "advanced") {
    tab = "general";
    $("#advanced").open = true;
  }
  if (!$(`#spanel-${tab}`)) tab = "model";
  $$("[data-stab]").forEach((t) => t.classList.toggle("is-active", t.dataset.stab === tab));
  $$(".spanel").forEach((p) => p.classList.toggle("is-active", p.id === `spanel-${tab}`));
  ({ model: loadProvider, helpers: loadAgentFiles, instructions: loadInstructions, connections: loadMcp, general: () => { loadAdvanced(); checkVersion(); } }[tab] || (() => {}))();
}
$$("[data-stab]").forEach((t) =>
  t.addEventListener("click", () => {
    openSettingsTab(t.dataset.stab);
    history.replaceState(null, "", `#settings/${t.dataset.stab}`);
  }),
);
function setStatus(id, text, kind) {
  const el = $("#" + id);
  if (!el) return;
  el.textContent = text;
  el.className = "status-text" + (kind ? " is-" + kind : "");
  if (kind === "ok") setTimeout(() => (el.textContent = ""), 2500);
}

/* ---- "Restart to apply" bar ---- */
function renderPending(list) {
  const bar = $("#pendingBar");
  if (!list.length || !LIVE) {
    bar.hidden = true;
    return;
  }
  const names = list.map((x) => x.toLowerCase());
  const what = names.length === 1 ? names[0] : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
  $("#pendingText").textContent = `Your changes to ${what} are saved — restart the assistant to apply them.`;
  bar.hidden = false;
}
$("#pendingRestart").addEventListener("click", () => restartAssistant());

/* ---- Restarting the assistant (applies settings changes) ---- */
async function waitForAssistant(label = "Restarting the assistant…") {
  const done = toast(label, { duration: 120000 });
  for (let i = 0; i < 40; i++) {
    await new Promise((r) => setTimeout(r, 3000));
    try {
      const e = await api.get("config/engine");
      if (e.online) {
        done();
        toast("Assistant ready.");
        loadAgentsList();
        refreshStatus();
        renderEngine(e);
        return true;
      }
    } catch (_) {}
  }
  done();
  toast("The assistant did not come back — see Settings → General → Advanced.", { error: true });
  return false;
}
async function restartAssistant() {
  if (!needLive()) return;
  const btns = [$("#engineRestart"), $("#pendingRestart")];
  btns.forEach((b) => (b.disabled = true));
  $("#pendingRestart").textContent = "Restarting…";
  try {
    const r = await api.post("config/restart", {});
    if (!r.ok) throw new Error(r.error || "restart failed");
    await waitForAssistant();
  } catch (e) {
    toast(`Restart failed: ${e.message}`, { error: true });
  }
  btns.forEach((b) => (b.disabled = false));
  $("#pendingRestart").textContent = "Restart assistant";
  refreshStatus();
}
const restartAction = { label: "Restart now", run: () => restartAssistant() };
/* After a change that needs a restart: confirm it, and show the pending bar. */
function changed(msg) {
  toast(msg);
  refreshStatus();
}

/* ---- Model ---- */
let PROV = { presets: [], current: {}, sel: null };
async function loadProvider() {
  if (!LIVE) {
    PROV = { presets: DEMO.presets, current: { configured: false }, sel: PROV.sel };
    return renderProvider();
  }
  try {
    const d = await api.get("config/provider");
    PROV.presets = d.presets || [];
    PROV.current = d.current || {};
  } catch (_) {}
  if (!PROV.sel && PROV.current.preset && PROV.presets.some((p) => p.id === PROV.current.preset)) PROV.sel = PROV.current.preset;
  renderProvider();
}
function renderProvider() {
  const c = PROV.current || {};
  $("#currentModel").innerHTML = c.configured
    ? `<span class="cm-icon">${I("cpu")}</span><span class="cm-text"><span>Mav is using</span><strong>${esc(c.model)}</strong><span>${esc((PROV.presets.find((p) => p.id === c.preset) || {}).label || c.provider)}</span></span>
       <span class="badge ${c.has_key || c.preset === "ollama" ? "ok" : "warn"}">${c.has_key ? "key saved" : c.preset === "ollama" ? "on your network" : "no key"}</span>`
    : `<span class="cm-icon">${I("plug")}</span><span class="cm-text"><span>No model connected yet</span><strong>Choose a provider below</strong></span>`;
  $("#providerGrid").innerHTML = PROV.presets
    .map(
      (p) => `<button type="button" class="provider ${p.id === PROV.sel ? "is-sel" : ""}" data-prov="${esc(p.id)}">
        <strong>${esc(p.label)} ${p.id === c.preset ? '<span class="badge ok">in use</span>' : ""}</strong><span>${esc(p.hint)}</span></button>`,
    )
    .join("");
  const p = PROV.presets.find((x) => x.id === PROV.sel);
  $("#providerForm").hidden = !p;
  if (!p) return;
  const isCurrent = p.id === c.preset;
  $("#fCustomId").hidden = p.id !== "custom";
  if (p.id === "custom" && isCurrent) $("#pCustomId").value = c.provider;
  $("#fBase").hidden = p.native;
  $("#pBase").value = isCurrent && c.base_url ? c.base_url : p.base || "";
  $("#pBaseHint").textContent = p.id === "ollama" ? "Where Ollama runs — e.g. http://192.168.1.10:11434/v1" : "";
  $("#fKey").hidden = false;
  $("#pKey").value = "";
  $("#pKey").placeholder = isCurrent && c.has_key ? "•••••••• saved — leave empty to keep it" : p.key === "optional" ? "optional" : "paste your API key";
  $("#pKeyHint").textContent = p.key === "required" ? "Kept on your server only." : "";
  $("#pModel").value = isCurrent ? c.model : p.model || "";
  $("#pModelList").innerHTML = "";
  $("#pTestResult").textContent = "";
  $("#pTestResult").className = "";
}
$("#providerGrid").addEventListener("click", (e) => {
  const b = e.target.closest("[data-prov]");
  if (!b) return;
  PROV.sel = b.dataset.prov;
  renderProvider();
  $("#providerForm").scrollIntoView({ behavior: "smooth", block: "nearest" });
});
function providerPayload() {
  return {
    provider: PROV.sel,
    custom_id: $("#pCustomId").value.trim(),
    base_url: $("#fBase").hidden ? "" : $("#pBase").value.trim(),
    api_key: $("#pKey").value.trim(),
    model: $("#pModel").value.trim(),
  };
}
$("#pTest").addEventListener("click", async () => {
  if (!needLive()) return;
  const out = $("#pTestResult");
  const btn = $("#pTest");
  btn.disabled = true;
  out.className = "";
  out.textContent = "Checking…";
  try {
    const p = providerPayload();
    const r = await api.post("config/provider/test", { ...p, provider: p.provider === "custom" ? p.custom_id || "custom" : p.provider });
    if (r.ok) {
      $("#pModelList").innerHTML = r.models.map((m) => `<option value="${esc(m)}">`).join("");
      out.className = "is-ok";
      out.textContent = `Connected — ${r.models.length} model${r.models.length === 1 ? "" : "s"} available. Pick one in the field.`;
      if (!$("#pModel").value && r.models.length) $("#pModel").value = r.models[0];
    } else {
      out.className = "is-err";
      out.textContent = r.error || "Connection failed.";
    }
  } catch (e) {
    out.className = "is-err";
    out.textContent = e.message;
  }
  btn.disabled = false;
});
$("#providerForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!needLive()) return;
  const p = providerPayload();
  if (!p.model) return toast("Choose a model.", { error: true });
  const btn = $("#pSave");
  btn.disabled = true;
  try {
    const r = await api.post("config/provider", p);
    toast(`Model set: ${r.ref.split("/").slice(1).join("/")}.`);
    await loadProvider();
    if (r.restart && r.restart.ok) await waitForAssistant("Applying…");
    else if (r.restart) {
      toast(`Saved, but the restart failed: ${r.restart.error}`, { error: true, action: restartAction });
      refreshStatus();
    }
  } catch (err) {
    toast(err.message, { error: true });
  }
  btn.disabled = false;
});

/* ---- Helpers (agent files) ---- */
let AGENT_FILES = [];
let AGENT_DIR = "";
async function loadAgentFiles() {
  if (!LIVE) {
    AGENT_FILES = state.agents.map((a) => ({ name: a, description: agentDesc(a), mode: "all" }));
    return renderAgentCards();
  }
  try {
    const d = await api.get("config/agent-files");
    AGENT_DIR = d.dir || "";
    AGENT_FILES = d.agents || [];
  } catch (_) {}
  renderAgentCards();
}
function renderAgentCards() {
  $("#agentCards").innerHTML = AGENT_FILES.length
    ? AGENT_FILES.map(
        (a) => `<div class="acard">
        <div class="acard-head">${agentAvatar(a.name)}<strong>${esc(agentDisplay(a.name))}</strong>${a.name === state.defaultAgent ? '<span class="badge ok">default</span>' : ""}</div>
        <p>${esc(a.description || "No description.")}</p>
        <div class="acard-foot">
          <button class="btn btn-primary btn-sm" data-start-agent="${esc(a.name)}">${I("chat")} Chat</button>
          <button class="btn btn-ghost btn-sm" data-edit-agent="${esc(a.name)}">${I("edit")} Edit</button>
        </div></div>`,
      ).join("")
    : `<div class="empty-state"><strong>No helper yet</strong>Create one — a coach, a tutor, a travel agent — with its own instructions.</div>`;
}
document.addEventListener("click", (e) => {
  const s = e.target.closest("[data-start-agent]");
  if (s) newChat(s.dataset.startAgent);
});
$("#agentCards").addEventListener("click", (e) => {
  const b = e.target.closest("[data-edit-agent]");
  if (b) editAgent(b.dataset.editAgent);
});
$("#agentNew").addEventListener("click", () => editAgent(null));

function parseAgentFile(text) {
  const m = String(text || "").match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
  if (!m) return { front: [], body: text || "", meta: {} };
  const front = m[1].split("\n");
  const meta = {};
  front.forEach((l) => {
    const mm = l.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
    if (mm && mm[2] !== "") meta[mm[1]] = mm[2].replace(/^["']|["']$/g, "");
  });
  return { front, body: m[2].replace(/^\n/, ""), meta };
}
function buildAgentFile(front, fields, body) {
  const lines = front.slice();
  Object.entries(fields).forEach(([k, v]) => {
    const i = lines.findIndex((l) => l.startsWith(k + ":"));
    if (v) {
      const line = `${k}: ${v}`;
      if (i >= 0) lines[i] = line;
      else lines.splice(k === "description" ? 0 : lines.length, 0, line);
    } else if (i >= 0) lines.splice(i, 1);
  });
  // A new helper gets sensible everyday permissions.
  if (!lines.some((l) => l.startsWith("permission:")))
    lines.push("permission:", "  websearch: allow", "  webfetch: allow", "  todowrite: allow");
  return `---\n${lines.join("\n")}\n---\n\n${body.trim()}\n`;
}
async function editAgent(name) {
  const isNew = !name;
  let text = "";
  if (!isNew && LIVE) {
    try {
      text = (await api.get(`config/agent-file?name=${encodeURIComponent(name)}`)).text || "";
    } catch (_) {
      return toast("Could not load this helper.", { error: true });
    }
  }
  const parsed = parseAgentFile(text);
  const form = document.createElement("form");
  form.className = "form";
  form.innerHTML = `
    ${isNew ? `<div class="field"><label>Name</label><input name="name" placeholder="e.g. coach, tutor, traveller" required><small>One word. This is how you call it.</small></div>` : ""}
    <div class="field"><label>What is it good at?</label><input name="description" value="${esc(parsed.meta.description || "")}" placeholder="Helps me train for a half-marathon"><small>Shown when you pick a helper; the Assistant also uses it to decide when to call this one.</small></div>
    <div class="field"><label>Instructions</label><textarea name="body" style="min-height:220px" placeholder="You are my running coach. You know I run 3 times a week…">${esc(parsed.body)}</textarea></div>
    <details class="raw"><summary>Advanced</summary>
      <div class="field-grid" style="margin-top:.8rem">
        <div class="field"><label>Who can talk to it</label><select name="mode">
          ${[["all", "Me and the Assistant"], ["primary", "Only me"], ["subagent", "Only the Assistant"]].map(([v, l]) => `<option value="${v}" ${(parsed.meta.mode || "all") === v ? "selected" : ""}>${l}</option>`).join("")}
        </select></div>
        <div class="field"><label>Model (optional)</label><input name="model" value="${esc(parsed.meta.model || "")}" placeholder="same as Mav"></div>
      </div>
      ${AGENT_DIR ? `<p class="hint">Stored in <code>${esc(AGENT_DIR)}/${esc(name || "<name>")}.md</code></p>` : ""}
    </details>`;
  const actions = [];
  if (!isNew)
    actions.push({
      label: "Delete", kind: "btn-danger", left: true,
      run: async () => {
        if (!(await confirmDialog(`Delete “${agentDisplay(name)}”?`, "Chats with it are kept.", "Delete"))) return false;
        await api.post("config/agent-file/delete", { name }).catch(() => {});
        changed("Helper deleted.");
        loadAgentFiles();
      },
    });
  actions.push({ label: "Cancel" });
  actions.push({
    label: isNew ? "Create helper" : "Save",
    kind: "btn-primary",
    run: async (btn) => {
      if (!needLive()) return false;
      const fd = new FormData(form);
      const nm = isNew ? String(fd.get("name") || "").trim().toLowerCase().replace(/\s+/g, "-") : name;
      if (!/^[a-z0-9][a-z0-9_-]{0,40}$/.test(nm)) {
        toast("Use letters and digits only for the name.", { error: true });
        return false;
      }
      const out = buildAgentFile(
        parsed.front,
        { description: String(fd.get("description") || "").trim(), mode: fd.get("mode"), model: String(fd.get("model") || "").trim() },
        String(fd.get("body") || ""),
      );
      btn.disabled = true;
      try {
        await api.post("config/agent-file", { name: nm, text: out });
        changed(isNew ? `“${agentDisplay(nm)}” created.` : "Helper saved.");
        loadAgentFiles();
        return true;
      } catch (e) {
        btn.disabled = false;
        toast(e.message, { error: true });
        return false;
      }
    },
  });
  modal.open({ title: isNew ? "New helper" : agentDisplay(name), body: form, actions, size: "wide" });
}

/* ---- Custom instructions ---- */
async function loadInstructions() {
  if (!LIVE) {
    $("#agentsEditor").value = "";
    return;
  }
  try {
    $("#agentsEditor").value = (await api.get("config/agents")).text || "";
  } catch (_) {
    setStatus("agentsStatus", "couldn't load", "err");
  }
}
$("#agentsSave").addEventListener("click", async () => {
  if (!needLive()) return;
  setStatus("agentsStatus", "saving…");
  try {
    await api.post("config/agents", { text: $("#agentsEditor").value });
    setStatus("agentsStatus", "saved", "ok");
    changed("Custom instructions saved.");
  } catch (_) {
    setStatus("agentsStatus", "save failed", "err");
  }
});
$("#agentsEditor").addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "s") {
    e.preventDefault();
    $("#agentsSave").click();
  }
});

/* ---- Connections (MCP servers) ---- */
let MCP = {};
async function loadMcp() {
  if (!LIVE) {
    MCP = {};
    return renderMcp();
  }
  try {
    MCP = (await api.get("config/mcp")).mcp || {};
  } catch (_) {
    setStatus("mcpStatus", "couldn't load", "err");
  }
  renderMcp();
}
let CATALOG = { items: [], runtimes: {} };
async function loadCatalog() {
  if (!LIVE) return renderCatalog();
  try {
    CATALOG = await api.get("config/mcp/catalog");
  } catch (_) {}
  renderCatalog();
}
const CAT_ICON = { Web: "globe", Everyday: "clock", "Notes & tasks": "edit", Home: "home", Work: "tool" };
function renderCatalog() {
  const items = CATALOG.items || [];
  $("#mcpCatalog").innerHTML = items
    .map(
      (it) => `<button class="cat-item ${it.installed ? "is-added" : ""}" data-cat="${esc(it.id)}">
        <span class="cm-icon sm">${I(CAT_ICON[it.category] || "plug")}</span>
        <span class="cat-text"><strong>${esc(it.name)}</strong><span>${esc(it.description)}</span></span>
        <span class="badge ${it.installed ? "ok" : ""}">${it.installed ? "added" : it.ready ? "add" : "needs " + esc(it.runtime === "uvx" ? "uv" : "Node.js")}</span>
      </button>`,
    )
    .join("");
  const missing = Object.entries(CATALOG.runtimes || {}).filter(([, ok]) => !ok).map(([r]) => r);
  $("#runtimeHint").innerHTML = missing.length
    ? `Some connections need ${missing.map((r) => (r === "npx" ? "<strong>Node.js</strong> (<code>sudo apt install nodejs npm</code>)" : "<strong>uv</strong> (<code>curl -LsSf https://astral.sh/uv/install.sh | sh</code>)")).join(" and ")} on your server.`
    : "";
}
$("#mcpCatalog").addEventListener("click", (e) => {
  const b = e.target.closest("[data-cat]");
  if (!b) return;
  const it = (CATALOG.items || []).find((x) => x.id === b.dataset.cat);
  if (it) addFromCatalog(it);
});
function addFromCatalog(it) {
  const form = document.createElement("form");
  form.className = "form";
  const tz = (() => {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
    } catch (_) {
      return "";
    }
  })();
  form.innerHTML =
    `<p>${esc(it.description)}</p>` +
    (it.note ? `<div class="onboard soft"><span>${esc(it.note)}</span></div>` : "") +
    (it.inputs || [])
      .map(
        (inp) => `<div class="field"><label>${esc(inp.label)}</label>
          <input name="${esc(inp.key)}" ${inp.secret ? 'type="password" autocomplete="new-password"' : ""} placeholder="${esc(inp.placeholder || "")}" value="${esc(inp.default_from === "browser_timezone" ? tz : "")}">
          ${inp.help || inp.link ? `<small>${esc(inp.help || "")} ${inp.link ? `<a href="${esc(inp.link)}" target="_blank" rel="noopener">Get it here ↗</a>` : ""}</small>` : ""}</div>`,
      )
      .join("") +
    (!it.ready ? `<p class="status-text is-err">This one needs ${it.runtime === "uvx" ? "uv" : "Node.js"} on your server — see the hint below the list.</p>` : "") +
    (it.docs ? `<small><a href="${esc(it.docs)}" target="_blank" rel="noopener">How it works ↗</a></small>` : "");
  form.addEventListener("submit", (e) => e.preventDefault());
  modal.open({
    title: it.installed ? `${it.name} (already added)` : `Add ${it.name}`,
    body: form,
    actions: [
      { label: "Cancel" },
      {
        label: it.installed ? "Replace" : "Add",
        kind: "btn-primary",
        run: async (btn) => {
          if (!needLive()) return false;
          const values = Object.fromEntries(new FormData(form).entries());
          btn.disabled = true;
          try {
            await api.post("config/mcp/install", { id: it.id, values });
            changed(`${it.name} added.`);
            loadMcp();
            return true;
          } catch (e) {
            btn.disabled = false;
            toast(e.message, { error: true });
            return false;
          }
        },
      },
    ],
  });
}

function renderMcp() {
  $("#mcpEditor").value = JSON.stringify(MCP, null, 2);
  const names = Object.keys(MCP);
  $("#mcpCards").innerHTML = names.length
    ? names
        .map((n) => {
          const s = MCP[n] || {};
          const remote = s.type === "remote" || (!s.type && s.url);
          const on = s.enabled !== false;
          return `<div class="acard ${on ? "" : "is-off"}">
            <div class="acard-head"><span class="cm-icon sm">${I(remote ? "globe" : "plug")}</span><strong>${esc(n)}</strong>
              <button class="switch" role="switch" aria-checked="${on}" data-mcp-toggle="${esc(n)}" title="${on ? "Turn off" : "Turn on"}"></button></div>
            <p>${remote ? `Online service · ${esc(String(s.url || "").replace(/^https?:\/\//, "").slice(0, 60))}` : "Runs on your server"}</p>
            <div class="acard-foot"><button class="btn btn-ghost btn-sm" data-mcp-edit="${esc(n)}">${I("edit")} Edit</button>
            <button class="btn btn-ghost btn-sm danger" data-mcp-del="${esc(n)}">${I("trash")} Remove</button></div></div>`;
        })
        .join("")
    : `<div class="empty">None yet — pick one below.</div>`;
  loadCatalog();
}
async function saveMcp(next, msg = "Saved.") {
  if (!needLive()) return false;
  setStatus("mcpStatus", "saving…");
  try {
    await api.post("config/mcp", { mcp: next });
    MCP = next;
    renderMcp();
    setStatus("mcpStatus", "saved", "ok");
    changed(msg);
    return true;
  } catch (e) {
    setStatus("mcpStatus", "save failed", "err");
    toast(String(e.message).slice(0, 300), { error: true });
    return false;
  }
}
$("#mcpCards").addEventListener("click", async (e) => {
  const t = e.target.closest("[data-mcp-toggle]");
  const d = e.target.closest("[data-mcp-del]");
  const ed = e.target.closest("[data-mcp-edit]");
  if (t) {
    const n = t.dataset.mcpToggle;
    saveMcp({ ...MCP, [n]: { ...MCP[n], enabled: MCP[n].enabled === false } });
  } else if (d) {
    const n = d.dataset.mcpDel;
    if (!(await confirmDialog(`Remove “${n}”?`, "Mav won't be able to use it anymore.", "Remove"))) return;
    const next = { ...MCP };
    delete next[n];
    saveMcp(next, "Removed.");
  } else if (ed) editMcp(ed.dataset.mcpEdit);
});
$("#mcpAdd").addEventListener("click", () => editMcp(null));
function editMcp(name) {
  const s = name ? MCP[name] : { type: "remote", enabled: true };
  const env = s.environment || s.headers || {};
  const form = document.createElement("form");
  form.className = "form";
  form.innerHTML = `
    <div class="field"><label>Name</label><input name="name" value="${esc(name || "")}" ${name ? "readonly" : ""} placeholder="calendar" required></div>
    <div class="field"><span class="field-label">Kind</span><div class="segmented">
      <button type="button" data-t="remote">Online service (URL)</button><button type="button" data-t="local">Program on the server</button></div></div>
    <div class="field" data-remote><label>Address</label><input name="url" value="${esc(s.url || "")}" placeholder="https://mcp.example.com/mcp"><small>The service gives you this address.</small></div>
    <div class="field" data-local><label>Command</label><input name="command" value="${esc(Array.isArray(s.command) ? s.command.join(" ") : s.command || "")}" placeholder="npx -y @some/mcp-server"></div>
    <div class="field"><span class="field-label" data-envlabel>Settings</span><div class="kvs" id="kvs"></div>
      <button type="button" class="btn btn-ghost btn-sm" data-addkv>${I("plus")} Add</button></div>`;
  let type = s.type === "local" || (!s.type && s.command) ? "local" : "remote";
  const kvs = form.querySelector("#kvs");
  const addKv = (k = "", v = "") => {
    const row = document.createElement("div");
    row.className = "kv-row";
    row.innerHTML = `<input placeholder="NAME" value="${esc(k)}"><input placeholder="value" value="${esc(v)}"><button type="button" class="icon-btn" aria-label="Remove">${I("x")}</button>`;
    row.querySelector("button").addEventListener("click", () => row.remove());
    kvs.appendChild(row);
  };
  Object.entries(env).forEach(([k, v]) => addKv(k, v));
  const setType = (t) => {
    type = t;
    form.querySelectorAll("[data-t]").forEach((b) => b.classList.toggle("is-active", b.dataset.t === t));
    form.querySelector("[data-local]").hidden = t !== "local";
    form.querySelector("[data-remote]").hidden = t !== "remote";
    form.querySelector("[data-envlabel]").textContent = t === "local" ? "Settings (environment variables)" : "Headers (e.g. Authorization)";
  };
  setType(type);
  form.addEventListener("click", (e) => {
    const b = e.target.closest("[data-t]");
    if (b) setType(b.dataset.t);
    if (e.target.closest("[data-addkv]")) addKv();
  });
  form.addEventListener("submit", (e) => e.preventDefault());
  modal.open({
    title: name ? `Connection “${name}”` : "Add a connection",
    body: form,
    actions: [
      { label: "Cancel" },
      {
        label: "Save",
        kind: "btn-primary",
        run: async () => {
          const fd = new FormData(form);
          const nm = String(fd.get("name") || "").trim();
          if (!nm) {
            toast("Give it a name.", { error: true });
            return false;
          }
          const pairs = {};
          kvs.querySelectorAll(".kv-row").forEach((r) => {
            const [k, v] = r.querySelectorAll("input");
            if (k.value.trim()) pairs[k.value.trim()] = v.value;
          });
          const entry = { type, enabled: s.enabled !== false };
          if (type === "local") {
            entry.command = String(fd.get("command") || "").trim().split(/\s+/).filter(Boolean);
            if (Object.keys(pairs).length) entry.environment = pairs;
          } else {
            entry.url = String(fd.get("url") || "").trim();
            if (Object.keys(pairs).length) entry.headers = pairs;
          }
          return saveMcp({ ...MCP, [nm]: entry }, name ? "Saved." : "Connection added.");
        },
      },
    ],
  });
}
$("#mcpReload").addEventListener("click", loadMcp);
$("#mcpSave").addEventListener("click", () => {
  let next;
  try {
    next = JSON.parse($("#mcpEditor").value || "{}");
  } catch (_) {
    return toast("Invalid JSON.", { error: true });
  }
  saveMcp(next);
});

/* ---- Version & updates ---- */
async function checkVersion(force = false) {
  if (!LIVE) return;
  let v;
  try {
    v = await api.get(`version${force ? "?refresh=1" : ""}`);
  } catch (_) {
    return;
  }
  state.version = v;
  $("#versionText").textContent =
    `Mav ${v.installed}` + (v.update_available ? ` — ${v.latest} is available` : v.latest ? " — up to date" : "");
  $("#updatePill").hidden = !v.update_available && !v.updating;
  $("#updatePillText").textContent = v.updating ? "Updating…" : `Update to ${v.latest}`;
  if (force && !v.update_available) toast(v.latest ? `You have the latest version (${v.installed}).` : "Could not check for updates right now.");
  return v;
}
$("#versionCheck").addEventListener("click", async () => {
  const v = await checkVersion(true);
  if (v && v.update_available) openUpdate();
});
$("#updatePill").addEventListener("click", () => openUpdate());

function openUpdate() {
  const v = state.version || {};
  if (v.updating) return followUpdate();
  modal.open({
    title: `Update to ${v.latest}`,
    body: `<p>You have <strong>${esc(v.installed)}</strong>. The update keeps your chats, memory, routines and settings; Mav is unavailable for a minute or two while it installs.</p>
      ${v.notes ? `<h3 class="sub">What's new</h3><div class="bubble release-notes">${mdToHtml(v.notes)}</div>` : ""}
      ${v.release_url ? `<small><a href="${esc(v.release_url)}" target="_blank" rel="noopener">Release page ↗</a></small>` : ""}`,
    actions: [
      { label: "Later" },
      {
        label: "Update now",
        kind: "btn-primary",
        run: async (btn) => {
          btn.disabled = true;
          try {
            await api.post("update", {});
          } catch (e) {
            btn.disabled = false;
            toast(e.message, { error: true });
            return false;
          }
          setTimeout(followUpdate, 50);
          return true;
        },
      },
    ],
  });
}

/* Follow the update: the server goes away while it reinstalls, then comes
   back with the new version — then reload the page. */
async function followUpdate() {
  const from = (state.version && state.version.installed) || "";
  const body = document.createElement("div");
  body.innerHTML = `<div class="thinking-row">${dots()} <span id="updStep">Starting the update…</span></div>
    <p class="hint" style="margin-top:.8rem">You can keep this page open; it reloads by itself when Mav is back.</p>`;
  modal.open({ title: "Updating Mav", body, actions: [{ label: "Hide" }] });
  $("#updatePill").hidden = false;
  $("#updatePillText").textContent = "Updating…";
  let seenDown = false;
  for (let i = 0; i < 200; i++) {
    await new Promise((r) => setTimeout(r, 3000));
    let st = null;
    try {
      st = await api.get("update/status");
    } catch (_) {
      seenDown = true;
      const el = $("#updStep");
      if (el) el.textContent = "Installing — Mav restarts…";
      continue;
    }
    const el = $("#updStep");
    if (el && st.steps && st.steps.length) el.textContent = st.steps[st.steps.length - 1];
    if (!st.running && (seenDown || st.installed !== from)) {
      if (st.installed !== from) {
        toast(`Mav updated to ${st.installed}. Reloading…`);
        setTimeout(() => location.reload(), 1500);
      } else {
        modal.close();
        toast("The update did not complete — see Settings → General → Advanced, or run: mav logs install", { error: true });
        checkVersion();
      }
      return;
    }
  }
}

/* ---- General → Advanced ---- */
function renderEngine(e) {
  if (!e) return;
  $("#engineDot").className = "dot " + (e.online ? "ok" : e.active ? "warn" : "off");
  $("#engineLabel").textContent = e.online ? "Assistant running" : e.active ? "Assistant starting…" : "Assistant stopped";
  $("#engineMeta").innerHTML = [
    ["Model", e.model || "—"],
    ["Engine", e.version ? `opencode ${e.version}` : "—"],
    ["Helpers", e.agents ?? "—"],
    ["Connections", e.mcp ?? "—"],
    ["Service", e.unit || "—"],
    ["Memory", (state.status && state.status.memory_backend) || "—"],
  ]
    .map(([k, v]) => `<div><span>${esc(k)}</span><span>${esc(v)}</span></div>`)
    .join("");
}
async function loadAdvanced() {
  if (!LIVE) return renderEngine({ unit: "demo", model: "—" });
  try {
    renderEngine(await api.get("config/engine"));
  } catch (_) {
    renderEngine({ unit: "?" });
  }
  try {
    const c = await api.get("config");
    $("#advPaths").innerHTML = [
      ["Engine config", c.config_path],
      ["Custom instructions", c.agents && c.agents.path],
      ["Helpers folder", AGENT_DIR || (c.config_path || "").replace(/opencode\.json$/, "agent")],
    ]
      .map(([k, v]) => `<div><span>${esc(k)}</span><span>${esc(v || "—")}</span></div>`)
      .join("");
  } catch (_) {}
  loadMcp();
}
$("#engineRefresh").addEventListener("click", loadAdvanced);
$("#engineRestart").addEventListener("click", restartAssistant);
setInterval(() => {
  if (LIVE && state.view === "settings" && currentSettingsTab() === "general" && $("#advanced").open && !document.hidden)
    api.get("config/engine").then(renderEngine).catch(() => {});
}, 15000);

/* ================================================================
   14. Voice (dictation + read aloud)
   ================================================================ */
const S = { speak: store.get("mav-speak") === "1", recog: null };
(() => {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return;
  const rec = new SR();
  rec.lang = navigator.language || "en-US";
  rec.interimResults = false;
  rec.continuous = false;
  S.recog = rec;
})();
function startDictation(btn, sel) {
  if (!S.recog) return toast("Dictation is not supported by this browser.");
  const input = $(sel);
  S.recog.onresult = (e) => {
    input.value = (input.value + " " + e.results[0][0].transcript).trim();
    autoGrow(input);
  };
  S.recog.onend = () => btn.classList.remove("is-on");
  try {
    S.recog.start();
    btn.classList.add("is-on");
  } catch (_) {
    btn.classList.remove("is-on");
  }
}
$("#chatMic").addEventListener("click", () => startDictation($("#chatMic"), "#chatInput"));
function speak(text, force = false) {
  if (!text || !("speechSynthesis" in window) || (!S.speak && !force)) return;
  const plain = text.replace(/```[\s\S]*?```/g, "").replace(/[*_`#>|]/g, "").slice(0, 900);
  const u = new SpeechSynthesisUtterance(plain);
  u.lang = navigator.language || "en-US";
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
}
function setSwitch(el, on) {
  el.setAttribute("aria-checked", on ? "true" : "false");
}
setSwitch($("#voiceSwitch"), S.speak);
$("#voiceSwitch").addEventListener("click", () => {
  S.speak = !S.speak;
  store.set("mav-speak", S.speak ? "1" : null);
  setSwitch($("#voiceSwitch"), S.speak);
  if (!S.speak && "speechSynthesis" in window) speechSynthesis.cancel();
});

/* ================================================================
   15. Notifications (Web Push)
   ================================================================ */
const N = { enabled: false };
function urlB64ToUint8Array(b64) {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}
function setNotifyUi(on) {
  N.enabled = on;
  $("#notifyToggle").classList.toggle("is-on", on);
  $("#notifyToggle").title = on ? "Notifications on" : "Turn on notifications";
  setSwitch($("#pushSwitch"), on);
}
async function togglePush() {
  if (!("Notification" in window) || !("serviceWorker" in navigator))
    return toast("Notifications need HTTPS and a recent browser.");
  if (!needLive()) return;
  if (N.enabled) {
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        await api.post("push/unsubscribe", { endpoint: sub.endpoint });
        await sub.unsubscribe();
      }
    } catch (_) {}
    setNotifyUi(false);
    return toast("Notifications off.");
  }
  try {
    const perm = await Notification.requestPermission();
    if (perm !== "granted") return toast("Permission denied by the browser.", { error: true });
    const { key } = await api.get("push/key");
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlB64ToUint8Array(key) });
    await api.post("push/subscribe", sub.toJSON());
    setNotifyUi(true);
    toast("Notifications on.", { action: { label: "Send a test", run: () => $("#pushTest").click() } });
  } catch (_) {
    toast("Could not turn notifications on.", { error: true });
  }
}
$("#notifyToggle").addEventListener("click", togglePush);
$("#pushSwitch").addEventListener("click", togglePush);
$("#pushTest").addEventListener("click", async () => {
  if (!N.enabled) return toast("Turn notifications on first.");
  try {
    const r = await api.post("push/test", {});
    toast(r.sent ? "Test sent." : "No device subscribed.");
  } catch (_) {
    toast("Failed to send.", { error: true });
  }
});
(async () => {
  try {
    if (!("serviceWorker" in navigator) || !("Notification" in window) || Notification.permission !== "granted") return;
    const reg = await navigator.serviceWorker.ready;
    if (await reg.pushManager.getSubscription()) setNotifyUi(true);
  } catch (_) {}
})();
/* When an answer finishes while the tab is in the background. */
function notifyLocal(title, body) {
  try {
    if (Notification.permission === "granted")
      new Notification(`${title} answered`, { body: body.replace(/[*_`#>]/g, "").slice(0, 140), icon: "icons/icon-192.png" });
  } catch (_) {}
}

async function openNotifById(id) {
  if (!id || !LIVE) return;
  let n = null;
  try {
    n = (await api.get(`notification?id=${encodeURIComponent(id)}`)).notification;
  } catch (_) {}
  if (!n) return toast("Alert not found.");
  const m = (n.link || "").match(/#chat\/([^&?#]+)/);
  if (m) return tellMeMore(n);
  newChat();
  send(`Tell me more about this alert you sent me.\n\nTitle: ${n.title || ""}\nDetails: ${n.body || ""}\n\nWhat changed, why it matters, and what I could do. Be concrete and brief.`);
}

/* ================================================================
   16. Search & commands (⌘K)
   ================================================================ */
const palette = $("#palette");
let palItems = [];
let palFocus = 0;
const PAL_ACTIONS = [
  { text: "New chat", ico: "edit", run: () => newChat() },
  { text: "New routine", ico: "bolt", run: () => editRoutine(null) },
  { text: "Keep an eye on a page, price or topic", ico: "eye", run: () => go("routines", "watch") },
  { text: "Tell Mav something to remember", ico: "brain", run: () => { go("memory"); $("#factInput").focus(); } },
  { text: "Change the model", ico: "cpu", run: () => go("settings", "model") },
  { text: "Custom instructions", ico: "edit", run: () => go("settings", "instructions") },
  { text: "Create a helper", ico: "user", run: () => { go("settings", "helpers"); editAgent(null); } },
  { text: "Add a connection", ico: "plug", run: () => { go("settings", "connections"); editMcp(null); } },
  { text: "Restart assistant", ico: "power", run: () => restartAssistant() },
  { text: "Check for updates", ico: "download", run: () => { go("settings", "general"); checkVersion(true).then((v) => v && v.update_available && openUpdate()); } },
  { text: "Toggle dark mode", ico: "moon", run: () => $("#themeToggle").click() },
  { text: "Keyboard shortcuts", ico: "key", run: () => showHelp() },
  { text: "Routines", ico: "arrow", run: () => go("routines") },
  { text: "Memory", ico: "arrow", run: () => go("memory") },
  { text: "Settings", ico: "arrow", run: () => go("settings") },
];
function openPalette() {
  palette.hidden = false;
  $("#paletteInput").value = "";
  renderPalette("");
  $("#paletteInput").focus();
}
function closePalette() {
  palette.hidden = true;
}
function renderPalette(q) {
  const ql = q.toLowerCase();
  const items = [];
  state.convs
    .filter((c) => !q || c.title.toLowerCase().includes(ql))
    .slice(0, q ? 8 : 5)
    .forEach((c) => items.push({ group: "Chats", text: c.title, ico: c.routine ? "bolt" : "chat", kind: fmtRel(c.updated), run: () => openChat(c.id) }));
  state.agents
    .filter((a) => q && (a.includes(ql) || agentDisplay(a).toLowerCase().includes(ql)))
    .forEach((a) => items.push({ group: "Helpers", text: `Talk to ${agentDisplay(a)}`, ico: "user", run: () => newChat(a) }));
  PAL_ACTIONS.filter((a) => !q || a.text.toLowerCase().includes(ql)).forEach((a) => items.push({ group: "Actions", ...a }));
  palItems = items;
  palFocus = 0;
  drawPalette();
  if (q && LIVE) searchPalette(q);
}
let palTimer = null;
function searchPalette(q) {
  clearTimeout(palTimer);
  palTimer = setTimeout(async () => {
    try {
      const r = await api.get(`search?q=${encodeURIComponent(q)}`);
      if ($("#paletteInput").value.trim() !== q) return;
      (r.facts || []).slice(0, 4).forEach((f) => palItems.push({ group: "Memory", text: f.fact, ico: "brain", run: () => go("memory") }));
      (r.conversations || []).slice(0, 4).forEach((c) => palItems.push({ group: "Memory", text: c.question, ico: "clock", kind: fmtRel(c.ts), run: () => go("memory") }));
      drawPalette();
    } catch (_) {}
  }, 220);
}
function drawPalette() {
  if (!palItems.length) {
    $("#paletteResults").innerHTML = `<div class="pal-empty">Nothing found — press Enter to ask Mav.</div>`;
    return;
  }
  let g = null;
  $("#paletteResults").innerHTML = palItems
    .map((it, i) => {
      const head = it.group !== g ? `<div class="pal-group">${esc(it.group)}</div>` : "";
      g = it.group;
      return `${head}<button class="pal-item ${i === palFocus ? "is-focus" : ""}" data-pal="${i}">${I(it.ico || "arrow")}<span class="pal-text">${esc(it.text)}</span>${it.kind ? `<span class="pal-kind">${esc(it.kind)}</span>` : ""}</button>`;
    })
    .join("");
  const f = $(".pal-item.is-focus");
  if (f) f.scrollIntoView({ block: "nearest" });
}
function runPal(i) {
  const it = palItems[i];
  const q = $("#paletteInput").value.trim();
  closePalette();
  if (it) it.run();
  else if (q) {
    newChat();
    send(q);
  }
}
$("#paletteInput").addEventListener("input", (e) => renderPalette(e.target.value.trim()));
$("#paletteInput").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (!palItems.length) return;
    palFocus = (palFocus + (e.key === "ArrowDown" ? 1 : -1) + palItems.length) % palItems.length;
    drawPalette();
  } else if (e.key === "Enter") {
    e.preventDefault();
    runPal(palItems.length ? palFocus : -1);
  }
});
$("#paletteResults").addEventListener("click", (e) => {
  const b = e.target.closest("[data-pal]");
  if (b) runPal(Number(b.dataset.pal));
});
palette.addEventListener("mousedown", (e) => {
  if (e.target === palette) closePalette();
});
$("#searchOpen").addEventListener("click", openPalette);

function showHelp() {
  const rows = [
    ["⌘/Ctrl K", "Search & commands"],
    ["Alt N", "New chat"],
    ["/", "Focus the message box"],
    ["Enter · Shift+Enter", "Send · new line"],
    ["Esc", "Stop the answer · close"],
    ["Alt ↑ / ↓", "Previous / next chat"],
  ];
  modal.open({
    title: "Shortcuts & commands",
    size: "small",
    body: `<div class="kvs">${rows.map(([k, v]) => `<div class="setting-row"><span>${esc(v)}</span><kbd>${esc(k)}</kbd></div>`).join("")}</div>
      <h3 class="sub" style="margin-top:1rem">Type in the message box</h3>
      <div class="kvs">${SLASH.map((s) => `<div class="setting-row"><code>${esc(s.cmd)}${s.arg ? " " + esc(s.arg) : ""}</code><span>${esc(s.desc)}</span></div>`).join("")}</div>`,
    actions: [{ label: "Close", kind: "btn-primary" }],
  });
}

/* Global shortcuts */
window.addEventListener("keydown", (e) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    palette.hidden ? openPalette() : closePalette();
    return;
  }
  if (e.altKey && e.code === "KeyN") {
    e.preventDefault();
    newChat();
    return;
  }
  if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown") && state.convs.length) {
    e.preventDefault();
    const i = state.convs.findIndex((c) => c.id === state.chat.id);
    const j = Math.max(0, Math.min(state.convs.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)));
    openChat(state.convs[j].id);
    return;
  }
  if (e.key === "Escape") {
    if (!palette.hidden) return closePalette();
    if (!$("#modal").hidden) return modal.close();
    if (!$("#agentMenu").hidden) return closeAgentMenu();
    if (document.body.classList.contains("drawer-open")) return closeDrawer();
    if (state.streaming) {
      stopStreaming();
      toast("Stopped.");
    }
    return;
  }
  if (!typing && e.key === "/" && !e.metaKey && !e.ctrlKey) {
    e.preventDefault();
    if (state.view !== "chat") go("chat");
    chatInput.focus();
  }
  if (!typing && e.key === "?") showHelp();
});

/* ================================================================
   17. Loading (live or demo)
   ================================================================ */
const DEMO = {
  agents: ["assistant", "researcher", "writer", "planner", "money"],
  info: {
    assistant: { description: "Your everyday assistant — answers directly, and calls in a helper when it helps" },
    researcher: { description: "Looks things up on the web, checks facts and compares options" },
    writer: { description: "Drafts and polishes emails, messages, posts and letters" },
    planner: { description: "Organises days, trips, projects and to-do lists" },
    money: { description: "Budgets, purchases, subscriptions and comparing offers" },
  },
  jobs: [
    { name: "Morning briefing", prompt: "Weather where I live and 3 headlines.", time: "07:30", days: ALL_DAYS, agent: "researcher", enabled: true },
    { name: "Weekly meal plan", prompt: "5 simple dinners and a shopping list.", time: "10:00", days: ["sun"], agent: "planner", enabled: true },
  ],
  inbox: [
    { id: 0, topic: "routine", title: "🔁 Morning briefing", body: "Sunny, 24°C — no umbrella needed. Headlines: …", ts: Date.now() / 1000 - 3600 },
    { id: 0, topic: "watch", title: "🏷️ Price change", body: "Price dropped: 129 → 99 EUR (-23%).", ts: Date.now() / 1000 - 8000 },
  ],
  presets: [
    { id: "anthropic", label: "Anthropic", hint: "Claude models. Needs an API key.", native: true, key: "required", model: "claude-sonnet-4-5" },
    { id: "openai", label: "OpenAI", hint: "GPT models. Needs an API key.", native: true, key: "required", model: "gpt-4o" },
    { id: "ollama", label: "Ollama (local)", hint: "Models on your own machine.", native: false, key: "optional", base: "http://localhost:11434/v1", model: "llama3.1" },
    { id: "custom", label: "Custom endpoint", hint: "Any OpenAI-compatible API.", native: false, key: "optional", base: "", model: "" },
  ],
};

async function loadAgentsList() {
  if (!LIVE) return;
  try {
    const d = await api.get("agents");
    state.agents = d.agents || [];
    state.agentInfo = d.details || {};
    state.defaultAgent = d.default || state.agents[0] || "";
    if (state.preferredAgent && !state.agents.includes(state.preferredAgent)) state.preferredAgent = "";
  } catch (_) {}
  renderAgentPills();
  if (!state.chat.messages.length && state.view === "chat") renderThread();
  renderConvList();
}

async function refreshStatus() {
  if (!LIVE) return;
  try {
    renderStatus(await api.get("status"));
  } catch (_) {}
}

async function boot() {
  hydrateIcons();
  let status = null;
  try {
    status = await api.get("status");
  } catch (_) {}
  if (!status) return enterDemo();
  LIVE = true;
  document.body.dataset.mode = "live";
  renderStatus(status);
  await Promise.allSettled([loadAgentsList(), loadConvs(), loadRoutines(), checkVersion()]);
  route();
  if (!state.chat.id) renderThread();
  const notif = new URLSearchParams(location.search).get("notif");
  if (notif) {
    history.replaceState(null, "", location.pathname + location.hash);
    openNotifById(notif);
  }
}

function enterDemo() {
  LIVE = false;
  document.body.dataset.mode = "mock";
  state.agents = DEMO.agents;
  state.agentInfo = DEMO.info;
  state.defaultAgent = "assistant";
  state.jobs = DEMO.jobs;
  state.inbox = DEMO.inbox;
  state.convs = [
    { id: "demo1", title: "Weekend in Lisbon", agent: "planner", updated: Date.now() - 600e3 },
    { id: "demo2", title: "Routine · Morning briefing", agent: "researcher", routine: true, updated: Date.now() - 3600e3 },
    { id: "demo3", title: "Reply to the landlord", agent: "writer", updated: Date.now() - 2 * 86400e3 },
  ];
  state.memory = { conversations: [], facts: [{ id: 1, fact: "Lives in Lyon, vegetarian", ts: Date.now() / 1000 }], preferences: [], backend: "demo" };
  renderStatus({ mode: "mock" });
  renderAgentPills();
  renderConvList();
  renderRoutines();
  route();
  if (!state.chat.id) renderThread();
}

/* Look for a new version every 6 hours. */
setInterval(() => LIVE && !document.hidden && checkVersion(), 6 * 3600e3);

/* Periodic refresh (paused while the tab is hidden). */
setInterval(() => {
  if (!LIVE || document.hidden) return;
  refreshStatus();
  if (state.view === "chat" && !state.chat.id) refreshInbox();
}, 30000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && LIVE) {
    refreshStatus();
    loadConvs();
  }
});

/* ================================================================
   18. PWA: service worker + install banner
   ================================================================ */
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("sw.js")
      .then((reg) => {
        reg.addEventListener("updatefound", () => {
          const sw = reg.installing;
          if (sw)
            sw.addEventListener("statechange", () => {
              if (sw.state === "installed" && navigator.serviceWorker.controller) sw.postMessage("skip-waiting");
            });
        });
      })
      .catch(() => {});
    let reloaded = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      // Never reload in the middle of an answer.
      if (reloaded || state.streaming) return;
      reloaded = true;
      location.reload();
    });
    navigator.serviceWorker.addEventListener("message", (e) => {
      if (e.data && e.data.type === "open-notif" && e.data.id) openNotifById(String(e.data.id));
      if (e.data && e.data.type === "open-chat" && e.data.id) openChat(String(e.data.id));
    });
  });
}
let deferredPrompt = null;
const banner = $("#installBanner");
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferredPrompt = e;
  if (store.get("mav-install-dismissed") !== "1") banner.hidden = false;
});
$("#installBtn").addEventListener("click", async () => {
  if (!deferredPrompt) {
    banner.hidden = true;
    store.set("mav-install-dismissed", "1");
    return;
  }
  deferredPrompt.prompt();
  try {
    await deferredPrompt.userChoice;
  } catch (_) {}
  deferredPrompt = null;
  banner.hidden = true;
});
$("#installClose").addEventListener("click", () => {
  banner.hidden = true;
  store.set("mav-install-dismissed", "1");
});
window.addEventListener("appinstalled", () => (banner.hidden = true));
if (/iphone|ipad|ipod/i.test(navigator.userAgent) && !(window.matchMedia("(display-mode: standalone)").matches || navigator.standalone) && store.get("mav-install-dismissed") !== "1") {
  banner.querySelector(".install-text span").textContent = "Tap Share, then “Add to Home Screen”.";
  $("#installBtn").textContent = "Got it";
  banner.hidden = false;
}

boot();
