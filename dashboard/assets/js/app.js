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
  square:
    '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>',
  pin: '<path d="M12 17v5M9 3h6l-1 6 4 4H6l4-4z"/>',
  sparkle:
    '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
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
  calendar:
    '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  plug: '<path d="M9 2v6M15 2v6M6 8h12v3a6 6 0 0 1-12 0zM12 17v5"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
  globe:
    '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M17 6l3 3"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  tool: '<path d="M14.7 6.3a4 4 0 0 0 5 5L21 13l-8 8-3-3 8-8-1.3-1.3a4 4 0 0 0-5-5L14 2z"/>',
  power: '<path d="M12 2v10M6.3 6.3a8 8 0 1 0 11.4 0"/>',
  volume:
    '<path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16 9a4 4 0 0 1 0 6M19 6a8 8 0 0 1 0 12"/>',
  tag: '<path d="M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9z"/><circle cx="7.5" cy="7.5" r="1.5"/>',
  news: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 8h10M7 12h10M7 16h6"/>',
  "bell-off":
    '<path d="M6 8a6 6 0 0 1 9.3-5M18 8c0 7 3 8 3 8H7M4 4l16 16M10 20a2 2 0 0 0 4 0"/>',
  gamepad:
    '<rect x="2" y="7" width="20" height="10" rx="4"/><path d="M7 10v4M5 12h4M15 11h.01M18 13h.01"/>',
  music:
    '<path d="M9 18V6l10-2v12"/><circle cx="6" cy="18" r="3"/><circle cx="16" cy="16" r="3"/>',
  coffee:
    '<path d="M4 8h13v5a5 5 0 0 1-10 0zM17 9h1a3 3 0 0 1 0 6h-1M6 3v2M10 3v2M14 3v2"/>',
  book: '<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 19a2 2 0 0 1 2-2h13"/>',
  send: '<path d="M22 2 11 13M22 2l-7 20-4-9-9-4z"/>',
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
  return new Date(ms).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
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
  return new Date(ms).toLocaleDateString([], {
    day: "numeric",
    month: "short",
  });
}
function dayGroup(ts) {
  const ms = toMs(ts);
  if (!ms) return "Older";
  const d = new Date(ms);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff =
    (today - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000;
  if (diff <= 0) return "Today";
  if (diff <= 1) return "Yesterday";
  if (diff <= 7) return "Previous 7 days";
  if (diff <= 30) return "Previous 30 days";
  return "Older";
}
const DAY_NAMES = {
  mon: "Mon",
  tue: "Tue",
  wed: "Wed",
  thu: "Thu",
  fri: "Fri",
  sat: "Sat",
  sun: "Sun",
};
const ALL_DAYS = Object.keys(DAY_NAMES);
function fmtDays(days) {
  if (!days || !days.length || days.length === 7) return "every day";
  const wk = ["mon", "tue", "wed", "thu", "fri"];
  if (days.length === 5 && wk.every((d) => days.includes(d))) return "weekdays";
  if (days.length === 2 && days.includes("sat") && days.includes("sun"))
    return "weekends";
  return days.map((d) => DAY_NAMES[d] || d).join(", ");
}

/* Agent identity: a stable colour + initial per agent name. */
function agentColor(name) {
  // Brand v2 helper palette: same lightness and saturation, distinct hues,
  // readable with white initials in light and dark themes.
  const fixed = {
    assistant: "#0f7a5c", // emerald — the brand
    researcher: "#3b5bdb", // indigo
    writer: "#b4407a", // rose
    planner: "#c26a1c", // amber-brown
    money: "#2f8a3a", // green
  };
  if (fixed[name]) return fixed[name];
  let h = 0;
  for (const c of String(name || "mav")) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h} 55% 42%)`;
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
  // The same message twice in a row (e.g. a caller re-reporting an error that
  // was already shown with its action) is shown once.
  if ([...box.children].some((t) => t.firstChild && t.firstChild.textContent === msg))
    return () => {};
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
      const f =
        b.querySelector("input, textarea, select") ||
        foot.querySelector(".btn-primary");
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
        {
          label: "Cancel",
          run: () => {
            done = true;
            resolve(false);
          },
        },
        {
          label: okLabel,
          kind: danger ? "btn-danger" : "btn-primary",
          run: () => {
            done = true;
            resolve(true);
          },
        },
      ],
      onClose: () => {
        if (!done) resolve(false);
      },
    });
  });
}

/* API */
let LIVE = false;
const api = {
  async get(path) {
    const r = await fetch(`/api/${path}`, {
      headers: { Accept: "application/json" },
    });
    if (r.status === 401 && LIVE) showAuthGate("login");
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
    if (r.status === 401 && data && data.auth && LIVE) showAuthGate("login");
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
  chat: {
    id: null,
    title: "",
    agent: "",
    pinned: false,
    routine: false,
    messages: [],
  },
  streaming: false,
  pendingFiles: [],
  jobs: [],
  memory: { conversations: [], facts: [], preferences: [] },
  inbox: [],
  drafts: [],
  proactivity: "normal",
  interests: { interests: [], autonomy: "suggest", selfinit: null },
  view: "chat",
};

function currentAgent() {
  return (
    state.chat.agent ||
    state.preferredAgent ||
    state.defaultAgent ||
    state.agents[0] ||
    ""
  );
}
function agentDesc(name) {
  return (state.agentInfo[name] && state.agentInfo[name].description) || "";
}

/* ================================================================
   3. Navigation (hash routing: #chat/<id>, #routines, #settings/model…)
   ================================================================ */
const VIEW_TITLES = {
  chat: "Mav",
  routines: "Routines",
  memory: "Memory",
  debates: "Debates",
  settings: "Settings",
};

function go(view, sub, { push = true } = {}) {
  if (!$(`#view-${view}`)) view = "chat";
  state.view = view;
  $$(".nav-item").forEach((b) =>
    b.classList.toggle("is-active", b.dataset.view === view),
  );
  $$(".view").forEach((v) =>
    v.classList.toggle("is-active", v.id === `view-${view}`),
  );
  $("#topbarTitle").textContent =
    view === "chat" ? state.chat.title || "Mav" : VIEW_TITLES[view];
  closeDrawer();
  if (view === "settings") openSettingsTab(sub || currentSettingsTab());
  if (view === "memory") loadMemory();
  if (view === "routines") openRoutinesTab(sub || currentRoutinesTab());
  if (view === "debates") loadDebates();
  if (view === "chat" && !state.chat.id) refreshInbox();
  if (push) {
    const h =
      view === "chat"
        ? state.chat.id
          ? `#chat/${state.chat.id}`
          : "#"
        : sub
          ? `#${view}/${sub}`
          : `#${view}`;
    if ((location.hash || "#") !== h)
      history.pushState(null, "", h === "#" ? location.pathname : h);
  }
  renderConvList();
}

window.addEventListener("popstate", () => route());
function route() {
  const [view, arg] = location.hash.replace(/^#/, "").split("/");
  if (!view || view === "chat") {
    if (arg && arg !== state.chat.id)
      openChat(decodeURIComponent(arg), { push: false });
    else if (!arg && state.chat.id) newChat(null, { push: false });
    else {
      go("chat", null, { push: false });
      updateChatActions(); // nothing to pin, export or delete yet
    }
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
$$(".nav-item").forEach((b) =>
  b.addEventListener("click", () => go(b.dataset.view)),
);

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
  if (mode === "light" || mode === "dark")
    document.documentElement.dataset.theme = mode;
  else delete document.documentElement.dataset.theme;
  store.set("mav-theme", mode === "auto" ? null : mode);
  const dark =
    mode === "dark" ||
    (mode !== "light" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);
  $("#themeToggle").innerHTML = I(dark ? "sun" : "moon");
  $$("#themeSeg button").forEach((b) =>
    b.classList.toggle("is-active", b.dataset.themeSet === (mode || "auto")),
  );
}
$("#themeToggle").addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(dark ? "light" : "dark");
});
$$("#themeSeg button").forEach((b) =>
  b.addEventListener("click", () => applyTheme(b.dataset.themeSet)),
);
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
  if (!menu.hidden && agentMenuCtx && agentMenuCtx.anchor === anchor)
    return closeAgentMenu();
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
  if (
    e.target.closest("#agentMenu") ||
    (agentMenuCtx && agentMenuCtx.anchor.contains(e.target))
  )
    return;
  closeAgentMenu();
});
["#chatAgent", "#composerAgent"].forEach((s) =>
  $(s).addEventListener("click", (e) =>
    openAgentMenu(e.currentTarget, currentAgent(), (a) => switchAgent(a)),
  ),
);

async function switchAgent(name) {
  if (name === currentAgent()) return;
  state.chat.agent = name;
  state.preferredAgent = name;
  store.set("mav-agent", name);
  renderAgentPills();
  if (state.chat.id && LIVE) {
    api
      .post("session/agent", { id: state.chat.id, agent: name })
      .catch(() => {});
    const c = state.convs.find((x) => x.id === state.chat.id);
    if (c) c.agent = name;
    renderConvList();
  }
  if (state.chat.messages.length)
    appendDivider(
      `Now talking to <strong>${esc(agentDisplay(name))}</strong>`,
      name,
    );
  else renderThread();
}

/* ================================================================
   5. Chats (sidebar)
   ================================================================ */
function renderConvList() {
  const box = $("#convList");
  const q = ($("#convFilter").value || "").trim().toLowerCase();
  const list = state.convs.filter(
    (c) => !q || c.title.toLowerCase().includes(q),
  );
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
    const busy = isStreaming(c.id) || c.running;
    html += `<div class="conv-item ${active ? "is-active" : ""} ${c._new ? "is-new" : ""}" data-id="${esc(c.id)}" role="button" tabindex="0" title="${esc(c.title)} · ${esc(agentDisplay(c.agent || state.defaultAgent))}">
      ${c.routine ? `<span class="agent-av sm routine-av">${I("bolt")}</span>` : agentAvatar(c.agent || state.defaultAgent, "sm")}
      <span class="ctitle">${esc(c.title)}</span>
      ${busy ? `<span class="cbusy" title="Working…">${dots()}</span>` : ""}
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
  if (e.key === "Enter" && e.target.classList.contains("conv-item"))
    openChat(e.target.dataset.id);
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
  if (
    cur &&
    cur.title !== state.chat.title &&
    $("#chatTitle").contentEditable !== "true"
  )
    setChatTitle(cur.title);
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
  const has = !!state.chat.id;
  ["#pinBtn", "#summaryBtn", "#exportBtn", "#deleteChatBtn"].forEach(
    (s) => ($(s).hidden = !has),
  );
  $("#pinBtn").classList.toggle("is-on", !!state.chat.pinned);
  $("#pinBtn").title = state.chat.pinned ? "Unpin" : "Pin";
}

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
function lowerFirst(s) {
  return s ? s[0].toLowerCase() + s.slice(1) : s;
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
  if (force || nearBottom()) messagesEl.scrollTop = messagesEl.scrollHeight;
}

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

  attachStream(st, qs, { wasNew, prompt: text, routineDraft });
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
      st.el.querySelector(".bubble").innerHTML = mdToHtml(st.reply.text || "");
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
  refreshStreamingUI();
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
    .map(
      (r) =>
        "<tr>" +
        header
          .map(
            (_, i) => `<td${cls(i)}>${inline(r[i] == null ? "" : r[i])}</td>`,
          )
          .join("") +
        "</tr>",
    )
    .join("");
  return `<div class="md-table-wrap"><table class="md-table"><thead><tr>${th}</tr></thead><tbody>${rows}</tbody></table></div>`;
}
/* ---- Rich directives: [[chart:SYMBOL:PERIOD]] and [[file:PATH]] ----
   Rendered on a line of their own. The chart pulls /api/chart (Yahoo
   proxy), the file becomes a download card to /api/download. */
const CHART_PERIODS = ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"];

function chartBlock(spec) {
  const parts = String(spec).split(":");
  const sym = (parts[0] || "").trim();
  let period = (parts[1] || "1mo").trim().toLowerCase();
  if (!CHART_PERIODS.includes(period)) period = "1mo";
  if (!sym) return "";
  const uid = "ch" + Math.random().toString(36).slice(2, 9);
  return `<figure class="md-chart" id="${uid}" data-symbol="${esc(sym)}" data-range="${esc(period)}">
    <div class="md-chart-head"><span class="md-chart-name">${esc(sym)}</span><span class="md-chart-quote"></span></div>
    <div class="md-chart-plot"><div class="md-chart-load">Loading chart…</div></div>
    <figcaption class="md-chart-foot"><span class="md-chart-range"></span><button type="button" class="chart-refresh" title="Refresh">${I("refresh")}</button></figcaption>
  </figure>`;
}

function fileCardHtml(raw) {
  const name = String(raw).trim();
  const base = name.split(/[\\/]/).pop() || name;
  const ext = (base.match(/\.([a-z0-9]+)$/i) || [null, ""])[1].toLowerCase();
  const url = "/api/download?path=" + encodeURIComponent(name);
  return `<a class="md-file" href="${escapeHtml(url)}" download="${escapeHtml(base)}">
    <span class="md-file-ico">${I("download")}</span>
    <span class="md-file-main"><strong>${esc(base)}</strong><span>${ext ? ext.toUpperCase() + " · " : ""}Click to download</span></span>
  </a>`;
}

function fmtChartNum(v, cur) {
  if (v == null || isNaN(v)) return "—";
  const abs = Math.abs(v);
  const digits = abs >= 1000 ? 0 : abs >= 1 ? 2 : 4;
  const n = Number(v).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
  return cur ? `${n} ${cur}` : n;
}

function sparkSvg(closes, positive, uid) {
  const w = 640,
    h = 180,
    pad = 10;
  const n = closes.length;
  if (n < 2) return "";
  let lo = Math.min(...closes),
    hi = Math.max(...closes);
  if (hi === lo) hi = lo + 1;
  const x = (i) => pad + (i * (w - 2 * pad)) / (n - 1);
  const y = (v) => h - pad - ((v - lo) / (hi - lo)) * (h - 2 * pad);
  const pts = closes.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  const line = "M" + pts.join(" L");
  const area = `${line} L${x(n - 1).toFixed(1)},${(h - pad).toFixed(1)} L${x(0).toFixed(1)},${(h - pad).toFixed(1)} Z`;
  const col = positive ? "var(--ok)" : "var(--danger)";
  const gid = (uid || "ch") + "g";
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" class="md-chart-svg" aria-hidden="true">
    <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${col}" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="${col}" stop-opacity="0"/>
    </linearGradient></defs>
    <path d="${area}" fill="url(#${gid})"/>
    <path d="${line}" fill="none" stroke="${col}" stroke-width="2" vector-effect="non-scaling-stroke"/>
  </svg>`;
}

async function loadChart(fig) {
  const sym = fig.dataset.symbol,
    range = fig.dataset.range;
  const plot = fig.querySelector(".md-chart-plot");
  const quote = fig.querySelector(".md-chart-quote");
  const foot = fig.querySelector(".md-chart-range");
  try {
    const r = await fetch(
      `/api/chart?symbol=${encodeURIComponent(sym)}&range=${encodeURIComponent(range)}`,
      { headers: { Accept: "application/json" } },
    );
    if (!r.ok) throw new Error("no data");
    const d = await r.json();
    if (!d.series || d.series.length < 2) throw new Error("no series");
    const up = (d.range_pct || 0) >= 0;
    plot.innerHTML = sparkSvg(d.series, up, fig.id);
    const chg = d.range_pct != null ? d.range_pct : 0;
    quote.innerHTML = `<span class="md-chart-price">${esc(fmtChartNum(d.price, d.currency))}</span><span class="md-chart-chg ${up ? "up" : "down"}">${up ? "+" : ""}${chg.toFixed(2)}%</span>`;
    fig.querySelector(".md-chart-name").textContent = d.name || sym;
    foot.textContent = `${range} · ${d.symbol || sym}`;
    fig.classList.toggle("is-up", up);
    fig.classList.toggle("is-down", !up);
  } catch (_) {
    plot.innerHTML = `<div class="md-chart-load">Chart unavailable</div>`;
  }
}

