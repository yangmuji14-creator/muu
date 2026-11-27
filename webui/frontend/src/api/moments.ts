import { apiDelete, apiGet, apiPost } from './client';

export interface MomentLike {
  author: string;
  author_label: string;
}

export interface MomentReply {
  id: string;
  author: string;
  author_label: string;
  timestamp: string;
  text: string;
  reply_to?: string | null;
  reply_to_label?: string | null;
}

export interface MomentItem {
  id: string;
  author: string;
  author_label: string;
  timestamp: string;
  text: string;
  likes: MomentLike[];
  replies: MomentReply[];
  images?: unknown;
  image_urls?: unknown;
  image_url?: string;
  liked_by_me?: boolean;
  liked?: boolean;
}

export const momentsApi = {
  list: (limit = 20) =>
    apiGet<{ moments: MomentItem[]; has_more: boolean }>(`/api/moments?limit=${limit}`),
  personas: () =>
    apiGet<{ personas: Array<{ id: string; name: string }> }>('/api/moments/personas'),
  publish: (body: { text: string; author?: string }) =>
    apiPost<{ ok: boolean; moment: MomentItem }>('/api/moments', body),
  remove: (id: string) => apiDelete<{ ok: boolean }>(`/api/moments/${encodeURIComponent(id)}`),
  like: (id: string) => apiPost<{ ok: boolean }>(`/api/moments/${encodeURIComponent(id)}/like`, {}),
  unlike: (id: string) => apiDelete<{ ok: boolean }>(`/api/moments/${encodeURIComponent(id)}/like`),
  reply: (id: string, body: { text: string; reply_to?: string }) =>
    apiPost<{ ok: boolean; reply: MomentReply }>(
      `/api/moments/${encodeURIComponent(id)}/replies`,
      body,
    ),
  removeReply: (momentId: string, replyId: string) =>
    apiDelete<{ ok: boolean }>(
      `/api/moments/${encodeURIComponent(momentId)}/replies/${encodeURIComponent(replyId)}`,
    ),
};
