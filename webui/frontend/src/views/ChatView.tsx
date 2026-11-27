import React, { useCallback, useEffect, useRef, useState } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ArrowCounterClockwise, Brain, Check, Copy, Plus } from '@phosphor-icons/react';
import { motion } from 'motion/react';
import {
  ChatMessage,
  StickerGroup,
  chatStream,
  deleteLastMessagePair,
  fetchHistory,
  listStickers,
  parseInlineThink,
  subscribeHistoryEvents,
  uploadImage,
} from '../api/chat';
import { Composer } from '../components/Composer';
import { InteractiveTileCanvas } from '../components/InteractiveTileCanvas';
import { ThinkingBlock } from '../components/ThinkingBlock';
import { friendlyTime, timeGreeting } from '../lib/format';
import { useApp } from '../store/AppContext';

const STARTER_PROMPTS = [
  '今天过得怎么样？跟我聊聊你此刻在想什么。',
  '帮我理一理最近有点乱的思绪。',
  '记得我们上次聊到的那件事吗？',
];

const PROMPT_TONES = [
  'var(--c-tone-blue)',
  'var(--c-tone-violet)',
  'var(--c-tone-teal)',
];

function CodeBlock({ className, children }: { className?: string; children?: React.ReactNode }) {
  const [copied, setCopied] = useState(false);
  const code = String(children ?? '').replace(/\n$/, '');
  const isBlock = Boolean(className) || code.includes('\n');

  if (!isBlock) {
    return <code className={className}>{children}</code>;
  }

  return (
    <div className="group/code relative my-2">
      <button
        type="button"
        onClick={() => {
          navigator.clipboard?.writeText(code);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        }}
        className="absolute right-2.5 top-2.5 flex items-center gap-1 rounded-[6px] border border-[var(--c-border)] bg-[var(--c-surface)] px-2 py-1 text-[11px] text-[var(--c-text-2)] opacity-0 transition group-hover/code:opacity-100 hover:text-[var(--c-text)]"
      >
        {copied ? <Check size={12} weight="bold" className="text-[var(--c-success)]" /> : <Copy size={12} weight="duotone" />}
        <span>{copied ? '已复制' : '复制'}</span>
      </button>
      <pre>
        <code className={className}>{children}</code>
      </pre>
    </div>
  );
}

