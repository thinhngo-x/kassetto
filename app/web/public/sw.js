// ytm service worker: hashed /assets/* cache-first (instant start), the page itself network-first
// (so Authelia's login redirect still works) with the cached copy as offline fallback. No API/audio caching.
const V = 'ytm-v2'
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (e) => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (k !== V) await caches.delete(k)
  await self.clients.claim()
})()))
self.addEventListener('fetch', (e) => {
  const u = new URL(e.request.url)
  if (e.request.method !== 'GET' || u.origin !== location.origin) return
  if (u.pathname.startsWith('/assets/')) {
    e.respondWith(caches.open(V).then(async (c) => {
      const hit = await c.match(e.request)
      if (hit) return hit
      const r = await fetch(e.request)
      if (r.ok) c.put(e.request, r.clone())
      return r
    }))
  } else if (e.request.mode === 'navigate' && u.pathname === '/') {
    e.respondWith((async () => {
      const c = await caches.open(V)
      try {
        const r = await fetch(e.request)
        if (r.ok && r.type === 'basic') c.put('/', r.clone())
        return r
      } catch (err) {
        const hit = await c.match('/')
        if (hit) return hit
        throw err
      }
    })())
  }
})
