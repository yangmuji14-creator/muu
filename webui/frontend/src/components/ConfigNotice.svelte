<script>
  // ConfigNotice.svelte — 配置引导提示组件 (纯展示 + 单一"去设置"动作)
  //
  // 用于聊天页识别"模型/服务商未配置或出错"的场景，主动引导用户去配置:
  //   - variant='banner' : 输入框上方的全宽警示条 (未配置守卫)
  //   - variant='card'   : 取代普通 AI 气泡的"配置提示卡" (后端回配置错误文案时)
  //
  // 零依赖; 所有颜色/间距/圆角/字号均取自 tokens.css 语义变量, 不发明新 token。
  let {
    variant = 'banner', // 'banner' | 'card'
    tone = 'warning',   // 'warning' | 'error' | 'info'
    icon = 'alert',
    title = '',
    text = '',
    actionLabel = '',
    onAction = null,
    checking = false,   // true -> 显示"检测中"态 (banner 守卫专用)
    foot = null,        // 可选尾巴内容 (snippet, 用于在 banner 末尾追加如"重新检测"按钮)
  } = $props();

  // 内联 SVG 图标 (Lucide 风格, 零外部依赖)
  const ICONS = {
    alert: `
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
    alertCircle: `
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
    info: `
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`,
    key: `
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21 2-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0 3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>`,
  };
</script>

<div class="notice n-{variant} n-tone-{tone}" class:is-checking={checking} role="alert">
  <span class="n-icon" aria-hidden="true">
    {#if checking}
      <span class="n-spin" aria-hidden="true"></span>
    {:else}
      {@html ICONS[icon] || ICONS.alert}
    {/if}
  </span>

  <div class="n-body">
    {#if title}<div class="n-title">{title}</div>{/if}
    {#if text}<div class="n-text">{text}</div>{/if}
  </div>

  {#if actionLabel && onAction}
    <button class="n-action" type="button" onclick={onAction}>{actionLabel}</button>
  {/if}

  {#if foot}{@render foot()}{/if}
</div>

<style>
  .notice {
    --notice-color: var(--warning);
    --notice-fill: var(--warning-soft);
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2) var(--space-3);
    padding: var(--space-3);
    border-radius: var(--radius-md);
    background: var(--notice-fill);
    color: var(--text-1);
  }

  .n-tone-error { --notice-color: var(--error); --notice-fill: var(--error-soft); }
  .n-tone-info { --notice-color: var(--info); --notice-fill: var(--info-soft); }

  .n-banner { width: 100%; }

  .n-card {
    max-width: min(340px, 100%);
    border-end-start-radius: var(--bubble-radius-sm);
  }

  .n-icon {
    display: grid;
    flex: none;
    place-items: center;
    width: 33px;
    height: 33px;
    border-radius: var(--radius-sm);
    background: var(--surface);
    color: var(--notice-color);
  }

  .n-body { flex: 1 1 10rem; min-width: 0; }

  .n-title {
    color: var(--text-1);
    font-size: var(--text-sm);
    font-weight: 650;
  }

  .n-text {
    color: var(--text-2);
    font-size: var(--text-xs);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .n-action {
    flex: none;
    min-height: 36px;
    padding: var(--space-1) var(--space-3);
    border: 0;
    border-radius: var(--radius-pill);
    background: var(--accent);
    color: var(--on-accent);
    font-size: var(--text-xs);
    font-weight: 650;
    cursor: pointer;
  }

  .n-action:hover { background: var(--accent-hover); }
  .is-checking .n-icon { color: var(--text-2); }

  .n-spin {
    width: 16px;
    height: 16px;
    border: 2px solid var(--border);
    border-top-color: currentColor;
    border-radius: var(--radius-pill);
    animation: n-rotate 0.8s linear infinite;
  }

  @keyframes n-rotate { to { transform: rotate(360deg); } }

  @media (prefers-reduced-motion: reduce) {
    .n-spin { animation: none; }
  }
</style>
