// Playback engine. Two <audio> elements: the active one plays, the standby one pre-buffers the next track
// (from halfway through the current one), so track changes are gapless. Also: play events for the
// recommender, ListenBrainz scrobbles, personal Autoplay refills, the Nest hand-off with position sync.
// Sound: per-track volume levelling (the embed service measures each cached song's loudness; loud masters are turned
// down to -14 LUFS via el.volume, smoothed), silent lead-ins / tails skipped, optional equal-power crossfade
// between the two elements (not between consecutive tracks of the same album: those stay gapless).
// Headphone correction (experimental): an AutoEq profile (preamp + parametric filters) applied with Web Audio:
// element -> per-element gain (volume, levelling, crossfade) -> preamp -> filters -> output. Created lazily on
// the first play after it is switched on (an element can't leave a Web Audio graph again, so "off" = flat).
// Verified 2026-11-24 on the owner's Android Brave: Web Audio keeps playing (and timers keep firing) when locked.
import { get, post, store, warmStream } from './api'
import { large } from './img'
import { speakerOutcome, trackOutcome, type EndReason } from './outcome'
import type { NestStatus, Song } from './types'
import { ui } from './ui.svelte'

/** Opus (better sound at the same size) unless this browser can't play it (some Safari versions) -> AAC copy. */
export const AAC = typeof Audio !== 'undefined' && !new Audio().canPlayType('audio/webm; codecs="opus"')
const streamUrl = (id: string, retry = false) => `/stream/${id}${AAC ? '?aac=1' : ''}${retry ? (AAC ? '&' : '?') + 'retry=1' : ''}`
export type Output = 'headphones' | 'speaker' | 'off'

/** Generic tuning for a phone / laptop speaker: drop the bass it can't play (less distortion and rattle when loud),
 *  a touch of upper-bass warmth, less boxiness and harshness, a little air; compression is added in the graph. */
const PHONE_SPEAKER: EqProfile['filters'] = [
  { type: 'highpass', f: 150, gain: 0, q: 0.7 },
  { type: 'peaking', f: 300, gain: 2, q: 1 },
  { type: 'peaking', f: 1000, gain: -1, q: 1 },
  { type: 'peaking', f: 3200, gain: -2, q: 1.5 },
  { type: 'highshelf', f: 9000, gain: 1.5, q: 0.7 },
]

export interface EqProfile { id: string; name: string; by: string; kind?: string; preamp: number
                            filters: { type: BiquadFilterType; f: number; gain: number; q: number }[] }

const plain = (s: Song): Song => ({ type: 'song', videoId: s.videoId, title: s.title, artist: s.artist, album: s.album,
                                     duration: s.duration, thumb: s.thumb })

class Player {
  queue = $state<Song[]>([])
  idx = $state(-1)
  playing = $state(false)
  buffering = $state(false)
  time = $state(0)
  duration = $state(0)
  autoplay = $state(store.get('autoplay', true))
  prefs = $state<Record<string, number>>({})
  nest = $state(false)
  nestPaused = $state(false)
  volume = $state(store.get('volume', 1))
  normalize = $state(store.get('normalize', true))
  trim = $state(store.get('trimSilence', true))
  crossfade = $state(store.get('crossfade', 3))           // seconds, 0 = off
  eqOn = $state(store.get('eqOn', false))
  canCast = $state(false)                                 // a speaker is set up and you may use it (its circle)
  speakerName = $state('Speaker')
  sleepAt = $state(0)                                     // sleep timer: epoch ms (0 = off); on the Nest = server's
  sleepEnd = $state(false)                                // sleep at the end of the current song
  eq = $state<EqProfile | null>(store.get('eq', null))
  output = $state<Output>(store.get('output', 'headphones'))   // what this device plays through (can't be detected)
  tone = $state<{ bass: number; treble: number }>(store.get('tone', { bass: 0, treble: 0 }))
  current = $derived(this.queue[this.idx] as Song | undefined)

  private els: HTMLAudioElement[] = []
  private a = 0
  private scrobbled = false
  private finished = false
  private audible = false                                // this track has really played (not just loading)
  private pendingSkip: { vid: string; body: Record<string, unknown>; timer: number; auto: boolean } | null = null
  private errors = 0
  private autoSkips = 0
  private lastGood: Song | undefined
  private refilling: Promise<void> | null = null
  private nestTimer = 0
  private nestStarted = 0
  private watchdog = 0
  private nestLast: { t: Song; pos: number; dur: number } | null = null
  private sent = new Set<string>()                       // implicit signals already sent for the current track
  private info = new Map<string, { gain: number | null; start: number; end: number | null }>()
  private defGain = 0.6                                  // median measured gain: used until a fresh track is measured
  private g = [1, 1]                                     // applied (smoothed) levelling gain per element
  private fade = [1, 1]                                  // crossfade multiplier per element
  private gainTimer = 0
  private xfOld: HTMLAudioElement | null = null          // the element fading out
  private xfTimer = 0
  private xfBegin = false
  private ctx: AudioContext | null = null
  private gains: GainNode[] = []
  private pre: GainNode | null = null
  private chain: BiquadFilterNode[] = []
  private comp: DynamicsCompressorNode | null = null
  private post: GainNode | null = null
  private sleepTimer = 0
  private resume: { vid: string; pos: number; scrobbled: boolean } | null = null
  private posSaved = 0
  private idleTimer = 0
  private sleepFade = 1

