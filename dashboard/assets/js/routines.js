/* Mav web app — The proactive inbox and routines.
   One of the classic scripts index.html loads in order (6/12); they share
   one global scope, like the single app.js they came from. */

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
      (x, i) => `<li><button class="inbox-item" data-more="${i}" title="Tell me more">
        <span class="inbox-ico">${I(TOPIC_ICON[x.topic] || "bell")}</span>
        <span class="what"><strong>${esc(x.title || "Notification")}</strong><span>${esc((x.body || "").replace(/[*_`#>|]+/g, "").replace(/\s+/g, " "))}</span></span>
        <span class="inbox-side"><span class="t">${esc(fmtRel(x.ts))}</span>${I("chevron").replace("data-i", 'class="go" data-i')}</span>
      </button></li>`,
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
  if (j.before_event) return "before";
  if (j.on_event) return "event";
  if (j.every_minutes) return "hours";
  if (j.days_of_month && j.days_of_month.length) return "monthly";
  if (j.last_day_of_month) return "monthly";
  return j.days && j.days.length && j.days.length < 7 ? "weekly" : "daily";
}
function jobWhen(j) {
  const mode = jobMode(j);
  if (mode === "before") return beforeText(j.before_event);
  if (mode === "event")
    return `when ${(j.on_event && j.on_event.kind) || "an event"} fires`;
  if (mode === "hours") {
    const m = Number(j.every_minutes);
    if (m < 60 || m % 60) return `every ${m} minutes`;
    return m === 60 ? "every hour" : `every ${m / 60} hours`;
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
  if (!$(`#rpanel-${tab}`) || (!isOwner() && (tab === "drafts" || tab === "interests"))) tab = "routines";
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
      <div class="suggest">${ROUTINE_IDEAS.map((r, i) => `<button class="chip" data-idea="${i}">${esc(r.label)}</button>`).join("")}
      <button class="chip chip-accent" data-goto="ideas">${I("sparkle")} More ideas</button></div></div>`;
    return;
  }
  box.innerHTML = jobs
    .map(
      (j, i) => `<div class="job ${j.enabled ? "" : "is-off"}">
      ${agentAvatar(j.agent || state.defaultAgent)}
      <div class="jmain" data-edit-job="${i}" title="Edit">
        <div class="jtitle">${esc(j.name)} ${j.running ? `<span class="badge warn">${dots()} running</span>` : ""}</div>
        <div class="jdesc">${esc(j.description || j.prompt || "")}</div>
        <div class="jsched"><span class="badge">${I("clock")} ${esc(jobWhen(j))}</span>
          <span class="badge">${esc(agentDisplay(j.agent || state.defaultAgent))}</span>
          ${j.last_run ? `<span>last run ${esc(j.last_run)}</span>` : ""}</div>
      </div>
      <div class="jacts">
        ${j.session ? `<button class="icon-btn" data-open-chat="${esc(j.session)}" title="Open its chat" aria-label="Open its chat">${I("chat")}</button>` : ""}
        <button class="icon-btn" data-run="${i}" title="Run now" aria-label="Run now">${I("play")}</button>
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
function beforeText(b) {
  const n = Number((b && b.minutes) || 0);
  const what = b && b.contains ? `an event mentioning “${b.contains}”` : "each event";
  return n ? `${n} min before ${what}` : `when ${what} starts`;
}
function draftWhen(d) {
  if (d.mode === "before") return beforeText({ minutes: d.before_minutes, contains: d.before_contains });
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
  } else if (d.mode === "before") {
    job.before_event = { minutes: Math.max(0, Math.round(Number(d.before_minutes) || 0)) };
    if (d.before_contains) job.before_event.contains = d.before_contains;
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
  if (!boxes.length) return []; // no other channel set up: everywhere (Web Push)
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
      before_minutes: (src.before_event && src.before_event.minutes) ?? 15,
      before_contains: (src.before_event && src.before_event.contains) || "",
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
      before_minutes: 15,
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
        <button type="button" data-m="daily">Every day</button><button type="button" data-m="weekly">Some days</button><button type="button" data-m="monthly">Once a month</button><button type="button" data-m="hours">Every few hours</button><button type="button" data-m="event">On an event</button><button type="button" data-m="before" ${state.calendars && state.calendars.length ? "" : "hidden"}>Before a meeting</button>
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
      <div class="field" data-f="before">
        <label>How long before each event</label>
        <div class="row"><input type="number" min="0" max="1440" name="before_minutes" value="${esc(d.before_minutes ?? 15)}" style="width:90px"> min
        <input type="text" name="before_contains" value="${esc(d.before_contains || "")}" placeholder="only events mentioning… (optional)"></div>
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
      x === "hours" || x === "event" || x === "before";
    form.querySelector('[data-f="before"]').hidden = x !== "before";
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
      before_minutes: Number(fd.get("before_minutes") || 0),
      before_contains: String(fd.get("before_contains") || "").trim(),
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
