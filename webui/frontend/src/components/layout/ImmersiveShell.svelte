<script>
  // ImmersiveShell.svelte — 沉浸外壳 (概念2)
  //
  // 没有侧栏、没有底部导航: 顶部一条 44px 细状态条, 内容占满整屏。
  // 导航与状态全部收进右侧抽屉。
  import { navTabs, TAB_LABELS, goTab, navigate, route } from '../../lib/router.js';
  import { layout } from '../../lib/layout.svelte.js';
  import { session, stateRevision, ensureActiveConversation } from '../../lib/session.svelte.js';
  import { fetchState } from '../../lib/stateApi.js';
  import { SETTINGS_GROUPS, SETTINGS_KEYS } from '../../lib/settingsNav.svelte.js';
  import StatePanel from './StatePanel.svelte';

  let { active = 'chat', children } = $props();

  let open = $state(false);
  let bar = $state(null);

  // 当前设置子页 (与 SettingsPage 的默认落地保持一致)
  let activeSub = $derived(
    Array.isArray($route.sub) && $route.sub.length > 0
      ? $route.sub[0]
      : (active === 'settings' ? SETTINGS_KEYS[0] : null),
  );

  $effect(() => {
    const cid = session.conversationId;
    const rev = stateRevision.n; // 依赖刷新信号：对话结束后重新拉取
    void rev;
    let alive = true;
    (async () => {
      const effective = cid || (await ensureActiveConversation());
      if (!alive || !effective) return;
      try {
        const d = await fetchState(effective);
        if (alive) bar = d;
      } catch {
        if (alive) bar = null;
      }
    })();
    return () => {
      alive = false;
    };
  });

  let tabs = $derived(navTabs(layout.mode));
  let name = $derived(bar?.persona_name || session.personaName || '');
  let moodLabel = $derived(bar?.mood?.label || '');
  let level = $derived(bar?.affection ? Math.round(bar.affection.level) : null);

  function pick(tab) {
    open = false;
    goTab(tab);
  }

  // 设置分类: 抽屉里也必须能切, 否则桌面宽度下 SettingsPage 走 inline 模式
  // (无索引页 / 无返回箭头), 会锁死在第一个分类出不来。
  function pickSub(key) {
    open = false;
    navigate(`settings/${key}`);
  }
</script>

