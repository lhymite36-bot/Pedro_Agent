// Pedro_Agent service worker: caches the app shell only. API calls, the live
// screen and the login page always go to the network (never cached).
const CACHE = 'pedro-shell-v4';
const SHELL = ['/', '/app.css', '/app.js', '/markdown.js', '/avatar.js', '/handsfree.js', '/bots_ui.js', '/groups_ui.js', '/live_ui.js', '/icon-192.png', '/manifest.webmanifest'];
self.addEventListener('install', (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {})); self.skipWaiting(); });
self.addEventListener('activate', (e) => { e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))); self.clients.claim(); });
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/live/') || url.pathname.startsWith('/login') || url.pathname === '/logout') return;
  // Network first so updates show at once; cache is the offline fallback.
  e.respondWith(fetch(e.request).then((res) => {
    if (res.ok && res.type === 'basic') { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
    return res;
  }).catch(() => caches.match(e.request)));
});
