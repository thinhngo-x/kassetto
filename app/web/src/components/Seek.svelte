<!-- Seek bar: pointer-driven (no re-render storm while dragging), GPU-only fill (transform), keyboard accessible. -->
<script lang="ts">
  import { player } from '../lib/player.svelte'
  let { compact = false }: { compact?: boolean } = $props()

  let dragging = $state(false), dragP = $state(0)
  let el: HTMLDivElement
  let p = $derived(dragging ? dragP : player.duration ? Math.min(1, player.time / player.duration) : 0)
  const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

  function pos(e: PointerEvent) {
    const r = el.getBoundingClientRect()
    return Math.min(1, Math.max(0, (e.clientX - r.left) / r.width))
  }
  function down(e: PointerEvent) { dragging = true; dragP = pos(e); el.setPointerCapture(e.pointerId) }
  function move(e: PointerEvent) { if (dragging) dragP = pos(e) }
  function up() { if (!dragging) return; dragging = false; player.seek(dragP * player.duration) }
  function key(e: KeyboardEvent) {
    if (e.key === 'ArrowRight') player.seek(Math.min(player.duration, player.time + 5))
    else if (e.key === 'ArrowLeft') player.seek(Math.max(0, player.time - 5))
    else return
    e.preventDefault()
  }
</script>

<div class="seek" class:compact>
  {#if !compact}<span class="time">{fmt(p * player.duration)}</span>{/if}
  <div class="track" bind:this={el} role="slider" tabindex="0" aria-label="Seek" aria-valuemin={0}
       aria-valuemax={Math.round(player.duration)} aria-valuenow={Math.round(p * player.duration)}
       onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up} onkeydown={key}>
    <div class="rail"><div class="fill" class:anim={!dragging} style:transform="scaleX({p})"></div></div>
    <div class="knob" class:show={dragging} style:left="{p * 100}%"></div>
  </div>
  {#if !compact}<span class="time">{fmt(player.duration)}</span>{/if}
</div>

<style>
  .seek { display: flex; align-items: center; gap: 10px; width: 100%; }
  .time { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; min-width: 36px; text-align: center; }
  .track { position: relative; flex: 1; height: 24px; display: flex; align-items: center; cursor: pointer; touch-action: none; }
  .rail { width: 100%; height: 4px; border-radius: 2px; background: color-mix(in srgb, var(--fg) 18%, transparent); overflow: hidden; }
  .fill { height: 100%; width: 100%; background: var(--fg); transform-origin: left; will-change: transform; }
  .fill.anim { transition: transform .25s linear; }
  .track:hover .fill { background: var(--accent); }
  .knob { position: absolute; width: 14px; height: 14px; margin-left: -7px; border-radius: 50%; background: var(--fg);
          box-shadow: 0 2px 6px rgb(0 0 0 / .4); transform: scale(0); transition: transform .12s var(--ease); }
  .track:hover .knob, .knob.show { transform: scale(1); }
  .compact .track { height: 14px; }
  .compact .rail { height: 3px; }
</style>
