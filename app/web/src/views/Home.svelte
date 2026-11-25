<script lang="ts">
  import Shelf from '../components/Shelf.svelte'
  import { get, store, swr } from '../lib/api'
  import { router } from '../lib/router.svelte'
  import type { Entry, PersonalShelf, Shelf as ShelfT, Song } from '../lib/types'

  let home = $state<ShelfT[]>([])
  let foryou = $state<PersonalShelf[]>([])
  let loaded = $state(false)
  const recent = store.get<Song[]>('recent', [])
  let quiz = $state(false)                                       // new here: offer the taste quiz
  $effect(() => { get<{ needed: boolean }>('/api/quiz/needed', 0).then((r) => (quiz = r.needed)).catch(() => {}) })

  $effect(() => {
    swr<PersonalShelf[]>('/api/foryou', (v) => (foryou = Array.isArray(v) && v[0]?.shelf ? v : []), 15 * 60_000)
    swr<ShelfT[]>('/api/home', (v) => { home = v; loaded = true }, 30 * 60_000)
  })

  // Curated home: a few rows that matter instead of YouTube Music's ~12 feed shelves (mostly playlists).
  // Each row merges the feed shelves matching it (interleaved, no duplicates); the rest stay under "More".
  const ROWS: { title: string; match: RegExp; only?: string[]; max: number }[] = [
    { title: 'Quick picks', match: /quick picks|song mixes|mixed for you|listen again/i, only: ['song'], max: 20 },
    { title: 'Trending songs', match: /trending songs|top songs|trending/i, only: ['song'], max: 15 },
    { title: 'Playlists for you', match: /featured playlists|^top in |for you/i, only: ['playlist'], max: 12 },
    { title: 'New releases', match: /new releases|new albums/i, only: ['album', 'single', 'playlist'], max: 12 },
    { title: 'Top artists', match: /^top in |top artists/i, only: ['artist'], max: 15 },
  ]
  const key = (e: Entry) => ('videoId' in e && e.videoId) || ('id' in e && e.id) || e.title
  let showMore = $state(false)
  let curated = $derived.by(() => {
    const used = new Set<string>(), shown = new Set<string>()      // feed shelves used / items already on a row
    const out: ShelfT[] = []
    const local = foryou.find((s) => s.regional)?.items ?? []      // KASSETTO_REGION's language shelf, if any
    for (const r of ROWS) {
      const src = home.filter((s) => r.match.test(s.title))
      const lists = src.map((s) => s.items.filter((e) => !r.only || r.only.includes(e.type)))
      if (r.title === 'Playlists for you') lists.unshift(local)     // your local-language picks first
      const items: Entry[] = []
      for (let i = 0; items.length < r.max && lists.some((l) => i < l.length); i++)
        for (const l of lists) {
          const e = l[i]
          if (e && !shown.has(key(e)) && items.length < r.max) { shown.add(key(e)); items.push(e) }
        }
      src.forEach((s, j) => { if (lists[r.title === 'Playlists for you' ? j + 1 : j].length) used.add(s.title) })   // took from it
      if (items.length >= 3) out.push({ title: r.title, items })
    }
    const rest = home.filter((s) => !used.has(s.title))
      .map((s) => ({ ...s, items: s.items.filter((e) => !shown.has(key(e))) })).filter((s) => s.items.length >= 3)
    return { rows: out, rest }
  })
  let personal = $derived(foryou.filter((s) => !s.regional))

  const h = new Date().getHours()
  const greet = h < 5 ? 'Good night' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
</script>

<div class="page">
  <h1 class="greet">{greet}</h1>
  {#if quiz}
    <button class="quizcard" onclick={() => router.go({ name: 'quiz' })}>
      <b>New here? Tell Kassetto what you like</b><small>10 quick rounds of 3 songs, about 2 minutes</small></button>
  {/if}
  {#each personal as s (s.shelf)}<Shelf title={s.shelf} items={s.items} />{/each}
  {#if recent.length}<Shelf title="Recently played" items={recent} />{/if}
  {#each curated.rows as s (s.title)}<Shelf title={s.title} items={s.items} />{/each}
  {#if curated.rest.length}
    {#if showMore}
      {#each curated.rest as s (s.title)}<Shelf title={s.title} items={s.items} />{/each}
    {/if}
    <button class="pill ghost more" onclick={() => (showMore = !showMore)}>
      {showMore ? 'Show less' : `More from YouTube Music (${curated.rest.length})`}</button>
  {/if}
  {#if !loaded && !home.length}
    {#each [0, 1, 2] as _}
      <div class="skel title"></div>
      <div class="skrow">{#each [0, 1, 2, 3, 4, 5] as __}<div class="skel tile"></div>{/each}</div>
    {/each}
  {/if}
</div>

<style>
  .more { display: block; margin: 28px auto 8px; }
  .greet { font-size: 28px; font-weight: 800; margin: 18px 0 2px; }
  .title { width: 180px; height: 22px; margin: 28px 0 14px; }
  .skrow { display: flex; gap: 14px; overflow: hidden; }
  .tile { width: 156px; height: 196px; flex: none; border-radius: 10px; }
  .quizcard { display: flex; flex-direction: column; gap: 2px; width: 100%; text-align: left; margin: 0 0 18px; padding: 14px 16px;
              border-radius: 12px; border: 1px solid var(--accent); background: none; color: inherit; cursor: pointer; }
</style>