  constructor() {
    for (let i = 0; i < 2; i++) {
      const el = new Audio()
      el.preload = 'auto'
      el.volume = this.volume
      this.els.push(el)
      const on = (ev: string, fn: () => void) => el.addEventListener(ev, () => { if (el === this.el) fn() })
      on('timeupdate', () => this.onTime())
      on('durationchange', () => { if (isFinite(el.duration)) this.duration = el.duration })
      on('play', () => { this.playing = true; this.wakeAudio() })
      on('pause', () => { this.playing = false; this.idleAudio() })
      on('waiting', () => (this.buffering = true))
      on('playing', () => { this.buffering = false; this.errors = 0 })
      on('canplay', () => (this.buffering = false))
      on('ended', () => { this.finishTrack('ended'); if (this.sleepEnd) this.sleepNow(); else this.next() })
      on('error', () => this.onError())
    }
    const saved = store.get<{ queue: Song[]; idx: number; pos?: number; vid?: string; scrobbled?: boolean; at?: number } | null>('player', null)
    if (saved?.queue?.length) {
      this.queue = saved.queue; this.idx = saved.idx
      // a reload continues where you were (same song, same second, already-scrobbled stays scrobbled), < 12 h old
      if (saved.vid && saved.vid === this.queue[this.idx]?.videoId && saved.pos && Date.now() - (saved.at ?? 0) < 12 * 3600_000) {
        this.resume = { vid: saved.vid, pos: saved.pos, scrobbled: !!saved.scrobbled }
        this.time = saved.pos; this.duration = this.queue[this.idx].duration || 0
      }
    }
    this.reattachNest(!!saved?.scrobbled && saved?.vid === this.queue[this.idx]?.videoId)
    get<Record<string, number>>('/api/prefs', 0).then((p) => (this.prefs = p)).catch(() => {})
    get<{ can_cast: boolean; speaker: string | null }>('/api/me', 0)
      .then((m) => { this.canCast = !!m.can_cast; this.speakerName = m.speaker || 'Speaker' }).catch(() => {})
    this.mediaSession()
    window.addEventListener('pagehide', () => { this.flushSkip(); this.save() })   // closing / reloading the page
  }

  private get el() { return this.els[this.a] }
  private get standby() { return this.els[1 - this.a] }

  // ---------- queue / playback ----------

  async playList(list: Song[], i = 0) {
    this.leftAutoplay()
    this.finishTrack('switch')
    this.queue = list.map(plain)
    this.idx = -1
    if (this.nest) { if (this.autoplay && list.length - i < 10) await this.refill(); return this.nestPlay(i) }
    this.playIndex(i)
    if (this.autoplay && this.queue.length - i < 3) this.refill()
  }

  /** You replaced an autoplay run with something you chose: the picks that were waiting didn't hold you. */
  private leftAutoplay() {
    const cur = this.current, ahead = this.queue.slice(this.idx + 1, this.idx + 4).filter((t) => t.auto)
    if (!cur || !(cur.auto || this.queue[this.idx + 1]?.auto)) return
    for (const t of [...(cur.auto && this.el.currentTime < 60 ? [cur] : []), ...ahead]) this.signal('escape', t)
  }

