/* Mav web app — Settings: usage, model, helpers, custom instructions.
   One of the classic scripts index.html loads in order (8/12); they share
   one global scope, like the single app.js they came from. */

/* ================================================================
   12. Settings
   ================================================================ */
function currentSettingsTab() {
  const a = $("[data-stab].is-active");
  return a ? a.dataset.stab : isOwner() && !MODEL_MANAGED ? "model" : "general";
}
function openSettingsTab(tab) {
  if (tab === "agents") tab = "helpers";
  if (tab === "system" || tab === "advanced") {
    tab = "general";
    $("#advanced").open = true;
  }
  if (!$(`#spanel-${tab}`)) tab = "model";
  if (!isOwner()) tab = "general"; // the rest is the owner's
  if (tab === "model" && MODEL_MANAGED) tab = "general"; // the plan's model
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
        if (!isOwner()) return;
        loadCode();
        loadAdvanced();
        checkVersion();
        loadFamily();
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
  renderSpeed(u.speed || {});
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
function renderSpeed(sp) {
  $("#speedCard").hidden = !sp.answers;
  if (!sp.answers) return;
  $("#speedTtft").textContent = sp.ttft_ms != null ? fmtSeconds(sp.ttft_ms) : "—";
  $("#speedTotal").textContent = sp.total_ms != null ? fmtSeconds(sp.total_ms) : "—";
  $("#speedSteps").textContent = sp.steps != null ? String(sp.steps) : "—";
  $("#speedIn").textContent = sp.input_tokens != null ? `${compact(sp.input_tokens)} tokens` : "—";
  const bits = [`${sp.answers} answer${sp.answers > 1 ? "s" : ""} measured`];
  if (sp.ttft_p90_ms != null && sp.answers >= 10) bits.push(`9 in 10 start within ${fmtSeconds(sp.ttft_p90_ms)}`);
  if (sp.cached_pct != null) bits.push(`${sp.cached_pct} % of the prompt came from the provider's cache`);
  $("#speedHint").textContent = bits.join(" · ") + ".";
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

/* Code and commands: Mav's code tools (the "code" connection). Self-hosted,
   the owner turns them on knowingly; in Mav Cloud they run in the person's
   own sandbox and are always on. */
async function loadCode() {
  if (!LIVE) return;
  let c;
  try {
    c = await api.get("config/code");
  } catch (_) {
    return;
  }
  $("#codeRow").hidden = false;
  const sw = $("#codeSwitch");
  sw.setAttribute("aria-checked", String(!!c.enabled));
  sw.disabled = !!c.managed;
  $("#codeText").textContent = c.managed
    ? "On: Mav runs Python and shell commands in your own sandbox, which holds none of your keys or data."
    : c.enabled
      ? `On: Mav runs Python and shell commands on this machine, in ${c.dir}.`
      : "Lets Mav run Python and shell commands on this machine, to compute, convert and build files for you.";
}
$("#codeSwitch").addEventListener("click", async () => {
  const sw = $("#codeSwitch");
  if (sw.disabled) return;
  const on = sw.getAttribute("aria-checked") !== "true";
  if (
    on &&
    !(await confirmDialog(
      "Let Mav run code on this machine?",
      "Mav will run commands as its own user, in its own folder, without your keys in their environment. A page or e-mail Mav reads could still try to make it run something: only turn this on if you trust what Mav reads, or run Mav in its own container or VM.",
      "Turn on",
    ))
  )
    return;
  sw.disabled = true;
  try {
    await api.post("config/code", { enabled: on });
    toast(on ? "Code tools on. Mav restarts for a few seconds." : "Code tools off. Mav restarts for a few seconds.");
  } catch (ex) {
    toast(ex.message, { error: true });
  }
  sw.disabled = false;
  loadCode();
});
