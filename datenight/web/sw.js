// Lets Date Night Picker open with no signal. Files are served from the phone's cache straight away, and
// quietly refreshed from the internet in the background, so updates arrive the next time the app opens.
const CACHE = "datenight-v1";
const FILES = ["./", "./index.html", "./manifest.webmanifest", "./icon-192.png", "./icon-512.png",
  "./maskable-512.png", "./apple-touch-icon.png", "../ideas.json"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k.startsWith("datenight-") && k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // Only the app's own files; weather, maps and opening hours always go to the internet.
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  event.respondWith(caches.open(CACHE).then(async (cache) => {
    const cached = await cache.match(event.request, { ignoreSearch: true });
    const fresh = fetch(event.request).then((response) => {
      if (response.ok) cache.put(event.request, response.clone());
      return response;
    }).catch(() => cached);
    if (cached) {
      event.waitUntil(fresh);
      return cached;
    }
    return fresh;
  }));
});