  playIndex(i: number) {
    if (i < 0 || i >= this.queue.length) return
    if (i > this.idx + 1 && this.idx >= 0) {                   // jumped ahead in Up next: past the autoplay picks between
      for (const t of this.queue.slice(this.idx + 1, i)) if (t.auto) this.signal('pass', t)
      this.signal('queue_pick', this.queue[i])
    }
    if (this.xfOld && !this.xfBegin) this.endCrossfade()
    if (i !== this.idx) this.finishTrack('switch')
    if (this.pendingSkip && this.queue[i]?.videoId === this.pendingSkip.vid) {   // came straight back: it was a mis-tap
      clearTimeout(this.pendingSkip.timer)
      if (this.pendingSkip.auto) this.autoSkips = Math.max(0, this.autoSkips - 1)
      this.pendingSkip = null
    }
    if (this.nest) { this.nestPlay(i); return }
    this.audible = false
    this.idx = i
    this.scrobbled = false
    this.finished = false
    const t = this.queue[i]
    if (this.standby.dataset.vid === t.videoId) {             // gapless: the next track is already buffered
      const old = this.el
      this.a = 1 - this.a
      if (old !== this.xfOld) { old.pause(); old.removeAttribute('src'); old.load() }
      delete old.dataset.vid
      if (Math.abs(this.el.currentTime - this.startOf(t.videoId)) > 0.5) this.el.currentTime = this.startOf(t.videoId)
    } else {
      this.el.src = streamUrl(t.videoId)
      this.el.dataset.vid = t.videoId
      const el = this.el, vid = t.videoId
      el.addEventListener('loadedmetadata', () => { const s0 = this.startOf(vid); if (s0 && el.dataset.vid === vid && el.currentTime < s0) el.currentTime = s0 }, { once: true })
    }
    const res = this.resume && this.resume.vid === t.videoId ? this.resume : null
    this.resume = null
    if (res) {                                                    // continue after a reload
      const el = this.el, vid = t.videoId
      el.addEventListener('loadedmetadata', () => { if (el.dataset.vid === vid) el.currentTime = res.pos }, { once: true })
      this.scrobbled = res.scrobbled
    }
    this.g[this.a] = this.target(this.el)
    this.apply()
    this.time = res ? res.pos : 0
    this.duration = t.duration || 0
    this.buffering = true
    this.graph()
    this.el.play().catch(() => {})
    clearTimeout(this.watchdog)
    const el = this.el
    this.watchdog = window.setTimeout(() => {           // still nothing after 15 s: treat like an error (one retry)
      if (el === this.el && this.current?.videoId === t.videoId && el.currentTime < 0.5 && !this.nest) this.onError()
    }, 15000)
    this.updateSession()
    this.save()
    this.remember(t)
    post('/api/listen', { ...t, type: 'playing_now' }).catch(() => {})
    const nx = this.queue[i + 1]
    if (nx) warmStream(nx.videoId)
    this.loadInfo([t.videoId, nx?.videoId])
    if (this.autoplay && this.idx >= this.queue.length - 3) this.refill()
  }

  toggle() {
    if (this.xfOld) this.endCrossfade()
    if (this.nest) { this.nestPaused = !this.nestPaused; post('/api/nest/' + (this.nestPaused ? 'pause' : 'resume')); return }
    if (!this.el.src && this.current) return this.playIndex(this.idx)
    if (this.el.paused) { this.graph(); this.el.play().catch(() => {}) }
    else this.el.pause()
  }

  next() {
    if (this.nest) { post('/api/nest/next').then(() => setTimeout(() => this.nestPoll(), 1200)); return }
    this.finishTrack('next')
    if (this.idx < this.queue.length - 1) return this.playIndex(this.idx + 1)
    if (this.autoplay) this.refill().then(() => { if (this.idx < this.queue.length - 1) this.playIndex(this.idx + 1) })
    else this.el.pause()
  }

  prev() {
    if (this.nest) return
    if (this.el.currentTime > 4) this.el.currentTime = this.startOf(this.current?.videoId)
    else this.playIndex(Math.max(0, this.idx - 1))
  }

  seek(t: number) {
    const from = this.time, d = this.duration
    if (t <= from - 10) this.signal('seek_back')
    else if (d && t - from > 0.2 * d) this.signal('seek_fwd')
    if (this.nest) { post('/api/nest/seek', { t }); this.time = t; return }
    if (isFinite(t)) { this.el.currentTime = t; this.time = t }
  }

  setVolume(v: number) {
    if (v - this.volume >= 0.1 && this.playing) this.signal('volume_up')
    this.volume = v
    this.apply()
    store.set('volume', v)
  }

  setNormalize(on: boolean) { this.normalize = on; store.set('normalize', on); this.smooth() }
  setTrim(on: boolean) { this.trim = on; store.set('trimSilence', on) }
  setCrossfade(s: number) { this.crossfade = s; store.set('crossfade', s) }

  // ---------- sound: levelling, silence trimming, crossfade ----------

  private startOf(vid?: string) { const s0 = (this.trim && vid && this.info.get(vid)?.start) || 0; return s0 > 0.3 ? s0 : 0 }

  private target(el: HTMLAudioElement) {
    if (!this.normalize) return 1
    const v = el.dataset.vid, g = v ? this.info.get(v)?.gain : null
    return g ?? this.defGain
  }

  private apply() {
    this.els.forEach((el, i) => {
      const v = Math.max(0, Math.min(1, this.volume * this.g[i] * this.fade[i] * this.sleepFade))
      if (this.ctx) { el.volume = 1; this.gains[i].gain.setTargetAtTime(v, this.ctx.currentTime, 0.015) }
      else el.volume = v
    })
  }

