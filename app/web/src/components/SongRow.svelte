<script lang="ts">
  import Art from './Art.svelte'
  import Icon from './Icon.svelte'
  import { player } from '../lib/player.svelte'
  import { ui, type PlaylistCtx } from '../lib/ui.svelte'
  import type { Song } from '../lib/types'
  import { whyIcon } from '../lib/why'
  import { resolveSoon } from '../lib/api'

  let { song, num = null, queueIndex, onplay, showWhy = false, playlist }:
    { song: Song; num?: number | null; queueIndex?: number; onplay: () => void; showWhy?: boolean; playlist?: PlaylistCtx } = $props()

  let active = $derived(player.current?.videoId === song.videoId)
  let hover = 0
  /** Mouse resting on a row = a likely tap: look it up ahead (touch scrolling must not trigger this). */
  function onEnter(e: PointerEvent) { if (e.pointerType === 'mouse') hover = window.setTimeout(() => resolveSoon([song.videoId]), 300) }
  const dur = (s?: number | null) => (s ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}` : '')
</script>

<div class="row" class:active role="button" tabindex="0" onpointerenter={onEnter} onpointerleave={() => clearTimeout(hover)}
     onclick={onplay} onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onplay())}>
  <div class="lead">
    {#if num !== null}<span class="num">{num}</span>{:else}<Art src={song.thumb} size={48} />{/if}
    {#if active}
      <span class="eq" class:paused={!player.playing} aria-label="Now playing"><i></i><i></i><i></i></span>
    {/if}
  </div>
  <div class="meta">
    <div class="t ellipsis">{song.title}</div>
    <div class="s ellipsis">
      {#if showWhy && song.why}<span class="why" title={song.because ?? 'Picked: ' + song.why}><Icon name={whyIcon(song.why)} size={13} label={song.because ?? 'Picked: ' + song.why} /></span>{/if}{song.artist}{song.album ? ` · ${song.album}` : ''}
    </div>
  </div>
  <span class="dur">{dur(song.duration)}</span>
  <button class="icon-btn more" aria-label="More options"
          onclick={(e) => { e.stopPropagation(); ui.openMenu({ song, queueIndex, playlist }) }}><Icon name="more" size={18} /></button>
</div>

<style>
  .row {
    display: flex; align-items: center; gap: 12px; min-height: 60px; padding: 6px 4px 6px 8px; border-radius: 10px;
    cursor: pointer; content-visibility: auto; contain-intrinsic-size: auto 60px; transition: background .12s;
  }
  .row:hover { background: color-mix(in srgb, var(--fg) 5%, transparent); }
  .row:active { background: color-mix(in srgb, var(--fg) 8%, transparent); }
  .lead { position: relative; flex: none; }
  .num { width: 48px; display: inline-block; text-align: center; color: var(--muted); font-variant-numeric: tabular-nums; }
  .meta { flex: 1; min-width: 0; }
  .t { font-weight: 560; }
  .active .t { color: var(--accent); }
  .s { color: var(--muted); font-size: 13px; margin-top: 2px; }
  .why { display: inline-flex; vertical-align: -2px; margin-right: 5px; color: var(--accent); }
  .dur { color: var(--muted); font-size: 13px; font-variant-numeric: tabular-nums; }
  .more { opacity: .7; }
  .eq { position: absolute; inset: 0; display: flex; align-items: flex-end; justify-content: center; gap: 3px;
        padding-bottom: 14px; background: rgb(0 0 0 / .45); border-radius: 6px; }
  .num + .eq { background: var(--bg); }
  .eq i { width: 3px; height: 16px; background: var(--accent); border-radius: 2px; transform-origin: bottom;
          animation: eq 0.9s ease-in-out infinite; }
  .eq i:nth-child(2) { animation-delay: -.3s; } .eq i:nth-child(3) { animation-delay: -.6s; }
  .eq.paused i { animation-play-state: paused; }
  @keyframes eq { 0%, 100% { transform: scaleY(.3); } 50% { transform: scaleY(1); } }
  @media (max-width: 520px) { .dur { display: none; } }
</style>
