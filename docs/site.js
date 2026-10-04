/* Mav — marketing site interactions. No dependencies. */
(function () {
  "use strict";

  // Copy-to-clipboard for the install command(s).
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
      // Fallback for non-secure contexts.
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

  // Show the latest released version (from GitHub; silently skipped offline).
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

  // Mobile: collapse the docs table of contents so the content comes first.
  const navToggle = document.getElementById("docsNavToggle");
  const docsNav = document.querySelector(".docs-nav");
  if (navToggle && docsNav) {
    navToggle.addEventListener("click", () => {
      const open = docsNav.classList.toggle("is-open");
      navToggle.setAttribute("aria-expanded", String(open));
    });
    // Tapping a link closes the drawer.
    docsNav.querySelectorAll("a").forEach((a) => {
      a.addEventListener("click", () => {
        docsNav.classList.remove("is-open");
        navToggle.setAttribute("aria-expanded", "false");
      });
    });
  }

  // Reveal-on-scroll for a touch of life. Fail-safe: everything is revealed
  // after a short delay no matter what, so content can never stay hidden.
  const reveal = (el) => {
    el.style.opacity = "1";
    el.style.transform = "none";
  };
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
    const targets = document.querySelectorAll(
      ".card, .steps li, .section-head, .final-cta",
    );
    targets.forEach((el) => {
      el.style.opacity = "0";
      el.style.transform = "translateY(14px)";
      el.style.transition = "opacity .5s ease, transform .5s ease";
      io.observe(el);
    });
    // Safety net.
    setTimeout(() => targets.forEach(reveal), 1800);
  }
})();