  // ---------- sleep timer ----------

  /** minutes > 0, 'end' = after this song, 0 = off. On the Nest the server runs it (the page may be closed). */
  setSleep(m: number | 'end') {
    clearInterval(this.sleepTimer); this.sleepFade = 1; this.apply()
    if (this.nest) {
      this.sleepEnd = false
      post<{ at: number }>('/api/nest/sleep', m === 'end' ? { end_of_track: true } : { minutes: m })
        .then((r) => { this.sleepAt = r.at ? r.at * 1000 : 0 }).catch(() => ui.say("Couldn't set the speaker's sleep timer"))
    } else {
      this.sleepEnd = m === 'end'
      this.sleepAt = typeof m === 'number' && m > 0 ? Date.now() + m * 60_000 : 0
      if (this.sleepAt) this.sleepTimer = window.setInterval(() => this.sleepTick(), 1000)
    }
    ui.say(m === 'end' ? 'Stopping after this song' : m ? `Stopping in ${m} min` : 'Sleep timer off')
  }

  private sleepTick() {
    const left = (this.sleepAt - Date.now()) / 1000
    if (left <= 0) return this.sleepNow()
    if (left < 20) { this.sleepFade = left / 20; this.apply() }       // fade out over the last 20 s
  }

  private sleepNow() {
    clearInterval(this.sleepTimer)
    this.sleepAt = 0; this.sleepEnd = false
    if (this.xfOld) this.endCrossfade()
    this.el.pause()
    this.sleepFade = 1; this.apply()
    ui.say('Sleep timer: paused. Good night')
  }

  // ---------- headphone correction (AutoEq, experimental) ----------

  setEqOn(on: boolean) { this.eqOn = on; store.set('eqOn', on); if (on) this.graph(); this.applyEq() }
  setEq(p: EqProfile | null) { this.eq = p; store.set('eq', p); this.applyEq() }
  setOutput(o: Output) { this.output = o; store.set('output', o); this.graph(); this.applyEq() }
  setTone(t: { bass: number; treble: number }) { this.tone = t; store.set('tone', t); this.applyEq() }

  /** Build the Web Audio graph once (needs a user gesture: called from play / toggle / the switch). */
  private graph() {
    if (this.ctx) { if (this.ctx.state !== 'running') this.ctx.resume().catch(() => {}); return }
    if (!this.eqOn || typeof AudioContext === 'undefined') return
    // only inside a tap: a context created without one starts suspended = silence (the element is rerouted)
    if ((navigator as any).userActivation && !(navigator as any).userActivation.isActive) return
    try {
      const ctx = new AudioContext()
      this.pre = ctx.createGain()
      this.gains = this.els.map((el) => { const g = ctx.createGain(); ctx.createMediaElementSource(el).connect(g).connect(this.pre!); return g })
      this.comp = ctx.createDynamicsCompressor()
      this.post = ctx.createGain()
      this.comp.connect(this.post).connect(ctx.destination)
      this.ctx = ctx
      ctx.onstatechange = () => { if (ctx.state !== 'running' && this.playing) ctx.resume().catch(() => {}) }
      this.applyEq()
      this.apply()
    } catch (e) { console.warn('EQ unavailable', e); this.ctx = null }
  }

  /** pre (preamp) -> profile filters (AutoEq headphones / phone speaker) -> bass/treble -> compressor -> post -> out.
   *  Off (or the switch off) = flat: an element can't leave the graph once it's in. */
  private applyEq() {
    const ctx = this.ctx, pre = this.pre, comp = this.comp, post = this.post
    if (!ctx || !pre || !comp || !post) return
    pre.disconnect()
    for (const f of this.chain) f.disconnect()
    const on = this.eqOn && this.output !== 'off'
    const head = on && this.output === 'headphones' ? this.eq : null
    const spk = on && this.output === 'speaker'
    const tone = on ? this.tone : { bass: 0, treble: 0 }
    const list = [...(head?.filters ?? []), ...(spk ? PHONE_SPEAKER : [])]
    if (tone.bass) list.push({ type: 'lowshelf', f: spk ? 250 : 120, gain: tone.bass, q: 0.7 })
    if (tone.treble) list.push({ type: 'highshelf', f: 6000, gain: tone.treble, q: 0.7 })
    this.chain = list.map((x) => {
      const f = ctx.createBiquadFilter()
      f.type = x.type; f.frequency.value = x.f; f.gain.value = x.gain; f.Q.value = x.q
      return f
    })
    const boost = Math.max(0, ...list.filter((x) => x.type !== 'highpass').map((x) => x.gain))
    const preDb = head ? Math.min(0, head.preamp) - Math.max(0, tone.bass, tone.treble) : -boost   // keeps boosts from clipping
    pre.gain.value = Math.pow(10, preDb / 20)
    // speaker: gentle compression so quiet parts carry on a small speaker, then make up the level
    comp.threshold.value = spk ? -22 : 0; comp.ratio.value = spk ? 3 : 1; comp.knee.value = 10
    comp.attack.value = 0.005; comp.release.value = 0.2
    post.gain.value = spk ? Math.pow(10, (4 + boost) / 20) : 1
    let node: AudioNode = pre
    for (const f of this.chain) { node.connect(f); node = f }
    node.connect(comp)
  }