function hydrateCharts(root = document) {
  $$(".md-chart:not([data-loaded])", root).forEach((fig) => {
    fig.dataset.loaded = "1";
    loadChart(fig);
  });
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
  t = t.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
  );
  t = t.replace(
    /(^|[\s(])(https?:\/\/[^\s<)]+)/g,
    '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>',
  );
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
    while (j < lines.length && /^\s*\|.*\|\s*$/.test(lines[j]))
      block.push(lines[j++]);
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
      m = line.match(/^\[\[chart:([^\]\s]+)\]\]$/i);
      if (m) {
        flush();
        out += chartBlock(m[1]);
        i++;
        continue;
      }
      m = line.match(/^\[\[(?:file|download):(.+?)\]\]$/i);
      if (m) {
        flush();
        out += fileCardHtml(m[1].trim());
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
        while (j < lines.length && /^\s*>\s?/.test(lines[j]))
          inner.push(lines[j++].replace(/^\s*>\s?/, ""));
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
          items.push({
            indent: mm[1].replace(/\t/g, "    ").length,
            ordered: /^\d/.test(mm[2]),
            text: mm[3],
          });
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
  return renderBlocks(text.split("\n")).replace(
    /\u0000CODE(\d+)\u0000/g,
    (_, i) => codeBlocks[Number(i)] || "",
  );
}
function renderList(items) {
  const root = { children: [] };
  const stack = [{ indent: -1, node: root }];
  for (const it of items) {
    while (stack.length > 1 && it.indent <= stack[stack.length - 1].indent)
      stack.pop();
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
        const body = task
          ? `${task[1] === " " ? "☐" : "☑"} ${inline(task[2])}`
          : inline(txt);
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
  $("#onboard").hidden = !(
    st.mode === "live" && st.provider_configured === false
  );
  const dot = $("#engineChipDot");
  dot.className =
    "dot " + (st.mode !== "live" ? "warn" : st.agent_online ? "ok" : "off");
  const model = st.model ? st.model.split("/").pop() : "no model yet";
  $("#engineChipText").textContent =
    st.mode !== "live" ? "Demo" : st.agent_online ? model : "Assistant offline";
  $("#engineChip").title =
    st.mode !== "live"
      ? "Demo mode"
      : st.agent_online
        ? `Model: ${st.model || "—"}`
        : "The assistant is not responding";
}
$("#engineChip").addEventListener("click", () =>
  go(
    "settings",
    state.status && state.status.provider_configured === false
      ? "model"
      : state.status && !state.status.agent_online
        ? "general"
        : "model",
  ),
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
    send(
      "Tell me more about your latest report — what matters and what should I do?",
    );
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
  if (j.on_event) return "event";
  if (j.every_minutes) return "hours";
  if (j.days_of_month && j.days_of_month.length) return "monthly";
  if (j.last_day_of_month) return "monthly";
  return j.days && j.days.length && j.days.length < 7 ? "weekly" : "daily";
}
function jobWhen(j) {
  const mode = jobMode(j);
  if (mode === "event")
    return `when ${(j.on_event && j.on_event.kind) || "an event"} fires`;
  if (mode === "hours") {
    const h = Math.max(1, Math.round(Number(j.every_minutes) / 60));
    return h === 1 ? "every hour" : `every ${h} hours`;
  }
  if (mode === "monthly") {
    if (j.last_day_of_month) return `last day of the month at ${j.time}`;
    const dom = (j.days_of_month || []).join(", ");
    return `the ${dom} of the month at ${j.time}`;
  }
  return mode === "daily"
    ? `every day at ${j.time}`
    : `${fmtDays(j.days)} at ${j.time}`;
}
function currentRoutinesTab() {
  const a = $("[data-rtab].is-active");
  return a ? a.dataset.rtab : "routines";
}
function openRoutinesTab(tab) {
  if (!$(`#rpanel-${tab}`)) tab = "routines";
  $$("[data-rtab]").forEach((t) =>
    t.classList.toggle("is-active", t.dataset.rtab === tab),
  );
  $$(".rpanel").forEach((p) =>
    p.classList.toggle("is-active", p.id === `rpanel-${tab}`),
  );
  if (tab === "watch") loadWatch();
  else if (tab === "drafts") loadDrafts();
  else if (tab === "interests") loadInterests();
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
  $("#navRoutinesCount").textContent =
    jobs.filter((j) => j.enabled).length || "";
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
async function loadProactivity() {
  if (LIVE) {
    try {
      const r = await api.get("proactivity");
      state.proactivity = r.level || "normal";
    } catch (_) {}
  }
  $$("#proactivitySeg [data-proactivity]").forEach((b) =>
    b.classList.toggle(
      "is-active",
      b.dataset.proactivity === state.proactivity,
    ),
  );
}
$$("#proactivitySeg [data-proactivity]").forEach((b) =>
  b.addEventListener("click", async () => {
    if (!needLive()) return;
    const level = b.dataset.proactivity;
    try {
      await api.post("proactivity", { level });
      state.proactivity = level;
      await loadProactivity();
      toast(
        level === "quiet"
          ? "Mav only interrupts for what's critical."
          : level === "chatty"
            ? "Mav will also send the small stuff."
            : "Back to normal proactivity.",
      );
    } catch (err) {
      toast(err.message, { error: true });
    }
  }),
);

async function loadDrafts() {
  if (!LIVE) return;
  try {
    const r = await api.get("drafts?status=pending");
    state.drafts = r.drafts || [];
  } catch (_) {
    state.drafts = [];
  }
  renderDrafts();
}
const DRAFT_KIND = {
  reply: "Reply",
  message: "Message",
  note: "Note",
  plan: "Plan",
  other: "Draft",
};
function renderDrafts() {
  const items = state.drafts || [];
  $("#draftCount").textContent = items.length || "";
  const box = $("#draftList");
  if (!box) return;
  if (!items.length) {
    box.innerHTML = `<div class="empty-state"><strong>No draft waiting</strong>
      When Mav notices a mail to answer or a follow-up to send, it writes a
      draft here for you to review.</div>`;
    return;
  }
  box.innerHTML = items
    .map(
      (d) => `<div class="draft">
      <div class="dhead"><span class="badge">${esc(DRAFT_KIND[d.kind] || "Draft")}</span>
        <strong>${esc(d.title)}</strong>
        <span class="dmeta">${esc(fmtRel(d.ts))}</span></div>
      <div class="dbody">${mdToHtml(d.body || "")}</div>
      <div class="dacts">
        ${
          d.email_to
            ? `<button class="btn btn-primary btn-sm" data-dmail="${d.id}">${I("send") || ""} Send email</button>`
            : ""
        }
        <button class="btn btn-ghost btn-sm" data-dedit="${d.id}">${I("edit") || ""} Edit</button>
        <button class="btn btn-ghost btn-sm" data-dcopy="${d.id}">${I("copy") || ""} Copy</button>
        <button class="btn btn-ghost btn-sm" data-dnotify="${d.id}">Send to my phone</button>
        <button class="btn btn-ghost btn-sm danger" data-ddiscard="${d.id}">Discard</button>
      </div>
      ${d.email_to ? `<div class="dmeta-to">To: ${esc(d.email_to)}</div>` : ""}</div>`,
    )
    .join("");
}
$("#draftList").addEventListener("click", async (e) => {
  const pick = (attr) => e.target.closest(`[data-${attr}]`);
  const copy = pick("dcopy");
  const edit = pick("dedit");
  const mail = pick("dmail");
  const notify = pick("dnotify");
  const disc = pick("ddiscard");
  const b = copy || edit || mail || notify || disc;
  if (!b) return;
  const key = ["dedit", "dmail", "dnotify", "dcopy", "ddiscard"].find(
    (k) => b.dataset[k],
  );
  const id = Number(b.dataset[key]);
  const d = (state.drafts || []).find((x) => x.id === id);
  if (copy && d) {
    try {
      await navigator.clipboard.writeText(d.body || "");
      return toast("Copied.");
    } catch (_) {
      return toast("Could not copy.", { error: true });
    }
  }
  if (edit && d) return editDraft(d);
  if (!needLive()) return;
  try {
    if (mail) {
      if (
        !(await confirmDialog("Send this email?", `To: ${d.email_to}`, "Send"))
      )
        return;
      const r = await api.post("drafts/send", { id });
      toast(r.ok ? "Email sent." : r.error || "Send failed.", { error: !r.ok });
      loadDrafts();
    } else if (notify) {
      await api.post("drafts/notify", { id });
      toast("Sent to your phone.");
      loadDrafts();
    } else {
      await api.post("drafts/status", { id, status: "discarded" });
      toast("Draft discarded.");
      loadDrafts();
    }
  } catch (err) {
    toast(err.message, { error: true });
  }
});

function editDraft(d) {
  const form = document.createElement("form");
  form.className = "form";
  form.innerHTML = `
    <div class="field"><label>To</label>
      <input type="email" name="to" value="${esc(d.email_to || "")}" placeholder="someone@example.com"></div>
    <div class="field"><label>Subject</label>
      <input type="text" name="subject" value="${esc(d.email_subject || d.title || "")}"></div>
    <div class="field"><label>Message</label>
      <textarea name="body" rows="10">${esc(d.body || "")}</textarea></div>`;
  const save = async () => {
    if (!needLive()) return false;
    const fd = new FormData(form);
    try {
      await api.post("drafts/edit", {
        id: d.id,
        to: String(fd.get("to") || "").trim(),
        subject: String(fd.get("subject") || "").trim(),
        body: String(fd.get("body") || ""),
      });
      toast("Draft saved.");
      loadDrafts();
      return true;
    } catch (err) {
      toast(err.message, { error: true });
      return false;
    }
  };
  modal.open({
    title: "Edit draft",
    size: "wide",
    body: form,
    actions: [
      { label: "Cancel" },
      { label: "Save", kind: "btn-primary", run: save },
    ],
  });
}

const ROUTINE_IDEAS = [
  {
    label: "☀️ Morning briefing",
    draft: {
      name: "Morning briefing",
      prompt:
        "Give me a short morning briefing: today's weather where I live, and 3 headlines worth knowing. Keep it under 120 words.",
      mode: "daily",
      time: "07:30",
      agent: "researcher",
    },
  },
  {
    label: "🥗 Weekly meal plan",
    draft: {
      name: "Weekly meal plan",
      prompt:
        "Plan 5 simple dinners for this week, with a shopping list grouped by aisle. Take what you know about my diet into account.",
      mode: "weekly",
      days: ["sun"],
      time: "10:00",
      agent: "planner",
    },
  },
  {
    label: "🧾 Friday money check",
    draft: {
      name: "Friday money check",
      prompt:
        "Remind me to review this week's spending, and ask me 3 quick questions to keep my budget on track.",
      mode: "weekly",
      days: ["fri"],
      time: "18:00",
      agent: "money",
    },
  },
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
      toast(
        `“${j.name}” is running — you'll get a notification.`,
        r.session
          ? {
              action: {
                label: "Open its chat",
                run: () => openChat(r.session),
              },
            }
          : {},
      );
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
      toast(
        `“${name}” is done.`,
        j.session
          ? { action: { label: "Read it", run: () => openChat(j.session) } }
          : {},
      );
    }
  }, 4000);
}
$("#routineNew").addEventListener("click", () => editRoutine(null));
$("#routineTemplate").addEventListener("click", openTemplatePicker);
async function openTemplatePicker() {
  if (!needLive()) return;
  let templates = [];
  try {
    templates = (await api.get(`job-templates?lang=${uiLang()}`)).templates || [];
  } catch (_) {}
  const body = templates.length
    ? `<div class="tpl-grid">${templates
        .map(
          (t) => `<button class="tpl" data-tpl="${esc(t.id)}">
            <span class="tpl-ico">${esc(t.icon || "🔁")}</span>
            <strong>${esc(t.label)}</strong>
            <span>${esc(t.description)}</span></button>`,
        )
        .join("")}</div>`
    : `<p class="hint">No template available.</p>`;
  modal.open({
    title: "Start from a template",
    body,
    actions: [{ label: "Close" }],
  });
  $("#modalBody").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-tpl]");
    if (!b) return;
    const tpl = templates.find((t) => t.id === b.dataset.tpl);
    if (tpl && tpl.requires === "mail" && !MAIL.configured) {
      // The routine needs Mail, and Mail is not set up yet.
      if (
        !(await confirmDialog(
          "Mail is not set up",
          "This routine reads your inbox. Connect your mailbox first? Mav will open Settings → Connections → Mail.",
          "Set up Mail",
        ))
      )
        return;
      modal.close();
      go("settings", "connections");
      return;
    }
    try {
      const r = await api.post("job/template", { id: b.dataset.tpl, lang: uiLang() });
      if (!r.job) return toast("Unknown template.", { error: true });
      modal.close();
      editRoutine(r.job);
    } catch (err) {
      toast(err.message, { error: true });
    }
  });
}

/* Turn "every morning at 7, give me the weather" into a routine draft. */
const WEEKDAYS = {
  monday: "mon",
  tuesday: "tue",
  wednesday: "wed",
  thursday: "thu",
  friday: "fri",
  saturday: "sat",
  sunday: "sun",
};
// Multilingual recurrence detection (EN/FR/ES), mirroring bot/ocroutine_nl.py
// so the chat offer matches what the backend recognises.
const RECUR_LANGS = {
  en: {
    days: WEEKDAYS,
    part: {
      morning: "08:00",
      noon: "12:00",
      lunch: "12:00",
      afternoon: "15:00",
      evening: "19:00",
      night: "21:00",
    },
    weekdays: ["weekday", "weekdays"],
    weekend: ["weekend", "weekends"],
    recur:
      /\b(every|each)\s+(day|morning|evening|night|afternoon|week|weekday|weekend|hour|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d+\s*h(ours?|rs?)?)s?\b|\b(daily|weekly|hourly)\b|\bon\s+(mondays|tuesdays|wednesdays|thursdays|fridays|saturdays|sundays|weekdays)\b/i,
    weekly: /\b(every|each)\s+week\b|\bweekly\b/i,
    interval: /\b(?:every|each)\s+(\d+)\s*h(?:ours?|rs?)?\b/i,
    hourly: /\b(?:every|each)\s+hour\b|\bhourly\b/i,
    at: /\bat\s+(\d{1,2})(?:[:h.](\d{2}))?\s*(am|pm)?\b/i,
  },
  fr: {
    days: {
      lundi: "mon",
      mardi: "tue",
      mercredi: "wed",
      jeudi: "thu",
      vendredi: "fri",
      samedi: "sat",
      dimanche: "sun",
    },
    part: {
      matin: "08:00",
      matinée: "08:00",
      midi: "12:00",
      déjeuner: "12:00",
      "après-midi": "15:00",
      aprèm: "15:00",
      soir: "19:00",
      soirée: "19:00",
      nuit: "21:00",
    },
    weekdays: ["jour ouvré", "jours ouvrés", "jours ouvrables", "semaine"],
    weekend: ["week-end", "weekend", "weekends"],
    recur:
      /\b(tous?\s+les|chaque|toutes?\s+les)\s+(jours?|matins?|matinées?|soirs?|soirées?|nuits?|après-midis?|semaines?|week-?ends?|heures?|lundis?|mardis?|mercredis?|jeudis?|vendredis?|samedis?|dimanches?|\d+\s*h(?:eures?)?)\b|\b(quotidien(?:ne)?|hebdomadaire|horaire)\b|\b(le|les)\s+(lundis?|mardis?|mercredis?|jeudis?|vendredis?|samedis?|dimanches?)\b/i,
    weekly: /\b(tous?\s+les|chaque)\s+semaines?\b|\bhebdomadaire\b/i,
    interval:
      /\b(?:tous?\s+les|toutes?\s+les|chaque)\s+(\d+)\s*h(?:eures?)?\b/i,
    hourly: /\b(toutes?\s+les|chaque)\s+heures?\b|\bhoraire\b/i,
    at: /\b(?:à|a|vers)\s+(\d{1,2})\s*(?:[:h.](\d{2}))?\s*h?\b/i,
  },
  es: {
    days: {
      lunes: "mon",
      martes: "tue",
      miércoles: "wed",
      miercoles: "wed",
      jueves: "thu",
      viernes: "fri",
      sábado: "sat",
      sabado: "sat",
      domingo: "sun",
    },
    part: {
      mañana: "08:00",
      manana: "08:00",
      mediodía: "12:00",
      mediodia: "12:00",
      almuerzo: "12:00",
      tarde: "15:00",
      noche: "21:00",
    },
    weekdays: ["día laborable", "días laborables", "entre semana"],
    weekend: ["fin de semana", "fines de semana"],
    recur:
      /\b(todos?\s+los|cada)\s+(días?|mañanas?|tardes?|noches?|semanas?|horas?|fines?\s+de\s+semana|\d+\s*h(?:oras?)?)\b|\b(diariamente|semanal(?:mente)?|cada\s+hora)\b|\b(los|el)\s+(lunes|martes|miércoles|miercoles|jueves|viernes|sábados?|sabados?|domingos?)\b/i,
    weekly: /\b(todos?\s+los|cada)\s+semanas?\b|\bsemanal(?:mente)?\b/i,
    interval: /\b(?:todos?\s+los|cada)\s+(\d+)\s*h(?:oras?)?\b/i,
    hourly: /\b(cada|todas?\s+las)\s+horas?\b|\bcada\s+hora\b/i,
    at: /\b(?:a|las)\s+(\d{1,2})(?:[:h.](\d{2}))?\s*h?\b/i,
  },
};
// `\b` only knows ASCII letters: "à 18h", "matinée", "sábado" never matched.
// Rebuild every pattern with Unicode-aware word boundaries.
const UB =
  "(?:(?<![\\p{L}\\p{N}_])(?=[\\p{L}\\p{N}_])|(?<=[\\p{L}\\p{N}_])(?![\\p{L}\\p{N}_]))";
