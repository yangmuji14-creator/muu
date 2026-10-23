<script>
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

<div class="panel tier-{tier}">
  <button
    class="p-head"
    type="button"
    aria-expanded={open}
    onclick={() => (open = !open)}
  >
    <span class="p-title">{title}</span>
    {#if badge}
      <span class="p-badge">{badge}</span>
    {/if}
    <svg
      class="p-arrow {open ? 'is-open' : ''}"
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
    <div class="p-body">
      {#if hint}
        <p class="p-hint">{hint}</p>
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
  /* PromptPanel 与 PersonaAdvanced / PersonaCard 共用同一套分区语法:
     不做盒子, 只做「一道更重的横线 + 11px 微标签标题」。
     原来这里是一张独立白卡, 和上下两张人设卡叠在一起就成了盒套盒。 */
  .panel {
    background: transparent;
    border: none;
    border-top: 1px solid var(--border-strong);
    border-radius: 0;
    box-shadow: none;
    overflow: visible;
    margin-top: var(--space-2);
  }

  /* 深度设置档: 视觉弱化(更灰/次要) —— 连线也降一档 */
  .panel.tier-2 {
    background: transparent;
    border-top-color: var(--border);
    box-shadow: none;
  }

  .p-head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    width: 100%;
    padding: var(--space-4) 0 var(--space-3);
    background: transparent;
    border: none;
    color: var(--text-3);
    font-size: var(--text-2xs);
    font-weight: 500;
    letter-spacing: var(--tracking-wider);
    cursor: pointer;
    transition: color var(--transition), border-color var(--transition);
  }
  .p-head:hover {
    background: transparent;
    color: var(--text-1);
  }
  .tier-2 .p-head {
    color: var(--text-3);
    font-weight: 500;
  }
  .p-title {
    flex: 1;
    text-align: left;
  }
  .p-badge {
    font-size: var(--text-2xs);
    letter-spacing: var(--tracking-wide);
    color: var(--text-3);
    background: var(--surface-2);
    border-radius: var(--radius-xs);
    padding: var(--hair) var(--optical-7);
    font-variant-numeric: tabular-nums;
  }
  .tier-2 .p-badge {
    background: var(--surface-2);
  }
  .p-arrow {
    transition: transform var(--transition);
    color: var(--text-3);
  }
  .p-arrow.is-open {
    transform: rotate(180deg);
  }

  .p-body {
    padding: 0 0 var(--space-5) 0;
    border-top: none;
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .p-hint {
    margin: 0;
    font-size: var(--text-2xs);
    line-height: 1.7;
    color: var(--text-3);
  }
  .p-content {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .p-actions {
    display: flex;
    justify-content: flex-end;
    padding-top: var(--space-3);
    border-top: 1px solid var(--border);
    margin-top: 0;
  }
</style>
