<script>
  // ============================================================
  // DiscoverPage.svelte — 发现 / 朋友圈  //
  // - GET /api/moments?limit=&offset= -> {moments:[...], has_more}
  // - 点赞  POST/DELETE /api/moments/{id}/like
  // - 评论  POST /api/moments/{id}/replies {text, reply_to?}
  // - 删除动态 DELETE /api/moments/{id}
  // - 删除评论 DELETE /api/moments/{id}/replies/{reply_id}
  // - 发布  POST /api/moments {text, author?} (作者下拉获取 GET /api/moments/personas)
  // - 加载更多 offset 用 limit 累加
  // ============================================================
import { get, post, del } from '../lib/pages-api.js';
import { friendlyTime } from '../lib/format.js';
import { confirmDialog } from '../lib/dialog.svelte.js';
import Avatar from '../components/Avatar.svelte';
import Toast from '../components/Toast.svelte';

  const LIMIT = 20;

  let moments = $state([]);
  let hasMore = $state(false);
  let offset = $state(0);
  let loading = $state(true);
  let loadingMore = $state(false);
  let toast = $state(null);
  let toastTimer = null;

  // 发布
  let publishOpen = $state(false);
  let newText = $state('');
  let newAuthor = $state('');
  let personas = $state([]);
  let publishing = $state(false);
  let authorLoading = $state(false);

  // 评论
  let openReplyId = $state(null);
  let replyDrafts = $state({}); // momentId -> text
  let replyTarget = $state(null); // {momentId, reply_id?, reply_to_label?}

  // 点赞本地覆盖: id -> bool
  let likedOverride = $state({});
  let liking = $state({});
  let replying = $state(false);
  let gallery = $state(null);

  function showDialog(node, selector) {
    node.showModal();
    node.querySelector(selector)?.focus();
  }

  function momentImages(moment) {
    const items = moment.images ?? moment.image_urls ?? moment.image_url;
    const images = Array.isArray(items) ? items : [items];
    return images.map((image) => typeof image === 'string' ? image : image?.url || image?.image_url)
      .filter((url) => typeof url === 'string' && url.trim());
  }

  function stepImage(offset) {
    if (gallery) gallery.index = (gallery.index + offset + gallery.urls.length) % gallery.urls.length;
  }

  function closeGallery(event) {
    event?.preventDefault();
    gallery = null;
  }

  function onGalleryKey(event) {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    stepImage(event.key === 'ArrowLeft' ? -1 : 1);
  }

  async function loadInitial() {
    loading = true;
    const r = await get(`/api/moments?limit=${LIMIT}&offset=0`);
    loading = false;
    if (r.ok) {
      moments = r.data.moments || [];
      offset = moments.length;
      hasMore = !!r.data.has_more;
    } else {
      moments = [];
      hasMore = false;
      showToast(r.data?.error || r.data?.detail || '加载失败', 'error');
    }
  }

  $effect(() => {
    loadInitial();
    loadPersonas();
  });

  async function loadPersonas() {
    authorLoading = true;
    const r = await get('/api/moments/personas');
    authorLoading = false;
    if (r.ok && Array.isArray(r.data?.personas)) personas = r.data.personas;
  }

  function showToast(text, type = 'info') {
    toast = { text, type };
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast = null), 2400);
  }

  // 轻量刷新: 拉取与当前相同数量的最新条目 (用于发布/评论后)
  async function reload(keepCount = moments.length) {
    const count = Math.max(keepCount, LIMIT);
    const r = await get(`/api/moments?limit=${count}&offset=0`);
    if (r.ok) {
      moments = r.data.moments || [];
      offset = moments.length;
      hasMore = !!r.data.has_more;
    }
  }

  async function loadMore() {
    if (loadingMore || !hasMore) return;
    loadingMore = true;
    const r = await get(`/api/moments?limit=${LIMIT}&offset=${offset}`);
    loadingMore = false;
    if (r.ok) {
      moments = [...moments, ...(r.data.moments || [])];
      offset = moments.length;
      hasMore = !!r.data.has_more;
    } else {
      showToast(r.data?.error || '加载更多失败', 'error');
    }
  }

  // ---- 点赞 ----
  function likedByMe(m) {
    if (likedOverride[m.id] !== undefined) return likedOverride[m.id];
    return m.liked_by_me === true || m.liked === true;
  }
  async function toggleLike(m) {
    if (liking[m.id]) return;
    liking[m.id] = true;
    const active = likedByMe(m);
    try {
      const r = active ? await del(`/api/moments/${m.id}/like`) : await post(`/api/moments/${m.id}/like`, {});
      if (!r.ok) {
        showToast(r.data?.error || r.data?.detail || (active ? '取消点赞失败' : '点赞失败'), 'error');
        return;
      }
      likedOverride[m.id] = !active;
      if (!active) {
        const likes = Array.isArray(m.likes) ? m.likes : [];
        m.likes = [...likes, { author: 'me', author_label: '我' }];
      } else {
        m.likes = (m.likes || []).filter((l) => l.author !== 'me' && l.author_label !== '我');
      }
    } catch {
      showToast('点赞请求失败，请重试', 'error');
    } finally {
      delete liking[m.id];
    }
  }

  // ---- 评论 ----
  function toggleReply(m) {
    if (openReplyId === m.id) {
      openReplyId = null;
      replyTarget = null;
    } else {
      openReplyId = m.id;
      replyTarget = null;
      if (replyDrafts[m.id] === undefined) replyDrafts[m.id] = '';
    }
  }
  function openReplyTo(m, rp) {
    openReplyId = m.id;
    if (replyDrafts[m.id] === undefined) replyDrafts[m.id] = '';
    replyTarget = { momentId: m.id, replyId: rp.id, replyToLabel: rp.author_label || rp.author };
  }
  function cancelReplyTo() {
    replyTarget = null;
  }

  function closeReply(event) {
    event?.preventDefault();
    openReplyId = null;
    replyTarget = null;
  }

  function closePublish(event) {
    event?.preventDefault();
    publishOpen = false;
  }
  async function submitReply(m) {
    const text = (replyDrafts[m.id] || '').trim();
    if (!text || replying) return;
    const body = { text };
    if (replyTarget?.momentId === m.id && replyTarget.replyId) body.reply_to = replyTarget.replyId;
    replying = true;
    try {
      const r = await post(`/api/moments/${m.id}/replies`, body);
      if (!r.ok) {
        showToast(r.data?.error || r.data?.detail || '评论失败', 'error');
        return;
      }
      replyDrafts[m.id] = '';
      if (openReplyId === m.id) closeReply();
      showToast('评论已发布', 'success');
      await reload();
    } catch {
      showToast('评论请求失败，请重试', 'error');
    } finally {
      replying = false;
    }
  }

  // ---- 删除 ----
  async function removeMoment(m) {
    const label = m.author_label || m.author || '该动态';
    const ok = await confirmDialog(`确定删除 ${label} 的这条动态吗？`, { title: '删除动态', danger: true });
    if (!ok) return;
    const r = await del(`/api/moments/${m.id}`);
    if (r.ok) {
      showToast('动态已删除', 'success');
      await reload();
    } else {
      showToast(r.data?.error || r.data?.detail || '删除失败', 'error');
    }
  }
  async function removeReply(m, rp) {
    const ok = await confirmDialog('确定删除这条评论吗？', { title: '删除评论', danger: true });
    if (!ok) return;
    const r = await del(`/api/moments/${m.id}/replies/${rp.id}`);
    if (r.ok) {
      showToast('评论已删除', 'success');
      await reload();
    } else {
      showToast(r.data?.error || r.data?.detail || '删除失败', 'error');
    }
  }

  // ---- 发布 ----
  function openPublish() {
    publishOpen = !publishOpen;
  }
  async function submitPublish() {
    const text = newText.trim();
    if (!text || publishing) return;
    publishing = true;
    const body = { text };
    if (newAuthor) body.author = newAuthor;
    try {
      const r = await post('/api/moments', body);
      if (!r.ok) {
        showToast(r.data?.error || r.data?.detail || '发布失败', 'error');
        return;
      }
      showToast('已发布', 'success');
      newText = '';
      newAuthor = '';
      publishOpen = false;
      await reload();
    } catch {
      showToast('发布请求失败，请重试', 'error');
    } finally {
      publishing = false;
    }
  }
