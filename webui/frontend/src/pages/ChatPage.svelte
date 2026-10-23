<script>
  // ChatPage.svelte — 聊天页（完整业务逻辑）
  // Svelte 5 runes。消费后端 /api/* 契约 (见 lib/chatApi.js), SSE 流式见 lib/chatStream.js。  // 只改本文件 + 自己的 lib 模块; 不动后端/全局结构/其它页面。
  import {
    listConversations,
    createConversation,
    updateConversation,
    deleteConversation,
    fetchHistory,
    listPersonas,
    listStickers,
    uploadImage,
  } from '../lib/chatApi.js';
  import { chatStream } from '../lib/chatStream.js';
  import { monitorApi } from '../lib/monitorApi.js';
  import { navigate } from '../lib/router.js';
  import { layout } from '../lib/layout.svelte.js';
  import { setActiveConversation, refreshState } from '../lib/session.svelte.js';
  import { confirmDialog, promptDialog } from '../lib/dialog.svelte.js';
  import ConfigNotice from '../components/ConfigNotice.svelte';

  // 后端将配置缺失/出错"包装成 done 事件的友好文案，命中即渲染为配置提示卡片而非普通气泡。
  const CONFIG_ERROR_TEXTS = [
    '我还没配置好模型呢',
    'API key 好像有问题',
    '模型太忙了',
    '网络有点慢',
    '网络好像断了',
    '出了点小问题',
    '我找不到我的人设了',
  ];
  function isConfigErrorText(reply) {
    const t = String(reply ?? '');
    if (!t) return false;
    return CONFIG_ERROR_TEXTS.some((k) => t.includes(k));
  }

  // ---------- 后端数据 (会话/人设/贴纸) ----------
  let conversations = $state([]);
  let personas = $state([]);
  let stickerGroups = $state([]); // [{pack,emotion,images:[]}]

  // ---------- 界面状态 ----------
  let activeConvId = $state(null);
  let messages = $state([]); // [{role,content,timestamp,sticker?,voice_url?,streaming?}]
  let loadingHistory = $state(false);

  let input = $state('');
  let sending = $state(false);
  let phase = $state(null); // {name,label}
  // 深度思考内容挂在消息对象上 (m.reasoning / m.thinkingOpen)，这样每条回复的思考
  // 都显示在它自己的气泡上方，而不是统一堆在输入框上面。

  let error = $state(null); // toast
  let toastTimer = null;

  // 模型/服务商配置就绪状态 null=检测中, true=已就绪(models>0), false=未配置(Key 无效
  let modelReady = $state(null);
  let modelChecking = $state(false);

  let showStickerPanel = $state(false);
  let uploading = $state(false);
  let previewImage = $state(null); // 点击气泡图片时的全屏预览 URL
  let voicePlayingUrl = $state(null); // 正在播放的语音条
  let voiceDurations = $state({});    // url -> 时长秒（metadata 加载后填充）
  let voiceAudio = null;

  /** 微信式语音条：点击播放/暂停 */
  function toggleVoice(url) {
    if (voicePlayingUrl === url) {
      voiceAudio?.pause();
      voiceAudio = null;
      voicePlayingUrl = null;
      return;
    }
    voiceAudio?.pause();
    voiceAudio = new Audio(url);
    voiceAudio.onended = () => {
      voicePlayingUrl = null;
      voiceAudio = null;
    };
    voiceAudio.onerror = () => {
      voicePlayingUrl = null;
      voiceAudio = null;
    };
    voiceAudio.play().catch(() => (voicePlayingUrl = null));
    voicePlayingUrl = url;
  }

  // 会话抽屉 (移动端
  let listOpen = $state(false);
  let isMobile = $state(false);

  // 最近一次流式stream 句柄 (换会话时发新消息/卸载时 abort)
  let agentStream = null;
  let unmountAbort = new AbortController();

  // 滚动锚点
  let messagesEl = $state(null);
  let bottomEl = $state(null);

  // ---------- 派生 ----------
  let activeConv = $derived(
    activeConvId ? conversations.find((c) => c.conversation_id === activeConvId) ?? null : null,
  );
  // ---------- 消息去抖（Web 端）----------
  // 与微信侧 DebounceManager 同构，且读同一个设置项「去抖延迟（秒）」：
  // 发出消息后先等 debounceSecs 秒，期间再发就重置计时；
  // 计时到 → 这段时间的多条消息**合并成一轮**提交（用 \n 拼接）。
  // 图片也在序列里（PawzoChat/微信式）：上传秒回后入队，与文字共用同一
  // 窗口；窗口内发的文字提交时由服务端认领 pending 图片，聚合成图+文一轮。
  // 回复生成中收到的消息则入队，等这一轮结束立即提交（不再二次等待）。
  let pendingQueue = $state([]); // [{content, streamContent, sticker?, imageOnly?, msgRef}]
  let debounceTimer = null;
  let debounceSecs = $state(3);   // 由 /api/settings 的 debounce_seconds 覆盖
  let debouncing = $state(false); // 正在等待合并窗口
  let canSend = $derived(!uploading && input.trim().length > 0);

  function clearDebounce() {
    if (debounceTimer) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
    debouncing = false;
  }

  /** 把一条消息放进待提交队列，并（重新）启动去抖计时 */
  function enqueue(item) {
    // PawzoChat 式顺序保证：消息自带到达时间戳，提交时按时间戳排序。
    // 即使队列因任何未知原因乱序（实测出现过一次），合并顺序也能恢复真实时序。
    pendingQueue = [...pendingQueue, { ...item, createdAt: Date.now() }];
    // 顺序指纹：定位「分段连发合并乱序」——enqueue 序 vs 提交序对照
    console.debug('[queue] enqueue', JSON.stringify(item.streamContent ?? item.content),
      '-> queue:', JSON.stringify(pendingQueue.map((q) => q.streamContent ?? q.content)));
    if (sending) return; // 正在生成：不另起计时，交给 finishStreaming 立即提交
    clearDebounce();
    debouncing = true;
    debounceTimer = setTimeout(() => {
      debounceTimer = null;
      debouncing = false;
      submitPending();
    }, Math.max(0, debounceSecs) * 1000);
  }

  /** 提交待发队列。
   *  - 多条文本合并成一轮（\n 拼接）；
   *  - 表情不与文本合并，一次只发一条（既有行为）；
   *  - 图片项（imageOnly）不发请求：它只参与去抖计时与排序，
   *    与文字同批时由服务端认领 pending 聚合；纯图片批次交给
   *    服务器看门兜底（自动按只发图处理）。 */
  function submitPending() {
    if (sending) return; // 生成中：交给 finishStreaming 立即提交
    if (uploading) {
      // 图片还在上传：推迟提交，传完再发（避免文字抢在图片入队前跑掉）
      clearDebounce();
      debouncing = true;
      debounceTimer = setTimeout(() => {
        debounceTimer = null;
        debouncing = false;
        submitPending();
      }, 600);
      return;
    }
    if (!pendingQueue.length) return;
    clearDebounce();
    // 表情不合并：一次只消费队首一条（既有行为）
    if (pendingQueue.some((it) => it.sticker)) {
      const first = pendingQueue[0];
      pendingQueue = pendingQueue.slice(1);
      if (first.sticker) {
        streamChat({ content: first.streamContent ?? first.content, sticker: first.sticker });
      } else {
        if (!first.imageOnly) {
          streamChat({ content: first.streamContent ?? first.content });
        }
        // 图片项不发请求（服务器看门兜底）；后面还有就继续消费
        if (pendingQueue.length) submitPending();
      }
      return;
    }
    const batch = [...pendingQueue].sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0));
    pendingQueue = [];
    const textItems = batch.filter((it) => !it.imageOnly);
    const hasImage = batch.some((it) => it.imageOnly);
    const merged = textItems.map((it) => it.streamContent ?? it.content).join('\n');
    console.debug('[queue] submit', JSON.stringify(merged), 'image:', hasImage, 'left:', pendingQueue.length);
    if (!merged.trim()) return; // 纯图片批次：不发请求，看门兜底；图片气泡保留
    if (textItems.length > 1) {
      // 多条文本合并成一条：只合并文本气泡；图片气泡保留（服务端会落一条
      // 带图消息，同步历史后按 blocks 渲染图行+文行，视觉一致）。
      // 按消息对象引用删除（review P2-8）。
      const queuedRefs = new Set(textItems.map((it) => it.msgRef).filter(Boolean));
      const keep = queuedRefs.size === textItems.length
        ? messages.filter((m) => !queuedRefs.has(m))
        : messages.slice(0, messages.length - textItems.length);
      messages = [...keep, { role: 'user', content: merged, timestamp: nowISO() }];
    }
    streamChat({ content: merged });
  }
  let personaOfActive = $derived(activeConv?.persona_id ?? null);
  let activePersona = $derived(personas.find((p) => p.id === personaOfActive) ?? null);

  // 把当前会话同步到全局 session, 供内心面板 / 今天页 / 沉浸抽屉读取
  $effect(() => {
    setActiveConversation({
      id: activeConvId,
      personaId: personaOfActive || '',
      personaName: activePersona?.name || activeConv?.persona_name || '',
    });
  });

  // ---------- 生命周期 ----------
  $effect(() => {
    const mq = window.matchMedia('(max-width: 767px)');
    const apply = () => (isMobile = mq.matches);
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  });

  $effect(() => {
    // 装载基础数据 + 检测模型配置
    let alive = true;
    loadAll();
    checkModelHealth();
    // 微信等外部渠道的消息 → Web 端准实时同步：轻量轮询历史，
    // 仅在空闲（未在生成/去抖/排队）且页面可见时拉取
    const syncTimer = setInterval(syncHistory, 5000);
    // 读「去抖延迟（秒）」：与微信侧共用同一设置项
    (async () => {
      try {
        const r = await fetch('/api/settings', { headers: { accept: 'application/json' } });
        const j = await r.json();
        const v = j?.values?.debounce_seconds;
        if (alive && typeof v === 'number' && v >= 0) debounceSecs = v;
      } catch {
        /* 读不到就用默认 3 秒 */
      }
    })();
    return () => {
      alive = false;
      clearDebounce();
      unmountAbort.abort();
      clearInterval(syncTimer);
      evtSource?.close();
      evtSource = null;
    };
    async function loadAll() {
      const results = await Promise.allSettled([listConversations(), listPersonas(), listStickers()]);
      if (!alive) return;
      const [convR, personaR, stickerR] = results;
      if (convR.status === 'fulfilled') conversations = convR.value;
      if (personaR.status === 'fulfilled') personas = personaR.value;
      if (stickerR.status === 'fulfilled') stickerGroups = stickerR.value;
    }
  });

  let syncing = false;
  /** 轮询同步：服务器消息数变多（微信侧新消息）时整体刷新本地列表。
   *  force=true（SSE 触发）时跳过去抖/排队守卫——外部渠道消息可在本地排队期间到达。 */
  async function syncHistory(force = false) {
    if (!activeConvId || sending || syncing || loadingHistory) return;
    if (!force && (debouncing || pendingQueue.length)) return;
    if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return;
    syncing = true;
    try {
      const list = await fetchHistory(activeConvId);
      if (sending) return; // 拉取期间本地开始了生成：不覆盖流式消息
      if (list.length > messages.length) {
        const nearBottom =
          !messagesEl ||
          messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 160;
        messages = list;
        if (nearBottom) jumpToBottom();
      }
    } catch {
      /* 静默：下一轮再试 */
    } finally {
      syncing = false;
    }
  }

  // ---- SSE 实时事件流（主通道）+ 5s 轮询（兜底）----
  let evtSource = null;
  function openEventStream(id) {
    evtSource?.close();
    evtSource = null;
    if (!id || typeof EventSource === 'undefined') return;
    try {
      evtSource = new EventSource(`/api/events?conversation_id=${encodeURIComponent(id)}`);
      evtSource.onmessage = (ev) => {
        try {
          const d = JSON.parse(ev.data);
          if (d.type === 'history_changed') syncHistory(true);
        } catch { /* 忽略坏帧 */ }
      };
      // EventSource 断线自动重连；彻底失败时轮询兜底
    } catch { /* 老浏览器无 SSE：轮询兜底 */ }
  }

  // 新消息 -> 滚到底部
  $effect(() => {
    if (!messagesEl || !bottomEl) return;
    if (loadingHistory) return; // 历史加载期间交给 jumpToBottom，避免两边抢滚动
    const n = messages.length;
    const s = sending;
    if (n > 0 || s) {
      // 流式期间每 token 一次 smooth 会不断打断滚动动画（review P3-1）：
      // 生成中用瞬时定位，结束后平滑滚一次
      bottomEl.scrollIntoView({ behavior: s ? 'auto' : 'smooth', block: 'end' });
    }
  });

  /** 载入历史后跳到最新消息。
   *  用瞬时定位（auto）而不是 smooth —— 长列表上 smooth 经常停在半路；
   *  再补两次，覆盖表情/图片/字体延迟加载导致的二次排版。 */
  function jumpToBottom() {
    const go = () => {
      if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight;
      bottomEl?.scrollIntoView({ behavior: 'auto', block: 'end' });
    };
    go();
    requestAnimationFrame(go);
    setTimeout(go, 120);
    setTimeout(go, 320);
  }

  // ---------- 会话操作 ----------
  let loadSeq = 0; // 会话历史加载序号：丢弃快速切换后的过期响应，避免旧会话串台
  async function selectConversation(id) {
    if (id === activeConvId && messages.length > 0) return;
    abortStream();
    activeConvId = id;
    phase = null;
    clearDebounce();
    pendingQueue = []; // 切换会话时丢弃未发出的排队消息，避免串到别的会话
    if (isMobile) listOpen = false;
    openEventStream(id);
    messages = [];
    loadingHistory = true;
    const seq = ++loadSeq;
    try {
      const list = await fetchHistory(id);
      if (seq !== loadSeq) return; // 已切走：丢弃过期响应
      messages = list;
      // 加载完历史后落到最新一条（刷新页面也停在最近聊的地方）
      jumpToBottom();
    } catch (e) {
      if (seq === loadSeq) showError(e.message);
    } finally {
      if (seq === loadSeq) loadingHistory = false;
    }
  }

  async function startWithPersona(persona_id) {
    // 复用已存在的同人设 web 会话, 否则新建
    const existing = conversations.find(
      (c) => c.persona_id === persona_id && c.platform === 'web',
    );
    if (existing) {
      showToast('已打开该会话');
      await selectConversation(existing.conversation_id);
      return;
    }
    try {
      const conv = await createConversation({ platform: 'web', persona_id });
      const fresh = await listConversations();
      conversations = fresh;
      await selectConversation(conv.conversation_id);
    } catch (e) {
      showError(e.message);
    }
  }

  async function newEmptyConversation() {
    // 新建会话：若有默认人设（或第一个人设）就打开其会话；后端按人设约束一个仅一个会话
    if (personas.length === 0) {
      showError('还没有可用的人设，请先在通讯录创建');
      return;
    }
    const persona = personas.find((p) => p.is_default) ?? personas[0];
    await startWithPersona(persona.id);
  }

  async function renameConversation(conv) {
    const title = await promptDialog('输入新的会话备注名（留空清除）', { title: '重命名会话', defaultValue: conv.title || '' });
    if (title === null) return;
    try {
      const updated = await updateConversation(conv.conversation_id, { title });
      conversations = conversations.map((c) =>
        c.conversation_id === updated.conversation_id ? updated : c,
      );
    } catch (e) {
      showError(e.message);
    }
  }

  async function removeConversation(conv) {
    const ok = await confirmDialog(`确定删除会话「${displayName(conv)}」？其历史消息也会清除。`, { title: '删除会话', danger: true });
    if (!ok) return;
    try {
      await deleteConversation(conv.conversation_id);
      conversations = conversations.filter((c) => c.conversation_id !== conv.conversation_id);
      if (activeConvId === conv.conversation_id) {
        abortStream();
        activeConvId = null;
        messages = [];
        clearDebounce();
        pendingQueue = [];
      }
    } catch (e) {
      showError(e.message);
    }
  }

  // ---------- 发送（SSE 流式） ----------
  function send() {
    const text = input.trim();
    if (!text || uploading) return;
    // 主动守卫: 模型未配置时拦截发送，引导去配置
    if (modelReady !== true) {
      showError('请先配置对话模型，AI 才能回复');
      return;
    }
    input = '';
    // 立刻显示自己的气泡（像真人聊天），再进入去抖窗口
    const msgRef = pushUserMessage(text);
    enqueue({ content: text, streamContent: text, msgRef });
  }

  function pushUserMessage(content, sticker, extra) {
    const msg = {
      role: 'user',
      content,
      timestamp: nowISO(),
      ...(sticker ? { sticker } : {}),
      ...(extra || {}),
    };
    messages = [...messages, msg];
    return msg;
  }

  /** 旧版图片消息的元文本清洗（只影响显示，不改落库数据）：
   *  '对方同时说：「xx」。对方发了一张图片：描述…' → 'xx'
   *  '对方发了一张图片：描述…' → '[图片]'。 */
  function cleanLegacyImageText(t) {
    if (!t) return t;
    const m = String(t).match(/^对方同时说：「([\s\S]*?)」。\s*对方发了一张图片：/);
    if (m) return m[1];
    if (/^对方发了一张图片：/.test(t)) return '[图片]';
    return t;
  }

  /** 消息 → content blocks（PawzoChat 式渲染输入）。
   *  服务器新消息自带 blocks；本地乐观消息/旧字段消息用 legacy 兜底组装。 */
  function blocksOf(m) {
    if (Array.isArray(m.blocks) && m.blocks.length) return m.blocks;
    const out = [];
    if (m.image) out.push({ type: 'image', url: m.image });
    if (m.sticker) out.push({ type: 'emoji', ...m.sticker });
    const t = String(m.content || '');
    const placeholder =
      (m.image && t.trim() === '[图片]') ||
      (m.sticker && t.trim() === '[表情]') ||
      (m.voice && t.trim() === '[语音]');
    if (t.trim() && !placeholder) out.push({ type: 'text', text: t });
    if (m.voice_url) out.push({ type: 'voice', url: m.voice_url });
    if (!out.length && t) out.push({ type: 'text', text: t });
    return out;
  }

  function streamChat({ content, sticker } = {}) {
    if (!activeConvId) {
      // 无会话时自动建一个会话（用 body persona_id; 这里用默认）
      showError('请先选择一个会话');
      return;
    }
    // 统一守卫（review P3-3）：文本/表情都走这里，模型未配置时一并拦截，
    // 与 send() 的行为保持一致（此前只有文本入口有守卫）
    if (modelReady !== true) {
      showError('请先配置对话模型，AI 才能回复');
      return;
    }
    if (sending) {
      // 已有回复在生成：不能并发发起（会 abort 掉当前流），应走 pendingQueue
      return;
    }
    abortStream();
    sending = true;
    phase = { name: 'context', label: '整理上下文' };

    // 先占用 assistant 气泡 (流式填充)；思考内容也挂在这条消息上
    messages = [
      ...messages,
      { role: 'assistant', content: '', streaming: true, timestamp: nowISO(), reasoning: '', thinkingOpen: true },
    ];

    const body = { content, conversation_id: activeConvId };
    if (personaOfActive) body.persona_id = personaOfActive;
    if (sticker) body.sticker = sticker;

    const currentLen = messages.length;

    agentStream = chatStream({
      body,
      signal: unmountAbort.signal,
      onToken: ({ token }) => {
        messages = messages.map((m, i) => {
          if (i === currentLen - 1 && m.streaming) return { ...m, content: m.content + token };
          return m;
        });
      },
      onPhase: ({ name, label }) => {
        phase = { name, label };
      },
      onReasoning: ({ text }) => {
        // 追加到当前这条 assistant 消息的 reasoning（显示在该气泡上方）
        messages = messages.map((m, i) =>
          i === currentLen - 1 && m.streaming
            ? { ...m, reasoning: (m.reasoning || '') + text }
            : m,
        );
      },
      onSticker: (stk) => {
        messages = messages.map((m, i) =>
          i === currentLen - 1 && m.streaming ? { ...m, sticker: stk } : m,
        );
      },
      onDone: ({ reply, voice_url }) => {
        const isConfig = isConfigErrorText(reply);
        messages = messages.map((m, i) => {
          if (i === currentLen - 1 && m.streaming) {
            return {
              ...m,
              content: reply ?? '',
              streaming: false,
              configError: isConfig || undefined,
              ...(voice_url ? { voice_url } : {}),
            };
          }
          return m;
        });
        finishStreaming();
        // 收到真实回复说明模型链路已通，顺带刷新一次配置状态
        if (!isConfig && modelReady !== true) checkModelHealth();
        // 让内心面板 / 记忆页 / 今天页重新拉取（含延迟补一次，等后台记忆提取落库）
        if (!isConfig) refreshState();
      },
      onError: ({ error: emsg }) => {
        const target = messages[currentLen - 1];
        if (target?.streaming) {
          if (target.content) {
            // 有半截内容：保留为不完整的消息
            messages = messages.map((m, i) =>
              i === currentLen - 1 ? { ...m, streaming: false } : m,
            );
          } else {
            // 空消息直接移除：否则头像+时间戳悬空无气泡（review P3-2）
            messages = messages.filter((_, i) => i !== currentLen - 1);
          }
        }
        finishStreaming();
        showError(emsg);
      },
    });
  }

  function finishStreaming() {
    sending = false;
    phase = null;
    agentStream = null;
    // 生成期间攒下的消息：立即提交（用户已经等过一轮，不再二次去抖）
    if (pendingQueue.length) submitPending();
  }

  function abortStream() {
    if (agentStream) {
      agentStream.abort();
      agentStream = null;
      // 中断后必须复位流状态：chatStream 对 AbortError 是静默 return（不走
      // onError/onDone），不复位的话 sending 永远为 true，聊天页死锁。
      sending = false;
      phase = null;
    }
  }

  // ---------- 图片上传（PawzoChat/微信式：选图即发，秒回上屏，支持多选） ----------
  async function pickImageFile(ev) {
    const files = Array.from(ev.target.files || []);
    ev.target.value = '';
    for (const f of files) {
      await sendImageFile(f);
    }
  }

  /** 图片立即上屏并上传（后端秒回）→ 加入去抖序列与文字同窗；
   *  窗口内发文字 → 服务端认领聚合成图+文一轮；纯图 → 服务器看门兜底。 */
  async function sendImageFile(file) {
    if (!activeConvId) {
      showError('请先选择一个会话');
      return;
    }
    const url = URL.createObjectURL(file);
    uploading = true;
    // 图片气泡先上屏（本地预览），上传完成后换成服务端 URL
    const localMsg = pushUserMessage('[图片]', null, { image: url });
    try {
      const data = await uploadImage(file, {
        conversation_id: activeConvId,
      });
      const serverUrl = data?.image_url;
      if (serverUrl) {
        messages = messages.map((m) => (m === localMsg ? { ...m, image: serverUrl } : m));
        // 图片加入去抖序列（PawzoChat/微信式）：入队即重置计时，与文字
        // 共用同一窗口；窗口内发的文字提交时服务端认领这张图聚合成一轮。
        enqueue({ content: '[图片]', streamContent: '[图片]', imageOnly: true, msgRef: localMsg });
      }
    } catch (e) {
      // 上传失败：撤掉本地预览气泡，避免和服务器历史对不上
      messages = messages.filter((m) => m !== localMsg);
      showError(e.message);
    } finally {
      uploading = false;
      if (url && !serverUrlKept(url)) URL.revokeObjectURL(url);
    }
  }

  /** 服务器已接管图片 URL 后本地 objectURL 才可释放 */
  function serverUrlKept(url) {
    return messages.some((m) => m.image === url);
  }

  // ---------- 贴纸 ----------
  async function sendSticker(group, filename) {
    const sticker = {
      pack: group.pack,
      emotion: group.emotion,
      filename,
      url: stickerUrl(group.pack, group.emotion, filename),
    };
    if (!activeConvId) {
      showError('请先选择一个会话');
      return;
    }
    showStickerPanel = false;
    // 气泡立刻出现，再进去抖窗口（表情不可与文本合并，会单独占一轮）
    const msgRef = pushUserMessage('[表情]', sticker);
    enqueue({ content: '[表情]', streamContent: `[表情:${group.emotion}]`, msgRef, sticker: { pack: group.pack, emotion: group.emotion, filename } });
  }

  // ---------- 工具 ----------
  function nowISO() {
    return new Date().toISOString();
  }
  function formatTime(ts) {
    if (!ts) return '';
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return '';
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    return `${hh}:${mm}`;
  }
  function displayName(conv) {
    return conv.title || conv.persona_name || '未命名会话';
  }
  function stickerUrl(pack, emotion, filename) {
    return `/api/stickers/file/${encodeURIComponent(pack)}/${encodeURIComponent(emotion)}/${encodeURIComponent(filename)}`;
  }
  function initialOf(name) {
    return (name || '?').trim().slice(0, 1).toUpperCase();
  }
  function showError(msg) {
    error = msg;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (error = null), 4000);
  }

  // 中性轻提示（复用 toast 展示位，非错误样式）
  function showToast(msg) {
    error = msg;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (error = null), 2500);
  }

  // 主动守卫: 通过 /api/health 检测模型是否已配置 (models===0 => 未配置( Key 无效)
  async function checkModelHealth() {
    modelChecking = true;
    const r = await monitorApi.health();
    modelChecking = false;
    // health 权威信号: models 为后端实际成功加载的模型实例数 ===0 即未配置(Key 无效
    const models = r && r.data ? Number(r.data.models) : 0;
    modelReady = r.ok === true && models > 0;
  }

  // 去模型设置子页（如 banner / 配置卡按钮
  function gotoModelSettings() {
    navigate('settings/model');
  }
  function stopEvent(e) {
    e.stopPropagation();
  }

  // 会话行上右键/点按菜单 (零依赖 以定位弹层替代原生 prompt)
  let menuOpen = $state(null); // { conv, x, y }

  function rowMenu(e, conv) {
    stopEvent(e);
    // 用按钮位置定位菜单，避免溢出边界
    const rect = e.currentTarget.getBoundingClientRect();
    menuOpen = { conv, x: rect.right, y: rect.bottom + 4 };
  }

  function closeMenu() {
    menuOpen = null;
  }

  function menuRename(conv) {
    closeMenu();
    renameConversation(conv);
  }

  function menuDelete(conv) {
    closeMenu();
    removeConversation(conv);
  }

  // 点击菜单外部关闭
  $effect(() => {
    if (!menuOpen) return;
    const onDoc = (e) => {
      if (!e.target.closest('.convs-menu, .row-menu')) closeMenu();
    };
    const onScroll = () => closeMenu();
    document.addEventListener('pointerdown', onDoc);
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onScroll);
    return () => {
      document.removeEventListener('pointerdown', onDoc);
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onScroll);
    };
  });


  async function renameConversationWithText(conv, title) {
    try {
      const updated = await updateConversation(conv.conversation_id, { title });
      conversations = conversations.map((c) =>
        c.conversation_id === updated.conversation_id ? updated : c,
      );
    } catch (e) {
      showError(e.message);
    }
  }

  // 首次进入: 自动选中第一个会话(如有)
  $effect(() => {
    if (!loadingHistory && activeConvId === null && conversations.length > 0 && messages.length === 0) {
      selectConversation(conversations[0].conversation_id);
    }
  });
