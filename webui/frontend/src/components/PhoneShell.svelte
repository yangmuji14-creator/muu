<script>
  // PhoneShell.svelte — 应用外壳
  //
  // 双轨:
  //   窄屏 (<768px): 顶栏 + 内容 + 底部导航
  //   宽屏 (>=768px): 左侧固定侧栏 + 内容区 (全宽铺满, 无居中容器)
  //
  // 可选 panel snippet: 传入时在桌面端作为右侧第三栏, 窄屏端收为底部抽屉。
  //
  // 视觉语言 (v2): 暖纸底 + 1px 细线分隔 + 四档玻璃材质。
  //   玻璃只用于「浮在内容之上」的表面 (顶栏/底栏/侧栏/抽屉/弹窗),
  //   内容区仍是实心 --surface —— 正文永不放在玻璃上。
  //   每处玻璃都带 @supports 不透明兜底与 prefers-reduced-transparency 退让。
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
    /* 透明而非 --bg: 氛围层铺在 body::before (z-index:-1),
       外壳必须让出来, 否则玻璃底下永远是一块纯色 —— 那正是
       "磨砂玻璃做了却看不见"的根因。 */
    background: transparent;
    overflow: hidden;
  }

  .main-area {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overflow-x: hidden;
    -webkit-overflow-scrolling: touch;
    overscroll-behavior: contain;
    /* 内容区用 --glass-content 而非不透明的 --surface:
       让氛围层以极淡的方式透上来, 页面才有"纸下有光"的层次。
       不支持 backdrop-filter 时退回 --surface (见下方 @supports)。 */
    background: var(--surface);
    scrollbar-width: thin;
    scrollbar-color: var(--border-strong) transparent;
    /* 两侧都预留滚动条槽位: 无论是否出现滚动条, 内容左右间距始终对称 */
    scrollbar-gutter: stable both-edges;
  }
  @supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
    .main-area {
      background-color: var(--glass-content);
      background-image: var(--glass-sheen);
      -webkit-backdrop-filter: blur(14px) saturate(1.08);
      backdrop-filter: blur(14px) saturate(1.08);
    }
  }
  @media (prefers-reduced-transparency: reduce) {
    .main-area {
      background: var(--surface);
      -webkit-backdrop-filter: none;
      backdrop-filter: none;
    }
  }
  .main-area::-webkit-scrollbar {
    width: 8px;
  }
  .main-area::-webkit-scrollbar-thumb {
    background: var(--border-strong);
    border: 2px solid transparent;
    background-clip: padding-box;
    border-radius: var(--radius-full);
  }
  .main-area::-webkit-scrollbar-thumb:hover {
    background: var(--text-3);
    border: 2px solid transparent;
    background-clip: padding-box;
  }
  .main-area::-webkit-scrollbar-track {
    background: transparent;
  }

  /* ---- 窄屏: 面板触发按钮 + 底部抽屉 ---- */
  .panel-trigger {
    height: 26px;
    padding: 0 var(--space-3);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-xs);
    background: transparent;
    color: var(--text-2);
    font-family: inherit;
    font-size: var(--text-xs);
    letter-spacing: 0.02em;
    cursor: pointer;
    transition: background var(--transition), color var(--transition), border-color var(--transition);
  }
  .panel-trigger:hover {
    background: var(--accent-wash);
    border-color: var(--accent-line);
    color: var(--accent);
  }

  .sheet-scrim {
    position: fixed;
    inset: 0;
    z-index: var(--z-scrim);
    background: var(--glass-0);
  }
  @supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
    .sheet-scrim {
      -webkit-backdrop-filter: blur(var(--glass-blur-0));
      backdrop-filter: blur(var(--glass-blur-0));
    }
  }
  /* 底部 sheet: glass-2 档。与 .imm-drawer 同级 —— 两者都是"盖在页面上
     但不离开页面"的表面, 必须用同一种材质语言, 否则窄屏下两种浮层
     看起来像来自两个产品。 */
  .sheet {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: var(--z-drawer);
    max-height: 68vh;
    display: flex;
    flex-direction: column;
    background: var(--surface);
    border-top: 1px solid var(--glass-border-2);
    border-radius: var(--radius-lg) var(--radius-lg) 0 0;
    box-shadow: var(--shadow-4);
  }
  @supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
    .sheet {
      background: var(--glass-2);
      -webkit-backdrop-filter: blur(var(--glass-blur-2)) saturate(var(--glass-sat-2));
      backdrop-filter: blur(var(--glass-blur-2)) saturate(var(--glass-sat-2));
      box-shadow: var(--glass-highlight), var(--shadow-4);
    }
  }
  @media (prefers-reduced-transparency: reduce) {
    .sheet {
      background: var(--surface);
      -webkit-backdrop-filter: none;
      backdrop-filter: none;
    }
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
    width: 26px;
    height: 26px;
    border: none;
    border-radius: var(--radius-xs);
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
    transition: background var(--transition), color var(--transition);
  }
  .sheet-close:hover { background: var(--row-hover); color: var(--text-1); }
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

    /* 侧栏: glass-1 (chrome 档)。桌面端侧栏是"常驻但非主体"的一列,
       用最薄玻璃让主内容区的暖纸底透一点过来, 两列才像同一张纸上的
       两个区域, 而不是被一条硬线拼起来的两块。
       注意: 侧栏底下是 --bg 而非图片, 玻璃在这里主要靠"内高光 + 细结构线"
       表达层次, 模糊本身几乎不可见 —— 这是刻意的, 避免侧栏看起来发灰。 */
    .sidebar {
      flex: none;
      width: var(--sidebar-w);
      display: flex;
      flex-direction: column;
      background: var(--bg);
      border-right: 1px solid var(--glass-border-2);
    }
    @supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
      .sidebar {
        background-color: var(--glass-1);
        background-image: var(--glass-sheen);
        -webkit-backdrop-filter: blur(var(--glass-blur-1)) saturate(var(--glass-sat-1));
        backdrop-filter: blur(var(--glass-blur-1)) saturate(var(--glass-sat-1));
        box-shadow: var(--glass-highlight);
      }
    }
    @media (prefers-reduced-transparency: reduce) {
      .sidebar {
        background: var(--bg);
        -webkit-backdrop-filter: none;
        backdrop-filter: none;
      }
    }
    /* 品牌区: 原来是「10px 黑方块 + 14px 慕」，高度只有 44px，
       在 196px 宽的侧栏顶部看起来像一行没加载完的占位。
       现在把方块做成「双色方形标」（黑块右下角挂 4px 冷蓝角），
       并给名字配一行 11px 等宽副标，让顶部成为一个真正的标识区。 */
    .sidebar-brand {
      display: flex;
      align-items: center;
      gap: var(--optical-9);
      height: calc(var(--topbar-h) + 8px);
      padding: 0 var(--space-4);
      border-bottom: 1px solid var(--border);
      flex: none;
    }
    .brand-mark {
      position: relative;
      flex: none;
      width: 11px;
      height: 11px;
      background: var(--text-1);
    }
    .brand-mark::after {
      content: '';
      position: absolute;
      right: -2px;
      bottom: -2px;
      width: 5px;
      height: 5px;
      background: var(--accent);
    }
    .brand-name {
      font-size: var(--text-13);
      font-weight: 600;
      letter-spacing: 0.12em;
      color: var(--text-1);
      white-space: nowrap;
    }
    .sidebar-foot {
      margin-top: auto;
      flex: none;
      border-top: 1px solid var(--border);
      padding: var(--space-3) var(--space-4) var(--space-4);
      font-size: var(--text-2xs);
      letter-spacing: 0.02em;
      line-height: 1.6;
      color: var(--text-3);
    }

    .panel-col {
      flex: none;
      width: var(--panel-w);
      border-left: 1px solid var(--glass-border-2);
      min-height: 0;
      display: flex;
      background: var(--bg);
    }
    @supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
      .panel-col {
        background-color: var(--glass-1);
        background-image: var(--glass-sheen);
        -webkit-backdrop-filter: blur(var(--glass-blur-1)) saturate(var(--glass-sat-1));
        backdrop-filter: blur(var(--glass-blur-1)) saturate(var(--glass-sat-1));
        box-shadow: var(--glass-highlight);
      }
    }
    @media (prefers-reduced-transparency: reduce) {
      .panel-col {
        background: var(--bg);
        -webkit-backdrop-filter: none;
        backdrop-filter: none;
      }
    }
    .panel-col > :global(*) {
      flex: 1;
      min-width: 0;
    }
  }
</style>
