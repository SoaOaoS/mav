/* ============================================================
   Mav — companion UI
   LIVE mode: real API (/api/*) served by mav_api.py, with SSE streaming.
   Automatic MOCK fallback if the API is unreachable (GitHub Pages).
   ============================================================ */

/* ---------- Fallback data (mock) ---------- */
const MOCK = {
  connections: [
    { name: "Moteur opencode", state: "ok", label: "en ligne" },
    { name: "Memory store", state: "ok", label: "connected" },
    { name: "Telegram", state: "ok", label: "pont actif" },
  ],
  jobs: [
    {
      name: "Revue du matin",
      description: "Point technique avant 8h.",
      time: "08:00",
      days: ["mon", "tue", "wed", "thu", "fri"],
      agent: "research",
      enabled: true,
    },
    {
      name: "Market recap",
      description: "Macro and markets summary.",
      time: "09:00",
      days: ["mon", "tue", "wed", "thu", "fri"],
      agent: "research",
      enabled: true,
    },
  ],
  jobResults: [
    {
      name: "point-marche",
      updated: 0,
      text: "Cautious European open, indices +0.3%. Gold at $2,640/oz, oil steady. Takeaway: stay defensive on rates.",
    },
    {
      name: "revue-matin",
      updated: 0,
      text: "2 open PRs to review, CI green, no critical vulnerable dependency.",
    },
  ],
  agents: ["general", "dev", "research", "writer"],
  today: [
    { t: "09:00", text: "Daily brief sent." },
    { t: "08:00", text: "Inbox review done." },
  ],
  memory: { conversations: [], facts: [], preferences: [] },
  watch: { items: [] },
  proxmox: {
    available: true,
    nodes: [
      {
        name: "node-1",
        status: "online",
        cpu: 7,
        mem_pct: 34,
        disk_used: 42000000000,
        disk_total: 120000000000,
        uptime: 662853,
      },
    ],
    vms: [
      {
        vmid: 101,
        name: "app-server",
        status: "running",
        cpu: 12,
        mem: 4e9,
        maxmem: 16e9,
        node: "node-1",
      },
      {
        vmid: 102,
        name: "proxy",
        status: "running",
        cpu: 3,
        mem: 1e9,
        maxmem: 1e9,
        node: "node-1",
      },
    ],
    running: 2,
    total: 2,
  },
  replies: {
    status: "Everything is fine on my side.",
    automations: "Here are your automations.",
    memories: "I remember a few things.",
    watch: "I watch several sources.",
    default: ["Got it, on it.", "Noted.", "Alright."],
  },
};

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

