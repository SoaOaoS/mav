/* Mav — website interactions (landing + docs). No dependencies. */
(function () {
  "use strict";

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const store = {
    get(k) {
      try {
        return localStorage.getItem(k);
      } catch (_) {
        return null;
      }
    },
    set(k, v) {
      try {
        localStorage.setItem(k, v);
      } catch (_) {}
    },
  };

  /* ------------------------------------------------------------ theme */
  const root = document.documentElement;
  const isDark = () =>
    root.dataset.theme
      ? root.dataset.theme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
  $$("[data-theme-toggle]").forEach((b) =>
    b.addEventListener("click", () => {
      const next = isDark() ? "light" : "dark";
      root.dataset.theme = next;
      store.set("mav-theme", next);
    }),
  );

  /* ------------------------------------------------------------ nav + progress */
  const nav = $("#nav");
  const bar = $("#progress");
  const onScroll = () => {
    const h = document.documentElement;
    const max = h.scrollHeight - h.clientHeight;
    if (bar) bar.style.transform = `scaleX(${max > 0 ? h.scrollTop / max : 0})`;
    if (nav) nav.classList.toggle("scrolled", h.scrollTop > 8);
  };
  document.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  const menuBtn = $("#menuBtn");
  if (menuBtn && nav) {
    menuBtn.addEventListener("click", () => {
      const open = nav.classList.toggle("open");
      menuBtn.setAttribute("aria-expanded", String(open));
    });
    $$("#navLinks a").forEach((a) =>
      a.addEventListener("click", () => {
        nav.classList.remove("open");
        menuBtn.setAttribute("aria-expanded", "false");
      }),
    );
  }

  /* ------------------------------------------------------------ copy */
  function copyText(text, btn) {
    const done = () => {
      const old = btn.textContent;
      btn.textContent = "Copied";
      btn.classList.add("done");
      setTimeout(() => {
        btn.textContent = old;
        btn.classList.remove("done");
      }, 1600);
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, () => {});
      return;
    }
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.cssText = "position:fixed;opacity:0";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      done();
    } catch (_) {}
    ta.remove();
  }
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".copy");
    if (!btn || btn.hasAttribute("data-copy-term")) return;
    const text =
      btn.dataset.copy ||
      (btn.closest(".codeblock") || btn.closest(".install") || document).querySelector("code")
        .textContent;
    copyText(text.trim(), btn);
  });

  /* ------------------------------------------------------------ split headings */
  $$("[data-split]").forEach((el) => {
    let i = 0;
    const walk = (node) => {
      Array.from(node.childNodes).forEach((n) => {
        if (n.nodeType === 3) {
          const frag = document.createDocumentFragment();
          n.textContent.split(/(\s+)/).forEach((part) => {
            if (!part) return;
            if (/^\s+$/.test(part)) {
              frag.appendChild(document.createTextNode(" "));
              return;
            }
            const w = document.createElement("span");
            w.className = "w";
            const s = document.createElement("span");
            s.textContent = part;
            s.style.setProperty("--i", i++);
            w.appendChild(s);
            frag.appendChild(w);
          });
          n.replaceWith(frag);
        } else if (n.nodeType === 1) {
          walk(n);
        }
      });
    };
    el.setAttribute("aria-label", el.textContent.trim());
    walk(el);
  });

  /* ------------------------------------------------------------ reveal */
  const revealables = $$("[data-reveal], [data-split], .stage, .film-frame");
  if ("IntersectionObserver" in window && !reduce) {
    const io = new IntersectionObserver(
      (entries) =>
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("in");
            io.unobserve(e.target);
          }
        }),
      { threshold: 0.12, rootMargin: "0px 0px -40px 0px" },
    );
    revealables.forEach((el) => io.observe(el));
  } else {
    revealables.forEach((el) => el.classList.add("in"));
  }

  /* ------------------------------------------------------------ GitHub numbers */
  const latest = $$("[data-latest-version]");
  const stars = $$("[data-stars]");
  if (latest.length) {
    fetch("https://api.github.com/repos/SoaOaoS/mav/releases/latest")
      .then((r) => (r.ok ? r.json() : null))
      .then((rel) => {
        if (!rel || !rel.tag_name) return;
        latest.forEach((el) => (el.textContent = rel.tag_name));
        const pill = $("#versionPill");
        if (pill && rel.html_url) pill.href = rel.html_url;
      })
      .catch(() => {});
  }
  if (stars.length) {
    fetch("https://api.github.com/repos/SoaOaoS/mav")
      .then((r) => (r.ok ? r.json() : null))
      .then((repo) => {
        if (!repo || typeof repo.stargazers_count !== "number") return;
        const n = repo.stargazers_count;
        const txt = n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, "") + "k" : String(n);
        stars.forEach((el) => (el.textContent = txt));
      })
      .catch(() => {});
  }

  /* ------------------------------------------------------------ counters */
  const counters = $$("[data-count]");
  if (counters.length && "IntersectionObserver" in window && !reduce) {
    const co = new IntersectionObserver(
      (entries) =>
        entries.forEach((e) => {
          if (!e.isIntersecting) return;
          const el = e.target;
          const to = Number(el.dataset.count || 0);
          const t0 = performance.now();
          const step = (t) => {
            const p = Math.min(1, (t - t0) / 900);
            el.textContent = Math.round(to * (1 - Math.pow(1 - p, 3)));
            if (p < 1) requestAnimationFrame(step);
          };
          el.textContent = "0";
          requestAnimationFrame(step);
          co.unobserve(el);
        }),
      { threshold: 0.6 },
    );
    counters.forEach((c) => co.observe(c));
  }

  /* ------------------------------------------------------------ tile spotlight */
  $$(".tile").forEach((t) =>
    t.addEventListener("pointermove", (e) => {
      const r = t.getBoundingClientRect();
      t.style.setProperty("--mx", e.clientX - r.left + "px");
      t.style.setProperty("--my", e.clientY - r.top + "px");
    }),
  );

  /* ------------------------------------------------------------ visibility gate */
  // Animations that loop only run while their section is on screen.
  function gate(el) {
    const g = { on: false, waiters: [] };
    g.wait = () => (g.on ? Promise.resolve() : new Promise((r) => g.waiters.push(r)));
    if (!("IntersectionObserver" in window)) {
      g.on = true;
      return g;
    }
    new IntersectionObserver(
      (entries) =>
        entries.forEach((e) => {
          g.on = e.isIntersecting;
          if (g.on) g.waiters.splice(0).forEach((r) => r());
        }),
      { threshold: 0.25 },
    ).observe(el);
    return g;
  }

  /* ------------------------------------------------------------ hero scene */
  const stage = $("#stage");
  if (stage) runScene(stage);

  function runScene(stage) {
    const msgs = $("#sceneMsgs");
    const input = $("#sceneInput");
    const send = $("#sceneSend");
    const push = $("#scenePush");
    const cursor = $("#sceneCursor");
    const ask = "Make me a CSV of my subscriptions and tell me what to cancel";
    const answer =
      "You pay 74 € a month across 9 subscriptions. Two haven't been used in 3 months: the language app (12.99 €) and the second streaming plan (8.99 €). Cancelling both saves 263 € a year.";
    const tools = [
      ["Searched memory", "subscriptions, budget", "0.3s"],
      ["Read mail", "receipt OR invoice · last 90 days", "1.4s"],
      ["Wrote a file", "mav-files/subscriptions.csv", "0.2s"],
    ];
    const g = gate(stage);

    const el = (cls, html) => {
      const d = document.createElement("div");
      d.className = cls;
      if (html) d.innerHTML = html;
      return d;
    };
    const mavMsg = () => {
      const m = el("msg-mav pop", '<span class="av">A</span>');
      const body = el("body");
      m.appendChild(body);
      msgs.appendChild(m);
      return body;
    };
    const toolEl = (t, done) => {
      const d = el("tool pop" + (done ? " ok" : ""));
      d.innerHTML = `<span class="st"></span><span>${t[0]}</span><code>${t[1]}</code>`;
      if (done) d.insertAdjacentHTML("beforeend", `<time>${t[2]}</time>`);
      return d;
    };
    const fileCard = () =>
      el("file-card pop", "<i>CSV</i><div>subscriptions.csv<small>9 rows · 1 KB</small></div>");

    function moveTo(target, dx = 0.5, dy = 0.5) {
      const s = stage.getBoundingClientRect();
      const r = target.getBoundingClientRect();
      cursor.style.transform = `translate(${r.left - s.left + r.width * dx}px, ${
        r.top - s.top + r.height * dy
      }px)`;
    }
    async function click() {
      cursor.classList.remove("click");
      void cursor.offsetWidth;
      cursor.classList.add("click");
      await sleep(260);
    }

    if (reduce) {
      msgs.appendChild(el("msg-me", ask));
      const body = mavMsg();
      tools.forEach((t) => body.appendChild(toolEl(t, true)));
      body.appendChild(el("", `<p>${answer}</p>`).firstChild);
      body.appendChild(fileCard());
      push.classList.add("is-in");
      cursor.style.display = "none";
      return;
    }

    (async function loop() {
      for (;;) {
        await g.wait();
        msgs.innerHTML = "";
        push.classList.remove("is-in");
        input.textContent = "Ask Mav anything…";
        input.classList.remove("typing");
        moveTo(stage.querySelector(".app"), 0.62, 0.42);
        await sleep(900);

        moveTo(input, 0.3, 0.6);
        await sleep(900);
        await click();
        input.classList.add("typing");
        input.textContent = "";
        for (const ch of ask) {
          input.textContent += ch;
          await sleep(26 + Math.random() * 40);
        }
        await sleep(300);
        moveTo(send, 0.5, 0.55);
        await sleep(700);
        send.classList.add("press");
        await click();
        send.classList.remove("press");
        input.textContent = "Ask Mav anything…";
        input.classList.remove("typing");
        msgs.appendChild(el("msg-me pop", ask));
        moveTo(stage.querySelector(".app"), 0.9, 0.95);
        await sleep(600);

        const body = mavMsg();
        for (const t of tools) {
          const d = toolEl(t, false);
          body.appendChild(d);
          await sleep(700 + Math.random() * 500);
          d.replaceWith(toolEl(t, true));
          await sleep(120);
        }
        const p = document.createElement("p");
        p.className = "caret";
        body.appendChild(p);
        for (const w of answer.split(" ")) {
          p.textContent += (p.textContent ? " " : "") + w;
          await sleep(45 + Math.random() * 45);
        }
        p.classList.remove("caret");
        await sleep(250);
        body.appendChild(fileCard());
        await sleep(1800);

        push.classList.add("is-in");
        await sleep(600);
        moveTo(push, 0.7, 0.6);
        await sleep(3600);
      }
    })();
  }

  /* ------------------------------------------------------------ film */
  const playBtn = $("#playBtn");
  const video = $("#film-video");
  if (playBtn && video) {
    // Native controls only once it plays, so they never sit under our button.
    video.removeAttribute("controls");
    playBtn.addEventListener("click", () => {
      playBtn.classList.add("gone");
      video.controls = true;
      video.play().catch(() => {});
    });
    video.addEventListener("play", () => {
      playBtn.classList.add("gone");
      video.controls = true;
    });
    video.addEventListener("ended", () => playBtn.classList.remove("gone"));
  }

  /* ------------------------------------------------------------ story (sticky scroll) */
  const steps = $$(".story-step");
  const panels = $$(".panel");
  const draftText = $("#draftText");
  const draft =
    "Hello Mrs Martin, yes, the notice period is one month. I can leave the keys on the 30th, and the plumber can come any morning next week.";
  let drafting = 0;
  async function typeDraft() {
    if (!draftText) return;
    const id = ++drafting;
    draftText.textContent = "";
    if (reduce) {
      draftText.textContent = draft;
      return;
    }
    for (const ch of draft) {
      if (id !== drafting) return;
      draftText.textContent += ch;
      await sleep(18);
    }
  }
  function showStep(i) {
    steps.forEach((s, k) => s.classList.toggle("active", k === i));
    panels.forEach((p, k) => p.classList.toggle("active", k === i));
    if (i === 2) typeDraft();
  }
  const narrow = window.matchMedia("(max-width: 900px)");
  if (steps.length) {
    // Phones: no scroll-driven story, the panels take turns on their own.
    const g = gate($("#story"));
    let k = 0;
    (async function cycle() {
      for (;;) {
        await sleep(4200);
        await g.wait();
        if (narrow.matches && !reduce) showStep((k = (k + 1) % panels.length));
      }
    })();
  }
  if (steps.length && "IntersectionObserver" in window) {
    const so = new IntersectionObserver(
      (entries) =>
        entries.forEach((e) => {
          if (e.isIntersecting && !narrow.matches) showStep(Number(e.target.dataset.step));
        }),
      { rootMargin: "-45% 0px -45% 0px" },
    );
    steps.forEach((s) => so.observe(s));
  }

  /* ------------------------------------------------------------ showcase */
  const showTabs = $$("#showTabs button");
  if (showTabs.length) {
    const imgs = $$(".shots img");
    const copy = [
      ["For you, first thing.", "Reports and alerts wait on the home screen. Tap “Tell me more” to pick up the thread."],
      ["Watch it work.", "Every tool call shows up in order. Tap one to see what ran, how long it took, and what came back."],
      ["Routines that fit real life.", "Daily, weekly, monthly, on an event or only if a condition is met. Each one has its own chat."],
      ["It remembers you.", "Facts Mav learned about you, in plain words. Edit or delete any of them."],
    ];
    const show = $("#show");
    const box = $("#showcase");
    const g = gate(box);
    const DUR = 5000;
    let cur = 0;
    let timer = null;
    let hover = false;
    box.style.setProperty("--dur", DUR + "ms");
    const select = (i) => {
      cur = i;
      showTabs.forEach((b, k) => {
        b.setAttribute("aria-selected", String(k === i));
        const bar = b.querySelector("i");
        bar.style.animation = "none";
        void bar.offsetWidth;
        bar.style.animation = "";
      });
      imgs.forEach((im, k) => im.classList.toggle("on", k === i));
      $("#showTitle").textContent = copy[i][0];
      $("#showText").textContent = copy[i][1];
      schedule();
    };
    const schedule = () => {
      clearTimeout(timer);
      if (reduce || hover) return;
      timer = setTimeout(async () => {
        await g.wait();
        select((cur + 1) % showTabs.length);
      }, DUR);
    };
    showTabs.forEach((b, k) => b.addEventListener("click", () => select(k)));
    show.addEventListener("pointerenter", () => {
      hover = true;
      box.classList.add("paused");
      clearTimeout(timer);
    });
    show.addEventListener("pointerleave", () => {
      hover = false;
      box.classList.remove("paused");
      select(cur);
    });
    if (reduce) box.classList.add("paused");
    g.wait().then(() => select(0));
  }

  /* ------------------------------------------------------------ terminal */
  const term = $("#termOut");
  if (term) {
    const scripts = {
      docker: [
        ["$ ", "git clone https://github.com/SoaOaoS/mav.git && cd mav"],
        ["$ ", "cp .env.example .env"],
        ["$ ", "docker compose up -d"],
        ["", "<span class='ok'> ✔</span> Container mav-postgres-1  <span class='d'>Healthy</span>"],
        ["", "<span class='ok'> ✔</span> Container mav-engine-1    <span class='d'>Healthy</span>"],
        ["", "<span class='ok'> ✔</span> Container mav-web-1       <span class='d'>Healthy</span>"],
        ["", "<span class='ok'> ✔</span> Container mav-worker-1    <span class='d'>Started</span>"],
        ["", ""],
        ["", "<span class='k'>→</span> Open <span class='p'>http://localhost:8787</span> and choose a password"],
      ],
      installer: [
        ["$ ", "curl -fsSL https://raw.githubusercontent.com/SoaOaoS/mav/main/get.sh | sudo bash"],
        ["", "<span class='d'>  Mav installer</span>"],
        ["", "<span class='ok'>✔</span> Dependencies   <span class='d'>python · node · postgres</span>"],
        ["", "<span class='k'>?</span> Model provider <span class='p'>› Anthropic</span>"],
        ["", "<span class='ok'>✔</span> API key        <span class='d'>checked</span>"],
        ["", "<span class='ok'>✔</span> Model          <span class='d'>picked from the provider's list</span>"],
        ["", "<span class='ok'>✔</span> Services       <span class='d'>engine · web app · worker</span>"],
        ["", ""],
        ["", "<span class='k'>→</span> Mav is running. Open the address it prints."],
      ],
    };
    const g = gate(term);
    let which = "docker";
    let run = 0;
    async function play() {
      const id = ++run;
      await g.wait();
      term.innerHTML = "";
      for (const [prompt, line] of scripts[which]) {
        if (id !== run) return;
        const row = document.createElement("div");
        term.appendChild(row);
        if (prompt) {
          row.innerHTML = "<span class='p'>$</span> ";
          const t = document.createTextNode("");
          row.appendChild(t);
          for (const ch of line) {
            if (id !== run) return;
            t.textContent += ch;
            if (!reduce) await sleep(14);
          }
          if (!reduce) await sleep(380);
        } else {
          row.innerHTML = line || "&nbsp;";
          if (!reduce) await sleep(260);
        }
      }
    }
    $$("[data-term]").forEach((b) =>
      b.addEventListener("click", () => {
        which = b.dataset.term;
        $$("[data-term]").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
        play();
      }),
    );
    const copyTerm = $("[data-copy-term]");
    if (copyTerm)
      copyTerm.addEventListener("click", () =>
        copyText(
          scripts[which]
            .filter((l) => l[0])
            .map((l) => l[1])
            .join("\n"),
          copyTerm,
        ),
      );
    play();
  }

  /* ============================================================ DOCS */
  const prose = $(".prose");
  if (!prose) return;

  const sections = $$("section[id]", prose);
  const sideLinks = $$(".side a[href^='#']");
  const groupOf = {};
  $$(".side-group").forEach((grp) => {
    const name = grp.querySelector("span").textContent;
    $$("a", grp).forEach((a) => (groupOf[a.getAttribute("href").slice(1)] = name));
  });

  // Section eyebrow, heading anchors and stable ids for sub-headings.
  const slug = (s) =>
    s
      .toLowerCase()
      .replace(/<[^>]+>/g, "")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "");
  sections.forEach((sec) => {
    const h2 = sec.querySelector("h2");
    if (h2 && groupOf[sec.id]) {
      const c = document.createElement("p");
      c.className = "crumb";
      c.textContent = groupOf[sec.id];
      sec.insertBefore(c, h2);
    }
    if (h2) h2.insertAdjacentHTML("afterbegin", `<a class="anchor" href="#${sec.id}" aria-label="Link to this section">#</a>`);
    $$("h3", sec).forEach((h3) => {
      if (!h3.id) h3.id = sec.id + "-" + slug(h3.textContent);
      h3.insertAdjacentHTML("afterbegin", `<a class="anchor" href="#${h3.id}" aria-label="Link to this heading">#</a>`);
    });
  });

  // Code blocks: a header with the language and a copy button, light highlighting.
  $$("pre", prose).forEach((pre) => {
    const code = pre.querySelector("code") || pre;
    const text = code.textContent;
    let lang = "shell";
    if (/^\s*[{[]/.test(text)) lang = "json";
    else if (/^(GET|POST|PUT|DELETE|PATCH) /m.test(text)) lang = "http";
    else if (/^[A-Z_]+=/m.test(text) && !/^\$|^sudo|^curl|^git|^mav /m.test(text)) lang = "env";
    else if (/[│▼▲─]/.test(text)) lang = "diagram";
    const wrap = document.createElement("div");
    wrap.className = "codeblock";
    wrap.innerHTML = `<div class="codeblock-bar"><span>${lang}</span><button class="copy">Copy</button></div>`;
    pre.replaceWith(wrap);
    wrap.appendChild(pre);
    if (lang === "shell") {
      code.innerHTML = code.innerHTML
        .split("\n")
        .map((l) =>
          l
            .replace(/(^|\s)(#[^\n]*)$/, '$1<span class="tok-c">$2</span>')
            .replace(/^(\s*)(sudo|curl|git|docker|mav|cp|cd|systemctl|journalctl|ssh|psql)\b/, '$1<span class="tok-k">$2</span>'),
        )
        .join("\n");
    } else if (lang === "json") {
      code.innerHTML = code.innerHTML.replace(/(&quot;|")([^"&]*?)(&quot;|")(\s*:)/g, '<span class="tok-k">$1$2$3</span>$4');
    } else if (lang === "env") {
      code.innerHTML = code.innerHTML
        .split("\n")
        .map((l) => (l.startsWith("#") ? `<span class="tok-c">${l}</span>` : l.replace(/^([A-Z_]+)=/, '<span class="tok-k">$1</span>=')))
        .join("\n");
    }
  });

  // Previous / next at the end of the page's last section is overkill on one
  // page; instead each section ends with a link to the next one.
  sections.forEach((sec, i) => {
    const prev = sections[i - 1];
    const next = sections[i + 1];
    if (!prev && !next) return;
    const nav = document.createElement("nav");
    nav.className = "docs-pager";
    nav.setAttribute("aria-label", "Previous and next");
    const title = (s) => s.querySelector("h2").textContent.replace(/^#/, "").trim();
    if (prev) nav.insertAdjacentHTML("beforeend", `<a href="#${prev.id}"><small>← Previous</small>${title(prev)}</a>`);
    if (next) nav.insertAdjacentHTML("beforeend", `<a class="next" href="#${next.id}"><small>Next →</small>${title(next)}</a>`);
    sec.appendChild(nav);
  });

  // Scroll spy: the sidebar follows the section, the right column lists its
  // sub-headings.
  const toc = $("#tocList");
  const sideLabel = $("#sideCurrent");
  let current = null;
  function setCurrent(sec) {
    if (sec === current) return;
    current = sec;
    sideLinks.forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "#" + sec.id));
    const active = sideLinks.find((a) => a.classList.contains("active"));
    if (active && window.innerWidth > 860) {
      const side = $(".side");
      const r = active.getBoundingClientRect();
      const sr = side.getBoundingClientRect();
      if (r.top < sr.top || r.bottom > sr.bottom) active.scrollIntoView({ block: "nearest" });
    }
    if (sideLabel) sideLabel.textContent = sec.querySelector("h2").textContent.replace(/^#/, "").trim();
    if (toc) {
      const subs = $$("h3", sec);
      toc.innerHTML = subs.length
        ? subs.map((h) => `<li><a href="#${h.id}">${h.textContent.replace(/^#/, "").trim()}</a></li>`).join("")
        : `<li><a href="#${sec.id}">${sec.querySelector("h2").textContent.replace(/^#/, "").trim()}</a></li>`;
    }
  }
  function spy() {
    const y = window.scrollY + 140;
    let sec = sections[0];
    for (const s of sections) if (s.offsetTop <= y) sec = s;
    setCurrent(sec);
    if (!toc) return;
    const subs = $$("a", toc);
    let on = subs[0];
    subs.forEach((a) => {
      const t = document.getElementById(a.getAttribute("href").slice(1));
      if (t && t.getBoundingClientRect().top < 160) on = a;
    });
    subs.forEach((a) => a.classList.toggle("active", a === on));
  }
  document.addEventListener("scroll", spy, { passive: true });
  window.addEventListener("load", spy);
  spy();

  // Mobile: the sidebar is a drawer.
  const side = $(".side");
  const sideToggle = $("#sideToggle");
  if (side && sideToggle) {
    sideToggle.addEventListener("click", () => {
      const open = side.classList.toggle("open");
      sideToggle.setAttribute("aria-expanded", String(open));
      document.body.style.overflow = open ? "hidden" : "";
    });
    $$("a", side).forEach((a) =>
      a.addEventListener("click", () => {
        side.classList.remove("open");
        sideToggle.setAttribute("aria-expanded", "false");
        document.body.style.overflow = "";
      }),
    );
  }

  /* ------------------------------------------------------------ search palette */
  const pal = $("#palette");
  if (!pal) return;
  const q = $("#paletteInput");
  const list = $("#paletteList");
  const index = [];
  sections.forEach((sec) => {
    const h2 = sec.querySelector("h2").textContent.replace(/^#/, "").trim();
    const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
    const firstP = sec.querySelector("p:not(.crumb)");
    const body = $$(":scope > :not(nav):not(.crumb)", sec).map(text).join(" ");
    index.push({ id: sec.id, title: h2, where: groupOf[sec.id] || "", body, snippet: text(firstP) });
    $$("h3", sec).forEach((h3) => {
      let body = "";
      for (let n = h3.nextElementSibling; n && n.tagName !== "H3" && n.tagName !== "NAV"; n = n.nextElementSibling) body += " " + text(n);
      index.push({ id: h3.id, title: h3.textContent.replace(/^#/, "").trim(), where: h2, body, snippet: body.trim() });
    });
  });
  const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const hl = (s, terms) => {
    let out = esc(s);
    terms.forEach((t) => {
      if (t) out = out.replace(new RegExp("(" + t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig"), "<mark>$1</mark>");
    });
    return out;
  };
  let sel = 0;
  function render() {
    const terms = q.value.toLowerCase().trim().split(/\s+/).filter(Boolean);
    let hits = index;
    if (terms.length) {
      hits = index
        .map((it) => {
          const t = it.title.toLowerCase();
          const b = it.body.toLowerCase();
          if (!terms.every((w) => t.includes(w) || b.includes(w))) return null;
          const score = terms.reduce((s, w) => s + (t.includes(w) ? 10 : 0) + (t.startsWith(w) ? 5 : 0) + (b.includes(w) ? 1 : 0), 0);
          let snip = it.snippet;
          const at = b.indexOf(terms[0]);
          if (at > 60) snip = "…" + it.body.slice(at - 40, at + 120);
          return { it, score, snip };
        })
        .filter(Boolean)
        .sort((a, b) => b.score - a.score)
        .slice(0, 12)
        .map((h) => ({ ...h.it, snippet: h.snip }));
    } else {
      hits = index.filter((it) => !it.id.includes("-")).slice(0, 8);
    }
    sel = 0;
    list.innerHTML = hits.length
      ? hits
          .map(
            (it, i) =>
              `<li><a href="#${it.id}" class="${i === 0 ? "sel" : ""}">${hl(it.title, terms)}<small>${esc(it.where)}${it.where ? " · " : ""}${hl(it.snippet.slice(0, 140), terms)}</small></a></li>`,
          )
          .join("")
      : `<li class="empty">No results for “${esc(q.value)}”</li>`;
  }
  function openPalette() {
    pal.classList.add("open");
    q.value = "";
    render();
    q.focus();
  }
  function closePalette() {
    pal.classList.remove("open");
  }
  $$("[data-search]").forEach((b) => b.addEventListener("click", openPalette));
  q.addEventListener("input", render);
  pal.addEventListener("click", (e) => {
    if (e.target === pal) closePalette();
    if (e.target.closest("a")) closePalette();
  });
  document.addEventListener("keydown", (e) => {
    if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !/INPUT|TEXTAREA/.test(document.activeElement.tagName))) {
      e.preventDefault();
      openPalette();
      return;
    }
    if (!pal.classList.contains("open")) return;
    const items = $$("a", list);
    if (e.key === "Escape") closePalette();
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!items.length) return;
      sel = (sel + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length;
      items.forEach((a, i) => a.classList.toggle("sel", i === sel));
      items[sel].scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter" && items[sel]) {
      e.preventDefault();
      location.hash = items[sel].getAttribute("href");
      closePalette();
    }
  });
})();
