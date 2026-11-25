<!-- Lyrics for the current track. Synced lyrics: the current line is highlighted, the view follows it
     (paused for 4 s after you scroll yourself, then it catches up), tapping a line seeks there. Plain lyrics: text.
     The position is extrapolated between player updates (phone ~4/s, Nest 1/s) so the highlight lands on time. -->
<script lang="ts">
  import { get, store } from '../lib/api'
  import { player } from '../lib/player.svelte'

  interface Lyr { synced: boolean; lines: { t: number | null; text: string; roman?: string }[]; source: string | null }
  let { height = '60vh' }: { height?: string } = $props()

  let lyr = $state<Lyr | null>(null)
  let loading = $state(false)
  let box = $state<HTMLDivElement>()
  let userScrollUntil = 0
  let phon = $state(store.get<boolean>('phonetics', true))          // romanized line under Korean / Japanese / Chinese …
  let hasPhon = $derived(!!lyr?.lines.some((l) => l.roman))
  const togglePhon = () => { phon = !phon; store.set('phonetics', phon) }
  let resume = 0

  $effect(() => {
    const t = player.current
    if (!t) { lyr = null; return }
    const q = new URLSearchParams({ videoId: t.videoId, title: t.title, artist: t.artist, duration: String(t.duration || '') })
    let stale = false
    loading = true
    lyr = null
    get<Lyr>(`/api/lyrics?${q}`, 24 * 3600_000).then((v) => { if (!stale) { lyr = v; if (v.lines.length) player.signal('lyrics_open', t) } })
      .catch(() => { if (!stale) lyr = { synced: false, lines: [], source: null } })
      .finally(() => { if (!stale) loading = false })
    return () => { stale = true }
  })

  // smooth clock: the last reported position + time since, while playing (capped: a stall can't run ahead)
  let now = $state(0)
  let base = 0, at = 0
  $effect(() => { base = player.time; at = performance.now(); now = base })
  $effect(() => {
    if (!player.playing || !lyr?.synced) return
    const id = setInterval(() => { if (!document.hidden) now = base + Math.min(1.5, (performance.now() - at) / 1000) }, 100)
    return () => clearInterval(id)
  })

  // index of the line being sung (binary search; a small lead so the highlight lands on time)
  let active = $derived.by(() => {
    if (!lyr?.synced) return -1
    const L = lyr.lines, t = now + 0.25
    let lo = 0, hi = L.length - 1, ans = -1
    while (lo <= hi) { const m = (lo + hi) >> 1; if ((L[m].t ?? 0) <= t) { ans = m; lo = m + 1 } else hi = m - 1 }
    return ans
  })

  /** Put the active line ~38 % down the box. Measured against the box itself (offsetTop would be relative to
   *  whatever positioned ancestor there is: the full-player sheet on phones, so it scrolled to the wrong place). */
  function follow(smooth = true) {
    const i = active
    if (i < 0 || !box || document.hidden || Date.now() < userScrollUntil) return
    const el = box.querySelectorAll<HTMLElement>('.line')[i]
    if (!el) return
    const top = box.scrollTop + el.getBoundingClientRect().top - box.getBoundingClientRect().top - box.clientHeight * 0.38
    box.scrollTo({ top: Math.max(0, top), behavior: smooth ? 'smooth' : 'auto' })
  }
  $effect(() => { void active; void box; follow() })
  $effect(() => { void phon; requestAnimationFrame(() => follow(false)) })          // line heights changed
  $effect(() => {
    const vis = () => { if (!document.hidden) follow(false) }
    document.addEventListener('visibilitychange', vis)
    return () => { document.removeEventListener('visibilitychange', vis); clearTimeout(resume) }
  })

  // only your own gestures pause following (its own smooth scrolling fires scroll events too)
  function onUser() {
    userScrollUntil = Date.now() + 4000
    clearTimeout(resume)
    resume = window.setTimeout(() => follow(), 4100)                 // then catch up, even mid-line
  }
</script>

{#if loading}
  <div class="state">{#each Array(6) as _, i}<div class="skel" style:width="{60 + ((i * 17) % 35)}%"></div>{/each}</div>
{:else if lyr && lyr.lines.length}
  {#if hasPhon}<button class="phon" class:on={phon} onclick={togglePhon} aria-pressed={phon}>{phon ? 'Hide phonetics' : 'Show phonetics'}</button>{/if}
  <div class="lyrics" class:synced={lyr.synced} style:height bind:this={box} onwheel={onUser} ontouchmove={onUser} onkeydown={onUser}
       onmousedown={(e) => { if (e.target === box) onUser() }}>
    {#each lyr.lines as ln, i (i)}
      {#if lyr.synced}
        <button class="line" class:on={i === active} class:past={i < active} onclick={() => { if (ln.t === null) return; userScrollUntil = 0; clearTimeout(resume); player.seek(ln.t) }}>
          {ln.text || '♪'}{#if phon && ln.roman}<span class="rom">{ln.roman}</span>{/if}
        </button>
      {:else}
        <p class="line plain">{ln.text || ' '}{#if phon && ln.roman}<span class="rom">{ln.roman}</span>{/if}</p>
      {/if}
    {/each}
    {#if lyr.source}<p class="src">Lyrics: {lyr.source}</p>{/if}
  </div>
{:else}
  <div class="state empty">No lyrics found for this song.</div>
{/if}

<style>
  .lyrics { overflow-y: auto; overscroll-behavior: contain; padding: 12px 4px 40vh; scroll-padding: 30%;
            mask-image: linear-gradient(to bottom, transparent 0, #000 8%, #000 80%, transparent 100%); }
  .line { display: block; width: 100%; text-align: left; font-size: clamp(20px, 2.4vw, 28px); font-weight: 750; line-height: 1.3;
          padding: 6px 0; color: color-mix(in srgb, var(--fg) 38%, transparent); letter-spacing: -0.01em;
          transition: color .3s ease, transform .3s var(--ease); transform-origin: left center; }
  .synced .line:hover { color: color-mix(in srgb, var(--fg) 70%, transparent); }
  .line.past { color: color-mix(in srgb, var(--fg) 55%, transparent); }
  .line.on { color: var(--fg); transform: scale(1.02); }
  .plain { margin: 0; color: var(--fg-2); font-size: 18px; font-weight: 600; cursor: default; }
  .rom { display: block; font-size: .62em; font-weight: 600; letter-spacing: 0; margin-top: 2px; opacity: .8; }
  .phon { float: right; position: relative; z-index: 1; margin: 4px 0 -30px; font-size: 12px; font-weight: 650; color: var(--muted);
          padding: 4px 10px; border-radius: 999px; background: color-mix(in srgb, var(--fg) 8%, transparent); }
  .phon.on { color: var(--fg); }
  .src { color: var(--muted); font-size: 12px; margin-top: 24px; }
  .state { padding: 20px 4px; display: grid; gap: 14px; }
  .state .skel { height: 22px; }
  .empty { color: var(--muted); text-align: center; }
</style>