function uniRe(src, flags = "i") {
  return new RegExp(src.split("\\b").join(UB), flags.includes("u") ? flags : flags + "u");
}
function wordRe(word) {
  return uniRe(`\\b${escRe(word)}\\b`);
}
for (const L of Object.values(RECUR_LANGS))
  for (const k of ["recur", "weekly", "interval", "hourly", "at"])
    L[k] = uniRe(L[k].source, L[k].flags);
const RECUR_ORDER = ["fr", "en", "es"];
function recurLang(text) {
  return RECUR_ORDER.find((l) => RECUR_LANGS[l].recur.test(text)) || "en";
}
function detectRoutine(text) {
  if (!text || text.length > 400 || text.startsWith("/")) return null;
  const lang = RECUR_ORDER.find((l) => RECUR_LANGS[l].recur.test(text));
  return lang ? draftRoutine(text) : null;
}
function draftRoutine(text) {
  const t = text.toLowerCase();
  const lang = recurLang(text);
  const L = RECUR_LANGS[lang];
  const d = {
    mode: "daily",
    time: "09:00",
    days: [...ALL_DAYS],
    hours: 0,
    lang,
  };
  const consumed = [];
  let m;
  // The recurrence itself ("every morning", "tous les jours", "daily"…) is
  // not part of what to do.
  if ((m = t.match(L.recur))) consumed.push(m[0]);
  if ((m = t.match(L.interval))) {
    d.mode = "hours";
    d.hours = Number(m[1]);
    consumed.push(m[0]);
  } else if ((m = t.match(L.hourly))) {
    d.mode = "hours";
    d.hours = 1;
    consumed.push(m[0]);
  }
  const days = Object.entries(L.days)
    .filter(([w]) => uniRe(`\\b${escRe(w)}s?\\b`).test(t))
    .map(([, v]) => v);
  if (L.weekdays.some((w) => t.includes(w))) {
    d.days = ["mon", "tue", "wed", "thu", "fri"];
    consumed.push(...L.weekdays.filter((w) => t.includes(w)));
  } else if (L.weekend.some((w) => t.includes(w))) {
    d.days = ["sat", "sun"];
    consumed.push(...L.weekend.filter((w) => t.includes(w)));
  } else if (days.length) d.days = days;
  else if ((m = t.match(L.weekly))) {
    d.days = ["mon"];
    consumed.push(m[0]);
  }
  if (d.mode !== "hours" && d.days.length < 7) d.mode = "weekly";
  for (const [word, h] of Object.entries(L.part)) {
    if (wordRe(word).test(t)) {
      d.time = h;
      consumed.push(word);
      break;
    }
  }
  if ((m = t.match(L.at))) {
    let h = Number(m[1]);
    if (m[3] === "pm" && h < 12) h += 12;
    if (m[3] === "am" && h === 12) h = 0;
    if (h < 24) {
      d.time = `${String(h).padStart(2, "0")}:${m[2] || "00"}`;
      consumed.push(m[0]);
    }
  }
  // What to do = the sentence without the fragments we recognised.
  let what = text;
  [...new Set(consumed)]
    .sort((a, b) => b.length - a.length)
    .forEach((frag) => {
      what = what.replace(new RegExp(escRe(frag), "gi"), " ");
    });
  what = what.replace(/\s{2,}/g, " ").replace(/^[\s,.:;-]+|[\s,.:;-]+$/g, "");
  const remind = what.match(/^(please\s+)?remind me (to |about |that )?(.*)$/i);
  d.prompt = remind
    ? `Send me a short, friendly reminder: ${remind[3]}. One or two sentences.`
    : what.charAt(0).toUpperCase() + what.slice(1);
  const nameSrc = remind ? remind[3] : what;
  d.name = (nameSrc.split(/\s+/).slice(0, 4).join(" ") || "Routine")
    .replace(/[^\p{L}\p{N}\s.-]/gu, "")
    .trim();
  d.name = d.name.charAt(0).toUpperCase() + d.name.slice(1);
  d.agent = currentAgent();
  return d;
}
function escRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
function draftWhen(d) {
  return d.mode === "hours"
    ? d.hours === 1
      ? "every hour"
      : `every ${d.hours} hours`
    : d.mode === "weekly"
      ? `${fmtDays(d.days)} at ${d.time}`
      : `every day at ${d.time}`;
}
function uniqueRoutineName(name, original = "") {
  const taken = new Set(
    state.jobs.map((j) => j.name).filter((n) => n !== original),
  );
  if (!taken.has(name)) return name;
  let i = 2;
  while (taken.has(`${name} ${i}`)) i++;
  return `${name} ${i}`;
}
function draftToJob(d) {
  const job = {
    name: uniqueRoutineName(d.name, d.original || ""),
    prompt: d.prompt,
    agent: d.agent || "",
    enabled: true,
    description: d.description || "",
  };
  if (d.mode === "hours") {
    const mult = d.unit === "minutes" ? 1 : 60;
    job.every_minutes = Math.max(5, Math.round(d.hours * mult));
  } else if (d.mode === "monthly") {
    job.time = d.time;
    if (d.last_day_of_month) job.last_day_of_month = true;
    if (d.days_of_month && d.days_of_month.length)
      job.days_of_month = d.days_of_month;
  } else if (d.mode === "event") {
    job.on_event = { kind: d.event_kind || "custom" };
    if (d.event_contains) job.on_event.contains = d.event_contains;
  } else {
    job.time = d.time;
    job.days = d.mode === "weekly" ? d.days : [...ALL_DAYS];
  }
  if (d.condition_type && d.condition_type !== "none") {
    job.condition_type = d.condition_type;
    if (d.condition_value) job.condition_value = d.condition_value;
    if (d.condition_source) job.condition_source = d.condition_source;
    if (d.condition_negate) job.condition_negate = true;
    if (d.condition_type === "number")
      job.condition_op = d.condition_op || ">=";
  }
  if (d.channels && d.channels.length) job.channels = d.channels;
  return job;
}
/* Where a routine's reports go. Shown only once other channels exist;
   everything ticked (the default) is sent as "everywhere". */
function channelPicker(chosen) {
  const list = state.channels || [];
  if (!list.length) return "";
  const all = !chosen || !chosen.length;
  const opts = [["push", "Web Push (this app)"], ...list.map((c) => [c.id, `${c.name} · ${c.type}`])];
  return `<details class="field"><summary>Send reports to… (optional)</summary>
    <div class="row wrap" style="margin-top:0.5rem" data-chans>${opts
      .map(
        ([id, label]) =>
          `<label class="check"><input type="checkbox" value="${esc(id)}" ${all || chosen.includes(id) ? "checked" : ""}> ${esc(label)}</label>`,
      )
      .join("")}</div></details>`;
}
function pickedChannels(form) {
  const boxes = [...form.querySelectorAll("[data-chans] input")];
  const on = boxes.filter((b) => b.checked).map((b) => b.value);
  if (!on.length) return ["none"]; // only the inbox on the home screen
  return on.length === boxes.length ? [] : on;
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
  if (!src)
    d = {
      name: "",
      prompt: "",
      agent: state.preferredAgent || state.defaultAgent,
      mode: "daily",
      time: "08:00",
      days: [...ALL_DAYS],
      hours: 4,
    };
  else if (existing) {
    const mode = jobMode(src);
    const cond = src.skip_if || {};
    d = {
      ...src,
      mode,
      hours:
        mode === "hours"
          ? src.every_minutes % 60 === 0
            ? src.every_minutes / 60
            : src.every_minutes
          : 4,
      unit:
        mode === "hours" && src.every_minutes % 60 !== 0 ? "minutes" : "hours",
      days: src.days && src.days.length ? src.days : [...ALL_DAYS],
      time: src.time || "08:00",
      days_of_month: src.days_of_month || [],
      last_day_of_month: !!src.last_day_of_month,
      event_kind: (src.on_event && src.on_event.kind) || "custom",
      event_contains: (src.on_event && src.on_event.contains) || "",
      condition_type: cond.type || "none",
      condition_value: cond.value || "",
      condition_source: cond.source || "",
      condition_negate: !!cond.negate,
      condition_op: cond.op || ">=",
    };
  } else
    d = {
      hours: 4,
      unit: "hours",
      days: [...ALL_DAYS],
      time: "08:00",
      days_of_month: [],
      event_kind: "custom",
      condition_type: "none",
      ...src,
    };
  if (state.view !== "routines" && !existing) go("routines", "routines");
  const form = document.createElement("form");
  form.className = "form";
  form.innerHTML = `
    <div class="field"><label>What should Mav do?</label>
      <textarea name="prompt" required placeholder="e.g. Tell me if I need an umbrella today, and what to wear.">${esc(d.prompt || "")}</textarea>
      <small>Write it like a message to Mav. If there's nothing worth telling you, it stays quiet.</small></div>
    <div class="field"><span class="field-label">When</span>
      <div class="segmented" data-modes>
        <button type="button" data-m="daily">Every day</button><button type="button" data-m="weekly">Some days</button><button type="button" data-m="monthly">Once a month</button><button type="button" data-m="hours">Every few hours</button><button type="button" data-m="event">On an event</button>
      </div></div>
    <div class="when-row">
      <div class="field" data-f="time"><label>At</label><input type="time" name="time" value="${esc(d.time)}"></div>
      <div class="field" data-f="days"><span class="field-label">On</span><div class="days">${ALL_DAYS.map((x) => `<button type="button" data-day="${x}" class="${d.days.includes(x) ? "is-on" : ""}">${DAY_NAMES[x]}</button>`).join("")}</div></div>
      <div class="field" data-f="monthly">
        <label>Day(s) of the month</label>
        <div class="row"><input type="text" name="days_of_month" value="${esc((d.days_of_month || []).join(", "))}" placeholder="1, 15" style="width:110px">
        <label class="check"><input type="checkbox" name="last_day_of_month" ${d.last_day_of_month ? "checked" : ""}> last day</label></div>
      </div>
      <div class="field" data-f="event">
        <label>When this event fires</label>
        <div class="row"><select name="event_kind">${[
          "github",
          "calendar",
          "form",
          "payment",
          "iot",
          "custom",
        ]
          .map(
            (k) =>
              `<option ${k === d.event_kind ? "selected" : ""} value="${k}">${k}</option>`,
          )
          .join("")}</select>
        <input type="text" name="event_contains" value="${esc(d.event_contains || "")}" placeholder="contains… (optional)"></div>
      </div>
      <div class="field" data-f="hours"><label>Every</label><div class="row"><input type="number" min="1" max="1440" name="hours" value="${esc(d.hours)}" style="width:90px">
        <select name="unit">
          <option value="hours" ${d.unit !== "minutes" ? "selected" : ""}>hours</option>
          <option value="minutes" ${d.unit === "minutes" ? "selected" : ""}>minutes</option>
        </select></div></div>
    </div>
    <div class="field-grid">
      <div class="field"><label>Helper</label><select name="agent">${state.agents
        .map(
          (a) =>
            `<option ${a === (d.agent || state.defaultAgent) ? "selected" : ""} value="${esc(a)}">${esc(agentDisplay(a))}</option>`,
        )
        .join("")}</select></div>
      <div class="field"><label>Name</label><input name="name" value="${esc(d.name || "")}" placeholder="Morning briefing"></div>
    </div>
    <details class="field">
      <summary>Only run when… (optional)</summary>
      <div class="row" style="margin-top:0.5rem">
        <select name="condition_type">${[
          ["none", "always"],
          ["text_contains", "text contains"],
          ["text_matches", "text matches regex"],
          ["number", "number"],
          ["weekday", "weekday"],
          ["exists", "not empty"],
        ]
          .map(
            ([v, l]) =>
              `<option ${v === (d.condition_type || "none") ? "selected" : ""} value="${v}">${l}</option>`,
          )
          .join("")}</select>
        <input type="text" name="condition_value" value="${esc(d.condition_value || "")}" placeholder="value">
        <input type="text" name="condition_source" value="${esc(d.condition_source || "")}" placeholder="source (optional)">
      </div>
      <small>Checked before Mav runs — if it isn't met, the routine is skipped.</small>
    </details>${channelPicker(d.channels)}`;
  let mode = d.mode;
  const setMode = (x) => {
    mode = x;
    form
      .querySelectorAll("[data-m]")
      .forEach((b) => b.classList.toggle("is-active", b.dataset.m === x));
    form.querySelector('[data-f="time"]').hidden =
      x === "hours" || x === "event";
    form.querySelector('[data-f="days"]').hidden = x !== "weekly";
    form.querySelector('[data-f="monthly"]').hidden = x !== "monthly";
    form.querySelector('[data-f="event"]').hidden = x !== "event";
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
    if (!name)
      name =
        prompt
          .split(/\s+/)
          .slice(0, 4)
          .join(" ")
          .replace(/[^\p{L}\p{N}\s.-]/gu, "")
          .trim() || "Routine";
    const domRaw = String(fd.get("days_of_month") || "");
    const job = draftToJob({
      original: existing ? d.name : "",
      name,
      prompt,
      agent: fd.get("agent"),
      mode,
      time: fd.get("time"),
      hours: Number(fd.get("hours") || 1),
      unit: fd.get("unit") === "minutes" ? "minutes" : "hours",
      days: [...form.querySelectorAll("[data-day].is-on")].map(
        (b) => b.dataset.day,
      ),
      days_of_month: domRaw
        .split(/[,\s]+/)
        .map((x) => parseInt(x, 10))
        .filter((n) => n >= 1 && n <= 31),
      last_day_of_month: !!fd.get("last_day_of_month"),
      event_kind: fd.get("event_kind"),
      event_contains: String(fd.get("event_contains") || "").trim(),
      condition_type: fd.get("condition_type"),
      condition_value: String(fd.get("condition_value") || "").trim(),
      condition_source: String(fd.get("condition_source") || "").trim(),
      description: existing ? d.description : "",
      channels: pickedChannels(form),
    });
    if (mode === "weekly" && !job.days.length) {
      toast("Pick at least one day.", { error: true });
      return false;
    }
    if (mode === "monthly" && !job.days_of_month && !job.last_day_of_month) {
      toast("Pick a day of the month.", { error: true });
      return false;
    }
    job.original = existing ? d.name : "";
    job.enabled = existing ? d.enabled !== false : true;
    btn.disabled = true;
    try {
      await api.post("job/save", job);
      toast(
        isNew
          ? "Routine created — you'll get a notification each time it runs."
          : "Routine saved.",
      );
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
      label: "Delete",
      kind: "btn-danger",
      left: true,
      run: async () => {
        if (
          !(await confirmDialog(
            "Delete this routine?",
            `“${d.name}” will stop running. Its chat is kept.`,
            "Delete",
          ))
        )
          return false;
        await api.post("job/delete", { name: d.name }).catch(() => {});
        toast("Routine deleted.");
        loadRoutines();
      },
    });
  actions.push(
    { label: "Cancel" },
    {
      label: isNew ? "Create routine" : "Save",
      kind: "btn-primary",
      run: save,
    },
  );
  modal.open({
    title: isNew ? "New routine" : `Routine “${d.name}”`,
    body: form,
    actions,
  });
}

