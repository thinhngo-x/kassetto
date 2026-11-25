<!-- Desktop player bar (≥960 px): track | transport + seek | autoplay, Nest, queue, volume. -->
<script lang="ts">
  import SleepButton from './SleepButton.svelte'
  import Art from './Art.svelte'
  import Icon from './Icon.svelte'
  import Seek from './Seek.svelte'
  import { player } from '../lib/player.svelte'
  import { ui } from '../lib/ui.svelte'
  let liked = $derived(player.current ? player.prefs[player.current.videoId] === 1 : false)
  let lastVol = 1
</script>

<div class="bar">
  <div class="left">
    {#if player.current}
      {@const t = player.current}
      <Art src={t.thumb} size={56} />
      <div class="meta">
        <div class="t ellipsis">{t.title}</div>
        <div class="s ellipsis">{#if player.nest}<span class="nest">Nest Mini · </span>{/if}{t.artist}</div>
      </div>
      <button class="icon-btn" class:on={liked} class:heart={liked} aria-label={liked ? 'Remove from liked songs' : 'Add to liked songs'} onclick={() => player.like(t)}><Icon name={liked ? 'liked' : 'like'} size={19} /></button>
    {/if}
  </div>
  <div class="center">
    <div class="transport">
      <button class="icon-btn" aria-label="Shuffle up next" onclick={() => player.shuffleRest()}><Icon name="shuffle" size={18} /></button>
      <button class="icon-btn" aria-label="Previous" disabled={player.nest} onclick={() => player.prev()}><Icon name="prev" size={19} /></button>
      <button class="play" aria-label={player.playing ? 'Pause' : 'Play'} disabled={!player.current} onclick={() => player.toggle()}>
        {#if player.buffering && !player.nest}<span class="spin"></span>{/if}
        <Icon name={player.playing ? 'pause' : 'play'} size={19} />
      </button>
      <button class="icon-btn" aria-label="Next" onclick={() => player.next()}><Icon name="next" size={19} /></button>
      <button class="icon-btn" class:on={player.autoplay} aria-label="Autoplay" title="Autoplay" onclick={() => player.setAutoplay(!player.autoplay)}><Icon name="autoplay" size={19} /></button>
    </div>
    <Seek />
  </div>
  <div class="right">
    {#if player.canCast}<button class="icon-btn" class:on={player.nest} title={player.nest ? 'Back to this device' : 'Play on Nest Mini'}
            aria-label={player.nest ? 'Back to this device' : 'Play on Nest'} onclick={() => (player.nest ? player.toPhone() : player.toNest())}>
      <Icon name="speaker" size={19} /></button>{/if}
    <SleepButton />
    <button class="icon-btn" class:on={ui.panel === 'lyrics'} aria-label="Lyrics" title="Lyrics" onclick={() => (ui.panel = ui.panel === 'lyrics' ? null : 'lyrics')}><Icon name="lyrics" size={19} /></button>
    <button class="icon-btn" class:on={ui.panel === 'queue'} aria-label="Queue" title="Queue" onclick={() => (ui.panel = ui.panel === 'queue' ? null : 'queue')}><Icon name="queue" size={19} /></button>
    <button class="icon-btn" aria-label={player.volume ? 'Mute' : 'Unmute'}
            onclick={() => { if (player.volume) { lastVol = player.volume; player.setVolume(0) } else player.setVolume(lastVol || 1) }}>
      <Icon name={player.volume ? 'volume' : 'mute'} size={19} /></button>
    <input class="vol" type="range" min="0" max="1" step="0.01" value={player.volume} aria-label="Volume"
           style:--v={player.volume} oninput={(e) => player.setVolume(+(e.currentTarget as HTMLInputElement).value)} />
  </div>
</div>

<style>
  .bar { position: fixed; left: 0; right: 0; bottom: 0; z-index: 40; height: var(--bar-h); display: grid;
         grid-template-columns: minmax(200px, 1fr) minmax(360px, 560px) minmax(200px, 1fr); align-items: center; gap: 16px;
         padding: 0 16px; background: color-mix(in srgb, var(--tint-soft) 60%, var(--bg-2)); border-top: 1px solid var(--line);
         transition: background .8s; }
  .left, .right { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .right { justify-content: flex-end; }
  .meta { min-width: 0; flex: 0 1 auto; }
  .t { font-weight: 600; font-size: 14px; }
  .s { font-size: 12.5px; color: var(--muted); }
  .nest { color: var(--accent); }
  .center { display: flex; flex-direction: column; align-items: center; gap: 2px; }
  .transport { display: flex; align-items: center; gap: 8px; }
  .play { position: relative; width: 36px; height: 36px; border-radius: 50%; background: var(--fg); color: var(--bg);
          display: grid; place-items: center; transition: transform .12s var(--ease); }
  .play:active { transform: scale(.92); }
  .play:disabled, .icon-btn:disabled { opacity: .35; }
  .spin { position: absolute; inset: -3px; border-radius: 50%; border: 2px solid transparent; border-top-color: var(--accent); animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .vol { width: 110px; height: 4px; appearance: none; border-radius: 2px; cursor: pointer;
         background: linear-gradient(to right, var(--fg) calc(var(--v) * 100%), color-mix(in srgb, var(--fg) 20%, transparent) 0); }
  .vol::-webkit-slider-thumb { appearance: none; width: 12px; height: 12px; border-radius: 50%; background: var(--fg); }
  .vol::-moz-range-thumb { width: 12px; height: 12px; border: 0; border-radius: 50%; background: var(--fg); }
</style>
