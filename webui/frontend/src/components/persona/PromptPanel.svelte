<script>
  import './editor.css';
  // PromptPanel.svelte — 可复用折叠面板 (高级 Prompt 分层用)
  //
  // Props:
  //   title    - 面板标题
  //   hint     - 展开后顶部说明文字 (可选)
  //   tier     - 1 = 常用「微调」档, 2 = 次要「深度设置」档 (弱化视觉)
  //   badge    - 右侧计数徽标 (可选)
  //   open     - 双向展开状态 (默认收起)
  //   children - 默认内容 snippet
  //   actions  - 底部操作 snippet (可选, 如保存按钮)
  let {
    title,
    hint = '',
    tier = 1,
    badge = '',
    open = $bindable(false),
    children,
    actions,
  } = $props();
</script>

<div class="panel persona-surface tier-{tier}">
  <button
    class="persona-disclosure"
    type="button"
    aria-expanded={open}
    onclick={() => (open = !open)}
  >
    <span class="p-title">{title}</span>
    {#if badge}
      <span class="persona-disclosure-meta">{badge}</span>
    {/if}
    <svg
      class="persona-chevron {open ? 'is-open' : ''}"
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    ><polyline points="6 9 12 15 18 9"/></svg>
  </button>

  {#if open}
    <div class="p-body persona-reveal">
      {#if hint}
        <p class="persona-hint">{hint}</p>
      {/if}
      <div class="p-content">
        {@render children?.()}
      </div>
      {#if actions}
        <div class="p-actions">
          {@render actions()}
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .panel.tier-2 { background: var(--surface-2); box-shadow: none; }
  .p-title { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .p-body, .p-content { display: grid; gap: var(--space-3); }
  .p-body { padding: var(--space-3); }
  .p-actions { display: flex; justify-content: flex-end; }
</style>
