<script lang="ts">
  import Art from '../components/Art.svelte'
  import Icon from '../components/Icon.svelte'
  import Shelf from '../components/Shelf.svelte'
  import SongRow from '../components/SongRow.svelte'
  import { get, peek, post, resolveSoon } from '../lib/api'
  import { router } from '../lib/router.svelte'
  import { ui } from '../lib/ui.svelte'
  import { player } from '../lib/player.svelte'
  import type { Detail, Kind } from '../lib/types'

  let { kind, id }: { kind: Kind; id: string } = $props()
  let d = $state<Detail | null>(null)
  let error = $state('')

  $effect(() => {
    const path = `/api/${kind}?id=${encodeURIComponent(id)}`
    if (kind === 'myplaylist') void ui.plVersion                 // reload after an edit (add / remove / move)
    d = peek<Detail>(path) ?? null                   // instant when warmed on pointer-down / visited before
    error = ''
    get<Detail>(path, kind === 'mix' || kind === 'myplaylist' ? 0 : 10 * 60_000).then((v) => { d = v; resolveSoon(v.tracks.slice(0, 2).map((t) => t.videoId)) }).catch(() => (error = 'YouTube Music didn\'t return this page. Try again in a moment.'))
  })

  let total = $derived(d ? d.tracks.reduce((a, t) => a + (t.duration || 0), 0) : 0)
  const label: Record<Kind, string> = { album: 'Album', artist: 'Artist', playlist: 'Playlist', mix: 'Mix', lbplaylist: 'ListenBrainz', versions: 'Versions', myplaylist: 'Playlist' }
  let editable = $derived(!!d?.meta && d.meta.kind === 'user')
  async function rename() {
    const n = prompt('Playlist name', d?.title)?.trim()
    if (!n || !d?.meta) return
    await post('/api/myplaylist/rename', { id: d.meta.id, name: n }); ui.plVersion++
  }
  let circles = $state<{ id: string; name: string; members: { name: string }[] }[]>([])
  $effect(() => { if (kind === 'myplaylist') get<{ circles: typeof circles }>('/api/me', 3600_000).then((m) => (circles = m.circles)).catch(() => {}) })
  async function share(circle: string) {
    if (!d?.meta) return
    await post('/api/myplaylist/share', { id: d.meta.id, circle: circle || null }); ui.plVersion++
    const c = circles.find((x) => x.id === circle)
    ui.say(c ? `Shared with ${c.name}: everyone in it can add and remove songs` : 'Now private')
  }
  async function del() {
    if (!d?.meta || !confirm(`Delete “${d.title}”?`)) return
    await post('/api/myplaylist/delete', { id: d.meta.id }); ui.plVersion++
    ui.say('Playlist deleted'); router.go({ name: 'library' }, true)
  }
  function shuffle() {
    if (!d) return
    const a = d.tracks.slice()
    for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]] }
    player.playList(a, 0)
  }
</script>

<div class="page">
  {#if d}
    <header class="hero">
      <Art src={d.thumb || d.tracks[0]?.thumb} size={200} round={kind === 'artist'} eager />
      <div class="hm">
        <span class="kind">{label[kind]}</span>
        <h1>{d.title}</h1>
        {#if d.sub}<p class="sub">{d.sub}</p>{/if}
        {#if d.tracks.length}<p class="count">{d.tracks.length} songs{total ? ` · ${Math.round(total / 60)} min` : ''}</p>{/if}
      </div>
    </header>
    {#if d.tracks.length}
      <div class="acts">
        <button class="pill" onclick={() => player.playList(d!.tracks, 0)}><Icon name="play" size={20} /> Play</button>
        <button class="pill ghost" onclick={shuffle}><Icon name="shuffle" size={20} /> Shuffle</button>
        {#if kind !== 'myplaylist'}<button class="icon-btn" aria-label="Save as playlist" title="Save as playlist" onclick={() => ui.openAddTo(d!.tracks)}><Icon name="plus" /></button>{/if}
        {#if editable}
          <button class="icon-btn" aria-label="Rename" title="Rename" onclick={rename} disabled={!d.meta?.mine}><Icon name="edit" /></button>
          {#if d.meta?.mine}
            {#if circles.length}<label class="sharesel" class:on={d.meta.shared} title="Who can see and edit it"><Icon name="share" size={18} />
              <select value={d.meta.circle ?? ''} onchange={(e) => share((e.currentTarget as HTMLSelectElement).value)}>
                <option value="">Private</option>
                {#each circles as c}<option value={c.id}>Shared with {c.name} ({c.members.length})</option>{/each}
              </select></label>{/if}
          <button class="icon-btn" aria-label="Delete playlist" title="Delete" onclick={del}><Icon name="trash" /></button>{/if}
        {/if}
      </div>
      <div class="list">
        {#each d.tracks as t, i (t.videoId + i)}
          <SongRow song={t} num={kind === 'album' ? i + 1 : null} onplay={() => player.playList(d!.tracks, i)}
                   playlist={editable ? { id: d.meta!.id, index: i, count: d.tracks.length } : undefined} />
        {/each}
      </div>
    {:else if !d.albums?.length}
      <p class="muted">{kind === 'mix' ? 'Play and finish a few songs first, then your mix appears here.'
        : kind === 'myplaylist' ? (editable ? 'Empty for now: use ⋯ → Add to playlist on any song.' : 'Not enough listening for this one yet. It is rebuilt every Monday.')
        : 'Nothing playable here.'}</p>
      {#if editable && d.meta?.mine}<div class="acts"><button class="pill ghost" onclick={del}><Icon name="trash" size={18} /> Delete playlist</button></div>{/if}
    {/if}
    {#if d.albums?.length}<Shelf title="Albums & singles" items={d.albums} />{/if}
  {:else if error}
    <p class="muted">{error}</p>
  {:else}
    <div class="hero"><div class="skel" style="width:200px;height:200px"></div><div class="hm"><div class="skel" style="width:60%;height:30px"></div></div></div>
    {#each Array(8) as _}<div class="skel" style="height:56px;margin:8px 0"></div>{/each}
  {/if}
</div>

<style>
  .hero { display: flex; gap: 22px; align-items: flex-end; margin: 18px 0 18px; }
  .hero :global(.art) { border-radius: 12px; box-shadow: var(--shadow); }
  .hm { min-width: 0; flex: 1; }
  .kind { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); }
  h1 { font-size: clamp(24px, 4vw, 44px); font-weight: 850; margin: 4px 0 6px; line-height: 1.1;
       display: -webkit-box; -webkit-line-clamp: 3; line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
  .sub { margin: 0; color: var(--fg-2); }
  .count { margin: 4px 0 0; color: var(--muted); font-size: 13px; }
  .acts { display: flex; gap: 10px; margin-bottom: 10px; align-items: center; flex-wrap: wrap; }
  .sharesel { display: inline-flex; align-items: center; gap: 6px; height: 36px; padding: 0 10px; border-radius: 18px; background: var(--surface-2); color: var(--muted); }
  .sharesel.on { color: var(--accent); }
  .sharesel select { background: none; border: 0; color: var(--fg); font: inherit; font-size: 14px; }
  @media (max-width: 600px) {
    .hero { flex-direction: column; align-items: center; text-align: center; }
    .hero :global(.art) { width: min(60vw, 240px) !important; height: min(60vw, 240px) !important; }
    .acts { justify-content: center; }
  }
</style>
