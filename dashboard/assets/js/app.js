/* Mav web app — Loading (live or demo), the service worker and install banner.
   One of the classic scripts index.html loads in order (12/12); they share
   one global scope, like the single app.js they came from. */

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
function showAuthGate(mode, named) {
  if (authMode === mode) return;
  authMode = mode;
  const setup = mode === "setup";
  // Several people use this Mav: they sign in with their name (none = the owner).
  const askName = !setup && (named ?? AUTH_NAMED);
  $("#authName").hidden = !askName;
  $("#authTitle").textContent = setup ? "Protect your Mav" : "Welcome back";
  $("#authLead").textContent = setup
    ? "Choose a password. Anyone who wants to open Mav — from this device or your phone — will need it."
    : askName
      ? "Your name and password. The owner can leave the name empty."
      : "Enter your password to open Mav.";
  $("#authPassword").autocomplete = setup ? "new-password" : "current-password";
  $("#authPassword2").hidden = !setup;
  $("#authPassword2").required = setup;
  $("#authSubmit").textContent = setup ? "Set password and continue" : "Sign in";
  $("#authFoot").hidden = setup;
  $("#authError").hidden = true;
  $("#authGate").hidden = false;
  hideSplash();
  setTimeout(() => $(askName ? "#authName" : "#authPassword").focus(), 50);
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
      body: JSON.stringify({ password: pw, name: $("#authName").value.trim() }),
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

/* Family: the owner gives each person their own sign-in. Members get their
   own chats, memory and routines; settings that cost money or reach your
   accounts (model, connections, helpers, backup) stay with the owner. */
function applyRole() {
  document.body.dataset.role = ME.role;
  $("#accountText").textContent =
    ME.role === "owner"
      ? AUTH_NAMED
        ? `Signed in as ${ME.name || "the owner"}.`
        : "Only people with the password can open Mav."
      : `Signed in as ${ME.name}. Your chats, memory and routines are yours alone.`;
}
async function loadFamily() {
  if (!LIVE || ME.role !== "owner") return;
  let r;
  try {
    r = await api.get("family");
  } catch (_) {
    return;
  }
  $("#familyRow").hidden = !r.enabled;
  const members = (r.accounts || []).filter((a) => a.role === "member");
  state.family = members;
  const box = $("#familyList");
  box.hidden = !r.enabled || !members.length;
  box.innerHTML = members
    .map(
      (m) => `<div class="chan" data-id="${m.id}">
        <span class="chan-type">Member</span>
        <strong>${esc(m.name)}</strong>
        <span class="chan-acts">
          <button class="btn btn-ghost btn-sm" data-fam="password">New password</button>
          <button class="btn btn-ghost btn-sm" data-fam="remove">Remove</button>
        </span></div>`,
    )
    .join("");
}
$("#familyAdd").addEventListener("click", () => {
  if (!needLive()) return;
  modal.open({
    title: "Add a person",
    body: `<div class="field"><label>Name</label><input id="famName" maxlength="32" autocomplete="off" placeholder="e.g. Alex"></div>
      <div class="field"><label>Their password (8+ characters)</label><input type="password" id="famPw" autocomplete="new-password"></div>
      <p class="hint">They sign in with this name and password, and can change the password later.</p>`,
    actions: [
      { label: "Cancel" },
      {
        label: "Add",
        kind: "btn-primary",
        run: async () => {
          try {
            const r = await api.post("family/add", { name: $("#famName").value, password: $("#famPw").value });
            AUTH_NAMED = true;
            applyRole();
            await loadFamily();
            toast(`${r.member.name} can now sign in.`);
          } catch (ex) {
            toast(ex.message, { error: true });
            return false;
          }
        },
      },
    ],
  });
});
$("#familyList").addEventListener("click", (e) => {
  const b = e.target.closest("[data-fam]");
  if (!b) return;
  const m = (state.family || []).find((x) => String(x.id) === b.closest("[data-id]").dataset.id);
  if (!m) return;
  if (b.dataset.fam === "password")
    return modal.open({
      title: `New password for ${m.name}`,
      body: `<div class="field"><label>New password (8+ characters)</label><input type="password" id="famPw" autocomplete="new-password"></div>
        <p class="hint">${esc(m.name)} is signed out everywhere and uses this one next time.</p>`,
      actions: [
        { label: "Cancel" },
        {
          label: "Set password",
          kind: "btn-primary",
          run: async () => {
            try {
              await api.post("family/password", { id: m.id, password: $("#famPw").value });
              toast("Password set.");
            } catch (ex) {
              toast(ex.message, { error: true });
              return false;
            }
          },
        },
      ],
    });
  modal.open({
    title: `Remove ${m.name}?`,
    size: "small",
    body: `<p>${esc(m.name)} is signed out, and their chats, memory, routines and notifications are erased. This can't be undone.</p>`,
    actions: [
      { label: "Cancel" },
      {
        label: "Remove",
        kind: "btn-danger",
        run: async () => {
          try {
            await api.post("family/remove", { id: m.id });
            toast(`${m.name} was removed.`);
            await loadFamily();
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
  if (ME.role !== "owner") {
    // The owner chose the model: nothing to connect here.
    OB.connected = true;
    $("#obModelReady").hidden = false;
    $("#obModelReady").innerHTML = `${I("check")}<span>Mav is ready — the owner has connected it to a model.</span>`;
    $("#obModelForm").hidden = true;
    return;
  }
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
  AUTH_NAMED = !!(auth && auth.named);
  if (auth && auth.enabled && (auth.setup_needed || !auth.authenticated)) {
    LIVE = true;
    document.body.dataset.mode = "live";
    return showAuthGate(auth.setup_needed ? "setup" : "login");
  }
  if (auth && auth.user) ME = auth.user;
  applyRole();
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
    loadCalendars(),
    loadFamily(),
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
    // A first visit has no worker yet: taking control then is not an update,
    // and reloading would wipe what the person is typing (e.g. the password).
    const hadController = !!navigator.serviceWorker.controller;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      // Never reload in the middle of an answer.
      if (!hadController || reloaded || anyStreaming()) return;
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