</script>

<svelte:head><title>发现 · 慕</title></svelte:head>

<Toast {toast} />

<div class="page">
  <header class="page-top">
    <div class="page-top-main">
      <h1 class="page-title">发现</h1>
      <p class="page-lede">记录彼此的日常。</p>
    </div>
    <button class="btn btn-primary btn-sm" type="button" onclick={openPublish}>
      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
      发布
    </button>
  </header>

  {#if publishOpen}
    <dialog class="moment-dialog glass-3" aria-label="发布动态" oncancel={closePublish} use:showDialog={'.field-input'}>
      <form class="dialog-form" onsubmit={(event) => { event.preventDefault(); submitPublish(); }}>
        <header class="dialog-head">
          <h2>发布动态</h2>
          <button class="icon-btn" type="button" aria-label="关闭发布窗口" onclick={closePublish}>×</button>
        </header>
        <label class="field">
          <span class="field-label">正文</span>
          <textarea class="field-input" rows="4" placeholder="分享此刻…" bind:value={newText}></textarea>
        </label>
        <label class="field">
          <span class="field-label">{authorLoading ? '正在加载作者…' : '发布身份'}</span>
          <select class="field-input" bind:value={newAuthor}>
            <option value="">以我本人发布</option>
            {#each personas as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
          </select>
        </label>
        {#if toast?.type === 'error'}<p class="dialog-feedback" role="alert">{toast.text}</p>{/if}
        <div class="form-actions">
          <button class="btn btn-outline" type="button" onclick={closePublish}>取消</button>
          <button class="btn btn-primary" type="submit" disabled={publishing || !newText.trim()}>
            {publishing ? '发布中…' : '发布'}
          </button>
        </div>
      </form>
    </dialog>
  {/if}

  {#if loading}
    <div class="empty-state" role="status"><p class="empty-desc">加载中…</p></div>
  {:else if moments.length === 0}
    <div class="empty-state">
      <span class="empty-icon"><svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg></span>
      <p class="empty-title">还没有动态</p>
      <p class="empty-desc">点右上角「发布」写下此刻。用她的人设发一条，她会在之后的对话里记得。</p>
      <button class="btn btn-primary empty-btn" type="button" onclick={openPublish}>
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        发布第一条
      </button>
    </div>
  {:else}
    <div class="timeline">
      {#each moments as m (m.id)}
        {@const images = momentImages(m)}
        <article class="moment">
          <header class="moment-head">
            <Avatar name={m.author_label || m.author || '?'} src={m.author_avatar || ''} size={42} />
            <div class="moment-meta">
              <span class="moment-author">{m.author_label || m.author || '匿名'}</span>
              <span class="moment-time">{friendlyTime(m.timestamp)}</span>
            </div>
            <button class="icon-btn ghost del-btn" type="button" title="删除动态" aria-label="删除这条动态" onclick={() => removeMoment(m)}>
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            </button>
          </header>

          {#if m.text}<p class="moment-text">{m.text}</p>{/if}

          {#if images.length}
            <div class="moment-images" class:single={images.length === 1} class:pair={images.length === 2 || images.length === 4}>
              {#each images.slice(0, 9) as url, index}
                <button class="moment-image" type="button" aria-label={'查看第 ' + (index + 1) + ' 张图片'} onclick={() => (gallery = { urls: images, index })}>
                  <img src={url} alt="" loading="lazy" />
                  {#if index === 8 && images.length > 9}<span class="image-extra">+{images.length - 9}</span>{/if}
                </button>
              {/each}
            </div>
          {/if}

          {#if (m.likes || []).length > 0}
            <div class="likes-row">
              <span class="likes-icon" aria-hidden="true">♥</span>
              <span class="likes-text">
                {(m.likes || []).map((l) => l.author_label || l.author).join('、')}
              </span>
            </div>
          {/if}

          <footer class="moment-foot">
            <button class="foot-btn {likedByMe(m) ? 'is-liked' : ''}" type="button" aria-pressed={likedByMe(m)} disabled={liking[m.id]} onclick={() => toggleLike(m)}>
              <svg viewBox="0 0 24 24" width="18" height="18" fill="{likedByMe(m) ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/></svg>
              {likedByMe(m) ? '已赞' : '赞'}
              {#if (m.likes || []).length}<span class="action-count">{m.likes.length}</span>{/if}
            </button>
            <button class="foot-btn" type="button" aria-haspopup="dialog" onclick={() => toggleReply(m)}>
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
              评论
              {#if (m.replies || []).length}<span class="action-count">{m.replies.length}</span>{/if}
            </button>
          </footer>

          {#if (m.replies || []).length > 0}
            <div class="replies">
              {#each m.replies as rp (rp.id)}
                <div class="reply">
                  <span class="reply-author">{rp.author_label || rp.author || '匿名'}</span>
                  {#if rp.reply_to_label || rp.reply_to}
                    <span class="reply-arrow">回复</span>
                    <span class="reply-to">{rp.reply_to_label || rp.reply_to}</span>
                  {/if}
                  <span class="reply-colon">：</span>
                  <span class="reply-text">{rp.text}</span>
                  <div class="reply-actions">
                    <button class="mini-btn" type="button" onclick={() => openReplyTo(m, rp)}>回复</button>
                    <button class="mini-btn danger" type="button" onclick={() => removeReply(m, rp)}>删除</button>
                  </div>
                </div>
              {/each}
            </div>
          {/if}

          {#if openReplyId === m.id}
            <dialog class="moment-dialog glass-3" aria-label="写评论" oncancel={closeReply} use:showDialog={'.field-input'}>
              <form class="dialog-form" onsubmit={(event) => { event.preventDefault(); submitReply(m); }}>
                <header class="dialog-head">
                  <h2>写评论</h2>
                  <button class="icon-btn" type="button" aria-label="关闭评论窗口" onclick={closeReply}>×</button>
                </header>
                {#if replyTarget?.momentId === m.id && replyTarget.replyToLabel}
                  <div class="reply-target">
                    回复 @{replyTarget.replyToLabel}
                    <button class="mini-btn" type="button" onclick={cancelReplyTo}>取消回复对象</button>
                  </div>
                {/if}
                <input class="field-input" type="text" aria-label="评论内容" placeholder="写评论…" bind:value={replyDrafts[m.id]} />
                {#if toast?.type === 'error'}<p class="dialog-feedback" role="alert">{toast.text}</p>{/if}
                <div class="form-actions">
                  <button class="btn btn-outline" type="button" onclick={closeReply}>取消</button>
                  <button class="btn btn-primary" type="submit" disabled={replying || !(replyDrafts[m.id] || '').trim()}>{replying ? '发送中…' : '发送'}</button>
                </div>
              </form>
            </dialog>
          {/if}
        </article>
      {/each}
    </div>

    {#if hasMore}
      <div class="load-more">
        <button class="btn btn-outline" type="button" disabled={loadingMore} onclick={loadMore}>
          {loadingMore ? '加载中…' : '加载更多'}
        </button>
      </div>
    {/if}
  {/if}
</div>

{#if gallery}
  <dialog class="gallery glass-3" aria-label="动态图片" oncancel={closeGallery} onkeydown={onGalleryKey} use:showDialog={'.gallery-close'}>
    <div class="gallery-content">
      <header class="gallery-head">
        <span>{gallery.index + 1} / {gallery.urls.length}</span>
        <button class="icon-btn gallery-close" type="button" onclick={closeGallery} aria-label="关闭图片预览">×</button>
      </header>
      <img src={gallery.urls[gallery.index]} alt={'动态图片 ' + (gallery.index + 1)} />
      {#if gallery.urls.length > 1}
        <div class="gallery-actions">
          <button class="btn btn-outline" type="button" onclick={() => stepImage(-1)}>上一张</button>
          <button class="btn btn-outline" type="button" onclick={() => stepImage(1)}>下一张</button>
        </div>
      {/if}
    </div>
  </dialog>
{/if}

<style>
  .page {
    max-width: 790px;
    margin-inline: auto;
    padding: clamp(16px, 4vw, 48px) clamp(12px, 4vw, 36px) var(--space-6);
  }

  .page-top, .moment-head, .moment-foot, .reply, .reply-actions, .form-actions,
  .dialog-head, .gallery-head, .gallery-actions {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  .page-top { justify-content: space-between; margin-bottom: var(--space-4); }
  .page-title {
    margin: 0;
    color: var(--text-1);
    font-size: clamp(1.8rem, 4vw, 2.9rem);
    line-height: var(--leading-tight);
    letter-spacing: var(--tracking-tighter);
  }

  .page-lede { margin: var(--space-2) 0 0; color: var(--text-2); font-size: var(--text-sm); }
  .timeline { display: grid; gap: var(--space-3); }

  .moment, .empty-state {
    display: grid;
    gap: var(--space-3);
    min-width: 0;
    padding: clamp(14px, 3vw, 24px);
    border-radius: var(--radius-lg);
    background: var(--surface);
    box-shadow: var(--surface-stage-shadow);
  }

  .moment-head { gap: var(--space-3); }
  .moment-meta { display: grid; flex: 1; min-width: 0; }
  .moment-author { color: var(--text-1); font-weight: 700; overflow-wrap: anywhere; }
  .moment-time { color: var(--text-2); font-size: var(--text-xs); font-variant-numeric: tabular-nums; }
  .moment-text { margin: 0; color: var(--text-1); white-space: pre-wrap; overflow-wrap: anywhere; }

  .moment-images {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 5px;
    max-width: min(100%, 480px);
    border-radius: var(--radius-md);
  }

  .moment-images.single { grid-template-columns: minmax(0, 1fr); }
  .moment-images.pair { grid-template-columns: repeat(2, minmax(0, 1fr)); }

  .moment-image {
    position: relative;
    display: block;
    min-width: 0;
    aspect-ratio: 1;
    padding: 0;
    overflow: hidden;
    border: 0;
    border-radius: var(--radius-sm);
    background: var(--surface-2);
    cursor: zoom-in;
  }

  .moment-image img { display: block; width: 100%; height: 100%; object-fit: cover; }
  .single .moment-image { width: fit-content; max-width: 100%; aspect-ratio: auto; border-radius: var(--radius-md); }
  .single .moment-image img { width: auto; max-width: 100%; max-height: 480px; object-fit: contain; }

  .image-extra {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    background: rgba(0, 0, 0, 0.56);
    color: white;
    font-size: var(--text-lg);
    font-weight: 700;
  }

  .icon-btn, .btn, .foot-btn, .mini-btn {
    display: inline-flex;
    flex: none;
    align-items: center;
    justify-content: center;
    gap: var(--space-1);
    min-height: 36px;
    padding: var(--space-1) var(--space-3);
    border: 0;
    border-radius: var(--radius-pill);
    background: var(--field-fill);
    color: var(--text-2);
    font: inherit;
    font-size: var(--text-13);
    font-weight: 600;
    cursor: pointer;
  }

  .icon-btn { width: 36px; padding: 0; background: transparent; font-size: var(--text-lg); }
  .icon-btn:hover, .mini-btn:hover, .btn-outline:hover:enabled { background: var(--row-hover); color: var(--text-1); }
  .btn-primary { background: var(--accent); color: var(--on-accent); }
  .btn-primary:hover:enabled { background: var(--accent-hover); }
  /* 次要按钮：透明底 + 描边感（不抢占主按钮的填充色）。 */
  .btn-outline { background: transparent; box-shadow: inset 0 0 0 1px var(--border); color: var(--text-1); }
  .btn-outline:hover:enabled { background: var(--row-hover); color: var(--text-1); }
  .btn-sm { min-height: 30px; padding-inline: var(--space-2); font-size: var(--text-xs); }
  .btn:disabled, .foot-btn:disabled { opacity: 0.65; cursor: default; }

  .likes-row, .replies, .reply-target {
    min-width: 0;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--field-fill);
    color: var(--text-2);
    font-size: var(--text-13);
    overflow-wrap: anywhere;
  }

  .likes-row { display: flex; align-items: baseline; gap: var(--space-2); }
  .likes-icon { color: var(--accent); }
  .moment-foot { flex-wrap: wrap; }
  .foot-btn:hover:enabled, .foot-btn.is-liked { background: var(--accent-soft); color: var(--accent); }
  .action-count { font-variant-numeric: tabular-nums; }

  .replies { display: grid; gap: var(--space-1); }
  .reply { flex-wrap: wrap; gap: 0 var(--space-1); }
  .reply-author, .reply-to { color: var(--text-1); font-weight: 650; }
  .reply-text { flex: 1 1 8ch; min-width: 0; color: var(--text-1); white-space: pre-wrap; }
  .reply-actions { margin-inline-start: auto; gap: 0; }
  .mini-btn { min-height: 30px; padding: 0 var(--space-2); background: transparent; font-size: var(--text-xs); }
  .mini-btn.danger:hover, .del-btn:hover { background: var(--error-soft); color: var(--error); }

  .moment-dialog, .gallery {
    color: var(--text-1);
    border: 0;
    border-radius: var(--radius-xl);
    max-height: calc(100dvh - 2 * var(--space-4));
    overflow: auto;
    animation: rise var(--transition-spring);
  }

  .moment-dialog { width: min(500px, calc(100% - 2 * var(--space-3))); padding: clamp(14px, 3vw, 22px); }
  .gallery { width: min(900px, calc(100% - 2 * var(--space-3))); padding: var(--space-3); }

  .moment-dialog::backdrop, .gallery::backdrop { background: var(--scrim); }
  .dialog-form, .gallery-content, .field { display: grid; gap: var(--space-3); min-width: 0; }
  .field { gap: var(--space-1); color: var(--text-2); font-size: var(--text-13); font-weight: 650; }
  .dialog-head, .gallery-head { justify-content: space-between; }
  .dialog-head h2 { margin: 0; font-size: var(--text-lg); }
  .dialog-feedback { margin: 0; color: var(--error); font-size: var(--text-13); }
  .form-actions, .gallery-actions { flex-wrap: wrap; justify-content: flex-end; }
  .gallery-content img { max-width: 100%; max-height: 70dvh; margin-inline: auto; border-radius: var(--radius-md); object-fit: contain; }
  .gallery-head span { font-size: var(--text-13); font-variant-numeric: tabular-nums; }

  .field-input {
    width: 100%;
    min-height: 40px;
    padding: var(--space-2) var(--space-3);
    border: 0;
    border-radius: var(--radius-sm);
    background: var(--field-fill);
    color: var(--text-1);
    font: inherit;
    font-size: var(--text-base);
    font-weight: 400;
  }

  .field-input:focus { background: var(--field-fill-focus); box-shadow: var(--focus-ring); }
  textarea.field-input { resize: vertical; }

  .empty-state { justify-items: center; text-align: center; }
  .empty-icon { display: grid; place-items: center; width: 48px; height: 48px; border-radius: var(--radius-md); background: var(--accent-soft); color: var(--accent); }
  .empty-title, .empty-desc { margin: 0; }
  .empty-title { color: var(--text-1); font-weight: 650; }
  .empty-desc { color: var(--text-2); font-size: var(--text-13); }
  .load-more { display: flex; justify-content: center; margin-top: var(--space-3); }

  @keyframes rise {
    from { opacity: 0; transform: translateY(var(--motion-offset)); }
    to { opacity: 1; transform: translateY(0); }
  }

  @media (max-width: 600px) {
    .page { padding-inline: var(--space-3); }
    .replies { padding-inline: var(--space-2); }
  }
</style>