<div class="imm">
  <header class="imm-bar glass-1">
    <span class="imm-dot" aria-hidden="true"></span>
    {#if name}<span class="imm-name">{name}</span>{/if}
    {#if moodLabel}<span class="imm-meta imm-mood">{moodLabel}</span>{/if}
    {#if level !== null}<span class="imm-meta">亲密 <span class="mono">{level}</span></span>{/if}
    <button class="imm-btn" type="button" aria-label="打开侧栏" aria-expanded={open} onclick={() => (open = !open)}>
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h16"/></svg>
    </button>
  </header>

  <div class="imm-frame">
    {#if active !== 'chat'}<div class="imm-material glass-2" aria-hidden="true"></div>{/if}
    <main class="imm-main">{@render children?.()}</main>
  </div>
</div>

{#if open}
  <div class="imm-scrim scrim-layer" role="presentation" onclick={() => (open = false)}></div>
  <aside class="imm-drawer glass-3" aria-label="导航与状态">
    <div class="imm-drawer-head">
      <span class="micro-label">导航</span>
      <button class="imm-close" type="button" aria-label="关闭" onclick={() => (open = false)}>
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>
      </button>
    </div>
    <div class="imm-drawer-content">
      <nav class="imm-nav" aria-label="主导航">
        {#each tabs as tab}
          <button
            class="imm-tab {active === tab ? 'on' : ''}"
            type="button"
            onclick={() => pick(tab)}
            aria-current={active === tab ? 'page' : undefined}
          >{TAB_LABELS[tab]}</button>

          {#if tab === 'settings' && active === 'settings'}
            <div class="imm-subs">
              {#each SETTINGS_GROUPS as g, gi}
                {#if gi > 0}<div class="imm-sub-sep" aria-hidden="true"></div>{/if}
                {#each g.items as item}
                  <button
                    class="imm-sub {activeSub === item.key ? 'on' : ''}"
                    type="button"
                    onclick={() => pickSub(item.key)}
                    aria-current={activeSub === item.key ? 'page' : undefined}
                  >{item.title}</button>
                {/each}
              {/each}
            </div>
          {/if}
        {/each}
      </nav>
      <StatePanel compact />
    </div>
  </aside>
{/if}

<style>
  .imm {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    width: 100%;
    height: 100dvh;
    padding: var(--space-2);
    overflow: hidden;
  }

  .imm-bar {
    display: flex;
    flex: none;
    align-items: center;
    gap: var(--space-2);
    min-height: calc(var(--topbar-h) + var(--space-1));
    padding: var(--space-1) var(--space-2) var(--space-1) var(--space-4);
    border-radius: var(--radius-lg);
  }

  .imm-dot {
    flex: none;
    width: 8px;
    height: 8px;
    border-radius: var(--radius-pill);
    background: var(--accent-gradient);
    box-shadow: 0 0 0 4px var(--accent-glow);
  }

  .imm-name {
    min-width: 0;
    overflow: hidden;
    color: var(--text-1);
    font-size: var(--text-sm);
    font-weight: 650;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .imm-meta {
    flex: none;
    color: var(--text-2);
    font-size: var(--text-xs);
    white-space: nowrap;
  }

  .imm-mood {
    padding: 2px var(--space-2);
    border-radius: var(--radius-pill);
    background: var(--accent-soft);
    color: var(--accent);
  }

  .imm-btn,
  .imm-close {
    display: inline-flex;
    flex: none;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border: 0;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-2);
    cursor: pointer;
  }

  .imm-btn { margin-left: auto; }

  .imm-btn:hover,
  .imm-close:hover {
    background: var(--row-hover);
    color: var(--text-1);
  }

  .imm-frame {
    position: relative;
    flex: 1;
    min-height: 0;
  }

  .imm-material {
    position: absolute;
    inset: 0;
    border-radius: var(--radius-xl);
    pointer-events: none;
  }

  .imm-main {
    position: relative;
    height: 100%;
    overflow: hidden auto;
    border-radius: var(--radius-xl);
    overscroll-behavior: contain;
  }

  .imm-main :global(.chat-stage) {
    overflow: hidden;
    border-radius: var(--radius-xl);
    box-shadow: var(--surface-stage-shadow);
  }

  .imm-scrim {
    position: fixed;
    inset: 0;
    z-index: var(--z-scrim);
    animation: fadeIn var(--transition);
  }

  .imm-drawer {
    position: fixed;
    inset-block: var(--space-3);
    inset-inline-end: var(--space-3);
    z-index: var(--z-drawer);
    display: flex;
    flex-direction: column;
    width: min(330px, calc(100vw - var(--space-5)));
    border-radius: var(--radius-xl);
    animation: slideInRight var(--transition-snap);
  }

  .imm-drawer-head {
    display: flex;
    flex: none;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-2) var(--space-2) 0 var(--space-4);
  }

  .imm-drawer-head .micro-label {
    color: var(--text-1);
    font-size: var(--text-sm);
    letter-spacing: normal;
  }

  .imm-drawer-content {
    min-height: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
    border-radius: 0 0 var(--radius-xl) var(--radius-xl);
  }

  .imm-nav,
  .imm-subs {
    display: flex;
    flex-direction: column;
    gap: var(--optical-3);
  }

  .imm-nav { padding: var(--space-2) var(--space-3); }
  .imm-subs { padding-left: var(--space-3); }

  .imm-tab,
  .imm-sub {
    position: relative;
    min-height: 36px;
    padding: var(--space-1) var(--space-3);
    border: 0;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-2);
    font-family: inherit;
    font-size: var(--text-sm);
    text-align: left;
    cursor: pointer;
  }

  .imm-sub { font-size: var(--text-xs); }
  .imm-tab:hover,
  .imm-sub:hover { background: var(--row-hover); color: var(--text-1); }

  .imm-tab.on,
  .imm-sub.on {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 650;
  }

  .imm-tab.on::before,
  .imm-sub.on::before {
    position: absolute;
    inset-block: 27%;
    inset-inline-start: 3px;
    width: 3px;
    border-radius: var(--radius-pill);
    background: currentColor;
    content: '';
  }

  .imm-sub-sep {
    height: 1px;
    margin: var(--space-1) var(--space-3);
    background: var(--surface-divider);
  }

  @media (min-width: 768px) {
    .imm { gap: var(--optical-10); padding: var(--space-3); }
  }
</style>