/* ================================================================
   10. Keep an eye on
   ================================================================ */
const WATCH_KINDS = {
  web: {
    ph: "https://example.com/page",
    hint: "You'll get an alert when the text of the page changes.",
    ico: "globe",
    label: "Page",
  },
  price: {
    ph: "https://shop.example.com/product",
    hint: "Mav reads the price on the page and alerts you when it changes — or only when it drops below your target.",
    ico: "tag",
    label: "Price",
  },
  news: {
    ph: "a topic, e.g. “Lyon public transport strike”",
    hint: "You'll get the new headlines about this topic as they come out.",
    ico: "news",
    label: "News",
  },
  rss: {
    ph: "https://example.com/feed.xml",
    hint: "New items in an RSS or Atom feed — several at once arrive as one alert.",
    ico: "news",
    label: "Feed",
  },
  github: {
    ph: "owner/repo, e.g. home-assistant/core",
    hint: "You'll hear about each new release of this GitHub repository.",
    ico: "bolt",
    label: "Releases",
  },
};
const WATCH_FEEDS = ["news", "rss", "github"];
let watchKind = "web";
function setWatchKind(k) {
  watchKind = k;
  $$("#watchKinds [data-kind]").forEach((b) =>
    b.classList.toggle("is-active", b.dataset.kind === k),
  );
  $("#watchTarget").placeholder = WATCH_KINDS[k].ph;
  $("#watchHint").textContent = WATCH_KINDS[k].hint;
  $("#watchBelow").hidden = k !== "price";
  $("#watchOnly").hidden = !WATCH_FEEDS.includes(k);
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
          const [target, extra] = String(x.target).split("|");
          const below = x.kind === "price" ? extra : "";
          const only = WATCH_FEEDS.includes(x.kind) ? extra : "";
          const price = (x.last_state || "").match(/price=([0-9.]+)/);
          const href = /^https?:/.test(target)
            ? target
            : x.kind === "github"
              ? `https://github.com/${target}/releases`
              : "";
          return `<div class="wcard"><div class="wtop">${I(k.ico)} ${esc(k.label)}
            <button class="icon-btn" data-rm="${x.id}" title="Stop">${I("trash")}</button></div>
            <div class="wtarget">${href ? `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(target.replace(/^https?:\/\/(www\.)?/, "").slice(0, 70))}</a>` : esc(target)}</div>
            <div class="wstate"><span class="dot ${x.last_state ? "ok" : ""}"></span>
              ${only ? `Only if it mentions ${esc(only)} · ` : ""}
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
  if (!["news", "github"].includes(watchKind) && !/^https?:\/\//i.test(target))
    target = "https://" + target;
  target = target.replace(/\|/g, " ");
  const below = $("#watchBelow").value.trim();
  if (watchKind === "price" && below) target += `|${below}`;
  const only = $("#watchOnly").value.replace(/\|/g, " ").trim();
  if (WATCH_FEEDS.includes(watchKind) && only) target += `|${only}`;
  try {
    await api.post("watch/add", { kind: watchKind, target });
    $("#watchTarget").value = "";
    $("#watchBelow").value = "";
    $("#watchOnly").value = "";
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
   10b. Interests — the control tower
   ================================================================ */
const INTEREST_CAT = {
  sport: { ico: "activity", label: "Sport" },
  finance: { ico: "chart", label: "Finance" },
  tech: { ico: "cpu", label: "Tech" },
  games: { ico: "gamepad", label: "Games" },
  music: { ico: "music", label: "Music" },
  food: { ico: "coffee", label: "Food" },
  travel: { ico: "globe", label: "Travel" },
  culture: { ico: "book", label: "Culture" },
  other: { ico: "sparkle", label: "Other" },
};
const AUTONOMY_LABEL = {
  off: "Mav observes your interests but never creates watch routines on its own.",
  suggest: "Mav proposes watch routines and you accept them with one click.",
  auto: "Mav creates, tunes and retires its own watch routines without asking.",
};
async function loadInterests() {
  if (LIVE) {
    try {
      state.interests = await api.get("interests");
    } catch (_) {}
  }
  renderInterests();
}
function renderInterests() {
  const data = state.interests || {};
  const items = data.interests || [];
  $("#interestCount").textContent =
    items.filter((i) => i.polarity === "like").length || "";
  const b = $("#interestBackend");
  if (b) {
    b.className = "badge " + (data.backend === "postgres" ? "ok" : "warn");
    b.textContent =
      data.backend === "postgres" ? "Profile on" : LIVE ? "File only" : "Demo";
  }
  const aut = data.autonomy || "suggest";
  $$("#autonomySeg [data-autonomy]").forEach((x) =>
    x.classList.toggle("is-active", x.dataset.autonomy === aut),
  );
  const hint = $("#autonomyHint");
  if (hint) hint.textContent = AUTONOMY_LABEL[aut] || "";

  renderSelfInit(data.selfinit);

  const box = $("#interestList");
  if (!box) return;
  if (!items.length) {
    box.innerHTML = `<div class="empty-state"><strong>Nothing learned yet</strong>
      Talk to Mav, or add a topic above (say “j'adore la cyber”, “I love the Lakers”). Mav records each one with its evidence and turns the ones it can into watches.</div>`;
    return;
  }
  box.innerHTML = items
    .map((it) => {
      const cat = INTEREST_CAT[it.category] || INTEREST_CAT.other;
      const pct = Math.round((it.score || 0) * 100);
      const conf = Math.round((it.confidence || 0) * 100);
      const dislike = it.polarity === "dislike";
      const flags = [
        dislike ? `<span class="badge warn">dislike</span>` : "",
        it.pinned ? `<span class="badge ok">pinned</span>` : "",
        it.muted ? `<span class="badge warn">muted</span>` : "",
        it.conflicted ? `<span class="badge warn">uncertain</span>` : "",
        it.last_ref ? `<span class="badge">watched</span>` : "",
      ].join("");
      const ev = (it.evidence || [])
        .slice(-2)
        .map(
          (e) =>
            `<div class="iev">“${esc(e.snippet || "")}” <span class="imeta">${esc(fmtRel(e.ts))} · ${esc(e.source || "")}</span></div>`,
        )
        .join("");
      const cadences = ["off", "weekly", "biweekly", "monthly", "quarterly"];
      return `<div class="icard ${dislike ? "is-dislike" : ""} ${it.muted ? "is-muted" : ""}">
        <div class="ihead">
          ${I(cat.ico)} <strong>${esc(it.label)}</strong>
          <span class="imeta">${esc(cat.label)}${it.polarity === "like" && it.cadence ? " · " + esc(it.cadence) : ""}</span>
          <span class="grow"></span>
          ${flags}
          <button class="icon-btn" data-iopen="${esc(it.key)}" title="Open a chat about this">${I("chat")}</button>
          <button class="icon-btn" data-iboost="${esc(it.key)}" title="More like this">${I("plus")}</button>
          <button class="icon-btn" data-imute="${esc(it.key)}" title="${it.muted ? "Unmute" : "Mute"}">${I(it.muted ? "bell" : "bell-off")}</button>
          <button class="icon-btn" data-ipin="${esc(it.key)}" title="${it.pinned ? "Unpin" : "Pin"}">${I("pin")}</button>
          <button class="icon-btn danger" data-idel="${esc(it.key)}" title="Forget">${I("trash")}</button>
        </div>
        <div class="ibars">
          <span class="ibar" title="Interest strength"><i style="width:${pct}%"></i></span>
          <span class="imeta">interest ${pct}% · confidence ${conf}%</span>
          ${it.due_in_days != null ? `<span class="imeta">· next nudge in ${it.due_in_days <= 0 ? "queued" : it.due_in_days + "d"}</span>` : ""}
        </div>
        ${
          it.conflicted
            ? `<div class="iconflict">You said both. Settle it:
          <button class="btn btn-ghost btn-sm" data-iresolve="${esc(it.key)}" data-pol="like">Keep “like”</button>
          <button class="btn btn-ghost btn-sm" data-iresolve="${esc(it.key)}" data-pol="dislike">Make it a dislike</button></div>`
            : ""
        }
        ${ev ? `<div class="ievidence">${ev}</div>` : ""}
        <div class="iacts">
          <select class="isel" data-icadence="${esc(it.key)}" aria-label="Cadence">
            ${cadences.map((c) => `<option value="${c}" ${c === it.cadence ? "selected" : ""}>${c === "off" ? "Off" : "nudge " + c}</option>`).join("")}
          </select>
          <button class="btn btn-ghost btn-sm" data-ifbup="${esc(it.key)}">👍</button>
          <button class="btn btn-ghost btn-sm" data-ifbdown="${esc(it.key)}">👎</button>
        </div>
      </div>`;
    })
    .join("");
}
function renderSelfInit(si) {
  const box = $("#selfinitBox");
  if (!box) return;
  const c = (si && si.counts) || {};
  const total = (c.create || 0) + (c.update || 0) + (c.retire || 0);
  if (!si || !total) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const rows = [];
  (si.create || []).forEach((j) =>
    rows.push(
      `<li>${I("plus")} Create watch <strong>${esc(j.name)}</strong> — every ${Math.round((j.every_minutes || 0) / 60)}h</li>`,
    ),
  );
  (si.update || []).forEach((j) =>
    rows.push(`<li>${I("edit")} Retune <strong>${esc(j.name)}</strong></li>`),
  );
  (si.retire || []).forEach((j) =>
    rows.push(
      `<li>${I("trash")} Retire <strong>${esc(j.name)}</strong> (interest cooled down)</li>`,
    ),
  );
  box.innerHTML = `<div class="card selfinit-card"><div class="ac-row">
      <div><strong>Mav proposes ${total} change${total > 1 ? "s" : ""} to its own watches</strong>
      <p class="hint">${si.autonomy === "auto" ? "Applied automatically." : "Review and let Mav apply them."}</p></div>
      <button class="btn btn-primary btn-sm" id="selfinitApply">${I("check")} Apply now</button>
      </div><ul class="selfinit-list">${rows.join("")}</ul></div>`;
}
$$("#autonomySeg [data-autonomy]").forEach((btn) =>
  btn.addEventListener("click", async () => {
    if (!needLive()) return;
    try {
      await api.post("interests/autonomy", { level: btn.dataset.autonomy });
      toast("Saved.");
      loadInterests();
    } catch (err) {
      toast(err.message, { error: true });
    }
  }),
);
document.addEventListener("click", async (e) => {
  if (e.target.closest("#selfinitApply")) {
    if (!needLive()) return;
    try {
      const r = await api.post("interests/apply", {});
      toast(
        r.applied || (r.counts && r.counts.create)
          ? "Mav updated its watches."
          : "Nothing to apply.",
      );
      loadInterests();
    } catch (err) {
      toast(err.message, { error: true });
    }
  }
});
$("#interestForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const label = $("#interestLabel").value.trim();
  if (!label || !needLive()) return;
  try {
    await api.post("interests/add", {
      label,
      category: $("#interestCategory").value,
      polarity: $("#interestPolarity").value,
    });
    $("#interestLabel").value = "";
    toast("Noted.");
    loadInterests();
  } catch (err) {
    toast(err.message, { error: true });
  }
});
$("#interestList").addEventListener("click", async (e) => {
  const pick = (a) => e.target.closest(`[data-${a}]`);
  const open = pick("iopen");
  const boost = pick("iboost");
  const mute = pick("imute");
  const pin = pick("ipin");
  const del = pick("idel");
  const resolve = pick("iresolve");
  const up = pick("ifbup");
  const down = pick("ifbdown");
  const b = open || boost || mute || pin || del || resolve || up || down;
  if (!b || !needLive()) return;
  const key =
    b.dataset.iopen ||
    b.dataset.iboost ||
    b.dataset.imute ||
    b.dataset.ipin ||
    b.dataset.idel ||
    b.dataset.iresolve ||
    b.dataset.ifbup ||
    b.dataset.ifbdown;
  try {
    if (open) {
      toast("Mav is opening a chat…");
      const r = await api.post("interests/open", { key });
      if (r.session) openChat(r.session);
      return;
    }
    if (boost) await api.post("interests/feedback", { key, positive: true });
    else if (up || down)
      await api.post("interests/feedback", { key, positive: !!up });
    else if (mute) {
      const it = (state.interests.interests || []).find((x) => x.key === key);
      await api.post("interests/update", { key, muted: !(it && it.muted) });
    } else if (pin) {
      const it = (state.interests.interests || []).find((x) => x.key === key);
      await api.post("interests/update", { key, pinned: !(it && it.pinned) });
    } else if (resolve) {
      await api.post("interests/update", {
        key,
        polarity: b.dataset.pol,
        resolve_conflict: true,
      });
    } else if (del) {
      if (!(await confirmDialog("Forget this interest?", key, "Forget")))
        return;
      await api.post("interests/delete", { key });
    }
    loadInterests();
  } catch (err) {
    toast(err.message, { error: true });
  }
});
$("#interestList").addEventListener("change", async (e) => {
  const sel = e.target.closest("[data-icadence]");
  if (!sel || !needLive()) return;
  try {
    await api.post("interests/update", {
      key: sel.dataset.icadence,
      cadence: sel.value,
    });
    toast("Cadence updated.");
    loadInterests();
  } catch (err) {
    toast(err.message, { error: true });
  }
});

/* ================================================================
   11. Memory
   ================================================================ */
$$("[data-mtab]").forEach((t) =>
  t.addEventListener("click", () => {
    $$("[data-mtab]").forEach((x) => x.classList.toggle("is-active", x === t));
    $$(".mpanel").forEach((p) =>
      p.classList.toggle("is-active", p.id === `mpanel-${t.dataset.mtab}`),
    );
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
  b.textContent =
    m.backend === "postgres" ? "Memory on" : LIVE ? "Database offline" : "Demo";
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
          (
            c,
          ) => `<li><span class="ltext"><strong>${esc(c.question || c.title || c.fact || "")}</strong>
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
  await api
    .post(f ? "memory/fact/delete" : "memory/exchange/delete", {
      id: Number(f ? f.dataset.delFact : x.dataset.delEx),
    })
    .catch(() => {});
  toast("Forgotten.");
  loadMemory();
});
$("#forgetAll").addEventListener("click", async () => {
  if (!needLive()) return;
  if (
    !(await confirmDialog(
      "Clear chat memory?",
      "Mav will stop recalling your past chats. What it knows about you (above) is kept.",
      "Clear",
    ))
  )
    return;
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
        [
          ...(r.conversations || []),
          ...(r.facts || []).map((f) => ({ ...f, kind: "about you" })),
          ...(r.documents || []).map((d) => ({ ...d, kind: "document" })),
        ],
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
  $$("[data-stab]").forEach((t) =>
    t.classList.toggle("is-active", t.dataset.stab === tab),
  );
  $$(".spanel").forEach((p) =>
    p.classList.toggle("is-active", p.id === `spanel-${tab}`),
  );
  (
    ({
      model: loadProvider,
      helpers: loadAgentFiles,
      instructions: loadInstructions,
      connections: () => {
        loadMcp();
        loadMail();
      },
      usage: loadUsage,
      general: () => {
        loadAdvanced();
        checkVersion();
      },
    })[tab] || (() => {})
  )();
}
$$("[data-stab]").forEach((t) =>
  t.addEventListener("click", () => {
    openSettingsTab(t.dataset.stab);
    history.replaceState(null, "", `#settings/${t.dataset.stab}`);
  }),
);
/* ---------- Usage ---------- */
const money = (v) =>
  v >= 100 ? `$${Math.round(v)}` : v >= 1 ? `$${v.toFixed(2)}` : `$${v.toFixed(v ? 3 : 2)}`;
const compact = (n) =>
  n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n || 0);
