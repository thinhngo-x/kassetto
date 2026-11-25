<script lang="ts">
  import Art from './Art.svelte'
  import Icon from './Icon.svelte'
  import { get, warm } from '../lib/api'
  import { player } from '../lib/player.svelte'
  import { router } from '../lib/router.svelte'
  import type { Detail, Entry } from '../lib/types'

  let { item, size = 156 }: { item: Entry; size?: number } = $props()

  const path = (it: Entry) => (it.type === 'song' ? '' : `/api/${it.type}?id=${encodeURIComponent(it.id)}`)

  function open() {
    if (item.type === 'song') player.playList([item])
    else router.go({ name: 'detail', kind: item.type, id: item.id })
  }
  async function quickPlay(e: Event) {
    e.stopPropagation()
    if (item.type === 'song') return player.playList([item])
    const d = await get<Detail>(path(item))
    if (d.tracks?.length) player.playList(d.tracks, 0)
  }
  // hover with a mouse = intent; touch is skipped on purpose (a finger landing on a tile is usually a scroll)
  function intent(e: PointerEvent) { if (e.pointerType === 'mouse' && item.type !== 'song') warm(path(item)) }
  let sub = $derived(item.type === 'song' ? item.artist : item.sub || '')
</script>

<div class="tile" class:artist={item.type === 'artist'} style:--w="{size}px" role="button" tabindex="0"
     onclick={open} onpointerenter={intent} onkeydown={(e) => e.key === 'Enter' && open()}>
  <div class="cover">
    <Art src={item.thumb} {size} round={item.type === 'artist'} />
    {#if item.type !== 'artist'}
      <button class="play" aria-label="Play {item.title}" onclick={quickPlay}><Icon name="play" size={18} /></button>
    {/if}
  </div>
  <div class="t ellipsis">{item.title}</div>
  {#if sub}<div class="s ellipsis">{sub}</div>{/if}
</div>

<style>
  .tile { width: var(--w); flex: none; cursor: pointer; scroll-snap-align: start; }
  .cover { position: relative; border-radius: 10px; transition: transform .18s var(--ease); }
  .tile:active .cover { transform: scale(.97); }
  .cover :global(.art) { border-radius: 10px; }
  .artist .cover :global(.art) { border-radius: 50%; }
  .play {
    position: absolute; right: 8px; bottom: 8px; width: 38px; height: 38px; border-radius: 50%; display: grid; place-items: center;
    background: var(--accent); color: var(--accent-fg); box-shadow: 0 6px 18px rgb(0 0 0 / .4);
    opacity: 0; transform: translateY(6px); transition: opacity .18s, transform .18s var(--ease);
  }
  .tile:hover .play, .tile:focus-within .play { opacity: 1; transform: none; }
  @media (hover: none) { .play { opacity: .92; transform: none; width: 32px; height: 32px; } }
  .t { margin-top: 8px; font-weight: 600; font-size: 14px; }
  .s { color: var(--muted); font-size: 12.5px; margin-top: 1px; }
  .artist .t, .artist .s { text-align: center; }
</style>
