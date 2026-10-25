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
</script>

<div class="app-shell" class:desktop={isDesktop} class:multi-col={multiCol} class:rail={railMode} class:panel-closed={!panelOpen}>
  {#if isDesktop}
    <aside class="sidebar" aria-label="主导航">
      <div class="sidebar-brand">
        <span class="brand-mark" aria-hidden="true"></span>
        <span class="brand-name">慕</span>
      </div>
      <TabBar {active} vertical rail={railMode} />
      <div class="sidebar-foot">
        {#if sidefoot}{@render sidefoot()}{/if}
      </div>
    </aside>

    <section class="main-area">
      {@render children?.()}
    </section>

    {#if panel}
      {#if panelOpen}
        <aside class="panel-col" aria-label="她的状态">
          <button class="panel-collapse" type="button" aria-label="收起状态面板" title="收起" onclick={() => (userToggle = false)}>
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>
          </button>
          {@render panel()}
        </aside>
      {:else}
        <button class="panel-rail-tab" type="button" aria-label="展开状态面板" title="她的状态" onclick={() => (userToggle = true)}>
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
          <button class="panel-trigger" type="button" onclick={() => (shell.panelSheetOpen = true)}>状态</button>
        {/if}
        <ThemeToggle />
      {/snippet}
    </TopBar>

    <section class="main-area">
      {@render children?.()}
    </section>

    <TabBar {active} vertical={false} />

    {#if panel && shell.panelSheetOpen}
      <div class="sheet-scrim" role="presentation" onclick={closePanelSheet}></div>
      <div class="sheet" role="dialog" aria-label="她的状态">
        <div class="sheet-head">
          <span class="micro-label">她的状态</span>
          <button class="sheet-close" type="button" aria-label="关闭" onclick={closePanelSheet}>
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
        /* 列级玻璃: 正文是全页最亮的一档 (浅色) / 最暗的一档 (深色),
           明度阶梯的锚点就在这一块。
           v7: 正文是内容层, 按 HIG 用 standard material 的 thin 档,
           不用 Liquid Glass —— Liquid Glass 属于控件与导航层,
           铺在正文上会让"什么是可点的"失去区分。 */
        background-color: var(--glass-content);
        background-image: var(--mat-rim), var(--mat-veil), var(--mat-grain);
        background-size: 100% var(--mat-rim-h), 100% 100%, 128px 128px;
        background-position: top left, center, center;
        background-repeat: no-repeat, no-repeat, repeat;
        background-clip: padding-box;
        -webkit-backdrop-filter: blur(var(--mat-blur-thin)) saturate(var(--mat-sat-thin))
          brightness(var(--mat-bri-thin));
        backdrop-filter: blur(var(--mat-blur-thin)) saturate(var(--mat-sat-thin))
          brightness(var(--mat-bri-thin));
      }
      /* 聊天页是唯一的「多列内嵌」布局: .conv-panel 与 .chat-stage 都长在
         .main-area 里面。外壳若继续铺玻璃, 会话列就会变成
         「main-area 玻璃 × conv-panel 玻璃」两层叠加, 等效 alpha 从 .58 涨到
         .82 (深色 .68 → .90) —— 氛围色被彻底吃掉, 实测会话列 spread 只剩 25,
         这就是"配色明明调了却看不出蓝紫"的结构性根因。
         所以聊天页把外壳让成透明, 玻璃改由两列各自承担, 每列只有一层。 */
      .app-shell.multi-col .main-area {
        background-color: transparent;
        background-image: none;
        -webkit-backdrop-filter: none;
        backdrop-filter: none;
        /* 聊天页自己管理滚动 (.msgs 是滚动容器), 外壳不该再留滚动条槽位 ——
           两侧各 10px 的 gutter 会把正文无端缩窄 20px。 */
        overflow: hidden;
        scrollbar-gutter: auto;
      }
    }
  @media (prefers-reduced-transparency: reduce) {
    .main-area {
      background: var(--col-content-solid);
      -webkit-backdrop-filter: none;
      backdrop-filter: none;
    }
  }
  /* 聊天页自己管理滚动 (.msgs 是滚动容器), 外壳不该再留滚动条槽位 ——
     两侧各 10px 的 gutter 会把正文无端缩窄 20px。这条必须无条件生效,
     不能只在 @supports 里写一遍。 */
  .app-shell.multi-col .main-area {
    overflow: hidden;
    scrollbar-gutter: auto;
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

  /* ---- 窄屏: 页面接管顶栏时的按钮与标题 ---- */
  .head-btn {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    padding: 0;
    border: none;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-2);
    cursor: pointer;
    transition: background var(--transition), color var(--transition);
  }
  .head-btn:hover {
    background: var(--row-hover);
    color: var(--text-1);
  }
  .head-title {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--text-13);
    font-weight: 500;
    color: var(--text-2);
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
        /* 列级玻璃: 侧栏是四列里最暗的一档, 主动退到氛围层后面。
           之前和 conv-panel / panel-col 共用 --glass-1, 三列同进同退,
           所以四列永远只有 4 个明度点的差 —— 看不出层次。

           v7 (Apple 材质): 列是**内容层**, 按 HIG 该用 standard material
           而不是 Liquid Glass。所以这里不再是"一个 rgba + 一条斜向白斑",
           而是五层结构: 色膜 + 厚度渐变 + 颗粒 + 1px 镜面边 + 双 hairline 边。
           玻璃的"材质感"全部来自后四层, 色膜只负责决定压到多亮。 */
        background-color: var(--glass-nav);
        background-image: var(--mat-rim), var(--mat-veil), var(--mat-grain);
        background-size: 100% var(--mat-rim-h), 100% 100%, 128px 128px;
        background-position: top left, center, center;
        background-repeat: no-repeat, no-repeat, repeat;
        background-clip: padding-box;
        -webkit-backdrop-filter: blur(var(--mat-blur-thin)) saturate(var(--mat-sat-thin))
          brightness(var(--mat-bri-thin));
        backdrop-filter: blur(var(--mat-blur-thin)) saturate(var(--mat-sat-thin))
          brightness(var(--mat-bri-thin));
        box-shadow: var(--glass-highlight);
      }
    }
    @media (prefers-reduced-transparency: reduce) {
      .sidebar {
        /* 兜底不能用 --bg: 那会把四列压回同一个色, 层次当场消失。
           用各列自己的实色, 减弱透明模式下仍然读得出四层。 */
        background: var(--col-nav-solid);
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
      position: relative;
      background: var(--bg);
    }
    @supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
      .panel-col {
        /* 列级玻璃: 右栏是次级信息, 明度夹在侧栏与会话列表之间 ——
           必须比正文暗 (浅色) 才不会抢走视觉重心。
           v7: 与 .sidebar 同一套五层材质, 只有色膜 (--glass-aside) 不同。
           材质参数刻意一致 —— 同一次交互里相邻的两列如果模糊半径不同,
           边框的锐度就会不一致, 读起来像两块贴在一起的不同的板。 */
        background-color: var(--glass-aside);
        background-image: var(--mat-rim), var(--mat-veil), var(--mat-grain);
        background-size: 100% var(--mat-rim-h), 100% 100%, 128px 128px;
        background-position: top left, center, center;
        background-repeat: no-repeat, no-repeat, repeat;
        background-clip: padding-box;
        -webkit-backdrop-filter: blur(var(--mat-blur-thin)) saturate(var(--mat-sat-thin))
          brightness(var(--mat-bri-thin));
        backdrop-filter: blur(var(--mat-blur-thin)) saturate(var(--mat-sat-thin))
          brightness(var(--mat-bri-thin));
        box-shadow: var(--glass-highlight);
      }
    }
    @media (prefers-reduced-transparency: reduce) {
      .panel-col {
        background: var(--col-aside-solid);
        -webkit-backdrop-filter: none;
        backdrop-filter: none;
      }
    }
    .panel-col > :global(:not(.panel-collapse)) {
      flex: 1;
      min-width: 0;
    }

    /* ---- 右侧状态面板的开合 ----
       面板是辅助信息, 必须能一键让位给正文。收起后不留一条空栏,
       只在右缘留一枚 28px 竖标签, 需要时再展开。 */
    .panel-collapse {
      position: absolute;
      top: var(--space-3);
      right: var(--space-2);
      z-index: var(--z-sticky);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 24px;
      height: 24px;
      padding: 0;
      border: none;
      border-radius: var(--radius-xs);
      background: transparent;
      color: var(--text-3);
      cursor: pointer;
      transition: background var(--transition), color var(--transition);
    }
    .panel-collapse:hover {
      background: var(--row-hover);
      color: var(--text-1);
    }
    .panel-rail-tab {
      flex: none;
      width: 28px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: var(--space-2);
      padding: var(--space-4) 0;
      border: none;
      border-left: 1px solid var(--glass-border-2);
      /* 透明底在最右缘会直接露出 ambient-b 色团(实测 rel 30.7,
         比正文亮三倍), 读成一条紫色胶带。铺一层列玻璃把它压回 chrome 层。 */
      background: var(--glass-nav);
      color: var(--text-2);
      font-family: inherit;
      font-size: var(--text-2xs);
      letter-spacing: 0.18em;
      cursor: pointer;
      transition: background var(--transition), color var(--transition);
    }
    @supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
      .panel-rail-tab {
        background: var(--col-nav-solid);
        -webkit-backdrop-filter: blur(var(--mat-blur-thin)) saturate(var(--mat-sat-thin));
        backdrop-filter: blur(var(--mat-blur-thin)) saturate(var(--mat-sat-thin));
      }
    }
    .panel-rail-tab:hover {
      background: var(--row-hover);
      color: var(--accent);
    }
    .rail-tab-text {
      writing-mode: vertical-rl;
      text-transform: uppercase;
    }

    /* ---- 图标轨: 1024px 以下侧栏只留图标 ----
       一级导航一旦占满 200px, 会话列和正文就没有余量了。
       这一档把侧栏压到 64px, 名字收进 title, 选中态换成图标底色。 */
    .app-shell.rail .sidebar {
      width: var(--sidebar-rail);
    }
    .app-shell.rail .sidebar-brand {
      justify-content: center;
      padding: 0;
    }
    .app-shell.rail .brand-name {
      display: none;
    }
    .app-shell.rail .sidebar-foot {
      display: none;
    }
  }
</style>
