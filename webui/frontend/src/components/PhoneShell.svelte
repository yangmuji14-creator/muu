<script>
  // PhoneShell.svelte — 应用外壳
  //
  // 双轨:
  //   窄屏 (<768px): 顶栏 + 内容 + 底部导航
  //   宽屏 (>=768px): 左侧固定侧栏 + 内容区 (全宽铺满, 无居中容器)
  //
  // 可选 panel snippet: 传入时在桌面端作为右侧第三栏, 窄屏端收为底部抽屉。
  //
  import TabBar from './TabBar.svelte';
  import TopBar from './TopBar.svelte';
  import ThemeToggle from './ThemeToggle.svelte';
  import { shell, closePanelSheet } from '../lib/shell.svelte.js';
  import { layout } from '../lib/layout.svelte.js';

  // multiCol: 当前内容是否为「多列内嵌」布局 (聊天页)。
  //   聊天页的 conv-panel / chat-stage 各自铺玻璃, 外壳必须让成透明,
  //   否则两层玻璃叠加会把氛围色吃掉。
  //   这里用显式 prop 而不是 :has(.chat-page) —— 聊天页是常驻挂载的
  //   (切走只加 .page-hidden), 用 :has 会让外壳在**所有**页面都放弃玻璃,
  //   于是通讯录/设置页直接露出原始氛围层, 深色下是一整片高饱和紫。
  let { active = 'chat', children, sidefoot, panel, multiCol = false } = $props();

  let isDesktop = $state(false);
  let wide = $state(false);

  $effect(() => {
    const mq = window.matchMedia('(min-width: 768px)');
    const apply = () => (isDesktop = mq.matches);
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  });

  // 宽屏阈值: 只有真正宽到能把三栏都放下时, 右侧面板才默认展开。
  //   1440 下三栏 = 200 导航 + 256 会话 + 272 状态 = 728, 正文只剩 692 ——
  //   正文是产品的主体, 不该被两块辅助栏挤到不足一半。所以默认收起,
  //   只在右缘留一枚 28px 竖标签, 需要时一键展开。
  const WIDE_MIN = 1500;
  $effect(() => {
    const mq = window.matchMedia(`(min-width: ${WIDE_MIN}px)`);
    const apply = () => (wide = mq.matches);
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  });

  // 中等宽度 (1024–1499): 左侧导航收成图标轨, 把宽度让给聊天正文。
  let railMode = $state(false);
  $effect(() => {
    const mq = window.matchMedia('(min-width: 1024px)');
    const apply = () => (railMode = !mq.matches);
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  });

  // 右侧第三栏的「能否停靠」阈值。1520 以下三栏会挤掉正文：
  //   1520 - 200(导航) - 256(会话) - 272(状态) = 792 正文，刚好够读；
  //   再窄就必须收起状态面板，否则正文降到 500 以下，读一行要断三次。
  const DOCK_MIN = 1520;
  let canDock = $state(false);
  $effect(() => {
    const mq = window.matchMedia(`(min-width: ${DOCK_MIN}px)`);
    const apply = () => (canDock = mq.matches);
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  });

  // 用户手动开合优先于断点默认值; 跨断点时回到默认 (初始渲染不算跨断点)。
  const PANEL_KEY = 'cc-panel-open';
  function readPanelPref() {
    try {
      const v = localStorage.getItem(PANEL_KEY);
      return v === null ? null : v === '1';
    } catch {
      return null;
    }
  }
  let userToggle = $state(readPanelPref());
  // canDock 是硬闸门：窗口不够宽时，无论上次记住的是什么都不停靠，
  // 否则 900px 下三栏并排会把正文压成一条缝。
  let panelOpen = $derived(canDock && (userToggle ?? wide));

  function openPanel() {
    if (canDock) userToggle = true;
    else shell.panelSheetOpen = true;
  }

  function closeSheetOnEscape(event) {
    // 有模态 <dialog> 打开时，Esc 归它处理：原生 dialog 的 cancel 不会把
    // keydown 标成 defaultPrevented，所以必须显式查一次，否则「确认删除」
    // 弹窗按 Esc 会把它背后的状态面板也一起关掉。
    if (
      event.key === 'Escape'
      && !event.defaultPrevented
      && !document.querySelector('dialog[open]')
      && shell.panelSheetOpen
    ) {
      closePanelSheet();
    }
  }

  let prevWide = null;
  $effect(() => {
    const w = wide;
    if (prevWide !== null && prevWide !== w) userToggle = null;
    prevWide = w;
  });

  $effect(() => {
    if (userToggle === null) return;
    try {
      localStorage.setItem(PANEL_KEY, userToggle ? '1' : '0');
    } catch {
      /* 隐私模式下 localStorage 可能不可用, 忽略 */
    }
  });

  // 把「外壳有没有状态面板」告诉页面: 窄屏下聊天页据此决定顶栏要不要给
  // 「状态」按钮 —— 没有面板时不该出现一个点了没反应的按钮。
  $effect(() => {
    shell.panelAvailable = Boolean(panel) && layout.mode === 'panel';
    return () => {
      shell.panelAvailable = false;
    };
  });

  $effect(() => {
    if (!panel || (isDesktop && panelOpen)) closePanelSheet();
  });
