<!-- Wake-up alarms on the Nest: when (a time, or after the morning briefing), which days, what (Your mix / liked
     songs / a playlist), how loud, fade-in and when to stop. Shared by the speaker's circle. -->
<!-- Morning routines (optional external routines service): at a time, on chosen days, the spoken briefing and/or
     music on the Nest. Shared by the speaker's circle. Hidden when the routines service isn't set up. -->
<script lang="ts">
  import Icon from './Icon.svelte'
  import { get, post } from '../lib/api'
  import { ui } from '../lib/ui.svelte'

  interface Src { kind: 'mix' | 'liked' | 'playlist'; id?: string; name?: string }
  interface Music { on: boolean; source: Src; by: string; volume: number; fade: number; minutes: number }
  interface Routine { id: string; label: string; on: boolean; days: number[]; time: string; briefing: { on: boolean; voice: string }; music: Music }
  interface Last { started?: number; finished?: number; result?: string; reason?: string }
  interface R { available: boolean; error?: string; routines: Routine[]; last: Record<string, Last>; voices: string[]; running: string[]
    allowed: boolean; circle: string | null; people: Record<string, string> }
  interface Pl { id: string; name: string }

  let w = $state<R | null>(null)
  let pls = $state<Pl[]>([])
  let open = $state<string | null>(null)
  const load = () => get<R>('/api/routines', 0).then((v) => (w = v)).catch(() => {})
  $effect(() => { load(); get<Pl[]>('/api/myplaylists', 0).then((v) => (pls = v)).catch(() => {}) })
  const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
  const VOICE: Record<string, string> = { 'nu-luu-loat': 'Female, fluent', 'nu-calm': 'Female, calm', 'nu-nhe-nhang': 'Female, gentle',
    'nu-nhan-nha': 'Female, leisurely', 'nu-cham': 'Female, slow', 'nam-calm': 'Male, calm', 'nam-truyen-cam': 'Male, expressive',
    'nam-nhanh': 'Male, fast', 'nam-cham': 'Male, slow' }
  let timer = 0
  function save() {                                       // debounced: sliders send many changes
    clearTimeout(timer)
    timer = window.setTimeout(async () => {
      try {
        const r = await fetch('/api/routines', { method: 'PUT', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ routines: $state.snapshot(w!.routines) }) })
        if (!r.ok) throw new Error(await r.text())
        w = await r.json()
      } catch (e) { ui.say("Couldn't save: " + (e as Error).message.slice(0, 80)) }
    }, 400)
  }
  function add() {
    const id = 'r' + Date.now() % 1e9
    const by = Object.keys(w!.people)[0] ?? ''
    w!.routines.push({ id, label: '', on: true, days: [0, 1, 2, 3, 4], time: '07:30', briefing: { on: true, voice: 'nu-luu-loat' },
      music: { on: true, source: { kind: 'mix' }, by, volume: 0.25, fade: 60, minutes: 30 } })
    open = id; save()
  }
  async function runNow(r: Routine) {
    try { await post(`/api/routines/${r.id}/run`); ui.say(r.briefing.on ? 'Starting: the briefing takes ~30 s to prepare' : 'Starting on the Nest…') }
    catch { ui.say("Couldn't start it") }
    setTimeout(load, 4000)
  }
  const days = (d: number[]) => d.length === 7 ? 'every day' : d.join() === '0,1,2,3,4' ? 'weekdays' : d.join() === '5,6' ? 'weekends'
    : d.length ? d.map((i) => DAYS[i]).join(' ') : 'no days'
  const what = (s: Src) => s.kind === 'mix' ? 'Your mix' : s.kind === 'liked' ? 'Liked songs' : s.name || 'a playlist'
  const steps = (r: Routine) => [r.briefing.on && 'briefing', r.music.on && what(r.music.source)].filter(Boolean).join(' + ') || 'nothing'
  const srcVal = (s: Src) => s.kind === 'playlist' ? 'pl:' + s.id : s.kind
  function setSrc(m: Music, v: string) {
    m.source = v.startsWith('pl:') ? { kind: 'playlist', id: v.slice(3), name: pls.find((p) => p.id === v.slice(3))?.name } : { kind: v as 'mix' | 'liked' }
    save()
  }
  const ago = (t?: number) => t ? new Date(t * 1000).toLocaleString(undefined, { weekday: 'short', hour: '2-digit', minute: '2-digit' }) : ''
