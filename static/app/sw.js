/* Shell service worker: precache the app frame so an installed PWA opens
   offline; live data always comes from the network. */
// ASSUMPTION: bumping CACHE is what evicts the poisoned install-day cache —
// activate deletes every other key, so each future asset fix bumps it again.
const CACHE = "fis-cek-shell-v2";
const SHELL = ["./", "index.html", "manifest.webmanifest", "icon.svg"];
const LIVE_PREFIXES = ["/v1", "/api", "/demo"];
// Everything index.html executes or styles: a phone must pick up a shipped
// fix on the next load instead of replaying install day forever.
const CODE = /\.(?:js|mjs|css)$/i;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) {
    return;
  }
  // Job state, authenticated views and the demo server's live config must
  // never come from a stale cache.
  if (LIVE_PREFIXES.some((prefix) => url.pathname.startsWith(prefix))) {
    return;
  }
  if (CODE.test(url.pathname)) {
    event.respondWith(networkFirst(event));
    return;
  }
  event.respondWith(cacheFirst(event.request));
});

// Code is network-first, cache-only-when-offline: a stale status.js is a
// lying status card, and the cache is there so the app still opens with no
// connection on the code it already has.
function networkFirst(event) {
  return fetch(event.request)
    .then((response) => {
      if (response.ok) {
        const copy = response.clone();
        event.waitUntil(
          caches.open(CACHE).then((cache) => cache.put(event.request, copy))
        );
      }
      return response;
    })
    .catch(() =>
      caches.match(event.request).then((hit) => hit || Response.error())
    );
}

function cacheFirst(request) {
  return caches.match(request).then(
    (hit) =>
      hit ||
      fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      })
  );
}