let LIVE = false;
let STATUS = null;
const api = {
  async get(path) {
    const r = await fetch(`/api/${path}`, {
      headers: { Accept: "application/json" },
    });
    if (!r.ok) throw new Error(r.status);
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(`/api/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) throw new Error(r.status);
    return r.json();
  },
};

/* ---------- Utilitaires ---------- */
function fmtDays(days) {
  if (!days || !days.length) return "";
  const map = {
    mon: "lun",
    tue: "mar",
    wed: "mer",
    thu: "jeu",
    fri: "ven",
    sat: "sam",
    sun: "dim",
  };
  return days.map((d) => map[d] || d).join("–");
}
function fmtDate(ts) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "short",
  });
}
function fmtTime(ts) {
  if (ts && ts > 1e12) ts = Math.floor(ts / 1000);
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
  });
}
function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}
function fmtBytes(b) {
  if (!b) return "—";
  const g = b / 1e9;
  return g >= 1 ? `${g.toFixed(1)} Go` : `${Math.round(b / 1e6)} Mo`;
}
function fmtUptime(s) {
  if (!s) return "—";
  const d = Math.floor(s / 86400),
    h = Math.floor((s % 86400) / 3600);
  return d > 0 ? `${d}j ${h}h` : `${h}h`;
}
let toastTimer = null;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 2600);
}

/* ---------- Horloge ---------- */
function tick() {
  const n = new Date();
  $("#clock").textContent =
    `${String(n.getHours()).padStart(2, "0")}:${String(n.getMinutes()).padStart(2, "0")}`;
}
setInterval(tick, 1000);
tick();

/* ---------- Salutation ---------- */
function greet() {
  const h = new Date().getHours();
  if (h < 6) return "Good night";
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}
$("#greeting").textContent = greet();

/* ---------- Navigation ---------- */
function go(view) {
  $$(".nav-item, .tab").forEach((b) =>
    b.classList.toggle("is-active", b.dataset.view === view),
  );
  $$(".view").forEach((v) =>
    v.classList.toggle("is-active", v.id === `view-${view}`),
  );
  if (view === "system") loadInfra();
  if (view === "settings") loadSettings();
  setMobileTitle(view);
  window.scrollTo({ top: 0, behavior: "smooth" });
}
$$(".nav-item, .tab").forEach((b) =>
  b.addEventListener("click", () => go(b.dataset.view)),
);
$$("[data-goto]").forEach((b) =>
  b.addEventListener("click", () => go(b.dataset.goto)),
);

/* Mobile header: contextual title + quick actions */
const VIEW_TITLES = {
  home: "Mav",
  chat: "Conversations",
  jobs: "Automations",
  memory: "Memories",
  watch: "Watch",
  system: "Infra",
  settings: "Settings",
};
function setMobileTitle(view) {
  const t = $("#mobileTitle");
  if (t) t.textContent = VIEW_TITLES[view] || "Mav";
}
$("#mobileNew").addEventListener("click", () => newSession());
$("#mobileSearch").addEventListener("click", () => openPalette());

/* ---------- Rendu ---------- */
function renderStatus(st) {
  STATUS = st;
  if (!st) return;
  $("#greetingSub").textContent =
    st.mode === "mock" || st.agent_online === undefined
      ? "Demo preview — I connect to the agent when you open me from your network."
      : st.agent_online
        ? "I am online. Everything is calm on my side."
        : "My engine is not responding right now.";

  $("#stats").innerHTML = [
    { v: st.jobs_active ?? "—", k: "automatisations actives" },
    { v: st.conversations ?? "—", k: "stored exchanges" },
    { v: st.facts ?? "—", k: "faits retenus" },
    { v: st.watch_items ?? "—", k: "surveillances" },
  ]
    .map(
      (s) =>
        `<div class="stat"><div class="v">${esc(s.v)}</div><div class="k">${esc(s.k)}</div></div>`,
    )
    .join("");
}

function renderConnections(list) {
  $("#connList").innerHTML = list
    .map(
      (c) =>
        `<li><span class="st ${esc(c.state)}"></span>${esc(c.name)}<span class="lbl">${esc(c.label)}</span></li>`,
    )
    .join("");
}

function renderToday(items) {
  $("#today").innerHTML = (items || [])
    .map(
      (t) =>
        `<li><span class="t">${esc(t.t)}</span><span>${esc(t.text)}</span></li>`,
    )
    .join("");
}

function renderMiniJobs(jobs) {
  $("#homeJobs").innerHTML = (jobs || [])
    .slice(0, 3)
    .map(
      (j) => `
    <li>
      <span class="jname">${esc(j.name)}</span>
      <span class="jwhen">${j.every_minutes ? `${j.every_minutes} min` : esc(j.time)}</span>
      <span class="pill ${j.enabled ? "on" : "off"}">${j.enabled ? "actif" : "pause"}</span>
    </li>`,
    )
    .join("");
}

function renderJobResults(results) {
  const box = $("#jobResults");
  if (!box) return;
  const list = results || [];
  if (!list.length) {
    box.innerHTML = `<div class="jr-empty">No job result yet.</div>`;
    return;
  }
  box.innerHTML = list
    .map(
      (r) => `
    <div class="jr-item" data-jr>
      <div class="jr-head">
        <span class="jr-name">${esc(r.name)}</span>
        <span class="jr-time">${r.updated ? esc(fmtTime(r.updated)) + " · " + esc(fmtDate(Math.floor(r.updated / 1000))) : ""}</span>
      </div>
      <div class="jr-preview">${mdToHtml(r.text)}</div>
    </div>`,
    )
    .join("");
  mountCharts(box);
}

// Click a job result: expand / collapse the preview.
$("#jobResults").addEventListener("click", (e) => {
  const item = e.target.closest("[data-jr]");
  if (item) item.classList.toggle("is-open");
});

function renderJobs(jobs) {
  $("#jobsList").innerHTML = (jobs || [])
    .map(
      (j) => `
    <div class="job">
      <div class="jicon"><span class="nav-ico" data-ico="bolt"></span></div>
      <div>
        <div class="jtitle">${esc(j.name)}</div>
        <div class="jdesc">${esc(j.description || "")}${j.agent ? ` · agent ${esc(j.agent)}` : ""}</div>
      </div>
      <div class="job-actions">
        <div class="jtime">${j.every_minutes ? `${j.every_minutes} min` : esc(j.time)}<small>${esc(fmtDays(j.days))}${j.last_run ? ` · ${esc(j.last_run)}` : ""}</small></div>
        <button class="job-act" data-run="${esc(j.name)}">Lancer</button>
        <button class="job-act ${j.enabled ? "" : "off"}" data-toggle="${esc(j.name)}" data-enabled="${j.enabled ? "1" : "0"}">${j.enabled ? "Actif" : "Pause"}</button>
      </div>
    </div>`,
    )
    .join("");
  $("#navJobsCount").textContent = (jobs || []).filter((j) => j.enabled).length;
}

function renderMemory(mem) {
  const rows = [];
  (mem.conversations || []).forEach((c) =>
    rows.push({ date: fmtTime(c.ts), text: c.question, tag: "exchange" }),
  );
  (mem.facts || []).forEach((f) =>
    rows.push({ date: fmtDate(f.ts), text: f.fact, tag: "fait" }),
  );
  (mem.preferences || []).forEach((p) =>
    rows.push({
      date: fmtDate(p.ts),
      text: `${p.key} : ${p.value}`,
      tag: "preference",
    }),
  );
  if (!rows.length) {
    $("#memoryList").innerHTML =
      `<li><div class="mdate"></div><div class="mtext" style="color:var(--ink-3)">Nothing in memory yet.</div></li>`;
    return;
  }
  $("#memoryList").innerHTML = rows
    .map(
      (m) => `
    <li>
      <div class="mdate">${esc(m.date)}</div>
      <div><div class="mtext">${esc(m.text)}</div><span class="mtag">${esc(m.tag)}</span></div>
    </li>`,
    )
    .join("");
}

function renderWatch(watch) {
  const items = (watch && watch.items) || [];
  if (!items.length) {
    $("#watchList").innerHTML =
      `<div class="wcard"><div class="wtype">Watch</div><div class="wtarget">No active watch</div><div class="wstate"><span class="st"></span>idle</div></div>`;
    return;
  }
  $("#watchList").innerHTML = items
    .map((w) => {
      const changed = w.last_state && /chang|new|alert/i.test(w.last_state);
      return `
    <div class="wcard">
      <div class="wtype">${esc(w.kind)}</div>
      <div class="wtarget">${esc(w.target)}</div>
      <div class="wstate ${changed ? "changed" : ""}"><span class="st"></span>${changed ? "changed" : "stable"}${w.last_checked ? ` · ${esc(fmtTime(w.last_checked))}` : ""}</div>
      <button class="watch-rm" data-rm="${w.id}">Remove</button>
    </div>`;
    })
    .join("");
}

function renderInfra(px) {
  if (!px || !px.available) {
    $("#infraNodes").innerHTML =
      `<div class="node-card"><h3>Proxmox</h3><div class="node-row">Indisponible</div></div>`;
    $("#infraVms").innerHTML = "";
    return;
  }
  $("#infraNodes").innerHTML = (px.nodes || [])
    .map(
      (n) => `
    <div class="node-card">
      <h3>${esc(n.name)} <span class="vm-dot ${n.status === "online" ? "running" : "stopped"}"></span></h3>
      <div class="node-row"><span>CPU</span><span>${n.cpu}%</span></div>
      <div class="mini-bar"><i style="width:${Math.min(100, n.cpu)}%"></i></div>
      <div class="node-row"><span>Memory</span><span>${n.mem_pct}% · ${fmtBytes(n.mem_used)}/${fmtBytes(n.mem_total)}</span></div>
      <div class="mini-bar"><i style="width:${Math.min(100, n.mem_pct)}%"></i></div>
      <div class="node-row"><span>Uptime</span><span>${fmtUptime(n.uptime)}</span></div>
    </div>`,
    )
    .join("");
  const vms = px.vms || [];
  $("#infraVms").innerHTML = vms
    .map(
      (v) => `
    <div class="vm-card">
      <h4><span class="vm-dot ${v.status}"></span>${esc(v.name || "VM " + v.vmid)}</h4>
      <div class="node-row"><span>#${v.vmid} · ${esc(v.node || "")}</span><span>${esc(v.status)}</span></div>
      ${v.status === "running" ? `<div class="node-row"><span>CPU ${v.cpu}%</span><span>${fmtBytes(v.mem)}/${fmtBytes(v.maxmem)}</span></div>` : ""}
    </div>`,
    )
    .join("");
}

/* ---------- Actions jobs ---------- */
$("#jobsList").addEventListener("click", async (e) => {
  const run = e.target.closest("[data-run]");
  if (run) {
    if (!LIVE) return toast("Disponible sur le live uniquement.");
    try {
      await api.post("job/run", { name: run.dataset.run });
      toast(
        `Job "${run.dataset.run}" started — the report will land on Telegram.`,
      );
    } catch (_) {
      toast("Échec du lancement.");
    }
    return;
  }
  const tog = e.target.closest("[data-toggle]");
  if (tog) {
    if (!LIVE) return toast("Disponible sur le live uniquement.");
    const enabled = tog.dataset.enabled !== "1";
    try {
      await api.post("job/toggle", { name: tog.dataset.toggle, enabled });
      const j = await api.get("jobs");
      renderJobs(j.jobs || []);
      renderMiniJobs(j.jobs || []);
      toast(enabled ? "Automation enabled." : "Automation paused.");
    } catch (_) {
      toast("Échec.");
    }
  }
});

/* ---------- Watch: add / remove ---------- */
$("#watchForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!LIVE) return toast("Disponible sur le live uniquement.");
  const kind = $("#watchKind").value;
  const target = $("#watchTarget").value.trim();
  if (!target) return;
  try {
    await api.post("watch/add", { kind, target });
    $("#watchTarget").value = "";
    const w = await api.get("watch");
    renderWatch(w);
    toast("Watch item added.");
  } catch (_) {
    toast("Échec de l'ajout.");
  }
});
$("#watchList").addEventListener("click", async (e) => {
  const rm = e.target.closest("[data-rm]");
  if (!rm) return;
  try {
    await api.post("watch/remove", { id: Number(rm.dataset.rm) });
    renderWatch(await api.get("watch"));
    toast("Watch item removed.");
  } catch (_) {}
});

/* ---------- Search (memory) ---------- */
let searchTimer = null;
$("#memorySearch").addEventListener("input", (e) => {
  const q = e.target.value.trim();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    if (!q) return renderMemory(CACHED_MEMORY);
    if (!LIVE) return;
    try {
      const r = await api.get(`search?q=${encodeURIComponent(q)}`);
      renderSearchResults(r);
    } catch (_) {}
  }, 300);
});
function renderSearchResults(r) {
  const rows = [];
  (r.documents || []).forEach((d) =>
    rows.push({
      date: fmtDate(d.ts),
      text: d.excerpt || d.title,
      tag: "document",
    }),
  );
  (r.conversations || []).forEach((c) =>
    rows.push({ date: fmtTime(c.ts), text: c.question, tag: "exchange" }),
  );
  (r.facts || []).forEach((f) =>
    rows.push({ date: fmtDate(f.ts), text: f.fact, tag: "fait" }),
  );
  $("#memoryList").innerHTML = rows.length
    ? rows
        .map(
          (m) => `
      <li><div class="mdate">${esc(m.date)}</div>
      <div><div class="mtext">${esc(m.text)}</div><span class="mtag">${esc(m.tag)}</span></div></li>`,
        )
        .join("")
    : `<li><div class="mdate"></div><div class="mtext" style="color:var(--ink-3)">No result.</div></li>`;
}

/* ---------- Infra ---------- */
async function loadInfra() {
  if (!LIVE) return renderInfra(MOCK.proxmox);
  try {
    renderInfra(await api.get("proxmox"));
  } catch (_) {
    renderInfra(null);
  }
}

/* ---------- Settings: agent config (AGENTS.md + MCP) ---------- */
const engine = { timer: null };

function engineDot(online, active) {
  const cls = online ? "ok" : active ? "warn" : "off";
  return `<span class="engine-dot is-${cls}" id="engineDot"></span>`;
}

function renderEngine(e) {
  if (!e) return;
  const online = !!e.online;
  const active = !!e.active;
  const dot = $("#engineDot");
  if (dot)
    dot.className = `engine-dot is-${online ? "ok" : active ? "warn" : "off"}`;
  $("#engineLabel").textContent = online
    ? "Engine online"
    : active
      ? "Engine starting…"
      : "Engine offline";
  $("#engineMeta").innerHTML = [
    ["Service", esc(e.unit || "—")],
    ["Version", esc(e.version || "—")],
    ["Model", esc(e.model || "—")],
    ["Agents", String(e.agents ?? "—")],
    ["MCP servers", String(e.mcp ?? "—")],
  ]
    .map(
      ([k, v]) =>
        `<div class="engine-row"><span>${k}</span><span>${v}</span></div>`,
    )
    .join("");
}

async function loadEngine() {
  if (!LIVE) {
    renderEngine({ active: false, online: false, unit: "demo", model: "—" });
    return;
  }
  try {
    renderEngine(await api.get("config/engine"));
  } catch (_) {
    renderEngine({ active: false, online: false, unit: "?", model: "?" });
  }
}

async function loadAgents() {
  if (!LIVE) {
    $("#agentsPath").textContent = "demo";
    $("#agentsEditor").value =
      "# Agent instructions\n\n(editable when connected to a live engine)";
    return;
  }
  try {
    const d = await api.get("config/agents");
    $("#agentsPath").textContent = d.path || "";
    $("#agentsEditor").value = d.text || "";
    setStatus("agentsStatus", d.exists ? "loaded" : "new file", "ok");
  } catch (_) {
    setStatus("agentsStatus", "load failed", "err");
  }
}

async function loadMcp() {
  if (!LIVE) return;
  try {
    const d = await api.get("config/mcp");
    $("#mcpPath").textContent = d.path || "";
    const mcp = d.mcp || {};
    $("#mcpEditor").value = JSON.stringify(mcp, null, 2);
    renderMcpCards(mcp);
    setStatus("mcpStatus", `${Object.keys(mcp).length} server(s)`, "ok");
  } catch (_) {
    setStatus("mcpStatus", "load failed", "err");
  }
}

function renderMcpCards(mcp) {
  const keys = Object.keys(mcp);
  const box = $("#mcpCards");
  if (!keys.length) {
    box.innerHTML = `<div class="mcp-empty">No MCP server configured yet.</div>`;
    return;
  }
  box.innerHTML = keys
    .map((name) => {
      const s = mcp[name] || {};
      const type = s.type || (s.command ? "local" : s.url ? "remote" : "?");
      const enabled = s.enabled !== false;
      const detail =
        s.url ||
        (Array.isArray(s.command) ? s.command.join(" ") : s.command) ||
        "";
      return `
        <div class="mcp-card ${enabled ? "" : "is-off"}">
          <div class="mcp-card-head">
            <strong>${esc(name)}</strong>
            <span class="mcp-badge">${esc(type)}</span>
            <span class="mcp-state ${enabled ? "on" : "off"}">${enabled ? "enabled" : "disabled"}</span>
          </div>
          ${detail ? `<div class="mcp-detail">${esc(String(detail).slice(0, 140))}</div>` : ""}
        </div>`;
    })
    .join("");
}

function setStatus(id, text, kind) {
  const el = $("#" + id);
  if (!el) return;
  el.textContent = text;
  el.className = "editor-status" + (kind ? " is-" + kind : "");
  if (kind === "ok")
    setTimeout(() => {
      el.textContent = "";
    }, 2500);
}

async function saveAgents() {
  if (!LIVE) return toast("Not connected.");
  setStatus("agentsStatus", "saving…");
  try {
    await api.post("config/agents", { text: $("#agentsEditor").value });
    setStatus("agentsStatus", "saved", "ok");
    toast("AGENTS.md saved. Restart the engine to apply.");
  } catch (_) {
    setStatus("agentsStatus", "save failed", "err");
  }
}

async function saveMcp() {
  if (!LIVE) return toast("Not connected.");
  let mcp;
  try {
    mcp = JSON.parse($("#mcpEditor").value || "{}");
  } catch (e) {
    setStatus("mcpStatus", "invalid JSON", "err");
    return toast("Invalid JSON.");
  }
  setStatus("mcpStatus", "saving…");
  try {
    await api.post("config/mcp", { mcp });
    setStatus("mcpStatus", "saved", "ok");
    renderMcpCards(mcp);
    toast("MCP config saved. Restart the engine to connect them.");
  } catch (_) {
    setStatus("mcpStatus", "save failed", "err");
  }
}

async function restartEngine() {
  if (!LIVE) return toast("Not connected.");
  const btn = $("#engineRestart");
  btn.disabled = true;
  btn.textContent = "Restarting…";
  toast("Restarting the engine…");
  try {
    const r = await api.post("config/restart", {});
    if (!r.ok) {
      toast("Restart failed: " + (r.error || "?"));
      return;
    }
    // The restart is asynchronous: poll until the engine is back online.
    let tries = 0;
    const poll = setInterval(async () => {
      tries++;
      await loadEngine();
      const online = $("#engineDot").classList.contains("is-ok");
      if (online || tries >= 40) {
        clearInterval(poll);
        btn.disabled = false;
        btn.textContent = "Restart engine";
        toast(
          online
            ? "Engine back online."
            : "Engine did not come back — check the service.",
        );
      }
    }, 3000);
  } catch (_) {
    toast("Restart failed.");
    btn.disabled = false;
    btn.textContent = "Restart engine";
  }
}

function loadSettings() {
  loadEngine();
  loadAgents();
  loadMcp();
  loadAgentFiles();
}

/* ---------- Settings: user agent files ---------- */
let EDIT_AGENT = null;

async function loadAgentFiles() {
  if (!LIVE) return;
  try {
    const d = await api.get("config/agent-files");
    $("#agentFilesPath").textContent = d.dir || "";
    renderAgentCards(d.agents || []);
  } catch (_) {
    setStatus("agentFilesStatus", "load failed", "err");
  }
}

function renderAgentCards(agents) {
  const box = $("#agentCards");
  if (!agents.length) {
    box.innerHTML = `<div class="mcp-empty">No custom agent yet.</div>`;
    return;
  }
  box.innerHTML = agents
    .map(
      (a) => `
      <div class="agent-card" data-name="${esc(a.name)}">
        <div class="agent-card-head">
          <strong>${esc(a.name)}</strong>
          <span class="mcp-badge">${esc(a.mode || "subagent")}</span>
          <button class="ghost-btn agent-card-edit" data-edit="${esc(a.name)}">Edit</button>
        </div>
        ${a.description ? `<div class="mcp-detail">${esc(a.description)}</div>` : ""}
      </div>`,
    )
    .join("");
  box
    .querySelectorAll("[data-edit]")
    .forEach((b) =>
      b.addEventListener("click", () => editAgent(b.dataset.edit)),
    );
}

async function editAgent(name) {
  if (!LIVE) return;
  try {
    const d = await api.get(
      `config/agent-file?name=${encodeURIComponent(name)}`,
    );
    EDIT_AGENT = name;
    $("#agentEditName").textContent = d.path || name;
    $("#agentEditor").value = d.text || "";
    $("#agentEditorWrap").hidden = false;
    $("#agentDelete").hidden = false;
    $("#agentEditor").focus();
  } catch (_) {
    toast("Could not load the agent.");
  }
}

function newAgent() {
  EDIT_AGENT = "";
  $("#agentEditName").textContent = "new agent";
  $("#agentEditor").value =
    "---\ndescription: What this agent does\nmode: subagent\n---\n\nYou are…\n";
  $("#agentEditorWrap").hidden = false;
  $("#agentDelete").hidden = true;
  $("#agentEditor").focus();
}

async function saveAgent() {
  const name = (EDIT_AGENT || "").trim();
  if (!name) {
    // Derive the name from the filename field via a prompt fallback.
    const chosen = window.prompt("Agent name (a-z, 0-9, - _):", "");
    if (!chosen) return;
    EDIT_AGENT = chosen.trim().toLowerCase();
  }
  setStatus("agentFilesStatus", "saving…");
  try {
    await api.post("config/agent-file", {
      name: EDIT_AGENT,
      text: $("#agentEditor").value,
    });
    setStatus("agentFilesStatus", "saved", "ok");
    toast("Agent saved. Restart the engine to use it.");
    $("#agentEditorWrap").hidden = true;
    loadAgentFiles();
  } catch (_) {
    setStatus("agentFilesStatus", "save failed", "err");
  }
}

async function deleteAgent() {
  if (!EDIT_AGENT) return;
  if (!window.confirm(`Delete agent "${EDIT_AGENT}"?`)) return;
  try {
    await api.post("config/agent-file/delete", { name: EDIT_AGENT });
    toast("Agent deleted.");
    $("#agentEditorWrap").hidden = true;
    loadAgentFiles();
  } catch (_) {
    toast("Delete failed.");
  }
}

function initSettings() {
  $$(".settings-tab").forEach((t) =>
    t.addEventListener("click", () => {
      $$(".settings-tab").forEach((x) =>
        x.classList.toggle("is-active", x === t),
      );
      $$(".settings-panel").forEach((p) =>
        p.classList.toggle("is-active", p.id === `panel-${t.dataset.stab}`),
      );
    }),
  );
  $("#agentsSave").addEventListener("click", saveAgents);
  $("#agentsReload").addEventListener("click", loadAgents);
  $("#mcpSave").addEventListener("click", saveMcp);
  $("#mcpReload").addEventListener("click", loadMcp);
  $("#engineRestart").addEventListener("click", restartEngine);
  $("#engineRefresh").addEventListener("click", loadEngine);
  $("#agentNew").addEventListener("click", newAgent);
  $("#agentSave").addEventListener("click", saveAgent);
  $("#agentDelete").addEventListener("click", deleteAgent);
  $("#agentCancel").addEventListener("click", () => {
    $("#agentEditorWrap").hidden = true;
  });
  // Live engine status while the settings view is open.
  engine.timer = setInterval(() => {
    if (
      document.body.dataset.mode === "live" &&
      $("#view-settings").classList.contains("is-active")
    )
      loadEngine();
  }, 15000);
}

/* ---------- Agents (selector) ---------- */
let AGENTS = [];
let CURRENT_AGENT = "";
function renderAgentSelect() {
  const label = $("#chatAgentLabel");
  if (!label) return;
  label.innerHTML = `
    <button type="button" class="agent-btn" id="agentBtn" title="Choisir l'agent">
      <span class="agent-dot"></span>
      <span class="agent-name">${esc(CURRENT_AGENT || "agent")}</span>
      <span class="agent-caret">▾</span>
    </button>
    <div class="agent-menu" id="agentMenu" hidden>
      ${AGENTS.map(
        (a) =>
          `<button type="button" class="agent-opt ${a === CURRENT_AGENT ? "is-sel" : ""}" data-agent="${esc(a)}">${esc(a)}</button>`,
      ).join("")}
    </div>`;
  const btn = $("#agentBtn");
  const menu = $("#agentMenu");
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    menu.hidden = !menu.hidden;
    btn.classList.toggle("is-open", !menu.hidden);
  });
  menu.addEventListener("click", (e) => {
    const opt = e.target.closest("[data-agent]");
    if (!opt) return;
    CURRENT_AGENT = opt.dataset.agent;
    localStorage.setItem("mav-agent", CURRENT_AGENT);
    menu.hidden = true;
    btn.classList.remove("is-open");
    renderAgentSelect();
    toast(`Agent: ${CURRENT_AGENT} (applied to the next message)`);
  });
}
document.addEventListener("click", () => {
  const menu = $("#agentMenu");
  const btn = $("#agentBtn");
  if (menu) menu.hidden = true;
  if (btn) btn.classList.remove("is-open");
});

/* ---------- Chat & gestionnaire de sessions ---------- */
const messages = $("#messages");
let CURRENT_SESSION = null;
let CONVS = [];
let CACHED_MEMORY = { conversations: [], facts: [], preferences: [] };
let streaming = false;
let abortController = null;
let pendingFiles = [];

/* ---------- Mini markdown renderer (zero dependency) ----------
   Handles: ``` code blocks, tables, inline code, bold, italic,
   headings, lists, quotes, links, and line breaks. Escapes
   HTML first, to avoid any injection. */
function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Split a table row into cells (| a | b | -> [a, b]).
function splitRow(line) {
  let s = String(line).trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

// True if the line is a table separator (|---|---|).
function isTableSep(line) {
  const cells = splitRow(line);
  return cells.length > 0 && cells.every((c) => /^:?-{2,}:?$/.test(c));
}

function renderTable(lines) {
  const header = splitRow(lines[0]);
  const aligns = splitRow(lines[1]).map((c) => {
    if (/^:-+:$/.test(c)) return "center";
    if (/^:-+$/.test(c)) return "left";
    if (/^-+:$/.test(c)) return "right";
    return "";
  });
  const body = lines.slice(2).map(splitRow);

  const th = header
    .map(
      (c, i) =>
        `<th${aligns[i] ? ` class="md-${aligns[i]}"` : ""}>${inline(c)}</th>`,
    )
    .join("");
  const rows = body
    .map(
      (r) =>
        "<tr>" +
        header
          .map((_, i) => {
            const cell = r[i] == null ? "" : r[i];
            return `<td${aligns[i] ? ` class="md-${aligns[i]}"` : ""}>${inline(cell)}</td>`;
          })
          .join("") +
        "</tr>",
    )
    .join("");

  return `<div class="md-table-wrap"><table class="md-table"><thead><tr>${th}</tr></thead><tbody>${rows}</tbody></table></div>`;
}

// Rendu en ligne (gras, italique, code, liens, images).
// Échappe le HTML puis applique les transformations markdown.
function inline(s) {
  let t = escapeHtml(s);
  t = t.replace(/`([^`\n]+)`/g, '<code class="md-inline">$1</code>');
  t = t.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  t = t.replace(/__([^_\n]+)__/g, "<strong>$1</strong>");
  t = t.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  t = t.replace(/(^|[^_])_([^_\n]+)_/g, "$1<em>$2</em>");
  t = t.replace(/~~([^~\n]+)~~/g, "<del>$1</del>");
  t = t.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, src) => {
    const raw = src.replace(/&amp;/g, "&");
    const url = /^(https?:|data:image)/i.test(raw)
      ? raw
      : /^media:/i.test(raw)
        ? "/api/media/by-name?name=" + encodeURIComponent(raw.slice(6))
        : "/api/asset?path=" + encodeURIComponent(raw);
    return `<img class="md-img" src="${escapeHtml(url)}" alt="${alt}" loading="lazy">`;
  });
  t = t.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
  );
  return t;
}

function mdToHtml(src) {
  let text = String(src == null ? "" : src);

  // 0) Graphiques : directive [[chart:SYMBOL:RANGE]] ou bloc ```chart:...
  const charts = [];
  const pushChart = (symbol, range) => {
    const i = charts.length;
    charts.push({
      symbol: (symbol || "SPY").toUpperCase(),
      range: range || "1mo",
    });
    return `\u0000CHART${i}\u0000`;
  };
  text = text.replace(
    /\[\[\s*chart\s*:\s*([A-Za-z0-9.\-^=]+)\s*:\s*([A-Za-z0-9]+)\s*\]\]/gi,
    (_, s, r) => pushChart(s, r),
  );
  text = text.replace(
    /\[\[\s*chart\s*:\s*([A-Za-z0-9.\-^=]+)\s*\]\]/gi,
    (_, s) => pushChart(s, "1mo"),
  );
  text = text.replace(
    /```chart:([A-Za-z0-9.\-^=]+)(?::([A-Za-z0-9]+))?\n?([\s\S]*?)```/gi,
    (_, s, r) => `${pushChart(s, r)}\n`,
  );

  // 1) Code blocks: isolated before any processing (placeholders).
  const codeBlocks = [];
  text = text.replace(/```([\w-]*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    const i = codeBlocks.length;
    const cls = lang
      ? ` class="md-code lang-${escapeHtml(lang)}"`
      : ' class="md-code"';
    codeBlocks.push(
      `<pre${cls}><code>${escapeHtml(code.replace(/\n$/, ""))}</code></pre>`,
    );
    return `\u0000CODE${i}\u0000`;
  });

  const fmt = (s) => inline(s);

  // 2) Table: return the HTML rows of a table (or null if not a start).
  const renderTableAt = (lines, i) => {
    if (!/^\s*\|.*\|\s*$/.test(lines[i])) return null;
    if (i + 1 >= lines.length || !isTableSep(lines[i + 1])) return null;
    const block = [];
    let j = i;
    while (j < lines.length && /^\s*\|.*\|\s*$/.test(lines[j])) {
      block.push(lines[j]);
      j++;
    }
    return { html: renderTable(block), next: j };
  };

  // 3) Blocks: line-by-line parser (recursive level for quotes).
  const renderBlocks = (lines) => {
    let out = "";
    let para = [];
    const flushPara = () => {
      if (para.length) {
        out += `<p class="md-p">${para.join("<br>")}</p>`;
        para = [];
      }
    };

    let i = 0;
    while (i < lines.length) {
      const raw = lines[i];
      const line = raw.trim();

      if (!line) {
        flushPara();
        i++;
        continue;
      }

      // Placeholder de bloc de code.
      let m = line.match(/^\u0000CODE(\d+)\u0000$/);
      if (m) {
        flushPara();
        out += codeBlocks[Number(m[1])] || "";
        i++;
        continue;
      }
      // Placeholder de graphique.
      m = line.match(/^\u0000CHART(\d+)\u0000$/);
      if (m) {
        flushPara();
        const c = charts[Number(m[1])] || { symbol: "SPY", range: "1mo" };
        out += `<div class="md-chart" data-symbol="${escapeHtml(c.symbol)}" data-range="${escapeHtml(c.range)}"></div>`;
        i++;
        continue;
      }

      // Titres.
      m = raw.match(/^(#{1,6})\s+(.*)$/);
      if (m) {
        flushPara();
        const lvl = Math.min(m[1].length + 1, 6);
        out += `<h${lvl} class="md-h">${fmt(m[2])}</h${lvl}>`;
        i++;
        continue;
      }

      // Horizontal rule.
      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(raw)) {
        flushPara();
        out += '<hr class="md-hr">';
        i++;
        continue;
      }

      // Tableau.
      const t = renderTableAt(lines, i);
      if (t) {
        flushPara();
        out += t.html;
        i = t.next;
        continue;
      }

      // Citation (bloc de lignes > ...).
      if (/^\s*>\s?/.test(raw)) {
        flushPara();
        const inner = [];
        let j = i;
        while (j < lines.length && /^\s*>\s?/.test(lines[j])) {
          inner.push(lines[j].replace(/^\s*>\s?/, ""));
          j++;
        }
        out += `<blockquote class="md-quote">${renderBlocks(inner)}</blockquote>`;
        i = j;
        continue;
      }

      // List (bullets or ordered, with nesting).
      if (/^(\s*)([-*+]|\d+[.)])\s+/.test(raw)) {
        flushPara();
        const items = [];
        let j = i;
        while (j < lines.length && /^(\s*)([-*+]|\d+[.)])\s+/.test(lines[j])) {
          const mm = lines[j].match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
          const indent = mm[1].replace(/\t/g, "    ").length;
          items.push({
            indent,
            ordered: /^\d/.test(mm[2]),
            text: mm[3],
          });
          j++;
        }
        out += renderList(items, fmt);
        i = j;
        continue;
      }

      // Ligne de texte -> paragraphe.
      para.push(fmt(raw));
      i++;
    }
    flushPara();
    return out;
  };

  const html = renderBlocks(text.split("\n"));
  // Safety: no code placeholder must remain.
  return html.replace(
    /\u0000CODE(\d+)\u0000/g,
    (_, i) => codeBlocks[Number(i)] || "",
  );
}

// Table des listes : construit l'arbre depuis l'indentation puis rend le HTML.
function renderList(items, fmt) {
  const root = { children: [] };
  const stack = [{ indent: -1, node: root }];
  for (const it of items) {
    while (stack.length > 1 && it.indent <= stack[stack.length - 1].indent) {
      stack.pop();
    }
    const parent = stack[stack.length - 1].node;
    const node = { ordered: it.ordered, text: it.text, children: [] };
    parent.children.push(node);
    stack.push({ indent: it.indent, node });
  }
  return renderListNodes(root.children, fmt);
}

function renderListNodes(nodes, fmt) {
  let out = "";
  let i = 0;
  while (i < nodes.length) {
    const ordered = nodes[i].ordered;
    let j = i;
    while (j < nodes.length && nodes[j].ordered === ordered) j++;
    const tag = ordered ? "ol" : "ul";
    out += `<${tag} class="md-list">`;
    for (let k = i; k < j; k++) {
      const n = nodes[k];
      const inner = n.children.length ? renderListNodes(n.children, fmt) : "";
      out += `<li>${fmt(n.text)}${inner}</li>`;
    }
    out += `</${tag}>`;
    i = j;
  }
  return out;
}

/* ---------- Graphiques (lightweight-charts) ---------- */
function mountCharts(root) {
  if (typeof LightweightCharts === "undefined" || !root) return;
  root.querySelectorAll(".md-chart:not([data-mounted])").forEach((el) => {
    el.dataset.mounted = "1";
    const symbol = el.dataset.symbol;
    const range = el.dataset.range || "1mo";
    el.innerHTML = `<div class="md-chart-head"><span class="md-chart-sym">${escapeHtml(symbol)}</span><span class="md-chart-load">chargement…</span></div><div class="md-chart-body"></div>`;
    const body = el.querySelector(".md-chart-body");
    const load = el.querySelector(".md-chart-load");
    fetch(
      `/api/chart?symbol=${encodeURIComponent(symbol)}&range=${encodeURIComponent(range)}`,
    )
      .then((r) => r.json())
      .then((d) => {
        if (!d.candles || !d.candles.length) throw new Error("no data");
        const up = (d.pct ?? 0) >= 0;
        el.classList.toggle("is-up", up);
        el.classList.toggle("is-down", !up);
        const priceTxt =
          d.price != null
            ? d.price.toLocaleString("fr-FR", { maximumFractionDigits: 2 })
            : "—";
        const pctTxt = d.pct != null ? `${up ? "+" : ""}${d.pct}%` : "";
        el.querySelector(".md-chart-head").innerHTML =
          `<span class="md-chart-sym">${escapeHtml(d.name || symbol)}</span>` +
          `<span class="md-chart-price">${priceTxt} <em>${pctTxt}</em></span>`;
        drawChart(body, d);
      })
      .catch(() => {
        if (load) load.textContent = "indisponible";
        el.classList.add("md-chart-error");
      });
  });
}

function drawChart(container, d) {
  const line = d.candles.map((c) => ({ time: c.time, value: c.close }));
  const chart = LightweightCharts.createChart(container, {
    width: container.clientWidth || 300,
    height: 180,
    layout: {
      background: { type: "solid", color: "rgba(255,255,255,0)" },
      textColor: "#6b7a82",
      fontFamily: "Inter, sans-serif",
      fontSize: 11,
    },
    grid: {
      vertLines: { color: "rgba(0,0,0,0.04)" },
      horzLines: { color: "rgba(0,0,0,0.04)" },
    },
    rightPriceScale: {
      borderVisible: false,
      scaleMargins: { top: 0.15, bottom: 0.15 },
    },
    timeScale: { borderVisible: false, fixLeftEdge: true, fixRightEdge: true },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    handleScroll: false,
    handleScale: false,
  });
  const up = (d.pct ?? 0) >= 0;
  const color = up ? "#2f9d6f" : "#d9534f";
  const series = chart.addAreaSeries({
    lineColor: color,
    topColor: up ? "rgba(47,157,111,0.28)" : "rgba(217,83,79,0.28)",
    bottomColor: "rgba(255,255,255,0)",
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: true,
  });
  series.setData(line);
  chart.timeScale().fitContent();
  new ResizeObserver(() => {
    try {
      chart.applyOptions({ width: container.clientWidth });
    } catch (_) {}
  }).observe(container);
}

function addMsg(text, who) {
  const el = document.createElement("div");
  el.className = `msg ${who}`;
  el.innerHTML =
    who === "mav"
      ? `<div class="avatar"></div><div class="bubble"></div>`
      : `<div class="bubble"></div>`;
  const bubble = el.querySelector(".bubble");
  // Mav's answers are rendered as markdown; the user's
  // l'utilisateur restent en texte brut.
  if (who === "mav") {
    bubble.innerHTML = mdToHtml(text);
    mountCharts(bubble);
  } else {
    bubble.textContent = text;
  }
  messages.appendChild(el);
  messages.scrollTop = messages.scrollHeight;
  return bubble;
}

/* Lightbox : clic sur une image du fil pour l'agrandir. */
const lightbox = document.createElement("div");
lightbox.className = "lightbox";
lightbox.hidden = true;
lightbox.innerHTML = `<img alt="">`;
lightbox.addEventListener("click", () => (lightbox.hidden = true));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") lightbox.hidden = true;
});
messages.addEventListener("click", (e) => {
  const img = e.target.closest("img.md-img");
  if (!img) return;
  lightbox.querySelector("img").src = img.src;
  lightbox.hidden = false;
});
document.body.appendChild(lightbox);
function addToolNote(text) {
  const el = document.createElement("div");
  el.className = "tool-note";
  el.textContent = text;
  messages.appendChild(el);
  messages.scrollTop = messages.scrollHeight;
  return el;
}
function clearMessages() {
  messages.innerHTML = "";
}
function welcome() {
  clearMessages();
  addMsg("Hi. I am ready — tell me what you need.", "mav");
}
function setChatTitle(title) {
  $("#chatTitle").textContent = title || "New conversation";
}

function thinking(on) {
  document.body.classList.toggle("is-thinking", !!on);
}

function renderConvList() {
  if (!CONVS.length) {
    $("#convList").innerHTML = `<div class="conv-empty">No conversation.</div>`;
    return;
  }
  $("#convList").innerHTML = CONVS.map(
    (c) => `
    <div class="conv-item ${c.id === CURRENT_SESSION ? "is-active" : ""}" data-id="${esc(c.id)}">
      <span class="ctitle">${esc(c.title)}</span>
      <button class="cdel" data-del="${esc(c.id)}" title="Supprimer"><span class="nav-ico" data-ico="trash"></span></button>
    </div>`,
  ).join("");
}

async function loadConvs() {
  if (!LIVE) {
    CONVS = [{ id: "mock", title: "Demo conversation" }];
    CURRENT_SESSION = "mock";
    renderConvList();
    setChatTitle("Demo conversation");
    return;
  }
  try {
    CONVS = (await api.get("sessions")).sessions || [];
  } catch (_) {
    CONVS = [];
  }
  renderConvList();
}

async function openSession(id) {
  CURRENT_SESSION = id;
  renderConvList();
  if (!LIVE) return;
  try {
    const s = await api.get(`session?id=${encodeURIComponent(id)}`);
    setChatTitle(s.title);
    clearMessages();
    if (!s.messages || !s.messages.length) welcome();
    else s.messages.forEach((m) => addMsg(m.text, m.role));
  } catch (_) {
    welcome();
  }
}

async function newSession() {
  if (!LIVE) {
    CURRENT_SESSION = "mock";
    setChatTitle("New conversation");
    welcome();
    go("chat");
    return;
  }
  try {
    const s = await api.post("session/new", { agent: CURRENT_AGENT });
    CURRENT_SESSION = s.id;
    setChatTitle(s.title);
    welcome();
    await loadConvs();
    renderConvList();
    go("chat");
  } catch (_) {
    welcome();
  }
}

async function deleteSession(id) {
  if (!LIVE) return;
  try {
    await api.post("session/delete", { id });
    if (CURRENT_SESSION === id) {
      CURRENT_SESSION = null;
      setChatTitle("");
    }
    await loadConvs();
    if (!CURRENT_SESSION && CONVS.length) await openSession(CONVS[0].id);
    else if (!CONVS.length) newSession();
    else renderConvList();
  } catch (_) {}
}

async function renameSession() {
  if (!LIVE || !CURRENT_SESSION) return;
  const current = ($("#chatTitle").textContent || "").trim();
  const name = prompt("Renommer la discussion :", current);
  if (!name || !name.trim()) return;
  try {
    await api.post("session/rename", {
      id: CURRENT_SESSION,
      title: name.trim(),
    });
    setChatTitle(name.trim());
    await loadConvs();
  } catch (_) {}
}

$("#newConv").addEventListener("click", () => newSession());
$("#renameBtn").addEventListener("click", () => renameSession());
$("#convList").addEventListener("click", (e) => {
  const del = e.target.closest(".cdel");
  if (del) {
    e.stopPropagation();
    deleteSession(del.dataset.del);
    return;
  }
  const item = e.target.closest(".conv-item");
  if (item) openSession(item.dataset.id);
});

/* ---------- Export & summary ---------- */
$("#exportBtn").addEventListener("click", () => {
  if (!LIVE || !CURRENT_SESSION) return toast("Nothing to export.");
  window.location.href = `/api/session/export?id=${encodeURIComponent(CURRENT_SESSION)}`;
});
$("#summaryBtn").addEventListener("click", async () => {
  if (!LIVE || !CURRENT_SESSION) return;
  toast("Summarizing…");
  try {
    const r = await api.post("session/summary", { id: CURRENT_SESSION });
    addMsg("## Summary\n" + (r.summary || "…"), "mav");
  } catch (_) {
    toast("Summary failed.");
  }
});

/* ---------- Attachments ---------- */
function bindAttach(inputSel) {
  $(inputSel).addEventListener("change", async (e) => {
    for (const f of e.target.files) {
      const reader = new FileReader();
      reader.onload = async () => {
        const b64 = String(reader.result).split(",")[1];
        if (LIVE) {
          try {
            const up = await api.post("upload", {
              name: f.name,
              data: b64,
              mime: f.type,
            });
            pendingFiles.push(up);
          } catch (_) {
            toast("Upload failed.");
          }
        } else {
          pendingFiles.push({ filename: f.name, mime: f.type, url: "" });
        }
        renderAttachments();
      };
      reader.readAsDataURL(f);
    }
    e.target.value = "";
  });
}
function renderAttachments() {
  const box = $("#chatAttachments");
  if (!pendingFiles.length) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  box.hidden = false;
  box.innerHTML = pendingFiles
    .map(
      (f, i) =>
        `<span class="att-chip">${esc(f.filename)} <button data-rm-att="${i}">×</button></span>`,
    )
    .join("");
}
$("#chatAttachments").addEventListener("click", (e) => {
  const rm = e.target.closest("[data-rm-att]");
  if (rm) {
    pendingFiles.splice(Number(rm.dataset.rmAtt), 1);
    renderAttachments();
  }
});
bindAttach("#chatFileInput");
bindAttach("#heroFile");

/* ---------- Envoi (streaming) ---------- */
function setStreaming(on) {
  streaming = on;
  thinking(on);
  $("#sendBtn").hidden = on;
  $("#stopBtn").hidden = !on;
  if (!on) $("#typing").hidden = true;
}

async function send(raw, cmd) {
  const text = (raw || "").trim();
  if (!text && !cmd && !pendingFiles.length) return;
  const shown = text || cmd;
  if (shown) addMsg(shown, "me");

  if (!LIVE) {
    $("#typing").hidden = false;
    const key = (cmd || text || "").trim().toLowerCase();
    const pool = MOCK.replies[key] || MOCK.replies.default;
    const reply = Array.isArray(pool)
      ? pool[Math.floor(Math.random() * pool.length)]
      : pool;
    setTimeout(() => {
      $("#typing").hidden = true;
      addMsg(reply, "mav");
    }, 700);
    pendingFiles = [];
    renderAttachments();
    return;
  }

  const files = pendingFiles.slice();
  pendingFiles = [];
  renderAttachments();

  setStreaming(true);
  $("#typing").hidden = false;
  let bubble = null;
  let acc = "";

  const qs = new URLSearchParams({
    prompt: text || cmd || "(attachment)",
    session: CURRENT_SESSION || "",
    agent: CURRENT_AGENT || "",
  });
  if (files.length)
    qs.set(
      "files",
      JSON.stringify(
        files.map((f) => ({ url: f.url, mime: f.mime, filename: f.filename })),
      ),
    );

  try {
    const resp = await fetch(`/api/stream?${qs.toString()}`, {
      headers: { Accept: "text/event-stream" },
    });
    if (!resp.ok || !resp.body) throw new Error("flux indisponible");

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let sessionFromServer = null;
    let finished = false;

    const handle = (evName, data) => {
      if (evName === "start") {
        try {
          sessionFromServer = JSON.parse(data).session;
        } catch (_) {}
      } else if (evName === "delta") {
        let d = "";
        try {
          d = JSON.parse(data).delta || "";
        } catch (_) {}
        acc += d;
        if (!bubble) {
          $("#typing").hidden = true;
          bubble = addMsg("", "mav");
        }
        bubble.innerHTML = mdToHtml(acc);
        messages.scrollTop = messages.scrollHeight;
      } else if (evName === "done") {
        finished = true;
        try {
          const d = JSON.parse(data);
          if (!sessionFromServer && d.session) sessionFromServer = d.session;
          if (!acc && d.text) acc = d.text;
        } catch (_) {}
      } else if (evName === "error") {
        finished = true;
        let msg = "Je n'ai pas pu joindre mon moteur.";
        try {
          msg = "Erreur : " + JSON.parse(data).message;
        } catch (_) {}
        errorMsg = msg;
      }
    };

    let errorMsg = null;
    let terminal = false;
    while (!terminal) {
      let value, done;
      try {
        ({ value, done } = await reader.read());
      } catch (_) {
        // The server may close the connection right after the final event:
        // if we already have the result, that is not an error.
        break;
      }
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        let evName = "message";
        let dataLines = [];
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) evName = line.slice(6).trim();
          else if (line.startsWith("data:"))
            dataLines.push(line.slice(5).trim());
        }
        handle(evName, dataLines.join("\n"));
        if (evName === "done" || evName === "error") {
          terminal = true;
          break;
        }
      }
    }
    try {
      reader.cancel();
    } catch (_) {}

    if (sessionFromServer && sessionFromServer !== CURRENT_SESSION) {
      CURRENT_SESSION = sessionFromServer;
    }
    if (errorMsg) {
      addMsg(errorMsg, "mav");
    } else if (!acc) {
      addMsg("(no answer)", "mav");
    } else if (bubble) {
      bubble.innerHTML = mdToHtml(acc);
      mountCharts(bubble);
    } else {
      addMsg(acc, "mav");
    }
  } catch (_) {
    addMsg("Connexion interrompue.", "mav");
  } finally {
    setStreaming(false);
    if (S.shouldSpeak) speak(acc);
    await loadConvs();
  }
}

$("#stopBtn").addEventListener("click", async () => {
  if (!LIVE || !CURRENT_SESSION) return;
  try {
    await api.post("session/abort", { id: CURRENT_SESSION });
  } catch (_) {}
  setStreaming(false);
  toast("Stopped.");
});

$("#chatForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const i = $("#chatInput");
  send(i.value);
  i.value = "";
});
$("#heroForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const i = $("#heroInput");
  send(i.value);
  i.value = "";
  go("chat");
});
$$(".chip").forEach((c) =>
  c.addEventListener("click", () => {
    go("chat");
    send("", c.dataset.cmd);
  }),
);

/* ---------- Voice (dictation + read-aloud) ---------- */
const S = { shouldSpeak: false, recog: null };
function setupVoice() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SR) {
    const rec = new SR();
    rec.lang = "fr-FR";
    rec.interimResults = false;
    rec.continuous = false;
    S.recog = rec;
  }
}
setupVoice();

function startDictation(btn, inputSel) {
  if (!S.recog) return toast("Dictation not supported by this browser.");
  const input = $(inputSel);
  S.recog.onresult = (e) => {
    input.value = (input.value + " " + e.results[0][0].transcript).trim();
  };
  S.recog.onend = () => btn.classList.remove("is-rec");
  try {
    S.recog.start();
    btn.classList.add("is-rec");
  } catch (_) {
    btn.classList.remove("is-rec");
  }
}
$("#chatMic").addEventListener("click", () =>
  startDictation($("#chatMic"), "#chatInput"),
);
$("#heroMic").addEventListener("click", () =>
  startDictation($("#heroMic"), "#heroInput"),
);

function speak(text) {
  if (!text || !("speechSynthesis" in window)) return;
  const u = new SpeechSynthesisUtterance(text.slice(0, 600));
  u.lang = "fr-FR";
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
}
$("#voiceToggle").addEventListener("click", () => {
  S.shouldSpeak = !S.shouldSpeak;
  $("#voiceToggle").classList.toggle("is-on", S.shouldSpeak);
  if (!S.shouldSpeak) speechSynthesis.cancel();
  toast(S.shouldSpeak ? "Read-aloud enabled." : "Read-aloud disabled.");
});

/* ---------- Notifications (Web Push) ---------- */
const N = { enabled: false };
function urlB64ToUint8Array(b64) {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

// Sync the visual state of the push buttons (sidebar + mobile).
function setNotifyUi(on) {
  N.enabled = on;
  document
    .querySelectorAll("#notifyToggle, #mobileNotify")
    .forEach((el) => el.classList.toggle("is-on", on));
}

async function togglePushNotify() {
  if (!("Notification" in window) || !("serviceWorker" in navigator)) {
    return toast("Notifications not supported.");
  }
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
    return toast("Notifications disabled.");
  }
  try {
    const perm = await Notification.requestPermission();
    if (perm !== "granted") return toast("Permission denied.");
    const { key } = await api.get("push/key");
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlB64ToUint8Array(key),
    });
    await api.post("push/subscribe", sub.toJSON());
    setNotifyUi(true);
    toast("Notifications enabled.");
  } catch (_) {
    toast("Échec de l'activation.");
  }
}

$("#notifyToggle").addEventListener("click", togglePushNotify);
$("#mobileNotify").addEventListener("click", togglePushNotify);

// "Test" button: send an immediate push to check delivery.
const testBtn = $("#mobileNotifyTest");
if (testBtn) {
  testBtn.addEventListener("click", async () => {
    if (!N.enabled) return toast("Active d'abord les notifications (cloche).");
    try {
      const r = await api.post("push/test", {});
      toast(r.sent ? "Test push sent." : "No subscriber to send to.");
    } catch (_) {
      toast("Échec de l'envoi.");
    }
  });
}

// On load: reflect the real subscription state.
(async () => {
  try {
    if (!("serviceWorker" in navigator) || !("Notification" in window)) return;
    if (Notification.permission !== "granted") return;
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) setNotifyUi(true);
  } catch (_) {}
})();

/* ---------- Palette de commandes (⌘K) ---------- */
const palette = $("#palette");
function openPalette() {
  palette.hidden = false;
  $("#paletteInput").value = "";
  $("#paletteResults").innerHTML =
    `<div class="pal-item" data-pal-action="new-chat"><span class="pal-kind">Action</span><span class="pal-text">New conversation</span></div>
    <div class="pal-item" data-pal-view="jobs"><span class="pal-kind">Go</span><span class="pal-text">Automations</span></div>
    <div class="pal-item" data-pal-view="memory"><span class="pal-kind">Go</span><span class="pal-text">Memories</span></div>
    <div class="pal-item" data-pal-view="watch"><span class="pal-kind">Go</span><span class="pal-text">Watch</span></div>
    <div class="pal-item" data-pal-view="system"><span class="pal-kind">Go</span><span class="pal-text">Infra</span></div>`;
  $("#paletteInput").focus();
}
function closePalette() {
  palette.hidden = true;
}
$("#searchOpen").addEventListener("click", openPalette);
palette.addEventListener("click", (e) => {
  if (e.target === palette) closePalette();
});
window.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    palette.hidden ? openPalette() : closePalette();
  }
  if (e.key === "Escape") closePalette();
});

let palTimer = null;
$("#paletteInput").addEventListener("input", (e) => {
  const q = e.target.value.trim();
  clearTimeout(palTimer);
  palTimer = setTimeout(async () => {
    if (!q) return openPalette();
    const items = [];
    CONVS.filter((c) =>
      c.title.toLowerCase().includes(q.toLowerCase()),
    ).forEach((c) =>
      items.push({
        kind: "Conversation",
        text: c.title,
        action: "open",
        id: c.id,
      }),
    );
    if (LIVE) {
      try {
        const r = await api.get(`search?q=${encodeURIComponent(q)}`);
        (r.facts || []).forEach((f) =>
          items.push({ kind: "Souvenir", text: f.fact }),
        );
        (r.documents || []).forEach((d) =>
          items.push({ kind: "Document", text: d.title }),
        );
      } catch (_) {}
    }
    $("#paletteResults").innerHTML = items.length
      ? items
          .slice(0, 20)
          .map(
            (i) =>
              `<div class="pal-item" ${i.action === "open" ? `data-pal-open="${esc(i.id)}"` : ""}><span class="pal-kind">${esc(i.kind)}</span><span class="pal-text">${esc(i.text)}</span></div>`,
          )
          .join("")
      : `<div class="pal-empty">No result.</div>`;
  }, 250);
});
$("#paletteResults").addEventListener("click", (e) => {
  const open = e.target.closest("[data-pal-open]");
  if (open) {
    closePalette();
    go("chat");
    openSession(open.dataset.palOpen);
    return;
  }
  const view = e.target.closest("[data-pal-view]");
  if (view) {
    closePalette();
    go(view.dataset.palView);
    return;
  }
  const act = e.target.closest("[data-pal-action]");
  if (act) {
    closePalette();
    newSession();
  }
});

welcome();
initSettings();

/* ---------- Chargement ---------- */
async function loadLive() {
  // Only the "status" probe decides whether we are live. Other calls fail
  // independently: a slow endpoint must not switch the whole UI to demo mode.
  let status = null;
  try {
    status = await api.get("status");
  } catch (_) {
    status = null;
  }

  if (!status) {
    enterMock();
    return;
  }

  LIVE = true;
  document.body.dataset.mode = "live";
  renderStatus(status);

  const soft = async (path, fn) => {
    try {
      fn(await api.get(path));
    } catch (_) {
      /* endpoint secondaire indisponible : on garde le reste */
    }
  };

  await Promise.all([
    soft("connections", (d) => renderConnections(d.connections || [])),
    soft("jobs", (d) => {
      renderJobs(d.jobs || []);
      renderMiniJobs(d.jobs || []);
    }),
    soft("job-results", (d) => renderJobResults(d.results || [])),
    soft("memory", (d) => {
      CACHED_MEMORY = d;
      renderMemory(d);
    }),
    soft("watch", (d) => renderWatch(d)),
    soft("agents", (d) => {
      AGENTS = d.agents || [];
      CURRENT_AGENT = localStorage.getItem("mav-agent") || AGENTS[0] || "";
      renderAgentSelect();
    }),
  ]);

  renderToday([{ t: "—", text: "Connected to the agent engine, live." }]);

  try {
    await loadConvs();
    if (CONVS.length) await openSession(CONVS[0].id);
    else await newSession();
  } catch (_) {
    CURRENT_SESSION = "";
    renderConvList();
  }

  // A notification was tapped: open a dedicated conversation and
  // ask for the alert detail.
  await maybeOpenNotif();
}

function notifParam() {
  try {
    return new URLSearchParams(location.search).get("notif");
  } catch (_) {
    return null;
  }
}

async function maybeOpenNotif() {
  const id = notifParam();
  if (!id) return;
  // Nettoie l'URL pour ne pas rejouer au prochain rechargement.
  try {
    history.replaceState(null, "", location.pathname);
  } catch (_) {}
  await openNotifById(id);
}

async function openNotifById(id) {
  if (!id || !LIVE) return;
  let n = null;
  try {
    n = (await api.get(`notification?id=${encodeURIComponent(id)}`))
      .notification;
  } catch (_) {}
  if (!n) {
    go("chat");
    toast("Alerte introuvable.");
    return;
  }
  await newSession();
  setChatTitle("Alerte · " + String(n.title || "").slice(0, 40));
  const topic =
    n.topic === "watch" ? "de veille" : n.topic === "job" ? "de job" : "";
  const prompt =
    `Give me the details of this ${topic} alert you sent me.\n\n` +
    `Titre : ${n.title || ""}\n` +
    `Info : ${n.body || ""}\n\n` +
    "Explain the context, why it matters, and what to watch next. " +
    "Sois concret et bref.";
  go("chat");
  await send(prompt, null);
}

function enterMock() {
  LIVE = false;
  document.body.dataset.mode = "mock";
  renderStatus({
    mode: "mock",
    jobs_active: MOCK.jobs.filter((j) => j.enabled).length,
    conversations: "—",
    facts: "—",
    watch_items: "—",
  });
  renderConnections(MOCK.connections);
  renderJobs(MOCK.jobs);
  renderMiniJobs(MOCK.jobs);
  renderJobResults(MOCK.jobResults);
  CACHED_MEMORY = MOCK.memory;
  renderMemory(MOCK.memory);
  renderWatch(MOCK.watch);
  renderToday(MOCK.today);
  AGENTS = MOCK.agents;
  CURRENT_AGENT = AGENTS[0];
  renderAgentSelect();
  CURRENT_SESSION = "mock";
  renderConvList();
}
loadLive();

/* ---------- PWA : service worker + installation ---------- */
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("sw.js")
      .then((reg) => {
        // A new SW version is found: take over immediately.
        reg.addEventListener("updatefound", () => {
          const sw = reg.installing;
          if (sw)
            sw.addEventListener("statechange", () => {
              if (
                sw.state === "installed" &&
                navigator.serviceWorker.controller
              ) {
                sw.postMessage("skip-waiting");
              }
            });
        });
      })
      .catch(() => {});
    // When the SW takes over, reload once to serve the fresh version.
    let reloaded = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (reloaded) return;
      reloaded = true;
      location.reload();
    });
    // Le SW signale un clic sur une notification alors que l'app est ouverte.
    navigator.serviceWorker.addEventListener("message", (e) => {
      if (e.data && e.data.type === "open-notif" && e.data.id) {
        openNotifById(String(e.data.id));
      }
    });
  });
}
let deferredPrompt = null;
const banner = $("#installBanner");
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferredPrompt = e;
  if (localStorage.getItem("mav-install-dismissed") !== "1")
    banner.hidden = false;
});
$("#installBtn").addEventListener("click", async () => {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  try {
    await deferredPrompt.userChoice;
  } catch (_) {}
  deferredPrompt = null;
  banner.hidden = true;
});
$("#installClose").addEventListener("click", () => {
  banner.hidden = true;
  localStorage.setItem("mav-install-dismissed", "1");
});
window.addEventListener("appinstalled", () => {
  banner.hidden = true;
});
const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
const isStandalone =
  window.matchMedia("(display-mode: standalone)").matches ||
  navigator.standalone === true;
if (
  isIOS &&
  !isStandalone &&
  localStorage.getItem("mav-install-dismissed") !== "1"
) {
  const s = banner.querySelector(".install-text span");
  if (s) s.textContent = 'Tap Share then "Add to Home Screen".';
  $("#installBtn").textContent = "Compris";
  $("#installBtn").addEventListener(
    "click",
    () => {
      banner.hidden = true;
      localStorage.setItem("mav-install-dismissed", "1");
    },
    { once: true },
  );
  banner.hidden = false;
}

/* Refresh the status */
setInterval(async () => {
  if (!LIVE) return;
  try {
    renderStatus(await api.get("status"));
  } catch (_) {}
}, 20000);
