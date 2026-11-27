import { useEffect } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  ArrowRight,
  BookOpenText,
  Clock,
  Graph,
  Heart,
  SunHorizon,
  X,
} from '@phosphor-icons/react';
import { useApp } from '../store/AppContext';
import { friendlyTime } from '../lib/format';

export function StateDrawer() {
  const { stateDrawerOpen, setStateDrawerOpen, companionState, navigate } = useApp();

  useEffect(() => {
    if (!stateDrawerOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setStateDrawerOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [stateDrawerOpen, setStateDrawerOpen]);

  const mood = companionState?.mood;
  const affection = companionState?.affection;
  const openLoops = companionState?.open_loops || [];
  const memories = companionState?.memories || [];
  const diary = companionState?.diary;

  return (
    <AnimatePresence>
      {stateDrawerOpen && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            onClick={() => setStateDrawerOpen(false)}
            className="fixed inset-0 z-40 bg-slate-950/20 backdrop-blur-[1px]"
          />

          <motion.aside
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', stiffness: 380, damping: 36 }}
            aria-label="伴侣状态"
            className="liquid-glass-panel fixed inset-y-0 right-0 z-50 flex w-[min(90vw,344px)] flex-col border-l border-[var(--c-border-strong)]"
          >
            <div className="flex h-12 shrink-0 items-center justify-between border-b border-[var(--c-border)] px-4">
              <div className="flex items-baseline gap-2 truncate">
                <h2 className="text-[14px] font-semibold text-[var(--c-text)]">
                  {companionState?.persona_name || '慕'} · 此刻状态
                </h2>
                <span className="truncate text-[11.5px] text-[var(--c-text-2)]">情绪与记忆</span>
              </div>
              <button
                type="button"
                data-cursor="block"
                onClick={() => setStateDrawerOpen(false)}
                className="flex h-7 w-7 items-center justify-center rounded-[8px] text-[var(--c-text-2)] transition hover:bg-[var(--c-surface-2)] hover:text-[var(--c-text)]"
                aria-label="关闭状态"
              >
                <X size={16} weight="bold" />
              </button>
            </div>

            <div className="flex-1 space-y-3 overflow-y-auto p-4">
              {/* Mood & Energy */}
              <div className="overflow-hidden rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)]">
                <div
                  className="flex items-center justify-between border-b border-[var(--c-border)] px-3.5 py-2.5"
                  style={{ backgroundColor: 'var(--c-tone-amber-soft)' }}
                >
                  <span className="flex items-center gap-1.5 text-[12px] font-semibold text-[var(--c-text)]">
                    <SunHorizon size={15} weight="duotone" style={{ color: 'var(--c-tone-amber)' }} />
                    当前心境
                  </span>
                  <span
                    className="rounded-[6px] px-2 py-0.5 text-[11.5px] font-semibold"
                    style={{
                      backgroundColor: 'var(--c-surface)',
                      color: 'var(--c-tone-amber)',
                    }}
                  >
                    {mood?.label || '平静'}
                  </span>
                </div>
                {mood && (
                  <div className="space-y-2 p-3.5 text-[12px]">
                    <div>
                      <div className="mb-1 flex justify-between text-[var(--c-text-2)]">
                        <span>精力值</span>
                        <span className="font-mono font-semibold text-[var(--c-text)]">
                          {Math.round(mood.energy * 100)}%
                        </span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-[var(--c-surface-2)]">
                        <div
                          className="h-full rounded-full transition-all"
                          style={{
                            width: `${Math.min(100, Math.max(4, mood.energy * 100))}%`,
                            background: 'linear-gradient(90deg, var(--c-tone-amber), var(--c-tone-blue))',
                          }}
                        />
                      </div>
                    </div>
                    <div className="flex justify-between pt-1 text-[var(--c-text-2)]">
                      <span>愉悦度 {mood.valence.toFixed(2)}</span>
                      <span>唤醒度 {mood.arousal.toFixed(2)}</span>
                    </div>
                  </div>
                )}
              </div>

              {/* Affection */}
              {affection && (
                <div className="overflow-hidden rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)]">
                  <div className="flex items-center justify-between px-3.5 py-3">
                    <span className="flex items-center gap-1.5 text-[12.5px] font-medium text-[var(--c-text-2)]">
                      <Heart size={15} weight="duotone" style={{ color: 'var(--c-tone-rose)' }} />
                      关系阶段
                    </span>
                    <span
                      className="rounded-[6px] px-2.5 py-0.5 text-[12.5px] font-semibold"
                      style={{
                        backgroundColor: 'var(--c-tone-rose-soft)',
                        color: 'var(--c-tone-rose)',
                      }}
                    >
                      {affection.stage} · Lv.{affection.level}
                    </span>
                  </div>
                </div>
              )}

              {/* Open loops */}
              {openLoops.length > 0 && (
                <div className="overflow-hidden rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)]">
                  <div
                    className="flex items-center gap-1.5 border-b border-[var(--c-border)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--c-text)]"
                    style={{ backgroundColor: 'var(--c-tone-teal-soft)' }}
                  >
                    <Clock size={15} weight="duotone" style={{ color: 'var(--c-tone-teal)' }} />
                    记挂中的事
                  </div>
                  <div className="space-y-2 p-3">
                    {openLoops.map((loop) => (
                      <div
                        key={loop.id}
                        className="rounded-[8px] bg-[var(--c-surface-2)] px-3 py-2 text-[12.5px] text-[var(--c-text)]"
                      >
                        <div>{loop.title}</div>
                        {loop.expected_date && (
                          <div className="mt-0.5 text-[11px] text-[var(--c-text-2)]">
                            预期时间：{loop.expected_date}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Diary */}
              {diary && (
                <div className="overflow-hidden rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)]">
                  <div
                    className="flex items-center justify-between border-b border-[var(--c-border)] px-3.5 py-2.5 text-[12px]"
                    style={{ backgroundColor: 'var(--c-tone-violet-soft)' }}
                  >
                    <span className="flex items-center gap-1.5 font-semibold text-[var(--c-text)]">
                      <BookOpenText size={15} weight="duotone" style={{ color: 'var(--c-tone-violet)' }} />
                      最近日记
                    </span>
                    <span className="text-[var(--c-text-2)]">{friendlyTime(diary.created_at)}</span>
                  </div>
                  <p className="p-3.5 text-[13px] leading-relaxed text-[var(--c-text)]">{diary.summary}</p>
                </div>
              )}

              {/* Recent Memories */}
              <div className="overflow-hidden rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)]">
                <div
                  className="flex items-center justify-between border-b border-[var(--c-border)] px-3.5 py-2.5"
                  style={{ backgroundColor: 'var(--c-tone-blue-soft)' }}
                >
                  <span className="flex items-center gap-1.5 text-[12px] font-semibold text-[var(--c-text)]">
                    <Graph size={15} weight="duotone" style={{ color: 'var(--c-tone-blue)' }} />
                    最近记忆
                  </span>
                  <button
                    type="button"
                    data-cursor="block"
                    onClick={() => {
                      setStateDrawerOpen(false);
                      navigate('memory');
                    }}
                    className="inline-flex items-center gap-1 text-[12px] font-medium text-[var(--c-accent)] hover:underline"
                  >
                    <span>记忆图谱</span>
                    <ArrowRight size={12} weight="bold" />
                  </button>
                </div>
                <div className="p-3">
                  {memories.length === 0 ? (
                    <p className="text-[12.5px] text-[var(--c-text-2)]">暂无记忆条目</p>
                  ) : (
                    <ul className="space-y-2">
                      {memories.map((m) => (
                        <li
                          key={m.id}
                          className="rounded-[8px] bg-[var(--c-surface-2)] px-3 py-2 text-[12.5px] leading-relaxed text-[var(--c-text)]"
                        >
                          {m.content}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
