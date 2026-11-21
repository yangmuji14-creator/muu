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
  let query = $state('');
  let category = $state('');
  let tag = $state('');
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

  const dayFormatter = new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: 'long', day: 'numeric',
  });

  function tagsOf(memory) {
    return Array.isArray(memory.tags) ? memory.tags : [];
  }

  function memoryCategory(memory) {
    return memory.category || '未分类';
  }

  function dayGroups(entries) {
    const groups = new Map();
    const timestamp = (entry) => Date.parse(entry.created_at) || 0;
    for (const entry of [...entries].sort((left, right) => timestamp(right) - timestamp(left))) {
      const date = new Date(entry.created_at);
      const label = entry.created_at && !Number.isNaN(date.getTime()) ? dayFormatter.format(date) : '日期未知';
      if (!groups.has(label)) groups.set(label, []);
      groups.get(label).push(entry);
    }
    return [...groups].map(([label, items]) => ({ label, items }));
  }

  let categories = $derived([...new Set(messages.map(memoryCategory))]);
  let tags = $derived([...new Set(messages.flatMap(tagsOf))]);
  let visibleMemories = $derived.by(() => {
    const needle = query.trim().toLowerCase();
    return messages.filter((entry) => {
      const name = memoryCategory(entry);
      const entryTags = tagsOf(entry);
      return (!category || category === name)
        && (!tag || entryTags.includes(tag))
        && (!needle || [entry.content, name, ...entryTags].some((text) => String(text ?? '').toLowerCase().includes(needle)));
    });
  });
  let memoryDays = $derived(dayGroups(visibleMemories));
  let diaryDays = $derived(dayGroups(summaries));

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
      offset = messages.length;
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
    const cid = session.conversationId;
    const currentTab = tab;
    void stateRevision.n;
    let active = true;
    (async () => {
      if (!cid) await ensureActiveConversation();
      if (!active) return;
      if (currentTab === 'memory') loadMemory(true);
      else loadDiary(true);
    })();
    return () => { active = false; };
  });
</script>

<svelte:head><title>记忆 · 慕</title></svelte:head>

<Toast {toast} />

