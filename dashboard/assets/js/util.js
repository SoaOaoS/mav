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
