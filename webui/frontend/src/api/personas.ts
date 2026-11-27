import { apiDelete, apiGet, apiPost, apiPostFile } from './client';

export interface PersonaSummary {
  id: string;
  name: string;
  avatar: string;
  age?: number | null;
  gender?: string;
  occupation?: string;
  personality?: string[];
  relationship_level?: number | null;
  summary?: string;
}

export interface PersonaDetail {
  id: string;
  name: string;
  age?: number | null;
  gender?: string;
  occupation?: string;
  background?: string;
  personality?: string[];
  speaking_style?: string;
  relationship?: string;
  avatar?: string;
  [key: string]: unknown;
}

export interface PersonaTagsMeta {
  version: number;
  tags: string[];
  specs: Array<{
    tag: string;
    speaking?: string;
    emotion?: string;
    relationship?: string;
    hard_rules?: string[];
  }>;
  max_tags: number;
  mutex_groups: string[][];
}

export const personasApi = {
  list: () => apiGet<PersonaSummary[]>('/api/persona'),
  get: (id: string) => apiGet<PersonaDetail>(`/api/persona/${encodeURIComponent(id)}`),
  getAdvanced: (id: string) =>
    apiGet<Record<string, unknown>>(`/api/persona/${encodeURIComponent(id)}/advanced`),
  update: (id: string, fields: Record<string, unknown>) =>
    apiPost<{ ok: boolean; persona: { id: string; name: string } }>(
      `/api/persona/${encodeURIComponent(id)}`,
      { fields },
    ),
  tags: () => apiGet<PersonaTagsMeta>('/api/persona/tags'),
  previewTags: (tags: string[]) =>
    apiPost<{
      speaking?: string;
      emotion?: string;
      relationship?: string;
      hard_rules?: string[];
      conflicts?: string[][];
      unknown?: string[];
      truncated?: string[];
    }>('/api/persona/tags/preview', { tags }),
  create: (body: {
    id?: string;
    name: string;
    description?: string;
    personality?: string[];
    drafts?: { speaking?: string; emotion?: string; relationship?: string };
  }) =>
    apiPost<{ ok: boolean; generated_id: boolean; persona: { id: string; name: string } }>(
      '/api/persona',
      body,
    ),
  remove: (id: string) => apiDelete<{ ok: boolean }>(`/api/persona/${encodeURIComponent(id)}`),
  uploadAvatar: (id: string, file: File) =>
    apiPostFile<{ ok: boolean; avatar_url: string }>(
      `/api/persona/${encodeURIComponent(id)}/avatar`,
      file,
      'file',
    ),
};
