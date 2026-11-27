import { useEffect, useState } from 'react';
import { Brain, CaretRight } from '@phosphor-icons/react';
import { AnimatePresence, motion } from 'motion/react';

export function ThinkingBlock({
  reasoning,
  isThinking,
  durationMs,
}: {
  reasoning: string;
  isThinking?: boolean;
  durationMs?: number;
}) {
  const [open, setOpen] = useState(Boolean(isThinking));

  useEffect(() => {
    if (isThinking) setOpen(true);
    else if (durationMs && durationMs > 0) setOpen(false);
  }, [isThinking, durationMs]);

  if (!reasoning.trim() && !isThinking) return null;

  const seconds = durationMs ? (durationMs / 1000).toFixed(1) : null;

  return (
    <div className="mb-2">
      <button
        type="button"
        data-cursor="block"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-[7px] px-2 py-1 text-[12px] font-medium text-[var(--c-text-2)] transition hover:bg-[var(--c-surface-2)] hover:text-[var(--c-text)]"
      >
        <Brain
          size={14}
          weight="duotone"
          style={{ color: 'var(--c-tone-violet)' }}
          className={isThinking ? 'animate-pulse' : ''}
        />
        <span>
          {isThinking
            ? '正在深度思考…'
            : seconds
              ? `已深度思考 · ${seconds}s`
              : '思考过程'}
        </span>
        <CaretRight
          size={13}
          weight="bold"
          className={`transition-transform duration-200 ${open ? 'rotate-90' : ''}`}
        />
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="mt-1.5 rounded-[8px] border-l-2 border-[var(--c-tone-violet)]/40 bg-[var(--c-tone-violet-soft)]/50 px-3 py-2 text-[12.5px] leading-relaxed text-[var(--c-text-2)] whitespace-pre-wrap">
              {reasoning}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
