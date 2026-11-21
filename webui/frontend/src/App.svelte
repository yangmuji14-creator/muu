<script>
  // App.svelte — 应用外壳
  //
  // 职责:
  //   - 启动 hash 路由监听 (startRouter)
  //   - 按布局模式选择外壳:
  //       immersive -> ImmersiveShell (细状态条 + 抽屉, 无侧栏)
  //       panel     -> PhoneShell + 右侧内心面板
  //       today     -> PhoneShell, 落地页为「今天」
  //   - 按顶层 page 渲染对应页面组件
  import PhoneShell from './components/PhoneShell.svelte';
  import ImmersiveShell from './components/layout/ImmersiveShell.svelte';
  import StatePanel from './components/layout/StatePanel.svelte';
  import AppDialog from './components/AppDialog.svelte';
  import { route, startRouter } from './lib/router.js';
  import { layout } from './lib/layout.svelte.js';
  // 副作用导入：单例构造时读取已保存的背景并应用到页面
  import './lib/backgroundManager.js';

  import TodayPage from './pages/TodayPage.svelte';
  import ChatPage from './pages/ChatPage.svelte';
  import ContactsPage from './pages/ContactsPage.svelte';
  import DiscoverPage from './pages/DiscoverPage.svelte';
  import MemoryPage from './pages/MemoryPage.svelte';
  import SettingsPage from './pages/SettingsPage.svelte';

  // 顶层 page -> 组件映射
  const pageMap = {
    today: TodayPage,
    chat: ChatPage,
    contacts: ContactsPage,
    discover: DiscoverPage,
    memory: MemoryPage,
    settings: SettingsPage,
  };

  let ready = $state(false);

  $effect(() => {
    startRouter();
    // 微任务后标记就绪, 确保 route 已初始化
    queueMicrotask(() => (ready = true));
  });

  let activePage = $derived($route.page ?? 'chat');
  // 大写变量名: Svelte 5 runes 将其视为动态组件引用，随 route 变化重新渲染
  let Current = $derived(pageMap[$route.page] ?? ChatPage);

</script>

<svelte:head><title>慕</title></svelte:head>

{#if !ready}
  <div class="boot">
    <div class="brand-mark boot-logo" aria-hidden="true"></div>
    <span class="boot-text">引导中…</span>
  </div>
{:else}
  {#snippet pageBody()}
    <!-- 聊天页常驻挂载：切到其他 Tab 也不卸载，正在生成的回复/思考不中断。
         非激活时 display:none（在流里但不可见）。 -->
    <div class="page-enter" class:page-hidden={activePage !== 'chat'}>
      <ChatPage />
    </div>
    {#if activePage !== 'chat'}
      {#key activePage}
        <div class="page-enter page-arrive">
          <Current></Current>
        </div>
      {/key}
    {/if}
  {/snippet}

  {#snippet statePanel()}
    <StatePanel />
  {/snippet}

  {#if layout.mode === 'immersive'}
    <ImmersiveShell active={activePage}>
      {@render pageBody()}
    </ImmersiveShell>
  {:else}
    <PhoneShell
      active={activePage}
      panel={layout.mode === 'panel' && activePage === 'chat' ? statePanel : undefined}
      multiCol={activePage === 'chat'}
    >
      {@render pageBody()}
    </PhoneShell>
  {/if}

  <AppDialog />
{/if}

<style>
  .page-enter {
    height: 100%;
    min-height: 0;
  }

  .page-hidden { display: none; }
  .page-arrive { animation: page-enter var(--transition-snap); }

  @keyframes page-enter {
    from { opacity: 0; transform: translateY(var(--motion-offset)); }
    to { opacity: 1; transform: translateY(0); }
  }

  :global(.brand-mark) {
    position: relative;
    flex: none;
    width: var(--brand-size, 28px);
    height: var(--brand-size, 28px);
    border-radius: var(--radius-avatar);
    background: var(--accent-gradient);
    box-shadow: inset 0 1px 0 var(--floating-highlight), var(--shadow-accent);
    color: var(--on-accent);
  }

  :global(.brand-mark)::before,
  :global(.brand-mark)::after {
    position: absolute;
    content: '';
    background: currentColor;
    clip-path: polygon(50% 0, 62% 38%, 100% 50%, 62% 62%, 50% 100%, 38% 62%, 0 50%, 38% 38%);
  }

  :global(.brand-mark)::before { inset: 24% 30% 29% 23%; }
  :global(.brand-mark)::after { inset: 20% 17% 62% 65%; opacity: 0.68; }

  .boot {
    display: grid;
    align-content: center;
    justify-items: center;
    gap: var(--space-3);
    min-height: 100dvh;
    color: var(--text-2);
  }

  .boot-logo {
    --brand-size: 42px;
    animation: pulse 1.25s var(--ease-in-out) infinite;
  }

  .boot-text { font-size: var(--text-xs); }

  @media (prefers-reduced-motion: reduce) {
    .boot-logo { animation: none; }
    /* 页面切换的入场动画也一并关掉：--dur-3 归零只让时长变 0，
       仍是「一帧闪」；显式 animation: none 更干净。 */
    .page-arrive { animation: none; }
  }
</style>
