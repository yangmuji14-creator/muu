import { useCallback, useEffect, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { ChatCircle, Heart, Plus, Trash, X } from '@phosphor-icons/react';
import { MomentItem, momentsApi } from '../api/moments';
import { friendlyTime } from '../lib/format';
import { useApp } from '../store/AppContext';

export function DiscoverView() {
  const { confirm, notify } = useApp();
  const [moments, setMoments] = useState<MomentItem[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [limit, setLimit] = useState(20);
  const [loading, setLoading] = useState(true);

  const [publishOpen, setPublishOpen] = useState(false);
  const [newText, setNewText] = useState('');
  const [newAuthor, setNewAuthor] = useState('');
  const [authors, setAuthors] = useState<Array<{ id: string; name: string }>>([]);
  const [publishing, setPublishing] = useState(false);

  const [replyOpenId, setReplyOpenId] = useState<string | null>(null);
  const [replyText, setReplyText] = useState('');
  const [replyTo, setReplyTo] = useState<{ id: string; label: string } | null>(null);

  const load = useCallback(async (cnt = limit) => {
    setLoading(true);
    const r = await momentsApi.list(cnt);
    setLoading(false);
    if (r.ok && r.data) {
      setMoments(r.data.moments || []);
      setHasMore(Boolean(r.data.has_more));
    }
  }, [limit]);

  useEffect(() => {
    load(20);
    momentsApi.personas().then((r) => {
      if (r.ok && r.data?.personas) setAuthors(r.data.personas);
    });
  }, []);

  const isLiked = (m: MomentItem) =>
    Boolean(m.liked_by_me || m.liked || m.likes?.some((l) => l.author === 'user' || l.author === 'me'));

  const handleToggleLike = async (m: MomentItem) => {
    const active = isLiked(m);
    const r = active ? await momentsApi.unlike(m.id) : await momentsApi.like(m.id);
    if (!r.ok) {
      notify(r.error || '操作失败', 'error');
      return;
    }
    await load();
  };

  const handlePublish = async () => {
    const text = newText.trim();
    if (!text || publishing) return;
    setPublishing(true);
    const r = await momentsApi.publish({ text, author: newAuthor || undefined });
    setPublishing(false);
    if (r.ok) {
      setNewText('');
      setPublishOpen(false);
      notify('动态已发布', 'success');
      await load();
    } else {
      notify(r.error || '发布失败', 'error');
    }
  };

  const handleReply = async (m: MomentItem) => {
    const text = replyText.trim();
    if (!text) return;
    const r = await momentsApi.reply(m.id, {
      text,
      reply_to: replyTo?.id,
    });
    if (r.ok) {
      setReplyText('');
      setReplyOpenId(null);
      setReplyTo(null);
      await load();
    } else {
      notify(r.error || '评论失败', 'error');
    }
  };

  const handleDeleteMoment = async (m: MomentItem) => {
    const ok = await confirm('确定删除这条动态吗？', { title: '删除动态', danger: true });
    if (!ok) return;
    const r = await momentsApi.remove(m.id);
    if (r.ok) {
      notify('已删除', 'success');
      await load();
    }
  };

  return (
    <div className="h-full overflow-y-auto px-4 pb-16 pt-16 md:px-8">
      <div className="mx-auto max-w-[740px] space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-[22px] font-semibold tracking-tight text-[var(--c-text)]">动态</h1>
            <p className="mt-0.5 text-[13px] text-[var(--c-text-2)]">记录日常瞬间与彼此回应</p>
          </div>

          <button
            type="button"
            data-cursor="block"
            onClick={() => setPublishOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-[8px] bg-[var(--c-accent)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--c-on-accent)] transition hover:bg-[var(--c-accent-hover)]"
          >
            <Plus size={15} weight="bold" />
            <span>发布动态</span>
          </button>
        </div>

        {loading && moments.length === 0 ? (
          <div className="rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] p-10 text-center text-[13.5px] text-[var(--c-text-2)]">
            正在加载动态…
          </div>
        ) : moments.length === 0 ? (
          <div className="rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] p-10 text-center text-[13.5px] text-[var(--c-text-2)]">
            还没有动态记录，发布第一条日常吧。
          </div>
        ) : (
          <div className="space-y-3.5">
            {moments.map((m) => {
              const liked = isLiked(m);
              return (
                <article
                  key={m.id}
                  className="rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] p-5 shadow-2xs"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-[14px] font-semibold text-[var(--c-text)]">
                        {m.author_label || m.author || '我'}
                      </span>
                      <span className="text-[12px] text-[var(--c-text-3)]">
                        {friendlyTime(m.timestamp)}
                      </span>
                    </div>
                    <button
                      type="button"
                      data-cursor="block"
                      onClick={() => handleDeleteMoment(m)}
                      className="rounded-[8px] p-1.5 text-[var(--c-text-3)] hover:bg-[var(--c-surface-2)] hover:text-[var(--c-error)]"
                      title="删除动态"
                    >
                      <Trash size={14} weight="duotone" />
                    </button>
                  </div>

                  <p className="mt-2.5 whitespace-pre-wrap text-[14.5px] leading-relaxed text-[var(--c-text)]">
                    {m.text}
                  </p>

                  <div className="mt-4 flex items-center gap-4 border-t border-[var(--c-border)] pt-3">
                    <button
                      type="button"
                      data-cursor="block"
                      onClick={() => handleToggleLike(m)}
                      style={liked ? { color: 'var(--c-tone-rose)' } : undefined}
                      className={`inline-flex items-center gap-1.5 text-[12.5px] font-medium transition ${
                        liked ? '' : 'text-[var(--c-text-2)] hover:text-[var(--c-text)]'
                      }`}
                    >
                      <Heart size={16} weight={liked ? 'fill' : 'duotone'} />
                      <span>{m.likes?.length || 0}</span>
                    </button>

                    <button
                      type="button"
                      data-cursor="block"
                      onClick={() => {
                        setReplyOpenId(replyOpenId === m.id ? null : m.id);
                        setReplyTo(null);
                        setReplyText('');
                      }}
                      className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-[var(--c-text-2)] hover:text-[var(--c-text)]"
                    >
                      <ChatCircle size={16} weight="duotone" />
                      <span>{m.replies?.length || 0}</span>
                    </button>

                    {m.likes?.length > 0 && (
                      <span className="truncate text-[12px] text-[var(--c-text-3)]">
                        {m.likes.map((l) => l.author_label || l.author).join('、')} 觉得很赞
                      </span>
                    )}
                  </div>

                  {m.replies?.length > 0 && (
                    <div className="mt-3 space-y-1.5 rounded-[8px] bg-[var(--c-surface-2)] p-3">
                      {m.replies.map((rp) => (
                        <div
                          key={rp.id}
                          className="group flex items-start justify-between gap-2 text-[13px]"
                        >
                          <button
                            type="button"
                            onClick={() => {
                              setReplyOpenId(m.id);
                              setReplyTo({ id: rp.id, label: rp.author_label || rp.author });
                            }}
                            className="text-left leading-relaxed text-[var(--c-text)]"
                          >
                            <span className="font-semibold text-[var(--c-accent)]">
                              {rp.author_label || rp.author}
                            </span>
                            {rp.reply_to_label && (
                              <span className="text-[var(--c-text-2)]"> 回复 {rp.reply_to_label}</span>
                            )}
                            <span>：{rp.text}</span>
                          </button>
                          <button
                            type="button"
                            onClick={async () => {
                              const res = await momentsApi.removeReply(m.id, rp.id);
                              if (res.ok) await load();
                            }}
                            className="shrink-0 text-[11px] text-[var(--c-text-3)] opacity-0 group-hover:opacity-100 hover:text-[var(--c-error)]"
                          >
                            删除
                          </button>
                        </div>
                      ))}
                    </div>
                  )}

                  {replyOpenId === m.id && (
                    <form
                      className="mt-3 flex gap-2"
                      onSubmit={(e) => {
                        e.preventDefault();
                        handleReply(m);
                      }}
                    >
                      <input
                        autoFocus
                        value={replyText}
                        onChange={(e) => setReplyText(e.target.value)}
                        placeholder={replyTo ? `回复 ${replyTo.label}…` : '写下评论…'}
                        className="flex-1 rounded-[8px] border border-[var(--c-border)] bg-[var(--c-bg)] px-3 py-1.5 text-[13px] text-[var(--c-text)] outline-none focus:border-[var(--c-accent-border)]"
                      />
                      <button
                        type="submit"
                        data-cursor="block"
                        className="rounded-[8px] bg-[var(--c-accent)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--c-on-accent)]"
                      >
                        发送
                      </button>
                    </form>
                  )}
                </article>
              );
            })}

            {hasMore && (
              <div className="pt-2 text-center">
                <button
                  type="button"
                  data-cursor="block"
                  onClick={() => {
                    const next = limit + 20;
                    setLimit(next);
                    load(next);
                  }}
                  className="rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] px-5 py-2 text-[13px] font-medium text-[var(--c-text-2)] hover:text-[var(--c-text)]"
                >
                  加载更多
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Publish Dialog */}
      <Dialog.Root open={publishOpen} onOpenChange={setPublishOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/35 backdrop-blur-xs" />
          <Dialog.Content className="liquid-glass-modal fixed left-1/2 top-1/2 z-50 w-[min(92vw,460px)] -translate-x-1/2 -translate-y-1/2 rounded-[14px] p-6 outline-none">
            <div className="flex items-center justify-between pb-3">
              <Dialog.Title className="text-[15px] font-semibold text-[var(--c-text)]">
                发布动态
              </Dialog.Title>
              <button
                type="button"
                onClick={() => setPublishOpen(false)}
                className="rounded-[8px] p-1 text-[var(--c-text-2)] hover:bg-[var(--c-surface-2)]"
              >
                <X size={16} weight="bold" />
              </button>
            </div>
            <textarea
              rows={4}
              value={newText}
              onChange={(e) => setNewText(e.target.value)}
              placeholder="记录一件小事…"
              className="w-full resize-none rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] p-3 text-[13.5px] text-[var(--c-text)] outline-none focus:border-[var(--c-accent-border)]"
            />
            {authors.length > 0 && (
              <div className="mt-3 flex items-center justify-between text-[12.5px]">
                <span className="text-[var(--c-text-2)]">发布身份</span>
                <select
                  value={newAuthor}
                  onChange={(e) => setNewAuthor(e.target.value)}
                  className="rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] px-2.5 py-1 text-[var(--c-text)] outline-none"
                >
                  <option value="">我</option>
                  {authors.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setPublishOpen(false)}
                className="rounded-[8px] border border-[var(--c-border)] px-3.5 py-1.5 text-[13px] text-[var(--c-text-2)]"
              >
                取消
              </button>
              <button
                type="button"
                disabled={!newText.trim() || publishing}
                onClick={handlePublish}
                className="rounded-[8px] bg-[var(--c-accent)] px-4 py-1.5 text-[13px] font-medium text-[var(--c-on-accent)] disabled:opacity-40"
              >
                {publishing ? '发布中…' : '发布'}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
