<script>
  // ============================================================
  // ContactsPage.svelte — 通讯录 人设/角色花名册 + 分组详情编辑
  //
  // - 列表: GET /api/persona -> [{id,name,avatar}]
  // - 搜索过滤名字; 点行进详情子视图 (组件内状态切换)
  // - 详情: GET /api/persona/{id} -> USER_FIELDS dict
  //         GET /api/persona/{id}/advanced -> ADVANCED_FIELDS dict
  // - 分组 Tab 编辑: 一个 schema (USER_GROUPS + ADV_GROUP) 刻画每个字段
  //   控件类型 (text/number/textarea/select/range/switch/list/list-dict/json),
  //   保存只提交当前分组涉及的字段, POST /api/persona/{id} {"fields":{...}}
  // - 精简视图 (PawzoChat 风格: 顶部固定基础区 头像+名字) + 3 张核心人设卡
  //   (PersonaCard) 关 textarea 优先; 其余全部字段收进「高级/全部字段」  //   折叠区 (PersonaAdvanced, 默认收起, 手风琴按原分组收起)  //   精简卡字段在高级区不重复, 54 个字段均可完整读写。  // - 新建 POST /api/persona {id,name,description?}
  // - 删除 DELETE /api/persona/{id}
  // - 头像: POST /api/persona/{id}/avatar (multipart file) / DELETE
  // - 去聊天 goTab('chat')
  //
  // 字段类型对照后端 core/persona/models.py (权威):
  //   initiative_level/clinginess/jealous_tendency : str (高中底 -> select
  //   relationship_level : int 0-100 -> range 滑杆
  //   sticker_probability : float -> range 0-1 (百分比显示)
  //   hobby : list[dict{name,detail}] -> list-dict 两列编辑
  //   高级 dict 字段 (identity_anchor/speaking_style/...) -> json 文本区  // ============================================================
