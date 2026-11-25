<script lang="ts">
  import Art from '../components/Art.svelte'
  import Icon from '../components/Icon.svelte'
  import Shelf from '../components/Shelf.svelte'
  import SongRow from '../components/SongRow.svelte'
  import Tile from '../components/Tile.svelte'
  import { get, resolveSoon, store } from '../lib/api'
  import { player } from '../lib/player.svelte'
  import { router } from '../lib/router.svelte'
  import type { Entry, Item, Song } from '../lib/types'

  interface Results {
    q?: string; intent?: 'lookup' | 'similar' | 'vibe'; top?: Entry | null; library?: Song[]; songs?: Song[]
    artists?: Item[]; albums?: Item[]; playlists?: Item[]; vibe?: Song[]; similar?: { seed: Song; songs: Song[] }
  }

  let { q, f }: { q: string; f: string } = $props()
  const FILTERS = [['all', 'All'], ['songs', 'Songs'], ['artists', 'Artists'], ['albums', 'Albums'], ['playlists', 'Playlists'], ['videos', 'Videos']]
  const EXAMPLES = ['songs like The Night We Met', 'nhạc buồn chill', 'calm acoustic folk', 'energetic rock with big vocals']

  let text = $state('')
  let focused = $state(false)
  let suggestions = $state<string[]>([])
  let quick = $state<Song[]>([])
  let recent = $state<string[]>(store.get('searches', []))
  let loading = $state(false)
  let all = $state<Results>({})
  let list = $state<Entry[]>([])
  let input: HTMLInputElement
  let timer = 0, seq = 0

  $effect(() => {                                    // run the search whenever the route's q / f change
    const query = q, filter = f
    text = query
    if (!query) { all = {}; list = []; queueMicrotask(() => input?.focus()); return }
    const my = ++seq
    loading = true
    const p = filter === 'all'
      ? get<Results>(`/api/search2?q=${encodeURIComponent(query)}`, 10 * 60_000).then((r) => { if (my === seq) { all = r; warmResults(r) } })
      : get<Entry[]>(`/api/search?q=${encodeURIComponent(query)}&filter=${filter}`, 10 * 60_000).then((r) => { if (my === seq) { list = r; resolveSoon(songsOf(r).slice(0, 2).map((t) => t.videoId)) } })
    p.catch(() => {}).finally(() => { if (my === seq) loading = false })
  })

  /** The songs most likely to be tapped next, looked up ahead (see resolveSoon). */
  function warmResults(r: Results) {
    const top = r.top?.type === 'song' ? r.top.videoId : undefined
    if (r.intent === 'vibe') return resolveSoon([r.vibe?.[0]?.videoId])
    if (r.intent === 'similar') return resolveSoon([r.similar?.seed.videoId, r.similar?.songs[0]?.videoId])
    resolveSoon([top, ...(r.songs ?? []).slice(0, 2).map((t) => t.videoId), r.library?.[0]?.videoId])
  }
  function onInput() {
    clearTimeout(timer)
    const v = text.trim()
    if (!v) { suggestions = []; quick = []; return }
    timer = window.setTimeout(() => get<{ suggestions: string[]; library: Song[] }>(`/api/suggest2?q=${encodeURIComponent(v)}`, 60 * 60_000)
      .then((x) => { if (text.trim() === v) { suggestions = x.suggestions; quick = x.library } }).catch(() => {}), 150)
  }
  function submit(v = text) {
    v = v.trim()
    if (!v) return
    recent = [v, ...recent.filter((x) => x.toLowerCase() !== v.toLowerCase())].slice(0, 12)
    store.set('searches', recent)
    focused = false
    input?.blur()
    router.go({ name: 'search', q: v, f: q ? f : 'all' }, !!q && router.route.name === 'search')
  }
  function openTop(t: Entry) { if (t.type === 'song') { fromSearch(t); player.playList([t]) } else router.go({ name: 'detail', kind: t.type, id: t.id }) }
  /** A song started from search results = you went looking for it (implicit signal). */
  function fromSearch(t?: Song) { queueMicrotask(() => player.signal('search_click', t ?? player.current)) }
  const songsOf = (l: Entry[]) => l.filter((x): x is Song => x.type === 'song')
  const kindLabel = (t: Entry) => (t.type === 'song' ? `Song · ${t.artist}` : `${t.type[0].toUpperCase()}${t.type.slice(1)}${t.sub ? ' · ' + t.sub : ''}`)
  let showPanel = $derived(focused && (text.trim() ? suggestions.length + quick.length > 0 : true))
