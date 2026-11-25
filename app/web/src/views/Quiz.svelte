<!-- First-run taste quiz: 10 rounds of 3 songs, ❤️ what you like (server/quiz.py). Tap a cover to listen. -->
<script lang="ts">
  import Icon from '../components/Icon.svelte'
  import { get, post } from '../lib/api'
  import { sized } from '../lib/img'
  import { player } from '../lib/player.svelte'
  import { router } from '../lib/router.svelte'
  import type { Song } from '../lib/types'

  let round = $state(1)
  let total = $state(10)
  let songs = $state<Song[]>([])
  let liked = $state<Set<string>>(new Set())
  let loading = $state(true)
  let likedCount = $state(0)
  let done = $state(false)

  async function load(n: number) {
    loading = true
    try {
      const r = await get<{ round: number; total: number; songs: Song[] }>(`/api/quiz?round=${n}`, 0)
      round = r.round; total = r.total; songs = r.songs; liked = new Set()
      if (!r.songs.length) done = true                          // out of songs: finish early
    } catch { songs = [] }
    loading = false
  }
  $effect(() => { load(1) })

  function toggle(v: string) {
    const s = new Set(liked)
    if (s.has(v)) s.delete(v); else s.add(v)
    liked = s
  }

  async function next() {
    const r = await post<{ liked: number }>('/api/quiz', { shown: songs.map((s) => s.videoId), liked: [...liked] }).catch(() => null)
    if (r) likedCount = r.liked
    if (round >= total) { done = true; return }
    await load(round + 1)
  }
</script>

<div class="page quiz">
  {#if done}
    <h1 class="h">Thanks!</h1>
    <p class="muted">{likedCount ? `${likedCount} songs liked. Your mix and autoplay start from them, and keep learning from what you finish and skip.` : 'Nothing liked: no problem, Kassetto learns from what you play.'}</p>
    <button class="pill" onclick={() => router.go({ name: 'home' })}><Icon name="home" size={20} /> To your home page</button>
  {:else}
    <h1 class="h">What do you like? <small class="muted">{round} / {total}</small></h1>
    <p class="muted">Tap a cover to listen, ❤️ the ones you like (any number, or none).</p>
    <div class="row">
      {#if loading}
        {#each [0, 1, 2] as _}<div class="card skel"></div>{/each}
      {:else}
        {#each songs as s (s.videoId)}
          <div class="card" class:on={liked.has(s.videoId)}>
            <button class="cover" aria-label={`Play ${s.title}`} onclick={() => player.playList([s], 0)}>
              <img src={sized(s.thumb, 240)} alt="" loading="lazy" />
              <span class="play"><Icon name={player.current?.videoId === s.videoId && player.playing ? 'pause' : 'play'} size={28} /></span>
            </button>
            <div class="meta"><b class="ellipsis">{s.title}</b><small class="ellipsis muted">{s.artist}</small></div>
            <button class="heart" aria-pressed={liked.has(s.videoId)} aria-label="Like" onclick={() => toggle(s.videoId)}>
              <Icon name={liked.has(s.videoId) ? 'liked' : 'like'} size={24} /></button>
          </div>
        {/each}
      {/if}
    </div>
    <div class="acts">
      <button class="pill" onclick={next} disabled={loading}>{round >= total ? 'Finish' : 'Next'}</button>
      <button class="pill ghost" onclick={() => { done = true }}>Stop here</button>
    </div>
  {/if}
</div>

<style>
  .row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 16px 0; }
  .card { background: var(--card, rgba(255, 255, 255, .04)); border-radius: 12px; padding: 8px; display: flex;
          flex-direction: column; gap: 6px; border: 2px solid transparent; min-height: 220px; }
  .card.on { border-color: var(--accent); }
  .cover { position: relative; padding: 0; border: 0; background: none; cursor: pointer; aspect-ratio: 1; }
  .cover img { width: 100%; height: 100%; object-fit: cover; border-radius: 8px; display: block; }
  .play { position: absolute; inset: auto 6px 6px auto; background: rgba(0, 0, 0, .55); border-radius: 50%; padding: 6px; display: flex; }
  .meta { display: flex; flex-direction: column; min-width: 0; }
  .heart { align-self: flex-end; background: none; border: 0; color: var(--accent); cursor: pointer; }
  .acts { display: flex; gap: 8px; }
  .skel { min-height: 220px; }
</style>
