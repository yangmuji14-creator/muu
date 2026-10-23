<script>
  // ============================================================
  // MemoryPage.svelte — 记忆: 重要记忆 + 大脑日记
  //
  // 重要记忆:
  //   GET /api/memory?conversation_id=&persona_id=&offset=&limit=&level_min=&level_max=
  //     -> { messages:[...], total:N }   (key WEN messages)
  //   每条 {id,content,level,category,created_at,tags,source,confidence,last_accessed}
  //   详情 GET /api/memory/{id}?conversation_id=&persona_id= -> 含 access_count,
  //        related_memory_ids,superseded_by,forget_score,archived
  //   删除 DELETE /api/memory/{id}?conversation_id=&persona_id=
  //
  // 大脑日记:
  //   GET /api/life_summary?persona_id=&conversation_id=&limit=20 -> {summaries,total}
  //   每条 {id,summary_type,summary,recent_status,key_events,message_count,created_at,emotional_trends}
  //   GET /api/life_summary/latest -> 可能返回 null
  // ============================================================
import { get, del } from '../lib/pages-api.js';
import { friendlyTime } from '../lib/format.js';
import { confirmDialog } from '../lib/dialog.svelte.js';
import { session, stateRevision, ensureActiveConversation } from '../lib/session.svelte.js';
import Toast from '../components/Toast.svelte';

  const LIMIT = 20;

  let tab = $state('memory'); // 'memory' | 'diary'

  // ---- 重要记忆 ----
  let messages = $state([]);
  let total = $state(0);
  let offset = $state(0);
  let loading = $state(true);
  let loadingMore = $state(false);
  let openId = $state(null);
  let detailMap = $state({}); // id -> detail dict
  let loadingDetailId = $state(null);

  // ---- 大脑日记 ----
  let summaries = $state([]);
  let summaryTotal = $state(0);
  let diaryLoading = $state(true);
  let diaryLoadingMore = $state(false);
  let summaryOffset = $state(0);
  let latest = $state(null); // 最新摘要(可为 null)
  let latestLoading = $state(true);

  let toast = $state(null);
  let toastTimer = null;

  function qs(extra = {}) {
    // 必须带上当前会话 / 人设，否则后端会回退到空的默认作用域（web_user），
    // 永远查不到这个会话里产生的记忆。
    const p = new URLSearchParams();
    if (session.conversationId) p.set('conversation_id', session.conversationId);
    if (session.personaId) p.set('persona_id', session.personaId);
    for (const [k, v] of Object.entries(extra)) {
      if (v !== undefined && v !== null && v !== '') p.set(k, v);
    }
    return p.toString();
  }

  function showToast(text, type = 'info') {
    toast = { text, type };
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast = null), 2400);
  }

  async function loadMemory(reset = true) {
    if (reset) {
      loading = true;
      messages = [];
      offset = 0;
      total = 0;
      openId = null;
      detailMap = {};
      const r = await get(`/api/memory?${qs({ offset: 0, limit: LIMIT, level_min: 1, level_max: 5 })}`);
      loading = false;
      if (r.ok) {
        messages = r.data.messages || [];
        total = r.data.total ?? messages.length;
        offset = messages.length;
      } else {
        showToast(r.data?.error || r.data?.detail || '加载记忆失败', 'error');
      }
    } else {
      loadingMore = true;
      const r = await get(`/api/memory?${qs({ offset, limit: LIMIT, level_min: 1, level_max: 5 })}`);
      loadingMore = false;
      if (r.ok) {
        messages = [...messages, ...(r.data.messages || [])];
        total = r.data.total ?? messages.length;
        offset = messages.length;
      } else {
        showToast(r.data?.error || '加载更多失败', 'error');
      }
    }
  }

  async function toggleDetail(m) {
    if (openId === m.id) {
      openId = null;
      return;
    }
    openId = m.id;
    if (detailMap[m.id]) return;
    loadingDetailId = m.id;
    const r = await get(`/api/memory/${m.id}?${qs()}`);
    loadingDetailId = null;
    if (r.ok && r.data) {
      detailMap[m.id] = r.data;
    } else {
      showToast(r.data?.error || r.data?.detail || '加载详情失败', 'error');
    }
  }

  async function removeMemory(m) {
    const ok = await confirmDialog('确定删除这条记忆吗？此操作不可恢复。', { title: '删除记忆', danger: true });
    if (!ok) return;
    const r = await del(`/api/memory/${m.id}?${qs()}`);
    if (r.ok) {
      showToast('记忆已删除', 'success');
      if (openId === m.id) openId = null;
      messages = messages.filter((x) => x.id !== m.id);
      total = Math.max(0, total - 1);
    } else {
      showToast(r.data?.error || r.data?.detail || '删除失败', 'error');
    }
  }

  // ---- 大脑日记 ----
  async function loadDiary(reset = true) {
    const loadLatest = async () => {
      latestLoading = true;
      // 必须带会话作用域，否则后端回退到默认作用域，读到的不是当前会话的摘要
      const r = await get(`/api/life_summary/latest?${qs()}`);
      latestLoading = false;
      if (r.ok) latest = r.data || null;
      else latest = null;
    };
    if (reset) {
      diaryLoading = true;
      summaries = [];
      summaryOffset = 0;
      summaryTotal = 0;
      const [r] = await Promise.all([get(`/api/life_summary?${qs({ limit: LIMIT })}`), loadLatest()]);
      diaryLoading = false;
      if (r.ok) {
        summaries = r.data.summaries || [];
        summaryTotal = r.data.total ?? summaries.length;
        summaryOffset = summaries.length;
      } else {
        showToast(r.data?.error || r.data?.detail || '加载日记失败', 'error');
      }
    } else {
      diaryLoadingMore = true;
      const r = await get(`/api/life_summary?${qs({ limit: LIMIT, offset: summaryOffset })}`);
      diaryLoadingMore = false;
      if (r.ok) {
        summaries = [...summaries, ...(r.data.summaries || [])];
        summaryTotal = r.data.total ?? summaries.length;
        summaryOffset = summaries.length;
      } else {
        showToast(r.data?.error || '加载更多失败', 'error');
      }
    }
  }

  function levelColor(lv) {
    // 重要度 1-5 -> 语义色
    if (lv >= 5) return 'var(--error)';
    if (lv >= 4) return 'var(--warning)';
    if (lv >= 3) return 'var(--accent)';
    if (lv >= 2) return 'var(--info)';
    return 'var(--text-3)';
  }

  $effect(() => {
    // 依赖：当前标签 / 会话 / 刷新信号。聊天结束后自动重新拉取，无需手动刷新。
    const _cid = session.conversationId;
    const _rev = stateRevision.n;
    void _cid;
    void _rev;
    (async () => {
      // 没进过聊天页时 session 可能还是空的，先解析出活动会话再查
      if (!session.conversationId) await ensureActiveConversation();
      if (tab === 'memory') loadMemory(true);
      else loadDiary(true);
    })();
  });
