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
  /* 空状态原来是一个「虚线圆角框 + 居中图标 + 居中文字」的居中方团,
     放在已经去框化的设置区块里像一块补丁。
     现在改为左对齐的「竖线锚点 + 图标 + 文案」: 竖线把视线钉在左边,
     图标缩到 22px 只作为符号, 文案左起 —— 和页面级空状态 (.pg-empty)
     用同一套语言, 全站空状态终于长得一致。 */
  .empty-state {
    display: flex;
    align-items: flex-start;
    gap: var(--space-3);
    text-align: left;
    padding: var(--space-4) 0 var(--space-4) var(--space-4);
    border-left: 2px solid var(--border-strong);
  }
  .empty-state.compact {
    padding: var(--space-3) 0 var(--space-3) var(--space-3);
    gap: var(--space-2);
  }
  .empty-icon {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    color: var(--text-3);
  }
  .empty-copy {
    display: flex;
    flex-direction: column;
    gap: var(--optical-3);
    min-width: 0;
  }
  .empty-title {
    margin: 0;
    font-size: var(--text-13);
    font-weight: 600;
    letter-spacing: var(--tracking-tight);
    color: var(--text-1);
  }
  .empty-desc {
    margin: 0;
    max-width: 52ch;
    font-size: var(--text-xs);
    color: var(--text-2);
    line-height: 1.7;
  }
  .empty-action { margin-top: var(--space-2); }
</style>
