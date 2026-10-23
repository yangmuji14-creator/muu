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
  // 独白常常上百字，244px 宽的栏里会一个人顶掉半屏。默认截到四行，
  // 超长时才给「展开」——短独白不该看到任何折叠痕迹。
  // 阈值 50：中文在 215px 内容宽、15px 字号下一行约 12 字，四行约 48 字，
  // 再多一行就把它当长段落处理。
  let monologueExpanded = $state(false);
  let monologueLong = $derived(monologue.length > 50);
  $effect(() => {
    // 独白换了内容就收回折叠态，免得旧的展开状态套到新的一段上
    void monologue;
    monologueExpanded = false;
  });
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
        <p class="sp-quote" class:is-clamped={monologueLong && !monologueExpanded}>{monologue}</p>
        {#if monologueLong}
          <button class="sp-more" type="button" onclick={() => (monologueExpanded = !monologueExpanded)}>
            {monologueExpanded ? '收起' : '展开'}
          </button>
        {/if}
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
    /* 不再自带底色: 外层 .panel-col 已经是 glass-1, 这里再铺一层 --bg
       会把玻璃彻底盖住, 让侧栏又变回不透明。 */
    background: transparent;
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
    padding: var(--space-4) var(--space-4) var(--space-5);
    border-bottom: 1px solid var(--border);
  }
  .sp-section.sp-last { border-bottom: none; }
  .sp-section .micro-label { margin-bottom: var(--space-3); }

  /* 两条进度行: 3px 细条改成 4px 圆头, 填充色从炭黑改冷蓝。
     炭黑填充在暖灰轨道上读数很费解 (哪头是“满”看不出来),
     冷蓝 + 圆头 + 右侧等宽读数, 一眼能读出比例。 */
  .sp-row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin-bottom: var(--optical-10);
  }
  .sp-key {
    flex: none;
    width: 30px;
    font-size: var(--text-2xs);
    letter-spacing: var(--tracking-wide);
    color: var(--text-3);
  }
  .sp-track {
    flex: 1;
    height: 4px;
    background: var(--surface-3);
    overflow: hidden;
    border-radius: var(--radius-full);
  }
  .sp-fill {
    display: block;
    height: 100%;
    background: var(--accent);
    border-radius: var(--radius-full);
    transition: width var(--transition-slow);
  }
  .sp-val {
    flex: none;
    min-width: 30px;
    text-align: right;
    font-size: var(--text-2xs);
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
  }
  .sp-note {
    font-size: var(--text-2xs);
    color: var(--text-3);
    padding-left: 38px;
    margin-top: -4px;
  }

  /* 内心独白: 这一栏原本是「28px 灰标签 + 14px 灰字」,
     整块面板读起来没有一处是「内容」。给它一道左竖线 + 15px/1.75,
     成为这一栏第一个真正可读的段落。 */
  .sp-quote {
    margin: 0;
    padding-left: var(--space-3);
    border-left: 2px solid var(--accent-line);
    font-size: var(--text-15);
    line-height: 1.72;
    letter-spacing: 0.005em;
    color: var(--text-1);
  }
  .sp-quote.is-clamped {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 4;
    line-clamp: 4;
    overflow: hidden;
  }
  .sp-more {
    display: inline-block;
    margin: var(--space-1) 0 0 var(--space-3);
    padding: 0;
    border: none;
    background: none;
    font-size: var(--text-xs);
    color: var(--accent);
    cursor: pointer;
  }
  .sp-more:hover { text-decoration: underline; }

  .sp-list {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  /* 记忆条目: 原来是 nowrap + ellipsis, 242px 宽的栏里几乎每条都被裁成
     「他说他会一直陪着我，我记住了…」—— 六条记忆五条以省略号收尾,
     一栏全是断句, 读的人根本得不到信息。放开到两行 clamp:
     一行放得下的自然还是一行, 长的那条多给一行就够说完整。 */
  .sp-list li {
    position: relative;
    padding-left: 12px;
    margin-bottom: var(--optical-7);
    font-size: var(--text-13);
    line-height: 1.62;
    color: var(--text-2);
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    overflow: hidden;
    word-break: break-word;
  }
  .sp-list li::before {
    content: '';
    position: absolute;
    left: 0;
    top: 9px;
    width: 5px;
    height: 1px;
    background: var(--border-strong);
  }
  /* 待跟进: 标题可截断, 日期完整保留（不随长标题被裁掉） */
  .sp-list li.sp-loop {
    display: flex;
    align-items: baseline;
    gap: var(--optical-6);
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
    font-size: var(--text-2xs);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  .sp-diary {
    margin: 0;
    font-size: var(--text-13);
    line-height: 1.74;
    color: var(--text-2);
    display: -webkit-box;
    -webkit-line-clamp: 6;
    line-clamp: 6;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .sp-empty {
    padding: var(--space-6) var(--space-4);
    font-size: var(--text-13);
    color: var(--text-3);
    line-height: 1.72;
  }
  .sp-empty p { margin: 0 0 var(--optical-5); }
  .sp-hint { font-size: var(--text-xs); color: var(--text-3); }
</style>
