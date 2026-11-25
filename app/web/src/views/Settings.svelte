<!-- Settings: playback, sound, the speaker, people & circles (moved out of Library to keep it about music). -->
<script lang="ts">
  import HeadphonePicker from '../components/HeadphonePicker.svelte'
  import PeopleEditor from '../components/PeopleEditor.svelte'
  import Routines from '../components/Routines.svelte'
  import Icon from '../components/Icon.svelte'
  import { get, post } from '../lib/api'
  import { ui } from '../lib/ui.svelte'
  import { player, type Output } from '../lib/player.svelte'

  interface Me { user: string; name: string; owner: boolean; can_cast: boolean; speaker: string | null; listenbrainz: string
    blend: { name: string; weight: number }[]; circles: { id: string; name: string; blend: number; speaker: boolean; members: { user: string; name: string }[] }[] }
  let me = $state<Me | null>(null)
  let showPeople = $state(false)
  $effect(() => { get<Me>('/api/me', 0).then((v) => (me = v)).catch(() => {}) })
  interface Spk { on: boolean; bass: number; treble: number; allowed: boolean }
  let spk = $state<Spk | null>(null)
  $effect(() => { get<Spk>('/api/speaker', 0).then((v) => (spk = v)).catch(() => {}) })
  async function setSpk(patch: Partial<Spk>) {
    if (!spk) return
    spk = { ...spk, ...patch }
    await post('/api/speaker', patch).catch(() => ui.say("Couldn't save"))
  }
  let canCast = $derived(!!me?.can_cast)

  // The speaker (owner): found on the network (mDNS), or fixed by KASSETTO_SPEAKER
  interface Found { host: string; name: string; model: string }
  interface Speakers { current: { host: string; name: string; fixed?: boolean } | null; found: Found[]; stream_base: string }
  let speakers = $state<Speakers | null>(null)
  let searching = $state(false)
  async function findSpeakers() {
    searching = true
    try { speakers = await get<Speakers>('/api/speakers', 0) } catch { ui.say("Couldn't look for speakers") }
    searching = false
  }
  async function pick(s: Found | null) {
    try {
      await post('/api/speakers', s ? { host: s.host, name: s.name } : { host: null })
      ui.say(s ? `Speaker: ${s.name}` : 'No speaker'); await findSpeakers(); location.reload()
    } catch { ui.say("Couldn't save") }
  }
</script>

