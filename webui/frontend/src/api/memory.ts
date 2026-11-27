import { apiDelete, apiGet, apiPost } from './client';

export interface MemoryItem {
  id: string;
  content: string;
  level: number;
  category: string;
  created_at: string;
  tags: string[];
  source: string;
  confidence: number;
  last_accessed?: string;
  archived?: boolean;
}

export interface MemoryDetail extends MemoryItem {
  access_count: number;
  related_memory_ids: string[];
  superseded_by?: string | null;
  forget_score: number;
}

export interface LifeSummaryItem {
  id: string;
  summary_type: string;
  summary: string;
  recent_status: string;
  key_events: string[];
  message_count: number;
  created_at: string;
  emotional_trends: Record<string, unknown> | string[] | string;
}

export interface MemoryStatus {
  available?: boolean;
  loaded?: boolean;
  model?: string;
  total?: number;
  indexed?: number;
  coverage?: number;
  [key: string]: unknown;
}

export interface SemanticSearchResult {
  id?: string;
  content: string;
  score?: number;
  similarity?: number;
  level?: number;
  category?: string;
  tags?: string[];
  created_at?: string;
}

function buildQuery(params: Record<string, string | number | undefined>) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v));
  }
  return q.toString();
}

export const memoryApi = {
  list: (opts: {
    conversation_id?: string;
    persona_id?: string;
    offset?: number;
    limit?: number;
    level_min?: number;
    level_max?: number;
  }) => apiGet<{ messages: MemoryItem[]; total: number }>(`/api/memory?${buildQuery(opts)}`),

  detail: (id: string, opts: { conversation_id?: string; persona_id?: string }) =>
    apiGet<MemoryDetail>(`/api/memory/${encodeURIComponent(id)}?${buildQuery(opts)}`),

  remove: (id: string, opts: { conversation_id?: string; persona_id?: string }) =>
    apiDelete<{ ok: boolean }>(`/api/memory/${encodeURIComponent(id)}?${buildQuery(opts)}`),

  status: () => apiGet<MemoryStatus>('/api/memory/status'),

  search: (q: string, opts: { conversation_id?: string; persona_id?: string; top_k?: number }) =>
    apiGet<{ query: string; results: SemanticSearchResult[]; semantic: boolean }>(
      `/api/memory/search?${buildQuery({ q, ...opts })}`,
    ),

  reindex: (body: { force?: boolean; conversation_id?: string; persona_id?: string } = {}) =>
    apiPost<{ ok: boolean; [key: string]: unknown }>('/api/memory/reindex', body),

  lifeSummaries: (opts: { conversation_id?: string; persona_id?: string; limit?: number }) =>
    apiGet<{ summaries: LifeSummaryItem[]; total: number }>(
      `/api/life_summary?${buildQuery(opts)}`,
    ),

  latestLifeSummary: (opts: { conversation_id?: string; persona_id?: string }) =>
    apiGet<LifeSummaryItem | null>(`/api/life_summary/latest?${buildQuery(opts)}`),
};
