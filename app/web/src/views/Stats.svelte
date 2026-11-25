<!-- Your listening stats (this month / year / all time / a past month) + what both listeners love. -->
<script lang="ts">
  import Icon from '../components/Icon.svelte'
  import SongRow from '../components/SongRow.svelte'
  import { get } from '../lib/api'
  import { player } from '../lib/player.svelte'
  import type { Song, Taste } from '../lib/types'

  interface S { period: string; months: string[]; minutes: number; plays: number; artists_count: number; songs_count: number
    days_listened: number; top_artists: { name: string; plays: number }[]
    top_songs: { videoId: string | null; title: string; artist: string; plays: number; thumb?: string }[]
    hours: number[]; timeline: { month: string; minutes: number; top_artist: string | null }[]; spotify?: Sp | null }
  interface Sp { from: string; to: string; plays: number; hours: number; artists_count: number; songs_count: number
    years: { year: string; plays: number; hours: number; top_artist: string }[]; top_artists: { name: string; hours: number }[]
    top_songs: { title: string; artist: string; album: string; plays: number; videoId: string | null }[] }
  interface T { circle: string | null; circle_name?: string; circles?: { id: string; name: string }[]; members: { user: string; name: string }[]
    artists: { name: string; people: string[]; share: number }[]; songs: Song[] }

  let taste = $state<Taste | null>(null)
  $effect(() => { get<Taste>('/api/taste', 60_000).then((v) => (taste = v)).catch(() => {}) })
  const pct = (x: number) => Math.round(x * 100)
  const SIG: Record<string, string> = { replay: 'Replays', queue_add: 'Queued (play next / add)', queue_remove: 'Removed from queue',
    search_click: 'Played from search', search_artist: 'Artists searched', lyrics_open: 'Lyrics opened', seek_back: 'Rewinds',
    seek_fwd: 'Big skips ahead', volume_up: 'Volume turned up', queue_pick: 'Picked from Up next',
    pass: 'Autoplay picks jumped past', escape: 'Left autoplay for your own pick' }
  const FEAT: Record<string, string> = { sim: 'Similar to what plays', aff: 'Artists you like', snd: 'Sounds like your taste',
    sess: 'Fits this session', sess_art: "Session's artist mood", new_artist: 'New artists', recent: 'Played recently',
    skips: 'Skipped before', liked: 'Liked songs' }
  let period = $state('month')
  let s = $state<S | null>(null)
  let t = $state<T | null>(null)
  $effect(() => { const p = period; s = null; get<S>(`/api/stats?period=${p}`, 0).then((v) => (s = v)).catch(() => {}) })
  let circle = $state('')
  $effect(() => { const c = circle; get<T>(`/api/together${c ? '?circle=' + c : ''}`, 0).then((v) => (t = v)).catch(() => {}) })

  const monthName = (m: string) => new Date(m + '-01T12:00').toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
  const fmtMin = (m: number) => (m >= 120 ? `${Math.round(m / 6) / 10} h` : `${m} min`)
  let songs = $derived((s?.top_songs ?? []).filter((x) => x.videoId).map((x): Song => ({ type: 'song', videoId: x.videoId!, title: x.title,
    artist: x.artist, thumb: x.thumb, album: `${x.plays} play${x.plays === 1 ? '' : 's'}` })))
  let sp = $derived(s?.spotify ?? null)
  let maxY = $derived(Math.max(1, ...(sp?.years ?? []).map((y) => y.hours)))
  let maxSA = $derived(Math.max(1, ...(sp?.top_artists ?? []).map((a) => a.hours)))
  let prior = $state<boolean | null>(null)
  $effect(() => { if (sp && prior === null) get<{ prior: boolean }>('/api/spotify', 0).then((v) => (prior = v.prior)).catch(() => {}) })
  async function setPrior(v: boolean) {
    prior = v
    await fetch('/api/spotify', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prior: v }) })
  }
  let maxA = $derived(Math.max(1, ...(s?.top_artists ?? []).map((a) => a.plays)))
  let maxH = $derived(Math.max(1, ...(s?.hours ?? [0])))
  let maxM = $derived(Math.max(1, ...(s?.timeline ?? []).map((m) => m.minutes)))
  let peak = $derived(s ? s.hours.indexOf(Math.max(...s.hours)) : -1)
  const part = (h: number) => (h < 5 ? 'night owl' : h < 12 ? 'morning person' : h < 18 ? 'afternoon listener' : 'evening listener')
