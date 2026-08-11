/* 서비스 워커 — 브라우저에 앱으로 설치될 수 있게 하고, 화면 파일만 캐시한다.
   영상·오디오·API 응답은 캐시하지 않는다 (항상 최신이어야 하므로). */

const CACHE = "capcut-studio-v1";
const SHELL = [
  "/",
  "/index.html",
  "/style.css",
  "/app.js",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // API와 미디어는 캐시를 거치지 않고 항상 서버에 직접 물어본다
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/media/")) return;
  if (event.request.method !== "GET") return;

  // 화면 파일은 네트워크 우선, 서버가 꺼져 있으면 캐시로 대체
  event.respondWith(
    fetch(event.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(event.request, copy));
        return res;
      })
      .catch(() => caches.match(event.request).then((hit) => hit || caches.match("/index.html")))
  );
});
