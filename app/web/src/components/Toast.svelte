<script lang="ts">
  import { ui } from '../lib/ui.svelte'
</script>

<div class="wrap" aria-live="polite">
  {#if ui.toast}
    {#key ui.toast.id}<div class="toast">{ui.toast.msg}</div>{/key}
  {/if}
</div>

<style>
  .wrap { position: fixed; left: 0; right: 0; z-index: 90; display: flex; justify-content: center; pointer-events: none;
          bottom: calc(var(--nav-h) + var(--mini-h) + env(safe-area-inset-bottom) + 18px); }
  @media (min-width: 960px) { .wrap { bottom: calc(var(--bar-h) + 16px); } }
  .toast { background: var(--fg); color: var(--bg); padding: 10px 16px; border-radius: 10px; font-size: 14px; font-weight: 550;
           max-width: 90vw; box-shadow: var(--shadow); animation: in .22s var(--ease); }
  @keyframes in { from { opacity: 0; transform: translateY(8px); } }
</style>