</script>

<div class="page">
  <h1 class="h">Your stats</h1>
  <div class="chips per">
    <button class="chip" class:on={period === 'month'} onclick={() => (period = 'month')}>This month</button>
    <button class="chip" class:on={period === 'year'} onclick={() => (period = 'year')}>This year</button>
    <button class="chip" class:on={period === 'all'} onclick={() => (period = 'all')}>All time</button>
    {#each (s?.months ?? []).slice(1, 7) as m}<button class="chip" class:on={period === m} onclick={() => (period = m)}>{monthName(m)}</button>{/each}
  </div>

  {#if !s}
    <div class="cards">{#each Array(4) as _}<div class="skel" style="height:86px"></div>{/each}</div>
  {:else if !s.plays}
    <p class="muted">Nothing listened to in this period yet. Stats fill up as you play (half a song or more counts).</p>
  {:else}
    <div class="cards">
      <div class="card"><b>{fmtMin(s.minutes)}</b><span>listened</span></div>
      <div class="card"><b>{s.plays}</b><span>plays</span></div>
      <div class="card"><b>{s.artists_count}</b><span>artists</span></div>
      <div class="card"><b>{s.days_listened}</b><span>days with music</span></div>
    </div>

    <section>
      <h2 class="section-title">Top artists</h2>
      {#each s.top_artists.slice(0, 10) as a, i}
        <div class="bar"><span class="n">{i + 1}</span><span class="l ellipsis">{a.name}</span>
          <span class="b"><i style:transform="scaleX({a.plays / maxA})"></i></span><span class="v">{a.plays}</span></div>
      {/each}
    </section>

    {#if songs.length}
      <section>
        <h2 class="section-title">Top songs <button class="more" onclick={() => player.playList(songs, 0)}><Icon name="play" size={16} /> Play</button></h2>
        {#each songs.slice(0, 10) as x, i (x.videoId)}<SongRow song={x} num={i + 1} onplay={() => player.playList(songs, i)} />{/each}
      </section>
    {/if}

    <section>
      <h2 class="section-title">When you listen {#if peak >= 0}<small>mostly around {peak}:00, a {part(peak)}</small>{/if}</h2>
      <div class="hours">{#each s.hours as h, i}<div class="hc" title="{i}:00 · {h} min"><i style:height="{(h / maxH) * 100}%" class:pk={i === peak}></i>{#if i % 6 === 0}<small>{i}h</small>{/if}</div>{/each}</div>
    </section>

    {#if s.timeline.length > 1}
      <section>
        <h2 class="section-title">Month by month</h2>
        {#each s.timeline.slice().reverse() as m}
          <div class="bar"><span class="l ellipsis">{monthName(m.month)}</span><span class="b"><i style:transform="scaleX({m.minutes / maxM})"></i></span>
            <span class="v w">{fmtMin(m.minutes)}{m.top_artist ? ` · ${m.top_artist}` : ''}</span></div>
        {/each}
      </section>
    {/if}
  {/if}

  {#if sp}
    <section>
      <h2 class="section-title">Your Spotify years <small>{sp.from}–{sp.to} · {sp.hours} h · {sp.plays} plays · {sp.artists_count} artists</small></h2>
      {#each sp.years as y}
        <div class="bar"><span class="l ellipsis">{y.year}</span><span class="b"><i style:transform="scaleX({y.hours / maxY})"></i></span>
          <span class="v w">{y.hours} h · {y.top_artist}</span></div>
      {/each}
      <h3 class="sub">Top artists then</h3>
      {#each sp.top_artists.slice(0, 10) as a, i}
        <div class="bar"><span class="n">{i + 1}</span><span class="l ellipsis">{a.name}</span>
          <span class="b"><i style:transform="scaleX({a.hours / maxSA})"></i></span><span class="v">{a.hours} h</span></div>
      {/each}
      <h3 class="sub">Top songs then</h3>
      {#each sp.top_songs.slice(0, 10) as x, i}
        <div class="bar"><span class="n">{i + 1}</span><span class="l ellipsis">{x.title}</span><span class="v w">{x.artist} · {x.plays}×</span></div>
      {/each}
      {#if prior !== null}
        <label class="prior"><input type="checkbox" checked={prior} onchange={(e) => setPrior((e.currentTarget as HTMLInputElement).checked)} />
          Let it nudge autoplay <small>only artists you still play here get a small boost; it never brings back an artist on its own</small></label>
      {/if}
    </section>
  {/if}

  {#if t?.circle}
    <section>
      <h2 class="section-title">{t.members.length === 2 ? 'Both of you' : `Your circle: ${t.circle_name}`} <small>{t.members.map((m) => m.name).join(', ')}</small></h2>
      {#if (t.circles?.length ?? 0) > 1}<div class="chips per">{#each t.circles! as c}<button class="chip" class:on={t.circle === c.id} onclick={() => (circle = c.id)}>{c.name}</button>{/each}</div>{/if}
      {#if t.artists.length}
        <div class="chips">{#each t.artists as a}<span class="chip" title="played by {a.people.join(', ')}">{a.name}{t.members.length > 2 ? ` · ${a.people.length}` : ''}</span>{/each}</div>
      {:else}<p class="muted">No artists in common yet.</p>{/if}
      {#if t.songs.length}
        <h3 class="sub">Songs {t.members.length === 2 ? 'you both' : 'several of you'} love</h3>
        {#each t.songs.slice(0, 10) as x, i (x.videoId)}<SongRow song={x} onplay={() => player.playList(t!.songs, i)} />{/each}
      {/if}
    </section>
  {:else if t}
    <p class="muted together">Join a circle (family, partner, friends) and what you love in common shows up here.</p>
  {/if}
  <section>
    <h2 class="section-title">What Kassetto has learned <small>your taste, as the recommender sees it</small></h2>
    {#if taste}
      <div class="tcards">
        <div class="tcard">
          <div class="k">Plays</div><div class="v">{taste.ytm_plays + taste.listenbrainz_listens}</div>
          <div class="k">Likes</div><div class="v">{taste.likes}</div>
          <div class="k">Variety boost now <small class="muted">(when autoplay isn't holding you)</small></div><div class="v">{Math.round((taste.boredom ?? 0) * 100)}%</div>
          <div class="k">Songs fingerprinted</div><div class="v">{taste.embedded}<small>{taste.embed_queue ? ` +${taste.embed_queue} queued` : ''}</small></div>
        </div>
        <div class="tcard">
          <div class="ct">Top artists</div>
          <div class="artists">{#each taste.top_artists.slice(0, 10) as [a]}<span class="chip">{a}</span>{/each}</div>
        </div>
        <div class="tcard">
          <div class="ct">What it learns from <small>besides ♡ and how much you listen</small></div>
          {#each Object.entries(SIG) as [k, label]}
            <div class="k">{label}</div><div class="v">{taste.signals?.[k] ?? 0}</div>
          {/each}
        </div>
        {#if taste.ranker}
          {@const moved = Object.entries(taste.ranker.weights).filter(([k]) => k !== 'bias').map(([k, v]) => [k, v.now - v.start] as const).sort((x, y) => Math.abs(y[1]) - Math.abs(x[1]))}
          <div class="tcard wide">
            <div class="ct">The ranker is learning you <small>{taste.ranker.labelled} of {taste.ranker.served} picks have an outcome · {taste.ranker.updates} updates</small></div>
            {#if taste.ranker.updates}
              {#each moved.slice(0, 5) as [k, d]}
                <div class="src"><span class="sn">{FEAT[k] ?? k}</span><span class="sb"><i style:transform="scaleX({Math.min(1, Math.abs(d) / 1.5)})" class:neg={d < 0}></i></span><span class="sv">{d > 0 ? '+' : ''}{d.toFixed(2)}</span></div>
              {/each}
              <small class="muted">How much each signal's weight moved from where Kassetto started, for you{taste.session?.plays ? ` · this session: ${taste.session.plays} plays` : ''}.</small>
            {:else}<small class="muted">It starts from Kassetto's built-in weights and adjusts them to you as autoplay picks get finished, skipped or passed over.</small>{/if}
          </div>
        {/if}
        <div class="tcard wide">
          <div class="ct">How each source is doing <small>(share of its picks you finished)</small></div>
          {#each Object.entries(taste.sources).sort((a, b) => b[1] - a[1]) as [name, v]}
            <div class="src"><span class="sn">{name}</span><span class="sb"><i style:transform="scaleX({v})"></i></span><span class="sv">{pct(v)}%</span></div>
          {/each}
        </div>
        {#each taste.taste_clusters as c, k}
          <div class="tcard">
            <div class="ct">Taste group {k + 1} <small>by sound</small></div>
            <ul>{#each c.songs as s}<li class="ellipsis">{s}</li>{/each}</ul>
          </div>
        {/each}
      </div>
    {/if}
  </section>
</div>

<style>
  .h { font-size: 28px; font-weight: 800; margin: 18px 0 8px; }
  .per { margin-bottom: 14px; flex-wrap: wrap; }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }
  .card { background: var(--surface); border-radius: 14px; padding: 16px; display: flex; flex-direction: column; gap: 2px; }
  .card b { font-size: 26px; font-weight: 850; }
  .card span { color: var(--muted); font-size: 13px; }
  .bar { display: grid; grid-template-columns: 22px minmax(90px, 200px) 1fr auto; align-items: center; gap: 10px; padding: 5px 0; }
  .bar .n { color: var(--muted); font-variant-numeric: tabular-nums; text-align: right; }
  .bar:not(:has(.n)) { grid-template-columns: minmax(110px, 180px) 1fr auto; }
  .b { height: 8px; border-radius: 4px; background: var(--surface-2); overflow: hidden; }
  .b i { display: block; height: 100%; background: var(--accent); transform-origin: left; }
  .v { color: var(--muted); font-size: 13px; font-variant-numeric: tabular-nums; }
  .v.w { min-width: 0; max-width: 40vw; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .hours { display: grid; grid-template-columns: repeat(24, 1fr); gap: 3px; height: 110px; align-items: end; padding-bottom: 18px; }
  .hc { position: relative; height: 100%; display: flex; align-items: flex-end; }
  .hc i { display: block; width: 100%; min-height: 2px; background: color-mix(in srgb, var(--accent) 55%, transparent); border-radius: 3px 3px 0 0; }
  .hc i.pk { background: var(--accent); }
  .hc small { position: absolute; top: 100%; left: 0; font-size: 10px; color: var(--muted); margin-top: 4px; }
  .sub { font-size: 15px; margin: 16px 0 4px; }
  .more { margin-left: auto; display: inline-flex; align-items: center; gap: 4px; font-size: 13px; font-weight: 600; color: var(--muted); }
  .together { margin-top: 24px; }
  .sb i.neg { background: var(--muted); }
  .tcards { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
  .tcard { background: var(--surface); border-radius: 14px; padding: 16px; display: grid; grid-template-columns: 1fr auto; gap: 8px 12px; align-content: start; }
  .tcard.wide { grid-column: 1 / -1; grid-template-columns: 1fr; }
  .tcard .k { color: var(--muted); }
  .tcard .v { font-weight: 750; font-variant-numeric: tabular-nums; text-align: right; }
  .tcard .v small { color: var(--muted); font-weight: 500; }
  .ct { grid-column: 1 / -1; font-weight: 700; }
  .ct small { color: var(--muted); font-weight: 500; }
  .artists { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 6px; }
  .artists .chip { height: 28px; display: inline-flex; align-items: center; text-transform: capitalize; }
  ul { grid-column: 1 / -1; margin: 0; padding-left: 18px; color: var(--fg-2); font-size: 14px; }
  .src { display: grid; grid-template-columns: 170px 1fr 44px; align-items: center; gap: 12px; font-size: 14px; }
  .sn { color: var(--fg-2); }
  .sb { height: 6px; border-radius: 3px; background: var(--surface-2); overflow: hidden; }
  .sb i { display: block; height: 100%; background: var(--accent); transform-origin: left; transition: transform .6s var(--ease); }
  .sv { text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }
  @media (max-width: 520px) { .src { grid-template-columns: 120px 1fr 40px; } }

  .bar:has(.n):not(:has(.b)) { grid-template-columns: 22px minmax(90px, 1fr) auto; }
  .prior { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: baseline; margin-top: 14px; font-size: 14px; }
  .prior input { accent-color: var(--accent); }
  .prior small { color: var(--muted); font-size: 12px; }
  @media (max-width: 520px) { .bar { grid-template-columns: 20px 100px 1fr auto; } }
</style>