import { get, post, del, postFile } from '../lib/pages-api.js';
import { listConversations, fetchHistory } from '../lib/chatApi.js';
import { friendlyTime } from '../lib/format.js';
import { goTab } from '../lib/router.js';
import { confirmDialog } from '../lib/dialog.svelte.js';
import Avatar from '../components/Avatar.svelte';
  import Toast from '../components/Toast.svelte';
  import PersonaCard from '../components/persona/PersonaCard.svelte';
  import PersonaAdvanced from '../components/persona/PersonaAdvanced.svelte';
  import PromptAdvancedPanel from '../components/persona/PromptAdvancedPanel.svelte';
  import { PROMPT_ALL } from '../components/persona/promptFields.js';

  // ============================================================
  // 字段 schema: 分组 tab -> 字段控制描述
  // ============================================================
  const USER_GROUPS = [
    {
      id: 'basic',
      label: '基本信息',
      fields: [
        { key: 'name', label: '名字', type: 'text' },
        { key: 'age', label: '年龄', type: 'number', step: 1, min: 0 },
        { key: 'gender', label: '性别', type: 'select', optional: true, options: ['女', '男', '其他'] },
        { key: 'birthday', label: '生日', type: 'text', placeholder: '如 3 月 14 日' },
        { key: 'hometown', label: '家乡', type: 'text' },
        { key: 'occupation', label: '职业', type: 'text' },
        { key: 'relationship_level', label: '关系阶段 (%)', type: 'range', min: 0, max: 100, step: 1 },
        { key: 'daily_routine', label: '日常作息', type: 'textarea' },
        { key: 'appearance', label: '外貌', type: 'textarea' },
        { key: 'background', label: '背景故事', type: 'textarea' },
      ],
    },
    {
      id: 'personality',
      label: '性格与特征',
      fields: [
        { key: 'personality', label: '性格特点', type: 'list', emptyHint: '每行一个性格标签，点「添加」新增' },
        { key: 'mbti', label: 'MBTI', type: 'text', placeholder: '如 INFP' },
        { key: 'hobbies', label: '爱好', type: 'list-dict', namePlaceholder: '爱好名称', detailPlaceholder: '补充说明（可选）' },
        { key: 'initiative_level', label: '主动程度', type: 'select', options: ['低', '中', '高'] },
        { key: 'clinginess', label: '粘人程度', type: 'select', options: ['低', '中', '高'] },
        { key: 'jealous_tendency', label: '吃醋倾向', type: 'select', options: ['低', '中', '高'] },
        { key: 'conflict_style', label: '冲突风格', type: 'textarea' },
        { key: 'affection_style', label: '示爱风格', type: 'textarea' },
        { key: 'question_tendency', label: '提问倾向', type: 'textarea' },
      ],
    },
    {
      id: 'expression',
      label: '表达与说话',
      fields: [
        { key: 'speech_rhythm', label: '语速节奏', type: 'textarea' },
        { key: 'emoji_habits', label: 'Emoji 习惯', type: 'text' },
        { key: 'catchphrases', label: '口头禅', type: 'list' },
        { key: 'filler_words', label: '语气词', type: 'list' },
        { key: 'pet_names', label: '昵称', type: 'list' },
        { key: 'nickname_for_user', label: '对我的称呼', type: 'text' },
        { key: 'happy_expression', label: '开心表达', type: 'text' },
        { key: 'sad_expression', label: '难过表达', type: 'text' },
        { key: 'angry_expression', label: '生气表达', type: 'text' },
        { key: 'jealous_expression', label: '吃醋表达', type: 'text' },
        { key: 'shy_expression', label: '害羞表达', type: 'text' },
      ],
    },
    {
      id: 'interests',
      label: '兴趣与话题',
      fields: [
        { key: 'music_taste', label: '音乐品味', type: 'textarea' },
        { key: 'movie_taste', label: '影视品味', type: 'textarea' },
        { key: 'food_preferences', label: '饮食偏好', type: 'textarea' },
        { key: 'favorite_topics', label: '喜欢的话题', type: 'list' },
        { key: 'avoided_topics', label: '回避的话题', type: 'list' },
      ],
    },
    {
      id: 'stickers',
      label: '表情包',
      fields: [
        { key: 'sticker_enabled', label: '表情包开关', type: 'switch' },
        { key: 'sticker_probability', label: '表情包概率', type: 'range', min: 0, max: 1, step: 0.01, percent: true },
        { key: 'sticker_pack', label: '表情包组', type: 'text', placeholder: '如 builtin' },
      ],
    },
  ];

  // 高级 Prompt 分组 (次级/折叠) ：字段来自 promptFields.js (单一事实来源)
  // 这些字段由 PromptAdvancedPanel 以友好分层的方式渲染, 不再平铺 raw json。
  const ADV_GROUP = {
    id: 'advanced',
    label: '高级 Prompt',
    hint: '以下字段直接影响模型行为，若不确定请保持默认',
    fields: PROMPT_ALL,
  };

  // ============================================================
  // 精简视图 (PawzoChat 风格: 默认展示的核心人设卡字段
  // 这些字段在「高级/全部字段」区中不再重复出现。  // ============================================================
  const LEAN_CARDS = [
    {
      id: 'who',
      title: '人设 · 一句话认识 TA',
      subtitle: 'TA 是谁、什么样，第一眼就知道',
      fields: [
        // 顺序是「先短后长」：性别/年龄两个一行能填完的放最前，
        // 背景故事这种要滚半屏的 textarea 压到最后。
        // 原来 background 排第一，一进详情页就是一大块输入框，
        // 而末尾的「年龄」数字框下面拖着半屏空白。
        { key: 'gender', label: '性别', type: 'select', optional: true, options: ['女', '男', '其他'] },
        { key: 'age', label: '年龄', type: 'number', step: 1, min: 0 },
        { key: 'personality', label: '性格标签', type: 'list', emptyHint: '每行一个性格词，点「添加」新增，如 温柔、毒舌' },
        { key: 'background', label: '背景故事', type: 'textarea', rows: 6 },
      ],
    },
    {
      id: 'talk',
      title: '说话与相处',
      subtitle: 'TA 怎么叫你、怎么说话',
      fields: [
        { key: 'nickname_for_user', label: '对我的称呼', type: 'text', placeholder: 'TA 怎么称呼你，如 亲爱的' },
        { key: 'catchphrases', label: '口头禅', type: 'list', emptyHint: '每行一句口头禅，点「添加」新增' },
        { key: 'speech_rhythm', label: '语速与节奏', type: 'textarea', rows: 3 },
      ],
    },
    {
      id: 'intimacy',
      title: '亲密与表情包',
      subtitle: '关系进度与表情包',
      fields: [
        { key: 'relationship_level', label: '关系阶段 (%)', type: 'range', min: 0, max: 100, step: 1 },
        { key: 'sticker_enabled', label: '表情包开关', type: 'switch' },
        { key: 'pet_names', label: '我的称呼', type: 'list', emptyHint: '你叫 TA 的昵称，每行一个' },
      ],
    },
  ];

  // 精简卡涉及的字段 key 集合 (用于从高级区剔除)
  function leanKeys() {
    const s = new Set();
    for (const c of LEAN_CARDS) for (const f of c.fields) s.add(f.key);
    return s;
  }

  // 「高级/全部字段」分片 = 原分组减去除精简卡字段 (因 name 已在顶部)
  // 高级 Prompt 字段不在此区, 由下方 PromptAdvancedPanel 以分层友好方式渲染。
  function buildAdvancedGroups() {
    const skip = leanKeys();
    skip.add('name');
    const groups = [];
    for (const g of USER_GROUPS) {
      const rest = g.fields.filter((f) => !skip.has(f.key));
      if (rest.length) groups.push({ id: g.id, label: g.label, hint: g.hint, fields: rest });
    }
    return groups;
  }

  const ADVANCED_GROUPS = buildAdvancedGroups();

  // 查字段 meta
  // ============================================================
  // 归一化: 后端值 -> 编辑值  // ============================================================
  function norm(v, meta) {
    switch (meta.type) {
      case 'list':
        if (Array.isArray(v)) return v.map((s) => String(s));
        if (typeof v === 'string' && v.trim()) return v.split('\n').map((s) => s.trim()).filter(Boolean);
        return v == null ? [] : [String(v)];
      case 'list-dict': {
        if (!Array.isArray(v)) return [];
        return v.map((x) => ({ name: x?.name || '', detail: x?.detail || '' }));
      }
      case 'json':
        // dict 类字段: 空对象 -> 空文本 否则美化 JSON
        if (v == null) return '';
        if (typeof v === 'string') return v;
        if (typeof v === 'object' && Object.keys(v).length === 0) return '';
        return JSON.stringify(v, null, 2);
      case 'prompt-dict': {
        // 友好键值表示 归一化为对象, 保留全部历史 key(不丢字段),
        // 并确保 spec.keys 均存在(供输入框绑定)。
        const spec = meta.spec || {};
        const out = {};
        if (v && typeof v === 'object') {
          for (const [k, val] of Object.entries(v)) {
            if (val != null && typeof val !== 'object') out[k] = String(val);
          }
        } else if (typeof v === 'string') {
          const first = spec.keys && spec.keys[0];
          if (first != null) out[first] = v;
        }
        for (const k of spec.keys || []) {
          if (out[k] == null) out[k] = '';
        }
        return out;
      }
      case 'dialog-list': {
        // 结构化示例对: list[{ scenario, reply:[..] }]
        if (!Array.isArray(v)) return [];
        return v.map((d) => ({
          scenario: d?.scenario || '',
          reply: Array.isArray(d?.reply) ? d.reply.map((s) => String(s)) : [],
        }));
      }
      case 'range':
        if (v == null || v === '') return meta.min ?? 0;
        return Number(v);
      case 'number':
        if (v == null || v === '') return '';
        return Number(v);
      case 'switch':
        return !!v;
      case 'select':
      case 'text':
      case 'textarea':
      default:
        return v == null ? '' : String(v);
    }
  }

  // 反归一化: 编辑值 -> 后端值
  function denorm(slot) {
    const meta = slot.meta;
    const v = slot.value;
    switch (meta.type) {
      case 'list':
        return Array.isArray(v) ? v.map((s) => String(s).trim()).filter((s) => s) : [];
      case 'list-dict':
        return Array.isArray(v)
          ? v
              .filter((r) => r && String(r.name || '').trim())
              .map((r) => {
                const name = String(r.name).trim();
                const detail = String(r.detail || '').trim();
                return detail ? { name, detail } : { name };
              })
          : [];
      case 'json': {
        if (typeof v === 'string' && v.trim()) {
          try {
            return JSON.parse(v);
          } catch {
            // 解析失败则回退到后端原始值 避免破坏数据
            return slot.orig ?? {};
          }
        }
        return slot.orig ?? {};
      }
      case 'prompt-dict': {
        // 只保留非空 key, 且与 prompt_builder 期望的 key 完全一致
        // 未知 key(历史遗留) 原样保留, 不丢字段。
        if (!v || typeof v !== 'object') return {};
        const out = {};
        for (const [k, val] of Object.entries(v)) {
          const s = String(val ?? '').trim();
          if (s) out[k] = s;
        }
        return out;
      }
      case 'dialog-list': {
        // 过滤空场景条目: 剔除空回复 保持 { scenario, reply }
        if (!Array.isArray(v)) return [];
        return v
          .filter((d) => d && String(d.scenario || '').trim())
          .map((d) => ({
            scenario: String(d.scenario).trim(),
            reply: Array.isArray(d.reply)
              ? d.reply.map((s) => String(s).trim()).filter(Boolean)
              : [],
          }));
      }
      case 'number':
        return v === '' ? undefined : Number(v);
      case 'range':
        return Number(v);
      case 'switch':
        return !!v;
      case 'select':
      case 'text':
      case 'textarea':
      default:
        return String(v ?? '');
    }
  }

  // ============================================================
  // 状态变量  // ============================================================
  let list = $state([]);
  let loading = $state(true);
  let query = $state('');
  let previews = $state(new Map());
  let rosterConversations;
  const previewRequests = new Set();
  let selected = $state(null); // persona id in detail
  let detail = $state(null); // USER_FIELDS dict
  let advanced = $state(null); // ADVANCED_FIELDS dict
  let loadingDetail = $state(false);
  let detailError = $state('');
  let saving = $state(false);
  let toast = $state(null);
  let toastTimer = null;

  // 新建弹窗
  let showCreate = $state(false);
  let newForm = $state({ id: '', name: '', description: '', personality: [] });
  // 可选性格标签（来自 /api/persona/tags，与 CLI 向导同一份翻译表）
  let personaTags = $state([]);
  let tagSpecs = $state({});       // 标签名 → {speaking, emotion, relationship, hard_rules}
  let tagMax = $state(3);          // 多选上限（后端给，不前端写死）
  let tagMutex = $state([]);       // 互斥组
  let tagVersion = $state(1);      // 1 = 只有名字没有草稿，前端应隐藏预览区

  // 三段可编辑草稿。空串 = 用户清空了这一项。
  // 来源有二：点标签自动生成，或用户直接手写。两种都提交给后端 drafts。
  let drafts = $state({ speaking: '', emotion: '', relationship: '' });
  // 草稿是否被用户动过 —— 动过之后就不再被「点标签」覆盖，否则用户改的字会没
  let draftsDirty = $state(false);

  $effect(() => {
    let alive = true;
    get('/api/persona/tags')
      .then((r) => {
        if (!alive || !r.ok) return;
        const d = r.data || {};
        if (Array.isArray(d.tags)) personaTags = d.tags;
        if (Array.isArray(d.specs)) {
          const map = {};
          for (const s of d.specs) if (s?.name) map[s.name] = s;
          tagSpecs = map;
        }
        if (Number.isFinite(d.max_tags) && d.max_tags > 0) tagMax = d.max_tags;
        if (Array.isArray(d.mutex_groups)) tagMutex = d.mutex_groups;
        tagVersion = d.version === 2 ? 2 : 1;
      })
      .catch(() => { /* 标签加载失败不阻断建人，降级为纯手填 */ });
    return () => {
      alive = false;
    };
  });

  // 互斥对：选中一个就取消同组其它（后端只提示不拒绝，这里替用户做了）
  function mutexOf(tag) {
    const out = new Set();
    for (const g of tagMutex) {
      if (Array.isArray(g) && g.includes(tag)) for (const t of g) if (t !== tag) out.add(t);
    }
    return out;
  }

  function toggleTag(tag) {
    const picked = newForm.personality;
    if (picked.includes(tag)) {
      newForm.personality = picked.filter((t) => t !== tag);
    } else {
      // 上限：满了就不再追加，并给出原因（静默忽略会让人以为点坏了）
      if (picked.length >= tagMax) {
        showToast(`最多选 ${tagMax} 个性格标签`, 'error');
        return;
      }
      const blocked = mutexOf(tag);
      const kept = picked.filter((t) => !blocked.has(t));
      newForm.personality = [...kept, tag];
    }
    regenerateDrafts();
  }

  // 由本地 specs 直接拼三段文本 —— 与后端 preview_persona_tags 的合并规则
  // 完全一致（同层去重 + 「；」并列），所以不需要每次点选都打一次网络请求。
  // 后端仍保留 /tags/preview 供其它入口使用。
  function composeDrafts(picked) {
    const sep = '；';
    const join = (key) => {
      const seen = [];
      for (const t of picked) {
        const v = (tagSpecs[t]?.[key] || '').trim().replace(/。$/, '');
        if (v && !seen.includes(v)) seen.push(v);
      }
      return seen.join(sep);
    };
    return {
      speaking: join('speaking'),
      emotion: join('emotion'),
      relationship: join('relationship'),
    };
  }

  function regenerateDrafts() {
    if (tagVersion !== 2) return;
    // 用户手改过就不再覆盖 —— 否则他删掉的半句话会在下一次点选时复活
    if (draftsDirty) return;
    drafts = composeDrafts(newForm.personality);
  }

  // 手动重置回标签生成的版本
  function resetDrafts() {
    draftsDirty = false;
    drafts = composeDrafts(newForm.personality);
  }

  function onDraftInput(key, e) {
    drafts = { ...drafts, [key]: e.currentTarget.value };
    draftsDirty = true;
  }

  // 草稿 textarea 自动增高。
  // 原因: 后端生成的草稿常有 60~120 字, 而 rows="2" 只有两行高,
  // 内容被裁掉半行 —— 用户看不到自己即将保存的是什么, 等于白给。
  // 用 action 而不是 CSS: textarea 的 height 不会随内容自动长,
  // 必须读 scrollHeight 再回写。参数是草稿文本, 变化时重算。
  function autoGrow(node, text) {
    const fit = () => {
      // 先把 height 归零, 否则 scrollHeight 会取当前 height 而不是内容高度
      node.style.height = 'auto';
      // scrollHeight 不含 border, 而 .draft-input 是 border-box:
      // 直接写 scrollHeight 会让内容区少掉上下边框(实测 2px), 末行贴边。
      const cs = getComputedStyle(node);
      const borderY = (parseFloat(cs.borderTopWidth) || 0) + (parseFloat(cs.borderBottomWidth) || 0);
      node.style.height = node.scrollHeight + borderY + 'px';
    };
    // 首帧: 元素可能还没进入布局, 下一帧再算一次
    fit();
    requestAnimationFrame(fit);
    return {
      update(next) {
        // text 变化(标签增删 / 用户输入)后重算
        void next;
        requestAnimationFrame(fit);
      },
    };
  }

  let creating = $state(false);

  // 表单编辑状态 { key: { meta, value, orig? } } (rune 深响应
  let form = $state({});

  let filtered = $derived(
    query.trim() ? list.filter((p) => (p.name || '').toLowerCase().includes(query.trim().toLowerCase())) : list
  );

  // 名单每行的副标题: 年龄 · 性别 · 职业，按有值的拼，全空则返回空串。
  // 通讯录原来每行只有一个名字 —— 两个人设看着就是一张空表。
  function personaMeta(p) {
    const bits = [];
    if (p.age) bits.push(`${p.age} 岁`);
    const gender = (p.gender || '').trim();
    if (gender) bits.push(gender);
    const occ = (p.occupation || '').trim();
    if (occ) bits.push(occ);
    return bits.join(' · ');
  }

  function messageSnippet(message) {
    const blocks = Array.isArray(message.blocks) ? message.blocks : [];
    const text = String(blocks.find((block) => block.type === 'text')?.text ?? message.content ?? '').trim();
    const caption = /^对方同时说：「([\s\S]*?)」。\s*对方发了一张图片：/.exec(text);
    if (caption) return caption[1];
    if (/^对方发了一张图片：/.test(text)) return '图片';
    if (text) return text;
    if (message.image || blocks.some((block) => block.type === 'image')) return '图片';
    if (message.sticker || blocks.some((block) => block.type === 'emoji')) return '贴纸';
    if (message.voice_url || blocks.some((block) => block.type === 'voice')) return '语音';
    return '';
  }

  async function loadPreview(id) {
    if (previews.has(id) || previewRequests.has(id)) return;
    previewRequests.add(id);
    try {
      rosterConversations ??= listConversations().catch(() => {
        rosterConversations = null;
        return [];
      });
      const conversations = await rosterConversations;
      if (!Array.isArray(conversations)) return;
      // 一个角色可能同时有 Web / 微信两条会话。`updated_at` 只在建会话时
      // 写入、发消息不会刷新（后端 binding 不追踪最后消息时间），所以不能
      // 只挑“最近更新”的那条 —— 那常常是空的微信会话。改成最多取三条候选，
      // 各自拉一次历史，按**真实消息时间**取最新的那条。
      const candidates = conversations
        .filter((item) => item.persona_id === id && item.conversation_id)
        .sort((a, b) => (Date.parse(b.updated_at) || 0) - (Date.parse(a.updated_at) || 0))
        .slice(0, 3);
      if (!candidates.length) {
        previews = new Map(previews).set(id, null);
        return;
      }
      let latest = null;
      let snippet = '';
      for (const conversation of candidates) {
        let history;
        try {
          history = await fetchHistory(conversation.conversation_id);
        } catch {
          continue;
        }
        for (const message of history) {
          if (message.role !== 'user' && message.role !== 'assistant') continue;
          const time = Date.parse(message.timestamp) || 0;
          if (latest && time <= latest.time) continue;
          const text = messageSnippet(message);
          if (!text) continue;
          latest = { time, label: friendlyTime(message.timestamp) };
          snippet = text;
        }
      }
      previews = new Map(previews).set(id, latest ? { text: snippet, time: latest.label } : null);
    } catch {
      // 摘要是辅助信息，接口不可用时仍可浏览角色与编辑设定。
    } finally {
      previewRequests.delete(id);
    }
  }

  function watchPreview(node, id) {
    if (typeof IntersectionObserver === 'undefined') {
      loadPreview(id);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      loadPreview(id);
    });
    observer.observe(node);
    return { destroy: () => observer.disconnect() };
  }

  function showCreateDialog(node) {
    node.showModal();
    node.querySelector('.create-name')?.focus();
  }

  function closeCreate(event) {
    event?.preventDefault();
    showCreate = false;
  }

  $effect(() => {
    loadList();
  });

  async function loadList() {
    loading = true;
    const r = await get('/api/persona');
    list = Array.isArray(r.data) ? r.data : [];
    loading = false;
  }

  function showToast(text, type = 'info') {
    toast = { text, type };
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast = null), 2400);
  }

  function openDetail(id) {
    selected = id;
    detailError = '';
    loadDetail();
  }

  function backToList() {
    selected = null;
    detail = null;
    advanced = null;
    form = {};
  }

  async function loadDetail() {
    const id = selected;
    if (id == null) return;
    loadingDetail = true;
    detailError = '';
    const [b, a] = await Promise.all([
      get(`/api/persona/${id}`),
      get(`/api/persona/${id}/advanced`),
    ]);
    if (selected !== id) return;
    loadingDetail = false;
    if (!b.ok) {
      detailError = '加载失败，请重试';
      return;
    }
    const base = b.data && typeof b.data === 'object' ? b.data : {};
    detail = base;

    // 初始化编辑状态: 以 schema 覆盖扫描 USER/ADVANCED 字段
    const f = {};
    for (const g of USER_GROUPS) {
      for (const meta of g.fields) {
        const raw = base[meta.key];
        f[meta.key] = { meta, value: norm(raw, meta), orig: raw };
      }
    }
    if (a.ok && a.data && typeof a.data === 'object') {
      advanced = a.data;
      for (const meta of ADV_GROUP.fields) {
        const raw = a.data[meta.key];
        f[meta.key] = { meta, value: norm(raw, meta), orig: raw };
      }
    } else {
      advanced = {};
      for (const meta of ADV_GROUP.fields) {
        const raw = undefined;
        f[meta.key] = { meta, value: norm(raw, meta), orig: raw };
      }
    }
    form = f;
  }

  // 提交指定 key 涉及的字段 (精简区/高级区手风琴共用)
  async function saveFields(keys, label) {
    if (!selected || saving) return;
    saving = true;
    const fields = {};
    for (const key of keys) {
      const slot = form[key];
      if (!slot) continue;
      const val = denorm(slot);
      // 年龄为空则发 '' (后端宽松); 其余照常
      if (val === undefined) continue;
      fields[key] = val;
    }
    const r = await post(`/api/persona/${selected}`, { fields });
    saving = false;
    if (r.ok) {
      showToast(label ? `「${label}」已保存` : '已保存', 'success');
      // 名字是否变化 (先与旧 orig 比对)
      const nameSlot = form['name'];
      const nameChanged =
        nameSlot && fields.name !== undefined && String(fields.name) !== String(nameSlot.orig ?? '');
      // 保存成功后把 orig 同步为刚提交的值, 脏值检测才能复位
      for (const [k, v] of Object.entries(fields)) {
        const slot = form[k];
        if (slot) slot.orig = v;
      }
      if (nameChanged) await loadList();
    } else {
      showToast(r.data?.error || r.data?.detail || '保存失败', 'error');
    }
  }

  // 精简卡保存: 复用按字段过滤提交
  function saveCard(keys, label) {
    saveFields(keys, label);
  }

  // 高级区手风琴按分组保存
  function saveAdvanced(keys, label) {
    saveFields(keys, label);
  }

  // ---- 新建 ----
  async function createPersona() {
    if (creating) return;
    const name = newForm.name.trim();
    if (!name) {
      showToast('请填写名字', 'error');
      return;
    }
    creating = true;
    const body = {
      name,
      description: newForm.description.trim() || undefined,
      personality: newForm.personality,
    };
    // 三段草稿：只提交用户**最终看见**的文本。
    // 空串不提交（后端把空串当"这次不用标签建议"，不写入也不删标签已写的）。
    const trimmed = {
      speaking: drafts.speaking.trim(),
      emotion: drafts.emotion.trim(),
      relationship: drafts.relationship.trim(),
    };
    if (Object.values(trimmed).some(Boolean)) body.drafts = trimmed;
    // 角色 ID 留空则后端按名字自动生成（用户不该去想技术 ID）
    const id = newForm.id.trim();
    if (id) body.id = id;
    const r = await post('/api/persona', body);
    creating = false;
    if (r.ok) {
      showToast(
        r.data?.generated_id ? `已创建「${name}」` : `已创建新角色（ID：${id}）`,
        'success',
      );
      showCreate = false;
      newForm = { id: '', name: '', description: '', personality: [] };
      drafts = { speaking: '', emotion: '', relationship: '' };
      draftsDirty = false;
      await loadList();
    } else if (r.status === 409) {
      showToast(r.data?.error || r.data?.detail || 'ID 已存在', 'error');
    } else {
      showToast(r.data?.error || r.data?.detail || '创建失败', 'error');
    }
  }

  // ---- 删除 ----
  async function removePersona() {
    if (!selected) return;
    const id = selected;
    const name = list.find((p) => p.id === id)?.name || '该角色';
    const ok = await confirmDialog(`确定删除「${name}」吗？此操作不可恢复。`, { title: '删除角色', danger: true });
    if (!ok) return;
    // 乐观删除：立即从本地列表移除，无需等待接口返回/返回上一步    list = list.filter((p) => p.id !== id);
    const r = await del(`/api/persona/${id}`);
    if (r.ok) {
      showToast('已删除', 'success');
      backToList();
      await loadList();
    } else {
      // 失败则回滚并提示
      await loadList();
      showToast(r.data?.error || r.data?.detail || (r.status === 409 ? '无法删除：存在关联数据' : '删除失败'), 'error');
    }
  }

  // ---- 头像 ----
  function onAvatarChange(e) {
    const file = e.target.files?.[0];
    if (!file || selected == null) return;
    uploadAvatar(file);
    e.target.value = '';
  }
  async function uploadAvatar(file) {
    const r = await postFile(`/api/persona/${selected}/avatar`, file, 'file');
    if (r.ok) {
      showToast('头像已更新', 'success');
      await loadDetail();
      await loadList();
    } else {
      showToast(r.data?.error || r.data?.detail || '头像上传失败', 'error');
    }
  }
  async function removeAvatar() {
    if (selected == null) return;
    const r = await del(`/api/persona/${selected}/avatar`);
    if (r.ok) {
      showToast('头像已移除', 'success');
      await loadDetail();
      await loadList();
    } else {
      showToast(r.data?.error || r.data?.detail || '移除头像失败', 'error');
    }
  }

  function goChat(id) {
    try {
      localStorage.setItem('cc-chat-persona', id);
    } catch {
      /* ignore */
    }
    goTab('chat');
  }

  let avatarInput = $state(null);
  let avatarSrc = $derived(detail?.avatar || list.find((p) => p.id === selected)?.avatar || '');
  let nameSlot = $derived(form['name'] || null);
  // 名字是否有未保存修改 (与后端原值比对)
  let nameDirty = $derived(
    nameSlot ? String(nameSlot.value ?? '').trim() !== String(nameSlot.orig ?? '').trim() : false
  );

  // 保存名字 (hero 区独立入口, 不依赖任何人设卡)
  function saveName() {
    if (!selected || saving) return;
    const name = String(nameSlot?.value ?? '').trim();
    if (!name) {
      showToast('名字不能为空', 'error');
      return;
    }
    saveFields(['name'], '名字');
  }

  function onNameKeydown(e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      saveName();
    }
  }
