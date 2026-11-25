<script lang="ts">
  import Icon from './Icon.svelte'
  import Tile from './Tile.svelte'
  import type { Entry } from '../lib/types'

  let { title, items, sub = '' }: { title: string; items: Entry[]; sub?: string } = $props()
  let el = $state<HTMLDivElement>() as HTMLDivElement
  let atStart = $state(true), atEnd = $state(false)
  function onScroll() {
    atStart = el.scrollLeft < 8
    atEnd = el.scrollLeft + el.clientWidth > el.scrollWidth - 8
  }
  const by = (d: number) => el.scrollBy({ left: d * el.clientWidth * 0.85, behavior: 'smooth' })
</script>

{#if items.length}
  <section class="shelf">
    <div class="head">
      <h2 class="section-title">{title}{#if sub}<small>{sub}</small>{/if}</h2>
      <div class="nav">
        <button class="icon-btn" aria-label="Scroll left" disabled={atStart} onclick={() => by(-1)}><Icon name="left" /></button>
        <button class="icon-btn" aria-label="Scroll right" disabled={atEnd} onclick={() => by(1)}><Icon name="right" /></button>
      </div>
    </div>
    <div class="scroller" bind:this={el} onscroll={onScroll}>
      {#each items as it, i ((it.type === 'song' ? it.videoId : it.type + it.id) + ':' + i)}
        <Tile item={it} />
      {/each}
    </div>
  </section>
{/if}

<style>
  .shelf { content-visibility: auto; contain-intrinsic-size: auto 260px; }
  .head { display: flex; align-items: center; justify-content: space-between; }
  .nav { display: none; gap: 4px; margin-top: 14px; }
  .nav button:disabled { opacity: .3; pointer-events: none; }
  @media (hover: hover) and (min-width: 960px) { .nav { display: flex; } }
  .scroller {
    display: flex; gap: 14px; overflow-x: auto; scroll-snap-type: x mandatory; scroll-padding: 0 16px;
    margin: 0 -16px; padding: 0 16px 6px; scrollbar-width: none; overscroll-behavior-x: contain;
  }
  .scroller::-webkit-scrollbar { display: none; }
</style>