</script>

<div class="page">
  <form class="bar" role="search" onsubmit={(e) => { e.preventDefault(); submit() }}>
    <Icon name="search" size={19} />
    <input bind:this={input} bind:value={text} oninput={onInput} onfocus={() => (focused = true)}
           onblur={() => setTimeout(() => (focused = false), 150)} type="search" enterkeyhint="search"
           placeholder="Songs, artists, a mood, or “songs like …”" aria-label="Search" autocomplete="off" />
    {#if text}<button type="button" class="icon-btn" aria-label="Clear" onclick={() => { text = ''; suggestions = []; quick = []; input.focus() }}><Icon name="close" size={18} /></button>{/if}
  </form>

  {#if showPanel}
    <div class="panel">
      {#if text.trim()}
        {#each quick as t, i (t.videoId + i)}
          <button class="qs" onmousedown={(e) => e.preventDefault()} onclick={() => { focused = false; fromSearch(); player.playList([t]) }}>
            <Art src={t.thumb} size={36} /><span class="ellipsis"><b>{t.title}</b><small>{#if t.why === 'liked'}<Icon name="liked" size={11} label="liked" />{:else}<Icon name="history" size={11} label="played" />{/if} {t.artist}</small></span>
          </button>
        {/each}
        {#each suggestions as sg, i (sg + i)}<button onmousedown={(e) => e.preventDefault()} onclick={() => submit(sg)}><Icon name="search" size={17} />{sg}</button>{/each}
      {:else}
        {#if recent.length}
          <div class="ph">Recent searches</div>
          {#each recent.slice(0, 6) as r, i (r + i)}<button onmousedown={(e) => e.preventDefault()} onclick={() => submit(r)}><Icon name="back" size={17} />{r}</button>{/each}
        {/if}
        <div class="ph">Try</div>
        {#each EXAMPLES as ex}<button onmousedown={(e) => e.preventDefault()} onclick={() => submit(ex)}><Icon name="spark" size={17} />{ex}</button>{/each}
      {/if}
    </div>
  {/if}

  {#if q}
    <div class="chips filters">
      {#each FILTERS as [k, label]}
        <button class="chip" class:on={f === k} onclick={() => router.go({ name: 'search', q, f: k }, true)}>{label}</button>
      {/each}
    </div>

    {#if loading && !all.songs && !list.length}
      {#each Array(6) as _}<div class="skel skrow"></div>{/each}
    {:else if f === 'all'}
      {#if all.intent === 'vibe' && all.vibe?.length}
        <h2 class="section-title">Matches the vibe <small>from songs Kassetto has listened to</small></h2>
        <div class="acts"><button class="pill" onclick={() => (fromSearch(), player.playList(all.vibe!, 0))}><Icon name="play" size={18} /> Play these</button></div>
        {#each all.vibe.slice(0, 8) as t, i (t.videoId + i)}<SongRow song={t} onplay={() => (fromSearch(), player.playList(all.vibe!, i))} />{/each}
      {/if}

      {#if all.intent === 'similar' && all.similar}
        <h2 class="section-title">Songs like {all.similar.seed.title} <small>picked for you</small></h2>
        <div class="acts"><button class="pill" onclick={() => (fromSearch(), player.playList([all.similar!.seed, ...all.similar!.songs], 0))}><Icon name="play" size={18} /> Play</button></div>
        {#each all.similar.songs.slice(0, 10) as t, i (t.videoId + i)}<SongRow song={t} showWhy onplay={() => (fromSearch(), player.playList(all.similar!.songs, i))} />{/each}
      {/if}

      {#if all.top && all.intent === 'lookup'}
        {@const t = all.top}
        <h2 class="section-title">Top result</h2>
        <div class="top" role="button" tabindex="0" onclick={() => openTop(t)} onkeydown={(e) => e.key === 'Enter' && openTop(t)}>
          <Art src={t.thumb} size={96} round={t.type === 'artist'} eager />
          <div class="tm"><div class="tt ellipsis">{t.title}</div><div class="ts">{kindLabel(t)}</div></div>
          <span class="pbtn"><Icon name="play" size={22} /></span>
        </div>
      {/if}

      {#if all.library?.length && all.intent !== 'vibe'}
        <h2 class="section-title">From your library</h2>
        {#each all.library.slice(0, 3) as t, i (t.videoId + i)}<SongRow song={t} onplay={() => (fromSearch(), player.playList(all.library!, i))} />{/each}
      {/if}

      {#if all.intent === 'vibe'}<Shelf title="Playlists for this mood" items={all.playlists ?? []} />{/if}

      {#if all.songs?.length}
        <h2 class="section-title">Songs <button class="more" onclick={() => router.go({ name: 'search', q, f: 'songs' }, true)}>Show all</button></h2>
        {#each all.songs.slice(0, all.intent === 'lookup' ? 5 : 4) as t, i (t.videoId + i)}
          <SongRow song={t} onplay={() => (fromSearch(), player.playList([all.songs![i]]))} />
        {/each}
      {/if}
      <Shelf title="Artists" items={all.artists ?? []} />
      <Shelf title="Albums" items={all.albums ?? []} />
      {#if all.intent !== 'vibe'}<Shelf title="Playlists" items={all.playlists ?? []} />{/if}
    {:else if f === 'songs' || f === 'videos'}
      {@const songs = songsOf(list)}
      {#each songs as t, i (t.videoId + ':' + i)}<SongRow song={t} onplay={() => (fromSearch(), player.playList(songs, i))} />{/each}
      {#if !songs.length && !loading}<p class="muted">No results.</p>{/if}
    {:else}
      <div class="grid">{#each list as it, i ((it.type === 'song' ? it.videoId : it.id) + ':' + i)}<Tile item={it} />{/each}</div>
      {#if !list.length && !loading}<p class="muted">No results.</p>{/if}
    {/if}
  {:else if !focused}
    <p class="hint">Search any song, artist or album, describe a mood (“nhạc buồn chill”), or ask for “songs like …”. Ad-free.</p>
  {/if}
</div>

<style>
  .bar { position: sticky; top: 0; z-index: 10; display: flex; align-items: center; gap: 10px; height: 46px; margin: 12px 0 10px;
         padding: 0 6px 0 16px; border-radius: 23px; background: var(--surface-2); color: var(--muted); box-shadow: 0 0 0 8px var(--bg); }
  .bar:focus-within { box-shadow: 0 0 0 8px var(--bg), 0 0 0 2px var(--accent) inset; color: var(--fg); }
  input { flex: 1; min-width: 0; height: 100%; border: 0; outline: 0; background: none; font-size: 16px; color: var(--fg); }
  input::-webkit-search-cancel-button { display: none; }
  .panel { position: relative; z-index: 9; background: var(--surface); border-radius: 14px; padding: 6px; box-shadow: var(--shadow); margin-bottom: 10px; }
  .panel button { width: 100%; display: flex; align-items: center; gap: 14px; padding: 10px 12px; border-radius: 10px; text-align: left; color: var(--fg); }
  .panel button:hover { background: var(--surface-2); }
  .panel :global(svg) { color: var(--muted); flex: none; }
  .qs { padding: 6px 12px !important; }
  .qs span { display: flex; flex-direction: column; min-width: 0; }
  .qs small { color: var(--muted); font-size: 12px; }
  .ph { padding: 8px 12px 4px; font-size: 11.5px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
  .filters { margin: 4px 0 6px; }
  .acts { margin: -4px 0 6px; }
  .top { display: flex; align-items: center; gap: 16px; padding: 14px; border-radius: 16px; background: var(--surface); cursor: pointer; transition: background .15s; }
  .top:hover { background: var(--surface-2); }
  .tm { flex: 1; min-width: 0; }
  .tt { font-size: 21px; font-weight: 800; }
  .ts { color: var(--muted); margin-top: 4px; font-size: 14px; }
  .pbtn { width: 46px; height: 46px; border-radius: 50%; display: grid; place-items: center; background: var(--accent); color: var(--accent-fg); flex: none; }
  .more { margin-left: auto; font-size: 13px; font-weight: 600; color: var(--muted); }
  .more:hover { color: var(--fg); }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 18px 14px; margin-top: 14px; }
  .grid :global(.tile) { width: 100%; }
  .grid :global(.art) { width: 100% !important; height: auto !important; aspect-ratio: 1; }
  .skrow { height: 56px; margin: 8px 0; }
  .hint { color: var(--muted); text-align: center; margin-top: 16vh; padding: 0 24px; line-height: 1.6; }
</style>