<div class="page">
  <h1 class="h">Settings</h1>
  {#if me}<p class="who">Listening as <b>{me.name}</b> ·
    {#if me.blend.length}taste blended with {me.blend.map((b) => `${b.name} (${Math.round(b.weight * 100)}%)`).join(', ')}, your own plays count most{:else}your own taste{/if}
    · ListenBrainz {me.listenbrainz === 'own' ? 'on' : me.listenbrainz}</p>{/if}
  <section>
    <h2 class="section-title">Playback & sound</h2>
    <label class="setting">
      <span><b>Autoplay</b><br><small class="muted">Keep playing similar songs, picked for you, when the queue ends</small></span>
      <input type="checkbox" checked={player.autoplay} onchange={(e) => player.setAutoplay((e.currentTarget as HTMLInputElement).checked)} />
    </label>
    <label class="setting">
      <span><b>Even volume</b><br><small class="muted">Turn loud songs down so every song plays at about the same loudness</small></span>
      <input type="checkbox" checked={player.normalize} onchange={(e) => player.setNormalize((e.currentTarget as HTMLInputElement).checked)} />
    </label>
    <label class="setting">
      <span><b>Skip silence</b><br><small class="muted">Skip silent intros and endings</small></span>
      <input type="checkbox" checked={player.trim} onchange={(e) => player.setTrim((e.currentTarget as HTMLInputElement).checked)} />
    </label>
    <label class="setting">
      <span><b>Crossfade</b><br><small class="muted">Blend into the next song (not within an album)</small></span>
      <select value={player.crossfade} onchange={(e) => player.setCrossfade(+(e.currentTarget as HTMLSelectElement).value)}>
        {#each [0, 2, 3, 5, 8] as s}<option value={s}>{s ? `${s} s` : 'Off'}</option>{/each}
      </select>
    </label>
    <label class="setting">
      <span><b>Sound profile</b> <span class="exp">Experimental</span><br><small class="muted">Tune playback on this device for your headphones or its own speaker</small></span>
      <input type="checkbox" checked={player.eqOn} onchange={(e) => player.setEqOn((e.currentTarget as HTMLInputElement).checked)} />
    </label>
    {#if player.eqOn}
      <div class="sub-set prof">
        <div class="seg" role="radiogroup" aria-label="Playing through">
          {#each [['headphones', 'Headphones'], ['speaker', 'Phone speaker'], ['off', 'Off']] as [k, label]}
            <button role="radio" aria-checked={player.output === k} class:on={player.output === k} onclick={() => player.setOutput(k as Output)}>{label}</button>
          {/each}
        </div>
        <small class="muted">{player.output === 'speaker' ? 'Drops the bass a phone speaker can’t play (less distortion when loud), adds warmth and clarity, evens out quiet and loud parts.'
          : player.output === 'headphones' ? 'A measured correction for your model (below).' : 'Plain playback.'} Switch any time from the full player.</small>
        {#if player.output !== 'off'}
          <label>Bass <input type="range" min="-6" max="6" step="1" value={player.tone.bass} onchange={(e) => player.setTone({ ...player.tone, bass: +(e.currentTarget as HTMLInputElement).value })} /> {player.tone.bass > 0 ? '+' : ''}{player.tone.bass} dB</label>
          <label>Treble <input type="range" min="-6" max="6" step="1" value={player.tone.treble} onchange={(e) => player.setTone({ ...player.tone, treble: +(e.currentTarget as HTMLInputElement).value })} /> {player.tone.treble > 0 ? '+' : ''}{player.tone.treble} dB</label>
        {/if}
      </div>
      {#if player.output === 'headphones'}<HeadphonePicker />{/if}
    {/if}
  </section>
  {#if canCast || spk?.allowed || me?.owner}
    <section>
      <h2 class="section-title">{me?.speaker ?? 'Speaker'}</h2>
      {#if me?.owner}
        <div class="setting">
          <span><b>Speaker</b><br><small class="muted">{me.speaker ? `Playing on: ${me.speaker}` : 'None yet: find the Chromecast / Google Home speakers on your network'}</small></span>
          <button class="pill ghost" onclick={findSpeakers} disabled={searching}>{searching ? 'Looking…' : 'Find speakers'}</button>
        </div>
        {#if speakers}
          <div class="sub-set">
            {#if speakers.current?.fixed}<small class="muted">Set by KASSETTO_SPEAKER on the server.</small>
            {:else}
              {#each speakers.found as s (s.host)}
                <label><input type="radio" name="spk" checked={speakers.current?.host === s.host} onchange={() => pick(s)} /> {s.name} <small class="muted">{s.model} · {s.host}</small></label>
              {:else}<small class="muted">No speaker answered. Kassetto has to share the speakers' network (Docker: network_mode: host), or set KASSETTO_SPEAKER to its address.</small>{/each}
              {#if speakers.current}<button class="pill ghost" onclick={() => pick(null)}>Don't use a speaker</button>{/if}
            {/if}
            {#if speakers.current && !speakers.stream_base}<small class="muted">Set KASSETTO_STREAM_BASE (http://this-server:8091) so the speaker can fetch the music.</small>{/if}
          </div>
        {/if}
      {/if}
      {#if spk?.allowed}
        <label class="setting">
          <span><b>Speaker tuning</b><br><small class="muted">Even volume, a small-speaker EQ, clean mono mix and gentle compression for a small speaker</small></span>
          <input type="checkbox" checked={spk.on} onchange={(e) => setSpk({ on: (e.currentTarget as HTMLInputElement).checked })} />
        </label>
        {#if spk.on}
          <div class="sub-set">
            <label>Bass <input type="range" min="-6" max="6" step="1" value={spk.bass} onchange={(e) => setSpk({ bass: +(e.currentTarget as HTMLInputElement).value })} /> {spk.bass > 0 ? '+' : ''}{spk.bass} dB</label>
            <label>Treble <input type="range" min="-6" max="6" step="1" value={spk.treble} onchange={(e) => setSpk({ treble: +(e.currentTarget as HTMLInputElement).value })} /> {spk.treble > 0 ? '+' : ''}{spk.treble} dB</label>
            <small class="muted">Applies from the next song the speaker starts.</small>
          </div>
        {/if}
      {/if}
      <Routines />
    </section>
  {/if}
  {#if me?.circles.length || me?.owner}
    <section>
      <h2 class="section-title">Your circles <small>who you share playlists, stats and (if blended) taste with</small></h2>
      {#each me.circles as c (c.id)}
        <div class="circle"><b>{c.name}</b>{#if c.speaker}<span class="tag">speaker</span>{/if}
          <small>{c.members.map((m) => m.name).join(', ')} · taste blend {c.blend ? Math.round(c.blend * 100) + '%' : 'off'}</small></div>
      {:else}<p class="muted">You're not in a circle yet: your taste, playlists and stats are your own.</p>{/each}
      {#if me.owner}<button class="pill ghost stats" onclick={() => (showPeople = !showPeople)}><Icon name="share" size={18} /> People & circles</button>
        {#if showPeople}<PeopleEditor />{/if}{/if}
    </section>
  {/if}
</div>
<style>
  .h { font-size: 28px; font-weight: 800; margin: 18px 0 0; }
  .who { color: var(--muted); margin: 4px 0 0; font-size: 14px; }
  .more { margin: 6px 8px; color: var(--muted); font-weight: 600; font-size: 14px; }
  .more:hover { color: var(--fg); }
  .setting { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 16px; border-radius: 14px; background: var(--surface); cursor: pointer; }
  .setting input { width: 22px; height: 22px; accent-color: var(--accent); }
  .setting + .setting, .sub-set + .setting { margin-top: 8px; }
  .stats { margin-top: 14px; }
  .circle { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 10px; padding: 12px 16px; background: var(--surface); border-radius: 12px; margin-bottom: 8px; }
  .circle small { color: var(--muted); flex-basis: 100%; }
  .tag { font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: var(--accent); border: 1px solid currentColor; border-radius: 6px; padding: 0 5px; }
  .sub-set { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 18px; padding: 12px 16px; background: var(--surface); border-radius: 0 0 14px 14px; margin-top: -10px; color: var(--fg-2); font-size: 14px; }
  .sub-set .days { display: flex; gap: 6px; flex-wrap: wrap; }
  .prof small { flex-basis: 100%; }
  .seg { display: inline-flex; background: var(--surface-2); border-radius: 10px; padding: 3px; }
  .seg button { padding: 6px 12px; border-radius: 8px; font-size: 13px; font-weight: 650; color: var(--muted); }
  .seg button.on { background: var(--accent); color: var(--accent-fg); }
  .sub-set select { background: var(--surface-2); color: var(--fg); border: 0; border-radius: 8px; padding: 4px 8px; font: inherit; margin-left: 6px; }
  .sub-set input[type=range] { accent-color: var(--accent); vertical-align: middle; width: 120px; }
  .exp { font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: var(--accent); border: 1px solid currentColor; border-radius: 6px; padding: 1px 5px; vertical-align: 2px; }
  .setting select { background: var(--surface-2); color: var(--fg); border: 0; border-radius: 8px; padding: 6px 10px; font: inherit; }
</style>
