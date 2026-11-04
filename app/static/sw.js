/* 서비스 워커 — 브라우저에 앱으로 설치될 수 있게 하고, 화면 파일만 캐시한다.
   영상·오디오·API 응답은 캐시하지 않는다 (항상 최신이어야 하므로). */

/* 저장 이름을 바꾸면 activate 단계에서 옛 저장본이 통째로 지워진다.
   화면 색이나 아이콘처럼 겉모습이 바뀔 때마다 숫자를 올린다. */
const CACHE = "moviefit-studio-v3";   // v3 (2026-11-04): 옛 화면 파일이 며칠씩 남던 문제를 고쳤다
const SHELL = [
  "/",
  "/index.html",
  "/style.css?v=20261104",   // index.html 이 부르는 주소와 같아야 한다
  "/app.js?v=20261104",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/fonts/PretendardVariable.woff2",
];

/* 브라우저 자체의 기억(HTTP 캐시)을 건너뛰고 서버에 꼭 확인한다.
   예전 서버는 화면 파일에 "매번 확인하라" 표시를 안 붙여서, 브라우저가 파일 날짜만 보고
   며칠씩 옛 app.js 를 썼다. 새 판을 설치해도 화면이 안 바뀌는 일이 그래서 생겼다. */
const FRESH = { cache: "no-cache" };

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(SHELL.map((u) => new Request(u, { cache: "reload" }))))
      .then(() => self.skipWaiting())
  );
});

/* ⚠ 여기서 열린 화면을 새로 고치게(clients[].navigate) 하지 말 것.
   활성화가 끝나기 전에는 화면 요청이 이 워커에 오지 않는데, 활성화 안에서 그 새로 고침을
   기다리면 서로를 기다리며 멈춘다 (2026-11-04 크롬 탭이 통째로 멈췄다).
   옛 app.js 를 버리게 하는 일은 index.html 의 주소 끝 `?v=` 가 맡는다. */
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
  // 화면 이동(navigate) 요청은 설정을 덧붙여 다시 만들 수 없어서 주소로 다시 요청한다
  const fresh = event.request.mode === "navigate"
    ? fetch(event.request.url, { ...FRESH, credentials: "same-origin" })
    : fetch(event.request, FRESH);
  event.respondWith(
    fresh
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(event.request, copy));
        return res;
      })
      .catch(() => caches.match(event.request).then((hit) => hit || caches.match("/index.html")))
  );
});