  /** Battery: a running AudioContext keeps the phone's audio output awake (streaming silence) even while
   *  paused. Suspend it 5 s into a pause; resume on play (the page already has user activation by then). */
  private idleAudio() {
    clearTimeout(this.idleTimer)
    this.idleTimer = window.setTimeout(() => {
      if (this.ctx && !this.playing && !this.xfOld && this.ctx.state === 'running') this.ctx.suspend().catch(() => {})
    }, 5000)
  }

  private wakeAudio() {
    clearTimeout(this.idleTimer)
    if (this.ctx && this.ctx.state !== 'running') this.ctx.resume().catch(() => {})
  }

  /** Ease each element's levelling gain to its target (~1 s), e.g. when a fresh download gets measured mid-song. */
  private smooth() {
    if (this.gainTimer) return
    this.gainTimer = window.setInterval(() => {
      let moving = false
      this.els.forEach((el, i) => {
        const d = this.target(el) - this.g[i]
        if (Math.abs(d) > 0.004) { this.g[i] += d * 0.12; moving = true } else this.g[i] += d
      })
      this.apply()
      if (!moving) { clearInterval(this.gainTimer); this.gainTimer = 0 }
    }, 50)
  }

  private async loadInfo(ids: (string | undefined)[], retry = 0) {
    const want = ids.filter((v): v is string => !!v && !this.info.has(v))
    if (!want.length) return
    try {
      const r = await get<Record<string, any>>(`/api/audio?ids=${want.join(',')}`, 0)
      if (typeof r.default === 'number') this.defGain = r.default
      for (const v of want) if (r[v]) this.info.set(v, r[v])
    } catch { /* keep defaults */ }
    this.smooth()
    const cur = this.current?.videoId                         // a fresh download is measured ~1-2 s after it lands
    if (cur && want.includes(cur) && !this.info.has(cur) && retry < 4) {
      setTimeout(() => this.loadInfo([cur], retry + 1), [3000, 6000, 15000, 40000][retry])
    }
  }

  /** Crossfade length for t -> nx, or 0 (off, same album = gapless, next not buffered, very short track). */
  private xfFor(t: Song, nx: Song, end: number) {
    if (!this.crossfade || this.sleepEnd || (t.album && t.album === nx.album)) return 0
    if (this.standby.dataset.vid !== nx.videoId || this.standby.readyState < 3 || end < 40) return 0
    return this.crossfade
  }

  private startCrossfade(xf: number) {
    const oi = this.a
    this.finishTrack('ended')
    this.xfOld = this.el
    this.fade[1 - oi] = 0
    this.xfBegin = true
    this.playIndex(this.idx + 1)                              // gapless branch: swaps elements, keeps the old one playing
    this.xfBegin = false
    const t0 = performance.now()
    clearInterval(this.xfTimer)
    this.xfTimer = window.setInterval(() => {
      const p = Math.min(1, (performance.now() - t0) / (xf * 1000))
      this.fade[oi] = Math.cos(p * Math.PI / 2); this.fade[1 - oi] = Math.sin(p * Math.PI / 2)
      this.apply()
      if (p >= 1) this.endCrossfade()
    }, 50)
  }

  private endCrossfade() {
    clearInterval(this.xfTimer)
    const old = this.xfOld
    this.xfOld = null
    if (old && old !== this.el) { old.pause(); old.removeAttribute('src'); delete old.dataset.vid; old.load() }
    this.fade = [1, 1]
    this.apply()
  }

  playNext(s: Song) {
    if (!this.current) return this.playList([s])
    this.queue.splice(this.idx + 1, 0, plain(s))
    this.signal('queue_add', s)
    this.save(); ui.say('Plays next')
  }

  addToQueue(s: Song) {
    if (!this.current) return this.playList([s])
    let at = this.queue.findIndex((t, k) => k > this.idx && t.auto)
    if (at < 0) at = this.queue.length
    this.queue.splice(at, 0, plain(s))
    this.signal('queue_add', s)
    this.save(); ui.say('Added to queue')
  }

  remove(i: number) {
    if (i > this.idx) this.signal('queue_remove', this.queue[i])
    if (i === this.idx) { this.next(); this.queue.splice(i, 1); this.idx = Math.max(0, this.idx - 1); return }
    this.queue.splice(i, 1)
    if (i < this.idx) this.idx--
    this.save()
  }

