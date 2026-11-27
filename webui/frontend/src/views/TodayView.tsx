import {
  ArrowRight,
  BookOpenText,
  Clock,
  Graph,
  Heart,
  SunHorizon,
} from '@phosphor-icons/react';
import { motion } from 'motion/react';
import { friendlyTime, timeGreeting } from '../lib/format';
import { useApp } from '../store/AppContext';

export function TodayView() {
  const { companionState, navigate } = useApp();

  const personaName = companionState?.persona_name || '慕';
  const mood = companionState?.mood;
  const affection = companionState?.affection;
  const openLoops = companionState?.open_loops || [];
  const memories = companionState?.memories || [];
  const diary = companionState?.diary;

  return (
    <div className="h-full overflow-y-auto px-4 pb-16 pt-16 md:px-8">
      <div className="mx-auto max-w-[960px] space-y-5">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="overflow-hidden rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] shadow-2xs"
        >
          <div
            className="h-1 w-full"
            style={{
              background:
                'linear-gradient(90deg, var(--c-tone-blue), var(--c-tone-violet), var(--c-tone-teal), var(--c-tone-amber))',
            }}
          />
          <div className="flex flex-wrap items-end justify-between gap-4 p-6">
            <div>
              <div className="inline-flex items-center gap-2 text-[12.5px] font-medium text-[var(--c-text-2)]">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ background: 'linear-gradient(135deg, var(--c-tone-blue), var(--c-tone-violet))' }}
                />
                <span>
                  {personaName} · {mood?.label || '平静'}
                </span>
              </div>
              <h1 className="mt-2 text-[24px] font-semibold tracking-tight text-[var(--c-text)]">
                {timeGreeting()}，今天也在好好相处
              </h1>
              <p className="mt-1.5 max-w-[580px] text-[14px] leading-relaxed text-[var(--c-text-2)]">
                {companionState?.monologue ||
                  diary?.recent_status ||
                  '当下的点滴情绪与记挂，都会温和地留在今天这一页。'}
              </p>
            </div>

            <button
              type="button"
              data-cursor="block"
              onClick={() => navigate('chat')}
              className="inline-flex items-center gap-2 rounded-[8px] bg-[var(--c-accent)] px-4 py-2 text-[13px] font-medium text-[var(--c-on-accent)] transition hover:bg-[var(--c-accent-hover)]"
            >
              <span>回到对话</span>
              <ArrowRight size={15} weight="bold" />
            </button>
          </div>
        </motion.div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {/* Mood card */}
          <div className="overflow-hidden rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] shadow-2xs">
            <div
              className="flex items-center justify-between border-b border-[var(--c-border)] px-5 py-3"
              style={{ backgroundColor: 'var(--c-tone-amber-soft)' }}
            >
              <span className="flex items-center gap-2 text-[13.5px] font-semibold text-[var(--c-text)]">
                <SunHorizon size={17} weight="duotone" style={{ color: 'var(--c-tone-amber)' }} />
                情绪与精力
              </span>
              <span
                className="rounded-[6px] px-2.5 py-0.5 text-[12px] font-semibold"
                style={{ backgroundColor: 'var(--c-surface)', color: 'var(--c-tone-amber)' }}
              >
                {mood?.label || '平静'}
              </span>
            </div>

            <div className="p-5">
              {mood ? (
                <div className="space-y-3 text-[13px]">
                  <div>
                    <div className="mb-1.5 flex justify-between text-[var(--c-text-2)]">
                      <span>精力状态</span>
                      <span className="font-mono font-semibold text-[var(--c-text)]">
                        {Math.round(mood.energy * 100)}%
                      </span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-[var(--c-surface-2)]">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${Math.min(100, Math.max(4, mood.energy * 100))}%`,
                          background: 'linear-gradient(90deg, var(--c-tone-amber), var(--c-tone-blue))',
                        }}
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-2 pt-1 text-center">
                    <div className="rounded-[8px] border border-[var(--c-border)]/70 bg-[var(--c-bg)]/60 p-2.5">
                      <div className="text-[11px] text-[var(--c-text-3)]">愉悦度</div>
                      <div className="mt-0.5 font-mono font-semibold text-[var(--c-text)]">
                        {mood.valence.toFixed(2)}
                      </div>
                    </div>
                    <div className="rounded-[8px] border border-[var(--c-border)]/70 bg-[var(--c-bg)]/60 p-2.5">
                      <div className="text-[11px] text-[var(--c-text-3)]">唤醒度</div>
                      <div className="mt-0.5 font-mono font-semibold text-[var(--c-text)]">
                        {mood.arousal.toFixed(2)}
                      </div>
                    </div>
                    <div className="rounded-[8px] border border-[var(--c-border)]/70 bg-[var(--c-bg)]/60 p-2.5">
                      <div className="text-[11px] text-[var(--c-text-3)]">情绪强度</div>
                      <div className="mt-0.5 font-mono font-semibold text-[var(--c-text)]">
                        {mood.intensity.toFixed(2)}
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <p className="text-[13px] text-[var(--c-text-2)]">暂无情绪读数</p>
              )}
            </div>
          </div>

          {/* Affection & Open Loops */}
          <div className="overflow-hidden rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] shadow-2xs">
            <div
              className="flex items-center justify-between border-b border-[var(--c-border)] px-5 py-3"
              style={{ backgroundColor: 'var(--c-tone-rose-soft)' }}
            >
              <span className="flex items-center gap-2 text-[13.5px] font-semibold text-[var(--c-text)]">
                <Heart size={17} weight="duotone" style={{ color: 'var(--c-tone-rose)' }} />
                关系与挂念
              </span>
              {affection && (
                <span
                  className="rounded-[6px] px-2.5 py-0.5 text-[12px] font-semibold"
                  style={{ backgroundColor: 'var(--c-surface)', color: 'var(--c-tone-rose)' }}
                >
                  {affection.stage} · Lv.{affection.level}
                </span>
              )}
            </div>

            <div className="p-5">
              <div className="mb-2 flex items-center gap-1.5 text-[12px] text-[var(--c-text-2)]">
                <Clock size={14} weight="duotone" />
                <span>待跟进事项 ({openLoops.length})</span>
              </div>
              {openLoops.length === 0 ? (
                <p className="rounded-[8px] border border-[var(--c-border)]/70 bg-[var(--c-bg)]/60 p-3 text-[13px] text-[var(--c-text-2)]">
                  暂无挂念中的事项
                </p>
              ) : (
                <div className="space-y-2">
                  {openLoops.slice(0, 4).map((l) => (
                    <div
                      key={l.id}
                      className="flex items-center justify-between rounded-[8px] border border-[var(--c-border)]/70 bg-[var(--c-bg)]/60 px-3.5 py-2 text-[13px]"
                    >
                      <span className="text-[var(--c-text)]">{l.title}</span>
                      {l.expected_date && (
                        <span className="text-[11.5px] text-[var(--c-text-3)]">
                          {l.expected_date}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Diary */}
          <div className="overflow-hidden rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] shadow-2xs">
            <div
              className="flex items-center justify-between border-b border-[var(--c-border)] px-5 py-3"
              style={{ backgroundColor: 'var(--c-tone-violet-soft)' }}
            >
              <span className="flex items-center gap-2 text-[13.5px] font-semibold text-[var(--c-text)]">
                <BookOpenText size={17} weight="duotone" style={{ color: 'var(--c-tone-violet)' }} />
                最近一次阶段摘要
              </span>
              {diary?.created_at && (
                <span className="text-[12px] text-[var(--c-text-3)]">
                  {friendlyTime(diary.created_at)}
                </span>
              )}
            </div>
            <p className="p-5 text-[13.5px] leading-relaxed text-[var(--c-text)]">
              {diary?.summary || '当对话累积到一定次数，这里会自动沉淀成她视角下的阶段记忆。'}
            </p>
          </div>

          {/* Recent Memory Highlights */}
          <div className="overflow-hidden rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] shadow-2xs">
            <div
              className="flex items-center justify-between border-b border-[var(--c-border)] px-5 py-3"
              style={{ backgroundColor: 'var(--c-tone-teal-soft)' }}
            >
              <span className="flex items-center gap-2 text-[13.5px] font-semibold text-[var(--c-text)]">
                <Graph size={17} weight="duotone" style={{ color: 'var(--c-tone-teal)' }} />
                近期记住的事
              </span>
              <button
                type="button"
                data-cursor="block"
                onClick={() => navigate('memory')}
                className="text-[12.5px] font-medium hover:underline"
                style={{ color: 'var(--c-tone-teal)' }}
              >
                查看思维导图 →
              </button>
            </div>
            <div className="space-y-2 p-5">
              {memories.length === 0 ? (
                <p className="text-[13px] text-[var(--c-text-2)]">暂无记忆条目</p>
              ) : (
                memories.slice(0, 4).map((m) => (
                  <div
                    key={m.id}
                    className="rounded-[8px] border border-[var(--c-border)]/70 bg-[var(--c-bg)]/60 px-3.5 py-2.5 text-[13px] leading-relaxed text-[var(--c-text)]"
                  >
                    {m.content}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
