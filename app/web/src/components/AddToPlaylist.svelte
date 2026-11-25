<!-- 'Add to playlist' sheet: your playlists (+ ones shared with you), tick = already in it, or make a new one. -->
<script lang="ts">
  import Art from './Art.svelte'
  import Icon from './Icon.svelte'
  import { get, post } from '../lib/api'
  import { ui } from '../lib/ui.svelte'

  interface Pl { id: string; name: string; count: number; shared: boolean; mine: boolean; thumb: string | null; circle_name?: string; owner_name?: string }
  let lists = $state<Pl[] | null>(null)
  let has = $state<string[]>([])
  let name = $state('')
  let creating = $state(false)

  $effect(() => {
    const songs = ui.addTo
    if (!songs) return
    lists = null; name = ''; creating = false
    get<Pl[]>('/api/myplaylists', 0).then((v) => (lists = v)).catch(() => (lists = []))
    if (songs.length === 1) get<string[]>(`/api/myplaylist?containing=${songs[0].videoId}`, 0).then((v) => (has = v)).catch(() => (has = []))
    else has = []
  })
  async function add(p: Pl) {
    const songs = ui.addTo!
    const r = await post<{ added: number }>('/api/myplaylist/add', { id: p.id, songs })
    ui.closeAddTo(); ui.plVersion++
    ui.say(r.added ? `Added to ${p.name}` : `Already in ${p.name}`)
  }
  async function create() {
    const n = name.trim()
    if (!n) return
    const songs = ui.addTo!
    await post('/api/myplaylists', { name: n, songs })
    ui.closeAddTo(); ui.plVersion++
    ui.say(`Created ${n}`)
  }
</script>

{#if ui.addTo}
  <div class="backdrop" role="presentation" onclick={() => ui.closeAddTo()}></div>
  <div class="menu" role="dialog" aria-label="Add to playlist" aria-modal="true">
    <div class="h">Add {ui.addTo.length === 1 ? `“${ui.addTo[0].title}”` : `${ui.addTo.length} songs`} to…</div>
    {#if creating}
      <form class="new" onsubmit={(e) => { e.preventDefault(); create() }}>
        <!-- svelte-ignore a11y_autofocus -->
        <input bind:value={name} placeholder="Playlist name" maxlength="80" autofocus />
        <button class="pill" type="submit" disabled={!name.trim()}>Create</button>
      </form>
    {:else}
      <button class="row" onclick={() => (creating = true)}><span class="plus"><Icon name="plus" /></span> New playlist</button>
    {/if}
    {#if lists === null}
      {#each Array(3) as _}<div class="skel" style="height:52px;margin:6px 0"></div>{/each}
    {:else}
      {#each lists as p (p.id)}
        <button class="row" onclick={() => add(p)}>
          <Art src={p.thumb} size={44} />
          <span class="ellipsis"><b>{p.name}</b><small>{p.count} songs{p.shared ? ` · ${p.circle_name}` : ''}{p.mine ? '' : ` · by ${p.owner_name}`}</small></span>
          {#if has.includes(p.id)}<Icon name="check" size={18} />{/if}
        </button>
      {/each}
    {/if}
  </div>
{/if}

<style>
  .backdrop { position: fixed; inset: 0; z-index: 80; background: rgb(0 0 0 / .5); animation: fade .18s ease; }
  .menu { position: fixed; z-index: 81; left: 0; right: 0; bottom: 0; max-height: 80vh; overflow-y: auto;
          padding: 14px 10px calc(14px + env(safe-area-inset-bottom)); background: var(--surface); border-radius: 18px 18px 0 0;
          box-shadow: var(--shadow); animation: up .26s var(--ease); }
  @media (min-width: 960px) { .menu { left: 50%; right: auto; bottom: auto; top: 50%; width: 420px; transform: translate(-50%, -50%); border-radius: 18px; animation: none; } }
  .h { font-weight: 750; padding: 0 8px 10px; }
  .row { width: 100%; display: flex; align-items: center; gap: 12px; padding: 8px; border-radius: 10px; text-align: left; color: var(--fg); }
  .row:hover { background: var(--surface-2); }
  .row span.ellipsis { display: flex; flex-direction: column; flex: 1; min-width: 0; }
  .row :global(svg) { color: var(--accent); flex: none; }
  small { color: var(--muted); font-size: 12px; }
  .plus { width: 44px; height: 44px; border-radius: 8px; display: grid; place-items: center; background: var(--surface-2); }
  .new { display: flex; gap: 8px; padding: 4px 8px 8px; }
  .new input { flex: 1; min-width: 0; height: 40px; border: 0; border-radius: 10px; padding: 0 12px; background: var(--surface-2); color: var(--fg); font-size: 15px; }
  @keyframes up { from { transform: translateY(100%); } }
  @keyframes fade { from { opacity: 0; } }
</style>
