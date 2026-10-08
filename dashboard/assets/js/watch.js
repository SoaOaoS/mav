/* Mav web app — Keep an eye on, interests and memory.
   One of the classic scripts index.html loads in order (7/12); they share
   one global scope, like the single app.js they came from. */

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
