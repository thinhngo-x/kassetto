<script lang="ts">
  import FullPlayer from './components/FullPlayer.svelte'
  import Lyrics from './components/Lyrics.svelte'
  import Icon from './components/Icon.svelte'
  import MiniPlayer from './components/MiniPlayer.svelte'
  import PlayerBar from './components/PlayerBar.svelte'
  import QueueList from './components/QueueList.svelte'
  import SongMenu from './components/SongMenu.svelte'
  import AddToPlaylist from './components/AddToPlaylist.svelte'
  import Stats from './views/Stats.svelte'
  import Settings from './views/Settings.svelte'
  import Toast from './components/Toast.svelte'
  import { dominant, palette } from './lib/img'
  import { player } from './lib/player.svelte'
  import { router, type Route } from './lib/router.svelte'
  import { ui } from './lib/ui.svelte'
  import Detail from './views/Detail.svelte'
  import Home from './views/Home.svelte'
  import Library from './views/Library.svelte'
  import Search from './views/Search.svelte'

  const tabs: { name: Route['name']; label: string; icon: string; to: Route }[] = [
    { name: 'home', label: 'Home', icon: 'home', to: { name: 'home' } },
    { name: 'search', label: 'Search', icon: 'search', to: { name: 'search', q: '', f: 'all' } },
    { name: 'library', label: 'Library', icon: 'library', to: { name: 'library' } },
  ]
  let r = $derived(router.route)

  // Theme the chrome from the current cover (accent for controls, deep tint for backgrounds).
  $effect(() => {
    const thumb = player.current?.thumb
    if (!thumb) return
    let cancelled = false
    dominant(thumb).then((c) => {
      if (cancelled || !c) return
      const p = palette(c), root = document.documentElement.style
      root.setProperty('--accent', p.accent)
      root.setProperty('--tint', p.tint)
      root.setProperty('--tint-soft', p.tintSoft)
      document.querySelector('meta[name="theme-color"]')?.setAttribute('content', ui.full ? p.tint : '#0c0c10')
    })
    return () => { cancelled = true }
  })

  function keys(e: KeyboardEvent) {
    const tag = (e.target as HTMLElement).tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA' || e.metaKey || e.ctrlKey || e.altKey) return
    if (e.key === ' ') { e.preventDefault(); player.toggle() }
    else if (e.key === 'ArrowRight' && e.shiftKey) player.next()
    else if (e.key === 'ArrowLeft' && e.shiftKey) player.prev()
    else if (e.key === 'ArrowRight') player.seek(Math.min(player.duration, player.time + 10))
    else if (e.key === 'ArrowLeft') player.seek(Math.max(0, player.time - 10))
    else if (e.key === '/') { e.preventDefault(); router.go({ name: 'search', q: '', f: 'all' }) }
    else if (e.key === 'l' && player.current) player.like(player.current)
  }
</script>

<svelte:window onkeydown={keys} />