</script>

<svelte:window onkeydown={closeSheetOnEscape} />

<div class="app-shell" class:desktop={isDesktop} class:multi-col={multiCol} class:rail={railMode} class:panel-closed={!panelOpen}>
  {#if isDesktop}
    <aside class="sidebar glass-1" aria-label="主导航">
      <div class="sidebar-brand">
        <span class="brand-mark" aria-hidden="true"></span>
        <span class="brand-name">慕</span>
      </div>
      <TabBar {active} vertical rail={railMode} />
      {#if sidefoot}<div class="sidebar-foot">{@render sidefoot()}</div>{/if}
    </aside>

    <section class="main-frame">
      {#if !multiCol}<div class="main-material glass-2" aria-hidden="true"></div>{/if}
      <div class="main-area">{@render children?.()}</div>
    </section>

    {#if panel}
      {#if panelOpen}
        <aside class="panel-col glass-1" aria-label="她的状态">
          <div class="panel-header">
            <span class="panel-title">她的状态</span>
            <button class="panel-collapse" type="button" aria-label="收起状态面板" title="收起" onclick={() => (userToggle = false)}>
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>
            </button>
          </div>
          {@render panel()}
        </aside>
      {:else}
        <button class="panel-rail-tab" type="button" aria-label="展开状态面板" aria-expanded={shell.panelSheetOpen} title="她的状态" onclick={openPanel}>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M15 6l-6 6 6 6"/></svg>
          <span class="rail-tab-text">状态</span>
        </button>
      {/if}
    {/if}
  {:else}
    <TopBar>
      {#snippet brand()}
        {#if shell.chatHead}
          <button
            class="head-btn"
            type="button"
            aria-label="会话列表"
            title="会话列表"
            onclick={() => shell.chatHead?.openList?.()}
          >
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18M3 12h18M3 18h18"/></svg>
          </button>
          <span class="head-title">{shell.chatHead.title}</span>
        {:else}
          <span class="brand-mark" aria-hidden="true"></span>
          <span class="brand-name">慕</span>
        {/if}
      {/snippet}
      {#snippet actions()}
        {#if shell.chatHead}
          <button
            class="head-btn"
            type="button"
            aria-label="重命名会话"
            title="重命名"
            disabled={!shell.chatHead.canRename}
            onclick={() => shell.chatHead?.rename?.()}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
          </button>
        {/if}
        {#if panel}
          <button class="panel-trigger" type="button" aria-expanded={shell.panelSheetOpen} onclick={openPanel}>状态</button>
        {/if}
        <ThemeToggle />
      {/snippet}
    </TopBar>

    <section class="main-frame">
      {#if !multiCol}<div class="main-material glass-2" aria-hidden="true"></div>{/if}
      <div class="main-area">{@render children?.()}</div>
    </section>

    <TabBar {active} vertical={false} />
  {/if}

  {#if panel && shell.panelSheetOpen && !panelOpen}
    <div class="sheet-scrim scrim-layer" role="presentation" onclick={closePanelSheet}></div>
    <div class="sheet glass-3" class:side-sheet={isDesktop} role="dialog" aria-label="她的状态">
      <div class="panel-header">
        <span class="panel-title">她的状态</span>
        <button class="sheet-close" type="button" aria-label="关闭" onclick={closePanelSheet}>
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>
        </button>
      </div>
      <div class="sheet-body">{@render panel()}</div>
    </div>
  {/if}
</div>

<style>
  .app-shell {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100dvh;
    overflow: hidden;
  }

  .main-frame {
    position: relative;
    flex: 1;
    min-width: 0;
    min-height: 0;
  }

  .main-material {
    position: absolute;
    inset: 0;
    pointer-events: none;
  }

  .main-area {
    position: relative;
    height: 100%;
    overflow: hidden auto;
    overscroll-behavior: contain;
    scrollbar-gutter: stable both-edges;
    scrollbar-width: thin;
    scrollbar-color: var(--border-strong) transparent;
  }

  .multi-col .main-area {
    overflow: hidden;
    scrollbar-gutter: auto;
  }

  .head-btn,
  .panel-trigger,
  .panel-collapse,
  .sheet-close {
    display: inline-flex;
    flex: none;
    align-items: center;
    justify-content: center;
    min-width: 36px;
    min-height: 36px;
    padding: 0;
    border: 0;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-2);
    cursor: pointer;
  }

  .head-btn:hover:enabled,
  .panel-collapse:hover,
  .sheet-close:hover {
    background: var(--row-hover);
    color: var(--text-1);
  }

  .head-btn:disabled {
    opacity: 0.42;
    cursor: default;
  }

  .head-title {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    color: var(--text-1);
    font-size: var(--text-15);
    font-weight: 650;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .panel-trigger {
    padding-inline: var(--space-3);
    border-radius: var(--radius-pill);
    background: var(--field-fill);
    font-family: inherit;
    font-size: var(--text-xs);
    font-weight: 600;
  }

  .panel-trigger:hover,
  .panel-trigger[aria-expanded='true'] {
    background: var(--accent-soft);
    color: var(--accent);
  }

  .sheet-scrim {
    position: fixed;
    inset: 0;
    z-index: var(--z-scrim);
    animation: fadeIn var(--transition);
  }

  .sheet {
    position: fixed;
    inset-inline: var(--space-3);
    bottom: max(var(--space-3), env(safe-area-inset-bottom, 0px));
    z-index: var(--z-drawer);
    display: flex;
    flex-direction: column;
    max-height: 72dvh;
    margin-inline: auto;
    max-width: 520px;
    border-radius: var(--radius-xl);
    animation: sheet-enter var(--transition-snap);
  }

  .sheet.side-sheet {
    inset-block: var(--space-3);
    inset-inline: auto var(--space-3);
    max-height: none;
    width: min(340px, 90vw);
    animation-name: slideInRight;
  }

  @keyframes sheet-enter {
    from { opacity: 0; transform: translateY(var(--motion-offset)); }
    to { opacity: 1; transform: translateY(0); }
  }

  .panel-header {
    display: flex;
    flex: none;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-2) 0 var(--space-4);
  }

  .panel-title {
    font-size: var(--text-sm);
    font-weight: 650;
    color: var(--text-1);
  }

  .sheet-body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
    border-radius: 0 0 var(--radius-xl) var(--radius-xl);
  }

  .sheet-body :global(.state-panel) {
    height: auto;
    overflow: visible;
  }

  .brand-name {
    color: var(--text-1);
    font-size: var(--text-base);
    font-weight: 700;
    white-space: nowrap;
  }

  @media (min-width: 768px) {
    .app-shell.desktop {
      flex-direction: row;
      gap: var(--optical-10);
      padding: var(--space-3);
    }

    .main-area,
    .main-material {
      border-radius: var(--radius-xl);
    }

    .multi-col .main-area :global(.chat-body) {
      gap: var(--optical-10);
    }

    .multi-col .main-area :global(.conv-panel) {
      border-right: 0;
      border-radius: var(--radius-lg);
    }

    .multi-col .main-area :global(.chat-stage) {
      overflow: hidden;
      border-radius: var(--radius-xl);
      box-shadow: var(--surface-stage-shadow);
    }

    .sidebar,
    .panel-col {
      display: flex;
      flex: none;
      flex-direction: column;
      min-height: 0;
      border-radius: var(--radius-lg);
    }

    .sidebar { width: var(--sidebar-w); }
    .panel-col { width: var(--panel-w); }

    .sidebar-brand {
      display: flex;
      flex: none;
      align-items: center;
      gap: var(--space-3);
      min-height: calc(var(--topbar-h) + var(--space-3));
      padding-inline: var(--space-4);
    }

    .sidebar-foot {
      flex: none;
      margin-top: auto;
      padding: var(--space-3) var(--space-4) var(--space-4);
      color: var(--text-2);
      font-size: var(--text-xs);
    }

    .panel-col :global(.state-panel) {
      flex: 1;
      min-height: 0;
    }

    .panel-rail-tab {
      display: flex;
      flex: none;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      align-self: center;
      gap: var(--space-2);
      width: 36px;
      min-height: 80px;
      padding: var(--space-3) 0;
      border: 0;
      border-radius: var(--radius-pill);
      background: var(--col-nav-solid);
      color: var(--text-2);
      font: inherit;
      font-size: var(--text-xs);
      cursor: pointer;
    }

    .panel-rail-tab:hover,
    .panel-rail-tab[aria-expanded='true'] {
      background: var(--accent-soft);
      color: var(--accent);
    }

    .rail-tab-text { writing-mode: vertical-rl; }

    .app-shell.rail .sidebar { width: var(--sidebar-rail); }
    .app-shell.rail .sidebar-brand { justify-content: center; padding: 0; }
    .app-shell.rail .brand-name,
    .app-shell.rail .sidebar-foot { display: none; }
  }
</style>
