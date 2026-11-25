// UI state shared across components: toast, song menu, full player sheet, desktop queue panel.
// Overlays push a history entry so the phone's back button closes them instead of leaving the app.
import type { Song } from './types'

export interface PlaylistCtx { id: string; index: number; count: number }
export interface MenuState { song: Song; queueIndex?: number; playlist?: PlaylistCtx }

class UI {
  toast = $state<{ msg: string; id: number } | null>(null)
  menu = $state<MenuState | null>(null)
  addTo = $state<Song[] | null>(null)                   // 'Add to playlist' sheet
  plVersion = $state(0)                                 // bumped after a playlist edit: open playlist pages reload
  full = $state(false)
  panel = $state<'queue' | 'lyrics' | null>(null)
  sheetTab = $state<'next' | 'lyrics'>('next')
  wide = $state(typeof matchMedia !== 'undefined' && matchMedia('(min-width: 960px)').matches)
  private timer = 0

  say(msg: string, ms = 2600) {
    this.toast = { msg, id: Date.now() }
    clearTimeout(this.timer)
    this.timer = window.setTimeout(() => (this.toast = null), ms)
  }

  openMenu(m: MenuState) { this.menu = m; pushOverlay('menu') }
  closeMenu() { if (this.menu) { this.menu = null; popOverlay('menu') } }

  openAddTo(songs: Song[]) {
    if (this.menu) { this.menu = null; history.replaceState({ ...(history.state || {}), overlay: 'addto' }, '', location.hash || '#/') }
    else pushOverlay('addto')
    this.addTo = songs
  }
  closeAddTo() { if (this.addTo) { this.addTo = null; popOverlay('addto') } }

  openFull() { if (!this.full) { this.full = true; pushOverlay('full') } }
  closeFull() { if (this.full) { this.full = false; popOverlay('full') } }

  /** Navigate from inside an overlay (song menu, full player): close them all at once (the sheet slides down),
   *  step back over their history entries, then navigate, so Back afterwards returns to the previous page. */
  leaveTo(go: () => void) {
    const n = (this.menu ? 1 : 0) + (this.full ? 1 : 0) + (this.addTo ? 1 : 0)
    this.menu = null
    this.addTo = null
    this.full = false
    if (!n || !history.state?.overlay) return go()
    let done = false
    const run = () => { if (done) return; done = true; window.removeEventListener('popstate', run); go() }
    window.addEventListener('popstate', run)
    setTimeout(run, 400)                                    // in case the browser drops the popstate
    history.go(-n)
  }
}

export const ui = new UI()

function pushOverlay(name: string) {
  history.pushState({ ...(history.state || {}), overlay: name }, '', location.hash || '#/')
}
function popOverlay(name: string) {
  if (history.state?.overlay === name) history.back()
}

window.addEventListener('popstate', (e) => {
  const o = (e.state || {}).overlay
  if (o !== 'menu') ui.menu = null
  if (o !== 'addto') ui.addTo = null
  if (o !== 'full' && o !== 'menu' && o !== 'addto') ui.full = false
})

if (typeof matchMedia !== 'undefined') {
  matchMedia('(min-width: 960px)').addEventListener('change', (e) => (ui.wide = e.matches))
}

export const toast = (m: string) => ui.say(m)
