/* Service worker Mav — PWA.
   Strategy: NETWORK-FIRST for the shell (HTML/CSS/JS/icons), so updates
   always arrive; the cache is only an offline fallback. NEVER cache
   /api/* (the agent's live state).
*/

const CACHE = "mav-shell-v37";
const SHELL = [
  "./",
  "./index.html",
  "./assets/css/style.css",
  "./assets/js/boot.js",
  "./assets/js/util.js",
  "./assets/js/state.js",
  "./assets/js/chat.js",
  "./assets/js/stream.js",
  "./assets/js/markdown.js",
  "./assets/js/routines.js",
  "./assets/js/watch.js",
  "./assets/js/settings.js",
  "./assets/js/connections.js",
  "./assets/js/notify.js",
  "./assets/js/search.js",
  "./assets/js/app.js",
  "./manifest.webmanifest",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./icons/apple-touch-icon.png",
  "./icons/favicon.svg",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches
      .open(CACHE)
      .then((c) => c.addAll(SHELL))
      .catch(() => {})
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

// Immediate reload when the SW is asked to take over.
self.addEventListener("message", (e) => {
  if (e.data === "skip-waiting") self.skipWaiting();
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  // Never cache the API or any other origin.
  if (url.pathname.includes("/api/") || url.origin !== self.location.origin) {
    return;
  }

  // Network first; on network failure, fall back to the cache.
  e.respondWith(
    fetch(req)
      .then((res) => {
        if (res && res.status === 200 && res.type === "basic") {
          const copy = res.clone();
          caches
            .open(CACHE)
            .then((c) => c.put(req, copy))
            .catch(() => {});
        }
        return res;
      })
      .catch(() =>
        caches.match(req).then((hit) => {
          if (hit) return hit;
          // Navigations hors-ligne : on rend la coquille.
          if (req.mode === "navigate") return caches.match("./index.html");
          return Response.error();
        }),
      ),
  );
});

/* ---------- Web Push ---------- */
self.addEventListener("push", (event) => {
  let data = { title: "Mav", body: "New alert.", url: "./" };
  try {
    if (event.data) data = Object.assign(data, event.data.json());
  } catch (_) {}
  event.waitUntil(
    (async () => {
      // Show the notification first (absolute priority).
      await self.registration.showNotification(data.title || "Mav", {
        body: data.body || "",
        icon: "icons/icon-192.png",
        badge: "icons/icon-192.png",
        data: { url: data.url || "./" },
        tag: data.tag || undefined,
      });
      // Acknowledgement (diagnostics): must never block display.
      try {
        const ctl = new AbortController();
        setTimeout(() => ctl.abort(), 4000);
        await fetch("/api/push/ack", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: data.title || "Mav",
            body: data.body || "",
          }),
          signal: ctl.signal,
        });
      } catch (_) {}
    })(),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const raw = (event.notification.data && event.notification.data.url) || "./";
  const url = new URL(raw, self.location.origin).href;
  const m = url.match(/[?&]notif=(\d+)/);
  const notifId = m ? m[1] : null;
  // Routine reports link straight to the routine's chat.
  const c = url.match(/#chat\/([^&?#]+)/);
  const chatId = c ? decodeURIComponent(c[1]) : null;
  event.waitUntil(
    clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((list) => {
        // A Mav tab is already open: ask it to open the detail
        // (direct message, more reliable than navigate across browsers).
        for (const c of list) {
          if ("focus" in c) {
            try {
              if (notifId) c.postMessage({ type: "open-notif", id: notifId });
              else if (chatId) c.postMessage({ type: "open-chat", id: chatId });
            } catch (_) {}
            return c.focus();
          }
        }
        if (clients.openWindow) return clients.openWindow(url);
      }),
  );
});
