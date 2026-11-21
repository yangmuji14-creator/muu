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
  // data 当前属于哪个会话：切会话后旧载荷必须先清掉，
  // 否则新会话加载失败时会一直显示上一个会话的心情/记忆。
  let dataCid = $state(null);

  $effect(() => {
    const cid = session.conversationId;
    const rev = stateRevision.n; // 依赖刷新信号：对话结束后重新拉取
    void rev;
    let alive = true;
    let inflight = false;
    let timer = null;
    loading = true;
    failed = '';

    const POLL_MS = 60_000;

    function schedule() {
      if (!alive) return;
      clearTimeout(timer);
      // 隐藏的标签页不轮询；重新可见时由 visibilitychange 立刻补一次
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
      timer = setTimeout(load, POLL_MS);
    }

    async function load() {
      if (!alive || inflight) return; // 防止慢请求与新请求重叠导致乱序覆盖
      inflight = true;
      try {
        // 没有活动会话时先解析一个，否则会读到空的默认作用域
        const effective = cid || (await ensureActiveConversation());
        if (!alive) return;
        if (!effective) {
          loading = false;
          return;
        }
        if (dataCid && dataCid !== effective) {
          // 换会话：先把旧会话的数据清掉，失败时才能正确进入错误态
          data = null;
          failed = '';
        }
        const d = await fetchState(effective);
        if (!alive) return;
        data = d;
        dataCid = effective;
        failed = ''; // 成功后必须清掉旧的错误态，否则面板永久停在「状态暂时读不到」
      } catch (e) {
        // 当前会话尚无数据时才展示错误；轮询失败不覆盖已有内容
        if (alive && !data) failed = e.message || '加载失败';
      } finally {
        if (alive) loading = false;
        inflight = false;
        schedule();
      }
    }

    function onVisibility() {
      if (document.visibilityState === 'visible') load();
      else clearTimeout(timer);
    }

    load();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      alive = false;
      clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisibility);
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

  function progress(value, min, max) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.min(max, Math.max(min, number)) : min;
  }

  let moodValue = $derived(progress(mood?.valence, -1, 1));
  let affectionValue = $derived(progress(affection?.level, 0, 100));

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
      {#if mood}
        <section class="sp-section">
          <div class="sp-row">
            <h3>此刻心情</h3>
            {#if mood.label}<span class="sp-pill"><span class="sp-dot" aria-hidden="true"></span>{mood.label}</span>{/if}
          </div>
          <div class="sp-track" role="meter" aria-label="心情" aria-valuemin="-1" aria-valuemax="1" aria-valuenow={moodValue} aria-valuetext={mood.label || undefined}>
            <span class="sp-fill" style:width={(moodValue + 1) * 50 + '%'}></span>
          </div>
        </section>
      {/if}
      {#if affection}
        <section class="sp-section">
          <div class="sp-row">
            <h3>亲密度</h3>
            <span class="sp-val">{Math.round(affectionValue)}</span>
          </div>
          <div class="sp-track" role="meter" aria-label="亲密度" aria-valuemin="0" aria-valuemax="100" aria-valuenow={affectionValue}>
            <span class="sp-fill" style:width={affectionValue + '%'}></span>
          </div>
          {#if affection.stage}<div class="sp-note">{affection.stage}</div>{/if}
        </section>
      {/if}
    {/if}

    {#if monologue}
      <div class="sp-section">
        <h3>心里在想</h3>
        <p class="sp-quote" class:is-clamped={monologueLong && !monologueExpanded}>{monologue}</p>
        {#if monologueLong}
          <button class="sp-more" type="button" aria-expanded={monologueExpanded} onclick={() => (monologueExpanded = !monologueExpanded)}>
            {monologueExpanded ? '收起' : '展开'}
          </button>
        {/if}
      </div>
    {/if}

    {#if memories.length}
      <div class="sp-section">
        <h3>记得的事</h3>
        <ul class="sp-list">
          {#each memories as m}
            <li title={m.category}>{m.content}</li>
          {/each}
        </ul>
      </div>
    {/if}

    {#if loops.length}
      <div class="sp-section">
        <h3>待跟进</h3>
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
      <div class="sp-section">
        <h3>最近</h3>
        <p class="sp-diary">{diary.summary}</p>
      </div>
    {/if}
  {/if}
</aside>

<style>
  .state-panel {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    height: 100%;
    min-height: 0;
    padding: var(--space-3);
    overflow-y: auto;
    overscroll-behavior: contain;
    scrollbar-width: thin;
    scrollbar-color: var(--border-strong) transparent;
  }

  .state-panel.compact {
    height: auto;
    overflow: visible;
    padding-top: 0;
  }

  .sp-section,
  .sp-empty {
    flex: none;
    min-width: 0;
    padding: var(--space-3);
    border-radius: var(--radius-md);
    background: var(--surface);
    box-shadow: var(--shadow-1);
  }

  .sp-section h3 {
    margin: 0 0 var(--space-2);
    color: var(--text-1);
    font-size: var(--text-13);
    font-weight: 650;
    line-height: var(--leading-snug);
  }

  .sp-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    margin-bottom: var(--space-2);
  }

  .sp-row h3 { margin: 0; }

  .sp-pill {
    display: inline-flex;
    align-items: center;
    gap: var(--optical-5);
    max-width: 65%;
    padding: 3px var(--space-2);
    border-radius: var(--radius-pill);
    background: var(--accent-soft);
    color: var(--accent);
    overflow-wrap: anywhere;
    font-size: var(--text-xs);
    line-height: var(--leading-snug);
  }

  .sp-dot {
    flex: none;
    width: 6px;
    height: 6px;
    border-radius: var(--radius-pill);
    background: currentColor;
  }

  .sp-val {
    color: var(--accent);
    font-size: var(--text-lg);
    font-weight: 650;
    font-variant-numeric: tabular-nums;
    line-height: 1;
  }

  .sp-track {
    height: 5px;
    overflow: hidden;
    border-radius: var(--radius-pill);
    background: var(--progress-track);
  }

  .sp-fill {
    display: block;
    height: 100%;
    border-radius: inherit;
    background: var(--accent-gradient);
    transition: width var(--transition-spring);
  }

  .sp-note,
  .sp-date,
  .sp-hint {
    color: var(--text-2);
    font-size: var(--text-xs);
  }

  .sp-note { margin-top: var(--space-2); }

  .sp-quote,
  .sp-diary {
    margin: 0;
    color: var(--text-2);
    font-size: var(--text-13);
    line-height: var(--leading-normal);
    overflow-wrap: anywhere;
  }

  .sp-quote.is-clamped,
  .sp-diary {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .sp-quote.is-clamped { -webkit-line-clamp: 4; line-clamp: 4; }
  .sp-diary { -webkit-line-clamp: 6; line-clamp: 6; }

  .sp-more {
    min-height: 32px;
    margin-top: var(--space-2);
    padding-inline: var(--space-2);
    border: 0;
    border-radius: var(--radius-pill);
    background: var(--accent-soft);
    color: var(--accent);
    font-size: var(--text-xs);
    cursor: pointer;
  }

  .sp-more:hover { background: var(--accent-glow); }

  .sp-list {
    display: grid;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .sp-list li {
    position: relative;
    display: -webkit-box;
    padding-left: var(--space-3);
    overflow: hidden;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    color: var(--text-2);
    font-size: var(--text-13);
    overflow-wrap: anywhere;
  }

  .sp-list li::before {
    position: absolute;
    top: 0.65em;
    left: 0;
    width: 4px;
    height: 4px;
    border-radius: var(--radius-pill);
    background: var(--accent);
    content: '';
  }

  .sp-list li.sp-loop { display: flex; align-items: baseline; gap: var(--space-2); }
  .sp-loop-title { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sp-date { flex: none; white-space: nowrap; }

  .sp-empty { color: var(--text-2); font-size: var(--text-13); }
  .sp-empty p { margin: 0; }
  .sp-empty .sp-hint { margin-top: var(--space-1); }
</style>