  move(i: number, d: number) {
    const j = i + d
    if (j <= this.idx || j >= this.queue.length || i <= this.idx) return
    const [t] = this.queue.splice(i, 1)
    this.queue.splice(j, 0, t)
    this.save()
  }

  shuffleRest() {
    const rest = this.queue.slice(this.idx + 1)
    for (let i = rest.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [rest[i], rest[j]] = [rest[j], rest[i]] }
    this.queue = [...this.queue.slice(0, this.idx + 1), ...rest]
    this.save(); ui.say('Shuffled')
  }

  startRadio(s: Song) {
    this.playList([s]).then(() => this.refill())             // a radio always fills, whatever the Autoplay setting
  }

  setAutoplay(on: boolean) {
    this.autoplay = on
    store.set('autoplay', on)
    if (on) { if (this.queue.length - this.idx < 3) this.refill() }
    else this.queue = this.queue.filter((t, k) => k <= this.idx || !t.auto)
    ui.say(on ? 'Autoplay on: similar songs keep playing' : 'Autoplay off')
  }

  // ---------- recommender feedback ----------

  /** Implicit feedback (replays are detected by the server). Sent at most once per track and kind. */
  signal(kind: string, t: Song | undefined = this.current) {
    if (!t) return
    const k = t.videoId + ':' + kind
    if (this.sent.has(k)) return
    this.sent.add(k)
    post('/api/event', { ...t, event: kind }).catch(() => {})
  }

  like(s: Song) {
    const on = this.prefs[s.videoId] === 1
    if (on) delete this.prefs[s.videoId]
    else this.prefs[s.videoId] = 1
    post('/api/event', { ...s, event: on ? 'unlike' : 'like' }).catch(() => {})
    if (!on) { this.lastGood = s; ui.say('Added to liked songs') }
  }

  /** Song only (not the artist): never picked by autoplay / mixes again. Toggle. */
  hide(s: Song) {
    if (this.prefs[s.videoId] === -1) {
      delete this.prefs[s.videoId]
      post('/api/event', { ...s, event: 'unhide' }).catch(() => {}); ui.say('Back in recommendations'); return
    }
    this.prefs[s.videoId] = -1
    post('/api/event', { ...s, event: 'hide' }).catch(() => {})
    ui.say("Hidden: it won't be recommended")
    if (this.current?.videoId === s.videoId) this.next()
    else this.queue = this.queue.filter((t, k) => k <= this.idx || t.videoId !== s.videoId)
  }

  /** What a track's end says about it (rules: trackOutcome in outcome.ts). A skip is sent after 20 s: coming back
   *  to the song in time cancels it (mis-tap). */
  private finishTrack(reason: EndReason) {
    const t = this.current
    if (!t || this.nest || this.finished || !this.el.src) return
    this.finished = true
    const d = this.el.duration || t.duration || 0, p = this.el.currentTime || 0
    const ev = trackOutcome(reason, p, d, this.audible)
    if (!ev) return
    const body = { ...t, event: ev, played: Math.round(p), duration: Math.round(d) || t.duration }
    if (ev === 'skip') {
      this.flushSkip()
      this.pendingSkip = { vid: t.videoId, body, auto: !!t.auto, timer: window.setTimeout(() => this.flushSkip(), 20_000) }
    } else post('/api/event', body).catch(() => {})
    if (ev === 'complete' || this.prefs[t.videoId] === 1) { this.lastGood = t; this.autoSkips = 0 }
    if (ev === 'skip' && t.auto && ++this.autoSkips >= 2 && this.autoplay) {
      this.autoSkips = 0                                         // two autoplay picks skipped: rebuild from the last kept song
      this.queue = this.queue.filter((x, k) => k <= this.idx + 1 || !x.auto)
      this.refill(this.lastGood)
      ui.say('Adjusting to your skips…')
    }
  }

  private flushSkip() {
    const p = this.pendingSkip
    if (!p) return
    clearTimeout(p.timer); this.pendingSkip = null
    fetch('/api/event', { method: 'POST', credentials: 'same-origin', keepalive: true,
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(p.body) }).catch(() => {})
  }

  refill(seed?: Song): Promise<void> {
    if (this.refilling) return this.refilling
    const s = seed || this.queue[this.queue.length - 1] || this.current
    if (!s) return Promise.resolve()
    const ex = this.queue.slice(-150).map((t) => t.videoId).join(',')
    this.refilling = get<Song[]>(`/api/autoplay?seed=${s.videoId}&exclude=${ex}`, 0).then((more) => {
      const have = new Set(this.queue.map((t) => t.videoId))
      this.queue.push(...more.filter((t) => !have.has(t.videoId)).map((t) => ({ ...t, auto: true })))
      this.save()
    }).catch(() => {}).finally(() => (this.refilling = null))
    return this.refilling
  }

