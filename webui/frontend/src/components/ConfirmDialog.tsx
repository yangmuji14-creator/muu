import * as Dialog from '@radix-ui/react-dialog';
import { useApp } from '../store/AppContext';

export function ConfirmDialog() {
  const { confirmRequest, resolveConfirm } = useApp();

  return (
    <Dialog.Root
      open={Boolean(confirmRequest)}
      onOpenChange={(open) => {
        if (!open) resolveConfirm(false);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[70] bg-slate-950/35 backdrop-blur-xs" />
        <Dialog.Content className="liquid-glass-modal fixed left-1/2 top-1/2 z-[71] w-[min(92vw,380px)] -translate-x-1/2 -translate-y-1/2 rounded-[14px] p-5 outline-none">
          <Dialog.Title className="text-[15px] font-semibold text-[var(--c-text)]">
            {confirmRequest?.title}
          </Dialog.Title>
          <Dialog.Description className="mt-2 text-[13.5px] leading-relaxed text-[var(--c-text-2)]">
            {confirmRequest?.message}
          </Dialog.Description>
          <div className="mt-5 flex justify-end gap-2">
            <button
              type="button"
              data-cursor="block"
              onClick={() => resolveConfirm(false)}
              className="rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] px-3.5 py-1.5 text-[13px] font-medium text-[var(--c-text-2)] transition hover:text-[var(--c-text)]"
            >
              取消
            </button>
            <button
              type="button"
              data-cursor="block"
              onClick={() => resolveConfirm(true)}
              className={`rounded-[8px] px-3.5 py-1.5 text-[13px] font-medium text-white transition ${
                confirmRequest?.danger
                  ? 'bg-[var(--c-error)] hover:opacity-90'
                  : 'bg-[var(--c-accent)] hover:bg-[var(--c-accent-hover)]'
              }`}
            >
              {confirmRequest?.confirmText || '确认'}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
