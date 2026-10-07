/* Mav web app — State, navigation, the helper picker and the chat list.
   One of the classic scripts index.html loads in order (2/12); they share
   one global scope, like the single app.js they came from. */

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