<div class="app" class:has-player={!!player.current} class:queue-open={ui.wide && !!ui.panel}>
  {#if ui.wide}
    <aside class="side">
      <div class="logo"><span class="dot"><Icon name="play" size={16} /></span> Kassetto</div>
      <nav>
        {#each tabs as t}
          <a href="#/" class:on={r.name === t.name} onclick={(e) => { e.preventDefault(); router.go(t.to) }}><Icon name={t.icon} /> {t.label}</a>
        {/each}
      </nav>
      <div class="side-sec">
        <a href="#/mix/mix" onclick={(e) => { e.preventDefault(); router.go({ name: 'detail', kind: 'mix', id: 'mix' }) }}><Icon name="spark" size={20} /> Your mix</a>
        <a href="#/library" onclick={(e) => { e.preventDefault(); router.go({ name: 'library' }) }}><Icon name="liked" size={20} /> Liked songs</a>
        <a href="#/stats" onclick={(e) => { e.preventDefault(); router.go({ name: 'stats' }) }}><Icon name="chart" size={20} /> Your stats</a>
        <a href="#/settings" onclick={(e) => { e.preventDefault(); router.go({ name: 'settings' }) }}><Icon name="gear" size={20} /> Settings</a>
      </div>
    </aside>
  {/if}

  <main>
    {#if r.name === 'home'}<Home />
    {:else if r.name === 'search'}<Search q={r.q} f={r.f} />
    {:else if r.name === 'library'}<Library />
    {:else if r.name === 'stats'}<Stats />
    {:else if r.name === 'settings'}<Settings />
    {:else if r.name === 'detail'}{#key r.kind + r.id}<Detail kind={r.kind} id={r.id} />{/key}
    {/if}
  </main>

  {#if ui.wide && ui.panel}
    <aside class="queue" class:lyrics-panel={ui.panel === 'lyrics'}>
      <div class="qh">
        <div class="ptabs">
          <button class:on={ui.panel === 'queue'} onclick={() => (ui.panel = 'queue')}>Queue</button>
          <button class:on={ui.panel === 'lyrics'} onclick={() => (ui.panel = 'lyrics')}>Lyrics</button>
        </div>
        <button class="icon-btn" aria-label="Close panel" onclick={() => (ui.panel = null)}><Icon name="close" /></button>
      </div>
      {#if ui.panel === 'lyrics'}<Lyrics height="calc(100vh - var(--bar-h) - 80px)" />{:else}<QueueList />{/if}
    </aside>
  {/if}

  {#if ui.wide}
    <PlayerBar />
  {:else}
    <MiniPlayer />
    <nav class="tabbar">
      {#each tabs as t}
        <button class:on={r.name === t.name} onclick={() => router.go(t.to)}><Icon name={t.icon} /><span>{t.label}</span></button>
      {/each}
    </nav>
    <FullPlayer />
  {/if}
  <SongMenu />
  <AddToPlaylist />
  <Toast />
</div>

<style>
  .app { min-height: 100vh; padding-bottom: calc(var(--nav-h) + env(safe-area-inset-bottom) + 12px); }
  .app.has-player { padding-bottom: calc(var(--nav-h) + var(--mini-h) + env(safe-area-inset-bottom) + 20px); }
  main { min-width: 0; padding-top: env(safe-area-inset-top); }

  .tabbar { position: fixed; left: 0; right: 0; bottom: 0; z-index: 35; height: calc(var(--nav-h) + env(safe-area-inset-bottom));
            padding-bottom: env(safe-area-inset-bottom); display: flex;
            background: linear-gradient(to top, var(--bg) 60%, color-mix(in srgb, var(--bg) 85%, transparent)); }
  .tabbar :global(svg) { width: 22px; height: 22px; }
  .tabbar button { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 3px;
                   color: var(--muted); font-size: 11px; font-weight: 600; transition: color .15s; }
  .tabbar button.on { color: var(--fg); }

  @media (min-width: 960px) {
    .app, .app.has-player { display: grid; grid-template-columns: var(--side-w) 1fr; padding-bottom: calc(var(--bar-h) + 8px); }
    .app.queue-open { grid-template-columns: var(--side-w) 1fr 360px; }
    .side { position: sticky; top: 0; height: calc(100vh - var(--bar-h)); padding: 18px 12px; border-right: 1px solid var(--line);
            display: flex; flex-direction: column; gap: 18px; }
    .logo { display: flex; align-items: center; gap: 10px; font-weight: 850; font-size: 20px; padding: 0 10px; letter-spacing: -.02em; }
    .dot { width: 30px; height: 30px; border-radius: 9px; display: grid; place-items: center; background: var(--accent); color: var(--accent-fg); transition: background .6s; }
    nav, .side-sec { display: flex; flex-direction: column; gap: 2px; }
    .side-sec { border-top: 1px solid var(--line); padding-top: 14px; }
    .side a { display: flex; align-items: center; gap: 14px; height: 42px; padding: 0 12px; border-radius: 10px; color: var(--fg-2); font-weight: 600; }
    .side a:hover { background: var(--surface); color: var(--fg); }
    .side a.on { background: var(--surface-2); color: var(--fg); }
    .queue { position: sticky; top: 0; height: calc(100vh - var(--bar-h)); overflow-y: auto; border-left: 1px solid var(--line); padding: 12px 10px; }
    .qh { display: flex; align-items: center; justify-content: space-between; padding: 4px 6px 8px; }
    .ptabs { display: flex; gap: 4px; }
    .ptabs button { height: 32px; padding: 0 14px; border-radius: 16px; font-weight: 650; color: var(--muted); }
    .ptabs button.on { background: var(--surface-2); color: var(--fg); }
    .lyrics-panel { overflow: hidden; background: linear-gradient(to bottom, var(--tint-soft), var(--bg)); }
  }
</style>
