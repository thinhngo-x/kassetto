<!-- Song actions: bottom sheet on phones, centred card on desktop. Esc / back / backdrop closes. -->
<script lang="ts">
  import Art from './Art.svelte'
  import Icon from './Icon.svelte'
  import { player } from '../lib/player.svelte'
  import { router } from '../lib/router.svelte'
  import { post } from '../lib/api'
  import { ui } from '../lib/ui.svelte'

  function act(fn: () => void) { fn(); ui.closeMenu() }
  /** Actions that open another page: close the menu *and* the full player first. */
  const nav = (r: Parameters<typeof router.go>[0]) => ui.leaveTo(() => router.go(r))
  async function plEdit(action: string, body: Record<string, unknown>, msg?: string) {
    ui.closeMenu()
    await post(`/api/myplaylist/${action}`, body).catch(() => ui.say("Couldn't change the playlist"))
    ui.plVersion++
    if (msg) ui.say(msg)
  }
  function key(e: KeyboardEvent) { if (e.key === 'Escape' && ui.menu) ui.closeMenu() }
</script>

<svelte:window onkeydown={key} />

{#if ui.menu}
  {@const m = ui.menu}
  {@const s = m.song}
  {@const qi = m.queueIndex}
  {@const liked = player.prefs[s.videoId] === 1}
  <div class="backdrop" role="presentation" onclick={() => ui.closeMenu()}></div>
  <div class="menu" role="dialog" aria-label="Song options" aria-modal="true">
    <div class="head">
      <Art src={s.thumb} size={52} />
      <div class="meta"><div class="t ellipsis">{s.title}</div><div class="s ellipsis">{s.artist}</div>{#if s.because || s.why}<div class="b ellipsis">{s.because ?? `Picked: ${s.why}`}</div>{/if}</div>
    </div>
    <button onclick={() => act(() => player.playNext(s))}><Icon name="playnext" /> Play next</button>
    <button onclick={() => act(() => player.addToQueue(s))}><Icon name="addq" /> Add to queue</button>
    <button onclick={() => ui.openAddTo([s])}><Icon name="plus" /> Add to playlist</button>
    <button onclick={() => act(() => player.startRadio(s))}><Icon name="radio" /> Start radio</button>
    <button onclick={() => nav({ name: 'detail', kind: 'versions', id: s.videoId })}><Icon name="library" /> Other versions</button>
    <button onclick={() => act(() => player.like(s))}><Icon name={liked ? 'liked' : 'like'} /> {liked ? 'Remove from liked songs' : 'Add to liked songs'}</button>
    <button onclick={() => act(() => player.hide(s))}><Icon name="hide" /> {player.prefs[s.videoId] === -1 ? 'Show in recommendations again' : 'Hide from recommendations'}</button>
    <button onclick={() => nav({ name: 'search', q: s.artist.split(',')[0], f: 'all' })}><Icon name="search" /> Search {s.artist.split(',')[0]}</button>
    {#if m.playlist}
      {@const pl = m.playlist}
      <button onclick={() => plEdit('move', { id: pl.id, videoId: s.videoId, to: pl.index - 1 })} disabled={pl.index === 0}><Icon name="up" /> Move up in playlist</button>
      <button onclick={() => plEdit('move', { id: pl.id, videoId: s.videoId, to: pl.index + 1 })} disabled={pl.index >= pl.count - 1}><Icon name="dn" /> Move down in playlist</button>
      <button onclick={() => plEdit('remove', { id: pl.id, videoId: s.videoId }, 'Removed from playlist')}><Icon name="trash" /> Remove from playlist</button>
    {/if}
    {#if qi !== undefined && qi > player.idx}
      <button onclick={() => act(() => player.move(qi, -1))} disabled={qi <= player.idx + 1}><Icon name="up" /> Move up</button>
      <button onclick={() => act(() => player.move(qi, 1))} disabled={qi >= player.queue.length - 1}><Icon name="dn" /> Move down</button>
      <button onclick={() => act(() => player.remove(qi))}><Icon name="trash" /> Remove from queue</button>
    {/if}
  </div>
{/if}

<style>
  .b { font-size: 12px; color: var(--accent); margin-top: 2px; }
  .backdrop { position: fixed; inset: 0; z-index: 80; background: rgb(0 0 0 / .5); animation: fade .18s ease; }
  .menu { position: fixed; z-index: 81; left: 0; right: 0; bottom: 0; max-height: 80vh; overflow-y: auto;
          padding: 10px 10px calc(14px + env(safe-area-inset-bottom)); background: var(--surface); border-radius: 18px 18px 0 0;
          box-shadow: var(--shadow); animation: up .26s var(--ease); }
  @media (min-width: 960px) {
    .menu { left: 50%; right: auto; bottom: auto; top: 50%; width: 380px; border-radius: 16px; transform: translate(-50%, -50%);
            animation: pop .18s var(--ease); }
  }
  .head { display: flex; gap: 12px; align-items: center; padding: 6px 8px 12px; border-bottom: 1px solid var(--line); margin-bottom: 6px; }
  .meta { min-width: 0; }
  .t { font-weight: 650; }
  .s { color: var(--muted); font-size: 13px; }
  button { width: 100%; display: flex; align-items: center; gap: 16px; padding: 12px; border-radius: 10px; text-align: left; color: var(--fg); }
  button :global(svg) { color: var(--fg-2); width: 20px; height: 20px; }
  button:hover { background: var(--surface-2); }
  button:disabled { opacity: .35; }
  @keyframes fade { from { opacity: 0; } }
  @keyframes up { from { transform: translateY(100%); } }
  @keyframes pop { from { opacity: 0; transform: translate(-50%, -46%); } }
</style>
