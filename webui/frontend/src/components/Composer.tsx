import React, { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ArrowUp, Cpu, Image, Plus, Sticker, Stop } from '@phosphor-icons/react';
import { StickerGroup } from '../api/chat';
import { useApp } from '../store/AppContext';

interface ComposerProps {
  onSend: (text: string) => void;
  onUploadImage: (file: File) => void;
  onPickSticker: (sticker: { pack: string; emotion: string; filename: string; url: string }) => void;
  stickers: StickerGroup[];
  streaming: boolean;
  onStop: () => void;
  centered?: boolean;
}

export function Composer({
  onSend,
  onUploadImage,
  onPickSticker,
  stickers,
  streaming,
  onStop,
  centered = false,
}: ComposerProps) {
  const { modelSummary, openSettings } = useApp();
  const [text, setText] = useState('');
  const [stickerOpen, setStickerOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const currentKey = modelSummary?.current || '';
  const currentProvider = modelSummary?.providers?.find((p) => p.key === currentKey);
  const hasModels = (modelSummary?.providers?.length ?? 0) > 0;
  const activeModelLabel = currentProvider?.model_name || currentKey || '';

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(168, Math.max(40, el.scrollHeight))}px`;
  }, [text]);

  function submit() {
    const val = text.trim();
    if (!val || streaming) return;
    setText('');
    onSend(val);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <div className={`relative w-full ${centered ? 'max-w-[680px]' : 'mx-auto max-w-[740px]'}`}>
      {/* Sticker Popover */}
      <AnimatePresence>
        {stickerOpen && (
          <motion.div
            initial={{ opacity: 0, y: 8, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.96 }}
            transition={{ type: 'spring', stiffness: 420, damping: 32 }}
            className="liquid-glass-modal absolute bottom-full left-0 mb-2.5 w-[min(90vw,320px)] rounded-[12px] p-3"
          >
            <div className="mb-2 flex items-center justify-between text-[12px] font-medium text-[var(--c-text-2)]">
              <span>表情贴纸</span>
              <button
                type="button"
                onClick={() => setStickerOpen(false)}
                className="text-[11px] hover:text-[var(--c-text)]"
              >
                收起
              </button>
            </div>
            {stickers.length === 0 ? (
              <p className="py-4 text-center text-[12px] text-[var(--c-text-2)]">暂无可用贴纸</p>
            ) : (
              <div className="grid max-h-48 grid-cols-4 gap-2 overflow-y-auto">
                {stickers.flatMap((group) =>
                  group.images.map((fname) => {
                    const url = `/api/stickers/file/${encodeURIComponent(group.pack)}/${encodeURIComponent(group.emotion)}/${encodeURIComponent(fname)}`;
                    return (
                      <button
                        key={`${group.pack}-${group.emotion}-${fname}`}
                        type="button"
                        data-cursor="block"
                        onClick={() => {
                          onPickSticker({
                            pack: group.pack,
                            emotion: group.emotion,
                            filename: fname,
                            url,
                          });
                          setStickerOpen(false);
                        }}
                        className="flex flex-col items-center rounded-[8px] p-1.5 transition hover:bg-[var(--c-surface-2)]"
                        title={group.emotion}
                      >
                        <img src={url} alt={group.emotion} className="h-11 w-11 object-contain" />
                      </button>
                    );
                  }),
                )}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Main Liquid Glass Composer */}
      <div className="liquid-glass-strong glass-gleam relative rounded-[16px] p-3 pl-4 pr-3">
        <textarea
          ref={textareaRef}
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入消息… (Enter 发送，Shift + Enter 换行)"
          className="w-full resize-none bg-transparent py-1.5 text-[14.5px] leading-relaxed text-[var(--c-text)] placeholder-[var(--c-text-2)] outline-none"
        />

        <div className="mt-1.5 flex items-center justify-between gap-2">
          <div className="flex items-center gap-1">
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onUploadImage(f);
                e.target.value = '';
              }}
            />

            <button
              type="button"
              data-cursor="block"
              onClick={() => fileRef.current?.click()}
              title="发送图片"
              aria-label="发送图片"
              className="flex h-8 w-8 items-center justify-center rounded-[8px] text-[var(--c-text-2)] transition hover:bg-[var(--c-surface-2)] hover:text-[var(--c-text)]"
            >
              <Image size={17} weight="duotone" />
            </button>

            <button
              type="button"
              data-cursor="block"
              onClick={() => setStickerOpen((v) => !v)}
              title="表情贴纸"
              aria-label="表情贴纸"
              className={`flex h-8 w-8 items-center justify-center rounded-[8px] transition ${
                stickerOpen
                  ? 'bg-[var(--c-accent-soft)] text-[var(--c-accent)]'
                  : 'text-[var(--c-text-2)] hover:bg-[var(--c-surface-2)] hover:text-[var(--c-text)]'
              }`}
            >
              <Sticker size={17} weight="duotone" />
            </button>

            <div className="mx-1 h-3.5 w-px bg-[var(--c-border)]" />

            {/* Chatbox-style Model Provider Button (never hardcoded) */}
            <button
              type="button"
              data-cursor="block"
              data-cursor-wide="1"
              onClick={() => openSettings('model')}
              className="inline-flex h-8 items-center gap-1.5 rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] px-2.5 text-[12px] font-medium text-[var(--c-text-2)] transition hover:border-[var(--c-accent-border)] hover:text-[var(--c-accent)]"
            >
              {hasModels && activeModelLabel ? (
                <>
                  <Cpu size={14} weight="duotone" style={{ color: 'var(--c-tone-blue)' }} />
                  <span className="max-w-[160px] truncate">{activeModelLabel}</span>
                </>
              ) : (
                <>
                  <Plus size={14} weight="bold" style={{ color: 'var(--c-tone-blue)' }} />
                  <span>添加模型提供商</span>
                </>
              )}
            </button>
          </div>

          {streaming ? (
            <button
              type="button"
              data-cursor="block"
              onClick={onStop}
              aria-label="停止生成"
              className="flex h-8 w-8 items-center justify-center rounded-[8px] bg-[var(--c-text)] text-[var(--c-bg)] transition hover:opacity-85"
            >
              <Stop size={14} weight="fill" />
            </button>
          ) : (
            <button
              type="button"
              data-cursor="block"
              disabled={!text.trim()}
              onClick={submit}
              aria-label="发送"
              className="flex h-8 w-8 items-center justify-center rounded-[8px] bg-[var(--c-accent)] text-[var(--c-on-accent)] transition hover:bg-[var(--c-accent-hover)] disabled:cursor-not-allowed disabled:opacity-35"
            >
              <ArrowUp size={16} weight="bold" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
