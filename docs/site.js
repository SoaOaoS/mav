/* Mav — marketing site interactions. No dependencies. */
(function () {
  "use strict";

  /* -------- splash screen -------- */
  const splash = document.getElementById("splash");
  const root = document.body;
  function hideSplash() {
    if (splash) splash.classList.add("is-done");
    root.classList.remove("is-loading");
  }
  // Never trap the page behind the splash: hide on load, and at the latest
  // after 1.6 s no matter what.
  window.addEventListener("load", () => setTimeout(hideSplash, 400));
  setTimeout(hideSplash, 1600);

  /* -------- scroll progress -------- */
  const bar = document.getElementById("scrollProgress");
  if (bar) {
    const onScroll = () => {
      const h = document.documentElement;
      const max = h.scrollHeight - h.clientHeight;
      bar.style.width = (max > 0 ? (h.scrollTop / max) * 100 : 0) + "%";
    };
    document.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  /* -------- copy-to-clipboard -------- */
  function copyText(text, btn) {
    const done = () => {
      const old = btn.textContent;
      btn.textContent = "Copied!";
      setTimeout(() => (btn.textContent = old), 1600);
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard
        .writeText(text)
        .then(done)
        .catch(() => {});
    } else {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        done();
      } catch (_) {}
      document.body.removeChild(ta);
    }
  }
  document.querySelectorAll(".copy-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const scope = btn.closest(".install");
      const code = scope ? scope.querySelector("code") : null;
      copyText(code ? code.textContent.trim() : "", btn);
    });
  });

  /* -------- latest release pill -------- */
  const pill = document.getElementById("versionPill");
  const latest = document.querySelectorAll("[data-latest-version]");
  if (pill || latest.length) {
    fetch("https://api.github.com/repos/SoaOaoS/mav/releases/latest", {
      headers: { Accept: "application/vnd.github+json" },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((rel) => {
        if (!rel || !rel.tag_name) return;
        if (pill) {
          pill.textContent = `${rel.tag_name} · Open source · MIT`;
          if (rel.html_url) pill.href = rel.html_url;
        }
        latest.forEach((el) => (el.textContent = rel.tag_name));
      })
      .catch(() => {});
  }

  /* -------- mobile docs TOC -------- */
  const navToggle = document.getElementById("docsNavToggle");
  const docsNav = document.querySelector(".docs-nav");
  if (navToggle && docsNav) {
    navToggle.addEventListener("click", () => {
      const open = docsNav.classList.toggle("is-open");
      navToggle.setAttribute("aria-expanded", String(open));
    });
    docsNav.querySelectorAll("a").forEach((a) => {
      a.addEventListener("click", () => {
        docsNav.classList.remove("is-open");
        navToggle.setAttribute("aria-expanded", "false");
      });
    });
  }

  /* -------- reveal on scroll -------- */
  const reveal = (el) => {
    el.style.opacity = "1";
    el.style.transform = "none";
  };
  const targets = document.querySelectorAll(
    "[data-reveal], .card, .steps li, .section-head, .final-cta",
  );
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            reveal(e.target);
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.12 },
    );
    targets.forEach((el) => {
      if (!el.hasAttribute("data-reveal")) {
        el.style.opacity = "0";
        el.style.transform = "translateY(14px)";
        el.style.transition = "opacity .5s ease, transform .5s ease";
      }
      io.observe(el);
    });
    // Safety net: nothing stays hidden.
    setTimeout(() => targets.forEach(reveal), 1800);
  } else {
    targets.forEach(reveal);
  }

  /* -------- 3D tilt on the hero mock -------- */
  const tilt = document.querySelector("[data-tilt]");
  if (tilt && window.matchMedia("(hover: hover)").matches) {
    const strength = 6;
    tilt.addEventListener("mousemove", (e) => {
      const r = tilt.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - 0.5;
      const y = (e.clientY - r.top) / r.height - 0.5;
      tilt.style.transform = `perspective(1400px) rotateY(${
        -7 + x * strength
      }deg) rotateX(${3 - y * strength}deg) translateZ(0)`;
    });
    tilt.addEventListener("mouseleave", () => {
      tilt.style.transform = "";
    });
  }

  /* -------- counters (the "1 command / 0 accounts" stats) -------- */
  const counters = document.querySelectorAll("[data-count]");
  if (counters.length && "IntersectionObserver" in window) {
    const co = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (!e.isIntersecting) return;
          const el = e.target;
          const to = Number(el.dataset.count || 0);
          const t0 = performance.now();
          const dur = 700;
          const step = (t) => {
            const p = Math.min(1, (t - t0) / dur);
            el.textContent = Math.round(to * (1 - Math.pow(1 - p, 3)));
            if (p < 1) requestAnimationFrame(step);
          };
          requestAnimationFrame(step);
          co.unobserve(el);
        });
      },
      { threshold: 0.6 },
    );
    counters.forEach((c) => co.observe(c));
  } else {
    counters.forEach((c) => (c.textContent = c.dataset.count));
  }
})();
