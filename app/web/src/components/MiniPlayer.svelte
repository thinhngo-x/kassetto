<script lang="ts">
  import Art from './Art.svelte'
  import Icon from './Icon.svelte'
  import { player } from '../lib/player.svelte'
  import { ui } from '../lib/ui.svelte'
  let p = $derived(player.duration ? Math.min(1, player.time / player.duration) : 0)
</script>

{#if player.current}
  {@const t = player.current}
  <div class="mini" role="button" tabindex="0" onclick={() => ui.openFull()} onkeydown={(e) => e.key === 'Enter' && ui.openFull()}>
    <div class="prog" style:transform="scaleX({p})"></div>
    <Art src={t.thumb} size={44} />
    <div class="meta">
      <div class="t ellipsis">{t.title}</div>
      <div class="s ellipsis">
        {#if player.nest}<span class="nest"><Icon name="speaker" size={12} /> {player.speakerName}</span> · {/if}{player.buffering && !player.nest ? 'Loading…' : t.artist}
      </div>
    </div>
    <button class="icon-btn" aria-label={player.playing ? 'Pause' : 'Play'} onclick={(e) => { e.stopPropagation(); player.toggle() }}>
      <Icon name={player.playing ? 'pause' : 'play'} size={24} />
    </button>
    <button class="icon-btn" aria-label="Next" onclick={(e) => { e.stopPropagation(); player.next() }}><Icon name="next" /></button>
  </div>
{/if}

<style>
  .mini {
    position: fixed; left: 8px; right: 8px; bottom: calc(var(--nav-h) + env(safe-area-inset-bottom) + 6px); z-index: 30;
    height: var(--mini-h); display: flex; align-items: center; gap: 10px; padding: 0 6px 0 10px; border-radius: 14px;
    background: color-mix(in srgb, var(--tint) 70%, var(--surface)); box-shadow: var(--shadow); overflow: hidden;
    transition: background .6s ease; cursor: pointer;
  }
  .prog { position: absolute; left: 10px; right: 10px; bottom: 0; height: 2px; background: var(--fg); transform-origin: left;
          transition: transform .25s linear; border-radius: 1px; opacity: .85; }
  .meta { flex: 1; min-width: 0; }
  .t { font-weight: 600; font-size: 14px; }
  .s { font-size: 12.5px; color: var(--fg-2); }
  .nest { color: var(--accent); display: inline-flex; gap: 3px; align-items: center; }
  .icon-btn { color: var(--fg); }
</style>
