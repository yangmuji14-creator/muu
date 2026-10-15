<script>
  // StatePanel.svelte — 内心面板 (概念1 的右侧栏 / 概念2 抽屉内复用)
  //
  // 展示 AI 的运行时状态: 此刻(心情/亲密度) · 内心独白 · 记得的事 · 待跟进 · 最近
  // 数据来自 GET /api/state，任一子项缺失时该段自动隐藏。
  import { session, stateRevision, ensureActiveConversation } from '../../lib/session.svelte.js';
  import { fetchState } from '../../lib/stateApi.js';
  import { shortDate } from '../../lib/format.js';

  let { compact = false } = $props();

  let data = $state(null);
  let loading = $state(false);
  let failed = $state('');

  $effect(() => {
    const cid = session.conversationId;
    const rev = stateRevision.n; // 依赖刷新信号：对话结束后重新拉取
    void rev;
    let alive = true;
    loading = true;
    failed = '';
    (async () => {
      // 没有活动会话时先解析一个，否则会读到空的默认作用域
      const effective = cid || (await ensureActiveConversation());
      if (!alive) return;
      if (!effective) {
        loading = false;
        return;
      }
      try {
        const d = await fetchState(effective);
        if (alive) data = d;
      } catch (e) {
        if (alive) failed = e.message || '加载失败';
      } finally {
        if (alive) loading = false;
      }
    })();
    return () => {
      alive = false;
    };
  });

  let mood = $derived(data?.mood ?? null);
  let affection = $derived(data?.affection ?? null);
  let memories = $derived(data?.memories ?? []);
  let loops = $derived(data?.open_loops ?? []);
  let monologue = $derived((data?.monologue ?? '').trim());
  let diary = $derived(data?.diary ?? null);

  let hasAny = $derived(
    !!(mood || affection || memories.length || loops.length || monologue || diary),
  );
</script>

<aside class="state-panel" class:compact aria-label="她的状态">
  {#if loading && !data}
    <div class="sp-empty">加载中…</div>
  {:else if failed}
    <div class="sp-empty">状态暂时读不到</div>
  {:else if !hasAny}
    <div class="sp-empty">
      <p>还没有可显示的状态。</p>
      <p class="sp-hint">和她聊几句，这里会慢慢有内容。</p>
    </div>
  {:else}
    {#if mood || affection}
      <div class="sp-section">
        <div class="micro-label">此刻</div>
        {#if mood}
          <div class="sp-row">
            <span class="sp-key">心情</span>
            <span class="sp-track"><span class="sp-fill" style="width:{(mood.valence + 1) / 2 * 100}%"></span></span>
            <span class="sp-val">{mood.label}</span>
          </div>
        {/if}
        {#if affection}
          <div class="sp-row">
            <span class="sp-key">亲密</span>
            <span class="sp-track"><span class="sp-fill" style="width:{affection.level}%"></span></span>
            <span class="sp-val mono">{Math.round(affection.level)}</span>
          </div>
          <div class="sp-note">{affection.stage}</div>
        {/if}
      </div>
    {/if}

    {#if monologue}
      <div class="sp-section">
        <div class="micro-label">心里在想</div>
        <p class="sp-quote">{monologue}</p>
      </div>
    {/if}

    {#if memories.length}
      <div class="sp-section">
        <div class="micro-label">记得的事</div>
        <ul class="sp-list">
          {#each memories as m}
            <li title={m.category}>{m.content}</li>
          {/each}
        </ul>
      </div>
    {/if}

    {#if loops.length}
      <div class="sp-section">
        <div class="micro-label">待跟进</div>
        <ul class="sp-list">
          {#each loops as l}
            <li class="sp-loop">
              <span class="sp-loop-title">{l.title}</span>{#if shortDate(l.expected_date)}<span class="sp-date mono">{shortDate(l.expected_date)}</span>{/if}
            </li>
          {/each}
        </ul>
      </div>
    {/if}

    {#if diary?.summary}
      <div class="sp-section sp-last">
        <div class="micro-label">最近</div>
        <p class="sp-diary">{diary.summary}</p>
      </div>
    {/if}
  {/if}
</aside>

<style>
  .state-panel {
    height: 100%;
    overflow-y: auto;
    background: var(--bg);
    scrollbar-width: thin;
    scrollbar-color: var(--border-strong) transparent;
  }
  .state-panel::-webkit-scrollbar { width: 8px; }
  .state-panel::-webkit-scrollbar-thumb {
    background: var(--border-strong);
    border: 2px solid transparent;
    background-clip: padding-box;
    border-radius: var(--radius-full);
  }

  .sp-section {
    padding: var(--space-3) var(--space-4);
    border-bottom: 1px solid var(--border);
  }
  .sp-section.sp-last { border-bottom: none; }
  .sp-section .micro-label { margin-bottom: var(--space-2); }

  .sp-row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin-bottom: 6px;
  }
  .sp-key {
    flex: none;
    width: 28px;
    font-size: var(--text-xs);
    color: var(--text-2);
  }
  .sp-track {
    flex: 1;
    height: 3px;
    background: var(--surface-3);
    overflow: hidden;
  }
  .sp-fill {
    display: block;
    height: 100%;
    background: var(--text-1);
  }
  .sp-val {
    flex: none;
    min-width: 28px;
    text-align: right;
    font-size: var(--text-xs);
    color: var(--text-2);
  }
  .sp-note {
    font-size: var(--text-xs);
    color: var(--text-3);
    padding-left: 36px;
  }

  .sp-quote {
    margin: 0;
    font-size: var(--text-sm);
    line-height: 1.7;
    color: var(--text-2);
  }

  .sp-list {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sp-list li {
    position: relative;
    padding-left: 12px;
    margin-bottom: 5px;
    font-size: var(--text-sm);
    line-height: 1.6;
    color: var(--text-2);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sp-list li::before {
    content: '';
    position: absolute;
    left: 0;
    top: 8px;
    width: 4px;
    height: 1px;
    background: var(--text-3);
  }
  /* 待跟进: 标题可截断, 日期完整保留（不随长标题被裁掉） */
  .sp-list li.sp-loop {
    display: flex;
    align-items: baseline;
    gap: 6px;
    overflow: visible;
    white-space: normal;
  }
  .sp-loop-title {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sp-date {
    flex: none;
    font-size: var(--text-xs);
    color: var(--text-3);
    white-space: nowrap;
  }

  .sp-diary {
    margin: 0;
    font-size: var(--text-sm);
    line-height: 1.7;
    color: var(--text-2);
    display: -webkit-box;
    -webkit-line-clamp: 6;
    line-clamp: 6;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .sp-empty {
    padding: var(--space-5) var(--space-4);
    font-size: var(--text-sm);
    color: var(--text-3);
    line-height: 1.7;
  }
  .sp-empty p { margin: 0 0 4px; }
  .sp-hint { font-size: var(--text-xs); color: var(--text-3); }
</style>
