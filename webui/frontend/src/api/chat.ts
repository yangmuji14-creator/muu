import { apiDelete, apiGet, apiPatch, apiPost, apiRequest } from './client';

export interface ConversationBinding {
  conversation_id: string;
  platform: string;
  account_id?: string;
  contact_id?: string;
  persona_id: string;
  persona_name?: string;
  title?: string;
  created_at?: string;
  updated_at?: string;
}

export interface MessageBlock {
  type: 'text' | 'image' | 'emoji' | 'voice';
  text?: string;
  url?: string;
  pack?: string;
  emotion?: string;
  filename?: string;
}

export interface ChatMessage {
  id?: string;
  role: 'user' | 'assistant';
  content: string;
  reasoning?: string;
  reasoningDone?: boolean;
  reasoningDurationMs?: number;
  timestamp?: string;
  blocks?: MessageBlock[];
  image?: string;
  voice?: string;
  sticker?: {
    pack: string;
    emotion: string;
    filename: string;
    url: string;
  };
  platform?: string;
  streaming?: boolean;
  phaseLabel?: string;
  error?: boolean;
}

export interface StickerGroup {
  pack: string;
  emotion: string;
  images: string[];
}

export async function listConversations(): Promise<ConversationBinding[]> {
  const r = await apiGet<ConversationBinding[]>('/api/conversations');
  if (!r.ok || !Array.isArray(r.data)) throw new Error(r.error || '加载会话失败');
  return r.data;
}

export async function createConversation(persona_id: string, platform = 'web') {
  const contact_id =
    platform === 'web'
      ? `web_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`
      : persona_id;
  const r = await apiPost<ConversationBinding>('/api/conversations', {
    platform,
    persona_id,
    contact_id,
  });
  if (!r.ok || !r.data) throw new Error(r.error || '创建会话失败');
  return r.data;
}

export async function updateConversation(
  id: string,
  payload: { persona_id?: string; title?: string },
) {
  const r = await apiPatch<ConversationBinding>(
    `/api/conversations/${encodeURIComponent(id)}`,
    payload,
  );
  if (!r.ok || !r.data) throw new Error(r.error || '更新会话失败');
  return r.data;
}

export async function deleteConversation(id: string) {
  const r = await apiDelete<{ ok: boolean }>(`/api/conversations/${encodeURIComponent(id)}`);
  if (!r.ok) throw new Error(r.error || '删除会话失败');
  return r.data;
}

export async function fetchHistory(conversationId: string): Promise<ChatMessage[]> {
  const q = new URLSearchParams({ conversation_id: conversationId });
  const r = await apiGet<{ messages: ChatMessage[] }>(`/api/history?${q.toString()}`);
  if (!r.ok) throw new Error(r.error || '加载历史记录失败');
  return Array.isArray(r.data?.messages) ? r.data.messages : [];
}

export async function deleteLastMessagePair(conversationId: string) {
  const q = new URLSearchParams({ conversation_id: conversationId });
  const r = await apiDelete<{ ok: boolean; remaining: number }>(`/api/history/last?${q.toString()}`);
  if (!r.ok) throw new Error(r.error || '删除上一轮对话失败');
  return r.data;
}

export async function listStickers(): Promise<StickerGroup[]> {
  const r = await apiGet<{ stickers: StickerGroup[] }>('/api/stickers');
  if (!r.ok || !Array.isArray(r.data?.stickers)) return [];
  return r.data.stickers;
}

export async function uploadImage(
  file: File,
  opts: { caption?: string; conversation_id?: string } = {},
) {
  const fd = new FormData();
  fd.append('image', file);
  if (opts.caption) fd.append('caption', opts.caption);
  if (opts.conversation_id) fd.append('conversation_id', opts.conversation_id);
  const r = await apiRequest<{ ok: boolean; image_url: string }>('/api/upload/image', {
    method: 'POST',
    body: fd,
  });
  if (!r.ok || !r.data) throw new Error(r.error || '上传图片失败');
  return r.data;
}

/**
 * Splits inline <think>...</think> blocks from reply text cleanly.
 */
export function parseInlineThink(raw: string): { thinking: string; reply: string; inThink: boolean } {
  const openTag = '<think>';
  const closeTag = '</think>';
  const start = raw.indexOf(openTag);
  if (start === -1) {
    return { thinking: '', reply: raw, inThink: false };
  }
  const afterOpen = start + openTag.length;
  const end = raw.indexOf(closeTag, afterOpen);
  if (end === -1) {
    return {
      thinking: raw.slice(afterOpen),
      reply: raw.slice(0, start),
      inThink: true,
    };
  }
  const thinking = raw.slice(afterOpen, end).trim();
  const reply = (raw.slice(0, start) + raw.slice(end + closeTag.length)).replace(/^\n+/, '');
  return { thinking, reply, inThink: false };
}