  // ---------- audio element events ----------

  private onTime() {
    const el = this.el, c = el.currentTime
    if (Date.now() - this.posSaved > 5000) { this.posSaved = Date.now(); this.save() }
    if (!this.audible && !el.paused && c > this.startOf(this.current?.videoId) + 1) this.audible = true
    const d = isFinite(el.duration) ? el.duration : this.current?.duration || 0
    this.time = c
    if (d) this.duration = d
    const t = this.current
    if (t && !this.scrobbled && d > 30 && c >= Math.min(240, d / 2)) {
      this.scrobbled = true
      post('/api/listen', { ...t, type: 'single', listened_at: Math.floor(Date.now() / 1000 - c) }).catch(() => {})
    }
    const nx = this.queue[this.idx + 1]                           // pre-buffer the next track for a gapless change
    if (nx && d && !this.xfOld && c > Math.min(d * 0.5, d - 25) && this.standby.dataset.vid !== nx.videoId) {
      const sb = this.standby, vid = nx.videoId
      sb.src = streamUrl(vid)
      sb.dataset.vid = vid
      this.g[1 - this.a] = this.target(sb)
      sb.addEventListener('loadedmetadata', () => { const s0 = this.startOf(vid); if (s0 && sb.dataset.vid === vid) sb.currentTime = s0 }, { once: true })
      sb.load()
      this.loadInfo([vid])
    }
    if (t && nx && d && !this.xfOld && this.el === el && !el.paused) {   // silent tail / crossfade into the next track
      const e = this.info.get(t.videoId)?.end
      const end = this.trim && e && e < d - 0.3 ? e : d
      const xf = this.xfFor(t, nx, end)
      if (xf && c >= end - xf) this.startCrossfade(xf)
      else if (!xf && end < d - 0.3 && c >= end - 0.05) { this.finishTrack('ended'); if (this.sleepEnd) this.sleepNow(); else this.next() }
    }
    if ('mediaSession' in navigator && d && isFinite(d)) {
      try { navigator.mediaSession.setPositionState({ duration: d, position: Math.min(c, d), playbackRate: 1 }) } catch { /* */ }
    }
  }

  private onError() {
    const t = this.current
    if (!t || !this.el.src) return
    if (!t.retried) {
      t.retried = true
      setTimeout(() => { this.el.src = streamUrl(t.videoId, true); this.el.play().catch(() => {}) }, 700)
      return
    }
    this.errors++
    this.finishTrack('error')                                  // its fault, not the song's: no skip
    ui.say(`Can't play "${t.title}", skipping`)
    if (this.errors < 4) setTimeout(() => this.next(), 1000)
  }

  // ---------- Nest ----------

  /** After a reload: if the Nest is playing a song of this queue, follow it again instead of starting over. */
  private async reattachNest(scrobbled: boolean) {
    try {
      const st = await get<NestStatus & { allowed?: boolean }>('/api/nest/status', 0)
      if (!st.active || !st.videoId || st.allowed === false) return
      const k = this.queue.findIndex((t) => t.videoId === st.videoId)
      if (k < 0) return
      this.idx = k; this.resume = null
      this.nest = true; this.nestPaused = st.state === 'PAUSED'
      this.nestStarted = Date.now() - 10_000                      // already running: trust its position at once
      this.scrobbled = scrobbled && st.videoId === this.queue[k].videoId; this.nestLast = null   // not a new play
      this.updateSession(); this.nestPoll()
    } catch { /* no Nest: stay on the phone */ }
  }

  async toNest() {
    if (!this.current) return
    if (this.autoplay && this.queue.length - this.idx < 10) await this.refill()
    this.nestPlay(this.idx)
  }

  async toPhone() {
    let pos = 0
    try { pos = (await get<NestStatus>('/api/nest/status', 0)).position || 0 } catch { /* */ }
    const keepScrobbled = this.scrobbled                          // the phone continues the same play: don't count it twice
    this.nest = false
    clearTimeout(this.nestTimer)
    post('/api/nest/stop').catch(() => {})
    this.finished = true
    const i = this.idx
    this.idx = -1
    this.playIndex(i)
    this.scrobbled = keepScrobbled
    if (pos > 5) this.el.addEventListener('loadedmetadata', () => (this.el.currentTime = pos), { once: true })
  }

  private async nestPlay(i: number) {
    if (this.xfOld) this.endCrossfade()
    this.idx = i
    this.nest = true
    this.nestPaused = false
    this.el.pause()
    this.time = 0
    ui.say(`Sending to ${this.speakerName}…`)
    try {
      await post('/api/nest/play', { tracks: this.queue.slice(i, i + 100).map((t) => ({ videoId: t.videoId, title: t.title,
        artist: t.artist, thumb: large(t.thumb) })) })
      ui.say(`Playing on ${this.speakerName}`)
    } catch (e) { ui.say(`${this.speakerName}: ` + (e as Error).message) }
    this.nestStarted = Date.now()
    this.nestStart()
    this.nestPoll()
  }