let budgetAction = "warn";
function setBudgetAction(v) {
  budgetAction = v === "stop" ? "stop" : "warn";
  $$("#budgetAction [data-v]").forEach((b) =>
    b.classList.toggle("is-active", b.dataset.v === budgetAction),
  );
}
async function loadUsage() {
  if (!LIVE) return;
  let u;
  try {
    u = await api.get("usage");
  } catch (_) {
    return;
  }
  if (!u.available) {
    $("#usageMeterText").textContent = "Usage tracking is not available.";
    return;
  }
  $("#usageCost").textContent = money(u.cost || 0);
  $("#usageAnswers").textContent = String(u.answers || 0);
  $("#usageTokens").textContent = compact(u.tokens || 0);
  const b = u.budget || {};
  const meter = $("#usageMeter");
  if (b.monthly_usd) {
    const pct = Math.min(100, u.used_pct || 0);
    meter.hidden = false;
    meter.querySelector("i").style.width = `${pct}%`;
    meter.classList.toggle("is-high", pct >= 80 && pct < 100);
    meter.classList.toggle("is-over", pct >= 100);
    $("#usageMeterText").textContent =
      `${money(u.cost || 0)} of ${money(b.monthly_usd)} (${Math.round(u.used_pct || 0)} %)` +
      (u.blocked ? " — new answers are paused until you raise the budget." : "");
  } else {
    meter.hidden = true;
    $("#usageMeterText").textContent = "No budget set.";
  }
  const max = Math.max(...u.days.map((d) => d.cost), 0);
  $("#usageBars").innerHTML = u.days
    .map((d) => {
      const h = max ? Math.max(2, Math.round((90 * d.cost) / max)) : 2;
      return `<i class="${d.cost ? "" : "is-zero"}" style="height:${h}px" title="${esc(d.day)} · ${money(d.cost)} · ${d.answers} answer(s)"></i>`;
    })
    .join("");
  const label = { chat: "Chats", routine: "Routines & briefing", background: "Background (titles, memory)" };
  $("#usageSplit").innerHTML = Object.entries(u.by_source || {})
    .map(([k, v]) => `<span><strong>${esc(label[k] || k)}</strong> ${money(v.cost)} · ${v.answers}</span>`)
    .join("");
  $("#budgetAmount").value = b.monthly_usd || "";
  setBudgetAction(b.action);
  $("#smallModel").value = u.small_model || "";
  // Suggestions: the models of the provider already connected.
  try {
    const cur = ((await api.get("config/provider")).current || {});
    if (cur.provider) {
      const r = await api.post("config/provider/test", {
        provider: cur.preset === "custom" ? cur.provider : cur.preset || cur.provider,
        base_url: cur.base_url || "",
      });
      $("#smallModelList").innerHTML = (r.models || [])
        .map((m) => (typeof m === "string" ? m : m.id))
        .map((m) => `<option value="${esc(`${cur.provider}/${m}`)}">`)
        .join("");
    }
  } catch (_) {}
}
$("#budgetAction").addEventListener("click", (e) => {
  const b = e.target.closest("[data-v]");
  if (b) setBudgetAction(b.dataset.v);
});
$("#budgetSave").addEventListener("click", async () => {
  if (!needLive()) return;
  try {
    await api.post("usage/budget", {
      monthly_usd: Number($("#budgetAmount").value || 0),
      action: budgetAction,
    });
    toast("Budget saved.");
    loadUsage();
  } catch (ex) {
    toast(ex.message, { error: true });
  }
});
$("#smallModelSave").addEventListener("click", async () => {
  if (!needLive()) return;
  try {
    await api.post("usage/small-model", { model: $("#smallModel").value });
    toast($("#smallModel").value ? "Background model saved." : "Background work uses your main model.");
  } catch (ex) {
    toast(ex.message, { error: true });
  }
});

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
  const what =
    names.length === 1
      ? names[0]
      : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
  $("#pendingText").textContent =
    `Your changes to ${what} are saved — restart the assistant to apply them.`;
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
  toast(
    "The assistant did not come back — see Settings → General → Advanced.",
    { error: true },
  );
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
    PROV = {
      presets: DEMO.presets,
      current: { configured: false },
      sel: PROV.sel,
    };
    return renderProvider();
  }
  try {
    const d = await api.get("config/provider");
    PROV.presets = d.presets || [];
    PROV.current = d.current || {};
  } catch (_) {}
  if (
    !PROV.sel &&
    PROV.current.preset &&
    PROV.presets.some((p) => p.id === PROV.current.preset)
  )
    PROV.sel = PROV.current.preset;
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
      (
        p,
      ) => `<button type="button" class="provider ${p.id === PROV.sel ? "is-sel" : ""}" data-prov="${esc(p.id)}">
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
  $("#pBaseHint").textContent =
    p.id === "ollama"
      ? "Where Ollama runs — e.g. http://192.168.1.10:11434/v1"
      : "";
  $("#fKey").hidden = false;
  $("#pKey").value = "";
  $("#pKey").placeholder =
    isCurrent && c.has_key
      ? "•••••••• saved — leave empty to keep it"
      : p.key === "optional"
        ? "optional"
        : "paste your API key";
  $("#pKeyHint").textContent =
    p.key === "required" ? "Kept on your server only." : "";
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
    const r = await api.post("config/provider/test", {
      ...p,
      provider: p.provider === "custom" ? p.custom_id || "custom" : p.provider,
    });
    if (r.ok) {
      $("#pModelList").innerHTML = r.models
        .map((m) => `<option value="${esc(m)}">`)
        .join("");
      out.className = "is-ok";
      out.textContent = `Connected — ${r.models.length} model${r.models.length === 1 ? "" : "s"} available. Pick one in the field.`;
      if (!$("#pModel").value && r.models.length)
        $("#pModel").value = r.models[0];
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
      toast(`Saved, but the restart failed: ${r.restart.error}`, {
        error: true,
        action: restartAction,
      });
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
    AGENT_FILES = state.agents.map((a) => ({
      name: a,
      description: agentDesc(a),
      mode: "all",
    }));
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
    lines.push(
      "permission:",
      "  websearch: allow",
      "  webfetch: allow",
      "  todowrite: allow",
      // Files it hands you go to mav-files/ only ([[file:name]] in a reply).
      "  edit:",
      '    "*": deny',
      '    "mav-files/*": allow',
      '    "*/mav-files/*": allow',
    );
  return `---\n${lines.join("\n")}\n---\n\n${body.trim()}\n`;
}
async function editAgent(name) {
  const isNew = !name;
  let text = "";
  if (!isNew && LIVE) {
    try {
      text =
        (await api.get(`config/agent-file?name=${encodeURIComponent(name)}`))
          .text || "";
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
          ${[
            ["all", "Me and the Assistant"],
            ["primary", "Only me"],
            ["subagent", "Only the Assistant"],
          ]
            .map(
              ([v, l]) =>
                `<option value="${v}" ${(parsed.meta.mode || "all") === v ? "selected" : ""}>${l}</option>`,
            )
            .join("")}
        </select></div>
        <div class="field"><label>Model (optional)</label><input name="model" value="${esc(parsed.meta.model || "")}" placeholder="same as Mav"></div>
      </div>
      ${AGENT_DIR ? `<p class="hint">Stored in <code>${esc(AGENT_DIR)}/${esc(name || "<name>")}.md</code></p>` : ""}
    </details>`;
  const actions = [];
  if (!isNew)
    actions.push({
      label: "Delete",
      kind: "btn-danger",
      left: true,
      run: async () => {
        if (
          !(await confirmDialog(
            `Delete “${agentDisplay(name)}”?`,
            "Chats with it are kept.",
            "Delete",
          ))
        )
          return false;
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
      const nm = isNew
        ? String(fd.get("name") || "")
            .trim()
            .toLowerCase()
            .replace(/\s+/g, "-")
        : name;
      if (!/^[a-z0-9][a-z0-9_-]{0,40}$/.test(nm)) {
        toast("Use letters and digits only for the name.", { error: true });
        return false;
      }
      const out = buildAgentFile(
        parsed.front,
        {
          description: String(fd.get("description") || "").trim(),
          mode: fd.get("mode"),
          model: String(fd.get("model") || "").trim(),
        },
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
  modal.open({
    title: isNew ? "New helper" : agentDisplay(name),
    body: form,
    actions,
    size: "wide",
  });
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
let MCP_STATUS = {};
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
  try {
    MCP_STATUS = (await api.get("config/mcp/status")).status || {};
  } catch (_) {}
  renderMcp();
}
let MAIL = { presets: [], configured: false };

async function loadMail() {
  if (!LIVE) return;
  let m = null;
  try {
    m = await api.get("mail/status");
  } catch (_) {}
  if (!m) return;
  MAIL = m;
  const sel = $("#mailProvider");
  const current = m.presets || [];
  sel.innerHTML = current
    .map((p) => `<option value="${esc(p.id)}">${esc(p.label)}</option>`)
    .join("");
  if (m.user) $("#mailUser").value = m.user;
  if (m.imap) $("#mailImap").value = m.imap;
  if (m.smtp) $("#mailSmtp").value = m.smtp;
  $("#mailPass").value = "";
  $("#mailPass").placeholder = m.has_password
    ? "leave blank to keep the current one"
    : "app password";
  setMailHint(sel.value);
  setMailStatus(
    m.configured
      ? "Connected as " + m.user
      : "Not configured — Mav cannot read or send mail yet.",
    m.configured ? "ok" : "",
  );
}
function setMailHint(presetId) {
  const p = (MAIL.presets || []).find((x) => x.id === presetId);
  $("#mailHint").textContent = p && p.hint ? p.hint : "";
}
function setMailStatus(text, kind) {
  const el = $("#mailStatus");
  el.textContent = text || "";
  el.classList.toggle("is-ok", kind === "ok");
  el.classList.toggle("is-err", kind === "err");
}
$("#mailProvider").addEventListener("change", (e) => {
  const p = (MAIL.presets || []).find((x) => x.id === e.target.value);
  if (p) {
    if (p.imap) $("#mailImap").value = p.imap;
    if (p.smtp) $("#mailSmtp").value = p.smtp;
  }
  setMailHint(e.target.value);
});
function mailFields() {
  return {
    imap: $("#mailImap").value.trim(),
    smtp: $("#mailSmtp").value.trim(),
    user: $("#mailUser").value.trim(),
    password: $("#mailPass").value,
  };
}
$("#mailTest").addEventListener("click", async () => {
  if (!needLive()) return;
  setMailStatus("Checking…", "");
  try {
    const r = await api.post("mail/test", mailFields());
    if (r.ok) setMailStatus("Both IMAP and SMTP work.", "ok");
    else
      setMailStatus(
        (r.errors || []).join(" · ") || "Connection failed.",
        "err",
      );
  } catch (err) {
    setMailStatus(err.message, "err");
  }
});
$("#mailSave").addEventListener("click", async () => {
  if (!needLive()) return;
  const f = mailFields();
  if (!f.imap || !f.smtp || !f.user)
    return setMailStatus("Fill the servers and your address.", "err");
  if (!f.password && !MAIL.has_password)
    return setMailStatus("Enter the password (or an app password).", "err");
  try {
    const r = await api.post("mail/save", f);
    if (r.error) throw new Error(r.error);
    await loadMail();
    toast("Mail saved.");
  } catch (err) {
    setMailStatus(err.message, "err");
  }
});
$("#mailForget").addEventListener("click", async () => {
  if (!needLive()) return;
  if (
    !(await confirmDialog(
      "Forget mail access?",
      "Mav will no longer read or send your mail.",
      "Forget",
    ))
  )
    return;
  try {
    await api.post("mail/forget", {});
    $("#mailUser").value = "";
    $("#mailImap").value = "";
    $("#mailSmtp").value = "";
    $("#mailPass").value = "";
    loadMail();
    toast("Mail access removed.");
  } catch (err) {
    toast(err.message, { error: true });
  }
});

let CATALOG = { items: [], runtimes: {} };
async function loadCatalog() {
  if (!LIVE) return renderCatalog();
  try {
    CATALOG = await api.get("config/mcp/catalog");
  } catch (_) {}
  renderCatalog();
}
const CAT_ICON = {
  Web: "globe",
  Everyday: "clock",
  "Notes & tasks": "edit",
  Home: "home",
  Work: "tool",
};
function renderCatalog() {
  const items = CATALOG.items || [];
  $("#mcpCatalog").innerHTML = items
    .map(
      (
        it,
      ) => `<button class="cat-item ${it.installed ? "is-added" : ""}" data-cat="${esc(it.id)}">
        <span class="cm-icon sm">${I(CAT_ICON[it.category] || "plug")}</span>
        <span class="cat-text"><strong>${esc(it.name)}</strong><span>${esc(it.description)}</span></span>
        <span class="badge ${it.installed ? "ok" : ""}">${it.installed ? "added" : it.ready ? "add" : "needs " + esc(it.runtime === "uvx" ? "uv" : "Node.js")}</span>
      </button>`,
    )
    .join("");
  const missing = Object.entries(CATALOG.runtimes || {})
    .filter(([, ok]) => !ok)
    .map(([r]) => r);
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
    (it.note
      ? `<div class="onboard soft"><span>${esc(it.note)}</span></div>`
      : "") +
    (it.inputs || [])
      .map(
        (inp) => `<div class="field"><label>${esc(inp.label)}</label>
          <input name="${esc(inp.key)}" ${inp.secret ? 'type="password" autocomplete="new-password"' : ""} placeholder="${esc(inp.placeholder || "")}" value="${esc(inp.default_from === "browser_timezone" ? tz : "")}">
          ${inp.help || inp.link ? `<small>${esc(inp.help || "")} ${inp.link ? `<a href="${esc(inp.link)}" target="_blank" rel="noopener">Get it here ↗</a>` : ""}</small>` : ""}</div>`,
      )
      .join("") +
    (!it.ready
      ? `<p class="status-text is-err">This one needs ${it.runtime === "uvx" ? "uv" : "Node.js"} on your server — see the hint below the list.</p>`
      : "") +
    (it.docs
      ? `<small><a href="${esc(it.docs)}" target="_blank" rel="noopener">How it works ↗</a></small>`
      : "");
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
          const status = (MCP_STATUS[n] || {}).status || "";
          const badge =
            status === "connected"
              ? `<span class="oauth-badge is-ok">${I("check")} connected</span>`
              : status === "needs_auth" ||
                  status === "needs_client_registration"
                ? `<span class="oauth-badge is-auth">${I("key")} sign-in needed</span>`
                : status === "failed" || status === "error"
                  ? `<span class="oauth-badge is-err">${I("x")} failed</span>`
                  : "";
          const connectBtn =
            remote && on
              ? status === "connected"
                ? `<button class="btn btn-ghost btn-sm" data-mcp-oauth="${esc(n)}">${I("key")} Reconnect</button>`
                : `<button class="btn btn-primary btn-sm" data-mcp-oauth="${esc(n)}">${I("key")} Connect</button>`
              : "";
          return `<div class="acard ${on ? "" : "is-off"}">
            <div class="acard-head"><span class="cm-icon sm">${I(remote ? "globe" : "plug")}</span><strong>${esc(n)}</strong>
              <button class="switch" role="switch" aria-checked="${on}" data-mcp-toggle="${esc(n)}" title="${on ? "Turn off" : "Turn on"}"></button></div>
            <p>${
              remote
                ? `Online service · ${esc(
                    String(s.url || "")
                      .replace(/^https?:\/\//, "")
                      .slice(0, 60),
                  )}`
                : "Runs on your server"
            } ${badge}</p>
            <div class="acard-foot">${connectBtn}<button class="btn btn-ghost btn-sm" data-mcp-edit="${esc(n)}">${I("edit")} Edit</button>
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
  const oa = e.target.closest("[data-mcp-oauth]");
  if (oa) {
    connectMcpOauth(oa.dataset.mcpOauth);
  } else if (t) {
    const n = t.dataset.mcpToggle;
    saveMcp({ ...MCP, [n]: { ...MCP[n], enabled: MCP[n].enabled === false } });
  } else if (d) {
    const n = d.dataset.mcpDel;
    if (
      !(await confirmDialog(
        `Remove “${n}”?`,
        "Mav won't be able to use it anymore.",
        "Remove",
      ))
    )
      return;
    const next = { ...MCP };
    delete next[n];
    saveMcp(next, "Removed.");
  } else if (ed) editMcp(ed.dataset.mcpEdit);
});
$("#mcpAdd").addEventListener("click", () => editMcp(null));

/* OAuth sign-in for remote MCP servers, without leaving the dashboard. */
async function connectMcpOauth(name) {
  if (!needLive()) return;
  if (
    !(await confirmDialog(
      `Connect \u201c${name}\u201d?`,
      "We'll open the service's sign-in page in a new tab. After you approve, paste the code it shows you back here.",
      "Open sign-in page",
      false,
    ))
  )
    return;
  let start;
  try {
    start = await api.post("config/mcp/oauth/start", { name });
  } catch (e) {
    return toast(e.message, { error: true });
  }
  if (start.authorizationUrl)
    window.open(start.authorizationUrl, "_blank", "noopener");
  const form = document.createElement("form");
  form.className = "form";
  form.innerHTML = `
    <p>Approve access in the tab that just opened, then copy the <strong>code</strong> it shows and paste it below.</p>
    <div class="field"><label>Authorization code</label>
      <input name="code" autocomplete="off" placeholder="paste the code or the full URL">
      <small>If the page only shows a URL, paste the whole URL \u2014 we'll extract the code.</small></div>`;
  form.addEventListener("submit", (e) => e.preventDefault());
  const code = await new Promise((resolve) => {
    let done = false;
    modal.open({
      title: `Sign in to \u201c${name}\u201d`,
      body: form,
      actions: [
        {
          label: "Open page again",
          run: () => {
            if (start.authorizationUrl)
              window.open(start.authorizationUrl, "_blank", "noopener");
            return false;
          },
        },
        {
          label: "Cancel",
          run: () => {
            done = true;
            resolve("");
          },
        },
        {
          label: "Connect",
          kind: "btn-primary",
          run: () => {
            done = true;
            resolve(String(new FormData(form).get("code") || "").trim());
          },
        },
      ],
      onClose: () => {
        if (!done) resolve("");
      },
    });
  });
  if (!code) return;
  setStatus("mcpStatus", "connecting\u2026");
  try {
    await api.post("config/mcp/oauth/callback", { name, code });
    changed(`\u201c${name}\u201d connected.`);
    setStatus("mcpStatus", "connected", "ok");
    loadMcp();
  } catch (e) {
    setStatus("mcpStatus", "connect failed", "err");
    toast(String(e.message).slice(0, 300), { error: true });
  }
}
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
    form
      .querySelectorAll("[data-t]")
      .forEach((b) => b.classList.toggle("is-active", b.dataset.t === t));
    form.querySelector("[data-local]").hidden = t !== "local";
    form.querySelector("[data-remote]").hidden = t !== "remote";
    form.querySelector("[data-envlabel]").textContent =
      t === "local"
        ? "Settings (environment variables)"
        : "Headers (e.g. Authorization)";
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
            entry.command = String(fd.get("command") || "")
              .trim()
              .split(/\s+/)
              .filter(Boolean);
            if (Object.keys(pairs).length) entry.environment = pairs;
          } else {
            entry.url = String(fd.get("url") || "").trim();
            if (Object.keys(pairs).length) entry.headers = pairs;
          }
          return saveMcp(
            { ...MCP, [nm]: entry },
            name ? "Saved." : "Connection added.",
          );
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
    `Mav ${v.installed}` +
    (v.update_available
      ? ` — ${v.latest} is available`
      : v.latest
        ? " — up to date"
        : "");
  $("#updatePill").hidden = !v.update_available && !v.updating;
  $("#updatePillText").textContent = v.updating
    ? "Updating…"
    : `Update to ${v.latest}`;
  if (force && !v.update_available)
    toast(
      v.latest
        ? `You have the latest version (${v.installed}).`
        : "Could not check for updates right now.",
    );
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
  if (v.runtime === "docker")
    return modal.open({
      title: `Update to ${v.latest}`,
      body: `<p>You have <strong>${esc(v.installed)}</strong>. Mav runs in Docker: update it from the machine that runs it, in the folder with <code>docker-compose.yml</code>. Your chats, memory, routines and settings are kept.</p>
        <pre class="code-block"><code>docker compose pull && docker compose up -d</code></pre>
        ${v.notes ? `<h3 class="sub">What's new</h3><div class="bubble release-notes">${mdToHtml(v.notes)}</div>` : ""}
        ${v.release_url ? `<small><a href="${esc(v.release_url)}" target="_blank" rel="noopener">Release page ↗</a></small>` : ""}`,
      actions: [{ label: "OK", kind: "btn-primary" }],
    });
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
    if (el && st.steps && st.steps.length)
      el.textContent = st.steps[st.steps.length - 1];
    if (!st.running && (seenDown || st.installed !== from)) {
      if (st.installed !== from) {
        toast(`Mav updated to ${st.installed}. Reloading…`);
        setTimeout(() => location.reload(), 1500);
      } else {
        modal.close();
        toast(
          "The update did not complete — see Settings → General → Advanced, or run: mav logs install",
          { error: true },
        );
        checkVersion();
      }
      return;
    }
  }
}

/* ---- General → Advanced ---- */
function renderEngine(e) {
  if (!e) return;
  $("#engineDot").className =
    "dot " + (e.online ? "ok" : e.active ? "warn" : "off");
  $("#engineLabel").textContent = e.online
    ? "Assistant running"
    : e.active
      ? "Assistant starting…"
      : "Assistant stopped";
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
      [
        "Helpers folder",
        AGENT_DIR || (c.config_path || "").replace(/opencode\.json$/, "agent"),
      ],
    ]
      .map(
        ([k, v]) =>
          `<div><span>${esc(k)}</span><span>${esc(v || "—")}</span></div>`,
      )
      .join("");
  } catch (_) {}
  loadMcp();
}
$("#engineRefresh").addEventListener("click", loadAdvanced);
$("#engineRestart").addEventListener("click", restartAssistant);
setInterval(() => {
  if (
    LIVE &&
    state.view === "settings" &&
    currentSettingsTab() === "general" &&
    $("#advanced").open &&
    !document.hidden
  )
    api
      .get("config/engine")
      .then(renderEngine)
      .catch(() => {});
}, 15000);

/* ================================================================
   13b. Debates — live multi-agent threads
   ================================================================ */
let debateTimer = null;
let debateOpenId = null;
let debateLastCount = 0;

function debateCard(t) {
  const authors = (t.authors || []).filter((a) => a !== "system");
  const faces = authors
    .slice(0, 5)
    .map(
      (a) =>
        `<span class="deb-avatar" title="${esc(agentDisplay(a))}">${esc(
          (agentDisplay(a)[0] || "?").toUpperCase(),
        )}</span>`,
    )
    .join("");
  return `<button class="deb-card" data-debate="${esc(t.id)}">
    <div class="deb-card-head">
      <strong>${esc(t.title || "Debate")}</strong>
      <span class="deb-meta">${t.messages} message${t.messages === 1 ? "" : "s"}${
        t.last_ts ? " · " + fmtRel(t.last_ts) : ""
      }</span>
    </div>
    <p class="deb-q">${esc((t.question || "").slice(0, 180))}</p>
    <div class="deb-foot">${faces}<span class="deb-open">${I("arrow")} open</span></div>
  </button>`;
}

async function loadDebates() {
  if (!$("#view-debates")) return;
  try {
    const r = await api.get("debates");
    const items = r.debates || [];
    $("#debatesLive").hidden = !items.length;
    $("#debateList").innerHTML = items.length
      ? items.map(debateCard).join("")
      : `<p class="hint">No debates yet. Ask Mav for one — “debate whether I should…” — and it will appear here.</p>`;
  } catch (_) {
    $("#debateList").innerHTML = `<p class="hint">Could not load debates.</p>`;
  }
}

async function openDebate(id) {
  debateOpenId = id;
  debateLastCount = 0;
  history.pushState(null, "", `#debates/${encodeURIComponent(id)}`);
  modal.open({
    title: "Debate",
    size: "wide",
    body: `<div class="deb-thread" id="debThread"><p class="hint">Loading…</p></div>`,
    actions: [{ label: "Close" }],
    onClose: () => {
      debateOpenId = null;
    },
  });
  await refreshDebate(id);
  clearInterval(debateTimer);
  debateTimer = setInterval(() => {
    if (debateOpenId && !document.hidden) refreshDebate(debateOpenId);
  }, 4000);
}

async function refreshDebate(id) {
  try {
    const r = await api.get(`debate?id=${encodeURIComponent(id)}`);
    const d = r.debate;
    if (!d) return;
    const el = $("#debThread");
    if (!el) {
      clearInterval(debateTimer);
      return;
    }
    const msgs = (d.messages || []).filter((m) => m.author !== "system");
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    el.innerHTML =
      `<div class="deb-question">
         <span class="deb-tag">Question</span>
         <p>${mdToHtml(d.question || "")}</p>
       </div>` +
      msgs
        .map(
          (m) => `<div class="deb-msg" style="--ac:${agentColor(m.author)}">
            <div class="deb-who">
              <span class="deb-avatar">${esc(
                (agentDisplay(m.author)[0] || "?").toUpperCase(),
              )}</span>
              <span>${esc(agentDisplay(m.author))}</span>
              <time>${fmtClock(m.ts)}</time>
            </div>
            <div class="deb-body">${mdToHtml(m.text || "")}</div>
          </div>`,
        )
        .join("");
    if (msgs.length !== debateLastCount || atBottom)
      el.scrollTop = el.scrollHeight;
    debateLastCount = msgs.length;
  } catch (_) {}
}

document.addEventListener("click", (e) => {
  const card = e.target.closest("[data-debate]");
  if (card) openDebate(card.dataset.debate);
});

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
$("#chatMic").addEventListener("click", () =>
  startDictation($("#chatMic"), "#chatInput"),
);
function speak(text, force = false) {
  if (!text || !("speechSynthesis" in window) || (!S.speak && !force)) return;
  const plain = text
    .replace(/```[\s\S]*?```/g, "")
    .replace(/[*_`#>|]/g, "")
    .slice(0, 900);
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
    if (perm !== "granted")
      return toast("Permission denied by the browser.", { error: true });
    const { key } = await api.get("push/key");
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlB64ToUint8Array(key),
    });
    await api.post("push/subscribe", sub.toJSON());
    setNotifyUi(true);
    toast("Notifications on.", {
      action: { label: "Send a test", run: () => $("#pushTest").click() },
    });
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

/* Backup and restore (dashboard/server/mav_backup.py). A restore asks for
   the password again: it rewrites keys, helpers and the password itself. */
$("#backupDownload").addEventListener("click", (e) => {
  if (!LIVE) {
    e.preventDefault();
    needLive();
  } else toast("Preparing your backup…");
});
$("#backupRestore").addEventListener("click", () => {
  if (needLive()) $("#backupFile").click();
});
$("#backupFile").addEventListener("change", () => {
  const file = $("#backupFile").files[0];
  $("#backupFile").value = "";
  if (!file) return;
  const body = document.createElement("div");
  body.innerHTML = `<p>Everything in Mav will be replaced by <strong>${esc(file.name)}</strong>:
      memory, routines, chats, helpers, settings and keys. A copy of the current state is kept on the server first.</p>
    <div class="field"><label>Your password</label><input type="password" id="restorePw" autocomplete="current-password"></div>`;
  modal.open({
    title: "Restore this backup?",
    size: "small",
    body,
    actions: [
      { label: "Cancel" },
      {
        label: "Restore",
        kind: "btn-danger",
        run: async (btn) => {
          btn.disabled = true;
          btn.textContent = "Restoring…";
          try {
            const r = await fetch("/api/backup/restore", {
              method: "POST",
              headers: { "Content-Type": "application/gzip", "X-Mav-Password": $("#restorePw").value },
              body: file,
            });
            const res = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(res.error || `Restore failed (${r.status}).`);
            const n = Object.values(res.tables || {}).reduce((a, b) => a + b, 0);
            toast(`Restored: ${res.files} files, ${n} memory entries. Reloading…`);
            setTimeout(() => location.reload(), 2500);
          } catch (err) {
            btn.disabled = false;
            btn.textContent = "Restore";
            toast(err.message, { error: true });
            return false;
          }
        },
      },
    ],
  });
});

/* Other channels: ntfy, Gotify, Discord, Slack (bot/occhannels.py). Secrets
   come back masked; leaving one masked keeps the stored value. */
const CHAN_FIELDS = {
  server: ["Server", { ntfy: "https://ntfy.sh", gotify: "https://gotify.example.org" }],
  topic: ["Topic", { ntfy: "a long, hard-to-guess name" }],
  token: ["Token", { ntfy: "only for a protected topic", gotify: "the application token" }],
  webhook: ["Webhook URL", { discord: "https://discord.com/api/webhooks/…", slack: "https://hooks.slack.com/services/…" }],
};
const CH = { types: {}, publicUrl: "" };
async function loadChannels() {
  if (!LIVE) return;
  try {
    const r = await api.get("channels");
    state.channels = r.channels || [];
    CH.types = r.types || {};
    CH.publicUrl = r.public_url || "";
  } catch (_) {
    return;
  }
  const box = $("#chanList");
  box.hidden = !state.channels.length;
  box.innerHTML = state.channels
    .map(
      (c) => `<div class="chan" data-id="${esc(c.id)}">
        <span class="chan-type">${esc((CH.types[c.type] || {}).label || c.type)}</span>
        <strong>${esc(c.name)}</strong>
        <span class="chan-acts">
          <button class="btn btn-ghost btn-sm" data-ch="test">Test</button>
          <button class="btn btn-ghost btn-sm" data-ch="edit">Edit</button>
          <button class="switch" role="switch" aria-label="Enabled" aria-checked="${c.enabled ? "true" : "false"}" data-ch="toggle"></button>
        </span></div>`,
    )
    .join("");
}
function editChannel(c) {
  const isNew = !c;
  const form = document.createElement("form");
  form.className = "form";
  const type = (c && c.type) || "ntfy";
  form.innerHTML = `
    <div class="field-grid">
      <div class="field"><label>Type</label><select name="type" ${isNew ? "" : "disabled"}>${Object.entries(CH.types)
        .map(([k, t]) => `<option value="${k}" ${k === type ? "selected" : ""}>${esc(t.label)}</option>`)
        .join("")}</select></div>
      <div class="field"><label>Name</label><input name="name" value="${esc((c && c.name) || "")}" placeholder="My phone"></div>
    </div>
    <div data-fields></div>
    <div class="field"><label>Address of this Mav</label>
      <input name="public_url" value="${esc(CH.publicUrl || location.origin)}" placeholder="https://mav.example.org">
      <small>Used for the “open” link in the notification.</small></div>`;
  const draw = () => {
    const t = form.querySelector("[name=type]").value;
    form.querySelector("[data-fields]").innerHTML = ((CH.types[t] || {}).fields || [])
      .map((f) => {
        const [label, ph] = CHAN_FIELDS[f] || [f, {}];
        const secret = f === "token" || f === "webhook";
        return `<div class="field"><label>${esc(label)}</label><input name="${f}" ${secret ? 'type="password" autocomplete="off"' : ""}
          value="${esc((c && c[f]) || "")}" placeholder="${esc(ph[t] || "")}"></div>`;
      })
      .join("");
  };
  draw();
  form.querySelector("[name=type]").addEventListener("change", draw);
  form.addEventListener("submit", (e) => e.preventDefault());
  const actions = [];
  if (!isNew)
    actions.push({
      label: "Delete",
      kind: "btn-danger",
      left: true,
      run: async () => {
        await api.post("channels/delete", { id: c.id }).catch(() => {});
        loadChannels();
      },
    });
  actions.push(
    { label: "Cancel" },
    {
      label: isNew ? "Add" : "Save",
      kind: "btn-primary",
      run: async () => {
        const fd = Object.fromEntries(new FormData(form));
        fd.type = form.querySelector("[name=type]").value;
        if (c) Object.assign(fd, { id: c.id, enabled: c.enabled });
        try {
          const r = await api.post("channels/save", fd);
          await loadChannels();
          if (isNew) {
            const t = await api.post("channels/test", { id: r.id }).catch((e) => ({ error: e.message }));
            toast(t.ok ? "Channel added — a test is on its way." : `Saved, but the test failed: ${t.error || "?"}`, {
              error: !t.ok,
            });
          } else toast("Channel saved.");
        } catch (err) {
          toast(err.message, { error: true });
          return false;
        }
      },
    },
  );
  modal.open({ title: isNew ? "Add a channel" : `Channel “${c.name}”`, body: form, actions });
}
$("#chanAdd").addEventListener("click", async () => {
  if (!needLive()) return;
  if (!Object.keys(CH.types).length) await loadChannels();
  editChannel(null);
});
$("#chanList").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-ch]");
  if (!b) return;
  const c = state.channels.find((x) => x.id === b.closest("[data-id]").dataset.id);
  if (!c) return;
  if (b.dataset.ch === "edit") return editChannel(c);
  if (b.dataset.ch === "toggle") {
    await api.post("channels/save", { ...c, enabled: !c.enabled }).catch((err) => toast(err.message, { error: true }));
    return loadChannels();
  }
  b.disabled = true;
  try {
    const r = await api.post("channels/test", { id: c.id });
    toast(r.ok ? `Test sent to ${c.name}.` : r.error, { error: !r.ok });
  } catch (err) {
    toast(err.message, { error: true });
  }
  b.disabled = false;
});
(async () => {
  try {
    if (
      !("serviceWorker" in navigator) ||
      !("Notification" in window) ||
      Notification.permission !== "granted"
    )
      return;
    const reg = await navigator.serviceWorker.ready;
    if (await reg.pushManager.getSubscription()) setNotifyUi(true);
  } catch (_) {}
})();
/* When an answer finishes while the tab is in the background. */
function notifyLocal(title, body) {
  try {
    if (Notification.permission === "granted")
      new Notification(`${title} answered`, {
        body: body.replace(/[*_`#>]/g, "").slice(0, 140),
        icon: "icons/icon-192.png",
      });
  } catch (_) {}
}

async function openNotifById(id) {
  if (!id || !LIVE) return;
  let n = null;
  try {
    n = (await api.get(`notification?id=${encodeURIComponent(id)}`))
      .notification;
  } catch (_) {}
  if (!n) return toast("Alert not found.");
  const m = (n.link || "").match(/#chat\/([^&?#]+)/);
  if (m) return tellMeMore(n);
  newChat();
  send(
    `Tell me more about this alert you sent me.\n\nTitle: ${n.title || ""}\nDetails: ${n.body || ""}\n\nWhat changed, why it matters, and what I could do. Be concrete and brief.`,
  );
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
  {
    text: "Keep an eye on a page, price or topic",
    ico: "eye",
    run: () => go("routines", "watch"),
  },
  {
    text: "Tell Mav something to remember",
    ico: "brain",
    run: () => {
      go("memory");
      $("#factInput").focus();
    },
  },
  { text: "Change the model", ico: "cpu", run: () => go("settings", "model") },
  {
    text: "Custom instructions",
    ico: "edit",
    run: () => go("settings", "instructions"),
  },
  {
    text: "Create a helper",
    ico: "user",
    run: () => {
      go("settings", "helpers");
      editAgent(null);
    },
  },
  {
    text: "Add a connection",
    ico: "plug",
    run: () => {
      go("settings", "connections");
      editMcp(null);
    },
  },
  { text: "Restart assistant", ico: "power", run: () => restartAssistant() },
  {
    text: "Check for updates",
    ico: "download",
    run: () => {
      go("settings", "general");
      checkVersion(true).then((v) => v && v.update_available && openUpdate());
    },
  },
  {
    text: "Toggle dark mode",
    ico: "moon",
    run: () => $("#themeToggle").click(),
  },
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
    .forEach((c) =>
      items.push({
        group: "Chats",
        text: c.title,
        ico: c.routine ? "bolt" : "chat",
        kind: fmtRel(c.updated),
        run: () => openChat(c.id),
      }),
    );
  state.agents
    .filter(
      (a) =>
        q && (a.includes(ql) || agentDisplay(a).toLowerCase().includes(ql)),
    )
    .forEach((a) =>
      items.push({
        group: "Helpers",
        text: `Talk to ${agentDisplay(a)}`,
        ico: "user",
        run: () => newChat(a),
      }),
    );
  PAL_ACTIONS.filter((a) => !q || a.text.toLowerCase().includes(ql)).forEach(
    (a) => items.push({ group: "Actions", ...a }),
  );
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
      (r.facts || []).slice(0, 4).forEach((f) =>
        palItems.push({
          group: "Memory",
          text: f.fact,
          ico: "brain",
          run: () => go("memory"),
        }),
      );
      (r.conversations || []).slice(0, 4).forEach((c) =>
        palItems.push({
          group: "Memory",
          text: c.question,
          ico: "clock",
          kind: fmtRel(c.ts),
          run: () => go("memory"),
        }),
      );
      drawPalette();
    } catch (_) {}
  }, 220);
}
function drawPalette() {
  if (!palItems.length) {
    $("#paletteResults").innerHTML =
      `<div class="pal-empty">Nothing found — press Enter to ask Mav.</div>`;
    return;
  }
  let g = null;
  $("#paletteResults").innerHTML = palItems
    .map((it, i) => {
      const head =
        it.group !== g ? `<div class="pal-group">${esc(it.group)}</div>` : "";
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
$("#paletteInput").addEventListener("input", (e) =>
  renderPalette(e.target.value.trim()),
);
$("#paletteInput").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (!palItems.length) return;
    palFocus =
      (palFocus + (e.key === "ArrowDown" ? 1 : -1) + palItems.length) %
      palItems.length;
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
  const typing =
    /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) ||
    e.target.isContentEditable;
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
  if (
    e.altKey &&
    (e.key === "ArrowUp" || e.key === "ArrowDown") &&
    state.convs.length
  ) {
    e.preventDefault();
    const i = state.convs.findIndex((c) => c.id === state.chat.id);
    const j = Math.max(
      0,
      Math.min(state.convs.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)),
    );
    openChat(state.convs[j].id);
    return;
  }
  if (e.key === "Escape") {
    if (!palette.hidden) return closePalette();
    if (!$("#modal").hidden) return modal.close();
    if (!$("#agentMenu").hidden) return closeAgentMenu();
    if (document.body.classList.contains("drawer-open")) return closeDrawer();
    if (isStreaming(state.chat.id)) {
      stopActive();
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
/* ---------- Demo content (no server: GitHub Pages, or the API is down) ----
   Realistic sample chats, routines, alerts and memory, so the public demo
   shows what Mav does. Nothing here is sent anywhere. */
const D_NOW = Date.now();
const dmin = (m) => D_NOW - m * 60e3;
const dTool = (id, name, input, output, ms, startMin, detail = "") => ({
  id, name, status: "completed", detail, title: "",
  input: JSON.stringify(input, null, 2), output, start: dmin(startMin), end: dmin(startMin) + ms,
});
const DEMO_ANSWERS = {
  lyon: `Here's a relaxed **Saturday in Lyon** — good food, walking, no crowds:

**Morning**
- ☕ Praline brioche at the Croix-Rousse market, then down the *traboules* to the old town.

**Afternoon**
- 🍽️ Lunch at a bouchon in Vieux-Lyon — book for 12:30, they fill up on Saturdays.
- 🚶 Up to Fourvière for the view, then down through the Jardin du Rosaire.

**Evening**
- 🌅 Sunset on the Saône quays, dinner at Les Halles Paul Bocuse.

**Weather:** 19 °C and sunny — no umbrella needed. **Budget:** about 70 € per person.

Want me to save this as a file, or make it a routine for your next free weekend?`,
  subs: `You're paying for **6 subscriptions — 74.94 € a month** (899 € a year).

| Service | Per month | Last used |
|---|---:|---|
| Netflix | 13.49 € | yesterday |
| Spotify | 10.99 € | today |
| iCloud 200 GB | 2.99 € | today |
| Gym | 29.90 € | **5 weeks ago** |
| Adobe Lightroom | 11.99 € | **3 months ago** |
| News app | 5.58 € | 2 weeks ago |

**My suggestion:** cancel Lightroom and pause the gym until you go back — that saves **41.89 € a month**, about 500 € a year.

[[file:subscriptions-2026.csv]]

I put the table in a CSV, and drafted both cancellation emails for you to check.`,
};
const DEMO_CHATS = {
  convs: [
    { id: "demo-lyon", title: "Saturday in Lyon", agent: "assistant", updated: dmin(12) },
    { id: "demo-subs", title: "Subscriptions check", agent: "money", updated: dmin(55) },
    { id: "demo-r-umbrella", title: "Routine · Umbrella", agent: "assistant", routine: true, updated: dmin(180) },
    { id: "demo-r-inbox", title: "Routine · Inbox", agent: "assistant", routine: true, updated: dmin(150) },
    { id: "demo-r-flight", title: "Routine · Flight to Lisbon", agent: "money", routine: true, updated: dmin(95) },
  ],
  threads: {
    "demo-lyon": [
      { role: "me", text: "I have a free weekend in Lyon, plan my Saturday", ts: dmin(13) },
      { role: "mav", agent: "assistant", ts: dmin(12), text: DEMO_ANSWERS.lyon, tools: [
        dTool("t1", "websearch", { query: "things to do in Lyon Saturday" }, "10 results — Croix-Rousse market, Vieux-Lyon bouchons, Fourvière, Saône quays…", 1180, 13, "things to do in Lyon Saturday"),
        dTool("t2", "webfetch", { url: "https://www.visiterlyon.com/" }, "# Visiter Lyon\n\nMarkets, traboules, bouchons and viewpoints…", 640, 13, "visiterlyon.com"),
        dTool("t3", "webfetch", { url: "https://wttr.in/Lyon?format=3" }, "Lyon: ☀️ +19°C", 410, 12, "wttr.in"),
      ] },
    ],
    "demo-subs": [
      { role: "me", text: "Check my subscriptions, what could I cancel?", ts: dmin(56) },
      { role: "mav", agent: "money", ts: dmin(55), text: DEMO_ANSWERS.subs, tools: [
        dTool("s1", "task", { subagent_type: "money", description: "Audit subscriptions" }, "6 subscriptions found, 2 unused for weeks.", 2300, 56, "money"),
        dTool("s2", "write", { filePath: "mav-files/subscriptions-2026.csv" }, "Wrote 7 lines.", 90, 55),
      ] },
    ],
    "demo-r-umbrella": [
      { role: "mav", agent: "assistant", ts: dmin(180), text: "☔ **Yes, take an umbrella today.** Showers from 4 pm in Lyon (80 % chance), 14 °C. The morning stays dry if you leave before 8:30." },
    ],
    "demo-r-inbox": [
      { role: "mav", agent: "assistant", ts: dmin(150), text: "📬 **3 emails need you today.**\n\n- **Landlord** — asks when the plumber can come in. I drafted a reply offering Thursday morning.\n- **Bank** — your card expires next month; the new one is on its way.\n- **Julie** — dinner on Friday? You're free from 7 pm.\n\nEverything else is newsletters and receipts." },
    ],
    "demo-r-flight": [
      { role: "mav", agent: "money", ts: dmin(95), text: "✈️ **Paris → Lisbon dropped to 89 €** (was 132 €) for 14–18 May, direct. That's below your 100 € target. Prices for these dates usually go back up within 48 h." },
    ],
  },
  jobs: [
    { name: "Daily briefing", kind: "briefing", prompt: "Weather, what happened, what needs me.", time: "07:30", days: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], agent: "assistant", enabled: true },
    { name: "Umbrella", description: "Do I need an umbrella today?", prompt: "Tell me if I need an umbrella today.", time: "07:00", days: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], agent: "assistant", enabled: true },
    { name: "Inbox", description: "What needs me in my inbox", prompt: "Check my inbox and tell me what needs me today.", time: "08:30", days: ["mon", "tue", "wed", "thu", "fri"], agent: "assistant", enabled: true },
    { name: "Flight to Lisbon", description: "Paris → Lisbon under 100 €", prompt: "Watch flight prices Paris → Lisbon, 14–18 May; tell me under 100 €.", every_minutes: 360, agent: "money", enabled: true },
    { name: "Weekly review", description: "Plan my week on Sunday evening", prompt: "Plan my week from my calendar and to-dos.", time: "19:00", days: ["sun"], agent: "planner", enabled: true },
  ],
  inbox: [
    { id: 0, topic: "routine", title: "🔁 Flight to Lisbon", body: "Paris → Lisbon dropped to 89 € (was 132 €) — below your 100 € target.", ts: dmin(95) / 1000, link: "#chat/demo-r-flight" },
    { id: 0, topic: "routine", title: "🔁 Inbox", body: "3 emails need you today. Landlord — asks when the plumber can come in…", ts: dmin(150) / 1000, link: "#chat/demo-r-inbox" },
    { id: 0, topic: "routine", title: "🔁 Umbrella", body: "Yes, take an umbrella today. Showers from 4 pm in Lyon (80 % chance).", ts: dmin(180) / 1000, link: "#chat/demo-r-umbrella" },
  ],
  facts: [
    "Lives in Lyon, works from home on Mondays and Fridays",
    "Vegetarian, loves Lebanese food",
    "Training for a half-marathon in June",
    "Prefers short answers",
    "Partner: Julie — anniversary on 12 June",
  ],
};

/* A demo reply: a few tool steps, then a canned answer that fits the ask. */
function demoAnswerFor(text) {
  const t = (text || "").toLowerCase();
  if (/weekend|saturday|trip|plan my|visit/.test(t))
    return { text: DEMO_ANSWERS.lyon, tools: DEMO_CHATS.threads["demo-lyon"][1].tools };
  if (/subscri|budget|spend|money|cancel/.test(t))
    return { text: DEMO_ANSWERS.subs, tools: DEMO_CHATS.threads["demo-subs"][1].tools };
  if (/weather|rain|umbrella/.test(t))
    return { text: DEMO_CHATS.threads["demo-r-umbrella"][0].text, tools: [dTool("w1", "webfetch", { url: "https://wttr.in/Lyon" }, "Lyon: 🌦 +14°C, rain from 16:00", 380, 0, "wttr.in")] };
  return {
    text: `This is the **live demo**, with sample data — nothing you type leaves your browser.\n\nOn your own Mav, the **${agentDisplay(currentAgent())}** would answer this with your model, your memory and your tools. Try *"plan my Saturday"*, *"check my subscriptions"* or *"do I need an umbrella?"* to see it work, or [install Mav](https://github.com/SoaOaoS/mav#install) in one command.`,
    tools: [],
  };
}

const DEMO = {
  agents: ["assistant", "researcher", "writer", "planner", "money"],
  info: {
    assistant: {
      description:
        "Your everyday assistant — answers directly, and calls in a helper when it helps",
    },
    researcher: {
      description:
        "Looks things up on the web, checks facts and compares options",
    },
    writer: {
      description: "Drafts and polishes emails, messages, posts and letters",
    },
    planner: { description: "Organises days, trips, projects and to-do lists" },
    money: {
      description: "Budgets, purchases, subscriptions and comparing offers",
    },
  },
  jobs: [
    {
      name: "Morning briefing",
      prompt: "Weather where I live and 3 headlines.",
      time: "07:30",
      days: ALL_DAYS,
      agent: "researcher",
      enabled: true,
    },
    {
      name: "Weekly meal plan",
      prompt: "5 simple dinners and a shopping list.",
      time: "10:00",
      days: ["sun"],
      agent: "planner",
      enabled: true,
    },
  ],
  inbox: [
    {
      id: 0,
      topic: "routine",
      title: "🔁 Morning briefing",
      body: "Sunny, 24°C — no umbrella needed. Headlines: …",
      ts: Date.now() / 1000 - 3600,
    },
    {
      id: 0,
      topic: "watch",
      title: "🏷️ Price change",
      body: "Price dropped: 129 → 99 EUR (-23%).",
      ts: Date.now() / 1000 - 8000,
    },
  ],
  presets: [
    {
      id: "anthropic",
      label: "Anthropic",
      hint: "Claude models. Needs an API key.",
      native: true,
      key: "required",
      model: "claude-sonnet-4-5",
    },
    {
      id: "openai",
      label: "OpenAI",
      hint: "GPT models. Needs an API key.",
      native: true,
      key: "required",
      model: "gpt-4o",
    },
    {
      id: "ollama",
      label: "Ollama (local)",
      hint: "Models on your own machine.",
      native: false,
      key: "optional",
      base: "http://localhost:11434/v1",
      model: "llama3.1",
    },
    {
      id: "custom",
      label: "Custom endpoint",
      hint: "Any OpenAI-compatible API.",
      native: false,
      key: "optional",
      base: "",
      model: "",
    },
  ],
};

async function loadAgentsList() {
  if (!LIVE) return;
  try {
    const d = await api.get("agents");
    state.agents = d.agents || [];
    state.agentInfo = d.details || {};
    state.defaultAgent = d.default || state.agents[0] || "";
    if (state.preferredAgent && !state.agents.includes(state.preferredAgent))
      state.preferredAgent = "";
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

function hideSplash() {
  const el = document.getElementById("splash");
  if (el) el.classList.add("is-done");
  document.body.classList.remove("is-loading");
}

/* ---------- Sign-in ----------
   First run: create the password that protects this Mav. Afterwards: sign in.
   The session is an HttpOnly cookie; the server answers 401 without it. */
let authMode = "";
function showAuthGate(mode) {
  if (authMode === mode) return;
  authMode = mode;
  const setup = mode === "setup";
  $("#authTitle").textContent = setup ? "Protect your Mav" : "Welcome back";
  $("#authLead").textContent = setup
    ? "Choose a password. Anyone who wants to open Mav — from this device or your phone — will need it."
    : "Enter your password to open Mav.";
  $("#authPassword").autocomplete = setup ? "new-password" : "current-password";
  $("#authPassword2").hidden = !setup;
  $("#authPassword2").required = setup;
  $("#authSubmit").textContent = setup ? "Set password and continue" : "Sign in";
  $("#authFoot").hidden = setup;
  $("#authError").hidden = true;
  $("#authGate").hidden = false;
  hideSplash();
  setTimeout(() => $("#authPassword").focus(), 50);
}
$("#authForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const pw = $("#authPassword").value;
  const err = $("#authError");
  err.hidden = true;
  if (authMode === "setup" && pw !== $("#authPassword2").value) {
    err.textContent = "The two passwords differ.";
    err.hidden = false;
    return;
  }
  $("#authSubmit").disabled = true;
  try {
    const r = await fetch(`/api/auth/${authMode === "setup" ? "setup" : "login"}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: pw }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || "Could not sign in.");
    location.reload();
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
    $("#authSubmit").disabled = false;
  }
});

$("#signOut").addEventListener("click", async () => {
  if (!needLive()) return;
  await api.post("auth/logout").catch(() => {});
  location.reload();
});
$("#passwordChange").addEventListener("click", () => {
  if (!needLive()) return;
  modal.open({
    title: "Change password",
    body: `<div class="field"><label>Current password</label><input type="password" id="pwCur" autocomplete="current-password"></div>
      <div class="field"><label>New password (8+ characters)</label><input type="password" id="pwNew" autocomplete="new-password"></div>
      <p class="hint">Every other device will have to sign in again.</p>`,
    actions: [
      { label: "Cancel" },
      {
        label: "Change password",
        kind: "btn-primary",
        run: async () => {
          try {
            await api.post("auth/password", {
              current: $("#pwCur").value,
              password: $("#pwNew").value,
            });
            toast("Password changed.");
          } catch (ex) {
            toast(ex.message, { error: true });
            return false;
          }
        },
      },
    ],
  });
});

/* ================================================================
   First-run welcome: model → about you → routines → first briefing.
   Shown once on a fresh install (the server says when); reopen it from
   Settings → General. Every step can be skipped.
   ================================================================ */
const OB = { step: 1, presets: [], sel: null, connected: false, templates: [], picked: new Set(), created: [] };
const OB_STEPS = 4;

async function maybeOnboard() {
  if (!LIVE) return;
  try {
    const o = await api.get("onboarding");
    if (!o.done) openOnboarding(o);
  } catch (_) {}
}

async function openOnboarding(info) {
  if (!needLive()) return;
  try {
    info = info || (await api.get("onboarding"));
  } catch (_) {
    info = {};
  }
  const langs = info.languages || { en: "English" };
  const guess = (navigator.language || "en").slice(0, 2).toLowerCase();
  $("#obLang").innerHTML = Object.entries(langs)
    .map(([k, v]) => `<option value="${esc(k)}" ${k === guess ? "selected" : ""}>${esc(v)}</option>`)
    .join("");
  if (info.briefing && info.briefing.time) $("#obBriefTime").value = info.briefing.time;
  await obLoadModel();
  try {
    OB.templates = ((await api.get(`job-templates?lang=${uiLang()}`)).templates || []).filter(
      (t) => t.id !== "morning-brief", // the daily briefing covers it
    );
  } catch (_) {
    OB.templates = [];
  }
  obRenderRoutines();
  $("#onboarding").hidden = false;
  document.body.classList.add("has-onboarding");
  hydrateIcons($("#onboarding"));
  obGo(1);
}

function obClose() {
  $("#onboarding").hidden = true;
  document.body.classList.remove("has-onboarding");
}

async function obFinish() {
  try {
    await api.post("onboarding", { done: true });
  } catch (_) {}
  obClose();
}

function obGo(n) {
  OB.step = n;
  $$("#onboarding .ob-step").forEach((s) => (s.hidden = Number(s.dataset.ob) !== n));
  $("#obSteps").innerHTML = Array.from({ length: OB_STEPS }, (_, i) =>
    `<i class="${i + 1 < n ? "is-done" : i + 1 === n ? "is-on" : ""}"></i>`,
  ).join("");
  $("#obBack").hidden = n === 1 || n === OB_STEPS;
  $("#obSkip").hidden = n === OB_STEPS;
  $("#obAlt").hidden = n !== OB_STEPS;
  $("#obMsg").textContent = "";
  $("#obMsg").className = "ob-msg";
  $("#obNext").disabled = false;
  $("#obNext").textContent =
    n === 1 ? (OB.connected ? "Continue" : "Connect") : n === OB_STEPS ? "Brief me now" : "Continue";
  const focus = $(`#onboarding .ob-step[data-ob="${n}"]`).querySelector("input:not([type=checkbox]):not([type=time]), select");
  if (focus && n !== 1) setTimeout(() => focus.focus(), 30);
}

/* Step 1 — model */
async function obLoadModel() {
  try {
    const d = await api.get("config/provider");
    // A custom endpoint needs more fields: that stays in Settings → Model.
    OB.presets = (d.presets || []).filter((p) => p.id !== "custom");
    const c = d.current || {};
    OB.connected = !!c.configured;
    OB.sel = OB.sel || c.preset || (OB.presets[0] || {}).id;
    $("#obModelReady").hidden = !OB.connected;
    $("#obModelReady").innerHTML = OB.connected
      ? `${I("check")}<span>Mav is connected to <strong>${esc(c.model || "")}</strong>. You can change it later in Settings.</span>`
      : "";
    $("#obModelForm").hidden = OB.connected;
  } catch (_) {
    OB.presets = [];
  }
  obRenderProviders();
}
function obRenderProviders() {
  $("#obProviders").innerHTML = OB.presets
    .map(
      (p) => `<button type="button" class="ob-prov ${p.id === OB.sel ? "is-sel" : ""}" data-obprov="${esc(p.id)}">
        <strong>${esc(p.label)}</strong><span>${esc(p.hint)}</span></button>`,
    )
    .join("");
  const p = OB.presets.find((x) => x.id === OB.sel);
  ["#obFBase", "#obFKey", "#obFModel"].forEach((id) => ($(id).hidden = !p));
  if (!p) return;
  $("#obFBase").hidden = p.native;
  $("#obBase").value = p.base || "";
  $("#obFKey").hidden = p.key === "none";
  $("#obKey").placeholder = p.key === "optional" ? "optional" : "paste your API key";
  $("#obModel").value = p.model || "";
  $("#obTestResult").textContent = "";
}
$("#obProviders").addEventListener("click", (e) => {
  const b = e.target.closest("[data-obprov]");
  if (!b) return;
  OB.sel = b.dataset.obprov;
  obRenderProviders();
});
function obProviderPayload() {
  return {
    provider: OB.sel,
    base_url: $("#obFBase").hidden ? "" : $("#obBase").value.trim(),
    api_key: $("#obKey").value.trim(),
    model: $("#obModel").value.trim(),
  };
}
$("#obTest").addEventListener("click", async () => {
  const out = $("#obTestResult");
  out.className = "";
  out.textContent = "Checking…";
  try {
    const r = await api.post("config/provider/test", obProviderPayload());
    if (r.ok) {
      $("#obModelList").innerHTML = r.models.map((m) => `<option value="${esc(m)}">`).join("");
      if (!$("#obModel").value && r.models.length) $("#obModel").value = r.models[0];
      out.className = "is-ok";
      out.textContent = `Connected — ${r.models.length} model${r.models.length === 1 ? "" : "s"} available.`;
    } else {
      out.className = "is-err";
      out.textContent = r.error || "Connection failed.";
    }
  } catch (e) {
    out.className = "is-err";
    out.textContent = e.message;
  }
});

/* Step 3 — routines */
function obRenderRoutines() {
  $("#obRoutines").innerHTML = OB.templates
    .map(
      (t) => `<label class="ob-routine ${OB.picked.has(t.id) ? "is-on" : ""}">
        <input type="checkbox" data-obtpl="${esc(t.id)}" ${OB.picked.has(t.id) ? "checked" : ""} />
        <span class="ob-ico">${esc(t.icon || "⚡")}</span>
        <span class="ob-txt"><strong>${esc(t.label)}</strong><span>${esc(t.description || "")}</span></span>
      </label>`,
    )
    .join("");
}
$("#onboarding").addEventListener("change", (e) => {
  const cb = e.target.closest('input[type="checkbox"]');
  if (!cb) return;
  if (cb.dataset.obtpl) cb.checked ? OB.picked.add(cb.dataset.obtpl) : OB.picked.delete(cb.dataset.obtpl);
  cb.closest(".ob-routine").classList.toggle("is-on", cb.checked);
});

/* Navigation */
async function obNext() {
  const btn = $("#obNext");
  const msg = $("#obMsg");
  msg.textContent = "";
  btn.disabled = true;
  try {
    if (OB.step === 1 && !OB.connected) {
      const p = obProviderPayload();
      if (!p.provider) throw new Error("Pick a provider.");
      if (!p.model) throw new Error("Choose a model (Check lists them).");
      msg.textContent = "Connecting…";
      const r = await api.post("config/provider", p);
      if (!r.ok) throw new Error(r.error || "Could not save the model.");
      if (r.restart && r.restart.ok) await waitForAssistant("Applying…");
      OB.connected = true;
      refreshStatus();
    } else if (OB.step === 2) {
      OB.lang = $("#obLang").value;
      try {
        OB.templates = ((await api.get(`job-templates?lang=${OB.lang}`)).templates || []).filter(
          (t) => t.id !== "morning-brief",
        );
        obRenderRoutines();
      } catch (_) {}
      const body = {
        name: $("#obName").value,
        city: $("#obCity").value,
        language: $("#obLang").value,
        interests: $("#obInterests").value,
      };
      if (body.name.trim() || body.city.trim() || body.interests.trim() || body.language !== "en")
        await api.post("onboarding/profile", body);
    } else if (OB.step === 3) {
      const r = await api.post("onboarding/routines", {
        templates: [...OB.picked],
        language: $("#obLang").value,
        briefing: { enabled: $("#obBrief").checked, time: $("#obBriefTime").value },
      });
      OB.created = r.created || [];
      const n = OB.created.length + ($("#obBrief").checked ? 1 : 0);
      $("#obSummary").textContent = n
        ? `${n} routine${n > 1 ? "s" : ""} set up${$("#obBrief").checked ? `, including your briefing at ${$("#obBriefTime").value}` : ""}. Want your first briefing right now?`
        : "Mav is ready. Ask it anything, or set up routines later from the Routines page.";
      $("#obNext").hidden = !$("#obBrief").checked;
      loadRoutines();
      loadBriefing();
    } else if (OB.step === OB_STEPS) {
      await obFinish();
      return briefMe();
    }
    obGo(OB.step + 1);
    if (OB.step === OB_STEPS) $("#obNext").hidden = !$("#obBrief").checked;
  } catch (e) {
    msg.textContent = e.message;
    msg.className = "ob-msg is-err";
  } finally {
    btn.disabled = false;
  }
}
$("#obNext").addEventListener("click", obNext);
$("#obBack").addEventListener("click", () => obGo(Math.max(1, OB.step - 1)));
$("#obSkip").addEventListener("click", obFinish);
$("#obAlt").addEventListener("click", async () => {
  await obFinish();
  newChat();
});
$("#obReopen").addEventListener("click", () => openOnboarding());

async function boot() {
  hydrateIcons();
  // The splash only stays for the real first load; a safety net dismisses it
  // after 2 s no matter what, so the app is never stuck behind it.
  setTimeout(hideSplash, 2000);
  let auth = null;
  try {
    const r = await fetch("/api/auth/state", { headers: { Accept: "application/json" } });
    if (r.ok) auth = await r.json();
  } catch (_) {}
  if (auth && auth.enabled && (auth.setup_needed || !auth.authenticated)) {
    LIVE = true;
    document.body.dataset.mode = "live";
    return showAuthGate(auth.setup_needed ? "setup" : "login");
  }
  if (auth && !auth.enabled) $("#accountRow").hidden = true;
  let status = null;
  try {
    status = await api.get("status");
  } catch (_) {}
  if (!status) {
    enterDemo();
    hideSplash();
    return;
  }
  LIVE = true;
  document.body.dataset.mode = "live";
  renderStatus(status);
  await Promise.allSettled([
    loadAgentsList(),
    loadConvs(),
    loadRoutines(),
    loadProactivity(),
    checkVersion(),
    loadBriefing(),
    loadChannels(),
  ]);
  route();
  if (!state.chat.id) renderThread();
  maybeOnboard();
  const notif = new URLSearchParams(location.search).get("notif");
  if (notif) {
    history.replaceState(null, "", location.pathname + location.hash);
    openNotifById(notif);
  }
  hideSplash();
}

function enterDemo() {
  LIVE = false;
  document.body.dataset.mode = "mock";
  state.agents = DEMO.agents;
  state.agentInfo = DEMO.info;
  state.defaultAgent = "assistant";
  state.jobs = DEMO_CHATS.jobs;
  state.inbox = DEMO_CHATS.inbox;
  state.convs = DEMO_CHATS.convs.map((c) => ({ ...c }));
  state.memory = {
    conversations: [],
    facts: DEMO_CHATS.facts.map((fact, i) => ({ id: i + 1, fact, ts: (D_NOW - (i + 1) * 86400e3) / 1000 })),
    preferences: [],
    backend: "demo",
  };
  $("#demoBanner").hidden = false;
  $("#demoPill").hidden = false;
  document.body.classList.add("has-demo-banner");
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
  if (state.view === "debates" && !debateOpenId) loadDebates();
}, 30000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && LIVE) {
    refreshStatus();
    loadConvs();
  }
});

/* In the demo there is no server to download from. */
document.addEventListener("click", (e) => {
  const a = e.target.closest("a.md-file");
  if (!a || LIVE) return;
  e.preventDefault();
  toast("In the demo there is no file to download — on your own Mav, this opens the file.");
});

/* ================================================================
   18. PWA: service worker + install banner
   ================================================================ */
if ("serviceWorker" in navigator && !document.documentElement.dataset.demo) {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("sw.js")
      .then((reg) => {
        reg.addEventListener("updatefound", () => {
          const sw = reg.installing;
          if (sw)
            sw.addEventListener("statechange", () => {
              if (
                sw.state === "installed" &&
                navigator.serviceWorker.controller
              )
                sw.postMessage("skip-waiting");
            });
        });
      })
      .catch(() => {});
    let reloaded = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      // Never reload in the middle of an answer.
      if (reloaded || anyStreaming()) return;
      reloaded = true;
      location.reload();
    });
    navigator.serviceWorker.addEventListener("message", (e) => {
      if (e.data && e.data.type === "open-notif" && e.data.id)
        openNotifById(String(e.data.id));
      if (e.data && e.data.type === "open-chat" && e.data.id)
        openChat(String(e.data.id));
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
if (
  /iphone|ipad|ipod/i.test(navigator.userAgent) &&
  !(
    window.matchMedia("(display-mode: standalone)").matches ||
    navigator.standalone
  ) &&
  store.get("mav-install-dismissed") !== "1"
) {
  banner.querySelector(".install-text span").textContent =
    "Tap Share, then “Add to Home Screen”.";
  $("#installBtn").textContent = "Got it";
  banner.hidden = false;
}

boot();