</script>

<svelte:head><title>通讯录 · 慕</title></svelte:head>

<Toast {toast} />

<div class="page" class:detail={selected != null}>
  {#if selected == null}
    <!-- ================= 列表视图 ================= -->
    <header class="page-top">
      <div class="page-top-main">
        <h1 class="page-title">通讯录</h1>
        <p class="page-lede">管理角色与她们的人设。</p>
      </div>
      <button class="btn btn-primary btn-sm" type="button" onclick={() => (showCreate = true)}>
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        新建角色
      </button>
    </header>

    <div class="search-box">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <input
        class="search-input"
        type="search"
        placeholder="搜索角色"
        bind:value={query}
        aria-label="搜索角色"
      />
      {#if filtered.length > 0 && !loading}
        <span class="search-count mono">{filtered.length}</span>
      {/if}
    </div>

    {#if loading}
      <div class="empty-state">
        <span class="empty-icon"><svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg></span>
        <p class="empty-desc">加载中…</p>
      </div>
    {:else if filtered.length === 0}
      <div class="empty-state">
        {#if list.length === 0}
          <span class="empty-icon"><svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg></span>
          <p class="empty-title">还没有角色</p>
          <p class="empty-desc">先建一个人设：名字、性格、说话方式。之后每次对话她都会记得这些。</p>
          <button class="btn btn-primary empty-btn" type="button" onclick={() => (showCreate = true)}>
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            新建角色
          </button>
        {:else}
          <span class="empty-icon"><svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg></span>
          <p class="empty-title">没有匹配结果</p>
          <p class="empty-desc">换个关键词，或者清空搜索看全部。</p>
        {/if}
      </div>
    {:else}
      <ul class="list">
        {#each filtered as p (p.id)}
          {@const meta = personaMeta(p)}
          {@const preview = previews.get(p.id)}
          {@const summary = p.summary || p.description || ''}
          <li class="roster-row" use:watchPreview={p.id}>
            <button class="roster-main" type="button" aria-label={'打开' + p.name + '的角色详情'} onclick={() => openDetail(p.id)}>
              <span class="roster-identity">
                <Avatar name={p.name} src={p.avatar || ''} size={50} />
                <span class="roster-body">
                  <span class="roster-name">{p.name}</span>
                  {#if meta}<span class="roster-meta">{meta}</span>{/if}
                </span>
              </span>
              {#if Array.isArray(p.personality) && p.personality.length}
                <span class="roster-tags">
                  {#each p.personality.slice(0, 3) as tag}<span class="roster-tag">{tag}</span>{/each}
                </span>
              {/if}
              {#if preview}
                <span class="roster-preview">
                  <span class="roster-preview-head">
                    <span>最近互动</span>
                    {#if preview.time}<span>{preview.time}</span>{/if}
                  </span>
                  <span class="preview-text">{preview.text}</span>
                </span>
              {:else if summary}
                <span class="roster-preview"><span class="preview-text">{summary}</span></span>
              {/if}
            </button>
            <button class="btn roster-go" type="button" title="去聊天" aria-label={'和' + p.name + '聊天'} onclick={() => goChat(p.id)}>
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
              去聊天
            </button>
          </li>
        {/each}
      </ul>
      <div class="list-foot">
        <span class="list-foot-count">
          共 <span class="mono">{list.length}</span> 位角色
        </span>
        <button class="btn btn-ghost btn-sm" type="button" onclick={() => (showCreate = true)}>
          再建一个
        </button>
      </div>
    {/if}

  {:else}
    <!-- ================= 详情视图 ================= -->
    {#if detail == null}
      <div class="detail-head">
        <button class="icon-btn outline" type="button" onclick={backToList} aria-label="返回">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>
        </button>
        <span class="detail-title">{detailError || '加载中…'}</span>
        {#if detailError}
          <button class="btn btn-outline btn-sm" type="button" onclick={loadDetail}>重试</button>
        {/if}
      </div>
    {:else}
      <div class="detail-head">
        <button class="icon-btn outline" type="button" onclick={backToList} aria-label="返回">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>
        </button>
        <span class="detail-title">角色详情</span>
        <span class="detail-spacer"></span>
        <button class="btn btn-ghost btn-sm danger" type="button" onclick={removePersona}>删除</button>
      </div>

      <!-- 顶部固定区: 头像 + 名字 + 操作 -->
      <div class="hero-card">
        <div class="hero-main">
          <div class="hero-avatar">
            <Avatar name={nameSlot?.value || ''} src={avatarSrc} size={84} />
            <button class="avatar-edit" type="button" title="更换头像" onclick={() => avatarInput?.click()} aria-label="更换头像">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
            </button>
            <input
              bind:this={avatarInput}
              type="file"
              accept="image/*"
              style="display:none"
              onchange={onAvatarChange}
            />
          </div>
          <div class="hero-info">
            <div class="hero-name-row">
              <input
                class="hero-name-input {nameDirty ? 'dirty' : ''}"
                type="text"
                placeholder="角色名字"
                value={nameSlot?.value || ''}
                oninput={(e) => {
                  if (nameSlot) nameSlot.value = e.currentTarget.value;
                }}
                onkeydown={onNameKeydown}
                aria-label="角色名字"
              />
              {#if nameDirty}
                <button class="btn btn-primary btn-sm name-save" type="button" disabled={saving} onclick={saveName}>
                  {saving ? '保存中…' : '保存'}
                </button>
              {/if}
            </div>
            <div class="avatar-actions">
              {#if avatarSrc}
                <button class="btn btn-ghost btn-sm" type="button" onclick={removeAvatar}>移除头像</button>
              {:else}
                <span class="hero-sub">点头像右下角的相机图标可更换头像</span>
              {/if}
            </div>
          </div>
        </div>
        <button class="btn btn-primary go-chat" type="button" onclick={() => goChat(selected)}>去聊天</button>
      </div>

      <!-- 精简人设卡 (PawzoChat 风格: 默认清爽视图 -->
      <div class="lean-section">
        {#each LEAN_CARDS as card (card.id)}
          <PersonaCard
            title={card.title}
            subtitle={card.subtitle}
            fields={card.fields}
            form={form}
            saving={saving}
            onsave={saveCard}
          />
        {/each}
      </div>

      <!-- 高级/全部字段折叠区: 普通字段 (默认收起) -->
      <PersonaAdvanced
        groups={ADVANCED_GROUPS}
        form={form}
        saving={saving}
        onsave={saveAdvanced}
      />

      <!-- 高级 Prompt 区 (友好、分层、不吓人) -->
      <PromptAdvancedPanel
        form={form}
        saving={saving}
        onsave={saveAdvanced}
      />
    {/if}
  {/if}
</div>

<!-- 新建弹窗 -->
{#if showCreate}
  <dialog class="modal glass-3" aria-label="新建角色" oncancel={closeCreate} use:showCreateDialog>
    <form class="modal-form" onsubmit={(event) => { event.preventDefault(); createPersona(); }}>
      <header class="modal-head">
        <h2 class="modal-title">新建角色</h2>
        <button class="icon-btn" type="button" aria-label="关闭新建角色窗口" onclick={closeCreate}>×</button>
      </header>
      <label class="field">
        <span class="field-label">名字 *</span>
        <input class="field-plain create-name" type="text" aria-required="true" placeholder="如 小月" bind:value={newForm.name} />
      </label>

      {#if personaTags.length}
        <div class="field">
          <div class="field-row">
            <span class="field-label">性格</span>
            <span class="field-count">{newForm.personality.length}/{tagMax}</span>
          </div>
          <p class="tag-hint">
            {tagVersion === 2
              ? '点选后自动生成下面三段草稿，草稿可以随便改；改动之后不再被标签覆盖'
              : '点选后会写进说话方式、情绪反应和相处模式'}
          </p>
          <div class="tag-cloud" role="group" aria-label="性格标签">
            {#each personaTags as tag}
              {@const on = newForm.personality.includes(tag)}
              {@const full = !on && newForm.personality.length >= tagMax}
              <button
                class="tag-chip {on ? 'on' : ''} {full ? 'is-full' : ''}"
                type="button"
                aria-pressed={on}
                title={full ? `最多选 ${tagMax} 个` : tag}
                onclick={() => toggleTag(tag)}
              >{tag}</button>
            {/each}
          </div>
        </div>

        {#if tagVersion === 2 && (newForm.personality.length > 0 || draftsDirty)}
          <div class="draft-block">
            <div class="field-row">
              <span class="field-label">她会变成这样</span>
              {#if draftsDirty}
                <button class="draft-reset" type="button" onclick={resetDrafts}>恢复标签建议</button>
              {/if}
            </div>
            <p class="tag-hint">这三段会写进人设，直接影响她怎么说话、怎么反应、怎么和你相处</p>

            <label class="draft-row">
              <span class="draft-key">说话方式</span>
              <textarea
                class="draft-input"
                rows="2"
                placeholder="比如：语气温和耐心，语速偏慢"
                value={drafts.speaking}
                use:autoGrow={drafts.speaking}
                oninput={(e) => onDraftInput('speaking', e)}
              ></textarea>
            </label>

            <label class="draft-row">
              <span class="draft-key">情绪反应</span>
              <textarea
                class="draft-input"
                rows="2"
                placeholder="比如：先接住情绪，再讲道理"
                value={drafts.emotion}
                use:autoGrow={drafts.emotion}
                oninput={(e) => onDraftInput('emotion', e)}
              ></textarea>
            </label>

            <label class="draft-row">
              <span class="draft-key">相处模式</span>
              <textarea
                class="draft-input"
                rows="2"
                placeholder="比如：会主动关心，但不过度追问"
                value={drafts.relationship}
                use:autoGrow={drafts.relationship}
                oninput={(e) => onDraftInput('relationship', e)}
              ></textarea>
            </label>
          </div>
        {/if}
      {/if}

      <label class="field">
        <span class="field-label">描述</span>
        <textarea class="field-plain" rows="3" placeholder="可选的一句话介绍" bind:value={newForm.description}></textarea>
      </label>

      <label class="field">
        <span class="field-label">角色 ID</span>
        <input class="field-plain" type="text" placeholder="留空自动生成" bind:value={newForm.id} />
        <p class="tag-hint">技术标识，仅在你需要固定引用它时填写（调用接口、写配置用）</p>
      </label>
      {#if toast?.type === 'error'}<p class="create-error" role="alert">{toast.text}</p>{/if}
      <div class="modal-actions">
        <button class="btn btn-outline" type="button" onclick={closeCreate}>取消</button>
        <button class="btn btn-primary" type="submit" disabled={creating}>
          {creating ? '创建中…' : '创建'}
        </button>
      </div>
    </form>
  </dialog>
{/if}

<style>
  .page {
    max-width: var(--page-maxw);
    margin-inline: auto;
    padding: clamp(16px, 4vw, 48px) clamp(12px, 4vw, 40px) var(--space-6);
  }

  .page.detail { max-width: 970px; }
  .page-top, .detail-head, .hero-main, .hero-name-row, .modal-head, .modal-actions, .field-row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  .page-top { justify-content: space-between; margin-bottom: var(--space-4); }
  .page-title {
    margin: 0;
    color: var(--text-1);
    font-size: clamp(1.8rem, 4vw, 2.9rem);
    letter-spacing: var(--tracking-tighter);
    line-height: var(--leading-tight);
  }

  .page-lede { margin: var(--space-2) 0 0; color: var(--text-2); font-size: var(--text-sm); }

  .search-box {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    max-width: 460px;
    min-height: 43px;
    padding: 0 var(--space-3);
    margin-bottom: var(--space-4);
    border-radius: var(--radius-pill);
    background: var(--field-fill);
    color: var(--text-2);
  }

  .search-box svg { flex: none; }
  .search-box:focus-within { background: var(--field-fill-focus); box-shadow: var(--focus-ring); }
  .search-input {
    flex: 1;
    min-width: 0;
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--text-1);
    font: inherit;
    font-size: var(--text-sm);
  }
  .search-input:focus { outline: 0; box-shadow: none; }
  .search-count { color: var(--text-2); font-size: var(--text-xs); }

  .list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 240px), 1fr));
    gap: var(--space-3);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .roster-row, .hero-card, .empty-state {
    min-width: 0;
    border-radius: var(--radius-lg);
    background: var(--surface);
    box-shadow: var(--surface-stage-shadow);
  }

  .roster-row {
    display: flex;
    flex-direction: column;
    align-items: start;
    gap: var(--space-1);
    padding: var(--space-2);
    transition: box-shadow var(--transition), transform var(--transition-spring);
  }

  .roster-row:hover { box-shadow: var(--shadow-2); transform: translateY(-2px); }

  .roster-main {
    display: grid;
    flex: 1;
    align-content: start;
    gap: var(--space-2);
    width: 100%;
    padding: var(--space-2);
    border: 0;
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--text-1);
    font: inherit;
    text-align: start;
    cursor: pointer;
  }

  .roster-main:hover { background: var(--row-hover); }
  .roster-identity { display: flex; align-items: center; gap: var(--space-2); min-width: 0; }
  .roster-body { display: grid; gap: var(--optical-2); min-width: 0; }
  .roster-name { color: var(--text-1); font-size: var(--text-lg); font-weight: 680; line-height: var(--leading-tight); overflow-wrap: anywhere; }
  .roster-meta { color: var(--text-2); font-size: var(--text-xs); overflow-wrap: anywhere; }
  .roster-tags, .tag-cloud { display: flex; flex-wrap: wrap; gap: var(--space-1); }

  .roster-tag {
    max-width: 100%;
    padding: var(--optical-2) var(--space-2);
    border-radius: var(--radius-pill);
    background: var(--accent-soft);
    color: var(--accent);
    font-size: var(--text-xs);
    overflow-wrap: anywhere;
  }

  .roster-preview {
    display: grid;
    gap: var(--space-1);
    min-width: 0;
    padding: var(--space-2);
    border-radius: var(--radius-sm);
    background: var(--field-fill);
    color: var(--text-2);
    font-size: var(--text-xs);
  }

  .roster-preview-head { display: flex; flex-wrap: wrap; justify-content: space-between; gap: var(--space-1); }
  .preview-text {
    display: -webkit-box;
    overflow: hidden;
    color: var(--text-1);
    overflow-wrap: anywhere;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
  }

  .list-foot { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); margin-top: var(--space-3); color: var(--text-2); font-size: var(--text-xs); }

  .btn, .icon-btn, .avatar-edit, .tag-chip, .draft-reset {
    display: inline-flex;
    flex: none;
    align-items: center;
    justify-content: center;
    gap: var(--space-1);
    min-height: 36px;
    padding: var(--space-1) var(--space-3);
    border: 0;
    border-radius: var(--radius-pill);
    background: var(--field-fill);
    color: var(--text-2);
    font: inherit;
    font-size: var(--text-13);
    font-weight: 600;
    cursor: pointer;
  }

  .btn-primary { background: var(--accent); color: var(--on-accent); }
  .btn-primary:hover:enabled { background: var(--accent-hover); }
  .btn:not(.btn-primary):hover:enabled, .icon-btn:hover, .draft-reset:hover { background: var(--accent-soft); color: var(--accent); }
  .btn-outline { background: transparent; box-shadow: inset 0 0 0 1px var(--border); color: var(--text-1); }
  .btn-outline:hover:enabled { background: var(--accent-soft); color: var(--accent); }
  /* 幽灵按钮：完全透明、无描边，用于「删除 / 移除」这类次要动作。 */
  .btn-ghost { background: transparent; color: var(--text-2); }
  .btn-ghost:hover:enabled { background: var(--row-hover); color: var(--text-1); }
  .btn-sm { min-height: 30px; padding-inline: var(--space-2); font-size: var(--text-xs); }
  .empty-btn { margin-top: var(--space-2); }
  .name-save { flex: none; }
  .btn:disabled { opacity: 0.55; cursor: default; }
  .btn.danger { color: var(--error); }
  .btn.danger:hover:enabled { background: var(--error-soft); color: var(--error); }
  .btn.roster-go { margin: 0 var(--space-2) var(--space-2) auto; background: var(--accent-soft); color: var(--accent); }
  .btn.roster-go:hover { background: var(--accent-glow); }

  .icon-btn { width: 36px; padding: 0; background: var(--field-fill); font-size: var(--text-lg); }
  .detail-head { margin-bottom: var(--space-3); }
  .detail-title { min-width: 0; color: var(--text-1); font-size: var(--text-15); font-weight: 650; }
  .detail-spacer { flex: 1; }

  .hero-card {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    padding: clamp(14px, 3vw, 24px);
    margin-bottom: var(--space-4);
    background: radial-gradient(ellipse 80% 145% at 0% 0%, var(--accent-soft), transparent 80%), var(--surface);
  }

  .hero-main { flex: 1; min-width: 0; gap: var(--space-3); }
  .hero-avatar { position: relative; flex: none; }
  .avatar-edit {
    position: absolute;
    right: -4px;
    bottom: -4px;
    z-index: 3;
    width: 36px;
    min-height: 36px;
    padding: 0;
    background: var(--surface);
    color: var(--accent);
    box-shadow: var(--shadow-2);
  }

  .hero-info { display: grid; flex: 1; min-width: 0; gap: var(--space-2); }
  .hero-name-row { align-items: stretch; }
  .hero-name-input, .field-plain, .draft-input {
    min-width: 0;
    width: 100%;
    min-height: 40px;
    padding: var(--space-2) var(--space-3);
    border: 0;
    border-radius: var(--radius-sm);
    background: var(--field-fill);
    color: var(--text-1);
    font: inherit;
    font-size: var(--text-base);
  }

  .hero-name-input { font-size: clamp(1.1rem, 2.4vw, 1.55rem); font-weight: 680; }
  .hero-name-input.dirty { background: var(--accent-soft); }
  .hero-name-input:focus, .field-plain:focus, .draft-input:focus {
    outline: 0;
    background: var(--field-fill-focus);
    box-shadow: var(--focus-ring);
  }

  .avatar-actions { display: flex; align-items: center; min-height: 30px; }
  .hero-sub, .tag-hint { margin: 0; color: var(--text-2); font-size: var(--text-xs); }
  .lean-section { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: start; gap: var(--space-3); margin-bottom: var(--space-3); }
  .lean-section :global(.persona-card:last-child:nth-child(odd)) { grid-column: 1 / -1; }
  .page.detail :global(.prompt-advanced) { margin-top: var(--space-4); }

  .empty-state {
    display: grid;
    justify-items: center;
    gap: var(--space-2);
    padding: var(--space-5);
    text-align: center;
  }
  .empty-icon { display: grid; place-items: center; width: 48px; height: 48px; border-radius: var(--radius-md); background: var(--accent-soft); color: var(--accent); }
  .empty-title, .empty-desc { margin: 0; }
  .empty-title { font-weight: 650; }
  .empty-desc { color: var(--text-2); font-size: var(--text-13); }

  .modal {
    width: min(560px, calc(100% - 2 * var(--space-3)));
    max-height: calc(100dvh - 2 * var(--space-4));
    padding: clamp(14px, 3vw, 22px);
    overflow: auto;
    border: 0;
    border-radius: var(--radius-xl);
    color: var(--text-1);
    animation: rise var(--transition-spring);
  }

  .modal::backdrop { background: var(--scrim); }
  .modal-form, .field, .draft-block, .draft-row { display: grid; gap: var(--space-2); min-width: 0; }
  .modal-form { gap: var(--space-3); }
  .modal-head, .field-row { justify-content: space-between; }
  .modal-title { margin: 0; font-size: var(--text-lg); }
  .modal-actions { justify-content: flex-end; }
  .field-label, .draft-key { color: var(--text-1); font-size: var(--text-13); font-weight: 650; }
  .field-count { color: var(--text-2); font-size: var(--text-xs); }

  .tag-chip { min-height: 34px; color: var(--text-1); }
  .tag-chip.on, .tag-chip:hover { background: var(--accent-soft); color: var(--accent); }
  .tag-chip.is-full { color: var(--text-2); }
  .draft-block { padding: var(--space-3); border-radius: var(--radius-md); background: var(--surface-2); }
  .draft-reset { min-height: 32px; font-size: var(--text-xs); }
  .draft-input, textarea.field-plain { resize: vertical; }
  .create-error { margin: 0; color: var(--error); font-size: var(--text-13); }

  @keyframes rise {
    from { opacity: 0; transform: translateY(var(--motion-offset)); }
    to { opacity: 1; transform: translateY(0); }
  }

  @media (max-width: 650px) {
    .page { padding-inline: var(--space-3); }
    .search-input { font-size: var(--text-base); }
    .lean-section { grid-template-columns: minmax(0, 1fr); }
    .hero-card { flex-wrap: wrap; }
    .hero-main { flex-basis: 100%; }
    .go-chat { margin-inline-start: auto; }
  }

  @media (prefers-reduced-motion: reduce) {
    .roster-row:hover { transform: none; }
  }
</style>
