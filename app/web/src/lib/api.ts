// Fetch layer: in-memory cache + in-flight de-duplication, stale-while-revalidate via localStorage for the
// home screen (instant first paint), and Authelia session handling (an expired session = redirect -> reload).

type Entry = { t: number; v: unknown }
const mem = new Map<string, Entry>()
const inflight = new Map<string, Promise<unknown>>()
const MEM_MAX = 120

function sessionExpired() {
  const k = 'kassetto-reload'
  const last = Number(sessionStorage.getItem(k) || 0)
  if (Date.now() - last > 30_000) {           // at most one reload per 30 s (no loops)
    sessionStorage.setItem(k, String(Date.now()))
    location.reload()
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response
  try {
    r = await fetch(path, { credentials: 'same-origin', ...init })
  } catch (e) {
    if (navigator.onLine) sessionExpired()        // the redirect to the sign-in proxy fails CORS -> TypeError
    throw e
  }
  if (r.redirected || r.status === 401) { sessionExpired(); throw new Error('login required') }
  if (!r.ok) throw new Error((await r.text()).slice(0, 200) || r.statusText)
  return r.json() as Promise<T>
}

export function get<T>(path: string, ttl = 5 * 60_000): Promise<T> {
  const hit = mem.get(path)
  if (hit && Date.now() - hit.t < ttl) return Promise.resolve(hit.v as T)
  const running = inflight.get(path)
  if (running) return running as Promise<T>
  const p = request<T>(path).then((v) => {
    mem.set(path, { t: Date.now(), v })
    if (mem.size > MEM_MAX) mem.delete(mem.keys().next().value!)
    return v
  }).finally(() => inflight.delete(path))
  inflight.set(path, p)
  return p
}

/** Cached value without fetching (memory first, then the persisted copy). */
export function peek<T>(path: string): T | undefined {
  const hit = mem.get(path)
  if (hit) return hit.v as T
  try {
    const raw = localStorage.getItem('swr:' + path)
    if (raw) return JSON.parse(raw) as T
  } catch { /* storage unavailable */ }
  return undefined
}

/** Stale-while-revalidate: returns the persisted copy now (if any) and calls back with fresh data. */
export function swr<T>(path: string, onData: (v: T) => void, ttl = 10 * 60_000) {
  const cached = peek<T>(path)
  if (cached !== undefined) onData(cached)
  get<T>(path, ttl).then((v) => {
    onData(v)
    try { localStorage.setItem('swr:' + path, JSON.stringify(v)) } catch { /* quota */ }
  }).catch(() => {})
}

export function post<T = unknown>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}) })
}

/** Warm the server's audio cache for a song the user is about to play (pointer-down = strong intent). */
const warmed = new Set<string>()
export function warmStream(videoId: string) {
  if (warmed.has(videoId)) return
  warmed.add(videoId)
  fetch(`/api/prefetch?videoId=${videoId}${!new Audio().canPlayType('audio/webm; codecs="opus"') ? '&aac=1' : ''}`, { credentials: 'same-origin' }).catch(() => {})
}

/** Ask the server to look songs up ahead (most likely tap first): YouTube's pre-roll ad wait (5-10 s, enforced
 *  server-side) then runs out while the user is still choosing, so the tap plays in well under a second. */
const resolved = new Map<string, number>()
let pending: string[] = [], rtimer = 0
export function resolveSoon(ids: (string | undefined)[]) {
  const now = Date.now()
  for (const v of ids) if (v && !(now - (resolved.get(v) ?? 0) < 3.5 * 3600_000) && !pending.includes(v)) pending.push(v)
  if (!pending.length) return
  clearTimeout(rtimer)
  rtimer = window.setTimeout(() => {
    const batch = pending.slice(0, 6); pending = []
    batch.forEach((v) => resolved.set(v, Date.now()))
    fetch(`/api/resolve?ids=${batch.join(',')}`, { credentials: 'same-origin' }).catch(() => {})
  }, 250)
}

/** Warm a detail page's data (pointer-down on a tile) so the navigation renders from cache. */
export function warm(path: string) { get(path).catch(() => {}) }

export const store = {
  get<T>(k: string, d: T): T {
    try { const v = localStorage.getItem(k); return v === null ? d : (JSON.parse(v) as T) } catch { return d }
  },
  set(k: string, v: unknown) { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* quota */ } },
}
