import { AnimatePresence, motion } from 'motion/react';
import { CheckCircle, Info, WarningCircle } from '@phosphor-icons/react';
import { useApp } from '../store/AppContext';

export function Toast() {
  const { toast } = useApp();

  return (
    <div className="pointer-events-none fixed bottom-24 left-1/2 z-[80] -translate-x-1/2">
      <AnimatePresence>
        {toast && (
          <motion.div
            key={toast.id}
            initial={{ opacity: 0, y: 10, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.96 }}
            transition={{ type: 'spring', stiffness: 420, damping: 32 }}
            className="liquid-glass-strong flex items-center gap-2 rounded-[10px] px-3.5 py-2 text-[13px] font-medium text-[var(--c-text)]"
          >
            {toast.type === 'success' && (
              <CheckCircle size={16} weight="duotone" className="shrink-0 text-[var(--c-success)]" />
            )}
            {toast.type === 'error' && (
              <WarningCircle size={16} weight="duotone" className="shrink-0 text-[var(--c-error)]" />
            )}
            {toast.type === 'info' && (
              <Info size={16} weight="duotone" style={{ color: 'var(--c-tone-blue)' }} className="shrink-0" />
            )}
            <span>{toast.text}</span>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
