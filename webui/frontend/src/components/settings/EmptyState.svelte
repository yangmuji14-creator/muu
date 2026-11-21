<script>
  // EmptyState.svelte — 精致空状态 (图标 + 标题 + 描述 + 可选主操作)
  // 使用 tokens 的 --empty-* 语义变量 + 一个 svg 图标 (通过 icon name 引用)。
  import './settings-base.css';
  import { I } from './icons.js';

  let { icon = 'puzzle', title = '', desc = '', children, compact = false } = $props();
</script>

<div class="empty-state" class:compact>
  <div class="empty-icon" aria-hidden="true">
    {@html `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${I[icon] || ''}</svg>`}
  </div>
  <div class="empty-copy">
    {#if title}<p class="empty-title">{title}</p>{/if}
    {#if desc}<p class="empty-desc">{desc}</p>{/if}
    {#if children}
      <div class="empty-action">{@render children?.()}</div>
    {/if}
  </div>
</div>

<style>
  .empty-state {
    display: flex;
    align-items: flex-start;
    gap: var(--space-3);
    padding: var(--space-4);
    border-radius: var(--radius-lg);
    background: var(--field-fill);
  }
  .empty-state.compact { padding: var(--space-3); }
  .empty-icon {
    flex: none;
    display: grid;
    place-items: center;
    width: 38px;
    height: 38px;
    border-radius: var(--radius-md);
    background: var(--surface);
    color: var(--accent-strong);
  }
  .empty-copy { display: grid; align-self: center; gap: var(--space-1); min-width: 0; }
  .empty-title { margin: 0; color: var(--text-1); font-size: var(--text-13); font-weight: 650; overflow-wrap: anywhere; }
  .empty-desc { margin: 0; max-width: 54ch; color: var(--text-2); font-size: var(--text-xs); line-height: 1.55; overflow-wrap: anywhere; }
  .empty-action { margin-top: var(--space-2); }
</style>
