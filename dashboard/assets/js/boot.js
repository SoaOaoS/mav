/* Mav web app — runs before first paint (loaded in <head>, not deferred):
   apply the saved theme (no flash) and never leave the app behind the splash. */
(function () {
  try {
    var t = localStorage.getItem("mav-theme");
    if (t === "light" || t === "dark")
      document.documentElement.dataset.theme = t;
  } catch (_) {}
  // Safety net: never leave the app behind the splash, even if app.js
  // fails to load. Cleared far before a user would notice.
  setTimeout(function () {
    var s = document.getElementById("splash");
    if (s) s.classList.add("is-done");
    document.body.classList.remove("is-loading");
  }, 2500);
})();
