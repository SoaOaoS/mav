/* Service worker Mav — PWA.
   Stratégie : RÉSEAU D'ABORD pour la coquille (HTML/CSS/JS/icônes), afin que
   les mises à jour arrivent toujours ; le cache ne sert que de secours hors
   ligne. JAMAIS de cache pour /api/* (état temps réel de l'agent).
*/

const CACHE = "mav-shell-v11";
const SHELL = [
  "./",
  "./index.html",
  "./assets/css/style.css",
  "./assets/js/app.js",
  "./manifest.webmanifest",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./icons/apple-touch-icon.png",
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

// Recharge immédiate quand on demande au SW de prendre la main.
self.addEventListener("message", (e) => {
  if (e.data === "skip-waiting") self.skipWaiting();
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  // Jamais de cache pour l'API ni pour un autre domaine.
  if (url.pathname.includes("/api/") || url.origin !== self.location.origin) {
    return;
  }

  // Réseau d'abord ; en cas d'échec réseau, on retombe sur le cache.
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
  let data = { title: "Mav", body: "Nouvelle alerte.", url: "./" };
  try {
    if (event.data) data = Object.assign(data, event.data.json());
  } catch (_) {}
  event.waitUntil(
    (async () => {
      // Affiche la notification d'abord (priorité absolue).
      await self.registration.showNotification(data.title || "Mav", {
        body: data.body || "",
        icon: "icons/icon-192.png",
        badge: "icons/icon-192.png",
        data: { url: data.url || "./" },
        tag: data.tag || undefined,
      });
      // Accusé de réception (diagnostic) : ne doit jamais bloquer l'affichage.
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
  event.waitUntil(
    clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((list) => {
        // Un onglet Mav est déjà ouvert : on lui demande d'ouvrir le détail
        // (message direct, plus fiable que navigate selon les navigateurs).
        for (const c of list) {
          if ("focus" in c) {
            try {
              if (notifId) c.postMessage({ type: "open-notif", id: notifId });
            } catch (_) {}
            return c.focus();
          }
        }
        if (clients.openWindow) return clients.openWindow(url);
      }),
  );
});
