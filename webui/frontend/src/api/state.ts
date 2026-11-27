import { apiGet } from './client';

export interface CompanionState {
  user_id: string;
  persona_id: string;
  persona_name: string;
  mood: {
    key: string;
    label: string;
    valence: number;
    arousal: number;
    intensity: number;
    energy: number;
  } | null;
  affection: {
    level: number;
    stage: string;
  } | null;
  open_loops: Array<{
    id: string;
    title: string;
    category: string;
    expected_date: string;
  }>;
  memories: Array<{
    id: string;
    content: string;
    level: number;
    category: string;
  }>;
  diary: {
    summary: string;
    summary_type: string;
    recent_status: string;
    created_at: string;
  } | null;
  monologue: string;
}

export async function fetchState(conversationId?: string | null): Promise<CompanionState> {
  const q = conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : '';
  const r = await apiGet<CompanionState>(`/api/state${q}`);
  if (!r.ok || !r.data) throw new Error(r.error || '加载状态失败');
  return r.data;
}
