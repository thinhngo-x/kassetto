<script lang="ts">
  import Icon from '../components/Icon.svelte'
  import Shelf from '../components/Shelf.svelte'
  import SongRow from '../components/SongRow.svelte'
  import Tile from '../components/Tile.svelte'
  import { get, post, store } from '../lib/api'
  import { router } from '../lib/router.svelte'
  import { ui } from '../lib/ui.svelte'
  import { player } from '../lib/player.svelte'
  import type { Item, Song } from '../lib/types'

  let likes = $state<Song[] | null>(null)
  let showAll = $state(false)
  let allGigs = $state(false)
  interface Pl { id: string; name: string; count: number; shared: boolean; mine: boolean; thumb: string | null; owner: string; circle_name?: string; owner_name?: string }
  let pls = $state<Pl[] | null>(null)
  interface Gig { id: string; artist: string; date: string; time: string; venue: string; city: string; url: string; status?: string }
  let gigs = $state<{ updated: number | null; events: Gig[] } | null>(null)
  $effect(() => { get<typeof gigs>('/api/concerts', 3600_000).then((v) => (gigs = v)).catch(() => {}) })
  const gigDate = (d: string) => new Date(d + 'T12:00').toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })
  $effect(() => { void ui.plVersion; get<Pl[]>('/api/myplaylists', 0).then((v) => (pls = v)).catch(() => (pls = [])) })
  async function newPlaylist() {
    const name = prompt('New playlist name')?.trim()
    if (!name) return
    const { id } = await post<{ id: string }>('/api/myplaylists', { name })
    ui.plVersion++
    router.go({ name: 'detail', kind: 'myplaylist', id })
  }
  const asItem = (p: Pl): Item => ({ type: 'myplaylist', id: p.id, title: p.name, thumb: p.thumb,
    sub: `${p.count} songs${p.shared ? ` · ${p.circle_name}` : ''}${p.mine ? '' : ` · by ${p.owner_name}`}` })
  const recent = store.get<Song[]>('recent', [])
  $effect(() => { get<Song[]>('/api/likes', 0).then((v) => (likes = v)).catch(() => (likes = [])) })
  let shown = $derived(likes ? (showAll ? likes : likes.slice(0, 8)) : [])
</script>

<div class="page">
  <div class="top">
    <h1 class="h">Library</h1>
    <button class="icon-btn" aria-label="Your stats" title="Your stats" onclick={() => router.go({ name: 'stats' })}><Icon name="chart" size={22} /></button>
    <button class="icon-btn" aria-label="Settings" title="Settings" onclick={() => router.go({ name: 'settings' })}><Icon name="gear" size={22} /></button>
  </div>

  <section>
    <h2 class="section-title">Your playlists <button class="more" onclick={newPlaylist}><Icon name="plus" size={16} /> New</button></h2>
    {#if pls?.length}
      <div class="pls">{#each pls as p (p.id)}<Tile item={asItem(p)} size={140} />{/each}</div>
    {:else if pls}
      <p class="muted">Make playlists with <b>New</b>, or ⋯ → <b>Add to playlist</b> on any song. Share one and you can both add to it.</p>
    {/if}
  </section>

  <section>
    <h2 class="section-title">Liked songs <small>{likes?.length ?? ''}</small></h2>
    {#if likes?.length}
      <div class="acts">
        <button class="pill" onclick={() => player.playList(likes!, 0)}><Icon name="play" size={20} /> Play</button>
        <button class="pill ghost" onclick={() => { const a = likes!.slice().sort(() => Math.random() - 0.5); player.playList(a, 0) }}><Icon name="shuffle" size={20} /> Shuffle</button>
      </div>
      {#each shown as t, i (t.videoId + ':' + i)}<SongRow song={t} onplay={() => player.playList(likes!, i)} />{/each}
      {#if likes.length > 8}<button class="more" onclick={() => (showAll = !showAll)}>{showAll ? 'Show less' : `Show all ${likes.length}`}</button>{/if}
    {:else if likes}
      <p class="muted">Tap ♡ in the player and your liked songs collect here.</p>
    {:else}
      {#each Array(4) as _}<div class="skel" style="height:56px;margin:8px 0"></div>{/each}
    {/if}
  </section>

  {#if recent.length}<Shelf title="Recently played" items={recent} />{/if}

  {#if gigs?.events.length}
    <section>
      <h2 class="section-title">Concerts near you <small>artists you listen to · near you</small></h2>
      {#each gigs.events.slice(0, allGigs ? 30 : 3) as g (g.id)}
        <a class="gig" href={g.url} target="_blank" rel="noopener">
          <span class="gd">{gigDate(g.date)}{g.time ? ` · ${g.time}` : ''}</span>
          <span class="ellipsis"><b>{g.artist}</b><small>{g.venue}, {g.city}{g.status === 'cancelled' ? ' · cancelled' : ''}</small></span>
          <Icon name="right" size={18} />
        </a>
      {/each}
      {#if gigs.events.length > 3}<button class="more" onclick={() => (allGigs = !allGigs)}>{allGigs ? 'Show less' : `All ${gigs.events.length} concerts`}</button>{/if}
    </section>
  {/if}



</div>

<style>
  .top { display: flex; align-items: center; gap: 4px; margin: 18px 0 0; }
  .top .h { flex: 1; margin: 0; }
  .h { font-size: 28px; font-weight: 800; margin: 18px 0 0; }
  .acts { display: flex; gap: 10px; margin-bottom: 8px; }
  .more { margin: 6px 8px; color: var(--muted); font-weight: 600; font-size: 14px; }
  .more:hover { color: var(--fg); }
  .pls { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 16px 12px; }
  .pls :global(.tile) { width: 100%; }
  .pls :global(.art) { width: 100% !important; height: auto !important; aspect-ratio: 1; }
  .gig { display: flex; align-items: center; gap: 14px; padding: 10px 12px; border-radius: 12px; background: var(--surface); margin-bottom: 8px; color: var(--fg); text-decoration: none; }
  .gig:hover { background: var(--surface-2); }
  .gig .gd { flex: none; width: 128px; color: var(--accent); font-weight: 650; font-size: 13px; }
  .gig span.ellipsis { display: flex; flex-direction: column; flex: 1; min-width: 0; }
  .gig small { color: var(--muted); font-size: 12px; }
  .section-title .more { margin: 0 0 0 auto; display: inline-flex; align-items: center; gap: 4px; }
</style>
