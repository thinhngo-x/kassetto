<!-- Full-screen player sheet (mobile): artwork-tinted background, swipe down to close, queue below. -->
<script lang="ts">
  import SleepButton from './SleepButton.svelte'
  import Art from './Art.svelte'
  import Icon from './Icon.svelte'
  import Lyrics from './Lyrics.svelte'
  import QueueList from './QueueList.svelte'
  import Seek from './Seek.svelte'
  import { player } from '../lib/player.svelte'
  import { ui } from '../lib/ui.svelte'

  let dy = $state(0), startY = 0, dragging = $state(false)
  let sheet: HTMLDivElement
  function down(e: PointerEvent) {
    if (sheet.scrollTop > 0 || (e.target as HTMLElement).closest('button')) return
    dragging = true; startY = e.clientY; dy = 0
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }
  function move(e: PointerEvent) { if (dragging) dy = Math.max(0, e.clientY - startY) }
  function up() { if (!dragging) return; dragging = false; if (dy > 110) ui.closeFull(); dy = 0 }
  /** Cycle headphones -> phone speaker -> off; the toast names the mode you switched TO (decided once, here). */
  function switchSound() {
    const to = ({ headphones: 'speaker', speaker: 'off', off: 'headphones' } as const)[player.output]
    player.setOutput(to)
    ui.say(to === 'headphones' ? `Sound: headphones${player.eq ? ` (${player.eq.name})` : ''}` : to === 'speaker' ? 'Sound: phone speaker' : 'Sound profile: off')
  }
  let liked = $derived(player.current ? player.prefs[player.current.videoId] === 1 : false)
</script>

