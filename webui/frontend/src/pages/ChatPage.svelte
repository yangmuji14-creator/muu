<script>
  // 消息使用现有 content blocks 渲染，发送与历史同步继续走聊天 API。
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
  import { navigate, route } from '../lib/router.js';
  import { layout } from '../lib/layout.svelte.js';
  import { setActiveConversation, refreshState } from '../lib/session.svelte.js';
  import { confirmDialog, promptDialog } from '../lib/dialog.svelte.js';
  import { shell } from '../lib/shell.svelte.js';
  import Avatar from '../components/Avatar.svelte';
  import ConfigNotice from '../components/ConfigNotice.svelte';
  import { I } from '../components/settings/icons.js';

  const icebreakers = ['今天过得怎么样？', '给我讲个小故事吧', '聊聊最近的心情'];

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
  let showChatTools = $state(false);
  let conversationQuery = $state('');
  let uploading = $state(false);
  let attachmentPreview = $state(null);
  let imagePicker = $state(null);
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
  let inputEl = $state(null);

  // 输入框自适应高度: 单行起, 最多 6 行 (超过就滚动)。
  //   固定 40px 的 input 装不下稍长的消息, 用户看不到自己写了什么,
  //   这是「长文本可输入」这一条最直接的做法。
  const INPUT_MAX_H = 148;
  function autoGrow() {
    const el = inputEl;
    if (!el) return;
    el.style.height = 'auto';
    const next = Math.min(el.scrollHeight, INPUT_MAX_H);
    el.style.height = `${next}px`;
    el.style.overflowY = el.scrollHeight > INPUT_MAX_H ? 'auto' : 'hidden';
  }
  // Enter 发送 / Shift+Enter 换行; 输入法组合中的 Enter 不发送。
  function onInputKeydown(e) {
    if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return;
    e.preventDefault();
    if (canSend) send();
  }
  // 发送后清空输入并把高度收回单行
  $effect(() => {
    void input;
    if (input === '') queueMicrotask(autoGrow);
  });

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
  let personasById = $derived(new Map(personas.map((persona) => [persona.id, persona])));
  let activePersona = $derived(personasById.get(personaOfActive) ?? null);
  let companionName = $derived(activePersona?.name || activeConv?.persona_name || '慕');

  let visibleConversations = $derived.by(() => {
    const query = conversationQuery.trim().toLowerCase();
    return query ? conversations.filter((conv) =>
      [displayName(conv), conv.persona_name, channelName(conv.platform)]
        .some((label) => String(label ?? '').toLowerCase().includes(query)),
    ) : conversations;
  });

  // 每条消息的渲染视图：把 blocks/时间/是否合并/是否展示时间一次性算好。
  // 模板里若逐个 {@const} 现算，流式每个 token 都会重跑整列（每行 2 次
  // connectedMessages + formatTime + blocksOf + messageParts），长会话会卡。
  // 这里统一成一趟，并复用相邻行的 time 判断「是否显示时间戳」。
  let rowViews = $derived.by(() => {
    const rows = [];
    for (let i = 0; i < messages.length; i += 1) {
      const m = messages[i];
      const isUser = m.role === 'user';
      const blocks = blocksOf(m);
      const imgBlocks = blocks.filter((b) => b.type === 'image');
      // 文本块先清洗旧版图片元文本，再预先解析成 parts（代码围栏/引用），
      // 模板不再逐次重解析。
      const restBlocks = blocks
        .filter((b) => b.type !== 'image')
        .map((b) => {
          if (b.type !== 'text' || !b.text) return b;
          const text = String(cleanLegacyImageText(b.text));
          return { ...b, text, parts: messageParts(text) };
        });
      rows.push({
        message: m,
        isUser,
        isStreaming: m.streaming === true,
        joinedBefore: connectedMessages(messages[i - 1], m),
        joinedAfter: connectedMessages(m, messages[i + 1]),
        blocks,
        imgBlocks,
        restBlocks,
        // 已清洗的文本里若只剩 [图片] 占位，就不另起一条文字气泡。
        splitImage: isUser && imgBlocks.length > 0
          && restBlocks.some((b) => b.type === 'text' && b.text && b.text.trim() !== '[图片]'),
        time: formatTime(m.timestamp),
      });
    }
    // 时间戳只在「下一行不是同组」或「与下一行时间不同」时显示；
    // 复用已算好的 time，避免再 formatTime 一遍。
    for (let i = 0; i < rows.length; i += 1) {
      const next = rows[i + 1];
      rows[i].showTime = Boolean(rows[i].time)
        && (!rows[i].joinedAfter || rows[i].time !== next?.time);
    }
    return rows;
  });

  // 把当前会话同步到全局 session, 供内心面板 / 今天页 / 沉浸抽屉读取
  $effect(() => {
    setActiveConversation({
      id: activeConvId,
      personaId: personaOfActive || '',
      personaName: activePersona?.name || activeConv?.persona_name || '',
    });
  });

  // ---------- 生命周期 ----------
  // 聊天页自己的紧凑断点比外壳（768）高：三栏在 900 以下时，
  // 「导航 + 会话列 + 正文」会把正文压到 550 以下，读起来比手机还挤。
  // 所以 899 以下直接收成单列 + 抽屉，正文拿回整宽。
  $effect(() => {
    const mq = window.matchMedia('(max-width: 899px)');
    const apply = () => (isMobile = mq.matches);
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  });

  // 窄屏顶栏由外壳统一渲一条: 页面把「汉堡 + 当前会话名 + 重命名」登记过去,
  // 外壳的 TopBar 负责画。两条叠加的标题栏是这版之前最扎眼的毛病。
  //
  // 本页是常驻挂载的（切走只加 .page-hidden），所以必须看当前路由 ——
  // 否则在通讯录/设置页上，外壳顶栏还会挂着聊天的重命名铅笔。
  $effect(() => {
    const onChat = ($route.page ?? 'chat') === 'chat';
    if (!onChat || !isMobile || layout.mode === 'immersive') {
      shell.chatHead = null;
      return;
    }
    shell.chatHead = {
      title: activeConv ? displayName(activeConv) : '聊天',
      openList: () => (listOpen = true),
      canRename: Boolean(activeConvId),
      rename: () => {
        if (activeConvId) renameConversation(activeConv);
      },
    };
    return () => {
      shell.chatHead = null;
    };
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
    if (isMobile) listOpen = false;
    if (id === activeConvId && messages.length > 0) return;
    attachmentPreview = null;
    abortStream();
    activeConvId = id;
    phase = null;
    clearDebounce();
    pendingQueue = []; // 切换会话时丢弃未发出的排队消息，避免串到别的会话
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
    if (sendText(input.trim())) input = '';
  }

  function sendText(text) {
    if (!text || uploading) return false;
    // 主动守卫: 模型未配置时拦截发送，引导去配置
    if (modelReady !== true) {
      showError('请先配置对话模型，AI 才能回复');
      return false;
    }
    // 立即显示自己的消息，再进入去抖窗口。
    const msgRef = pushUserMessage(text);
    enqueue({ content: text, streamContent: text, msgRef });
    return true;
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
    return messages[messages.length - 1];
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

  function stopReply() {
    abortStream();
    const index = messages.findIndex((message) => message.streaming);
    if (index !== -1) {
      const partial = messages[index];
      messages = partial.content || partial.reasoning || partial.sticker
        ? messages.map((message, i) => i === index ? { ...message, streaming: false } : message)
        : messages.filter((_, i) => i !== index);
    }
    // 生成期间 enqueue() 不另起计时（sending 为真时直接入队），全靠正常结束
    // 的 finishStreaming() 去提交。手动停止走的是 abortStream() 而不是
    // finishStreaming()，如果不在这里补一次提交，用户在生成中排队的消息
    // 会一直停在队列里：气泡在屏幕上、却永远发不出去。
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
    const conversationId = activeConvId;
    ev.target.value = '';
    for (const file of files) {
      if (activeConvId !== conversationId || unmountAbort.signal.aborted) break;
      await sendImageFile(file);
    }
  }

  /** 图片立即上屏并上传（后端秒回）→ 加入去抖序列与文字同窗；
   *  窗口内发文字 → 服务端认领聚合成图+文一轮；纯图 → 服务器看门兜底。 */
  async function sendImageFile(file) {
    const conversationId = activeConvId;
    if (!conversationId) {
      showError('请先选择一个会话');
      return;
    }
    const url = URL.createObjectURL(file);
    uploading = true;
    attachmentPreview = { url, name: file.name };
    // 图片气泡先上屏（本地预览），上传完成后换成服务端 URL
    const localMsg = pushUserMessage('[图片]', null, { image: url });
    try {
      const data = await uploadImage(file, {
        conversation_id: conversationId,
      });
      if (activeConvId !== conversationId || unmountAbort.signal.aborted) return;
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
      if (activeConvId === conversationId && !unmountAbort.signal.aborted) showError(e.message);
    } finally {
      uploading = false;
      attachmentPreview = null;
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
  function channelName(platform) {
    if (platform === 'web') return 'Web';
    if (platform === 'wechat') return '微信';
    return platform || '';
  }

  function connectedMessages(first, second) {
    if (!first || !second || first.role !== second.role) return false;
    return Math.abs(Date.parse(second.timestamp) - Date.parse(first.timestamp)) < 5 * 60 * 1000;
  }

  // 只解析消息里的纯文本围栏与引用，由 Svelte 转义所有内容。
  function messageParts(content) {
    const parts = [];
    let kind = 'text';
    let lines = [];
    let fence = '';
    let language = '';

    function flush() {
      const text = lines.join('\n');
      if (kind === 'code' || text.trim()) parts.push({ kind, text, language });
      lines = [];
    }

    for (const line of content.replace(/\r\n?/g, '\n').split('\n')) {
      if (kind === 'code') {
        const closing = line.trim();
        if (closing.startsWith(fence) && closing.split('').every((char) => char === fence[0])) {
          flush();
          kind = 'text';
          language = '';
        } else lines.push(line);
        continue;
      }

      const opening = /^ {0,3}(`{3,}|~{3,})[ \t]*([\w#+.-]{0,32})[ \t]*$/.exec(line);
      if (opening) {
        flush();
        kind = 'code';
        [, fence, language] = opening;
        continue;
      }

      const quote = /^ {0,3}>[ \t]?(.*)$/.exec(line);
      const nextKind = quote ? 'quote' : 'text';
      if (nextKind !== kind) flush();
      kind = nextKind;
      lines.push(quote ? quote[1] : line);
    }
    flush();
    return parts;
  }

  async function copyCode(text) {
    const copied = await navigator.clipboard?.writeText(text).then(() => true, () => false);
    if (copied || copySelection(text)) showToast('已复制代码');
    else showError('复制失败，请选中代码后手动复制');
  }

  function copySelection(text) {
    const selection = document.createElement('textarea');
    const previous = document.activeElement;
    selection.value = text;
    selection.style.position = 'fixed';
    selection.style.opacity = '0';
    document.body.append(selection);
    try {
      selection.select();
      return document.execCommand('copy');
    } catch {
      return false;
    } finally {
      selection.remove();
      previous?.focus();
    }
  }

  function focusInside(node, selector) {
    node.querySelector(selector)?.focus();
  }

  function showImagePreview(node) {
    node.showModal();
    focusInside(node, '.img-preview-close');
  }

  function closeImagePreview(event) {
    event?.preventDefault();
    previewImage = null;
  }

  function handleEscape(event) {
    if (event.key !== 'Escape' || event.defaultPrevented || document.querySelector('dialog[open]')) return;
    if (menuOpen) {
      menuOpen.trigger.focus();
      closeMenu();
    } else if (showStickerPanel || showChatTools) {
      showStickerPanel = false;
      showChatTools = false;
    } else if (listOpen) listOpen = false;
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
  let menuOpen = $state(null); // { conv, x, y, trigger }

  function rowMenu(e, conv) {
    stopEvent(e);
    // 用按钮位置定位菜单，避免溢出边界
    const rect = e.currentTarget.getBoundingClientRect();
    if (menuOpen?.conv.conversation_id === conv.conversation_id) {
      closeMenu();
      return;
    }
    menuOpen = { conv, x: rect.right, y: rect.bottom + 4, trigger: e.currentTarget };
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

  // 首次进入: 自动选中第一个会话(如有)
  $effect(() => {
    if (!loadingHistory && activeConvId === null && conversations.length > 0 && messages.length === 0) {
      selectConversation(conversations[0].conversation_id);
    }
  });
</script>

<svelte:window onkeydown={handleEscape} />

<div class="chat-page" class:immersive={layout.mode === 'immersive'}>
  {#snippet icon(path, size = 18)}
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      {@html path}
    </svg>
  {/snippet}

  {#snippet dots()}
    <span class="thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span>
  {/snippet}

  {#snippet imageBlock(url)}
    <button class="chat-image-btn" type="button" onclick={() => (previewImage = url)} aria-label="查看大图">
      <img class="chat-image" src={url} alt="图片" loading="lazy" />
    </button>
  {/snippet}

  {#snippet conversationPanel(inDrawer)}
    <div class="panel-head">
      <h2 class="panel-title">会话</h2>
      <span class="panel-count" aria-label={'共 ' + conversations.length + ' 个会话'}>{conversations.length}</span>
      <button
        class="icon-btn add-btn"
        type="button"
        title="新建会话"
        aria-label="新建会话"
        onclick={inDrawer ? () => startWithPersona(personas[0]?.id) : newEmptyConversation}
        disabled={inDrawer && !personas.length}
      >{@render icon(I.plus)}</button>
      {#if inDrawer}
        <button class="icon-btn drawer-close" type="button" aria-label="关闭会话列表" onclick={() => (listOpen = false)}>
          {@render icon(I.close)}
        </button>
      {/if}
    </div>

    <label class="conv-search">
      {@render icon(I.search, 15)}
      <input type="search" aria-label="搜索会话" placeholder="搜索会话" bind:value={conversationQuery} />
    </label>

    <div class="conv-list">
      {#each visibleConversations as conv (conv.conversation_id)}
        {@const convName = displayName(conv)}
        {@const selected = conv.conversation_id === activeConvId}
        {@const unread = Math.floor(Number(conv.unread_count))}
        <div class="conv-entry" class:is-active={selected}>
          <button
            class="conv-row"
            type="button"
            aria-current={selected ? 'true' : undefined}
            onclick={() => selectConversation(conv.conversation_id)}
          >
            <Avatar name={convName} src={personasById.get(conv.persona_id)?.avatar || ''} size={36} />
            <span class="conv-meta">
              <span class="conv-name">{convName}</span>
              {#if conv.platform}<span class="conv-sub">{channelName(conv.platform)}</span>{/if}
            </span>
            {#if Number.isFinite(unread) && unread > 0}
              <span class="unread-badge" title={unread + ' 条未读'}>{unread > 99 ? '99+' : unread}</span>
            {/if}
          </button>
          <button
            class="icon-btn row-menu"
            type="button"
            title="会话操作"
            aria-label={convName + '的会话操作'}
            aria-expanded={menuOpen?.conv.conversation_id === conv.conversation_id}
            onclick={(event) => rowMenu(event, conv)}
          >
            {@render icon('<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>')}
          </button>
        </div>
      {:else}
        <p class="conv-empty">{conversationQuery.trim() ? '没有找到匹配的会话。' : '新建会话，或从下方选择人设。'}</p>
      {/each}
    </div>

    {#if personas.length}
      <div class="persona-panel">
        <span class="micro-label">人设</span>
        <div class="persona-row">
          {#each personas as p (p.id)}
            <button class="persona-chip" type="button" title={p.name} onclick={() => startWithPersona(p.id)}>
              <Avatar name={p.name} src={p.avatar || ''} size={22} />
              <span>{p.name}</span>
            </button>
          {/each}
        </div>
      </div>
    {/if}
  {/snippet}

  {#snippet recheckButton()}
    <button class="config-recheck" type="button" onclick={checkModelHealth} disabled={modelChecking}>
      {modelChecking ? '检测中…' : '重新检测'}
    </button>
  {/snippet}

  <div class="chat-body">
    {#if !isMobile && layout.mode !== 'immersive'}
      <aside class="conv-panel glass-1" aria-label="会话列表">
        {@render conversationPanel(false)}
      </aside>
    {/if}

    <section class="chat-stage glass-2" aria-label="聊天对话">
      {#if layout.mode !== 'immersive'}
        <header class="chat-heading">
          {#if isMobile}
            <button class="icon-btn" type="button" aria-label="会话列表" title="会话列表" onclick={() => (listOpen = true)}>
              {@render icon('<path d="M4 6h16M4 12h16M4 18h16"/>')}
            </button>
          {/if}
          <Avatar name={companionName} src={activePersona?.avatar || ''} size={38} />
          <div class="heading-text">
            <h1>{activeConv ? displayName(activeConv) : '聊天'}</h1>
            {#if activeConv?.platform}<span>{channelName(activeConv.platform)}</span>{/if}
          </div>
          {#if isMobile && activeConv}
            <button class="icon-btn" type="button" aria-label="重命名会话" title="重命名会话" onclick={() => renameConversation(activeConv)}>
              {@render icon('<path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>', 16)}
            </button>
          {/if}
        </header>
      {/if}

      <div class="msgs" class:empty={!loadingHistory && messages.length === 0} bind:this={messagesEl}>
        {#if loadingHistory}
          <div class="center-hint" role="status">{@render dots()}加载会话中…</div>
        {:else if messages.length === 0}
          <div class="welcome">
            <div class="welcome-avatar">
              <Avatar name={companionName} src={activePersona?.avatar || ''} size={84} />
            </div>
            <div class="welcome-heading">
              <h2>{activeConv ? companionName : '和慕聊聊'}</h2>
              {#if activeConv}<p>{activePersona?.description || '从一句问候开始'}</p>{/if}
            </div>
            {#if activeConv}
              <p class="welcome-note">今天有什么想说的？一件小事也可以。</p>
              {#if modelReady === true}
                <div class="prompt-chips" role="group" aria-label="破冰话题">
                  {#each icebreakers as prompt}
                    <button class="prompt-chip" type="button" disabled={uploading} onclick={() => sendText(prompt)}>
                      {prompt}{@render icon('<path d="M7 17 17 7M7 7h10v10"/>', 14)}
                    </button>
                  {/each}
                </div>
              {/if}
            {:else if personas.length}
              <p class="welcome-note">选一位伴侣，开始新的对话。</p>
              <div class="prompt-chips">
                {#each personas as p (p.id)}
                  <button class="prompt-chip" type="button" onclick={() => startWithPersona(p.id)}>
                    <Avatar name={p.name} src={p.avatar || ''} size={24} />
                    {p.name}
                  </button>
                {/each}
              </div>
            {:else}
              <p class="welcome-note">在通讯录创建一位伴侣，就能开始聊天。</p>
              <button class="prompt-chip" type="button" onclick={() => navigate('contacts')}>打开通讯录</button>
            {/if}
          </div>
        {:else}
          {#each rowViews as row, i (i)}
            {@const m = row.message}
            {@const isUser = row.isUser}
            {@const isStreaming = row.isStreaming}
            {@const joinedBefore = row.joinedBefore}
            {@const joinedAfter = row.joinedAfter}
            {@const blocks = row.blocks}
            {@const imgBlocks = row.imgBlocks}
            {@const restBlocks = row.restBlocks}
            {@const splitImage = row.splitImage}
            {@const time = row.time}
            {@const showTime = row.showTime}

            {#if splitImage}
              <div class="msg-row self" class:joins-before={joinedBefore}>
                <div class="bubble-col">
                  {#each imgBlocks as b}
                    {@render imageBlock(b.url)}
                  {/each}
                </div>
              </div>
            {/if}

            <div
              class="msg-row {isUser ? 'self' : 'friend'}"
              class:joins-before={joinedBefore || splitImage}
              class:joins-after={joinedAfter}
            >
              {#if !isUser}
                <span class="av" class:joined-avatar={joinedBefore} aria-hidden="true">
                  <Avatar name={companionName} src={activePersona?.avatar || ''} size={32} />
                </span>
              {/if}
              <div class="bubble-col">
                {#if !isUser && isStreaming && !m.reasoning && !m.content}
                  <div class="thinking-hint" role="status">{@render dots()}{phase?.label || '正在思考'}</div>
                {/if}
                {#if !isUser && m.reasoning}
                  <details
                    class="reasoning"
                    open={m.thinkingOpen !== false}
                    ontoggle={(event) => {
                      const open = event.currentTarget.open;
                      messages = messages.map((message, index) => (index === i ? { ...message, thinkingOpen: open } : message));
                    }}
                  >
                    <summary>
                      {isStreaming && !m.content ? '正在思考' : '深度思考'}
                      {#if isStreaming && !m.content}{@render dots()}{/if}
                    </summary>
                    <div class="reasoning-body">{m.reasoning}</div>
                  </details>
                {/if}

                {#if m.platform === 'wechat'}<span class="src-badge">微信</span>{/if}
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
                      {@render imageBlock(b.url)}
                    {/each}
                  {/if}
                  {#each restBlocks as b}
                    {#if b.type === 'emoji'}
                      <img class="sticker-img" src={b.url || stickerUrl(b.pack, b.emotion, b.filename)} alt="贴纸" loading="lazy" />
                    {:else if b.type === 'voice'}
                      <button
                        type="button"
                        class="bubble {isUser ? 'bubble-user' : 'bubble-ai'} voice-bar"
                        class:playing={voicePlayingUrl === b.url}
                        style:width={Math.min(220, 84 + Math.round(voiceDurations[b.url] || 1) * 6) + 'px'}
                        onclick={() => toggleVoice(b.url)}
                        aria-label={voicePlayingUrl === b.url ? '暂停语音' : '播放语音'}
                        aria-pressed={voicePlayingUrl === b.url}
                      >
                        <span class="voice-icon">{@render icon(I.voice, 16)}</span>
                        <span>{voiceDurations[b.url] ? Math.round(voiceDurations[b.url]) + '″' : '语音'}</span>
                      </button>
                      <audio preload="metadata" src={b.url} hidden onloadedmetadata={(event) => (voiceDurations[b.url] = event.currentTarget.duration || 1)}></audio>
                    {:else if b.text}
                      {@const text = b.text}
                      {#if !imgBlocks.length || text.trim() !== '[图片]'}
                        {@const parts = b.parts || []}
                        <div class="bubble {isUser ? 'bubble-user' : 'bubble-ai'}" class:is-streaming={isStreaming}>
                          {#each parts as part}
                            {#if part.kind === 'code'}
                              <div class="message-code">
                                <div class="code-head">
                                  <span>{part.language || '代码'}</span>
                                  <button type="button" class="code-copy" onclick={() => copyCode(part.text)} aria-label="复制代码">复制</button>
                                </div>
                                <pre><code>{part.text}</code></pre>
                              </div>
                            {:else if part.kind === 'quote'}
                              <blockquote>{part.text}</blockquote>
                            {:else}
                              <div class="bubble-text">{part.text}</div>
                            {/if}
                          {/each}
                          {#if isStreaming}<span class="streaming-indicator">{@render dots()}</span>{/if}
                        </div>
                      {/if}
                    {/if}
                  {/each}
                {/if}
                {#if showTime}
                  <time class="bubble-time">{time}</time>
                {/if}
              </div>
            </div>
          {/each}
          {#if debouncing && pendingQueue.length}
            <div class="thinking-hint debounce-hint">
              {@render dots()}
              <span>正在看，{debounceSecs} 秒内继续发送会合并{pendingQueue.length > 1 ? '，已排队 ' + pendingQueue.length + ' 条' : ''}。</span>
            </div>
          {/if}
        {/if}
        <div bind:this={bottomEl} class="scroll-anchor"></div>
      </div>

      <div class="input-area">
        {#if modelReady !== true}
          <div class="config-banner">
            <ConfigNotice
              variant="banner"
              tone="warning"
              icon={modelReady === null ? 'alert' : 'key'}
              title={modelReady === null ? '正在检测模型配置…' : '尚未配置对话模型'}
              text={modelReady === null
                ? ''
                : '配置对话模型后即可发送消息。'}
              actionLabel={modelReady === null ? '' : '去设置配置'}
              onAction={modelReady === null ? null : gotoModelSettings}
              checking={modelReady === null}
              foot={recheckButton}
            />
          </div>
        {/if}

        <div class="composer glass-3">
          {#if attachmentPreview}
            <div class="attachment">
              <div class="attachment-thumb">
                <img src={attachmentPreview.url} alt="" />
                <button type="button" class="attachment-close" aria-label="关闭上传预览" title="关闭预览" onclick={() => (attachmentPreview = null)}>
                  {@render icon(I.close, 12)}
                </button>
              </div>
              <div class="attachment-info">
                <strong>{attachmentPreview.name}</strong>
                <span role="status">正在上传…</span>
              </div>
            </div>
          {:else if uploading}
            <!-- 用户点 × 关掉了预览、但上传还在进行：仍要显示进度，
                 否则输入框一直禁用、屏幕上却没有任何「正在上传」的提示。 -->
            <div class="attachment attachment-uploading" role="status">
              <span class="attachment-spinner" aria-hidden="true"></span>
              <span>正在上传…</span>
            </div>
          {/if}
          <textarea
            class="text-input"
            bind:this={inputEl}
            bind:value={input}
            rows="1"
            aria-label="输入消息"
            placeholder={sending
              ? (pendingQueue.length ? '回复中…已排队 ' + pendingQueue.length + ' 条' : '回复中…继续输入会排队')
              : '想聊点什么？'}
            oninput={autoGrow}
            onkeydown={onInputKeydown}
            disabled={uploading}
          ></textarea>

          <div class="composer-actions">
            <div class="composer-tools">
              <input type="file" accept="image/*" multiple hidden bind:this={imagePicker} onchange={pickImageFile} />
              <button type="button" class="icon-btn act-btn" aria-label="发送图片" title="发送图片" disabled={uploading} onclick={() => imagePicker?.click()}>
                {@render icon('<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/>')}
              </button>
              <button
                type="button"
                class="icon-btn act-btn"
                aria-label="贴纸"
                title="贴纸"
                aria-expanded={showStickerPanel}
                onclick={() => { showStickerPanel = !showStickerPanel; showChatTools = false; }}
              >
                {@render icon('<path d="M21 12a9 9 0 1 1-9-9"/><path d="M21 12h-6a3 3 0 0 0-3 3v6"/><circle cx="9" cy="10" r=".5"/><circle cx="14" cy="8" r=".5"/>')}
              </button>
              <button
                type="button"
                class="icon-btn act-btn"
                aria-label="聊天设置"
                title="聊天设置"
                aria-expanded={showChatTools}
                onclick={() => { showChatTools = !showChatTools; showStickerPanel = false; }}
              >
                {@render icon('<path d="M4 7h4m4 0h8M4 17h8m4 0h4"/><circle cx="10" cy="7" r="2"/><circle cx="14" cy="17" r="2"/>')}
              </button>
            </div>

            {#if sending}
              <button class="send-btn stop" type="button" onclick={stopReply} title="停止生成" aria-label="停止生成">
                <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="3"/></svg>
              </button>
            {:else}
              <button class="send-btn" type="button" onclick={() => { if (canSend) send(); }} disabled={!canSend} title="发送" aria-label="发送">
                {@render icon('<path d="M12 19V5m-6 6 6-6 6 6"/>', 20)}
              </button>
            {/if}
          </div>
        </div>

        {#if showStickerPanel}
          <section class="sticker-panel glass-3" aria-label="贴纸" use:focusInside={'.sticker-item, .sticker-close'}>
            <div class="panel-head">
              <h2 class="panel-title">贴纸</h2>
              <button class="icon-btn sticker-close" type="button" onclick={() => (showStickerPanel = false)} aria-label="关闭贴纸">
                {@render icon(I.close)}
              </button>
            </div>
            <div class="sticker-grid">
              {#each stickerGroups as group}
                {#each group.images as filename}
                  <button class="sticker-item" type="button" onclick={() => sendSticker(group, filename)} title={group.pack + ' / ' + group.emotion}>
                    <img src={stickerUrl(group.pack, group.emotion, filename)} alt={group.emotion} loading="lazy" />
                  </button>
                {/each}
              {:else}
                <p class="center-hint">暂无贴纸</p>
              {/each}
            </div>
          </section>
        {/if}

        {#if showChatTools}
          <div class="chat-tools glass-3" role="group" aria-label="聊天设置快捷入口" use:focusInside={'.popover-action'}>
            <button class="popover-action" type="button" onclick={() => { showChatTools = false; gotoModelSettings(); }}>模型设置</button>
            <button class="popover-action" type="button" onclick={() => { showChatTools = false; navigate('settings/conversation'); }}>对话参数</button>
            <button class="popover-action" type="button" onclick={() => { showChatTools = false; navigate('settings/voice'); }}>
              {@render icon(I.voice, 16)}语音设置
            </button>
          </div>
        {/if}
      </div>
    </section>
  </div>

  {#if isMobile && listOpen}
    <button class="drawer-mask scrim-layer" type="button" tabindex="-1" aria-label="关闭会话列表遮罩" onclick={() => (listOpen = false)}></button>
    <aside class="drawer glass-3" aria-label="会话列表" use:focusInside={'.drawer-close'}>
      {@render conversationPanel(true)}
    </aside>
  {/if}

  {#if error}
    <div class="chat-toast glass-3" role="status">
      <span>{error}</span>
      <button class="icon-btn" type="button" onclick={() => (error = null)} aria-label="关闭提示">
        {@render icon(I.close, 16)}
      </button>
    </div>
  {/if}

  {#if menuOpen}
    <div
      class="convs-menu glass-3"
      style:--menu-right={menuOpen.x + 'px'}
      style:--menu-top={menuOpen.y + 'px'}
      role="group"
      aria-label="会话操作"
      use:focusInside={'.popover-action'}
    >
      <button class="popover-action" type="button" onclick={() => menuRename(menuOpen.conv)}>重命名</button>
      <button class="popover-action danger" type="button" onclick={() => menuDelete(menuOpen.conv)}>删除会话</button>
    </div>
  {/if}

  {#if previewImage}
    <dialog class="img-preview-overlay" aria-label="图片预览" use:showImagePreview oncancel={closeImagePreview}>
      <button class="img-preview-hit" type="button" aria-label="关闭图片预览" onclick={closeImagePreview}>
        <img class="img-preview-full" src={previewImage} alt="图片预览" />
      </button>
      <button class="icon-btn img-preview-close glass-3" type="button" aria-label="关闭图片预览" onclick={closeImagePreview}>
        {@render icon(I.close)}
      </button>
    </dialog>
  {/if}
</div>

<style>
  .chat-page {
    --self-fill: var(--bubble-self-bg);
    --self-ink: #fff;
    --code-fill: #161921;
    --code-ink: #eef0f6;
    position: relative;
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    overflow: hidden;
  }

  :global([data-theme='dark']) .chat-page {
    --self-fill: linear-gradient(150deg,
      color-mix(in srgb, var(--accent) 55%, var(--bg)),
      color-mix(in srgb, var(--accent-hover) 42%, var(--bg)));
  }

  .chat-body {
    display: flex;
    flex: 1;
    gap: var(--optical-10);
    min-height: 0;
  }

  .conv-panel,
  .drawer {
    display: flex;
    flex: none;
    flex-direction: column;
    gap: var(--space-3);
    min-height: 0;
    padding: var(--space-3);
    border-radius: var(--radius-lg);
  }

  .conv-panel { width: var(--conv-w); }

  .panel-head,
  .chat-heading,
  .composer-actions,
  .composer-tools {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  .panel-head { flex: none; }
  .panel-title {
    flex: 1;
    margin: 0;
    color: var(--text-1);
    font-size: var(--text-base);
    font-weight: 690;
    line-height: var(--leading-tight);
  }

  .panel-count,
  .unread-badge,
  .src-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 20px;
    padding: 0 var(--optical-6);
    border-radius: var(--radius-pill);
    font-size: var(--text-2xs);
    font-variant-numeric: tabular-nums;
  }

  .panel-count { background: var(--field-fill); color: var(--text-2); }
  .unread-badge { background: var(--accent); color: var(--on-accent); }
  .src-badge { background: var(--field-fill); color: var(--text-2); }

  .icon-btn {
    display: inline-grid;
    flex: none;
    place-items: center;
    width: 36px;
    height: 36px;
    padding: 0;
    border: 0;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-2);
    cursor: pointer;
  }

  .icon-btn:hover:enabled,
  .icon-btn[aria-expanded='true'] {
    background: var(--row-hover);
    color: var(--accent);
  }

  .icon-btn:disabled { opacity: 0.48; cursor: default; }
  .add-btn { background: var(--accent-soft); color: var(--accent); }
  .add-btn:hover:enabled { background: var(--accent-glow); }

  .conv-search {
    display: flex;
    flex: none;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
    min-height: 38px;
    padding: 0 var(--space-3);
    border-radius: var(--radius-pill);
    background: var(--field-fill);
    color: var(--text-2);
  }

  .conv-search:focus-within {
    background: var(--field-fill-focus);
    box-shadow: var(--focus-ring);
  }

  .conv-search input {
    width: 100%;
    min-width: 0;
    padding: 0;
    border: 0;
    border-radius: inherit;
    background: transparent;
    color: var(--text-1);
    font: inherit;
    font-size: var(--text-13);
  }

  .conv-search input:focus-visible { outline: 0; box-shadow: none; }
  .conv-search input::placeholder { color: var(--text-2); }

  .conv-list {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: var(--space-2);
    min-height: 0;
    margin: -3px;
    padding: 3px;
    overflow-y: auto;
    overscroll-behavior: contain;
    scrollbar-width: thin;
  }

  .conv-entry {
    position: relative;
    display: flex;
    flex: none;
    align-items: center;
    min-width: 0;
    padding-inline-end: var(--space-1);
    border-radius: var(--radius-md);
    transition: background-color var(--transition), box-shadow var(--transition),
      transform var(--transition-spring);
  }

  .conv-entry:hover { background: var(--row-hover); transform: translateY(-1px); }
  .conv-entry.is-active { background: var(--accent-soft); }
  .conv-entry.is-active::before {
    position: absolute;
    inset-block: 28%;
    inset-inline-start: 3px;
    width: 3px;
    border-radius: var(--radius-pill);
    background: var(--accent);
    content: '';
    pointer-events: none;
  }

  .conv-row {
    display: flex;
    flex: 1;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
    min-height: 54px;
    padding: var(--space-2) var(--space-1) var(--space-2) var(--space-2);
    border: 0;
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--text-1);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }

  .conv-meta {
    display: grid;
    flex: 1;
    min-width: 0;
    line-height: var(--leading-snug);
  }

  .conv-name,
  .conv-sub,
  .persona-chip span:last-child,
  .heading-text h1 {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .conv-name { font-size: var(--text-13); font-weight: 650; }
  .conv-sub { color: var(--text-2); font-size: var(--text-2xs); }
  .row-menu { width: 34px; }
  .conv-empty { margin: 0; padding: var(--space-2); color: var(--text-2); font-size: var(--text-xs); }

  .persona-panel {
    display: grid;
    flex: none;
    gap: var(--space-2);
  }

  .persona-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    max-height: min(120px, 23dvh);
    overflow-y: auto;
    padding: 3px;
    margin: -3px;
    scrollbar-width: thin;
  }

  .persona-chip,
  .prompt-chip {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    min-width: 0;
    padding: var(--space-1) var(--space-2);
    border: 0;
    border-radius: var(--radius-pill);
    background: var(--field-fill);
    color: var(--text-1);
    font: inherit;
    font-size: var(--text-xs);
    font-weight: 600;
    cursor: pointer;
  }

  .persona-chip { max-width: 100%; padding-inline-start: var(--space-1); }
  .persona-chip:hover,
  .prompt-chip:hover:enabled { background: var(--accent-soft); color: var(--accent); }
  .prompt-chip:disabled { opacity: 0.55; cursor: default; }

  .chat-stage {
    position: relative;
    display: flex;
    flex: 1;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
  }

  .chat-heading {
    display: none;
    flex: none;
    gap: var(--space-3);
    min-height: 64px;
    padding: var(--space-2) clamp(var(--space-4), 3vw, var(--space-6));
    box-shadow: inset 0 -0.5px 0 var(--surface-divider);
  }

  .heading-text { display: grid; flex: 1; min-width: 0; }
  .heading-text h1 {
    margin: 0;
    color: var(--text-1);
    font-size: var(--text-base);
    font-weight: 680;
    line-height: var(--leading-snug);
  }

  .heading-text span { color: var(--text-2); font-size: var(--text-xs); }

  .msgs {
    display: flex;
    flex: 1;
    flex-direction: column;
    min-height: 0;
    padding: var(--space-5)
      max(clamp(var(--space-4), 3vw, var(--space-6)), calc((100% - var(--chat-msg-maxw)) / 2))
      var(--space-3);
    overflow: hidden auto;
    overscroll-behavior: contain;
    scrollbar-width: thin;
  }

  .msgs.empty {
    background: radial-gradient(ellipse 65% 58% at 50% 35%, var(--accent-soft), transparent 76%);
  }

  .scroll-anchor { flex: none; height: 1px; }
  .msgs.empty .scroll-anchor { display: none; }

  .center-hint {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    padding: var(--space-4);
    color: var(--text-2);
    font-size: var(--text-sm);
  }

  .msgs > .center-hint { margin: auto; }

  .welcome {
    display: flex;
    flex: none;
    flex-direction: column;
    align-items: center;
    gap: var(--space-4);
    width: min(100%, 500px);
    margin: auto;
    padding-block: var(--space-3);
    text-align: center;
    animation: chat-appear var(--transition-spring);
  }

  .welcome-avatar {
    display: grid;
    place-items: center;
    width: 110px;
    height: 110px;
    border-radius: var(--radius-avatar);
    background: radial-gradient(ellipse, var(--accent-glow) 18%, transparent 75%);
    filter: drop-shadow(0 6px 12px var(--accent-glow));
  }

  .welcome-heading { display: grid; gap: var(--space-1); }
  .welcome-heading h2 {
    margin: 0;
    color: var(--text-1);
    font-size: clamp(1.8rem, 4vw, var(--text-3xl));
    font-weight: 700;
    letter-spacing: var(--tracking-tighter);
    line-height: var(--leading-tight);
    overflow-wrap: anywhere;
  }

  .welcome-heading p {
    display: -webkit-box;
    max-width: 42ch;
    margin: 0 auto;
    overflow: hidden;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    color: var(--text-2);
    font-size: var(--text-sm);
  }

  .welcome-note {
    max-width: 100%;
    margin: 0;
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius-md);
    background: var(--surface-bubble);
    box-shadow: var(--shadow-1);
    color: var(--text-1);
    font-size: var(--text-sm);
  }

  .prompt-chips { display: flex; flex-wrap: wrap; justify-content: center; gap: var(--space-2); }
  .prompt-chip { min-height: 39px; padding-inline: var(--space-3); }
  .prompt-chip :global(svg) { color: var(--accent); }

  .msg-row {
    display: flex;
    flex: none;
    align-self: flex-start;
    align-items: flex-start;
    gap: var(--space-2);
    min-width: 0;
    max-width: min(var(--chat-msg-maxw), 90%);
  }

  .msg-row + .msg-row { margin-top: 18px; }
  .msg-row.joins-before { margin-top: 5px; }
  .msg-row.self { align-self: flex-end; }
  .av { flex: none; padding-top: 1px; }
  .joined-avatar { visibility: hidden; }

  .bubble-col {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 5px;
    min-width: 0;
    max-width: 100%;
  }

  .self .bubble-col { align-items: flex-end; }

  .bubble {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--space-2);
    min-width: 0;
    max-width: 100%;
    padding: var(--optical-10) var(--space-4);
    border-radius: var(--bubble-radius-lg);
    font-size: var(--text-15);
    line-height: 1.65;
    overflow-wrap: anywhere;
  }

  .bubble-user {
    background: var(--self-fill);
    box-shadow: inset 0 1px 0 var(--floating-highlight);
    color: var(--self-ink);
  }

  .bubble-ai {
    background: var(--bubble-friend-bg);
    box-shadow: inset 0 0 0 1px var(--surface-divider), var(--shadow-1);
    color: var(--bubble-friend-text);
  }

  .joins-before .bubble-user { border-start-end-radius: var(--bubble-radius-sm); }
  .joins-after .bubble-user { border-end-end-radius: var(--bubble-radius-sm); }
  .joins-before .bubble-ai { border-start-start-radius: var(--bubble-radius-sm); }
  .joins-after .bubble-ai { border-end-start-radius: var(--bubble-radius-sm); }

  .bubble-text,
  .bubble blockquote { white-space: pre-wrap; }

  .bubble blockquote {
    margin: 0;
    padding: var(--space-1) var(--space-2);
    border-inline-start: 3px solid color-mix(in srgb, currentColor 48%, transparent);
    border-radius: var(--radius-xs);
    background: color-mix(in srgb, currentColor 8%, transparent);
    font-size: var(--text-sm);
  }

  .bubble-time {
    padding-inline: var(--optical-3);
    color: var(--bubble-time);
    font-size: var(--text-2xs);
    font-variant-numeric: tabular-nums;
    line-height: var(--leading-tight);
  }

  .message-code {
    min-width: 0;
    max-width: 100%;
    overflow: hidden;
    border-radius: var(--radius-sm);
    background: var(--code-fill);
    color: var(--code-ink);
  }

  .code-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding: var(--space-1) var(--space-2) var(--space-1) var(--space-3);
    background: color-mix(in srgb, var(--code-ink) 8%, transparent);
    font-family: var(--font-mono);
    font-size: var(--text-xs);
  }

  .code-copy {
    min-height: 30px;
    padding: 0 var(--space-2);
    border: 0;
    border-radius: var(--radius-xs);
    background: color-mix(in srgb, var(--code-ink) 10%, transparent);
    color: var(--code-ink);
    font: inherit;
    cursor: pointer;
  }

  .code-copy:hover { background: color-mix(in srgb, var(--code-ink) 20%, transparent); }

  .message-code pre {
    max-width: 100%;
    margin: 0;
    padding: var(--space-2) var(--space-3);
    overflow-x: auto;
    font-family: var(--font-mono);
    font-size: var(--text-13);
    line-height: var(--leading-normal);
    overflow-wrap: normal;
    scrollbar-width: thin;
  }

  .message-code code { font: inherit; }

  .chat-image-btn {
    display: block;
    max-width: min(100%, 290px);
    padding: 0;
    border: 0;
    border-radius: var(--radius-md);
    background: transparent;
    cursor: zoom-in;
  }

  .chat-image {
    display: block;
    max-width: 100%;
    max-height: min(320px, 50dvh);
    border-radius: inherit;
    box-shadow: var(--shadow-2);
    object-fit: contain;
  }

  .sticker-img {
    display: block;
    width: min(132px, 100%);
    max-height: 152px;
    object-fit: contain;
    filter: drop-shadow(0 5px 5px var(--surface-divider));
    animation: chat-appear var(--transition-spring);
  }

  .voice-bar {
    display: inline-flex;
    align-items: center;
    justify-content: flex-start;
    gap: var(--space-2);
    min-height: 42px;
    padding-block: 0;
    border: 0;
    cursor: pointer;
    white-space: nowrap;
  }

  .voice-icon { display: inline-flex; }
  .voice-bar.playing .voice-icon { animation: breathe 0.8s var(--ease-in-out) infinite; }

  .reasoning {
    min-width: 0;
    max-width: 100%;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--field-fill);
    color: var(--text-2);
    font-size: var(--text-xs);
    overflow-wrap: anywhere;
  }

  .reasoning summary { color: var(--text-1); font-weight: 600; cursor: pointer; }
  .reasoning summary .thinking-dots { margin-inline-start: var(--space-1); }
  .reasoning-body { max-height: 260px; margin-top: var(--space-2); overflow-y: auto; white-space: pre-wrap; }

  .thinking-hint {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-pill);
    background: var(--field-fill);
    color: var(--text-2);
    font-size: var(--text-xs);
  }

  .thinking-dots {
    display: inline-flex;
    flex: none;
    align-items: center;
    gap: 3px;
    color: var(--accent);
  }

  .thinking-dots i {
    width: 5px;
    height: 5px;
    border-radius: var(--radius-pill);
    background: currentColor;
    animation: breathe 1.18s var(--ease-in-out) infinite;
  }

  .thinking-dots i:nth-child(2) { animation-delay: 110ms; }
  .thinking-dots i:nth-child(3) { animation-delay: 220ms; }
  .streaming-indicator { line-height: 1; }
  .debounce-hint { align-self: flex-end; margin-top: var(--space-2); }

  @keyframes breathe {
    0%, 65%, 100% { opacity: 0.45; transform: translateY(0); }
    32% { opacity: 1; transform: translateY(-3px); }
  }

  .input-area {
    position: relative;
    z-index: var(--z-base);
    display: grid;
    flex: none;
    gap: var(--space-2);
    width: min(100%, calc(var(--chat-msg-maxw) + 2 * var(--space-4)));
    margin-inline: auto;
    padding: var(--space-1) var(--space-4) var(--space-4);
  }

  .immersive .input-area {
    padding-bottom: max(var(--space-4), env(safe-area-inset-bottom, 0px));
  }

  .composer {
    display: grid;
    min-width: 0;
    gap: var(--space-1);
    padding: var(--space-2);
    border-radius: var(--radius-lg);
  }

  .composer:focus-within {
    box-shadow: 0 0 0 3px var(--accent-soft), var(--surface-floating-shadow);
  }

  .text-input {
    width: 100%;
    min-height: 40px;
    max-height: 148px;
    padding: 8px var(--space-2);
    border: 0;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--input-text);
    font: inherit;
    font-size: var(--text-base);
    line-height: 1.5;
    resize: none;
  }

  .text-input:focus { outline: 0; box-shadow: none; }
  .text-input::placeholder { color: var(--input-placeholder); }

  .composer-actions { justify-content: space-between; }
  .composer-tools { gap: var(--space-1); }

  .send-btn {
    display: inline-grid;
    flex: none;
    place-items: center;
    width: 42px;
    height: 42px;
    padding: 0;
    border: 0;
    border-radius: var(--radius-pill);
    background: var(--accent-gradient);
    box-shadow: var(--shadow-accent);
    color: var(--on-accent);
    cursor: pointer;
  }

  .send-btn:hover:enabled { filter: brightness(1.08); }
  .send-btn:disabled {
    background: var(--field-fill);
    box-shadow: none;
    color: var(--text-3);
    cursor: default;
  }

  .send-btn.stop { background: var(--accent-soft); color: var(--accent); box-shadow: none; }

  .attachment {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-width: 0;
    padding: var(--space-1) var(--space-2);
  }

  .attachment-thumb { position: relative; flex: none; width: 48px; aspect-ratio: 1; }
  .attachment-thumb img { width: 100%; height: 100%; border-radius: var(--radius-sm); object-fit: cover; }

  .attachment-close {
    position: absolute;
    inset-block-start: -4px;
    inset-inline-end: -5px;
    display: grid;
    place-items: center;
    width: 24px;
    height: 24px;
    padding: 0;
    border: 0;
    border-radius: var(--radius-pill);
    background: var(--surface);
    box-shadow: var(--shadow-2);
    color: var(--text-1);
    cursor: pointer;
  }

  .attachment-info { display: grid; min-width: 0; color: var(--text-2); font-size: var(--text-xs); }
  .attachment-info strong { overflow: hidden; color: var(--text-1); text-overflow: ellipsis; white-space: nowrap; }
  .attachment-uploading { gap: var(--space-2); color: var(--text-2); font-size: var(--text-xs); }
  .attachment-spinner {
    flex: none;
    width: 16px;
    height: 16px;
    border: 2px solid var(--surface-divider);
    border-top-color: var(--accent);
    border-radius: var(--radius-pill);
    animation: spin 0.8s linear infinite;
  }
  @media (prefers-reduced-motion: reduce) {
    .attachment-spinner { animation: none; }
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  .config-recheck,
  .popover-action {
    min-height: 36px;
    padding: var(--space-1) var(--space-3);
    border: 0;
    border-radius: var(--radius-sm);
    background: var(--field-fill);
    color: var(--text-2);
    font: inherit;
    font-size: var(--text-xs);
    cursor: pointer;
  }

  .config-recheck:hover:enabled,
  .popover-action:hover { background: var(--row-hover); color: var(--text-1); }
  .config-recheck:disabled { opacity: 0.55; cursor: default; }

  .sticker-panel,
  .chat-tools,
  .convs-menu {
    z-index: var(--z-popover);
    padding: var(--space-2);
    border-radius: var(--radius-md);
    animation: chat-appear var(--transition-spring);
  }

  .sticker-panel,
  .chat-tools {
    position: absolute;
    inset-inline-start: var(--space-4);
    bottom: 100%;
  }

  .sticker-panel { width: min(420px, calc(100% - 2 * var(--space-4))); }
  .sticker-panel .panel-head { padding-inline-start: var(--space-2); }

  .sticker-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(48px, 1fr));
    gap: var(--space-1);
    max-height: min(210px, 36dvh);
    padding: 3px;
    overflow-y: auto;
    scrollbar-width: thin;
  }

  .sticker-grid .center-hint { grid-column: 1 / -1; margin: 0; }

  .sticker-item {
    display: grid;
    place-items: center;
    min-width: 0;
    aspect-ratio: 1;
    padding: var(--space-1);
    border: 0;
    border-radius: var(--radius-sm);
    background: transparent;
    cursor: pointer;
  }

  .sticker-item:hover { background: var(--accent-soft); }
  .sticker-item img { width: 100%; height: 100%; object-fit: contain; }

  .chat-tools,
  .convs-menu { display: grid; gap: var(--optical-3); width: 170px; }
  .popover-action { display: flex; align-items: center; gap: var(--space-2); background: transparent; text-align: left; }
  .popover-action.danger { color: var(--error); }
  .popover-action.danger:hover { background: var(--error-soft); color: var(--error); }

  .convs-menu {
    position: fixed;
    top: clamp(8px, var(--menu-top, 8px), calc(100dvh - 92px));
    left: max(8px, calc(var(--menu-right, 178px) - 170px));
  }

  .drawer-mask {
    position: absolute;
    inset: 0;
    z-index: var(--z-scrim);
    width: 100%;
    padding: 0;
    border: 0;
    border-radius: 0;
    cursor: pointer;
  }

  .drawer-mask:active { transform: none; }

  .drawer {
    position: absolute;
    inset-block: var(--space-2);
    inset-inline-start: var(--space-2);
    z-index: var(--z-drawer);
    width: min(310px, calc(100% - var(--space-6)));
    animation: chat-appear var(--transition-spring);
  }

  .chat-toast {
    position: absolute;
    top: var(--space-3);
    left: 50%;
    z-index: var(--z-toast);
    display: flex;
    align-items: center;
    gap: var(--space-2);
    width: max-content;
    max-width: min(92%, 480px);
    padding: var(--space-1) var(--space-1) var(--space-1) var(--space-3);
    border-radius: var(--radius-md);
    color: var(--text-1);
    font-size: var(--text-sm);
    overflow-wrap: anywhere;
    transform: translateX(-50%);
  }

  .img-preview-overlay {
    position: fixed;
    inset: 0;
    width: 100%;
    height: 100dvh;
    max-width: none;
    max-height: none;
    margin: 0;
    padding: 0;
    overflow: hidden;
    border: 0;
    background: transparent;
  }

  .img-preview-overlay::backdrop { background: rgb(0 0 0 / 0.82); }

  .img-preview-hit {
    display: grid;
    place-items: center;
    width: 100%;
    height: 100%;
    padding: var(--space-3);
    border: 0;
    background: transparent;
    cursor: zoom-out;
  }

  .img-preview-hit:active { transform: none; }
  .img-preview-full { max-width: 100%; max-height: 88dvh; border-radius: var(--radius-sm); object-fit: contain; }

  .img-preview-close {
    position: absolute;
    top: max(var(--space-3), env(safe-area-inset-top, 0px));
    inset-inline-end: var(--space-3);
    border-radius: var(--radius-pill);
  }

  @keyframes chat-appear {
    from { opacity: 0; transform: translateY(var(--motion-offset)); }
    to { opacity: 1; transform: translateY(0); }
  }

  @media (min-width: 768px) {
    .chat-heading { display: flex; }
  }

  @media (max-width: 767px) {
    .msgs { padding: var(--space-4) var(--space-3) var(--space-2); }
    .msg-row { max-width: 93%; }
    .bubble { padding-inline: var(--space-3); }
    .input-area { padding: var(--space-1) var(--space-3) var(--space-2); }
    .sticker-panel, .chat-tools { inset-inline-start: var(--space-3); }
    .sticker-panel { width: calc(100% - 2 * var(--space-3)); }
    .conv-search input { font-size: var(--text-base); }
  }

  @media (prefers-reduced-motion: reduce) {
    .thinking-dots i,
    .voice-bar.playing .voice-icon,
    .sticker-img { animation: none; }
    .conv-entry:hover { transform: none; }
  }
</style>
