import {
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  apiPut,
  apiRequest,
  downloadFile,
} from './client';

export interface ModelProviderItem {
  key: string;
  provider: string;
  model_name: string;
  base_url: string;
  multimodal: 'auto' | 'yes' | 'no' | string;
}

export interface ModelResponse {
  current: string | null;
  available: string[];
  providers: ModelProviderItem[];
  models: Record<string, { model_name: string; multimodal: string }>;
}

export interface BootstrapProvider {
  key: string;
  label: string;
  description: string;
  base_url: string;
  default_model: string;
  env_key?: string;
  provider: string;
}

export interface ModelRolesResponse {
  chat: { key?: string; provider: string; model_name: string; base_url: string } | null;
  vision: { key?: string; provider: string; model_name: string; base_url: string } | null;
  tts: { key?: string; provider: string; model_name: string; base_url: string } | null;
  pool: Array<{ key: string; provider: string; model_name: string; base_url: string }>;
  image_chain: string;
}

export interface SchemaField {
  section: string;
  key: string;
  label: string;
  type: 'float' | 'int' | 'bool';
  default: number | boolean;
  min?: number;
  max?: number;
  step?: number;
  hint?: string;
  target?: string;
  live?: boolean;
}

export const modelApi = {
  get: () => apiGet<ModelResponse>('/api/model'),
  set: (model: string) => apiPost<{ ok: boolean; current: string }>('/api/model', { model }),
  addProvider: (body: {
    key: string;
    provider: string;
    model_name: string;
    base_url: string;
    api_key: string;
    multimodal?: string;
    temperature?: number;
    max_tokens?: number;
    presence_penalty?: number;
    frequency_penalty?: number;
  }) => apiPost<{ ok: boolean; key: string; restart_required?: boolean }>('/api/model/provider', body),
  remove: (key: string) => apiDelete<{ ok: boolean }>(`/api/model/${encodeURIComponent(key)}`),
  discover: (base_url: string, api_key: string) =>
    apiPost<{ ok: boolean; models?: string[]; message?: string }>('/api/model/discover', {
      base_url,
      api_key,
    }),
  discoverByKey: (model_key: string) =>
    apiPost<{ ok: boolean; models?: string[]; message?: string }>('/api/model/discover', {
      model_key,
    }),
  setMultimodal: (model: string, multimodal: 'auto' | 'yes' | 'no') =>
    apiPost<{ ok: boolean; multimodal: string; image_chain: string }>('/api/model/multimodal', {
      model,
      multimodal,
    }),
  roles: () => apiGet<ModelRolesResponse>('/api/model/roles'),
  setRole: (role: 'chat' | 'vision' | 'tts', model_name: string, key = '') =>
    apiPost<{ ok: boolean; message?: string; image_chain?: string }>('/api/model/role', {
      role,
      model_name,
      key,
    }),
};

export const bootstrapApi = {
  status: () =>
    apiGet<{
      needs_setup: boolean;
      needs_persona_setup: boolean;
      models: string[];
      default_model: string | null;
    }>('/api/bootstrap/status'),
  providers: () => apiGet<{ providers: BootstrapProvider[] }>('/api/bootstrap/providers'),
  test: (body: { provider: string; base_url: string; api_key: string; model_name: string }) =>
    apiPost<{ ok: boolean; message?: string }>('/api/bootstrap/test', body),
};

export const visionApi = {
  get: () =>
    apiGet<{
      provider: string;
      model_name: string;
      base_url: string;
      has_api_key: boolean;
      main_model: string;
      main_multimodal_declared: string;
      main_is_multimodal: boolean;
      image_mode: 'auto' | 'direct' | 'vision';
      image_chain: string;
    }>('/api/vision/config'),
  set: (body: Record<string, unknown>) =>
    apiPost<{ ok: boolean; image_chain?: string }>('/api/vision/config', body),
};

export const settingsApi = {
  schema: () => apiGet<{ schema: SchemaField[] }>('/api/schema'),
  get: () => apiGet<{ values: Record<string, number | boolean> }>('/api/settings'),
  save: (values: Record<string, number | boolean>) =>
    apiPost<{ ok: boolean; values: Record<string, number | boolean> }>('/api/settings', { values }),
};

export interface VoiceProviderItem {
  name: string;
  provider?: string;
  base_url?: string;
  voice?: string;
  model?: string;
  enabled?: boolean;
  has_api_key?: boolean;
  [key: string]: unknown;
}

