<!-- Owner only: people (names, ListenBrainz "scrobble as") and circles (members, taste blend, speaker, concerts). -->
<script lang="ts">
  import Icon from './Icon.svelte'
  import { get } from '../lib/api'
  import { ui } from '../lib/ui.svelte'

  interface Person { name: string; scrobble_as?: string | null; own_listenbrainz: boolean }
  interface Circle { name: string; members: string[]; blend: number; speaker: boolean; concerts: boolean }
  interface Cfg { owner: string; people: Record<string, Person>; circles: Record<string, Circle> }

  let cfg = $state<Cfg | null>(null)
  let dirty = $state(false)
  let saving = $state(false)
  $effect(() => { get<Cfg>('/api/people', 0).then((v) => (cfg = v)).catch(() => ui.say("Couldn't load people")) })

  const ids = (o: object) => Object.keys(o)
  const touch = () => (dirty = true)
  function addCircle() {
    const name = prompt('Circle name (e.g. Family, Partner, Friends)')?.trim()
    if (!name || !cfg) return
    const id = name.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'circle'
    cfg.circles[cfg.circles[id] ? id + '-' + Date.now() % 1000 : id] = { name, members: [cfg.owner], blend: 0, speaker: false, concerts: false }
    touch()
  }
  function toggle(c: Circle, u: string) { c.members = c.members.includes(u) ? c.members.filter((m) => m !== u) : [...c.members, u]; touch() }
  function only(flag: 'speaker' | 'concerts', id: string) { for (const k of ids(cfg!.circles)) cfg!.circles[k][flag] = k === id; touch() }
  async function save() {
    saving = true
    try {
      const r = await fetch('/api/people', { method: 'PUT', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cfg) })
      if (!r.ok) throw new Error(await r.text())
      cfg = await r.json(); dirty = false; ui.say('Saved: takes effect right away')
    } catch (e) { ui.say('Save failed: ' + (e as Error).message) }
    saving = false
  }
</script>

{#if cfg}
  <div class="ed">
    <h3>People <small>everyone Authelia lets into ytm appears here after their first visit</small></h3>
    {#each ids(cfg.people) as u (u)}
      {@const p = cfg.people[u]}
      <div class="person">
        <input value={p.name} oninput={(e) => { p.name = (e.currentTarget as HTMLInputElement).value; touch() }} aria-label="Name of {u}" />
        <small class="login">{u}{u === cfg.owner ? ' · owner' : ''}</small>
        {#if p.own_listenbrainz}<small>ListenBrainz: own account</small>
        {:else}
          <label><small>ListenBrainz</small>
            <select value={p.scrobble_as ?? ''} onchange={(e) => { p.scrobble_as = (e.currentTarget as HTMLSelectElement).value || null; touch() }}>
              <option value="">off</option>
              {#each ids(cfg.people).filter((x) => x !== u && cfg!.people[x].own_listenbrainz) as x}<option value={x}>scrobble as {cfg.people[x].name}</option>{/each}
            </select></label>
        {/if}
      </div>
    {/each}

    <h3>Circles <small>share playlists & stats; blend = how much members' listening shapes each other's taste</small>
      <button class="more" onclick={addCircle}><Icon name="plus" size={15} /> New circle</button></h3>
    {#each ids(cfg.circles) as id (id)}
      {@const c = cfg.circles[id]}
      <div class="circ">
        <div class="top">
          <input value={c.name} oninput={(e) => { c.name = (e.currentTarget as HTMLInputElement).value; touch() }} aria-label="Circle name" />
          <button class="icon-btn" aria-label="Delete circle" onclick={() => { if (confirm(`Delete circle “${c.name}”? Playlists shared with it become private to their owners.`)) { delete cfg!.circles[id]; touch() } }}><Icon name="trash" size={17} /></button>
        </div>
        <div class="mem">{#each ids(cfg.people) as u}<button class="chip" class:on={c.members.includes(u)} onclick={() => toggle(c, u)}>{cfg.people[u].name}</button>{/each}</div>
        <label class="blend">Taste blend <input type="range" min="0" max="1" step="0.1" value={c.blend}
          oninput={(e) => { c.blend = +(e.currentTarget as HTMLInputElement).value; touch() }} />
          <b>{c.blend ? Math.round(c.blend * 100) + '%' : 'off'}</b>
          <small>{c.blend >= 0.5 ? 'household / partner: you learn from each other' : c.blend > 0 ? 'a light touch of each other' : 'friends: separate tastes, shared playlists'}</small></label>
        <div class="flags">
          <label><input type="radio" name="speaker" checked={c.speaker} onchange={() => only('speaker', id)} /> owns the Nest speaker + wake-up music</label>
          <label><input type="radio" name="concerts" checked={c.concerts} onchange={() => only('concerts', id)} /> concerts follow its artists</label>
        </div>
      </div>
    {/each}
    <div class="save"><button class="pill" disabled={!dirty || saving} onclick={save}>{saving ? 'Saving…' : 'Save'}</button>
      <small>New people: add them in Authelia with group <code>music</code>; they show up here after signing in.</small></div>
  </div>
{/if}

<style>
  .ed { background: var(--surface); border-radius: 14px; padding: 14px 16px; margin-top: 10px; }
  h3 { font-size: 15px; margin: 6px 0 10px; display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 10px; }
  h3 small, small { color: var(--muted); font-weight: 400; font-size: 12px; }
  .more { margin-left: auto; display: inline-flex; align-items: center; gap: 4px; font-size: 13px; color: var(--muted); font-weight: 600; }
  input:not([type]), .top input { height: 34px; border: 0; border-radius: 8px; padding: 0 10px; background: var(--surface-2); color: var(--fg); font: inherit; min-width: 0; }
  select { background: var(--surface-2); color: var(--fg); border: 0; border-radius: 8px; padding: 4px 8px; font: inherit; font-size: 13px; margin-left: 6px; }
  .person { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px; padding: 6px 0; border-bottom: 1px solid var(--surface-2); }
  .person input { width: 140px; }
  .login { min-width: 110px; }
  .circ { border: 1px solid var(--surface-2); border-radius: 12px; padding: 10px 12px; margin-bottom: 10px; display: grid; gap: 10px; }
  .top { display: flex; gap: 8px; } .top input { flex: 1; font-weight: 700; }
  .mem { display: flex; flex-wrap: wrap; gap: 6px; }
  .blend { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; font-size: 14px; }
  .blend input { accent-color: var(--accent); width: 140px; }
  .flags { display: flex; flex-wrap: wrap; gap: 4px 18px; font-size: 13px; color: var(--fg-2); }
  .flags input { accent-color: var(--accent); }
  .save { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 6px; }
  code { background: var(--surface-2); padding: 0 4px; border-radius: 4px; }
</style>