export function ChatView() {
  const {
    theme,
    welcomeGridEnabled,
    activeConversationId,
    activeConversation,
    startNewConversation,
    companionState,
    modelSummary,
    openSettings,
    bumpState,
    notify,
    reloadConversations,
  } = useApp();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [stickers, setStickers] = useState<StickerGroup[]>([]);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  const streamRef = useRef<{ abort: () => void } | null>(null);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const debounceTimerRef = useRef<number | null>(null);
  const pendingTextsRef = useRef<string[]>([]);

  useEffect(() => {
    listStickers().then(setStickers).catch(() => {});
  }, []);

  const loadHistory = useCallback(async (cid: string | null) => {
    if (!cid) {
      setMessages([]);
      return;
    }
    setLoading(true);
    try {
      const list = await fetchHistory(cid);
      setMessages(list);
    } catch {
      setMessages([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    streamRef.current?.abort();
    streamRef.current = null;
    setStreaming(false);
    loadHistory(activeConversationId);
  }, [activeConversationId, loadHistory]);

  useEffect(() => {
    if (!activeConversationId) return;
    return subscribeHistoryEvents(activeConversationId, () => {
      if (!streamRef.current) loadHistory(activeConversationId);
    });
  }, [activeConversationId, loadHistory]);

  const scrollToBottom = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight;
    });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages.length, scrollToBottom]);

  const flushSend = useCallback(
    async (
      combinedText: string,
      stickerMeta?: { pack: string; emotion: string; filename: string; url: string },
    ) => {
      let cid = activeConversationId;
      if (!cid) {
        const created = await startNewConversation();
        if (!created) return;
        cid = created.conversation_id;
      }

      const personaId = activeConversation?.persona_id || companionState?.persona_id || 'girlfriend_001';
      const requestId = `web_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

      setStreaming(true);
      const thinkStartRef = { ts: 0 };

      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: '',
          reasoning: '',
          streaming: true,
          phaseLabel: '连接思考中…',
          timestamp: new Date().toISOString(),
        },
      ]);

      let rawAccum = '';
      let sseReasoning = '';

      const handle = chatStream({
        body: {
          content: combinedText,
          conversation_id: cid,
          persona_id: personaId,
          request_id: requestId,
          ...(stickerMeta
            ? {
                sticker: {
                  pack: stickerMeta.pack,
                  emotion: stickerMeta.emotion,
                  filename: stickerMeta.filename,
                },
              }
            : {}),
        },
        onPhase: ({ label }) => {
          setMessages((prev) => {
            const copy = [...prev];
            const last = copy[copy.length - 1];
            if (last?.role === 'assistant' && last.streaming) {
              copy[copy.length - 1] = { ...last, phaseLabel: label };
            }
            return copy;
          });
        },
        onReasoning: ({ text }) => {
          if (!thinkStartRef.ts) thinkStartRef.ts = performance.now();
          sseReasoning += text;
          setMessages((prev) => {
            const copy = [...prev];
            const last = copy[copy.length - 1];
            if (last?.role === 'assistant') {
              copy[copy.length - 1] = {
                ...last,
                reasoning: sseReasoning,
                reasoningDone: false,
                phaseLabel: '深度思考中…',
              };
            }
            return copy;
          });
        },
        onToken: ({ token }) => {
          rawAccum += token;
          const inline = parseInlineThink(rawAccum);
          if (inline.inThink && !thinkStartRef.ts) thinkStartRef.ts = performance.now();
          const finalReasoning = sseReasoning || inline.thinking;
          const isThinkActive = Boolean(!inline.reply && (inline.inThink || (sseReasoning && !rawAccum)));

          const durationMs =
            !isThinkActive && thinkStartRef.ts
              ? Math.max(200, performance.now() - thinkStartRef.ts)
              : undefined;

          setMessages((prev) => {
            const copy = [...prev];
            const last = copy[copy.length - 1];
            if (last?.role === 'assistant') {
              copy[copy.length - 1] = {
                ...last,
                content: inline.reply,
                reasoning: finalReasoning,
                reasoningDone: !isThinkActive,
                reasoningDurationMs: durationMs ?? last.reasoningDurationMs,
                phaseLabel: isThinkActive ? '深度思考中…' : '',
              };
            }
            return copy;
          });
          scrollToBottom();
        },
        onSticker: (st) => {
          setMessages((prev) => {
            const copy = [...prev];
            const last = copy[copy.length - 1];
            if (last?.role === 'assistant') {
              copy[copy.length - 1] = { ...last, sticker: st };
            }
            return copy;
          });
        },
        onDone: ({ reply, voice_url }) => {
          streamRef.current = null;
          setStreaming(false);
          const inline = parseInlineThink(reply ?? rawAccum);
          const finalReasoning = sseReasoning || inline.thinking;
          const durationMs = thinkStartRef.ts ? Math.max(200, performance.now() - thinkStartRef.ts) : undefined;

          setMessages((prev) => {
            const copy = [...prev];
            const last = copy[copy.length - 1];
            if (last?.role === 'assistant') {
              copy[copy.length - 1] = {
                ...last,
                content: inline.reply || last.content,
                reasoning: finalReasoning || last.reasoning,
                reasoningDone: true,
                reasoningDurationMs: durationMs ?? last.reasoningDurationMs,
                voice: voice_url || last.voice,
                streaming: false,
                phaseLabel: '',
              };
            }
            return copy;
          });
          bumpState();
          reloadConversations();
        },
        onError: ({ error }) => {
          streamRef.current = null;
          setStreaming(false);
          setMessages((prev) => {
            const copy = [...prev];
            const last = copy[copy.length - 1];
            if (last?.role === 'assistant') {
              copy[copy.length - 1] = {
                ...last,
                content: last.content || error,
                streaming: false,
                phaseLabel: '',
                error: true,
              };
            }
            return copy;
          });
        },
      });

      streamRef.current = handle;
    },
    [activeConversationId, activeConversation, companionState, startNewConversation, scrollToBottom, bumpState, reloadConversations],
  );

  const handleSend = useCallback(
    (text: string) => {
      setMessages((prev) => [
        ...prev,
        {
          role: 'user',
          content: text,
          timestamp: new Date().toISOString(),
        },
      ]);

      pendingTextsRef.current.push(text);
      if (debounceTimerRef.current) window.clearTimeout(debounceTimerRef.current);

      // Keep crisp responsiveness while supporting rapid multi-line coalescing
      debounceTimerRef.current = window.setTimeout(() => {
        const joined = pendingTextsRef.current.join('\n');
        pendingTextsRef.current = [];
        debounceTimerRef.current = null;
        flushSend(joined);
      }, 220);
    },
    [flushSend],
  );

  const handleUploadImage = useCallback(
    async (file: File) => {
      let cid = activeConversationId;
      if (!cid) {
        const created = await startNewConversation();
        if (!created) return;
        cid = created.conversation_id;
      }
      try {
        const res = await uploadImage(file, { conversation_id: cid });
        setMessages((prev) => [
          ...prev,
          {
            role: 'user',
            content: '[图片]',
            image: res.image_url,
            timestamp: new Date().toISOString(),
          },
        ]);
        notify('图片已发送，可继续补充文字或等待识别回复', 'info');
      } catch (err) {
        notify(err instanceof Error ? err.message : '图片上传失败', 'error');
      }
    },
    [activeConversationId, startNewConversation, notify],
  );

  const handlePickSticker = useCallback(
    async (sticker: { pack: string; emotion: string; filename: string; url: string }) => {
      setMessages((prev) => [
        ...prev,
        {
          role: 'user',
          content: `[表情:${sticker.emotion}]`,
          sticker,
          timestamp: new Date().toISOString(),
        },
      ]);
      await flushSend(`[表情:${sticker.emotion}]`, sticker);
    },
    [flushSend],
  );

  const handleRegenerate = useCallback(async () => {
    if (!activeConversationId || streaming || messages.length < 2) return;
    const lastUser = [...messages].reverse().find((m) => m.role === 'user');
    if (!lastUser?.content) return;
    try {
      await deleteLastMessagePair(activeConversationId);
      setMessages((prev) => prev.slice(0, -1));
      await flushSend(lastUser.content);
    } catch (err) {
      notify(err instanceof Error ? err.message : '重新生成失败', 'error');
    }
  }, [activeConversationId, streaming, messages, flushSend, notify]);

  const personaName = companionState?.persona_name || activeConversation?.persona_name || '慕';
  const hasModels = (modelSummary?.providers?.length ?? 0) > 0;
  const isEmpty = !loading && messages.length === 0;

  if (isEmpty) {
    return (
      <div className="relative flex h-full w-full flex-col items-center justify-center px-4 pt-12">
        <InteractiveTileCanvas theme={theme} enabled={welcomeGridEnabled} />

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ type: 'spring', stiffness: 300, damping: 28 }}
          className="relative z-10 flex w-full max-w-[680px] flex-col items-center text-center"
        >
          <div className="mb-2.5 inline-flex items-center gap-2 text-[12.5px] font-medium text-[var(--c-text-2)]">
            <span
              className="h-2 w-2 rounded-full"
              style={{ background: 'linear-gradient(135deg, var(--c-tone-blue), var(--c-tone-rose))' }}
            />
            <span>
              {personaName} · 此刻{companionState?.mood?.label || '平静'}
            </span>
          </div>

          <h1 className="text-[28px] font-semibold tracking-tight text-[var(--c-text)] md:text-[32px]">
            {timeGreeting()}，今天想聊点什么？
          </h1>
          <p className="mt-2 max-w-[480px] text-[14px] leading-relaxed text-[var(--c-text-2)]">
            {companionState?.monologue ||
              companionState?.diary?.recent_status ||
              '随时开口，每一段对话与记忆都会安静留在这里。'}
          </p>

          {!hasModels && (
            <button
              type="button"
              data-cursor="block"
              onClick={() => openSettings('model')}
              className="mt-4 inline-flex items-center gap-1.5 rounded-[8px] border border-[var(--c-accent-border)] bg-[var(--c-accent-soft)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--c-accent)] transition hover:opacity-90"
            >
              <Plus size={15} weight="bold" />
              <span>先添加一个模型提供商即可开始对话</span>
            </button>
          )}

          <div className="mt-7 w-full">
            <Composer
              centered
              onSend={handleSend}
              onUploadImage={handleUploadImage}
              onPickSticker={handlePickSticker}
              stickers={stickers}
              streaming={streaming}
              onStop={() => {
                streamRef.current?.abort();
                setStreaming(false);
              }}
            />
          </div>

          <div className="mt-5 flex flex-wrap justify-center gap-2">
            {STARTER_PROMPTS.map((prompt, idx) => (
              <button
                key={prompt}
                type="button"
                data-cursor="block"
                onClick={() => handleSend(prompt)}
                className="inline-flex items-center gap-2 rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] px-3 py-1.5 text-[12.5px] text-[var(--c-text-2)] transition hover:border-[var(--c-accent-border)] hover:text-[var(--c-text)]"
              >
                <span
                  className="h-1.5 w-1.5 shrink-0 rounded-full"
                  style={{ backgroundColor: PROMPT_TONES[idx % PROMPT_TONES.length] }}
                />
                <span>{prompt}</span>
              </button>
            ))}
          </div>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="relative flex h-full w-full flex-col">
      {/* Scrollable Message Stream passing behind top & bottom Liquid Glass chrome */}
      <div
        ref={scrollerRef}
        className="flex-1 overflow-y-auto px-4 pb-36 pt-16 md:px-6"
      >
        <div className="mx-auto max-w-[740px] space-y-5">
          {loading ? (
            <div className="py-12 text-center text-[13px] text-[var(--c-text-2)]">
              正在读取对话记录…
            </div>
          ) : (
            messages.map((msg, idx) => {
              const isUser = msg.role === 'user';
              const isLast = idx === messages.length - 1;
              const imgUrl =
                msg.image || msg.blocks?.find((b) => b.type === 'image')?.url || undefined;
              const stickerUrl =
                msg.sticker?.url || msg.blocks?.find((b) => b.type === 'emoji')?.url || undefined;
              const voiceUrl =
                msg.voice || msg.blocks?.find((b) => b.type === 'voice')?.url || undefined;

              const parsed = !isUser && !msg.reasoning ? parseInlineThink(msg.content) : null;
              const reasoningText = msg.reasoning || parsed?.thinking || '';
              const displayContent = parsed ? parsed.reply : msg.content;

              if (isUser) {
                return (
                  <motion.div
                    key={`${idx}-${msg.timestamp || idx}`}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.18 }}
                    className="flex flex-col items-end"
                  >
                    {imgUrl && (
                      <img
                        src={imgUrl}
                        alt="用户图片"
                        className="mb-1.5 max-h-60 rounded-[12px] border border-[var(--c-border)] object-cover"
                      />
                    )}
                    {stickerUrl ? (
                      <img src={stickerUrl} alt="贴纸" className="h-20 w-20 object-contain" />
                    ) : (
                      displayContent &&
                      !(imgUrl && displayContent.trim() === '[图片]') && (
                        <div className="max-w-[80%] rounded-[14px] rounded-br-[4px] bg-[var(--c-bubble-user)] px-4 py-2.5 text-[14.5px] leading-relaxed text-[var(--c-bubble-user-text)] shadow-2xs">
                          <span className="whitespace-pre-wrap break-words">{displayContent}</span>
                        </div>
                      )
                    )}
                    {msg.timestamp && (
                      <span className="mt-1 px-1 text-[11px] text-[var(--c-text-3)]">
                        {friendlyTime(msg.timestamp)}
                      </span>
                    )}
                  </motion.div>
                );
              }

              return (
                <motion.div
                  key={`${idx}-${msg.timestamp || idx}`}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.2 }}
                  className="group flex flex-col items-start"
                >
                  <div className="max-w-[88%] rounded-[14px] rounded-bl-[4px] border border-[var(--c-border)] bg-[var(--c-bubble-ai)] px-4 py-3 text-[var(--c-text)] shadow-2xs">
                    {(reasoningText || (msg.streaming && msg.phaseLabel?.includes('思考'))) && (
                      <ThinkingBlock
                        reasoning={reasoningText}
                        isThinking={Boolean(msg.streaming && !msg.reasoningDone && !displayContent)}
                        durationMs={msg.reasoningDurationMs}
                      />
                    )}

                    {msg.streaming && !displayContent && msg.phaseLabel && (
                      <div className="flex items-center gap-2 text-[13px] text-[var(--c-text-2)]">
                        <Brain size={15} weight="duotone" style={{ color: 'var(--c-tone-violet)' }} className="animate-pulse" />
                        <span>{msg.phaseLabel}</span>
                      </div>
                    )}

                    {displayContent && (
                      <div className={`md-prose ${msg.error ? 'text-[var(--c-error)]' : ''}`}>
                        <Markdown
                          remarkPlugins={[remarkGfm]}
                          components={{
                            code: ({ className, children }) => (
                              <CodeBlock className={className}>{children}</CodeBlock>
                            ),
                          }}
                        >
                          {displayContent}
                        </Markdown>
                      </div>
                    )}

                    {stickerUrl && (
                      <img
                        src={stickerUrl}
                        alt="表情"
                        className="mt-2 h-20 w-20 object-contain"
                      />
                    )}

                    {voiceUrl && (
                      <audio controls src={voiceUrl} className="mt-2.5 h-8 max-w-full" />
                    )}
                  </div>

                  {/* Action row */}
                  {!msg.streaming && (
                    <div className="mt-1 flex items-center gap-2 px-1">
                      {msg.timestamp && (
                        <span className="text-[11px] text-[var(--c-text-3)]">
                          {friendlyTime(msg.timestamp)}
                        </span>
                      )}
                      {displayContent && (
                        <button
                          type="button"
                          onClick={() => {
                            navigator.clipboard?.writeText(displayContent);
                            setCopiedIndex(idx);
                            window.setTimeout(() => setCopiedIndex(null), 1400);
                          }}
                          className="inline-flex items-center gap-1 text-[11px] text-[var(--c-text-3)] opacity-0 transition group-hover:opacity-100 hover:text-[var(--c-text)]"
                        >
                          {copiedIndex === idx ? (
                            <Check size={12} weight="bold" className="text-[var(--c-success)]" />
                          ) : (
                            <Copy size={12} weight="duotone" />
                          )}
                          <span>{copiedIndex === idx ? '已复制' : '复制'}</span>
                        </button>
                      )}
                      {isLast && !streaming && (
                        <button
                          type="button"
                          onClick={handleRegenerate}
                          className="inline-flex items-center gap-1 text-[11px] text-[var(--c-text-3)] opacity-0 transition group-hover:opacity-100 hover:text-[var(--c-accent)]"
                        >
                          <ArrowCounterClockwise size={12} weight="bold" />
                          <span>重新生成</span>
                        </button>
                      )}
                    </div>
                  )}
                </motion.div>
              );
            })
          )}
        </div>
      </div>

      {/* Bottom Floating Liquid Glass Composer */}
      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-20 px-4 pb-4 pt-6 md:px-6">
        <div className="pointer-events-auto">
          <Composer
            onSend={handleSend}
            onUploadImage={handleUploadImage}
            onPickSticker={handlePickSticker}
            stickers={stickers}
            streaming={streaming}
            onStop={() => {
              streamRef.current?.abort();
              setStreaming(false);
            }}
          />
        </div>
      </div>
    </div>
  );
}