</script>

<div class="chat-page" class:immersive={layout.mode === 'immersive'}>
  {#snippet recheckButton()}
    <button class="config-recheck" type="button" onclick={checkModelHealth} disabled={modelChecking} title="重新检测">
      {modelChecking ? '检测中…' : '重新检测'}
    </button>
  {/snippet}

  {#if isMobile && layout.mode !== 'immersive'}
    <header class="mobile-head">
      <button class="icon-btn" onclick={() => (listOpen = true)} aria-label="会话列表" title="会话列表">
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18M3 12h18M3 18h18"/></svg>
      </button>
      <span class="head-title">{activeConv ? displayName(activeConv) : '聊天'}</span>
      <button
        class="icon-btn" onclick={() => { if (activeConvId) renameConversation(activeConv); }}
        aria-label="重命名" title="重命名" disabled={!activeConvId}
      >
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
      </button>
    </header>
  {/if}

  <div class="chat-body">
    {#if !isMobile && layout.mode !== 'immersive'}
      <aside class="conv-panel">
        <div class="panel-head">
          <span class="panel-title">会话</span>
          {#if conversations.length > 0}
            <span class="panel-count">{conversations.length}</span>
          {/if}
          <button class="add-btn" onclick={() => newEmptyConversation()} title="新建会话">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
          </button>
        </div>
        <div class="conv-list">
          {#each conversations as conv}
            <button
              class="conv-row {conv.conversation_id === activeConvId ? 'is-active' : ''}"
              onclick={() => selectConversation(conv.conversation_id)}
            >
              <span class="conv-dot">{initialOf(displayName(conv))}</span>
              <span class="conv-meta">
                <span class="conv-name">{displayName(conv)}</span>
                <span class="conv-sub">{conv.platform === 'web' ? 'Web' : conv.platform}</span>
              </span>
              <span class="row-menu" onclick={(e) => rowMenu(e, conv)} role="button" tabindex="-1" title="操作" onkeydown={(e) => e.key === 'Enter' && rowMenu(e, conv)}>
                <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>
              </span>
            </button>
          {/each}
          {#if conversations.length === 0}
            <div class="conv-empty">按 + 新建，或从下方人设开始。</div>
          {/if}
        </div>

        <div class="panel-divider"></div>

        <div class="persona-panel">
          <span class="panel-title">人设</span>
          <div class="persona-row" role="listbox">
            {#each personas as p}
              <button class="persona-chip" title={p.name} onclick={() => startWithPersona(p.id)}>
                {#if p.avatar}
                  <img class="chip-avatar" src={p.avatar} alt={p.name} loading="lazy" />
                {:else}
                  <span class="chip-avatar chip-fallback">{initialOf(p.name)}</span>
                {/if}
                <span class="chip-name">{p.name}</span>
              </button>
            {/each}
          </div>
        </div>
      </aside>
    {/if}

    <section class="chat-stage">
      <!-- 消息列表 -->
      <div class="msgs" class:empty={!loadingHistory && messages.length === 0} bind:this={messagesEl}>
        {#if loadingHistory}
          <div class="center-hint">加载中…</div>
        {:else if messages.length === 0}
          <div class="welcome">
            <div class="welcome-mark" aria-hidden="true">
              <span class="brand-dot"></span>
            </div>
            <span class="welcome-kicker">{activeConv ? '继续对话' : '新的开始'}</span>
            <h2 class="welcome-title">{activeConv ? displayName(activeConv) : '聊天'}</h2>
            <p class="welcome-desc">
              {#if activeConv}
                和 {displayName(activeConv)} 打个招呼吧。可以发文字、图片或语音，也可以从左侧选择人设开启新对话。              {:else}
                选择一个会话，或者挑一个人设开始。所有对话都留在这台机器上。              {/if}
            </p>
            {#if personas.length > 0 && !activeConv}
              <div class="welcome-personas">
                {#each personas as p}
                  <button class="welcome-chip" onclick={() => startWithPersona(p.id)}>
                    {#if p.avatar}
                      <img class="chip-avatar" src={p.avatar} alt={p.name} />
                    {:else}
                      <span class="chip-avatar chip-fallback">{initialOf(p.name)}</span>
                    {/if}
                    <span class="chip-body">
                      <span class="chip-name">{p.name}</span>
                      <span class="chip-go">开始对话</span>
                    </span>
                  </button>
                {/each}
              </div>
            {/if}
          </div>
        {:else}
          {#each messages as m, i (i)}
            {@const isUser = m.role === 'user'}
            {@const isStreaming = m.streaming === true}
            {@const blocks = blocksOf(m)}
            {@const imgBlocks = blocks.filter((b) => b.type === 'image')}
            {@const restBlocks = blocks.filter((b) => b.type !== 'image')}
            {@const splitImage = isUser && imgBlocks.length > 0 && restBlocks.some((b) => b.type === 'text')}
            {#if splitImage}
              <!-- 图片单独成一条消息（微信式：先发图、再发字），不附属文字气泡 -->
              <div class="bubble-row self">
                <div class="bubble-col">
                  {#each imgBlocks as b}
                    <div class="image-bubble">
                      <button class="chat-image-btn" type="button" onclick={() => (previewImage = b.url)} aria-label="查看大图">
                        <img class="chat-image" src={b.url} alt="图片" loading="lazy" />
                      </button>
                    </div>
                  {/each}
                  <span class="bubble-time">{formatTime(m.timestamp)}</span>
                </div>
              </div>
            {/if}
            <div class="bubble-row {isUser ? 'self' : 'friend'}">
              {#if !isUser && !isStreaming}
                <span class="av">{initialOf(activePersona?.name ?? activeConv?.persona_name ?? 'AI')}</span>
              {/if}
              <div class="bubble-col">
                {#if !isUser && isStreaming && !m.reasoning && !m.content}
                  <!-- 还没吐思考内容时的占位：挂在消息列里（DeepSeek 那种位置），
                       而不是输入框上方 -->
                  <div class="thinking-hint"><span class="thinking-dot"></span>{phase?.label || '正在思考'}</div>
                {/if}
                {#if !isUser && m.reasoning}
                  <!-- 深度思考：显示在这条回复自己的气泡上方（类似 DeepSeek） -->
                  <details
                    class="reasoning"
                    open={m.thinkingOpen !== false}
                    ontoggle={(e) => {
                      const open = e.currentTarget.open;
                      messages = messages.map((mm, ii) => (ii === i ? { ...mm, thinkingOpen: open } : mm));
                    }}
                  >
                    <summary>{isStreaming && !m.content ? '正在思考…' : '深度思考'}</summary>
                    <div class="reasoning-body">{m.reasoning}</div>
                  </details>
                {/if}
                {#if m.platform === 'wechat'}
                  <span class="src-badge">via 微信</span>
                {/if}
                {#if m.configError && !isUser && !isStreaming}
                  <ConfigNotice
                    variant="card"
                    tone="warning"
                    icon="key"
                    title="模型配置待处理"
                    text={m.content}
                    actionLabel="去设置配置"
                    onAction={gotoModelSettings}
                  />
                {:else}
                  {#if !splitImage}
                    {#each imgBlocks as b}
                      <div class="image-bubble">
                        <button class="chat-image-btn" type="button" onclick={() => (previewImage = b.url)} aria-label="查看大图">
                          <img class="chat-image" src={b.url} alt="图片" loading="lazy" />
                        </button>
                      </div>
                    {/each}
                  {/if}
                  {#each restBlocks as b}
                    {#if b.type === 'emoji'}
                      <div class="sticker-bubble">
                        <img class="sticker-img" src={b.url || stickerUrl(b.pack, b.emotion, b.filename)} alt="贴纸" loading="lazy" />
                      </div>
                    {:else if b.type === 'voice'}
                      <!-- 微信风格语音条：点击播放，宽度随时长递增 -->
                      <button
                        type="button"
                        class="bubble {isUser ? 'bubble-user' : 'bubble-ai'} voice-bar"
                        class:playing={voicePlayingUrl === b.url}
                        style="width: {Math.min(220, 84 + Math.round(voiceDurations[b.url] || 1) * 6)}px"
                        onclick={() => toggleVoice(b.url)}
                        title="点击播放"
                      >
                        <svg class="voice-icon" viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true"><path d="M3 9v6h4l5 5V4L7 9H3z"/><path d="M16 8a5 5 0 0 1 0 8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
                        <span class="voice-dur">{voiceDurations[b.url] ? `${Math.round(voiceDurations[b.url])}″` : '语音'}</span>
                      </button>
                      <audio preload="metadata" src={b.url} hidden onloadedmetadata={(e) => (voiceDurations[b.url] = e.currentTarget.duration || 1)}></audio>
                    {:else if b.text}
                      <div class="bubble {isUser ? 'bubble-user' : 'bubble-ai'} {isStreaming ? 'is-streaming' : ''}">
                        <div class="bubble-text">{cleanLegacyImageText(b.text)}{#if isStreaming}<span class="caret"></span>{/if}</div>
                      </div>
                    {/if}
                  {/each}
                {/if}
                <span class="bubble-time">{formatTime(m.timestamp)}</span>
              </div>
            </div>
          {/each}
          {#if debouncing && pendingQueue.length}
            <!-- 去抖等待中：告知"还会合并"，避免用户以为卡住 -->
            <div class="thinking-hint debounce-hint">
              <span class="thinking-dot"></span>正在看…（{debounceSecs} 秒内继续发会自动合并{pendingQueue.length > 1 ? `，已攒 ${pendingQueue.length} 条` : ''}）
            </div>
          {/if}
        {/if}
        <div bind:this={bottomEl} class="scroll-anchor"></div>
      </div>

      <!-- 输入区 -->
      <div class="input-area">
        {#if modelReady !== true}
          <div class="config-banner">
            <ConfigNotice
              variant="banner"
              tone="warning"
              icon={modelReady === null ? 'alert' : 'key'}
              title={modelReady === null ? '正在检测模型配置…' : '尚未配置对话模型'}
              text={modelReady === null
                ? '正在确认对话模型是否就绪…'
                : '对话模型尚未配置或 API Key 无效，AI 无法回复。请先配置后再发送。'}
              actionLabel={modelReady === null ? '' : '去设置配置'}
              onAction={modelReady === null ? null : gotoModelSettings}
              checking={modelReady === null}
              foot={recheckButton}
            />
          </div>
        {/if}

        {#if showStickerPanel}
          <div class="panel sheet">
            <div class="sheet-head">
              <span>贴纸</span>
              <button class="icon-btn" onclick={() => (showStickerPanel = false)} aria-label="关闭">
                <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
              </button>
            </div>
            <div class="sticker-grid">
              {#each stickerGroups as g}
                {#each g.images as fname}
                  <button class="sticker-item" onclick={() => sendSticker(g, fname)} title={`${g.pack}/${g.emotion}`}>
                    <img src={stickerUrl(g.pack, g.emotion, fname)} alt={`${g.emotion}`} loading="lazy" />
                  </button>
                {/each}
              {/each}
              {#if stickerGroups.length === 0}
                <div class="center-hint">暂无贴纸</div>
              {/if}
            </div>
          </div>
        {/if}

        <div class="composer">
          <label class="act-btn" title="图片" class:busy={uploading}>
            <input type="file" accept="image/*" multiple hidden onchange={pickImageFile} />
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>
          </label>

          <button class="act-btn" title="贴纸" onclick={() => { showStickerPanel = !showStickerPanel; }}>
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-9-9"/><path d="M21 12h-6a3 3 0 0 0-3 3v6"/><circle cx="9" cy="10" r="0.5"/><circle cx="14" cy="8" r="0.5"/></svg>
          </button>

          <input
            class="text-input"
            bind:value={input}
            placeholder={sending
              ? (pendingQueue.length ? `回复中…已排队 ${pendingQueue.length} 条` : '回复中…继续输入会排队')
              : '输入消息…'}
            onkeydown={(e) => { if (e.key === 'Enter' && canSend) send(); }}
            disabled={uploading}
          />

          {#if sending && !canSend}
            <button class="send-btn disabled" disabled title="正在生成">
              <span class="thinking-dot"></span>
            </button>
          {:else}
            <button class="send-btn {canSend ? 'active' : ''}" onclick={() => { if (canSend) send(); }} disabled={!canSend}
              title={sending ? '发送（当前回复完成后一起送达）' : '发送'}>
              <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M3.4 20.4l17-8.4-17-8.4L8 12l-4.6 8.4z"/></svg>
            </button>
          {/if}
        </div>
      </div>
    </section>
  </div>

  {#if isMobile && listOpen}
    <div class="drawer-mask" role="button" tabindex="-1" aria-label="关闭会话列表" onclick={() => (listOpen = false)} onkeydown={(e) => e.key === 'Enter' && (listOpen = false)}></div>
    <aside class="drawer">
      <div class="panel-head">
        <span class="panel-title">会话</span>
        <button class="icon-btn" onclick={() => { startWithPersona(personas[0]?.id) }} title="新建会话" disabled={!personas.length}>
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
        </button>
      </div>
      <div class="conv-list">
        {#each conversations as conv}
          <button
            class="conv-row {conv.conversation_id === activeConvId ? 'is-active' : ''}"
            onclick={() => selectConversation(conv.conversation_id)}
          >
            <span class="conv-dot">{initialOf(displayName(conv))}</span>
            <span class="conv-meta">
              <span class="conv-name">{displayName(conv)}</span>
              <span class="conv-sub">{conv.platform === 'web' ? 'Web' : conv.platform}</span>
            </span>
            <span class="row-menu" onclick={(e) => rowMenu(e, conv)} role="button" tabindex="-1" onkeydown={(e) => e.key === 'Enter' && rowMenu(e, conv)}>
              <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>
            </span>
          </button>
        {/each}
        {#if conversations.length === 0}
          <div class="conv-empty">暂无会话</div>
        {/if}
      </div>
      <div class="panel-divider"></div>
      <span class="panel-title">人设</span>
      <div class="persona-row">
        {#each personas as p}
          <button class="persona-chip" title={p.name} onclick={() => startWithPersona(p.id)}>
            {#if p.avatar}
              <img class="chip-avatar" src={p.avatar} alt={p.name} loading="lazy" />
            {:else}
              <span class="chip-avatar chip-fallback">{initialOf(p.name)}</span>
            {/if}
            <span class="chip-name">{p.name}</span>
          </button>
        {/each}
      </div>
    </aside>
  {/if}

  {#if error}
    <div class="toast" role="alert">{error}<button class="icon-btn" onclick={() => (error = null)} aria-label="关闭"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg></button></div>
  {/if}

  {#if menuOpen}
    <div class="convs-menu" style="left:{menuOpen.x}px;top:{menuOpen.y}px" role="menu" aria-label="会话操作">
      <button class="convs-menu-item" type="button" role="menuitem" onclick={() => menuRename(menuOpen.conv)}>
        <span class="convs-menu-ico" aria-hidden="true">{@html `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>`}</span>
        重命名      </button>
      <button class="convs-menu-item danger" type="button" role="menuitem" onclick={() => menuDelete(menuOpen.conv)}>
        <span class="convs-menu-ico" aria-hidden="true">{@html `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>`}</span>
        删除会话
      </button>
    </div>
  {/if}

  {#if previewImage}
    <!-- 全屏图片预览（PawzoChat 式 openImagePreview）：点图查看大图，点任意处/按 Esc 关闭 -->
    <div
      class="img-preview-overlay"
      role="dialog"
      aria-label="图片预览"
      tabindex="-1"
      onclick={() => (previewImage = null)}
      onkeydown={(e) => {
        if (e.key === "Escape" || e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          previewImage = null;
        }
      }}
    >
      <img class="img-preview-full" src={previewImage} alt="图片预览" />
    </div>
  {/if}
</div>

<style>
  .chat-page {
    height: 100%;
    min-height: 0;
    display: flex;
    flex-direction: column;
    /* 透明: 内容面玻璃由 .main-area 承担, 这里再铺一层不透明 --surface
       会把它整块盖掉, 氛围层就永远透不上来。 */
    background: transparent;
    position: relative;
    overflow: hidden;
  }

  /* 沉浸模式: 消息与输入条居中限宽, 像在读一封信而不是在刷消息流 */
  .chat-page.immersive .msgs {
    padding-left: max(var(--space-4), calc((100% - var(--chat-msg-maxw)) / 2));
    padding-right: max(var(--space-4), calc((100% - var(--chat-msg-maxw)) / 2));
  }
  /* 沉浸模式下 .composer 自己已经有 max-width + margin:auto 居中,
     不能再叠一层 calc((100% - 680px)/2) 的左右 padding ——
     两层限宽相乘会把输入框压成一条 26px 的窄缝(实测 immersive 桌面端)。 */
  .chat-page.immersive .composer {
    padding-left: var(--space-4);
    padding-right: var(--space-4);
  }

  /* 移动端聊天页原本是「顶栏 + 48px 聊天头」两条同色白条纵向叠着, 合计 92px,
     读起来像把同一个页头印了两遍。改成二级上下文条:
     高度收到 44px、标题左对齐降到 13px/500 灰字、底边用更轻的 --border,
     与 TopBar(11px 品牌 + --border-strong)拉开一级, 层级才成立。 */
  .mobile-head {
    flex: none;
    display: flex;
    align-items: center;
    gap: var(--space-1);
    height: 44px;
    padding: 0 var(--space-2) 0 var(--space-1);
    background: var(--surface);
    border-bottom: 1px solid var(--border);
  }
  .head-title {
    flex: 1;
    min-width: 0;
    font-weight: 500;
    font-size: var(--text-13);
    letter-spacing: var(--tracking-tight);
    color: var(--text-2);
    text-align: left;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .icon-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border: none;
    border-radius: var(--radius-xs);
    background: transparent;
    color: var(--text-2);
    cursor: pointer;
    transition: background var(--transition), color var(--transition);
  }
  .icon-btn:hover:not(:disabled) {
    background: var(--row-hover);
    color: var(--text-1);
  }
  .icon-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .chat-body {
    flex: 1;
    min-height: 0;
    display: flex;
    position: relative;
  }

  /* ---- 会话侧栏 (桌面) ----
     原 240px 里只有 12px padding + 一个 11px 标题, 整个栏是空的。
     加宽到 260px 并给标题加计数, 让「会话」这一栏自己也有信息:
     标题行左边是 11px 微标签, 右边是等宽数字的条数, 中线以下才是列表。
     列表为空时给一个左对齐的引导块而不是一句“暂无会话”, 与其它页面统一。 */
  .conv-panel {
    flex: none;
    width: var(--conv-w);
    border-right: 1px solid var(--border);
    /* 会话栏是「浮在氛围层之上」的一列 chrome, 用玻璃而非纯色,
       两列才有同一张纸上的前后关系, 而不是被一条硬线拼起来的两块。 */
    background: var(--bg);
    display: flex;
    flex-direction: column;
    min-height: 0;
    padding: var(--space-3) var(--space-2);
    gap: var(--space-2);
  }
  @supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
    .conv-panel {
      background-color: var(--glass-1);
      background-image: var(--glass-sheen);
      -webkit-backdrop-filter: blur(var(--glass-blur-1)) saturate(var(--glass-sat-1));
      backdrop-filter: blur(var(--glass-blur-1)) saturate(var(--glass-sat-1));
      /* 与 main-area 之间那条边界: 玻璃压玻璃时, 单靠 border-right
         会显得是"两块纸拼起来"; 加一条内高光让会话栏读作浮在上层的那一块。 */
      box-shadow: var(--glass-highlight);
    }
  }
  @media (prefers-reduced-transparency: reduce) {
    .conv-panel {
      background: var(--bg);
      -webkit-backdrop-filter: none;
      backdrop-filter: none;
    }
  }
  .panel-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 var(--space-2) var(--space-2);
    margin-bottom: var(--space-1);
    border-bottom: 1px solid var(--border);
  }
  .panel-title {
    font-size: var(--text-2xs);
    font-weight: 500;
    letter-spacing: var(--tracking-wider);
    color: var(--text-3);
    text-transform: uppercase;
    flex: 1;
  }
  .panel-count {
    font-size: var(--text-2xs);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.02em;
    margin-right: var(--space-2);
  }
  .add-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-xs);
    background: var(--surface);
    color: var(--text-2);
    cursor: pointer;
    transition: background var(--transition), color var(--transition), border-color var(--transition);
  }
  .add-btn:hover {
    background: var(--row-hover);
    color: var(--text-1);
  }
  .add-btn:active {
    transform: scale(0.94);
  }

  .conv-list {
    display: flex;
    flex-direction: column;
    gap: var(--optical-2);
    overflow-y: auto;
    min-height: 0;
    flex: 1;
  }
  .conv-row {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    width: 100%;
    padding: var(--space-2);
    border: none;
    border-left: 2px solid transparent;
    border-radius: 0;
    background: transparent;
    color: var(--text-1);
    text-align: left;
    cursor: pointer;
    transition: background var(--transition), border-color var(--transition);
    position: relative;
  }
  .conv-row:hover {
    background: var(--row-hover);
  }
  .conv-row.is-active {
    background: var(--surface);
    border-left-color: var(--accent);
  }
  .conv-dot {
    flex: none;
    width: 30px;
    height: 30px;
    border-radius: var(--radius-xs);
    background: var(--surface-3);
    color: var(--text-2);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-weight: 500;
    font-size: var(--text-13);
  }
  .conv-row.is-active .conv-dot {
    background: var(--accent-wash);
    color: var(--accent);
  }
  .conv-meta {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: var(--hair);
  }
  .conv-name {
    font-weight: 500;
    font-size: var(--text-13);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .conv-sub {
    font-size: var(--text-2xs);
    color: var(--text-3);
    letter-spacing: var(--tracking-wide);
  }
  .row-menu {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: var(--radius-xs);
    color: var(--text-3);
    cursor: pointer;
    opacity: 0;
    transition: opacity var(--transition), background var(--transition);
  }
  .conv-row:hover .row-menu,
  .conv-row.is-active .row-menu {
    opacity: 1;
  }
  .row-menu:hover {
    background: var(--row-active);
    color: var(--text-1);
  }
  /* 会话行上下拉菜单 */
  .convs-menu {
    position: fixed;
    z-index: var(--z-popover);
    min-width: 150px;
    padding: var(--space-1);
    background: var(--surface);
    border: 1px solid var(--card-border);
    border-radius: var(--card-radius);
    box-shadow: var(--shadow-3);
    display: flex;
    flex-direction: column;
    animation: convs-pop .14s ease-out;
  }
  @media (prefers-reduced-motion: reduce) {
    .convs-menu { animation: none; }
  }
  @keyframes convs-pop {
    from { opacity: 0; transform: translateY(-4px) scale(.98); }
    to { opacity: 1; transform: none; }
  }
  .convs-menu-item {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border: none;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-1);
    font-size: var(--text-sm);
    text-align: left;
    cursor: pointer;
    transition: background var(--transition), color var(--transition);
  }
  .convs-menu-item:hover { background: var(--row-hover); }
  .convs-menu-item.danger { color: var(--error); }
  .convs-menu-item.danger:hover { background: color-mix(in srgb, var(--error) 12%, transparent); }
  .convs-menu-ico { display: inline-flex; }
  .conv-empty {
    padding: var(--space-3) var(--space-2);
    text-align: left;
    font-size: var(--text-2xs);
    line-height: 1.7;
    color: var(--text-3);
    border-left: 2px solid var(--border-strong);
    padding-left: var(--space-3);
  }
  .panel-divider {
    border-top: 1px solid var(--border);
    margin: var(--space-2) 0;
  }
  .persona-panel {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .persona-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .persona-chip,
  .welcome-chip {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-1) var(--space-2) var(--space-1) var(--space-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-xs);
    background: var(--surface);
    color: var(--text-1);
    font-size: var(--text-xs);
    cursor: pointer;
    transition: border-color var(--transition), background var(--transition), transform var(--transition);
  }
  /* 人设卡: 从「一个小 chip」变成「一行卡片」, 头像 22→28px,
     名字下方加一行 10px 的动作暗示。整块可点, 目标区域从 ~72x26 提到 ~160x46,
     空会话页从「没东西可点」变成「一眼看到两个入口」。 */
  .welcome-chip {
    width: 100%;
    padding: var(--space-2);
    gap: var(--space-3);
    border-color: var(--border-strong);
    text-align: left;
  }
  .welcome-chip .chip-avatar {
    width: 28px;
    height: 28px;
  }
  .chip-body {
    display: flex;
    flex-direction: column;
    gap: var(--hair);
    min-width: 0;
  }
  .welcome-chip .chip-name {
    font-size: var(--text-13);
    font-weight: 500;
    max-width: none;
  }
  .chip-go {
    font-size: var(--text-2xs);
    letter-spacing: var(--tracking-wide);
    color: var(--text-3);
    transition: color var(--transition);
  }
  .welcome-chip:hover .chip-go { color: var(--accent); }
  .persona-chip:hover,
  .welcome-chip:hover {
    border-color: var(--accent);
    background: var(--tint);
  }
  .persona-chip:active,
  .welcome-chip:active {
    transform: scale(0.96);
  }
  .chip-avatar {
    width: 22px;
    height: 22px;
    border-radius: var(--radius-xs);
    object-fit: cover;
    background: var(--surface-2);
  }
  .chip-fallback {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-weight: 600;
    color: var(--accent-strong);
    background: var(--accent-soft);
  }
  .chip-name {
    max-width: 90px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* ---- 聊天主区 ---- */
  .chat-stage {
    flex: 1;
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
    position: relative;
  }
  .msgs {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overflow-x: hidden;
    padding: var(--space-5) var(--space-4) var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    -webkit-overflow-scrolling: touch;
  }
  /* 空会话：欢迎区靠左上方起笔，而不是死居中。
     居中会让整块内容随视口宽度漂移，且上下留白各占一半，
     屏幕看起来「中间有个小岛，四周全是海」。改成 8vh 起笔后，
     标题、说明、人设卡从左上角读完是一段完整的信息，视线有落点。 */
  .msgs.empty {
    justify-content: flex-start;
    align-items: flex-start;
    padding-top: clamp(var(--space-6), 9vh, 96px);
    padding-left: var(--space-5);
    padding-right: var(--space-5);
  }
  .msgs.empty .scroll-anchor {
    display: none;
  }
  .scroll-anchor {
    height: 1px;
    flex: none;
  }
  .center-hint {
    text-align: center;
    padding: var(--space-6);
    color: var(--text-3);
    font-size: var(--text-sm);
  }

  /* 欢迎区 ----
     原来是一个 360px 宽、全部居中的小方块: 72px 灰底 + 30px 黑方 + 17px 标题,
     在 1000+px 宽的空白消息区里视觉权重约等于零, 整页看起来像没渲染完。
     改成左对齐的「开启区」:
     ① 一个 3px 冷蓝竖条作为页面锚点, 把视线固定在文字起点
     ② 标题上到 --text-display(28px), 与说明文字形成 2.2 倍的字号落差
     ③ 人设从「小 chip 一行」改成两列卡片网格, 每张卡带 22px 头像 + 名字 + 
        「开始对话 →」暗示, 空页面立刻有了可操作的内容块
     左对齐比居中更稳: 居中的空状态会随着视口宽度漂移, 左对齐的起点与
     会话栏对齐, 整块界面显得是一个整体而不是浮在中间的一张卡片。 */
  .welcome {
    margin: 0;
    width: 100%;
    max-width: 460px;
    align-self: flex-start;
    text-align: left;
    padding: var(--space-2) 0 var(--space-2) var(--space-5);
    border-left: 3px solid var(--accent);
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-3);
  }
  .welcome-mark {
    display: none;
  }
  .brand-dot {
    width: 26px;
    height: 26px;
    border-radius: var(--radius-xs);
    background: var(--text-1);
  }
  .welcome-kicker {
    font-size: var(--text-2xs);
    font-weight: 500;
    letter-spacing: var(--tracking-wider);
    color: var(--accent);
    text-transform: uppercase;
  }
  .welcome-title {
    margin: 0;
    font-size: var(--text-display);
    font-weight: 600;
    letter-spacing: var(--tracking-tight);
    line-height: 1.1;
    color: var(--text-1);
  }
  .welcome-desc {
    margin: 0;
    font-size: var(--text-15);
    color: var(--text-2);
    line-height: 1.72;
    max-width: 40ch;
  }
  .welcome-personas {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: var(--space-2);
    margin-top: var(--space-3);
    width: 100%;
  }

  /* 气泡 */
  /* 气泡列宽: 阅读行长已经由 --chat-msg-maxw(640px) 的居中列给出,
     这里再从 78% 收到 92% —— 否则输入列 640px 里气泡只有 499px,
     右侧总空出一指宽的缝, 看着像没对齐。 */
  .bubble-row {
    display: flex;
    align-items: flex-start;
    gap: var(--space-2);
    max-width: min(var(--chat-msg-maxw), 92%);
  }
  .bubble-row.self {
    align-self: flex-end;
    flex-direction: row-reverse;
  }
  .bubble-row.friend {
    align-self: flex-start;
  }
  .av {
    flex: none;
    width: 28px;
    height: 28px;
    border-radius: var(--radius-xs);
    background: var(--accent-wash);
    color: var(--accent);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-weight: 500;
    font-size: var(--text-2xs);
    letter-spacing: 0.02em;
  }
  .bubble-col {
    display: flex;
    flex-direction: column;
    gap: var(--optical-4);
    min-width: 0;
  }
  /* 气泡: 从「纯黑底/直角灰盒」改成「有留白节奏的对话块」。
     用户气泡改成冷蓝实底, 与发送键同一套色 —— 
     整页只有「我说的话 + 发送键」是蓝色, 一眼能分清谁在说。
     近黑留给真正的标题与主按钮, 不再被气泡消耗掉。 */
  .bubble {
    padding: var(--space-3) var(--space-4);
    border-radius: var(--bubble-radius-lg);
    line-height: 1.62;
    word-break: break-word;
    white-space: pre-wrap;
  }
  .bubble-user {
    background: var(--bubble-self-bg);
    color: var(--bubble-self-text);
    border-bottom-right-radius: var(--bubble-radius-sm);
  }
  .bubble-ai {
    background: var(--bubble-friend-bg);
    color: var(--bubble-friend-text);
    border: 1px solid var(--bubble-border);
    border-bottom-left-radius: var(--bubble-radius-sm);
  }
  .bubble-text {
    font-size: var(--text-15);
  }
  .caret {
    display: inline-block;
    width: 2px;
    height: 1em;
    margin-left: var(--optical-2);
    vertical-align: text-bottom;
    background: currentColor;
    opacity: 0.7;
    animation: caret-blink 1s steps(1) infinite;
  }
  @keyframes caret-blink {
    50% { opacity: 0; }
  }
  .bubble-time {
    font-size: var(--text-xs);
    color: var(--bubble-time);
    padding: 0 var(--optical-2);
  }
  .self .bubble-time {
    text-align: right;
  }
  .sticker-bubble {
    max-width: 150px;
  }
  .image-bubble {
    max-width: min(260px, 78%);
  }
  .chat-image-btn {
    display: block;
    padding: 0;
    border: none;
    background: none;
    cursor: zoom-in;
    border-radius: var(--radius-md);
  }
  .chat-image-btn:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
  .chat-image {
    display: block;
    width: auto;
    height: auto;
    max-width: 100%;
    max-height: 300px;
    border-radius: var(--radius-md);
    box-shadow: 0 1px 3px rgb(0 0 0 / 0.18);
  }
  .src-badge {
    font-size: var(--text-xs);
    color: var(--text-3);
    opacity: 0.75;
    margin: var(--optical-2) var(--optical-4);
    user-select: none;
  }
  /* 图片预览: 全屏黑底是刻意的 —— 看图时界面应该彻底退场,
     所以这里不用玻璃而用近实心黑, 也不加模糊(模糊会让图片本身变脏)。 */
  .img-preview-overlay {
    position: fixed;
    inset: 0;
    z-index: var(--z-lightbox);
    background: rgba(0, 0, 0, 0.86);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: zoom-out;
  }
  .img-preview-full {
    max-width: 92vw;
    max-height: 92vh;
    object-fit: contain;
    border-radius: var(--radius-sm);
  }
  .sticker-img {
    width: 100%;
    max-width: 150px;
    border-radius: var(--radius-sm);
  }
  /* 微信风格语音条 */
  .voice-bar {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    height: 40px;
    padding: 0 var(--optical-14);
    border: none;
    cursor: pointer;
    text-align: left;
  }
  .voice-bar .voice-icon {
    flex: none;
  }
  .voice-bar .voice-dur {
    font-size: var(--text-sm);
    white-space: nowrap;
  }
  .voice-bar.playing .voice-icon {
    animation: voice-pulse 0.8s ease-in-out infinite alternate;
  }
  @keyframes voice-pulse {
    from { transform: scale(1); opacity: 1; }
    to { transform: scale(1.25); opacity: 0.6; }
  }

  /* 深度思考：作为 assistant 气泡列的第一个子项，显示在该条回复上方 */
  .reasoning {
    width: 100%;
    max-width: 100%;
    box-sizing: border-box;
    font-size: var(--text-xs);
    color: var(--text-3);
    background: color-mix(in srgb, var(--surface-2) 60%, transparent);
    border: 1px solid var(--border);
    border-left: 2px solid var(--accent);
    border-radius: var(--radius-sm);
    padding: var(--space-2) var(--space-3);
    margin-bottom: var(--optical-2);
  }
  .reasoning summary {
    cursor: pointer;
    font-weight: 600;
    user-select: none;
    color: var(--text-2);
  }
  .reasoning-body {
    margin-top: var(--space-2);
    white-space: pre-wrap;
    line-height: var(--leading-normal);
    max-height: 260px;
    overflow-y: auto;
  }

  /* 输入区 */
  .input-area {
    flex: none;
    border-top: 1px solid var(--border);
    /* 玻璃而非 --surface: 输入区横跨整个内容区宽度, 若用不透明底,
       氛围层会在页面最下方被一条硬边切断 —— 底部渐变(藕紫)全部失效。
       用 glass-1 让它与侧栏同属一层 chrome, 同时透出下方氛围。 */
    background: var(--glass-1);
    position: relative;
    padding-bottom: env(safe-area-inset-bottom);
  }
  @supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
    .input-area {
      background-color: var(--glass-1);
      /* 输入区的光泽带方向要反过来: 它贴在页面底部, 受光面在上沿,
         所以用 0deg 让亮度集中在上边一条, 而不是 160deg 斜着散开。 */
      background-image: linear-gradient(
        0deg,
        rgba(255, 255, 255, 0) 60%,
        rgba(255, 255, 255, 0.14) 100%
      );
      -webkit-backdrop-filter: blur(var(--glass-blur-2)) saturate(var(--glass-sat-2));
      backdrop-filter: blur(var(--glass-blur-2)) saturate(var(--glass-sat-2));
      box-shadow: var(--glass-highlight);
    }
  }
  @media (prefers-reduced-transparency: reduce) {
    .input-area {
      background: var(--surface);
      -webkit-backdrop-filter: none;
      backdrop-filter: none;
    }
  }  /* 配置守卫 banner (模型未配置时显示在输入框上方) */
  .config-banner {
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--border);
    background: color-mix(in srgb, var(--warning-soft) 70%, transparent);
  }
  .config-recheck {
    flex: none;
    height: var(--btn-h-sm);
    padding: 0 var(--space-2);
    border: 1px solid var(--border-strong);
    border-radius: var(--btn-radius);
    background: transparent;
    color: var(--text-2);
    font-size: var(--text-xs);
    white-space: nowrap;
    cursor: pointer;
    transition: background var(--transition), color var(--transition), border-color var(--transition);
  }
  .config-recheck:hover:not(:disabled) {
    background: var(--tint);
    border-color: var(--accent);
    color: var(--text-1);
  }
  .config-recheck:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
  /* 未产出内容时的思考提示（位于消息列内，不在输入区上方） */
  .thinking-hint {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-1) 0;
    font-size: var(--text-xs);
    color: var(--text-3);
  }
  .thinking-dot {
    width: 8px;
    height: 8px;
    border-radius: var(--radius-xs);
    background: var(--accent);
    animation: boot-pulse 1.2s var(--ease-in-out) infinite;
  }
  .debounce-hint {
    align-self: flex-start;
    padding-left: var(--optical-2);
    color: var(--text-3);
  }
  @keyframes boot-pulse {
    0%, 100% { opacity: 0.3; transform: scale(0.8); }
    50% { opacity: 1; transform: scale(1.1); }
  }

  .panel.sheet {
    border-bottom: 1px solid var(--border);
    background: var(--surface-2);
    padding: var(--space-3);
    max-height: 240px;
    overflow-y: auto;
  }
  .sheet-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--space-2);
    font-weight: 600;
    font-size: var(--text-sm);
    color: var(--text-1);
  }
  .sticker-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(56px, 1fr));
    gap: var(--space-2);
  }
  .sticker-item {
    border: none;
    background: transparent;
    cursor: pointer;
    padding: 0;
    border-radius: var(--radius-sm);
    transition: transform var(--transition), background var(--transition);
  }
  .sticker-item:hover {
    transform: scale(1.08);
    background: var(--tint);
  }
  .sticker-item img {
    width: 100%;
    aspect-ratio: 1;
    object-fit: contain;
  }

  .composer {
    display: flex;
    align-items: flex-end;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-4) var(--space-4);
    /* 与消息列同宽(640px), 输入框右边缘和气泡右边缘对齐 —— 
       原来 +200px 的宽限让输入条比对话宽出一截, 视线落点对不上。 */
    max-width: var(--chat-msg-maxw);
    margin: 0 auto;
    width: 100%;
  }
  .act-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    flex: none;
    margin-bottom: var(--optical-4);
    border: none;
    border-radius: var(--radius-xs);
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
    transition: background var(--transition), color var(--transition);
  }
  .act-btn:hover {
    background: var(--row-hover);
    color: var(--text-1);
  }
  .act-btn.busy {
    opacity: 0.45;
    pointer-events: none;
  }
  /* 输入框: 34px 扁条 -> 40px 高度 + 微内阴影, 让输入区成一个「可写入的凹槽」,
     而不是页面上又一根 1px 细线的装饰。focus 时边框转冷蓝并带 2px 环,
     是整页最明确的「你现在在这里」提示。 */
  .text-input {
    flex: 1;
    min-width: 0;
    height: 40px;
    padding: 0 var(--space-3);
    border: 1px solid var(--input-border);
    border-radius: var(--input-radius);
    background: var(--surface-2);
    color: var(--input-text);
    font-size: var(--text-15);
    box-shadow: inset 0 1px 2px color-mix(in srgb, var(--text-1) 5%, transparent);
    transition: border-color var(--transition), box-shadow var(--transition), background var(--transition);
  }
  .text-input:hover {
    border-color: var(--border-strong);
  }
  .text-input:focus {
    outline: none;
    background: var(--surface);
    border-color: var(--input-focus-border);
    box-shadow: var(--focus-ring);
  }
  .text-input::placeholder {
    color: var(--input-placeholder);
  }
  /* 发送键: 可发送时用冷蓝实底, 而不是近黑。
     近黑是「破坏性/最高权重」的颜色, 用在发送这种高频动作上过重;
     冷蓝是全站唯一的功能色, 留给唯一的主动作, 页面才有色彩呼吸点。 */
  .send-btn {
    flex: none;
    width: 40px;
    height: 40px;
    border: none;
    border-radius: var(--radius-sm);
    background: var(--surface-2);
    color: var(--text-3);
    cursor: not-allowed;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: background var(--transition), color var(--transition), transform var(--transition), box-shadow var(--transition);
  }
  .send-btn.active {
    background: var(--accent);
    color: var(--on-accent);
    cursor: pointer;
    box-shadow: 0 1px 2px color-mix(in srgb, var(--accent) 30%, transparent);
  }
  .send-btn.active:hover {
    background: var(--accent-strong);
  }
  .send-btn.active:active {
    transform: scale(0.94);
  }
  .send-btn.disabled {
    background: var(--surface-2);
  }
  .thinking-dot {
    width: 10px;
    height: 10px;
    border-radius: var(--radius-xs);
    background: var(--accent);
    animation: caret-blink 1s steps(1) infinite;
  }

  /* 移动端抽屉 */
  .drawer-mask {
    position: absolute;
    inset: 0;
    background: var(--glass-0);
    z-index: var(--z-scrim);
  }
  @supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
    .drawer-mask {
      -webkit-backdrop-filter: blur(var(--glass-blur-0));
      backdrop-filter: blur(var(--glass-blur-0));
    }
  }
  .drawer {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    width: min(300px, 82%);
    z-index: var(--z-drawer);
    background: var(--surface);
    border-right: 1px solid var(--glass-border-2);
    padding: var(--space-3);
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    box-shadow: var(--shadow-3);
    animation: draw-in 220ms var(--ease-out);
  }
  @supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
    .drawer {
      background: var(--glass-2);
      -webkit-backdrop-filter: blur(var(--glass-blur-2)) saturate(var(--glass-sat-2));
      backdrop-filter: blur(var(--glass-blur-2)) saturate(var(--glass-sat-2));
      box-shadow: var(--glass-highlight), var(--shadow-3);
    }
  }
  @media (prefers-reduced-transparency: reduce) {
    .drawer {
      background: var(--surface);
      -webkit-backdrop-filter: none;
      backdrop-filter: none;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .drawer { animation: none; }
  }
  @keyframes draw-in {
    from { transform: translateX(-100%); }
    to { transform: translateX(0); }
  }

  /* toast */
  .toast {
    position: absolute;
    top: var(--space-3);
    left: 50%;
    transform: translateX(-50%);
    z-index: var(--z-toast);
    display: flex;
    align-items: center;
    gap: var(--space-2);
    max-width: 90%;
    padding: var(--space-2) var(--space-3);
    background: var(--toast-bg);
    color: var(--toast-text);
    border-radius: var(--toast-radius);
    box-shadow: var(--toast-shadow);
    font-size: var(--text-sm);
  }

  @media (max-width: 767px) {
    .bubble-row {
      max-width: 86%;
    }
    .msgs {
      padding: var(--space-3);
    }
  }
</style>
