import { motion } from 'motion/react';
import { BookOpenText, Brain, GitCommit } from '@phosphor-icons/react';
import { LifeSummaryItem, MemoryItem } from '../api/memory';
import { friendlyTime } from '../lib/format';

interface ChainStep {
  id: string;
  kind: 'summary' | 'memory';
  ts: number;
  dateLabel: string;
  title: string;
  body: string;
  tags: string[];
  level?: number;
  rawMemory?: MemoryItem;
}

export function MemoryThoughtChain({
  summaries,
  memories,
  selectedId,
  onSelectMemory,
}: {
  summaries: LifeSummaryItem[];
  memories: MemoryItem[];
  selectedId: string | null;
  onSelectMemory: (m: MemoryItem) => void;
}) {
  const steps: ChainStep[] = [
    ...summaries.map((s) => ({
      id: `sum:${s.id}`,
      kind: 'summary' as const,
      ts: Date.parse(s.created_at) || 0,
      dateLabel: friendlyTime(s.created_at),
      title: `阶段反思 · ${s.summary_type || '成长摘要'}`,
      body: s.summary + (s.recent_status ? `\n当下心境：${s.recent_status}` : ''),
      tags: Array.isArray(s.key_events) ? s.key_events.slice(0, 4) : [],
    })),
    ...memories.map((m) => ({
      id: `mem:${m.id}`,
      kind: 'memory' as const,
      ts: Date.parse(m.created_at) || 0,
      dateLabel: friendlyTime(m.created_at),
      title: m.category || '记忆锚点',
      body: m.content,
      tags: Array.isArray(m.tags) ? m.tags : [],
      level: m.level,
      rawMemory: m,
    })),
  ].sort((a, b) => b.ts - a.ts);

  if (steps.length === 0) {
    return (
      <div className="flex h-[320px] items-center justify-center rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] text-[14px] text-[var(--c-text-2)]">
        暂无思维链条与阶段记忆记录
      </div>
    );
  }

  return (
    <div className="relative space-y-4 pl-6 before:absolute before:bottom-4 before:left-2.5 before:top-4 before:w-px before:bg-[var(--c-border-strong)]">
      {steps.map((step, i) => {
        const isSelected = step.rawMemory?.id === selectedId;
        return (
          <motion.div
            key={step.id}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: Math.min(i * 0.03, 0.3) }}
            className="relative"
          >
            {/* Chain Node Marker */}
            <div
              className={`absolute -left-[22px] top-4 flex h-4 w-4 items-center justify-center rounded-[6px] border ${
                step.kind === 'summary'
                  ? 'border-[var(--c-tone-violet)] bg-[var(--c-tone-violet)] text-white'
                  : 'border-[var(--c-border-strong)] bg-[var(--c-surface)] text-[var(--c-tone-blue)]'
              }`}
            >
              {step.kind === 'summary' ? (
                <Brain size={11} weight="duotone" />
              ) : (
                <GitCommit size={11} weight="duotone" />
              )}
            </div>

            <div
              data-cursor={step.rawMemory ? 'block' : undefined}
              onClick={() => step.rawMemory && onSelectMemory(step.rawMemory)}
              className={`overflow-hidden rounded-[12px] border transition ${
                step.rawMemory ? 'cursor-pointer hover:border-[var(--c-accent-border)]' : ''
              } ${
                isSelected
                  ? 'border-[var(--c-accent)] bg-[var(--c-accent-soft)]'
                  : 'border-[var(--c-border)] bg-[var(--c-surface)]'
              }`}
            >
              <div
                className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--c-border)]/70 px-4 py-2.5"
                style={{
                  backgroundColor:
                    step.kind === 'summary'
                      ? 'var(--c-tone-violet-soft)'
                      : 'var(--c-tone-blue-soft)',
                }}
              >
                <div className="flex items-center gap-2">
                  {step.kind === 'summary' && (
                    <BookOpenText size={14} weight="duotone" style={{ color: 'var(--c-tone-violet)' }} />
                  )}
                  <span className="text-[12.5px] font-semibold text-[var(--c-text)]">
                    {step.title}
                  </span>
                  {step.level !== undefined && (
                    <span
                      className="rounded-[6px] px-2 py-0.5 text-[11px] font-medium"
                      style={{ backgroundColor: 'var(--c-surface)', color: 'var(--c-tone-blue)' }}
                    >
                      重要度 {step.level}
                    </span>
                  )}
                </div>
                <span className="text-[11.5px] text-[var(--c-text-3)]">{step.dateLabel}</span>
              </div>

              <div className="p-4">
                <p className="whitespace-pre-wrap text-[13.5px] leading-relaxed text-[var(--c-text)]">
                  {step.body}
                </p>

                {step.tags.length > 0 && (
                  <div className="mt-2.5 flex flex-wrap gap-1.5">
                    {step.tags.map((t) => (
                      <span
                        key={t}
                        className="rounded-[6px] border border-[var(--c-border)] bg-[var(--c-surface-2)] px-2 py-0.5 text-[11px] text-[var(--c-text-2)]"
                      >
                        #{t}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}
