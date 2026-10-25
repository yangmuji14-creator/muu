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
      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="16" rx="1"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>`,
    chat: (color) => `
      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>`,
    contacts: (color) => `
      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>`,
    discover: (color) => `
      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/></svg>`,
    memory: (color) => `
      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16M4 12h16M4 18h10"/></svg>`,
    settings: (color) => `
      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`,
  };
</script>

<nav class="tabbar {vertical ? 'vertical' : 'horizontal'}" class:rail={rail && vertical} aria-label="主导航">
  {#each navTabs(layout.mode) as tab}
    {@const selected = active === tab}
    {@const color = selected ? 'var(--accent)' : 'var(--tab-inactive)'}
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
  .tabbar {
    display: flex;
  }

  /* ---- 移动端: 底部横排 ----
     glass-1 (chrome 档): 底栏在滚动内容之上浮动时, 让内容从底下
     透出来比一条实心色带更能表达"我还在这一页"。
     兜底为不透明 --surface, 见下方 @supports。 */
  .horizontal {
    flex-direction: row;
    align-items: stretch;
    flex: none;
    height: calc(var(--tabbar-h) + env(safe-area-inset-bottom, 0px));
    padding: 0 var(--space-2);
    padding-bottom: env(safe-area-inset-bottom, 0px);
    background: var(--surface);
    border-top: 1px solid var(--glass-border-2);
  }
  @supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
    .horizontal {
      background: var(--glass-1);
      -webkit-backdrop-filter: blur(var(--glass-blur-1)) saturate(var(--glass-sat-1));
      backdrop-filter: blur(var(--glass-blur-1)) saturate(var(--glass-sat-1));
    }
  }
  @media (prefers-reduced-transparency: reduce) {
    .horizontal {
      background: var(--surface);
      -webkit-backdrop-filter: none;
      backdrop-filter: none;
    }
  }
  .horizontal .tab {
    flex: 1;
    min-width: 0;
    flex-direction: column;
    justify-content: center;
    gap: var(--optical-3);
    padding: 0;
    border-radius: 0;
  }

  /* ---- 桌面端: 侧栏竖排 ---- */
  .vertical {
    flex-direction: column;
    padding: var(--space-2) 0;
    width: 100%;
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--border-strong) transparent;
  }
  .vertical::-webkit-scrollbar { width: 8px; }
  .vertical::-webkit-scrollbar-thumb {
    background: var(--border-strong);
    border: 2px solid transparent;
    background-clip: padding-box;
    border-radius: var(--radius-full);
  }
  .vertical .tab {
    flex-direction: row;
    justify-content: flex-start;
    gap: var(--optical-10);
    height: 32px;
    flex: none;
    padding: 0 var(--space-4);
    font-size: var(--text-13);
    letter-spacing: 0.005em;
    border-left: 2px solid transparent;
  }

  .tab {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    border: none;
    border-radius: 0;
    background: transparent;
    color: var(--tab-inactive);
    font-size: var(--text-xs);
    font-weight: 400;
    line-height: 1.2;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    transition: color var(--transition), background var(--transition), border-color var(--transition);
  }
  .tab:hover {
    color: var(--tab-hover);
    background: var(--row-hover);
  }
  .tab:active { background: var(--row-active); }

  /* 选中态: 冷蓝文字 + 冷蓝左标 + 一层极淡冷蓝底。
     原来是 surface-2（暖灰），和 hover 行几乎同色，扫视时找不到
     「我现在在哪」；换成 accent-wash 之后选中项在暖色侧栏里是唯一
     一块偏蓝的，眼睛一眼落上去。 */
  .tab.is-active {
    color: var(--accent);
    font-weight: 500;
  }
  .vertical .tab.is-active {
    background: var(--accent-wash);
    border-left-color: var(--accent);
  }
  .vertical .tab.is-active .tab-icon { color: var(--accent); }

  .tab-icon {
    display: inline-flex;
    flex: none;
  }
  .tab-label {
    white-space: nowrap;
  }

  /* ---- 设置分类 (展开式, 缩进在「设置」下方) ---- */
  .sub-tabs {
    display: flex;
    flex-direction: column;
    padding: var(--space-1) 0 var(--space-2);
  }
  /* 缩进对齐上一级图标的右缘: 16(pad) + 15(icon) + 10(gap) = 41px */
  .sub-tab {
    display: flex;
    align-items: center;
    height: 27px;
    padding: 0 var(--space-4) 0 41px;
    border: none;
    border-left: 2px solid transparent;
    background: transparent;
    font-family: inherit;
    font-size: var(--text-xs);
    letter-spacing: 0.01em;
    color: var(--text-2);
    text-align: left;
    cursor: pointer;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    transition: color var(--transition), background var(--transition), border-color var(--transition);
  }
  .sub-tab:hover { background: var(--row-hover); color: var(--text-1); }
  .sub-tab.on {
    color: var(--accent);
    font-weight: 500;
    border-left-color: var(--accent-line);
  }
  .sub-sep {
    height: 1px;
    margin: var(--space-1) var(--space-4) var(--space-1) 41px;
    background: var(--border);
  }

  /* ---- 图标轨 (rail) ----
     桌面侧栏收到 64px 宽: 只留图标, 文字与设置分类全部收起。
     选中态从「左侧竖线 + 淡底」换成「圆角方块底」—— 竖线在窄轨上
     贴着屏幕边缘, 反而看不清。 */
  .vertical.rail {
    padding: var(--space-2);
    gap: var(--optical-2);
    align-items: stretch;
  }
  .vertical.rail .tab {
    justify-content: center;
    height: 38px;
    padding: 0;
    border-left: none;
    border-radius: var(--radius-sm);
    gap: 0;
  }
  .vertical.rail .tab-label {
    display: none;
  }
  .vertical.rail .tab:hover {
    background: var(--row-hover);
  }
  .vertical.rail .tab.is-active {
    background: var(--accent-wash);
  }
</style>