</script>

{#if w?.available && w.allowed}
  <div class="head"><b>Morning routines</b> <small class="muted">the briefing and music on the Nest Mini{w.circle ? ` · shared by ${w.circle}` : ''}</small>
    <button class="more" onclick={add}><Icon name="plus" size={16} /> Add</button></div>
  {#each w.routines as r (r.id)}
    {@const last = w.last[r.id]}
    <div class="alarm" class:off={!r.on}>
      <button class="sum" onclick={() => (open = open === r.id ? null : r.id)} aria-expanded={open === r.id}>
        <span class="t">{r.time}{#if r.label}<small> {r.label}</small>{/if}</span>
        <span class="d ellipsis">{days(r.days)} · {steps(r)}</span>
      </button>
      <input type="checkbox" checked={r.on} aria-label="Routine on" onchange={(e) => { r.on = (e.currentTarget as HTMLInputElement).checked; save() }} />
    </div>
    {#if open === r.id}
      <div class="edit">
        <label>Time <input type="time" value={r.time} onchange={(e) => { r.time = (e.currentTarget as HTMLInputElement).value || r.time; save() }} /></label>
        <label>Name <input class="txt" value={r.label} placeholder="optional" onchange={(e) => { r.label = (e.currentTarget as HTMLInputElement).value; save() }} /></label>
        <div class="days">{#each DAYS as d, i}<button class="chip" class:on={r.days.includes(i)}
          onclick={() => { r.days = r.days.includes(i) ? r.days.filter((x) => x !== i) : [...r.days, i].sort(); save() }}>{d}</button>{/each}</div>

        <div class="step"><label class="sw"><input type="checkbox" checked={r.briefing.on} onchange={(e) => { r.briefing.on = (e.currentTarget as HTMLInputElement).checked; save() }} />
          <b>1. Briefing</b> <small class="muted">good morning, the date and the weather</small></label>
          {#if r.briefing.on}
            <label>Voice <select value={r.briefing.voice} onchange={(e) => { r.briefing.voice = (e.currentTarget as HTMLSelectElement).value; save() }}>
              {#each w.voices as v}<option value={v}>{VOICE[v] ?? v}</option>{/each}</select></label>
          {/if}
        </div>

        <div class="step"><label class="sw"><input type="checkbox" checked={r.music.on} onchange={(e) => { r.music.on = (e.currentTarget as HTMLInputElement).checked; save() }} />
          <b>{r.briefing.on ? '2. Then music' : 'Music'}</b></label>
          {#if r.music.on}
            {@const m = r.music}
            <label>Play
              <select value={srcVal(m.source)} onchange={(e) => setSrc(m, (e.currentTarget as HTMLSelectElement).value)}>
                <option value="mix">Your mix (fresh each time)</option>
                <option value="liked">Liked songs, shuffled</option>
                {#each pls as p}<option value={'pl:' + p.id}>{p.name}</option>{/each}
                {#if m.source.kind === 'playlist' && !pls.some((p) => p.id === m.source.id)}<option value={'pl:' + m.source.id}>{m.source.name || 'Playlist'}</option>{/if}
              </select></label>
            {#if Object.keys(w.people).length > 1}
              <label>Whose music
                <select value={m.by} onchange={(e) => { m.by = (e.currentTarget as HTMLSelectElement).value; save() }}>
                  {#each Object.entries(w.people) as [u, n]}<option value={u}>{n}</option>{/each}
                </select></label>
            {/if}
            <label>Volume <input type="range" min="0.05" max="0.8" step="0.05" value={m.volume}
              oninput={(e) => { m.volume = +(e.currentTarget as HTMLInputElement).value; save() }} /> {Math.round(m.volume * 100)}%</label>
            <label>Fade in
              <select value={m.fade} onchange={(e) => { m.fade = +(e.currentTarget as HTMLSelectElement).value; save() }}>
                {#each [[0, 'No'], [30, '30 s'], [60, '1 min'], [120, '2 min'], [300, '5 min'], [600, '10 min']] as [v, l]}<option value={v}>{l}</option>{/each}
              </select></label>
            <label>Stop after
              <select value={m.minutes} onchange={(e) => { m.minutes = +(e.currentTarget as HTMLSelectElement).value; save() }}>
                {#each [10, 15, 20, 30, 45, 60, 90, 120] as n}<option value={n}>{n} min</option>{/each}
              </select></label>
          {/if}
        </div>
        {#if last?.result}<small class="muted last">Last run {ago(last.started)}: {last.result}</small>{/if}
        <div class="acts">
          <button class="pill ghost" disabled={w.running.includes(r.id)} onclick={() => runNow(r)}><Icon name="play" size={16} /> {w.running.includes(r.id) ? 'Running…' : 'Run now'}</button>
          <button class="icon-btn" aria-label="Delete routine" onclick={() => { w!.routines = w!.routines.filter((x) => x.id !== r.id); open = null; save() }}><Icon name="trash" size={18} /></button>
        </div>
      </div>
    {/if}
  {:else}
    <p class="muted empty">No routines. <b>Add</b> one to wake up to the briefing and music.</p>
  {/each}
{:else if w && !w.available && w.error}
  <p class="muted empty">Morning routines: {w.error}.</p>
{/if}

<style>
  .head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; margin: 16px 0 8px; }
  .more { margin-left: auto; display: inline-flex; align-items: center; gap: 4px; color: var(--muted); font-weight: 600; font-size: 14px; }
  .alarm { display: flex; align-items: center; gap: 12px; padding: 10px 16px; background: var(--surface); border-radius: 14px; margin-top: 8px; }
  .alarm.off .t { color: var(--muted); }
  .sum { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: flex-start; text-align: left; }
  .t { font-size: 24px; font-weight: 800; font-variant-numeric: tabular-nums; }
  .d { color: var(--muted); font-size: 13px; max-width: 100%; }
  .alarm input { width: 22px; height: 22px; accent-color: var(--accent); }
  .edit { display: flex; flex-wrap: wrap; align-items: center; gap: 12px 18px; padding: 12px 16px; background: var(--surface);
          border-radius: 0 0 14px 14px; margin-top: -8px; color: var(--fg-2); font-size: 14px; }
  .days { display: flex; gap: 6px; flex-wrap: wrap; flex-basis: 100%; }
  .seg { display: inline-flex; background: var(--surface-2); border-radius: 10px; padding: 3px; flex-wrap: wrap; }
  .seg button { padding: 6px 12px; border-radius: 8px; font-size: 13px; font-weight: 650; color: var(--muted); }
  .seg button.on { background: var(--accent); color: var(--accent-fg); }
  select, input[type=time] { background: var(--surface-2); color: var(--fg); border: 0; border-radius: 8px; padding: 4px 8px; font: inherit; margin-left: 6px; color-scheme: dark; }
  input[type=range] { accent-color: var(--accent); vertical-align: middle; width: 120px; }
  .acts { display: flex; align-items: center; gap: 8px; flex-basis: 100%; justify-content: space-between; }
  .empty { margin: 4px 0; }
  .t small { font-size: 14px; font-weight: 600; color: var(--muted); }
  .txt { background: var(--surface-2); color: var(--fg); border: 0; border-radius: 8px; padding: 4px 8px; font: inherit; margin-left: 6px; width: 150px; }
  .step { flex-basis: 100%; display: flex; flex-wrap: wrap; align-items: center; gap: 10px 18px; padding-top: 10px; border-top: 1px solid var(--surface-2); }
  .sw { flex-basis: 100%; display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
  .sw input { accent-color: var(--accent); width: 18px; height: 18px; align-self: center; }
  .last { flex-basis: 100%; }
</style>