  /** A track started on the Nest: reset its scrobble, tell ListenBrainz "playing now". */
  private nestStart() {
    this.scrobbled = false
    this.nestLast = null
    const t = this.current
    if (t) post('/api/listen', { ...t, type: 'playing_now' }).catch(() => {})
  }

  /** A track on the Nest ended or was skipped: the same complete / partial / skip event as on the phone. */
  /** stopped = the music was stopped (speaker / app / back to phone): an early stop isn't a skip of that song. */
  private nestFinish(stopped = false) {
    const l = this.nestLast
    this.nestLast = null
    if (!l) return
    const ev = speakerOutcome(l.pos, l.dur, stopped)
    if (!ev) return
    post('/api/event', { ...l.t, event: ev, played: Math.round(l.pos), duration: Math.round(l.dur) }).catch(() => {})
    if (ev === 'complete' && !this.scrobbled && l.dur > 30) {     // ended between two polls before the halfway check
      post('/api/listen', { ...l.t, type: 'single', listened_at: Math.floor(Date.now() / 1000 - l.pos) }).catch(() => {})
    }
  }

  private async nestPoll() {
    clearTimeout(this.nestTimer)
    if (!this.nest) return
    try {
      const st = await get<NestStatus>('/api/nest/status', 0)
      if (!this.nest) return
      if (!st.active && Date.now() - this.nestStarted > 15000) {
        this.nestFinish(true); this.nest = false; ui.say(`${this.speakerName} stopped playing`); return
      }
      if (st.videoId && this.current && st.videoId !== this.current.videoId) {
        this.nestFinish()
        const k = this.queue.findIndex((t, j) => j >= this.idx - 1 && t.videoId === st.videoId)
        if (k >= 0) { this.idx = k; this.updateSession(); this.nestStart() }
      }
      this.nestPaused = st.state === 'PAUSED'
      this.sleepAt = st.sleep_at ? st.sleep_at * 1000 : 0
      const fresh = Date.now() - this.nestStarted > 4000 && ['PLAYING', 'PAUSED', 'BUFFERING'].includes(st.state || '')
      this.playing = fresh ? st.state !== 'PAUSED' : true
      this.time = fresh ? st.position || 0 : 0
      this.duration = (fresh && st.duration) || this.current?.duration || 0
      const t = this.current
      if (t && fresh) {                                           // the same scrobble rule as on the phone
        this.nestLast = { t, pos: this.time, dur: this.duration }
        if (!this.scrobbled && this.duration > 30 && this.time >= Math.min(240, this.duration / 2)) {
          this.scrobbled = true
          post('/api/listen', { ...t, type: 'single', listened_at: Math.floor(Date.now() / 1000 - this.time) }).catch(() => {})
        }
      }
    } catch { /* keep polling */ }
    this.nestTimer = window.setTimeout(() => this.nestPoll(), document.hidden ? 5000 : 1000)
  }

  // ---------- persistence / OS integration ----------

  private save() {
    store.set('player', { queue: $state.snapshot(this.queue.slice(Math.max(0, this.idx - 20), this.idx + 80)),
                          idx: Math.min(this.idx, 20), vid: this.current?.videoId,
                          pos: this.nest ? 0 : Math.floor(this.el.currentTime || this.resume?.pos || 0),
                          scrobbled: this.scrobbled, at: Date.now() })
  }

  private remember(t: Song) {
    const r = store.get<Song[]>('recent', []).filter((x) => x.videoId !== t.videoId)
    r.unshift(plain(t))
    store.set('recent', r.slice(0, 30))
  }

  private updateSession() {
    const t = this.current
    if (!t || !('mediaSession' in navigator)) return
    document.title = `${t.title} · Kassetto`
    navigator.mediaSession.metadata = new MediaMetadata({ title: t.title, artist: t.artist, album: t.album || '',
      artwork: t.thumb ? [{ src: large(t.thumb), sizes: '544x544' }] : [] })
  }

  private mediaSession() {
    if (!('mediaSession' in navigator)) return
    const ms = navigator.mediaSession
    ms.setActionHandler('play', () => this.toggle())
    ms.setActionHandler('pause', () => this.toggle())
    ms.setActionHandler('nexttrack', () => this.next())
    ms.setActionHandler('previoustrack', () => this.prev())
    try { ms.setActionHandler('seekto', (e) => this.seek(e.seekTime || 0)) } catch { /* */ }
  }
}

export const player = new Player()
