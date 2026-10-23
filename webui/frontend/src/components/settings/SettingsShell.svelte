<script>
  // SettingsShell.svelte — 设置子页统一外壳
  // 顶部标题头 (窄屏带返回箭头; 桌面端分类在侧栏, 不需要返回), 内容滚动区, 可选底部固定保存条。
  import './settings-base.css';
  import { I } from './icons.js';
  import { settingsNav } from '../../lib/settingsNav.svelte.js';

  let { title = '', desc = '', onback, children, footer, actions } = $props();
</script>

<div class="settings-main">
  <header class="sub-head back-head">
    {#if !settingsNav.inline}
      <button class="icon-btn" type="button" onclick={onback} aria-label="返回">
        {@html `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${I.back}</svg>`}
      </button>
    {/if}
    <div class="sub-title">
      <h3>{title}</h3>
      {#if desc}<p>{desc}</p>{/if}
    </div>
    {#if actions}
      <div class="head-actions">{@render actions?.()}</div>
    {/if}
  </header>

  <div class="sub-body">
    {@render children?.()}

    {#if footer}
      <div class="shell-footer">
        {@render footer?.()}
      </div>
    {/if}
  </div>
</div>

<style>
  /* 子页页头: 与页面层 (通讯录 / 发现 / 记忆 / 今天) 共用同一套层级 ——
     11px 微标签在上, 26px 主标题在下, 说明 13px。
     原 h3 是 18px/700, 在 860px 宽的设置区里既不够大也不够轻,
     读起来像「正文加粗」而不是「页面标题」。 */
  .sub-head {
    display: flex;
    align-items: flex-end;
    gap: var(--space-3);
    padding: 0 0 var(--space-4);
    margin-bottom: var(--space-4);
    border-bottom: 1px solid var(--border-strong);
  }
  .sub-head h3 {
    margin: 0;
    font-size: var(--text-display);
    font-weight: 600;
    letter-spacing: var(--tracking-tight);
    line-height: 1.12;
    color: var(--text-1);
  }
  .sub-head p { margin: var(--optical-6) 0 0; font-size: var(--text-13); line-height: 1.65; color: var(--text-2); max-width: 56ch; }
  .sub-title { min-width: 0; flex: 1; }
  .head-actions { flex: none; display: flex; align-items: center; gap: var(--space-2); padding-bottom: var(--optical-2); }

  /* 设置页底部操作条: sticky chrome, 与 .save-bar / 顶栏同一档玻璃。
     不透明底色会把滚动到它下面的字段硬切一刀, 玻璃让"内容还在继续"
     这件事可见 —— 这是玻璃在本项目里最实质的用途, 不是装饰。 */
  .shell-footer {
    position: sticky;
    bottom: 0;
    z-index: var(--z-sticky);
    background: var(--surface);
    padding: var(--space-3) 0;
    margin-top: var(--space-1);
    border-top: 1px solid var(--glass-border-2);
  }
  @supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
    .shell-footer {
      background: var(--glass-1);
      -webkit-backdrop-filter: blur(var(--glass-blur-1)) saturate(var(--glass-sat-1));
      backdrop-filter: blur(var(--glass-blur-1)) saturate(var(--glass-sat-1));
    }
  }
  @media (prefers-reduced-transparency: reduce) {
    .shell-footer {
      background: var(--surface);
      -webkit-backdrop-filter: none;
      backdrop-filter: none;
    }
  }
</style>
