// ============================================================
// lib/stateApi.js — 运行时状态聚合接口
//   GET /api/state?conversation_id=...
// ============================================================

/** 拉取当前会话的聚合状态: mood / affection / open_loops / memories / diary */
export async function fetchState(conversationId) {
  const q = conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : '';
  const r = await fetch(`/api/state${q}`, { headers: { Accept: 'application/json' } });
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try {
      const j = await r.json();
      if (j?.error) msg = j.error;
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  return r.json();
}
