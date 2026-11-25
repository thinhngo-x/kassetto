<script lang="ts">
  import SongRow from './SongRow.svelte'
  import { player } from '../lib/player.svelte'

  let up = $derived(player.queue.slice(player.idx, player.idx + 80).map((t, k) => ({ t, i: player.idx + k })))
  let autoAt = $derived(up.findIndex((x, k) => k > 0 && x.t.auto))
</script>

{#if !up.length}
  <p class="empty">Nothing queued. Play something.</p>
{:else}
  {#each up as { t, i }, k (t.videoId + ':' + i)}
    {#if k === autoAt}
      <div class="divider"><span>Autoplay</span><small>picked for you</small></div>
    {/if}
    <SongRow song={t} queueIndex={i} showWhy={t.auto} onplay={() => player.playIndex(i)} />
  {/each}
  {#if !player.autoplay && player.idx >= player.queue.length - 1}
    <p class="empty">End of queue. Turn on Autoplay to keep going with similar songs.</p>
  {/if}
{/if}

<style>
  .divider { display: flex; align-items: baseline; gap: 8px; margin: 16px 8px 6px; font-weight: 700; }
  .divider small { color: var(--muted); font-weight: 500; }
  .empty { color: var(--muted); text-align: center; padding: 24px 0; }
</style>
