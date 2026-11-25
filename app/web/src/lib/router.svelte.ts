// Hash router (#/, #/search?q=…&f=…, #/library, #/album/ID …) with per-entry scroll restoration.
import type { Kind } from './types'

export type Route =
  | { name: 'home' }
  | { name: 'search'; q: string; f: string }
  | { name: 'library' }
  | { name: 'stats' }
  | { name: 'settings' }
  | { name: 'detail'; kind: Kind; id: string }

const KINDS: Kind[] = ['album', 'artist', 'playlist', 'mix', 'lbplaylist', 'versions', 'myplaylist']

export function parse(hash: string): Route {
  const [path, qs] = hash.replace(/^#/, '').split('?')
  const parts = path.split('/').filter(Boolean)
  const q = new URLSearchParams(qs || '')
  if (parts[0] === 'search') return { name: 'search', q: q.get('q') || '', f: q.get('f') || 'all' }
  if (parts[0] === 'library') return { name: 'library' }
  if (parts[0] === 'stats') return { name: 'stats' }
  if (parts[0] === 'settings') return { name: 'settings' }
  if (KINDS.includes(parts[0] as Kind) && parts[1]) return { name: 'detail', kind: parts[0] as Kind, id: decodeURIComponent(parts[1]) }
  return { name: 'home' }
}

export function href(r: Route): string {
  switch (r.name) {
    case 'search': {
      const p = new URLSearchParams()
      if (r.q) p.set('q', r.q)
      if (r.f && r.f !== 'all') p.set('f', r.f)
      const s = p.toString()
      return '#/search' + (s ? '?' + s : '')
    }
    case 'library': return '#/library'
    case 'stats': return '#/stats'
    case 'settings': return '#/settings'
    case 'detail': return `#/${r.kind}/${encodeURIComponent(r.id)}`
    default: return '#/'
  }
}

class Router {
  route = $state<Route>(parse(location.hash))
  private scrolls = new Map<string, number>()

  go(r: Route, replace = false) {
    const h = href(r)
    this.scrolls.set(location.hash || '#/', window.scrollY)
    if (h === (location.hash || '#/') && !replace) return
    if (replace) history.replaceState({}, '', h)
    else history.pushState({}, '', h)
    this.route = r
    if (!replace) window.scrollTo({ top: 0 })
  }

  onPop() {
    const r = parse(location.hash)
    if (href(r) !== href(this.route)) {
      this.route = r
      const y = this.scrolls.get(location.hash || '#/') ?? 0
      requestAnimationFrame(() => requestAnimationFrame(() => window.scrollTo({ top: y })))
    }
  }
}

export const router = new Router()
window.addEventListener('popstate', () => router.onPop())
