<script>
  // TodayPage.svelte — 「今天」版面 (概念3 的落地页)
  //
  // 打开先看到的不是聊天窗, 而是她的今天: 心情 / 昨天 / 待跟进 / 记得的事。
  // 数据来自 GET /api/state。
  import { session, stateRevision, ensureActiveConversation } from '../lib/session.svelte.js';
  import { fetchState } from '../lib/stateApi.js';
  import { shortDate } from '../lib/format.js';
  import { navigate } from '../lib/router.js';

  let data = $state(null);
  let loading = $state(true);
  let failed = $state('');
  let samples = $state([]);
  let sampleConversation = null;
  let sampleScope = '';

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
        data = null;
        samples = [];
        sampleConversation = null;
        sampleScope = '';
        loading = false;
        return;
      }
      if (sampleConversation !== null && sampleConversation !== effective) {
        data = null;
        samples = [];
      }
      try {
        const d = await fetchState(effective);
        if (!alive) return;
        data = d;
        recordMood(effective, d?.mood?.valence);
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

  const now = new Date();
  const hour = now.getHours();
  const greeting = hour < 11 ? '早上好' : hour < 13 ? '中午好' : hour < 18 ? '下午好' : '晚上好';
  let dateLabel = $derived(
    `${now.getMonth() + 1}月${now.getDate()}日 ${WEEKDAYS[now.getDay()]}`,
  );

  let mood = $derived(data?.mood ?? null);
  let affection = $derived(data?.affection ?? null);
  let memories = $derived(data?.memories ?? []);
  let loops = $derived(data?.open_loops ?? []);
  let diary = $derived(data?.diary ?? null);
  let name = $derived(data?.persona_name || session.personaName || '她');

  let valence = $derived(readValence(mood?.valence));
  let moodPoints = $derived.by(() => {
    if (samples.length < 2) return '';
    const first = samples[0].at;
    const duration = Math.max(1, samples[samples.length - 1].at - first);
    return samples.map(({ at, value }) => {
      const x = 8 + 304 * (at - first) / duration;
      return x.toFixed(1) + ',' + (42 - 32 * value).toFixed(1);
    }).join(' ');
  });

  function readValence(value) {
    if (value == null || value === '') return null;
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(-1, Math.min(1, number)) : null;
  }

  function recordMood(conversationId, rawValue) {
    const scope = conversationId + '/' + new Date().toDateString();
    if (sampleScope !== scope) {
      sampleConversation = conversationId;
      sampleScope = scope;
      samples = [];
    }
    const value = readValence(rawValue);
    if (value === null) return;
    const at = Date.now();
    if (samples[samples.length - 1]?.at !== at) {
      samples = [...samples.slice(-11), { at, value }];
    }
  }

  function moodLine(m) {
    if (!m) return '';
    if (m.valence > 0.3) return '今天心情不错，比较愿意说话';
    if (m.valence < -0.3) return '今天情绪偏低，说话会克制一些';
    return '今天偏向安静，不太主动';
  }
</script>

<div class="today">
  <header class="today-head">
    <h1>今天</h1>
    <span class="date-pill">{dateLabel}</span>
  </header>

  <div class="today-grid">
    <section class="today-card greeting">
      <div>
        <h2>{greeting}</h2>
        <p>和{name}聊聊今天。</p>
      </div>
      <button class="today-go" type="button" onclick={() => navigate('chat')}>开始对话 <span aria-hidden="true">↗</span></button>
    </section>

    {#if loading && !data}
      <div class="today-card today-empty" role="status">正在加载今日状态…</div>
    {:else if failed}
      <div class="today-card today-empty" role="status">状态暂时读不到</div>
    {:else}
      <section class="today-card mood">
        <h3>她的心情</h3>
        {#if mood}
          <p class="mood-label"><span aria-hidden="true"></span>{mood.label}</p>
          {#if moodPoints}
            <svg class="mood-curve" viewBox="0 0 320 84" role="img" aria-label="本次查看期间记录的情绪曲线">
              <path d="M8 42H312" stroke="var(--surface-divider)" stroke-dasharray="4 5" />
              <polyline points={moodPoints} fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          {:else if valence !== null}
            <div class="mood-track" role="meter" aria-label="情绪值" aria-valuemin={-1} aria-valuemax={1} aria-valuenow={valence} aria-valuetext={mood.label}>
              <span style:left={(valence + 1) * 50 + '%'}></span>
            </div>
          {/if}
          <p class="note">{moodLine(mood)}</p>
        {:else}
          <p class="note">还没有心情记录</p>
        {/if}
      </section>

      <section class="today-card activity">
        <header class="card-head">
          <h3>伴侣动态</h3>
          <button class="today-link" type="button" onclick={() => navigate('discover')}>朋友圈 <span aria-hidden="true">↗</span></button>
        </header>
        {#if diary?.summary}
          <p class="diary-label">昨日日记</p>
          <p class="diary-summary">{diary.summary}</p>
        {:else}
          <p class="note">还没有日记。</p>
        {/if}
      </section>

      <section class="today-card agenda">
        <h3>待跟进</h3>
        {#if loops.length}
          <ul class="task-list">
            {#each loops as item}
              {@const date = shortDate(item.expected_date)}
              <li>
                <span>{item.title}</span>
                {#if date}<span class="task-date">{date}</span>{/if}
              </li>
            {/each}
          </ul>
        {:else}
          <p class="note">目前没有待跟进的事。</p>
        {/if}
      </section>

      <section class="today-card memories">
        <h3>记得的事</h3>
        {#if memories.length}
          <ul class="memory-list">
            {#each memories as memory}
              <li title={memory.category}>{memory.content}</li>
            {/each}
          </ul>
        {:else}
          <p class="note">还没有长期记忆</p>
        {/if}
      </section>

      <section class="today-card relationship">
        <h3>关系</h3>
        {#if affection}
          <div class="relationship-value">
            <strong>{Math.round(affection.level)}</strong>
            <span>{affection.stage}</span>
          </div>
          <p class="note">与{name}的亲密度</p>
        {:else}
          <p class="note">还没有关系记录</p>
        {/if}
      </section>
    {/if}
  </div>
</div>

<style>
  .today {
    max-width: var(--page-maxw);
    margin-inline: auto;
    padding: clamp(16px, 4vw, 52px) clamp(12px, 4vw, 44px) var(--space-6);
    font-variant-numeric: tabular-nums;
  }

  .today-head,
  .card-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }

  .today-head { margin-bottom: var(--space-4); }

  .today-head h1 {
    margin: 0;
    color: var(--text-1);
    font-size: clamp(1.8rem, 4vw, 2.9rem);
    font-weight: 700;
    letter-spacing: var(--tracking-tighter);
    line-height: var(--leading-tight);
  }

  .date-pill,
  .mood-label,
  .task-date,
  .memory-list li {
    display: inline-flex;
    align-items: center;
    max-width: 100%;
    padding: var(--space-1) var(--space-3);
    border-radius: var(--radius-pill);
    background: var(--field-fill);
    color: var(--text-2);
    font-size: var(--text-13);
    overflow-wrap: anywhere;
  }

  .today-grid {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: var(--space-3);
  }

  .today-card {
    display: grid;
    align-content: start;
    gap: var(--space-2);
    min-width: 0;
    padding: clamp(14px, 3vw, 24px);
    border-radius: var(--radius-lg);
    background: var(--surface);
    box-shadow: var(--surface-stage-shadow);
  }

  .greeting {
    grid-column: span 4;
    min-height: 192px;
    align-content: space-between;
    justify-items: start;
    background:
      radial-gradient(ellipse 90% 145% at 100% 0%, var(--accent-glow), transparent 76%),
      var(--surface);
  }

  .greeting h2,
  .today-card h3 {
    margin: 0;
    color: var(--text-1);
    line-height: var(--leading-tight);
  }

  .greeting h2 { font-size: clamp(1.6rem, 4vw, 2.35rem); }
  .greeting p { margin: var(--space-2) 0; color: var(--text-2); }
  .today-card h3 { font-size: var(--text-base); font-weight: 650; }

  .today-go,
  .today-link {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    min-height: 40px;
    padding: var(--space-1) var(--space-3);
    border: 0;
    border-radius: var(--radius-pill);
    background: var(--accent);
    color: var(--on-accent);
    font: inherit;
    font-size: var(--text-sm);
    font-weight: 600;
    cursor: pointer;
  }

  .today-go:hover { background: var(--accent-hover); }
  .today-link { min-height: 34px; background: var(--accent-soft); color: var(--accent); font-size: var(--text-xs); }
  .today-link:hover { background: var(--accent-glow); }

  .mood, .relationship { grid-column: span 2; }
  .activity, .agenda { grid-column: span 3; }
  .memories, .today-empty { grid-column: span 4; }

  .mood-label {
    justify-self: start;
    gap: var(--space-2);
    margin: 0;
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 650;
  }

  .mood-label span {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: currentColor;
  }

  .mood-track {
    position: relative;
    height: 8px;
    margin-block: var(--space-2);
    border-radius: var(--radius-pill);
    background: linear-gradient(90deg, var(--surface-3), var(--accent-glow));
  }

  .mood-track span {
    position: absolute;
    top: 50%;
    width: 12px;
    height: 12px;
    border: 2px solid var(--surface);
    border-radius: 50%;
    background: var(--accent);
    box-shadow: var(--shadow-1);
    transform: translate(-50%, -50%);
    transition: left var(--transition-spring);
  }

  .mood-curve { display: block; width: 100%; height: auto; max-height: 80px; color: var(--accent); }
  .note, .today-empty, .diary-label { color: var(--text-2); font-size: var(--text-13); }
  .note, .diary-label, .diary-summary { margin: 0; }
  .diary-label { font-weight: 650; }
  .diary-summary { color: var(--text-1); white-space: pre-wrap; overflow-wrap: anywhere; }

  .task-list, .memory-list { display: grid; gap: var(--space-2); margin: 0; padding: 0; list-style: none; }

  .task-list li {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-2);
    padding: var(--space-2);
    border-radius: var(--radius-sm);
    background: var(--field-fill);
    color: var(--text-1);
    font-size: var(--text-13);
    overflow-wrap: anywhere;
  }

  .task-date { flex: none; background: var(--accent-soft); color: var(--accent); font-size: var(--text-xs); }
  .memory-list { display: flex; flex-wrap: wrap; }

  .relationship-value { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--space-2); }
  .relationship-value strong { color: var(--accent); font-size: var(--text-2xl); font-weight: 680; }
  .relationship-value span { color: var(--text-1); font-size: var(--text-13); }

  @media (max-width: 850px) {
    .today-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .today-card { grid-column: span 1; }
    .greeting, .memories, .today-empty { grid-column: 1 / -1; }
  }

  @media (max-width: 520px) {
    .today { padding-inline: var(--space-3); }
    .today-grid { grid-template-columns: minmax(0, 1fr); }
    .greeting { min-height: 156px; }
  }
</style>
