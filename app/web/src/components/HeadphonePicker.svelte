<!-- Headphone correction (experimental): search AutoEq's ~8,800 measured headphones, pick yours (per device). -->
<script lang="ts">
  import Icon from './Icon.svelte'
  import { get } from '../lib/api'
  import { player, type EqProfile } from '../lib/player.svelte'
  import { ui } from '../lib/ui.svelte'

  interface Hit { id: string; name: string; by: string; kind: string }
  let q = $state('')
  let hits = $state<Hit[]>([])
  let total = $state(0)
  let busy = $state('')
  let timer = 0

  function search() {
    clearTimeout(timer)
    const v = q.trim()
    if (!v) { hits = []; return }
    timer = window.setTimeout(() => get<{ total: number; items: Hit[] }>(`/api/eq/search?q=${encodeURIComponent(v)}`, 3600_000)
      .then((r) => { if (q.trim() === v) { hits = r.items; total = r.total } }).catch(() => {}), 200)
  }
  async function pick(h: Hit) {
    busy = h.id
    try {
      const p = await get<EqProfile>(`/api/eq/profile?id=${encodeURIComponent(h.id)}`, 24 * 3600_000)
      player.setEq(p); q = ''; hits = []
      ui.say(`Correction for ${p.name} on`)
    } catch { ui.say("Couldn't load that profile, try another measurement") }
    busy = ''
  }
  const gainSum = (p: EqProfile) => p.filters.map((f) => `${f.gain > 0 ? '+' : ''}${f.gain.toFixed(1)} dB @ ${f.f >= 1000 ? (f.f / 1000).toFixed(1) + 'k' : Math.round(f.f)}`).slice(0, 4).join(', ')
</script>

<div class="hp">
  {#if player.eq}
    <div class="cur">
      <Icon name="taste" size={16} />
      <span class="ellipsis"><b>{player.eq.name}</b><small>{player.eq.by} · {player.eq.filters.length} filters, preamp {player.eq.preamp} dB · {gainSum(player.eq)}…</small></span>
      <button class="icon-btn" aria-label="Remove headphones" onclick={() => player.setEq(null)}><Icon name="close" size={16} /></button>
    </div>
  {/if}
  <input type="search" bind:value={q} oninput={search} placeholder={player.eq ? 'Choose other headphones…' : 'Search your headphones, e.g. “WH-1000XM4”'}
         autocomplete="off" aria-label="Search headphones" />
  {#if hits.length}
    <div class="list">
      {#each hits as h (h.id)}
        <button onclick={() => pick(h)} disabled={!!busy}>
          <span class="ellipsis"><b>{h.name}</b><small>{h.kind ? h.kind + ' · ' : ''}measured by {h.by}</small></span>
          {#if busy === h.id}<span class="spin"></span>{/if}
        </button>
      {/each}
    </div>
  {:else if q.trim() && total}
    <p class="muted">No match among {total.toLocaleString()} headphones. Try just the model (e.g. “XM4”).</p>
  {/if}
  <p class="note">Same model, several entries = different measurement labs; any of them is fine. Phone / browser only (the Nest plays the file as is). Takes effect from your next tap on play.</p>
</div>

<style>
  .hp { padding: 4px 16px 14px; background: var(--surface); border-radius: 0 0 14px 14px; margin-top: -10px; }
  .cur { display: flex; align-items: center; gap: 10px; padding: 8px 0; color: var(--accent); }
  .cur span, .list span { display: flex; flex-direction: column; min-width: 0; flex: 1; color: var(--fg); }
  small { color: var(--muted); font-size: 12px; }
  input { width: 100%; height: 40px; border: 0; border-radius: 10px; padding: 0 12px; background: var(--surface-2); color: var(--fg); font-size: 15px; }
  .list { margin-top: 6px; max-height: 300px; overflow-y: auto; }
  .list button { width: 100%; display: flex; align-items: center; gap: 10px; padding: 8px 6px; border-radius: 8px; text-align: left; }
  .list button:hover { background: var(--surface-2); }
  .note { color: var(--muted); font-size: 12px; margin: 10px 0 0; line-height: 1.5; }
  .spin { width: 16px; height: 16px; border: 2px solid var(--muted); border-top-color: var(--accent); border-radius: 50%; animation: r .8s linear infinite; }
  @keyframes r { to { transform: rotate(360deg); } }
</style>
