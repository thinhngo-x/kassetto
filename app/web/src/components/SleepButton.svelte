<!-- Sleep timer: a moon button with a small menu (15 / 30 / 45 / 60 min, end of song, off); shows the time left. -->
<script lang="ts">
  import Icon from './Icon.svelte'
  import { player } from '../lib/player.svelte'

  let { size = 19, chip = false }: { size?: number; chip?: boolean } = $props()
  let open = $state(false)
  let left = $derived.by(() => { void player.time; return player.sleepAt ? Math.max(0, Math.ceil((player.sleepAt - Date.now()) / 60_000)) : 0 })
  let on = $derived(!!player.sleepAt || player.sleepEnd)
  const pick = (m: number | 'end') => { player.setSleep(m); open = false }
</script>

<div class="wrap">
  {#if chip}
    <button class="chip" class:on onclick={() => (open = !open)}><Icon name="moon" size={15} /> {on ? (player.sleepEnd ? 'After this song' : `${left} min`) : 'Sleep timer'}</button>
  {:else}
    <button class="icon-btn" class:on aria-label="Sleep timer" title={on ? (player.sleepEnd ? 'Sleep: after this song' : `Sleep in ${left} min`) : 'Sleep timer'}
            onclick={() => (open = !open)}><Icon name="moon" {size} />{#if on && !player.sleepEnd}<small>{left}</small>{/if}</button>
  {/if}
  {#if open}
    <div class="backdrop" role="presentation" onclick={() => (open = false)}></div>
    <div class="pop" role="menu">
      {#each [15, 30, 45, 60, 90] as m}<button role="menuitem" onclick={() => pick(m)}>{m} minutes</button>{/each}
      <button role="menuitem" onclick={() => pick('end')}>End of this song</button>
      {#if on}<button role="menuitem" class="off" onclick={() => pick(0)}>Turn off</button>{/if}
    </div>
  {/if}
</div>

<style>
  .wrap { position: relative; display: inline-flex; }
  .icon-btn small { font-size: 10px; font-weight: 700; margin-left: 1px; }
  .backdrop { position: fixed; inset: 0; z-index: 90; }
  .pop { position: absolute; z-index: 91; bottom: calc(100% + 8px); left: 50%; transform: translateX(-50%); min-width: 180px;
         background: var(--surface-2); border-radius: 12px; padding: 6px; box-shadow: var(--shadow); display: flex; flex-direction: column; }
  .pop button { padding: 10px 12px; border-radius: 8px; text-align: left; color: var(--fg); white-space: nowrap; }
  .pop button:hover { background: color-mix(in srgb, var(--fg) 8%, transparent); }
  .off { color: var(--accent) !important; }
</style>