export const voiceApi = {
  list: () => apiGet<{ providers: VoiceProviderItem[]; active: string | null }>('/api/voice-providers'),
  add: (body: Record<string, unknown>) => apiPost<{ ok: boolean }>('/api/voice-providers', body),
  edit: (name: string, body: Record<string, unknown>) =>
    apiPut<{ ok: boolean }>(`/api/voice-providers/${encodeURIComponent(name)}`, body),
  remove: (name: string) =>
    apiDelete<{ ok: boolean }>(`/api/voice-providers/${encodeURIComponent(name)}`),
  test: (name: string) =>
    apiPost<{ ok: boolean; bytes?: number; error?: string }>(
      `/api/voice-providers/${encodeURIComponent(name)}/test`,
    ),
};

export const momentsAutoApi = {
  config: () =>
    apiGet<{
      config: {
        enabled: boolean;
        interval_minutes: number;
        persona_id: string;
        active_start: number;
        active_end: number;
      };
      personas: Array<{ id: string; name: string }>;
    }>('/api/moments/auto/config'),
  save: (body: Record<string, unknown>) =>
    apiPut<{ ok: boolean; config: Record<string, unknown> }>('/api/moments/auto/config', body),
  publish: () => apiPost<{ ok: boolean; error?: string }>('/api/moments/auto/publish'),
};

export interface WechatAccountItem {
  id: string;
  enabled: boolean;
  auto_start: boolean;
  persona_id: string;
  persona_name: string;
  has_credentials: boolean;
  adapter_running: boolean;
  session_expired: boolean;
}

export const wechatApi = {
  list: () => apiGet<WechatAccountItem[]>('/api/wechat/accounts'),
  add: (body: { id: string; persona_id?: string; enabled?: boolean; auto_start?: boolean }) =>
    apiPost<WechatAccountItem>('/api/wechat/accounts', body),
  edit: (id: string, body: { persona_id: string }) =>
    apiPatch<{ ok: boolean }>(`/api/wechat/accounts/${encodeURIComponent(id)}`, body),
  remove: (id: string) => apiDelete<{ ok: boolean }>(`/api/wechat/accounts/${encodeURIComponent(id)}`),
  logout: (id: string) =>
    apiPost<{ ok: boolean }>(`/api/wechat/logout/${encodeURIComponent(id)}`),
  qrcodeUrl: (id: string) => `/api/wechat/login/${encodeURIComponent(id)}/qrcode`,
};

export interface McpServerItem {
  name: string;
  command: string;
  args?: string[];
  env?: Record<string, string>;
  enabled?: boolean;
  _state?: string;
  _connected?: boolean;
  _tools?: number;
}

export const mcpApi = {
  list: () => apiGet<{ servers: McpServerItem[] }>('/api/mcp/servers'),
  add: (body: Record<string, unknown>) => apiPost<{ ok: boolean }>('/api/mcp/servers', body),
  edit: (name: string, body: Record<string, unknown>) =>
    apiPut<{ ok: boolean }>(`/api/mcp/servers/${encodeURIComponent(name)}`, body),
  remove: (name: string) =>
    apiDelete<{ ok: boolean }>(`/api/mcp/servers/${encodeURIComponent(name)}`),
  action: (name: string, action: 'test' | 'connect' | 'disconnect' | 'refresh') =>
    apiPost<{ ok: boolean; connected?: boolean; tools?: number; error?: string }>(
      `/api/mcp/servers/${encodeURIComponent(name)}/${action}`,
    ),
  tools: (name: string) =>
    apiGet<{ tools: Array<{ name: string; description: string }> }>(
      `/api/mcp/servers/${encodeURIComponent(name)}/tools`,
    ),
};

export const pluginsApi = {
  list: () =>
    apiGet<{
      plugins: Array<{ source: string; name: string; description: string; server?: string }>;
      builtin_count: number;
      mcp_count: number;
    }>('/api/plugins'),
};

export const monitorApi = {
  health: () =>
    apiGet<{
      ok: boolean;
      models: number;
      mcp_servers: number;
      runtime: { uptime_seconds: number; operations?: Record<string, unknown> };
    }>('/api/health'),
  diagnostics: () =>
    apiGet<{
      generated_at: string;
      overall: string;
      summary: { ok: number; warn: number; error: number };
      checks: Array<{ name: string; status: string; message: string }>;
    }>('/api/diagnostics'),
};

export const diagApi = {
  exportDiagnostics: () => downloadFile('/api/diagnostics/export'),
  backup: () => downloadFile('/api/backup', 'POST'),
  restore: (file: File) => {
    const fd = new FormData();
    fd.append('backup', file);
    return apiRequest<{ ok: boolean; restart_required?: boolean }>('/api/restore', {
      method: 'POST',
      body: fd,
    });
  },
  about: () =>
    apiGet<{
      name: string;
      version: string;
      license: string;
      author: string;
      installation_id: string;
      storage: string;
      privacy: string;
      tagline: string;
    }>('/api/about'),
};