export interface ChatStreamOptions {
  body: {
    content: string;
    conversation_id?: string;
    persona_id?: string;
    request_id?: string;
    sticker?: { pack: string; emotion: string; filename: string };
  };
  onToken?: (data: { token: string }) => void;
  onPhase?: (data: { name: string; label: string }) => void;
  onReasoning?: (data: { text: string }) => void;
  onSticker?: (data: { pack: string; emotion: string; filename: string; url: string }) => void;
  onDone?: (data: { reply?: string; level?: number; voice_url?: string | null }) => void;
  onError?: (data: { error: string }) => void;
  signal?: AbortSignal;
}

const decoder = new TextDecoder();

export function chatStream(opts: ChatStreamOptions): { signal: AbortSignal; abort: () => void } {
  const controller = new AbortController();
  const abort = () => controller.abort();

  if (opts.signal) {
    if (opts.signal.aborted) abort();
    else opts.signal.addEventListener('abort', abort, { once: true });
  }

  function dispatch(ev: { event: string; data: Record<string, unknown> }) {
    const d = ev.data || {};
    switch (ev.event) {
      case 'token':
        opts.onToken?.({ token: String(d.token ?? '') });
        break;
      case 'phase':
        opts.onPhase?.({ name: String(d.name ?? ''), label: String(d.label ?? '') });
        break;
      case 'reasoning':
        opts.onReasoning?.({ text: String(d.text ?? '') });
        break;
      case 'sticker':
        opts.onSticker?.({
          pack: String(d.pack ?? ''),
          emotion: String(d.emotion ?? ''),
          filename: String(d.filename ?? ''),
          url: String(d.url ?? ''),
        });
        break;
      case 'done':
        opts.onDone?.({
          reply: d.reply !== undefined ? String(d.reply) : undefined,
          level: typeof d.level === 'number' ? d.level : undefined,
          voice_url: typeof d.voice_url === 'string' ? d.voice_url : null,
        });
        break;
      case 'error':
        opts.onError?.({ error: String(d.error || '生成失败') });
        break;
      default:
        break;
    }
  }

  function parseBlock(block: string) {
    let eventName = 'message';
    const dataLines: string[] = [];
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) {
        eventName = line.slice('event:'.length).trim();
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice('data:'.length).trim());
      }
    }
    if (dataLines.length === 0) return null;
    const dataText = dataLines.join('\n');
    let data: Record<string, unknown>;
    try {
      data = JSON.parse(dataText) as Record<string, unknown>;
    } catch {
      data = { raw: dataText };
    }
    return { event: eventName, data };
  }

  function feed(text: string) {
    let rest = text;
    let idx: number;
    while ((idx = rest.indexOf('\n\n')) !== -1) {
      const block = rest.slice(0, idx);
      rest = rest.slice(idx + 2);
      const ev = parseBlock(block);
      if (ev) dispatch(ev);
    }
    return rest;
  }

  (async () => {
    let res: Response;
    try {
      res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'content-type': 'application/json', accept: 'text/event-stream' },
        body: JSON.stringify(opts.body),
        signal: controller.signal,
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      opts.onError?.({ error: '网络请求失败，请检查服务是否启动' });
      return;
    }

    if (!res.ok || !res.body) {
      let msg = `请求失败 (${res.status})`;
      try {
        const j = (await res.json()) as { error?: string };
        if (j?.error) msg = j.error;
      } catch {
        /* ignore */
      }
      opts.onError?.({ error: msg });
      return;
    }

    const reader = res.body.getReader();
    let buffer = '';
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (controller.signal.aborted) return;
        if (done) break;
        buffer = feed(buffer + decoder.decode(value, { stream: true }));
      }
      feed(buffer + decoder.decode());
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      opts.onError?.({ error: '连接中断，回复不完整' });
    }
  })();

  return { signal: controller.signal, abort };
}

export function subscribeHistoryEvents(
  conversationId: string,
  onHistoryChanged: () => void,
): () => void {
  const q = new URLSearchParams({ conversation_id: conversationId });
  const es = new EventSource(`/api/events?${q.toString()}`);
  es.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data) as { type?: string };
      if (data.type === 'history_changed') onHistoryChanged();
    } catch {
      /* ignore ping */
    }
  };
  return () => es.close();
}
