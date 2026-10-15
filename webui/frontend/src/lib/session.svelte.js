// ============================================================
// lib/session.svelte.js — 当前活动会话 (跨组件共享)
//
// ChatPage 在选中会话时写入; 内心面板 / 今天页 / 沉浸抽屉读取后拉 /api/state。
// ============================================================
import { listConversations } from './chatApi.js';

export const session = $state({
  conversationId: null,
  personaId: '',
  personaName: '',
});

/** 由 ChatPage 在切换会话时调用 */
export function setActiveConversation({ id = null, personaId = '', personaName = '' } = {}) {
  session.conversationId = id;
  session.personaId = personaId || '';
  session.personaName = personaName || '';
}

// ============================================================
// 状态刷新信号
//
// 内心面板 / 今天页 / 记忆页在 effect 里读取 stateRevision.n，
// 对话结束（或后台记忆提取完成）后调用 refreshState() 即可让它们重新拉取。
// 记忆提取是后台异步任务，所以再延迟补一次，避免第一次拉取时还没落库。
// ============================================================
export const stateRevision = $state({ n: 0 });

let _delayedTimer = null;

export function refreshState({ delayed = true } = {}) {
  stateRevision.n += 1;
  if (delayed) {
    // 合并窗口：连续多轮回复只保留一个延迟补拉，避免每个 bump 触发一轮全量重拉
    if (_delayedTimer) clearTimeout(_delayedTimer);
    _delayedTimer = setTimeout(() => {
      _delayedTimer = null;
      stateRevision.n += 1;
    }, 5000);
  }
}

// ============================================================
// 确保存在活动会话
//
// 内心面板 / 今天页 / 记忆页都要带 conversation_id 才能读到正确的记忆作用域，
// 但这些页面不一定在聊天页之后才打开。这里在必要时自己解析一个活动会话
// （优先 cc-chat-persona 指定的人设，否则取第一个）。
// ============================================================
let _ensuring = null;

export async function ensureActiveConversation() {
  if (session.conversationId) return session.conversationId;
  if (_ensuring) return _ensuring;
  _ensuring = (async () => {
    try {
      const list = await listConversations();
      // await 期间 ChatPage 可能已经设置好活动会话：以它为准，不要覆盖
      if (session.conversationId) return session.conversationId;
      const arr = Array.isArray(list) ? list : [];
      let pick = null;
      try {
        const preferred = localStorage.getItem('cc-chat-persona');
        if (preferred) pick = arr.find((c) => c.persona_id === preferred) || null;
      } catch {
        /* ignore */
      }
      pick = pick || arr[0] || null;
      if (pick) {
        setActiveConversation({
          id: pick.conversation_id,
          personaId: pick.persona_id,
          personaName: pick.persona_name || '',
        });
      }
      return session.conversationId;
    } catch {
      return null;
    } finally {
      _ensuring = null;
    }
  })();
  return _ensuring;
}
