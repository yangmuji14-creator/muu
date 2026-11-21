<script>
  import { fly } from 'svelte/transition';
  import { getDialog, settleDialog } from '../lib/dialog.svelte.js';
  import { I } from './settings/icons.js';

  const d = $derived(getDialog());

  function confirm(event) {
    event.preventDefault();
    if (!d) return;
    const answer = new FormData(event.currentTarget).get('answer');
    settleDialog(d.type === 'prompt' ? answer ?? '' : true);
  }

  function cancel() {
    if (!d) return;
    settleDialog(d.type === 'prompt' ? null : false);
  }

  function onCancel(event) {
    event.preventDefault();
    cancel();
  }

  function showModal(node) {
    node.showModal();
    node.querySelector('[data-initial-focus]')?.focus();
  }

  function modalTransition(node) {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    return fly(node, { y: reduce ? 0 : 6, duration: reduce ? 0 : 220 });
  }
</script>

{#if d}
  {#key d}
    <dialog
      class="app-modal glass-3"
      aria-label={d.title}
      oncancel={onCancel}
      use:showModal
      transition:modalTransition|global
    >
      <form class="app-modal-body" onsubmit={confirm}>
        <div class="app-modal-head">
          <h2 class="app-modal-title">{d.title}</h2>
          <button class="app-icon-btn" type="button" aria-label="关闭" title="关闭" onclick={cancel}>
            {@html `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${I.close}</svg>`}
          </button>
        </div>

        {#if d.message}
          <p class="app-modal-msg">{d.message}</p>
        {/if}

        {#if d.type === 'prompt'}
          <input
            class="app-input"
            type="text"
            aria-label={d.title}
            value={d.defaultValue || ''}
            placeholder={d.placeholder}
            name="answer"
            data-initial-focus
          />
        {/if}

        <div class="app-modal-actions">
          <button
            class="app-btn app-btn-ghost"
            type="button"
            data-initial-focus={d.type === 'confirm' && d.danger ? '' : undefined}
            onclick={cancel}
          >{d.cancelText || '取消'}</button>
          <button
            class="app-btn {d.danger ? 'app-btn-danger' : 'app-btn-primary'}"
            type="submit"
            data-initial-focus={d.type === 'confirm' && !d.danger ? '' : undefined}
          >{d.confirmText || '确定'}</button>
        </div>
      </form>
    </dialog>
  {/key}
{/if}

<style>
  .app-modal {
    position: fixed;
    inset: 0;
    width: min(420px, calc(100% - 2 * var(--space-4)));
    max-height: calc(100dvh - 2 * var(--space-4));
    margin: auto;
    padding: var(--space-5);
    overflow: auto;
    border: 0;
    border-radius: var(--radius-xl);
    color: var(--text-1);
  }

  .app-modal-body {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  .app-modal::backdrop {
    background: var(--scrim);
    animation: fadeIn var(--transition-slow);
  }

  .app-modal-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }

  .app-modal-title {
    margin: 0;
    font-size: var(--text-xl);
    font-weight: 680;
    line-height: var(--leading-tight);
    overflow-wrap: anywhere;
  }

  .app-icon-btn {
    display: inline-grid;
    flex: none;
    place-items: center;
    width: 36px;
    height: 36px;
    padding: 0;
    border: 0;
    border-radius: var(--radius-pill);
    background: var(--field-fill);
    color: var(--text-2);
    cursor: pointer;
  }

  .app-icon-btn:hover { background: var(--row-hover); color: var(--text-1); }

  .app-modal-msg {
    margin: 0;
    color: var(--text-2);
    font-size: var(--text-15);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .app-input {
    width: 100%;
    min-height: 44px;
    padding: var(--space-2) var(--space-3);
    border: 0;
    border-radius: var(--radius-sm);
    background: var(--field-fill);
    color: var(--text-1);
    font: inherit;
    font-size: var(--text-base);
  }

  .app-input:focus { background: var(--field-fill-focus); box-shadow: var(--focus-ring); }
  .app-input::placeholder { color: var(--input-placeholder); }

  .app-modal-actions {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: var(--space-2);
    padding-top: var(--space-1);
  }

  .app-btn {
    min-height: 40px;
    padding: var(--space-1) var(--space-4);
    border: 0;
    border-radius: var(--radius-pill);
    font: inherit;
    font-size: var(--text-sm);
    font-weight: 650;
    cursor: pointer;
  }

  .app-btn-primary {
    background: var(--accent);
    color: var(--on-accent);
    box-shadow: var(--shadow-accent);
  }

  .app-btn-primary:hover { background: var(--accent-hover); }
  .app-btn-ghost { background: var(--field-fill); color: var(--text-2); }
  .app-btn-ghost:hover { background: var(--row-hover); color: var(--text-1); }
  .app-btn-danger { background: var(--error); color: var(--on-error); }
  .app-btn-danger:hover { filter: brightness(1.08); }
</style>