</script>

<svelte:head><title>记忆 · 慕</title></svelte:head>

<Toast {toast} />

<div class="page">
  <header class="page-top">
    <div class="page-top-main">
      <span class="micro-label">记忆库</span>
      <h1 class="page-title">记忆</h1>
      <p class="page-lede">对话里被她判定为重要的事会沉淀在这里，也会整理成日记。</p>
    </div>
  </header>

  <div class="tabs" role="tablist">
    <button class="tab-btn {tab === 'memory' ? 'is-active' : ''}" role="tab" type="button" onclick={() => (tab = 'memory')}>
      重要记忆
      {#if messages.length > 0}<span class="tab-count mono">{messages.length}</span>{/if}
    </button>
    <button class="tab-btn {tab === 'diary' ? 'is-active' : ''}" role="tab" type="button" onclick={() => (tab = 'diary')}>
      大脑日记
      {#if summaries.length > 0}<span class="tab-count mono">{summaries.length}</span>{/if}
    </button>
  </div>

  {#if tab === 'memory'}
    <!-- ============ 重要记忆 ============ -->
    {#if loading}
      <div class="empty-state"><p class="empty-desc">加载中…</p></div>
    {:else if messages.length === 0}
      <div class="empty-state">
        <span class="empty-icon"><svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2a7 7 0 0 0-7 7c0 2.4 1.2 4.1 2.5 5.5.7.8 1 1.6 1 2.5v1h7v-1c0-.9.3-1.7 1-2.5C17.8 13.1 19 11.4 19 9a7 7 0 0 0-7-7z"/><line x1="9" y1="22" x2="15" y2="22"/></svg></span>
        <p class="empty-title">还没有重要记忆</p>
        <p class="empty-desc">多聊几轮之后，值得留下的片段会自动沉淀到这里。也可以在聊天里直接说「记住这件事」。</p>
      </div>
    {:else}
      <div class="list">
        {#each messages as m (m.id)}
          <div class="mem-item">
            <button class="mem-main" type="button" onclick={() => toggleDetail(m)}>
              <div class="mem-head">
                <span class="mem-level" style="background:{levelColor(m.level)}" title="重要度 {m.level}"></span>
                <span class="mem-category">{m.category || '未分类'}</span>
                {#if m.archived}<span class="mem-archived">已归档</span>{/if}
                <span class="mem-time">{friendlyTime(m.created_at)}</span>
                {#if m.source}<span class="mem-source">{m.source}</span>{/if}
              </div>
              <p class="mem-content">{m.content}</p>
              <div class="mem-tags">
                <span class="mem-meta">重要度 {m.level}</span>
                {#each (m.tags || []).slice(0, 5) as t (t)}
                  <span class="tag">#{t}</span>
                {/each}
              </div>
            </button>

            {#if openId === m.id}
              <div class="mem-detail">
                {#if loadingDetailId === m.id}
                  <p class="empty-desc">加载详情…</p>
                {:else if detailMap[m.id]}
                  {@const d = detailMap[m.id]}
                  {#if d.access_count != null}
                    <div class="detail-row"><span class="detail-k">访问次数</span><span class="detail-v">{d.access_count}</span></div>
                  {/if}
                  {#if d.confidence != null}
                    <div class="detail-row">
                      <span class="detail-k">置信度</span>
                      <span class="detail-v">{Number(d.confidence).toFixed(2)}</span>
                    </div>
                  {/if}
                  {#if d.forget_score != null}
                    <div class="detail-row">
                      <span class="detail-k">遗忘指数</span>
                      <span class="detail-v">{Number(d.forget_score).toFixed(3)}</span>
                    </div>
                  {/if}
                  {#if d.archived != null}
                    <div class="detail-row"><span class="detail-k">已归档</span><span class="detail-v">{d.archived ? '是' : '否'}</span></div>
                  {/if}
                  {#if d.superseded_by}
                    <div class="detail-row"><span class="detail-k">已被取代</span><span class="detail-v">{typeof d.superseded_by === 'object' ? JSON.stringify(d.superseded_by) : d.superseded_by}</span></div>
                  {/if}
                  {#if (d.related_memory_ids || []).length > 0}
                    <div class="detail-row"><span class="detail-k">关联记忆</span><span class="detail-v">{(d.related_memory_ids || []).join(', ')}</span></div>
                  {/if}
                  {#if d.last_accessed}
                    <div class="detail-row"><span class="detail-k">上次访问</span><span class="detail-v">{friendlyTime(d.last_accessed)}</span></div>
                  {/if}
                {/if}
                <button class="btn btn-outline btn-sm del-btn" type="button" onclick={() => removeMemory(m)}>删除此记忆</button>
              </div>
            {/if}
          </div>
        {/each}
      </div>

      {#if offset < total}
        <div class="load-more">
          <button class="btn btn-outline" type="button" disabled={loadingMore} onclick={() => loadMemory(false)}>
            {loadingMore ? '加载中…' : `加载更多 (${offset}/${total})`}
          </button>
        </div>
      {/if}
    {/if}

  {:else}
    <!-- ============ 大脑日记 ============ -->
    {#if latest}
      <div class="latest">
        <div class="latest-head">
          <span class="latest-badge">最新摘要</span>
          <span class="latest-time">{friendlyTime(latest.created_at)}</span>
        </div>
        <p class="latest-summary">{latest.summary}</p>
        {#if (latest.key_events || []).length > 0}
          <div class="tags-row">
            {#each (latest.key_events || []).slice(0, 8) as e (e)}
              <span class="tag">{e}</span>
            {/each}
          </div>
        {/if}
      </div>
    {/if}

    {#if diaryLoading}
      <div class="empty-state"><p class="empty-desc">加载中…</p></div>
    {:else if summaries.length === 0}
      <div class="empty-state">
        <span class="empty-icon"><svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg></span>
        <p class="empty-title">还没有大脑日记</p>
        <p class="empty-desc">积累到一定量的对话之后，记忆会被整理成周期性总结。先聊聊看。</p>
      </div>
    {:else}
      <div class="diary-list">
        {#each summaries as s (s.id)}
          <article class="diary">
            <header class="diary-head">
              <span class="diary-type">{s.summary_type || '总结'}</span>
              <span class="diary-time">{friendlyTime(s.created_at)}</span>
            </header>
            <p class="diary-summary">{s.summary}</p>

            {#if (s.key_events || []).length > 0}
              <div class="block">
                <span class="block-label">关键事件</span>
                <div class="tags-row">
                  {#each (s.key_events || []) as e (e)}
                    <span class="tag">{e}</span>
                  {/each}
                </div>
              </div>
            {/if}

            {#if s.recent_status || s.emotional_trends}
              <div class="block">
                {#if s.recent_status}
                  <div class="kv"><span class="kv-k">近期状态</span><span class="kv-v">{s.recent_status}</span></div>
                {/if}
                {#if s.emotional_trends}
                  <div class="kv"><span class="kv-k">情绪趋势</span><span class="kv-v">{typeof s.emotional_trends === 'object' ? JSON.stringify(s.emotional_trends) : s.emotional_trends}</span></div>
                {/if}
              </div>
            {/if}

            {#if s.message_count != null}
              <footer class="diary-foot">共 {s.message_count} 条消息</footer>
            {/if}
          </article>
        {/each}
      </div>

      {#if summaryOffset < summaryTotal}
        <div class="load-more">
          <button class="btn btn-outline" type="button" disabled={diaryLoadingMore} onclick={() => loadDiary(false)}>
            {diaryLoadingMore ? '加载中…' : `加载更多 (${summaryOffset}/${summaryTotal})`}
          </button>
        </div>
      {/if}
    {/if}
  {/if}
</div>

<style>
  .page {
    padding: var(--space-6) var(--space-6) var(--space-8);
    max-width: 820px;
    margin: 0;
  }

  /* ---- 页头: 与通讯录/发现同一套骨架 ---- */
  .page-top {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: var(--space-4);
    padding-bottom: var(--space-4);
    margin-bottom: var(--space-4);
    border-bottom: 1px solid var(--border-strong);
  }
  .page-top-main { min-width: 0; display: flex; flex-direction: column; }
  .page-title {
    margin: 0;
    font-size: var(--text-display);
    font-weight: 600;
    letter-spacing: var(--tracking-tight);
    line-height: 1.12;
    color: var(--text-1);
  }
  .page-lede {
    margin: var(--optical-6) 0 0;
    font-size: var(--text-13);
    line-height: 1.65;
    color: var(--text-2);
    max-width: 52ch;
  }

  /* 分段切换 -> 下划线标签 (与 Ink 语言一致, 不用药丸底)
     加了等宽计数, 让「重要记忆 12 / 大脑日记 3」一眼看出有多少内容,
     空 tab 也能立刻判断该不该点进去。 */
  .tabs {
    display: flex;
    gap: var(--space-5);
    margin-bottom: var(--space-5);
    padding: 0;
    background: transparent;
    border-bottom: 1px solid var(--border);
  }
  .tab-btn {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-3) 0;
    margin-bottom: -1px;
    border: none;
    border-bottom: 2px solid transparent;
    background: transparent;
    color: var(--text-3);
    font-size: var(--text-sm);
    font-weight: 500;
    letter-spacing: var(--tracking-tight);
    cursor: pointer;
    transition: color var(--transition), border-color var(--transition);
  }
  .tab-btn:hover { color: var(--text-2); }
  .tab-btn.is-active {
    color: var(--text-1);
    border-bottom-color: var(--accent);
  }
  .tab-count {
    font-size: var(--text-2xs);
    color: var(--text-3);
    background: var(--surface-2);
    padding: var(--hair) var(--optical-6);
    border-radius: var(--radius-xs);
  }
  .tab-btn.is-active .tab-count {
    color: var(--accent);
    background: var(--accent-wash);
  }

  /* ---- 重要记忆 ----
     从「一张张卡片」改成「细线分隔的条目」: 卡片(1px 边 + 6px 圆角 + 8px 间距)
     在长列表里会变成一堆并排的小盒子, 读起来像表单而不是内容流。
     条目化之后行与行之间只有一条线, 视觉密度上去、噪声下来。 */
  .list {
    display: flex;
    flex-direction: column;
    gap: 0;
    border-top: 1px solid var(--border);
  }
  .mem-item {
    background: transparent;
    border: none;
    border-bottom: 1px solid var(--border);
    border-radius: 0;
    box-shadow: none;
    overflow: hidden;
    transition: background var(--transition);
  }
  .mem-item:hover { background: var(--row-hover); }
  .mem-main {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-4) var(--space-3) var(--space-4) var(--space-4);
    border: none;
    background: transparent;
    text-align: left;
    cursor: pointer;
    color: var(--text-1);
  }
  .mem-head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  /* 重要度从 10px 色块改成 3px 竖条: 色块像「状态灯」, 竖条像「刻度」 */
  .mem-level {
    width: 3px;
    height: 13px;
    border-radius: 0;
    flex: none;
  }
  .mem-category {
    font-size: var(--text-2xs);
    font-weight: 500;
    letter-spacing: var(--tracking-wide);
    color: var(--text-2);
    background: transparent;
    border: 1px solid var(--border);
    padding: var(--hair) var(--optical-6);
    border-radius: var(--radius-xs);
  }
  .mem-time {
    font-size: var(--text-xs);
    color: var(--text-3);
    margin-left: auto;
    font-variant-numeric: tabular-nums;
  }
  .mem-archived {
    font-size: var(--text-2xs);
    font-weight: 500;
    letter-spacing: var(--tracking-wide);
    color: var(--text-3);
    border: 1px dashed var(--border-strong);
    padding: var(--hair) var(--optical-6);
    border-radius: var(--radius-xs);
  }
  .mem-source {
    font-size: var(--text-2xs);
    color: var(--text-3);
    letter-spacing: var(--tracking-wide);
  }
  .mem-content {
    margin: 0;
    font-size: var(--text-15);
    line-height: 1.72;
    color: var(--text-1);
  }
  .mem-tags {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
  }
  .mem-meta {
    font-size: var(--text-2xs);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .tag {
    font-size: var(--text-2xs);
    color: var(--text-2);
    background: var(--surface-2);
    padding: var(--hair) var(--optical-6);
    border-radius: var(--radius-xs);
    letter-spacing: 0.02em;
  }
  .mem-detail {
    padding: var(--space-3) var(--space-4) var(--space-4) var(--space-5);
    border-top: 1px solid var(--border);
    background: var(--surface-2);
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .detail-row {
    display: flex;
    gap: var(--space-3);
    font-size: var(--text-sm);
  }
  .detail-k {
    flex: none;
    width: 72px;
    color: var(--text-3);
  }
  .detail-v {
    color: var(--text-1);
    word-break: break-word;
  }
  .del-btn {
    align-self: flex-end;
    color: var(--error);
    border-color: var(--error);
    margin-top: var(--space-1);
  }

  /* ---- 大脑日记 ----
     latest 从「无底色的左蓝条块」变成「浅底 + 左冷蓝条 + 顶部微标签」,
     现在它看起来确实是「置顶摘要」而不是随便一段文字。
     原配色是 accent 实底 + 白字, 在页面里是一块高饱和蓝块, 过于抢眼;
     改成 wash 底 + accent 字, 保持强调但不压过正文。 */
  .latest {
    padding: var(--space-4);
    margin-bottom: var(--space-5);
    background: var(--accent-wash);
    border-left: 2px solid var(--accent);
    border-radius: 0 var(--radius) var(--radius) 0;
  }
  .latest-head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin-bottom: var(--space-2);
  }
  .latest-badge {
    font-size: var(--text-2xs);
    font-weight: 500;
    letter-spacing: var(--tracking-wide);
    color: var(--accent);
    background: transparent;
    border: 1px solid var(--accent-line);
    padding: var(--hair) var(--optical-7);
    border-radius: var(--radius-xs);
  }
  .latest-time { font-size: var(--text-xs); color: var(--text-3); margin-left: auto; }
  .latest-summary {
    margin: 0;
    font-size: var(--text-15);
    line-height: 1.75;
    color: var(--text-1);
  }

  .diary-list {
    display: flex;
    flex-direction: column;
    gap: 0;
    border-top: 1px solid var(--border);
  }
  .diary {
    padding: var(--space-4) 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    border-bottom: 1px solid var(--border);
    border-radius: 0;
    background: transparent;
  }
  .diary-head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .diary-type {
    font-size: var(--text-2xs);
    font-weight: 500;
    letter-spacing: var(--tracking-wide);
    color: var(--text-2);
    background: transparent;
    border: 1px solid var(--border);
    padding: var(--hair) var(--optical-7);
    border-radius: var(--radius-xs);
  }
  .diary-time {
    font-size: var(--text-xs);
    color: var(--text-3);
    margin-left: auto;
    font-variant-numeric: tabular-nums;
  }
  .diary-summary {
    margin: 0;
    font-size: var(--text-15);
    line-height: 1.75;
    color: var(--text-1);
  }
  .block {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    background: var(--surface-2);
    border-radius: var(--radius);
  }
  .block-label {
    font-size: var(--text-2xs);
    font-weight: 500;
    letter-spacing: var(--tracking-wide);
    color: var(--text-3);
  }
  .tags-row { display: flex; flex-wrap: wrap; gap: var(--optical-6); }
  .kv { display: flex; gap: var(--space-3); font-size: var(--text-13); }
  .kv-k { flex: none; color: var(--text-3); }
  .kv-v { color: var(--text-1); word-break: break-word; }
  .diary-foot {
    font-size: var(--text-xs);
    color: var(--text-3);
    padding-top: var(--space-2);
  }

  .load-more {
    display: flex;
    justify-content: center;
    margin-top: var(--space-5);
  }

  .btn {
    display: inline-flex; align-items: center; justify-content: center; gap: var(--optical-6);
    border-radius: var(--btn-radius); font-size: var(--text-sm);
    font-weight: 500; letter-spacing: var(--tracking-tight);
    cursor: pointer; border: 1px solid transparent; white-space: nowrap;
    transition: background var(--transition), border-color var(--transition), transform var(--transition), box-shadow var(--transition);
  }
  .btn:disabled { opacity: 0.55; cursor: not-allowed; }
  .btn:active:not(:disabled) { transform: scale(0.97); }
  .btn-outline {
    height: var(--btn-h-md); padding: 0 var(--space-4);
    background: var(--btn-outline-bg); border-color: var(--btn-outline-border); color: var(--btn-outline-text);
  }
  .btn-outline:hover:not(:disabled) { background: var(--btn-outline-hover); }
  .btn-sm { height: var(--btn-h-sm); padding: 0 var(--space-3); font-size: var(--text-xs); }

  /* ---- 空状态 ---- */
  .empty-state {
    display: flex; flex-direction: column; align-items: flex-start; text-align: left;
    gap: var(--space-2); padding: var(--space-5) 0 var(--space-5) var(--space-4);
    border-left: 2px solid var(--border-strong);
  }
  .empty-icon { display: inline-flex; color: var(--empty-icon); margin-bottom: var(--space-1); }
  .empty-title {
    margin: 0;
    font-size: var(--text-lg);
    font-weight: 600;
    letter-spacing: var(--tracking-tight);
    color: var(--text-1);
    line-height: 1.3;
  }
  .empty-desc {
    margin: 0;
    font-size: var(--text-13);
    line-height: 1.72;
    color: var(--text-2);
    max-width: 46ch;
  }
</style>
