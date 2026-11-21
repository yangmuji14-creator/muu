<script>
  // SettingsShell.svelte — 设置子页统一外壳
  // 顶部标题头 (窄屏带返回箭头; 桌面端分类在侧栏, 不需要返回), 内容滚动区, 可选底部固定保存条。
  import './settings-base.css';
  import { I } from './icons.js';
  import { settingsNav } from '../../lib/settingsNav.svelte.js';

  let { title = '', desc = '', onback, children, footer, showFooter = true, actions } = $props();
</script>

<div class="settings-main">
  <header class="sub-head">
    {#if !settingsNav.inline}
      <button class="icon-btn back-button" type="button" onclick={onback} aria-label="返回">
        {@html `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${I.back}</svg>`}
      </button>
    {/if}
    <div class="sub-title">
      <h1>{title}</h1>
      {#if desc}<p>{desc}</p>{/if}
    </div>
    {#if actions}
      <div class="head-actions">{@render actions?.()}</div>
    {/if}
  </header>

  <div class="sub-body">
    {@render children?.()}

    {#if footer && showFooter}
      <div class="shell-footer glass-3">
        {@render footer?.()}
      </div>
    {/if}
  </div>
</div>

<style>
  .sub-head {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--space-3);
    margin-bottom: var(--space-5);
  }
  .sub-head h1 {
    margin: 0;
    font-size: var(--text-display);
    font-weight: 680;
    letter-spacing: var(--tracking-tight);
    line-height: 1.15;
    overflow-wrap: anywhere;
  }
  .sub-head p {
    margin: var(--space-2) 0 0;
    color: var(--text-2);
    font-size: var(--text-13);
    line-height: 1.55;
  }
  .sub-title { flex: 1 1 180px; min-width: 0; }
  .head-actions { display: flex; align-items: center; flex: 0 1 auto; gap: var(--space-2); max-width: 100%; }
  .back-button { align-self: flex-start; }
  .shell-footer {
    position: sticky;
    z-index: var(--z-sticky);
    bottom: var(--space-2);
    padding: var(--space-3);
    border-radius: var(--radius-lg);
  }
</style>
