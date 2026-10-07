/* Mav web app — Search and commands.
   One of the classic scripts index.html loads in order (11/12); they share
   one global scope, like the single app.js they came from. */

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
