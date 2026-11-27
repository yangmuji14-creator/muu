export interface ApiResponse<T = unknown> {
  ok: boolean;
  status: number;
  data: T | null;
  error?: string;
}

export async function apiRequest<T = unknown>(
  url: string,
  options: RequestInit = {},
): Promise<ApiResponse<T>> {
  const isForm = options.body instanceof FormData;
  const headers: Record<string, string> = {
    accept: 'application/json',
    ...((options.headers as Record<string, string>) || {}),
  };
  if (!isForm && options.body && !headers['content-type']) {
    headers['content-type'] = 'application/json';
  }
  try {
    const res = await fetch(url, { ...options, headers });
    const data = (await res.json().catch(() => null)) as T | null;
    const errText =
      !res.ok && data && typeof data === 'object' && 'error' in data
        ? String((data as { error?: unknown }).error ?? '')
        : undefined;
    return {
      ok: res.ok,
      status: res.status,
      data,
      error: errText || (!res.ok ? `请求失败 (${res.status})` : undefined),
    };
  } catch (err) {
    return {
      ok: false,
      status: 0,
      data: null,
      error: err instanceof Error ? err.message : '网络连接失败',
    };
  }
}

export function apiGet<T = unknown>(url: string) {
  return apiRequest<T>(url);
}

export function apiPost<T = unknown>(url: string, body?: unknown) {
  return apiRequest<T>(url, {
    method: 'POST',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

export function apiPut<T = unknown>(url: string, body?: unknown) {
  return apiRequest<T>(url, {
    method: 'PUT',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

export function apiPatch<T = unknown>(url: string, body?: unknown) {
  return apiRequest<T>(url, {
    method: 'PATCH',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

export function apiDelete<T = unknown>(url: string) {
  return apiRequest<T>(url, { method: 'DELETE' });
}

export function apiPostFile<T = unknown>(url: string, file: File, field = 'file') {
  const fd = new FormData();
  fd.append(field, file);
  return apiRequest<T>(url, { method: 'POST', body: fd });
}

export async function downloadFile(
  resource: string,
  method: 'GET' | 'POST' = 'GET',
  body: unknown = null,
): Promise<ApiResponse<{ filename: string }>> {
  try {
    const res = await fetch(resource, {
      method,
      headers: body ? { 'content-type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => `HTTP ${res.status}`);
      return { ok: false, status: res.status, data: null, error: text };
    }
    const blob = await res.blob();
    const cd = res.headers.get('content-disposition') || '';
    const m = cd.match(/filename\*?=(?:UTF-8''|")?([^";]+)/i);
    let filename = (m ? m[1] : resource.split('/').pop() || 'download') + '.zip';
    filename = decodeURIComponent(filename).replace(/"/g, '');
    if (filename.endsWith('.zip.zip')) filename = filename.slice(0, -4);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    return { ok: true, status: res.status, data: { filename } };
  } catch (err) {
    return {
      ok: false,
      status: 0,
      data: null,
      error: err instanceof Error ? err.message : '下载失败',
    };
  }
}
