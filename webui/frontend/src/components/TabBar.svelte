<script>
  // TabBar.svelte — 主导航 (侧栏竖排 / 底部横排 两种形态)
  //
  // 竖排(桌面)时「设置」是**可展开**的: 选中设置后, 其分类直接缩进展开在下方,
  // 不再另开一栏, 也不再需要"进子页 → 返回"。
  import { navTabs, TAB_LABELS, goTab, navigate, route } from '../lib/router.js';
  import { layout } from '../lib/layout.svelte.js';
  import { SETTINGS_GROUPS, SETTINGS_KEYS } from '../lib/settingsNav.svelte.js';

  // rail: 桌面端「图标轨」形态 —— 只留图标与 tooltip, 把宽度让给正文。
  //   一级导航从「带文字的竖排列表」收成 64px 的形状后, 聊天页才有空间
  //   把会话列表与正文同时铺开; 文字标签在 title / aria-label 里仍然完整。
  let { active = 'chat', vertical = false, rail = false } = $props();

  // 当前设置子页; 未指定时高亮第一个分类 (与 SettingsPage 的默认落地一致)
  let activeSub = $derived(
    Array.isArray($route.sub) && $route.sub.length > 0
      ? $route.sub[0]
      : (active === 'settings' ? SETTINGS_KEYS[0] : null),
  );

  const iconFor = {
    today: (color) => `
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="16" rx="1"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>`,
    chat: (color) => `
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>`,
    contacts: (color) => `
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>`,
    discover: (color) => `
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/></svg>`,
    memory: (color) => `
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16M4 12h16M4 18h10"/></svg>`,
    settings: (color) => `
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`,
  };
</script>

<nav class="tabbar {vertical ? 'vertical' : 'horizontal glass-3'}" class:rail={rail && vertical} aria-label="主导航">
  {#each navTabs(layout.mode) as tab}
    {@const selected = active === tab}
    {@const color = 'currentColor'}
    <button
      class="tab {selected ? 'is-active' : ''}"
      type="button"
      onclick={() => goTab(tab)}
      aria-current={selected ? 'page' : undefined}
      aria-expanded={vertical && tab === 'settings' ? selected : undefined}
      title={TAB_LABELS[tab]}
      aria-label={rail && vertical ? TAB_LABELS[tab] : undefined}
    >
      <span class="tab-icon" aria-hidden="true">{@html iconFor[tab](color)}</span>
      <span class="tab-label">{TAB_LABELS[tab]}</span>
    </button>

    {#if vertical && !rail && tab === 'settings' && selected}
      <div class="sub-tabs">
        {#each SETTINGS_GROUPS as g, gi}
          {#if gi > 0}<div class="sub-sep" aria-hidden="true"></div>{/if}
          {#each g.items as item}
            <button
              class="sub-tab {activeSub === item.key ? 'on' : ''}"
              type="button"
              onclick={() => navigate(`settings/${item.key}`)}
              aria-current={activeSub === item.key ? 'page' : undefined}
            >{item.title}</button>
          {/each}
        {/each}
      </div>
    {/if}
  {/each}
</nav>

<style>
  .tabbar { display: flex; }

  .horizontal {
    position: relative;
    z-index: var(--z-sticky);
    flex: none;
    align-items: stretch;
    min-height: var(--tabbar-h);
    margin: var(--space-1) var(--space-3) max(var(--space-2), env(safe-area-inset-bottom, 0px));
    padding: var(--space-1);
    border-radius: var(--radius-pill);
  }

  .tab,
  .sub-tab {
    position: relative;
    display: flex;
    align-items: center;
    border: 0;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--tab-inactive);
    font: inherit;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }

  .tab:hover,
  .sub-tab:hover { background: var(--row-hover); color: var(--tab-hover); }

  .tab.is-active,
  .sub-tab.on {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 650;
  }

  .horizontal .tab {
    flex: 1;
    flex-direction: column;
    justify-content: center;
    gap: var(--optical-3);
    min-width: 0;
    min-height: 44px;
    padding: 0 var(--space-1);
    border-radius: var(--radius-pill);
    font-size: var(--text-2xs);
    line-height: 1.2;
  }

  .tab-icon {
    display: inline-flex;
    flex: none;
    transition: transform var(--transition-spring), filter var(--transition-fast);
  }

  .horizontal .tab.is-active .tab-icon {
    transform: scale(1.12);
    filter: drop-shadow(0 2px 5px var(--accent-glow));
  }

  .tab-label { white-space: nowrap; }

  .vertical {
    flex: 1;
    flex-direction: column;
    gap: var(--space-1);
    min-height: 0;
    padding: var(--space-2);
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--border-strong) transparent;
  }

  .vertical .tab {
    flex: none;
    justify-content: flex-start;
    gap: var(--optical-10);
    min-height: 42px;
    padding: 0 var(--space-4);
    font-size: var(--text-sm);
  }

  .vertical .is-active::before,
  .sub-tab.on::before {
    position: absolute;
    inset-block: 29%;
    inset-inline-start: 4px;
    width: 3px;
    border-radius: var(--radius-pill);
    background: currentColor;
    content: '';
  }

  .sub-tabs {
    display: flex;
    flex-direction: column;
    gap: var(--optical-2);
    padding: 0 0 var(--space-2) var(--space-3);
  }

  .sub-tab {
    min-height: 32px;
    padding: var(--space-1) var(--space-3);
    font-size: var(--text-xs);
    text-align: left;
  }

  .sub-sep {
    height: 1px;
    margin: var(--space-1) var(--space-3);
    background: var(--surface-divider);
  }

  .vertical.rail .tab { justify-content: center; gap: 0; padding: 0; }
  .vertical.rail .tab-label { display: none; }
</style>
