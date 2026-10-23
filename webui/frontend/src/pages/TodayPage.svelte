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
    <div class="today-head-main">
      <span class="micro-label">此刻</span>
      <h1 class="today-title">今天</h1>
    </div>
    <div class="today-head-side">
      <span class="today-date mono">{dateLabel}</span>
      <button class="today-go" type="button" onclick={() => navigate('chat')}>开始对话</button>
    </div>
  </header>

  {#if loading && !data}
    <div class="today-empty">加载中…</div>
  {:else if failed}
    <div class="today-empty">状态暂时读不到</div>
  {:else}
    <div class="today-grid">
      <section class="tcell tcell-mood">
        <div class="micro-label">她的心情</div>
        {#if mood}
          <div class="tcell-main">{mood.label}</div>
          <div class="ttrack"><span class="tfill" style="width:{(mood.valence + 1) / 2 * 100}%"></span></div>
          <p class="tcell-note">{moodLine(mood)}</p>
        {:else}
          <p class="tcell-note">还没有记录</p>
        {/if}
      </section>

      <section class="tcell tcell-diary">
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
              <li>{l.title}{#if shortDate(l.expected_date)}<span class="tdate mono">{shortDate(l.expected_date)}</span>{/if}</li>
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
        <p class="tcell-rel">
          {#if affection}
            和{name}<span class="trel-stage">{affection.stage}</span><span class="trel-num mono">{Math.round(affection.level)}</span>
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
  /* 今天页原来铺满整个主区: 1440 视口下三格各约 330px 宽,
     每格里只有 2-3 行 12-14px 的文字, 格子显得空、整页显得平。
     限宽到 1000px 之后单格宽度回落到 260-420px, 文字与格子的比例恢复正常;
     页头/三格/两条横栏都在同一条 1000px 轴线上, 版面像一个整块。 */
  .today {
    min-height: 100%;
    max-width: 1000px;
    margin: 0;
    background: var(--surface);
  }

  /* ---- 页头 ----
    原来是一个 44px 高、字号 14px 的单行顶栏, 「今天」两个字和日期挤在
     10px 黑方块旁边, 完全没有「这是主页」的分量。
     现在按其它页同一套骨架: 11px 微标签 + 26px 主标题, 右侧日期 + 主动作
     对齐到同一基线。四个页面从此有同一个「入口」结构。 */
  .today-head {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: var(--space-4);
    padding: var(--space-5) var(--space-5) var(--space-4);
    border-bottom: 1px solid var(--border-strong);
  }
  .today-head-main {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .today-head .micro-label { margin: 0 0 var(--optical-6); }
  .today-title {
    margin: 0;
    font-size: var(--text-display);
    font-weight: 600;
    letter-spacing: var(--tracking-tight);
    line-height: 1.12;
    color: var(--text-1);
  }
  .today-head-side {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    flex: none;
  }
  .today-date {
    font-size: var(--text-2xs);
    letter-spacing: var(--tracking-wide);
    color: var(--text-3);
  }
  .today-go {
    flex: none;
    height: var(--btn-h-md);
    padding: 0 var(--space-3);
    border: 1px solid var(--accent);
    border-radius: var(--btn-radius);
    background: var(--accent);
    color: var(--on-accent);
    font-family: inherit;
    font-size: var(--text-13);
    font-weight: 500;
    cursor: pointer;
    transition: background var(--transition), transform var(--transition);
  }
  .today-go:hover { background: var(--accent-strong); border-color: var(--accent-strong); }
  .today-go:active { transform: scale(0.96); }

  /* ---- 三格 ----
     原来三格等分、每格 16px 内边距、只有一根 1px 分隔线,
     格子之间没有任何「这是不同主题」的区分手段。
     现在心情格用冷蓝竖条强调(它是这页唯一会变的数值),
     日记格加宽(它是这页最长的一段文字), 待跟进保持窄。
     数字全部走等宽 + tabular-nums, 让 3px 的进度条有可比的读数。 */
  .today-grid {
    display: grid;
    grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.6fr) minmax(0, 1fr);
    border-bottom: 1px solid var(--border);
  }
  .tcell {
    padding: var(--space-5);
    border-right: 1px solid var(--border);
    min-width: 0;
  }
  .tcell.tcell-last { border-right: none; }
  .tcell .micro-label { margin-bottom: var(--space-3); }
  .tcell-mood { border-left: 2px solid var(--accent); }
  .tcell-main {
    font-size: var(--text-2xl);
    font-weight: 500;
    letter-spacing: var(--tracking-tight);
    color: var(--text-1);
    line-height: 1.1;
    margin-bottom: var(--space-3);
  }
  .ttrack {
    height: 4px;
    background: var(--surface-3);
    overflow: hidden;
    margin-bottom: var(--space-3);
    border-radius: var(--radius-full);
  }
  .tfill {
    display: block;
    height: 100%;
    background: var(--accent);
    border-radius: var(--radius-full);
    transition: width var(--transition-slow);
  }
  .tcell-note {
    margin: 0;
    font-size: var(--text-13);
    line-height: 1.72;
    color: var(--text-3);
  }
  .tcell-body {
    margin: 0;
    font-size: var(--text-15);
    line-height: 1.78;
    color: var(--text-1);
    display: -webkit-box;
    -webkit-line-clamp: 6;
    line-clamp: 6;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .tlist { margin: 0; padding: 0; list-style: none; }
  .tlist li {
    position: relative;
    padding-left: 14px;
    margin-bottom: var(--optical-7);
    font-size: var(--text-13);
    line-height: 1.62;
    color: var(--text-1);
  }
  .tlist li::before {
    content: '';
    position: absolute;
    left: 0;
    top: 9px;
    width: 5px;
    height: 1px;
    background: var(--accent);
  }
  .tdate { margin-left: var(--optical-6); font-size: var(--text-2xs); color: var(--text-3); }

  .trow {
    padding: var(--space-5);
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
  /* 记得的事: 原来是 surface-2 实底色块, 四条记忆就是四条整行灰条,
     读起来像一排按钮。改成「描边 + 次一级文字」, 块退成标注, 内容回到第一层。 */
  .tchips { display: flex; flex-wrap: wrap; gap: var(--optical-6); }
  .tchip {
    font-size: var(--text-13);
    line-height: 1.55;
    color: var(--text-2);
    background: transparent;
    border: 1px solid var(--border);
    border-radius: var(--radius-xs);
    padding: var(--optical-4) 8px;
    max-width: 100%;
    /* 原来 nowrap + ellipsis: 三条记忆各占一整行却只读到半句,
       最长的两条被截在「他提到了「团子」…」。放开到两行,
       clamp 兜住超长的, 一行放得下的自然还是一行。 */
    white-space: normal;
    overflow: hidden;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
  }
  .tcell-rel {
    margin: 0;
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    font-size: var(--text-15);
    color: var(--text-1);
  }
  .trel-stage {
    font-size: var(--text-2xs);
    letter-spacing: var(--tracking-wide);
    color: var(--accent);
    background: var(--accent-wash);
    padding: var(--hair) var(--optical-7);
    border-radius: var(--radius-xs);
  }
  .trel-num {
    font-size: var(--text-2xs);
    color: var(--text-3);
  }
  .tlink {
    flex: none;
    border: none;
    background: transparent;
    padding: 0;
    font-family: inherit;
    font-size: var(--text-13);
    color: var(--accent);
    cursor: pointer;
    transition: opacity var(--transition);
  }
  .tlink:hover { opacity: 0.72; }

  .today-empty {
    padding: var(--space-6) var(--space-5);
    font-size: var(--text-13);
    color: var(--text-3);
    border-left: 2px solid var(--border-strong);
    margin: var(--space-5);
  }

  @media (max-width: 767px) {
    .today-head { padding: var(--space-4); }
    .today-grid {
      grid-template-columns: minmax(0, 1fr);
    }
    .tcell {
      border-right: none;
      border-bottom: 1px solid var(--border);
      padding: var(--space-4);
    }
    .tcell.tcell-mood { border-left-width: 2px; }
    .tcell.tcell-last { border-bottom: none; }
    .trow { padding: var(--space-4); }
  }
</style>
