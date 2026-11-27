import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Check, PencilSimple, Plus, Trash, X } from '@phosphor-icons/react';
import { deleteConversation, updateConversation } from '../api/chat';
import { friendlyTime } from '../lib/format';
import { useApp } from '../store/AppContext';

export function ConversationDrawer() {
  const {
    historyDrawerOpen,
    setHistoryDrawerOpen,
    conversations,
    activeConversationId,
    setActiveConversationId,
    reloadConversations,
    startNewConversation,
    navigate,
    confirm,
    notify,
  } = useApp();

  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState('');

  useEffect(() => {
    if (!historyDrawerOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setHistoryDrawerOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [historyDrawerOpen, setHistoryDrawerOpen]);

  async function saveTitle(id: string) {
    const title = draftTitle.trim();
    setEditingId(null);
    if (!title) return;
    try {
      await updateConversation(id, { title });
      await reloadConversations();
    } catch (err) {
      notify(err instanceof Error ? err.message : '重命名失败', 'error');
    }
  }

  async function handleDelete(id: string, label: string) {
    const ok = await confirm(`确定删除会话「${label}」吗？相关聊天记录也将一并移除。`, {
      title: '删除会话',
      confirmText: '删除',
      danger: true,
    });
    if (!ok) return;
    try {
      await deleteConversation(id);
      if (activeConversationId === id) setActiveConversationId(null);
      await reloadConversations();
      notify('会话已删除', 'success');
    } catch (err) {
      notify(err instanceof Error ? err.message : '删除失败', 'error');
    }
  }

  return (
    <AnimatePresence>
      {historyDrawerOpen && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            onClick={() => setHistoryDrawerOpen(false)}
            className="fixed inset-0 z-40 bg-slate-950/20 backdrop-blur-[1px]"
          />

          <motion.aside
            initial={{ x: '-100%' }}
            animate={{ x: 0 }}
            exit={{ x: '-100%' }}
            transition={{ type: 'spring', stiffness: 380, damping: 36 }}
            aria-label="历史会话"
            className="liquid-glass-panel fixed inset-y-0 left-0 z-50 flex w-[min(86vw,296px)] flex-col border-r border-[var(--c-border-strong)]"
          >
            <div className="flex h-12 shrink-0 items-center justify-between border-b border-[var(--c-border)] px-4">
              <span className="text-[14px] font-semibold tracking-tight text-[var(--c-text)]">
                全部会话
              </span>
              <button
                type="button"
                data-cursor="block"
                onClick={() => setHistoryDrawerOpen(false)}
                className="flex h-7 w-7 items-center justify-center rounded-[8px] text-[var(--c-text-2)] transition hover:bg-[var(--c-surface-2)] hover:text-[var(--c-text)]"
                aria-label="关闭会话列表"
              >
                <X size={16} weight="bold" />
              </button>
            </div>

            <div className="p-3 pb-2">
              <button
                type="button"
                data-cursor="block"
                onClick={async () => {
                  await startNewConversation();
                  navigate('chat');
                  setHistoryDrawerOpen(false);
                }}
                className="flex h-8 w-full items-center justify-center gap-1.5 rounded-[8px] bg-[var(--c-accent)] px-3 text-[12.5px] font-medium text-[var(--c-on-accent)] transition hover:bg-[var(--c-accent-hover)]"
              >
                <Plus size={15} weight="bold" />
                <span>新建对话</span>
              </button>
            </div>

            <div className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
              {conversations.length === 0 ? (
                <div className="py-10 text-center text-[13px] text-[var(--c-text-2)]">
                  暂无历史会话
                </div>
              ) : (
                conversations.map((conv) => {
                  const active = conv.conversation_id === activeConversationId;
                  const label = conv.title || conv.persona_name || '新对话';
                  const isEditing = editingId === conv.conversation_id;

                  return (
                    <div
                      key={conv.conversation_id}
                      className={`group flex items-center gap-2 rounded-[8px] px-2.5 py-2 transition ${
                        active
                          ? 'bg-[var(--c-accent-soft)] text-[var(--c-accent)]'
                          : 'hover:bg-[var(--c-surface-2)] text-[var(--c-text)]'
                      }`}
                    >
                      {isEditing ? (
                        <form
                          className="flex flex-1 items-center gap-1"
                          onSubmit={(e) => {
                            e.preventDefault();
                            saveTitle(conv.conversation_id);
                          }}
                        >
                          <input
                            autoFocus
                            value={draftTitle}
                            onChange={(e) => setDraftTitle(e.target.value)}
                            className="min-w-0 flex-1 rounded-[6px] border border-[var(--c-accent-border)] bg-[var(--c-surface)] px-2 py-1 text-[13px] text-[var(--c-text)] outline-none"
                          />
                          <button
                            type="submit"
                            className="p-1 text-[var(--c-accent)]"
                            aria-label="保存"
                          >
                            <Check size={14} weight="bold" />
                          </button>
                        </form>
                      ) : (
                        <>
                          <button
                            type="button"
                            data-cursor="block"
                            onClick={() => {
                              setActiveConversationId(conv.conversation_id);
                              navigate('chat');
                              setHistoryDrawerOpen(false);
                            }}
                            className="min-w-0 flex-1 text-left"
                          >
                            <div className="truncate text-[13.5px] font-medium">{label}</div>
                            <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-[var(--c-text-2)]">
                              <span>{conv.platform === 'wechat' ? '微信' : '网页'}</span>
                              {conv.updated_at && <span>· {friendlyTime(conv.updated_at)}</span>}
                            </div>
                          </button>

                          <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition group-hover:opacity-100">
                            <button
                              type="button"
                              data-cursor="block"
                              onClick={() => {
                                setEditingId(conv.conversation_id);
                                setDraftTitle(label);
                              }}
                              className="rounded-[6px] p-1.5 text-[var(--c-text-2)] hover:bg-[var(--c-surface)] hover:text-[var(--c-text)]"
                              title="重命名"
                            >
                              <PencilSimple size={14} weight="duotone" />
                            </button>
                            <button
                              type="button"
                              data-cursor="block"
                              onClick={() => handleDelete(conv.conversation_id, label)}
                              className="rounded-[6px] p-1.5 text-[var(--c-text-2)] hover:bg-[var(--c-surface)] hover:text-[var(--c-error)]"
                              title="删除"
                            >
                              <Trash size={14} weight="duotone" />
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