<div class="sheet" class:open={ui.full} class:dragging bind:this={sheet} style:--dy="{dy}px" aria-hidden={!ui.full}>
  {#if player.current}
    {@const t = player.current}
    <div class="bg"></div>
    <div class="grab" role="presentation" onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up}>
    <header>
      <button class="icon-btn" aria-label="Close player" onclick={() => ui.closeFull()}><Icon name="down" size={24} /></button>
      <span class="where">{#if player.nest}<Icon name="speaker" size={14} /> Playing on {player.speakerName}{:else}Now playing
        {#if player.eqOn}
          <button class="snd" class:off={player.output === 'off'} onclick={switchSound}
                  aria-label="Sound profile: {player.output} (tap to switch)" title="Sound profile (tap to switch)">
            <Icon name={player.output === 'headphones' ? 'headphones' : player.output === 'speaker' ? 'phone' : 'taste'} size={14} /></button>
        {/if}{/if}</span>
      <button class="icon-btn" aria-label="More options" onclick={() => ui.openMenu({ song: t, queueIndex: player.idx })}><Icon name="more" /></button>
    </header>
    <div class="art" class:paused={!player.playing}>
      <Art src={t.thumb} size={520} eager />
    </div>
    </div>
    <div class="info">
      <div class="meta">
        <h1 class="ellipsis">{t.title}</h1>
        <p class="ellipsis">{t.artist}{t.album ? ` · ${t.album}` : ''}</p>
      </div>
      <button class="icon-btn" class:on={liked} class:heart={liked} aria-label={liked ? 'Remove from liked songs' : 'Add to liked songs'} onclick={() => player.like(t)}><Icon name={liked ? 'liked' : 'like'} size={24} /></button>
    </div>
    <Seek />
    <div class="ctl">
      <button class="icon-btn" class:on={player.autoplay} aria-label="Autoplay" onclick={() => player.setAutoplay(!player.autoplay)}><Icon name="autoplay" /></button>
      <button class="icon-btn big2" aria-label="Previous" disabled={player.nest} onclick={() => player.prev()}><Icon name="prev" size={28} /></button>
      <button class="playbtn" aria-label={player.playing ? 'Pause' : 'Play'} onclick={() => player.toggle()}>
        {#if player.buffering && !player.nest}<span class="spin"></span>{/if}
        <Icon name={player.playing ? 'pause' : 'play'} size={28} />
      </button>
      <button class="icon-btn big2" aria-label="Next" onclick={() => player.next()}><Icon name="next" size={28} /></button>
      <button class="icon-btn" class:on={player.nest} aria-label={player.nest ? 'Back to phone' : `Play on ${player.speakerName}`}
              style:visibility={player.canCast ? 'visible' : 'hidden'} disabled={!player.canCast}
              onclick={() => (player.nest ? player.toPhone() : player.toNest())}><Icon name={player.nest ? 'phone' : 'speaker'} /></button>
    </div>
    <div class="row2">
      <button class="chip" onclick={() => player.shuffleRest()}><Icon name="shuffle" size={15} /> Shuffle up next</button>
      <SleepButton chip />
    </div>
    <div class="tabs" role="tablist">
      <button role="tab" aria-selected={ui.sheetTab === 'next'} class:on={ui.sheetTab === 'next'} onclick={() => (ui.sheetTab = 'next')}>Up next</button>
      <button role="tab" aria-selected={ui.sheetTab === 'lyrics'} class:on={ui.sheetTab === 'lyrics'} onclick={() => (ui.sheetTab = 'lyrics')}>Lyrics</button>
    </div>
    {#if ui.sheetTab === 'lyrics'}<div class="lyr"><Lyrics height="62vh" /></div>{:else}<QueueList />{/if}
  {/if}
</div>

<style>
  .sheet {
    position: fixed; inset: 0; z-index: 50; overflow-y: auto; overscroll-behavior: contain; padding: 0 20px 40px;
    background: var(--bg); transform: translate3d(0, 100%, 0); transition: transform .36s var(--ease); will-change: transform;
    visibility: hidden;
  }
  .sheet.open { transform: translate3d(0, var(--dy), 0); visibility: visible; }
  .sheet.dragging { transition: none; }
  .bg { position: absolute; inset: 0 0 auto 0; height: 100vh; z-index: -1; pointer-events: none;
        background: radial-gradient(120% 70% at 50% 0%, var(--tint) 0%, var(--tint-soft) 55%, var(--bg) 100%); transition: background .8s; }
  .grab { touch-action: none; }
  header { display: flex; align-items: center; justify-content: space-between; padding-top: calc(env(safe-area-inset-top) + 8px);
           max-width: 560px; margin: 0 auto; }
  .where { font-size: 12.5px; color: var(--fg-2); font-weight: 600; display: inline-flex; gap: 6px; align-items: center; letter-spacing: .02em; }
  .art { width: min(86vw, 420px, 52vh); margin: 18px auto 22px; aspect-ratio: 1; transition: transform .4s var(--ease); }
  .art :global(.art) { width: 100% !important; height: 100% !important; border-radius: 14px; box-shadow: 0 24px 60px rgb(0 0 0 / .5); }
  .art.paused { transform: scale(.92); }
  .info, .sheet > :global(.seek), .ctl, .row2, .sheet > :global(.row), .sheet > :global(.divider), .sheet > :global(.empty) {
    max-width: 560px; margin-left: auto; margin-right: auto; }
  .info { display: flex; align-items: center; gap: 4px; }
  .meta { flex: 1; min-width: 0; }
  h1 { font-size: 22px; font-weight: 750; }
  .info p { margin: 4px 0 6px; color: var(--fg-2); }
  .ctl { display: flex; align-items: center; justify-content: space-between; margin-top: 6px; }
  .big2 { width: 48px; height: 48px; color: var(--fg); }
  .big2:disabled { opacity: .35; }
  .playbtn { position: relative; width: 62px; height: 62px; border-radius: 50%; display: grid; place-items: center;
             background: var(--fg); color: var(--bg); transition: transform .12s var(--ease); }
  .playbtn:active { transform: scale(.93); }
  .spin { position: absolute; inset: -4px; border-radius: 50%; border: 3px solid transparent; border-top-color: var(--accent);
          animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .snd { display: inline-grid; place-items: center; width: 26px; height: 26px; margin: -6px 0 -6px 2px; border-radius: 50%;
         color: var(--accent); background: color-mix(in srgb, var(--fg) 8%, transparent); }
  .snd.off { color: var(--muted); background: none; }
  .row2 { display: flex; justify-content: center; gap: 8px; margin: 14px auto 4px; }
  .row2 .chip { display: inline-flex; align-items: center; gap: 6px; }
  .tabs { display: flex; gap: 6px; max-width: 560px; margin: 22px auto 6px; padding: 4px; border-radius: 12px;
          background: color-mix(in srgb, var(--fg) 7%, transparent); }
  .tabs button { flex: 1; height: 36px; border-radius: 9px; font-weight: 650; color: var(--fg-2); transition: background .15s, color .15s; }
  .tabs button.on { background: color-mix(in srgb, var(--fg) 14%, transparent); color: var(--fg); }
  .lyr { max-width: 560px; margin: 0 auto; }
</style>
