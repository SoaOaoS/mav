/* Mav web app — Settings: connections, versions and updates, advanced.
   One of the classic scripts index.html loads in order (9/12); they share
   one global scope, like the single app.js they came from. */

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
