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

  // 页面切换过渡: 只做淡入 (去掉位移与模糊, 更快更干脆)
  function pageIn() {
    return {
      duration: 140,
      easing: (t) => 1 - Math.pow(1 - t, 3),
      css: (t) => `opacity: ${t};`,
    };
  }
</script>

<svelte:head><title>慕</title></svelte:head>

{#if !ready}
  <div class="boot">
    <div class="boot-logo" aria-hidden="true"></div>
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
        <div class="page-enter" transition:pageIn>
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
    <PhoneShell active={activePage} panel={layout.mode === 'panel' ? statePanel : undefined}>
      {@render pageBody()}
    </PhoneShell>
  {/if}

  <AppDialog />
{/if}

<style>
  .page-enter {
    /* 必须是确定高度: 子页面 (.chat-page 等) 用 height:100% 撑满,
       而百分比高度无法从父级的 min-height 解析 (曾导致页面塌缩成内容高度) */
    height: 100%;
    min-height: 0;
    will-change: opacity;
  }
  /* 常驻挂载但当前不可见的页面（聊天页切走时用） */
  .page-hidden {
    display: none;
  }
  .boot {
    min-height: 100dvh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--space-4);
    color: var(--text-2);
    font-size: var(--text-sm);
  }
  .boot-logo {
    width: 26px;
    height: 26px;
    background: var(--text-1);
    animation: boot-pulse 1.2s var(--ease-in-out) infinite;
  }
  .boot-text {
    letter-spacing: 0.08em;
    font-size: var(--text-xs);
    color: var(--text-3);
  }
  @keyframes boot-pulse {
    0%, 100% { opacity: 0.25; }
    50% { opacity: 1; }
  }
</style>
