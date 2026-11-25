<!-- Artwork: right-sized from the CDN, lazy, async-decoded, fades in once loaded (no layout shift). -->
<script lang="ts">
  import { sized } from '../lib/img'
  let { src, size = 48, round = false, eager = false, alt = '' }:
    { src?: string | null; size?: number; round?: boolean; eager?: boolean; alt?: string } = $props()
  let loaded = $state(false)
  let url = $derived(sized(src, size))
  $effect(() => { url; loaded = false })
</script>

<div class="art" class:round style:--s="{size}px">
  {#if url}
    <img src={url} {alt} width={size} height={size} loading={eager ? 'eager' : 'lazy'} decoding="async"
         fetchpriority={eager ? 'high' : 'auto'} class:loaded onload={() => (loaded = true)} onerror={() => (loaded = true)} />
  {/if}
</div>

<style>
  .art { width: var(--s); height: var(--s); flex: none; border-radius: 6px; overflow: hidden; background: var(--surface-2); }
  .round { border-radius: 50%; }
  img { width: 100%; height: 100%; object-fit: cover; opacity: 0; transition: opacity .25s ease; }
  img.loaded { opacity: 1; }
</style>
