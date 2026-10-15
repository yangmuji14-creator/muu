<script>
  // PhoneShell.svelte — 应用外壳
  //
  // 双轨:
  //   窄屏 (<768px): 顶栏 + 内容 + 底部导航
  //   宽屏 (>=768px): 左侧固定侧栏 + 内容区 (全宽铺满, 无居中容器)
  //
  // 可选 panel snippet: 传入时在桌面端作为右侧第三栏, 窄屏端收为底部抽屉。
  // 视觉语言: 暖纸底 + 1px 细线分隔, 无圆角容器/无阴影/无毛玻璃。
  import TabBar from './TabBar.svelte';
  import TopBar from './TopBar.svelte';
  import ThemeToggle from './ThemeToggle.svelte';

  let { active = 'chat', children, sidefoot, panel } = $props();

  let isDesktop = $state(false);
  let sheetOpen = $state(false);

  $effect(() => {
    const mq = window.matchMedia('(min-width: 768px)');
    const apply = () => (isDesktop = mq.matches);
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  });
</script>

<div class="app-shell" class:desktop={isDesktop}>
  {#if isDesktop}
    <aside class="sidebar" aria-label="主导航">
      <div class="sidebar-brand">
        <span class="brand-mark" aria-hidden="true"></span>
        <span class="brand-name">慕</span>
      </div>
      <TabBar {active} vertical />
      <div class="sidebar-foot">
        {#if sidefoot}{@render sidefoot()}{/if}
      </div>
    </aside>

    <section class="main-area">
      {@render children?.()}
    </section>

    {#if panel}
      <aside class="panel-col" aria-label="她的状态">
        {@render panel()}
      </aside>
    {/if}
  {:else}
    <TopBar>
      {#snippet actions()}
        {#if panel}
          <button class="panel-trigger" type="button" onclick={() => (sheetOpen = true)}>状态</button>
        {/if}
        <ThemeToggle />
      {/snippet}
    </TopBar>

    <section class="main-area">
      {@render children?.()}
    </section>

    <TabBar {active} vertical={false} />

    {#if panel && sheetOpen}
      <div class="sheet-scrim" role="presentation" onclick={() => (sheetOpen = false)}></div>
      <div class="sheet" role="dialog" aria-label="她的状态">
        <div class="sheet-head">
          <span class="micro-label">她的状态</span>
          <button class="sheet-close" type="button" aria-label="关闭" onclick={() => (sheetOpen = false)}>
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>
          </button>
        </div>
        <div class="sheet-body">{@render panel()}</div>
      </div>
    {/if}
  {/if}
</div>

<style>
  .app-shell {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100dvh;
    background: var(--bg);
    overflow: hidden;
  }

  .main-area {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overflow-x: hidden;
    -webkit-overflow-scrolling: touch;
    overscroll-behavior: contain;
    background: var(--surface);
    scrollbar-width: thin;
    scrollbar-color: var(--border-strong) transparent;
    /* 两侧都预留滚动条槽位: 无论是否出现滚动条, 内容左右间距始终对称 */
    scrollbar-gutter: stable both-edges;
  }
  .main-area::-webkit-scrollbar {
    width: 10px;
  }
  .main-area::-webkit-scrollbar-thumb {
    background: var(--border-strong);
    border: 3px solid transparent;
    background-clip: padding-box;
    border-radius: var(--radius-full);
  }
  .main-area::-webkit-scrollbar-track {
    background: transparent;
  }

  /* ---- 窄屏: 面板触发按钮 + 底部抽屉 ---- */
  .panel-trigger {
    height: 24px;
    padding: 0 var(--space-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-xs);
    background: transparent;
    color: var(--text-2);
    font-family: inherit;
    font-size: var(--text-xs);
    cursor: pointer;
  }
  .panel-trigger:hover { background: var(--row-hover); }

  .sheet-scrim {
    position: fixed;
    inset: 0;
    z-index: 40;
    background: var(--overlay);
  }
  .sheet {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 41;
    max-height: 68vh;
    display: flex;
    flex-direction: column;
    background: var(--bg);
    border-top: 1px solid var(--border);
  }
  .sheet-head {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-3) var(--space-4);
    border-bottom: 1px solid var(--border);
  }
  .sheet-close {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border: none;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
  }
  .sheet-body {
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }

  /* ---- 桌面端 (>=768px) ---- */
  @media (min-width: 768px) {
    .app-shell.desktop {
      flex-direction: row;
    }

    .sidebar {
      flex: none;
      width: var(--sidebar-w);
      display: flex;
      flex-direction: column;
      background: var(--bg);
      border-right: 1px solid var(--border);
    }
    .sidebar-brand {
      display: flex;
      align-items: center;
      gap: var(--space-2);
      height: var(--topbar-h);
      padding: 0 var(--space-4);
      border-bottom: 1px solid var(--border);
      flex: none;
    }
    .brand-mark {
      flex: none;
      width: 10px;
      height: 10px;
      background: var(--text-1);
    }
    .brand-name {
      font-size: var(--text-sm);
      font-weight: 500;
      letter-spacing: 0.04em;
      color: var(--text-1);
      white-space: nowrap;
    }
    .sidebar-foot {
      margin-top: auto;
      flex: none;
      border-top: 1px solid var(--border);
      padding: var(--space-3) var(--space-4);
      font-size: var(--text-xs);
      color: var(--text-3);
    }

    .panel-col {
      flex: none;
      width: 232px;
      border-left: 1px solid var(--border);
      min-height: 0;
      display: flex;
    }
    .panel-col > :global(*) {
      flex: 1;
      min-width: 0;
    }
  }
</style>