<div class="page">
  <header class="page-top">
    <div class="page-top-main">
      <h1 class="page-title">记忆</h1>
      <p class="page-lede">回看重要片段和日记。</p>
    </div>
  </header>

  <div class="tabs" role="tablist" aria-label="记忆视图">
    <button class="tab-btn {tab === 'memory' ? 'is-active' : ''}" role="tab" aria-selected={tab === 'memory'} type="button" onclick={() => (tab = 'memory')}>
      重要记忆
      {#if messages.length > 0}<span class="tab-count mono">{messages.length}</span>{/if}
    </button>
    <button class="tab-btn {tab === 'diary' ? 'is-active' : ''}" role="tab" aria-selected={tab === 'diary'} type="button" onclick={() => (tab = 'diary')}>
      大脑日记
      {#if summaries.length > 0}<span class="tab-count mono">{summaries.length}</span>{/if}
    </button>
  </div>

  {#if tab === 'memory'}
    <!-- ============ 重要记忆 ============ -->
    {#if loading}
      <div class="empty-state" role="status"><p class="empty-desc">加载中…</p></div>
    {:else if messages.length === 0}
      <div class="empty-state">
        <span class="empty-icon"><svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2a7 7 0 0 0-7 7c0 2.4 1.2 4.1 2.5 5.5.7.8 1 1.6 1 2.5v1h7v-1c0-.9.3-1.7 1-2.5C17.8 13.1 19 11.4 19 9a7 7 0 0 0-7-7z"/><line x1="9" y1="22" x2="15" y2="22"/></svg></span>
        <p class="empty-title">还没有重要记忆</p>
        <p class="empty-desc">多聊几轮之后，值得留下的片段会自动沉淀到这里。也可以在聊天里直接说「记住这件事」。</p>
      </div>
    {:else}
      <div class="memory-filters">
        <div class="filter-controls">
          <label class="search">
            <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/></svg>
            <input type="search" bind:value={query} aria-label="搜索已加载的记忆" placeholder="搜索已加载的记忆" />
          </label>
          <select class="category-filter" aria-label="按分类筛选" bind:value={category}>
            <option value="">全部分类</option>
            {#if category && !categories.includes(category)}<option value={category}>{category}</option>{/if}
            {#each categories as name (name)}<option value={name}>{name}</option>{/each}
          </select>
        </div>
        {#if tags.length || tag}
          <div class="filter-tags" role="group" aria-label="按标签筛选">
            <button class="filter-chip" type="button" aria-pressed={!tag} onclick={() => (tag = '')}>全部标签</button>
            {#if tag && !tags.includes(tag)}
              <button class="filter-chip" type="button" aria-pressed="true" onclick={() => (tag = '')}>#{tag}</button>
            {/if}
            {#each tags as name (name)}
              <button class="filter-chip" type="button" aria-pressed={tag === name} onclick={() => (tag = tag === name ? '' : name)}>#{name}</button>
            {/each}
          </div>
        {/if}
      </div>

      {#each memoryDays as day (day.label)}
        <section class="timeline">
          <h2 class="timeline-date">{day.label}</h2>
          <div class="list">
            {#each day.items as m (m.id)}
          <article class="mem-item" class:important={m.level >= 4}>
            <button class="mem-main" type="button" aria-expanded={openId === m.id} onclick={() => toggleDetail(m)}>
              <div class="mem-head">
                <span class="mem-level" style="background:{levelColor(m.level)}" title="重要度 {m.level}"></span>
                <span class="mem-category">{memoryCategory(m)}</span>
                {#if m.level >= 4}<span class="important-pill">重要</span>{/if}
                {#if m.archived}<span class="mem-archived">已归档</span>{/if}
                <span class="mem-time">{friendlyTime(m.created_at)}</span>
                {#if m.source}<span class="mem-source">{m.source}</span>{/if}
              </div>
              <p class="mem-content">{m.content}</p>
              <div class="mem-tags">
                <span class="mem-meta">重要度 {m.level}</span>
                {#each [...new Set(tagsOf(m))].slice(0, 5) as t (t)}
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
          </article>
            {/each}
          </div>
        </section>
      {:else}
        <div class="empty-state">
          <p class="empty-title">已加载的记忆中没有匹配结果</p>
          <button class="btn btn-outline" type="button" onclick={() => { query = ''; category = ''; tag = ''; }}>清除筛选</button>
        </div>
      {/each}

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
            {#each (latest.key_events || []).slice(0, 8) as e}
              <span class="tag">{e}</span>
            {/each}
          </div>
        {/if}
      </div>
    {/if}

    {#if diaryLoading}
      <div class="empty-state" role="status"><p class="empty-desc">加载中…</p></div>
    {:else if summaries.length === 0}
      <div class="empty-state">
        <span class="empty-icon"><svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg></span>
        <p class="empty-title">还没有大脑日记</p>
        <p class="empty-desc">积累到一定量的对话之后，记忆会被整理成周期性总结。先聊聊看。</p>
      </div>
    {:else}
      {#each diaryDays as day (day.label)}
        <section class="timeline">
          <h2 class="timeline-date">{day.label}</h2>
          <div class="diary-list">
            {#each day.items as s (s.id)}
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
                  {#each (s.key_events || []) as e}
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
        </section>
      {/each}

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
    max-width: 900px;
    margin-inline: auto;
    padding: clamp(16px, 4vw, 48px) clamp(12px, 4vw, 40px) var(--space-6);
  }

  .page-top { margin-bottom: var(--space-4); }
  .page-title {
    margin: 0;
    color: var(--text-1);
    font-size: clamp(1.8rem, 4vw, 2.9rem);
    font-weight: 700;
    letter-spacing: var(--tracking-tighter);
    line-height: var(--leading-tight);
  }

  .page-lede {
    margin: var(--space-2) 0 0;
    color: var(--text-2);
    font-size: var(--text-sm);
  }

  .tabs {
    display: inline-flex;
    flex-wrap: wrap;
    gap: var(--space-1);
    max-width: 100%;
    margin-bottom: var(--space-4);
    padding: var(--space-1);
    border-radius: var(--radius-pill);
    background: var(--field-fill);
  }

  .tab-btn, .btn, .filter-chip {
    min-height: 36px;
    padding: var(--space-1) var(--space-3);
    border: 0;
    border-radius: var(--radius-pill);
    background: transparent;
    color: var(--text-2);
    font: inherit;
    font-size: var(--text-13);
    font-weight: 600;
    cursor: pointer;
  }

  .tab-btn { display: inline-flex; align-items: center; gap: var(--space-1); }
  .tab-btn.is-active { background: var(--surface); box-shadow: var(--shadow-1); color: var(--accent); }
  .tab-btn:hover, .filter-chip:hover { color: var(--accent); }
  .tab-count { font-size: var(--text-xs); }
  .btn { background: var(--field-fill); }
  .btn:hover:enabled { background: var(--accent-soft); color: var(--accent); }
  .btn-outline { background: transparent; box-shadow: inset 0 0 0 1px var(--border); color: var(--text-1); }
  .btn-outline:hover:enabled { background: var(--accent-soft); color: var(--accent); }
  .btn-sm { min-height: 30px; padding-inline: var(--space-2); font-size: var(--text-xs); }
  .btn:disabled { opacity: 0.55; cursor: default; }

  .memory-filters { display: grid; gap: var(--space-2); margin-bottom: var(--space-4); }
  .filter-controls { display: flex; flex-wrap: wrap; gap: var(--space-2); }

  .search, .category-filter {
    min-height: 42px;
    padding: 0 var(--space-3);
    border: 0;
    border-radius: var(--radius-pill);
    background: var(--field-fill);
    color: var(--text-2);
  }

  .search { display: flex; flex: 1 1 210px; align-items: center; gap: var(--space-2); min-width: 0; }
  .search svg { flex: none; }
  .search:focus-within, .category-filter:focus { background: var(--field-fill-focus); box-shadow: var(--focus-ring); }
  .search input {
    width: 100%;
    min-width: 0;
    padding: 0;
    border: 0;
    border-radius: inherit;
    background: transparent;
    color: var(--text-1);
    font: inherit;
    font-size: var(--text-sm);
  }

  .search input::placeholder { color: var(--text-2); }
  .search input:focus { outline: 0; box-shadow: none; }
  .category-filter { max-width: 100%; font: inherit; font-size: var(--text-13); }

  .filter-tags {
    display: flex;
    gap: var(--space-1);
    padding: 3px;
    margin-inline: -3px;
    overflow-x: auto;
    scrollbar-width: thin;
  }

  .filter-chip { flex: none; min-height: 32px; background: var(--field-fill); white-space: nowrap; }
  .filter-chip[aria-pressed='true'] { background: var(--accent-soft); color: var(--accent); }

  .timeline {
    position: relative;
    padding-inline-start: var(--space-4);
    margin: 0 0 var(--space-4) var(--space-1);
    border-inline-start: 1px solid var(--surface-divider);
  }

  .timeline-date {
    position: relative;
    margin: 0 0 var(--space-2);
    color: var(--text-2);
    font-size: var(--text-13);
    font-weight: 650;
    font-variant-numeric: tabular-nums;
  }

  .timeline-date::before {
    position: absolute;
    top: 0.55em;
    inset-inline-start: calc(-1 * var(--space-4) - 4px);
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-soft);
    content: '';
  }

  .list, .diary-list { display: grid; gap: var(--space-2); }

  .mem-item, .latest, .diary, .empty-state {
    min-width: 0;
    border-radius: var(--radius-lg);
    background: var(--surface);
    box-shadow: var(--surface-stage-shadow);
  }

  .mem-item.important {
    background: linear-gradient(135deg, var(--warning-soft), transparent 54%), var(--surface);
  }

  .mem-main {
    display: grid;
    gap: var(--space-2);
    width: 100%;
    padding: var(--space-3) var(--space-4);
    border: 0;
    border-radius: inherit;
    background: transparent;
    color: var(--text-1);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }

  .mem-main:hover { background: var(--row-hover); }

  .mem-head, .mem-tags, .latest-head, .tags-row, .diary-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-2);
  }

  .mem-level { width: 6px; height: 6px; flex: none; border-radius: 50%; }
  .mem-time, .latest-time, .diary-time { margin-inline-start: auto; color: var(--text-2); font-size: var(--text-xs); font-variant-numeric: tabular-nums; }
  .mem-category { color: var(--text-1); font-size: var(--text-13); font-weight: 650; }
  .mem-meta, .mem-source, .mem-archived { color: var(--text-2); font-size: var(--text-xs); }

  .important-pill, .tag, .latest-badge, .diary-type {
    display: inline-flex;
    max-width: 100%;
    padding: var(--optical-2) var(--space-2);
    border-radius: var(--radius-pill);
    background: var(--accent-soft);
    color: var(--accent);
    font-size: var(--text-xs);
    overflow-wrap: anywhere;
  }

  .important-pill { background: var(--warning-soft); color: var(--warning); font-weight: 650; }
  .mem-content, .latest-summary, .diary-summary {
    margin: 0;
    color: var(--text-1);
    font-size: var(--text-15);
    line-height: 1.65;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .mem-detail {
    display: grid;
    gap: var(--space-2);
    padding: var(--space-3);
    margin: 0 var(--space-3) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--field-fill);
  }

  .detail-row, .kv { display: flex; flex-wrap: wrap; gap: var(--space-1) var(--space-2); justify-content: space-between; }
  .detail-k, .kv-k, .block-label, .diary-foot { color: var(--text-2); font-size: var(--text-xs); }
  .detail-v, .kv-v { color: var(--text-1); font-size: var(--text-13); overflow-wrap: anywhere; }
  .del-btn { justify-self: start; color: var(--error); }
  .del-btn:hover:enabled { background: var(--error-soft); color: var(--error); }

  .latest, .diary, .empty-state {
    display: grid;
    gap: var(--space-2);
    padding: clamp(14px, 3vw, 22px);
  }

  .latest { margin-bottom: var(--space-4); background: linear-gradient(135deg, var(--accent-soft), transparent 70%), var(--surface); }
  .block { display: grid; gap: var(--space-1); padding: var(--space-2) var(--space-3); border-radius: var(--radius-sm); background: var(--field-fill); }
  .diary-foot { text-align: end; }
  .load-more { display: flex; justify-content: center; margin-block: var(--space-3); }

  .empty-state { justify-items: center; padding-block: var(--space-5); text-align: center; }
  .empty-icon { display: grid; place-items: center; width: 48px; height: 48px; border-radius: var(--radius-md); background: var(--accent-soft); color: var(--accent); }
  .empty-title, .empty-desc { margin: 0; }
  .empty-title { color: var(--text-1); font-size: var(--text-base); font-weight: 650; }
  .empty-desc { color: var(--text-2); font-size: var(--text-13); }

  @media (max-width: 600px) {
    .page { padding-inline: var(--space-3); }
    .mem-main { padding-inline: var(--space-3); }
    .search input { font-size: var(--text-base); }
    .timeline { padding-inline-start: var(--space-3); }
    .timeline-date::before { inset-inline-start: calc(-1 * var(--space-3) - 4px); }
  }
</style>
