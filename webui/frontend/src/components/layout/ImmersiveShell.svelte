<script>
  // ImmersiveShell.svelte — 沉浸外壳 (概念2)
  //
  // 没有侧栏、没有底部导航: 顶部一条 32px 细状态条, 内容占满整屏。
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
  <header class="imm-bar">
    <span class="imm-dot" aria-hidden="true"></span>
    {#if name}<span class="imm-name">{name}</span>{/if}
    {#if moodLabel}<span class="imm-sep">·</span><span class="imm-meta">{moodLabel}</span>{/if}
    {#if level !== null}<span class="imm-sep">·</span><span class="imm-meta">亲密 <span class="mono">{level}</span></span>{/if}
    <button class="imm-btn" type="button" aria-label="打开侧栏" aria-expanded={open} onclick={() => (open = !open)}>
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h16"/></svg>
    </button>
  </header>

  <main class="imm-main">
    {@render children?.()}
  </main>
</div>

{#if open}
  <div class="imm-scrim" role="presentation" onclick={() => (open = false)}></div>
  <aside class="imm-drawer" aria-label="导航与状态">
    <div class="imm-drawer-head">
      <span class="micro-label">导航</span>
      <button class="imm-close" type="button" aria-label="关闭" onclick={() => (open = false)}>
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>
      </button>
    </div>
    <nav class="imm-nav">
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
    <StatePanel />
  </aside>
{/if}

<style>
  .imm {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100dvh;
    background: var(--surface);
    overflow: hidden;
  }

  .imm-bar {
    flex: none;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    height: 32px;
    padding: 0 var(--space-4);
    border-bottom: 1px solid var(--border);
    background: var(--surface);
  }
  .imm-dot {
    flex: none;
    width: 7px;
    height: 7px;
    border-radius: var(--radius-full);
    background: var(--accent);
  }
  .imm-name {
    font-size: var(--text-xs);
    color: var(--text-1);
    font-weight: 500;
  }
  .imm-sep { font-size: var(--text-xs); color: var(--text-3); }
  .imm-meta { font-size: var(--text-xs); color: var(--text-3); }
  .imm-btn {
    margin-left: auto;
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 22px;
    border: none;
    background: transparent;
    color: var(--text-2);
    cursor: pointer;
    border-radius: var(--radius-xs);
  }
  .imm-btn:hover { background: var(--row-hover); color: var(--text-1); }

  .imm-main {
    flex: 1;
    min-height: 0;
    /* 聊天页自带内部滚动(高度 100%，不会溢出)；
       设置等页面没有自己的滚动容器，必须让这里可滚，否则内容被裁掉翻不动。 */
    overflow-y: auto;
    overflow-x: hidden;
  }

  .imm-scrim {
    position: fixed;
    inset: 0;
    z-index: 40;
    background: var(--overlay);
  }

  .imm-drawer {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    z-index: 41;
    width: min(300px, 86vw);
    display: flex;
    flex-direction: column;
    background: var(--bg);
    border-left: 1px solid var(--border);
    overflow: hidden;
  }
  .imm-drawer-head {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-3) var(--space-4);
    border-bottom: 1px solid var(--border);
  }
  .imm-close {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border: none;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
    border-radius: var(--radius-xs);
  }
  .imm-close:hover { background: var(--row-hover); color: var(--text-1); }

  .imm-nav {
    flex: none;
    display: flex;
    flex-direction: column;
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--border);
  }
  .imm-tab {
    display: flex;
    align-items: center;
    height: 30px;
    padding: 0 var(--space-4);
    border: none;
    border-left: 2px solid transparent;
    background: transparent;
    font-family: inherit;
    font-size: var(--text-sm);
    color: var(--text-3);
    text-align: left;
    cursor: pointer;
    transition: color var(--transition), background var(--transition);
  }
  .imm-tab:hover { background: var(--row-hover); color: var(--text-2); }
  .imm-tab.on {
    color: var(--accent);
    font-weight: 500;
    background: var(--surface-2);
    border-left-color: var(--accent);
  }

  /* ---- 设置分类 (缩进展开在「设置」下方) ---- */
  .imm-subs {
    display: flex;
    flex-direction: column;
    padding: var(--space-1) 0 var(--space-2);
  }
  .imm-sub {
    display: flex;
    align-items: center;
    height: 26px;
    padding: 0 var(--space-4) 0 38px;
    border: none;
    border-left: 2px solid transparent;
    background: transparent;
    font-family: inherit;
    font-size: var(--text-xs);
    color: var(--text-3);
    text-align: left;
    cursor: pointer;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    transition: color var(--transition), background var(--transition);
  }
  .imm-sub:hover { background: var(--row-hover); color: var(--text-2); }
  .imm-sub.on { color: var(--accent); font-weight: 500; }
  .imm-sub-sep {
    height: 1px;
    margin: var(--space-1) var(--space-4) var(--space-1) 38px;
    background: var(--border);
  }
</style>
