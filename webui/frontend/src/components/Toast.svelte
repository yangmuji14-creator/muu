<script>
  import { fly } from 'svelte/transition';

  let { toast = null } = $props();

  function toastTransition(node) {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    return fly(node, { y: reduce ? 0 : 6, duration: reduce ? 0 : 200 });
  }
</script>

{#if toast}
  <div class="toast-zone" role="status" aria-live="polite">
    {#key toast}
      <div
        class="toast glass-3 {toast.type === 'success' ? 'is-success' : toast.type === 'error' ? 'is-error' : 'is-info'}"
        transition:toastTransition|global
      >
        <span class="toast-mark" aria-hidden="true">
          {toast.type === 'success' ? '✓' : toast.type === 'error' ? '!' : 'i'}
        </span>
        <span class="toast-text">
          <span class="sr-only">{toast.type === 'success' ? '成功：' : toast.type === 'error' ? '错误：' : '提示：'}</span>{toast.text}
        </span>
      </div>
    {/key}
  </div>
{/if}

<style>
  .toast-zone {
    position: fixed;
    inset-inline: 0;
    bottom: calc(var(--tabbar-h) + var(--space-5) + env(safe-area-inset-bottom, 0px));
    z-index: var(--z-toast);
    display: grid;
    justify-items: center;
    margin-inline: var(--space-4);
    pointer-events: none;
  }

  .toast {
    --toast-tone: var(--info);
    --toast-tint: var(--info-soft);
    display: flex;
    align-items: center;
    gap: var(--space-2);
    max-width: min(440px, 100%);
    padding: var(--space-2) var(--space-4) var(--space-2) var(--space-2);
    border-radius: var(--radius-lg);
    color: var(--text-1);
    font-size: var(--text-13);
    font-weight: 550;
    overflow-wrap: anywhere;
  }

  .toast-mark {
    display: grid;
    flex: none;
    place-items: center;
    width: 25px;
    height: 25px;
    border-radius: var(--radius-pill);
    background: var(--toast-tint);
    color: var(--toast-tone);
    font-weight: 700;
    line-height: 1;
  }

  .toast.is-success { --toast-tone: var(--success); --toast-tint: var(--success-soft); }
  .toast.is-error { --toast-tone: var(--error); --toast-tint: var(--error-soft); }
</style>
