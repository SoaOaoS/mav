/* Mav web app — Debates, voice, notifications, channels, calendars, backup.
   One of the classic scripts index.html loads in order (10/12); they share
   one global scope, like the single app.js they came from. */

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

/* Calendars (bot/occalendar.py): CalDAV or a private iCal link, read-only.
   Passwords and iCal links come back masked; leaving them keeps the stored one. */
async function loadCalendars() {
  if (!LIVE) return;
  let r;
  try {
    r = await api.get("calendar");
  } catch (_) {
    return;
  }
  state.calendars = r.sources || [];
  state.today = r.today || [];
  const box = $("#calList");
  box.hidden = !state.calendars.length;
  box.innerHTML = state.calendars
    .map(
      (c) => `<div class="chan" data-id="${esc(c.id)}">
        <span class="chan-type">${c.kind === "caldav" ? "CalDAV" : "iCal"}</span>
        <strong>${esc(c.name)}</strong>
        <span class="chan-acts">
          <button class="btn btn-ghost btn-sm" data-cal="test">Test</button>
          <button class="btn btn-ghost btn-sm" data-cal="edit">Edit</button>
          <button class="switch" role="switch" aria-label="Enabled" aria-checked="${c.enabled ? "true" : "false"}" data-cal="toggle"></button>
        </span></div>`,
    )
    .join("");
}
function fmtEvent(e) {
  const d = new Date(e.start * 1000);
  const day = d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  const when = e.all_day ? `${day}, all day` : `${day} ${d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
  return `${when} — ${e.title}${e.location ? ` (${e.location})` : ""}`;
}
function editCalendar(c) {
  const isNew = !c;
  const kind = (c && c.kind) || "caldav";
  const form = document.createElement("form");
  form.className = "form";
  form.innerHTML = `
    <div class="segmented" data-kinds ${isNew ? "" : "hidden"}>
      <button type="button" data-k="caldav">CalDAV account</button><button type="button" data-k="ics">iCal link</button>
    </div>
    <div class="field"><label>Name</label><input name="name" value="${esc((c && c.name) || "")}" placeholder="Personal"></div>
    <div class="field"><label data-urllabel>Address</label><input name="url" value="${esc((c && c.url) || "")}" placeholder="https://"></div>
    <div class="field-grid" data-auth>
      <div class="field"><label>User name</label><input name="username" autocomplete="off" value="${esc((c && c.username) || "")}"></div>
      <div class="field"><label>Password (an app password is best)</label><input name="password" type="password" autocomplete="new-password" value="${esc((c && c.password) || "")}"></div>
    </div>
    <p class="hint" data-hint></p>`;
  let k = kind;
  const hints = {
    caldav:
      "The CalDAV address of your account or of one calendar. Nextcloud: https://cloud.example.org/remote.php/dav — iCloud: https://caldav.icloud.com — Fastmail: https://caldav.fastmail.com/dav/calendars",
    ics: "Google Calendar: Settings → your calendar → “Secret address in iCal format”. Outlook: Calendar → Shared calendars → Publish → ICS. Keep it private: anyone with it can read the calendar.",
  };
  const setKind = (x) => {
    k = x;
    form.querySelectorAll("[data-k]").forEach((b) => b.classList.toggle("is-active", b.dataset.k === x));
    form.querySelector("[data-auth]").hidden = x !== "caldav";
    form.querySelector("[data-urllabel]").textContent = x === "caldav" ? "CalDAV address" : "iCal link";
    form.querySelector("[data-hint]").textContent = hints[x];
  };
  setKind(kind);
  form.addEventListener("click", (e) => {
    const b = e.target.closest("[data-k]");
    if (b) setKind(b.dataset.k);
  });
  form.addEventListener("submit", (e) => e.preventDefault());
  const actions = [];
  if (!isNew)
    actions.push({
      label: "Remove",
      kind: "btn-danger",
      left: true,
      run: async () => {
        await api.post("calendar/delete", { id: c.id }).catch(() => {});
        loadCalendars();
      },
    });
  actions.push(
    { label: "Cancel" },
    {
      label: isNew ? "Add" : "Save",
      kind: "btn-primary",
      run: async (btn) => {
        const fd = Object.fromEntries(new FormData(form));
        fd.kind = k;
        if (c) Object.assign(fd, { id: c.id, enabled: c.enabled });
        btn.disabled = true;
        try {
          const r = await api.post("calendar/save", fd);
          const t = await api.post("calendar/test", { id: r.id }).catch((e) => ({ error: e.message }));
          await loadCalendars();
          if (t.ok)
            toast(
              t.count
                ? `Connected — next: ${fmtEvent(t.upcoming[0])}${t.count > 1 ? ` (+${t.count - 1} in the next 2 weeks)` : ""}`
                : "Connected — nothing in the next 2 weeks.",
            );
          else toast(`Saved, but it could not be read: ${t.error || "?"}`, { error: true });
        } catch (err) {
          btn.disabled = false;
          toast(err.message, { error: true });
          return false;
        }
      },
    },
  );
  modal.open({ title: isNew ? "Add a calendar" : `Calendar “${c.name}”`, body: form, actions });
}
$("#calAdd").addEventListener("click", () => {
  if (needLive()) editCalendar(null);
});
$("#calList").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-cal]");
  if (!b) return;
  const c = (state.calendars || []).find((x) => x.id === b.closest("[data-id]").dataset.id);
  if (!c) return;
  if (b.dataset.cal === "edit") return editCalendar(c);
  if (b.dataset.cal === "toggle") {
    await api.post("calendar/save", { ...c, enabled: !c.enabled }).catch((err) => toast(err.message, { error: true }));
    return loadCalendars();
  }
  b.disabled = true;
  try {
    const r = await api.post("calendar/test", { id: c.id });
    toast(r.count ? `Next: ${fmtEvent(r.upcoming[0])}` : "Readable — nothing in the next 2 weeks.");
  } catch (err) {
    toast(err.message, { error: true });
  }
  b.disabled = false;
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
