<script>
  // TodayPage.svelte — 「今天」版面 (概念3 的落地页)
  //
  // 打开先看到的不是聊天窗, 而是她的今天: 心情 / 昨天 / 待跟进 / 记得的事。
  // 数据来自 GET /api/state。
  import { session, stateRevision, ensureActiveConversation } from '../lib/session.svelte.js';
  import { fetchState } from '../lib/stateApi.js';
  import { navigate } from '../lib/router.js';

  let data = $state(null);
  let loading = $state(true);
  let failed = $state('');

  $effect(() => {
    const cid = session.conversationId;
    const rev = stateRevision.n; // 依赖刷新信号：对话结束后重新拉取
    void rev;
    let alive = true;
    loading = true;
    failed = '';
    (async () => {
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

  const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

  let now = new Date();
  let dateLabel = $derived(
    `${now.getMonth() + 1}月${now.getDate()}日 ${WEEKDAYS[now.getDay()]}`,
  );

  let mood = $derived(data?.mood ?? null);
  let affection = $derived(data?.affection ?? null);
  let memories = $derived(data?.memories ?? []);
  let loops = $derived(data?.open_loops ?? []);
  let diary = $derived(data?.diary ?? null);
  let name = $derived(data?.persona_name || session.personaName || '她');

  function moodLine(m) {
    if (!m) return '';
    if (m.valence > 0.3) return '今天心情不错，比较愿意说话';
    if (m.valence < -0.3) return '今天情绪偏低，说话会克制一些';
    return '今天偏向安静，不太主动';
  }
</script>

<div class="today">
  <header class="today-head">
    <span class="today-mark" aria-hidden="true"></span>
    <span class="today-title">今天</span>
    <span class="today-date mono">{dateLabel}</span>
    <button class="today-go" type="button" onclick={() => navigate('chat')}>开始对话</button>
  </header>

  {#if loading && !data}
    <div class="today-empty">加载中…</div>
  {:else if failed}
    <div class="today-empty">状态暂时读不到</div>
  {:else}
    <div class="today-grid">
      <section class="tcell">
        <div class="micro-label">她的心情</div>
        {#if mood}
          <div class="tcell-main">{mood.label}</div>
          <div class="ttrack"><span class="tfill" style="width:{(mood.valence + 1) / 2 * 100}%"></span></div>
          <p class="tcell-note">{moodLine(mood)}</p>
        {:else}
          <p class="tcell-note">还没有记录</p>
        {/if}
      </section>

      <section class="tcell">
        <div class="micro-label">昨天</div>
        {#if diary?.summary}
          <p class="tcell-body">{diary.summary}</p>
        {:else}
          <p class="tcell-note">还没生成日记。多聊几次，她会把你们的近况记下来。</p>
        {/if}
      </section>

      <section class="tcell tcell-last">
        <div class="micro-label">待跟进</div>
        {#if loops.length}
          <ul class="tlist">
            {#each loops as l}
              <li>{l.title}{#if l.expected_date}<span class="tdate mono">{l.expected_date}</span>{/if}</li>
            {/each}
          </ul>
        {:else}
          <p class="tcell-note">暂时没有悬着的事</p>
        {/if}
      </section>
    </div>

    <section class="trow">
      <div class="micro-label">记得的事</div>
      {#if memories.length}
        <div class="tchips">
          {#each memories as m}
            <span class="tchip" title={m.category}>{m.content}</span>
          {/each}
        </div>
      {:else}
        <p class="tcell-note">还没有长期记忆</p>
      {/if}
    </section>

    <section class="trow trow-split">
      <div>
        <div class="micro-label">关系</div>
        <p class="tcell-body">
          {#if affection}
            和{name}：{affection.stage}（<span class="mono">{Math.round(affection.level)}</span>）
          {:else}
            还没有记录
          {/if}
        </p>
      </div>
      <button class="tlink" type="button" onclick={() => navigate('discover')}>朋友圈 →</button>
    </section>
  {/if}
</div>

<style>
  .today {
    min-height: 100%;
    background: var(--surface);
  }

  .today-head {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    height: var(--topbar-h);
    padding: 0 var(--space-4);
    border-bottom: 1px solid var(--border);
  }
  .today-mark {
    flex: none;
    width: 10px;
    height: 10px;
    background: var(--text-1);
  }
  .today-title {
    font-size: var(--text-sm);
    font-weight: 500;
    color: var(--text-1);
  }
  .today-date {
    font-size: var(--text-xs);
    color: var(--text-3);
  }
  .today-go {
    margin-left: auto;
    flex: none;
    height: 28px;
    padding: 0 var(--space-3);
    border: none;
    border-radius: var(--radius-sm);
    background: var(--text-1);
    color: var(--surface);
    font-family: inherit;
    font-size: var(--text-xs);
    font-weight: 500;
    cursor: pointer;
    transition: background var(--transition);
  }
  .today-go:hover { background: var(--btn-primary-hover); }

  .today-grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr) minmax(0, 1fr);
    border-bottom: 1px solid var(--border);
  }
  .tcell {
    padding: var(--space-4);
    border-right: 1px solid var(--border);
    min-width: 0;
  }
  .tcell.tcell-last { border-right: none; }
  .tcell .micro-label { margin-bottom: var(--space-3); }
  .tcell-main {
    font-size: var(--text-lg);
    font-weight: 500;
    color: var(--text-1);
    margin-bottom: var(--space-2);
  }
  .ttrack {
    height: 3px;
    background: var(--surface-3);
    overflow: hidden;
    margin-bottom: var(--space-2);
  }
  .tfill { display: block; height: 100%; background: var(--text-1); }
  .tcell-note {
    margin: 0;
    font-size: var(--text-xs);
    line-height: 1.7;
    color: var(--text-3);
  }
  .tcell-body {
    margin: 0;
    font-size: var(--text-sm);
    line-height: 1.75;
    color: var(--text-2);
    display: -webkit-box;
    -webkit-line-clamp: 4;
    line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .tlist { margin: 0; padding: 0; list-style: none; }
  .tlist li {
    position: relative;
    padding-left: 12px;
    margin-bottom: 5px;
    font-size: var(--text-sm);
    line-height: 1.6;
    color: var(--text-2);
  }
  .tlist li::before {
    content: '';
    position: absolute;
    left: 0;
    top: 9px;
    width: 4px;
    height: 1px;
    background: var(--text-3);
  }
  .tdate { margin-left: 6px; font-size: var(--text-xs); color: var(--text-3); }

  .trow {
    padding: var(--space-4);
    border-bottom: 1px solid var(--border);
  }
  .trow .micro-label { margin-bottom: var(--space-3); }
  .trow-split {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: var(--space-4);
    border-bottom: none;
  }
  .tchips { display: flex; flex-wrap: wrap; gap: var(--space-2); }
  .tchip {
    font-size: var(--text-xs);
    color: var(--text-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-xs);
    padding: 3px 8px;
  }
  .tlink {
    flex: none;
    border: none;
    background: transparent;
    padding: 0;
    font-family: inherit;
    font-size: var(--text-xs);
    color: var(--accent);
    cursor: pointer;
  }
  .tlink:hover { text-decoration: underline; }

  .today-empty {
    padding: var(--space-6) var(--space-4);
    font-size: var(--text-sm);
    color: var(--text-3);
  }

  @media (max-width: 767px) {
    .today-grid {
      grid-template-columns: minmax(0, 1fr);
    }
    .tcell {
      border-right: none;
      border-bottom: 1px solid var(--border);
    }
    .tcell.tcell-last { border-bottom: none; }
  }
</style>
