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
    if (bits.length) return bits.join(' · ');
    return (p.summary || '').trim();
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
    if (selected == null) return;
    loadingDetail = true;
    detailError = '';
    const [b, a] = await Promise.all([
      get(`/api/persona/${selected}`),
      get(`/api/persona/${selected}/advanced`),
    ]);
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
        <span class="micro-label">人物</span>
        <h1 class="page-title">通讯录</h1>
        <p class="page-lede">设定她是谁，之后所有对话都建立在这些设定之上。</p>
      </div>
      <button class="btn btn-primary btn-sm" type="button" onclick={() => (showCreate = true)}>
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        新建角色
      </button>
    </header>

    <div class="search-box">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="var(--text-3)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <input
        class="search-input"
        type="text"
        placeholder="搜索名字…"
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
        {#each filtered as p, i (p.id)}
          <li class="roster-row">
            <button class="roster-main" type="button" onclick={() => openDetail(p.id)}>
              <Avatar name={p.name} src={p.avatar || ''} size={40} />
              <span class="roster-body">
                <span class="roster-name">{p.name}</span>
                {#if personaMeta(p)}
                  <span class="roster-meta">{personaMeta(p)}</span>
                {:else}
                  <span class="roster-meta roster-meta-empty">还没填设定</span>
                {/if}
                {#if (p.personality || []).length > 0}
                  <span class="roster-tags">
                    {#each p.personality.slice(0, 3) as tag}<span class="roster-tag">{tag}</span>{/each}
                  </span>
                {/if}
              </span>
            </button>
            <button class="icon-btn outline roster-go" type="button" title="去聊天" onclick={() => goChat(p.id)}>
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
            </button>
          </li>
        {/each}
      </ul>
      <!-- 名单只有两三行时，下面会剩一大片空白，看起来像「还没加载完」。
           补一条收尾行：左边是计数，右边是「再建一个」——
           空白变成可操作的位置，而不是页面没铺满。 -->
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
  <div class="overlay" role="dialog" aria-modal="true" aria-label="新建角色">
    <div class="modal">
      <h2 class="modal-title">新建角色</h2>
      <label class="field">
        <span class="field-label">名字 *</span>
        <input class="field-plain" type="text" placeholder="如 小月" bind:value={newForm.name} />
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
      <div class="modal-actions">
        <button class="btn btn-outline" type="button" onclick={() => (showCreate = false)}>取消</button>
        <button class="btn btn-primary" type="button" disabled={creating} onclick={createPersona}>
          {creating ? '创建中…' : '创建'}
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  /* 页面骨架 (padding / max-width): 通讯录 / 发现 / 记忆 三页共用同一套数值,
     改动时三处要一起改, 否则页头基线会在切页时跳一下。 */
  /* ---- 页面容器 ----
     原来 max-width 820px + margin:0 是最刺眼的一处：1440 宽的窗口里
     内容全挤在左上角，右侧留下 600px 纯空白，读起来像「没铺满」。
     改成居中 + 960px：一行角色能放下更多信息，页面也不再偏左。
     详情视图是纵向表单，宽了不好读，单独收窄到 760px。 */
  .page {
    padding: var(--page-pad-y) var(--page-pad-x) var(--space-8);
    max-width: var(--page-maxw);
    margin: 0 auto;
    width: 100%;
  }
  .page.detail {
    max-width: 760px;
  }

  /* ---- 页头 ----
     原来标题只有 16px/500, 与正文 14px 只差 2px、字重只差 100 ——
     一进页面没有「这是哪」的落点。改成: 11px 微标签(拉字距) +
     26px 主标题 + 13px 一句说明, 三层在同一条左基线上。
     结构线用 --border-strong(比内容区的 --border 重一档),
     让「页头/内容」的边界靠线的重量而不是靠留白去区分。 */
  .page-top {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: var(--space-4);
    padding-bottom: var(--space-4);
    margin-bottom: var(--space-5);
    border-bottom: 1px solid var(--border-strong);
  }
  .page-top-main {
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .page-title {
    margin: 0;
    font-size: var(--text-display);
    font-weight: 600;
    letter-spacing: var(--tracking-tight);
    line-height: 1.12;
    color: var(--text-1);
  }
  .page-lede {
    margin: var(--optical-6) 0 0;
    font-size: var(--text-13);
    line-height: 1.65;
    color: var(--text-2);
    max-width: 52ch;
  }

  /* ---- 搜索框 ----
     原来 search-input 是 16px, 比它承载的列表项(14px)还大,
     输入框在页面里抢眼睛。降到 14px, 并把右侧计数做成等宽小字。 */
  .search-box {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: 0 var(--space-4);
    height: var(--input-h);
    background: var(--input-bg);
    border: 1px solid var(--input-border);
    border-radius: var(--input-radius);
    margin-bottom: var(--space-2);
    transition: border-color var(--transition), box-shadow var(--transition);
  }
  .search-box:focus-within {
    border-color: var(--input-focus-border);
    box-shadow: var(--focus-ring);
  }
  .search-input {
    flex: 1;
    min-width: 0;
    border: none;
    background: transparent;
    color: var(--input-text);
    font-size: var(--text-sm);
    outline: none;
  }
  .search-input::placeholder {
    color: var(--input-placeholder);
  }
  .search-count {
    flex: none;
    font-size: var(--text-xs);
    color: var(--text-3);
    padding-left: var(--space-2);
    border-left: 1px solid var(--border);
  }

  /* ---- 列表: 细线分隔的密集行, 不用卡片 ----
     hover 从「整行变色块」改成「左侧 2px 冷蓝短竖线」:
     变色块在暖纸底上是一片糊掉的灰, 竖线才是这套设计语言里
     已经用惯了的「指向」符号 (侧栏选中也是它)。 */
  .list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0;
    background: transparent;
    border: none;
    border-top: 1px solid var(--border);
    border-radius: 0;
  }
  .roster-row {
    position: relative;
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-3) 0 var(--space-3) var(--space-3);
    border-radius: 0;
    border-bottom: 1px solid var(--border);
    transition: background var(--transition), padding-left var(--transition);
  }
  .roster-row::before {
    content: '';
    position: absolute;
    left: 0;
    top: 50%;
    width: 2px;
    height: 0;
    background: var(--accent);
    transform: translateY(-50%);
    transition: height var(--transition-slow);
  }
  .roster-row:hover {
    background: var(--row-hover);
  }
  .roster-row:hover::before {
    height: 60%;
  }
  .roster-row:active {
    background: var(--row-active);
  }
  .roster-main {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: var(--space-3);
    border: none;
    background: transparent;
    padding: 0;
    cursor: pointer;
    text-align: left;
    color: var(--text-1);
  }
  /* 每行三段: 名字 / 一行摘要 / 最多三个性格标签。
     原来一行只有名字, 40px 行高里 36px 是头像, 名字右侧全是空白 ——
     名单看起来像没加载完。有摘要 + 标签之后这一行才承载「她是谁」。 */
  .roster-body {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: var(--optical-3);
  }
  .roster-name {
    font-size: var(--text-sm);
    font-weight: 500;
    letter-spacing: var(--tracking-tight);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .roster-meta {
    font-size: var(--text-xs);
    line-height: 1.45;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .roster-meta-empty { color: var(--text-3); opacity: 0.75; font-style: normal; }
  .roster-tags {
    display: flex;
    flex-wrap: wrap;
    gap: var(--optical-5);
    margin-top: var(--hair);
  }
  .roster-tag {
    font-size: var(--text-2xs);
    line-height: 1.5;
    letter-spacing: var(--tracking-wide);
    color: var(--text-2);
    background: var(--surface-2);
    border-radius: var(--radius-xs);
    padding: 0 var(--optical-5);
  }
  /* 「去聊天」按钮平时隐去, hover 行时才出现 —— 一列灰框按钮
     会让名单看起来像表格, 而这里应该是「人」。 */
  .roster-go {
    flex: none;
    opacity: 0;
    transition: opacity var(--transition), color var(--transition),
      border-color var(--transition);
  }
  .roster-row:hover .roster-go,
  .roster-go:focus-visible {
    opacity: 1;
  }
  .roster-go:hover {
    color: var(--accent);
    border-color: var(--accent-line);
  }

  /* 名单收尾行 —— 顺带把「共 N 位角色 / 再建一个」放在这里,
     让两三行名单下面的空白有一个可操作的落点。 */
  .list-foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-3) 0 0 var(--space-3);
  }
  .list-foot-count {
    font-size: var(--text-xs);
    color: var(--text-3);
    letter-spacing: var(--tracking-wide);
  }

  /* ---- 详情区 ----
     详情页原来有三层盒子叠着: hero 灰卡 + 若干 PersonaCard 白卡 + 折叠组卡片,
     每层都是「1px 线 + 圆角 + 内边距」, 一屏看下去就是盒套盒。
     统一成一套分区语法: 不用盒子, 用一道更重的横线切段, 段标题降成 11px 微标签。 */
  .detail-head {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding-bottom: var(--space-3);
    margin-bottom: var(--space-5);
    border-bottom: 1px solid var(--border-strong);
  }
  /* 「角色详情」降级成微标签: 它只是个位置提示, 真正的主角是下面的名字。
     原来它 18px/700, 和名字 22px/700 抢同一档视觉权重。 */
  .detail-title {
    font-size: var(--text-2xs);
    font-weight: 500;
    letter-spacing: var(--tracking-wider);
    color: var(--text-3);
  }
  .detail-spacer {
    flex: 1;
  }
  .btn.danger {
    color: var(--error);
  }
  .btn.danger:hover {
    background: color-mix(in srgb, var(--error) 12%, transparent);
  }

  /* ---- 身份区: 不再是灰盒子, 而是一个「档案抬头」----
     去掉背景/边框/圆角, 只用一道底线收尾, 头像和名字直接落在纸面上。
     这样详情页的层级是: 返回条 → 身份(最大) → 各字段分区(细线隔开)。
     .card 已收归 .settings-main 作用域 (见 settings-base.css 头部说明)。 */
  .hero-card {
    display: flex;
    align-items: center;
    gap: var(--space-4);
    padding: 0 0 var(--space-5);
    margin-bottom: var(--space-5);
    background: transparent;
    border: none;
    border-bottom: 1px solid var(--border-strong);
    border-radius: 0;
  }
  .hero-main {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: var(--space-4);
  }
  .hero-avatar {
    position: relative;
    flex: none;
  }
  .avatar-edit {
    position: absolute;
    right: -4px;
    bottom: -4px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: var(--radius-xs);
    border: 2px solid var(--surface);
    background: var(--accent);
    color: var(--on-accent);
    cursor: pointer;
    transition: background var(--transition), transform var(--transition);
  }
  .avatar-edit:hover {
    background: var(--accent-strong);
  }
  .hero-info {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .hero-name-row {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }
  /* 名字是这一页唯一的「大字号」: 26px/600 与页面主标题同档,
     输入态用底部细线, 静态时几乎是纯文本 —— 不再像个表单框。 */
  .hero-name-input {
    flex: 1;
    min-width: 0;
    border: none;
    border-bottom: 1px solid transparent;
    background: transparent;
    color: var(--text-1);
    font-size: var(--text-display);
    font-weight: 600;
    letter-spacing: var(--tracking-tight);
    line-height: 1.15;
    padding: 0 0 var(--optical-2);
    transition: border-color var(--transition);
  }
  .hero-name-input:hover {
    border-bottom-color: var(--border-strong);
  }
  .hero-name-input:focus-visible {
    outline: none;
    border-bottom-color: var(--input-focus-border);
  }
  .hero-name-input.dirty {
    border-bottom-color: var(--accent);
  }
  .hero-name-input::placeholder {
    color: var(--input-placeholder);
    font-weight: 500;
  }
  .name-save {
    flex: none;
  }
  .hero-sub {
    font-size: var(--text-2xs);
    letter-spacing: var(--tracking-wide);
    color: var(--text-3);
  }
  .avatar-actions {
    display: flex;
    gap: var(--space-2);
    flex-wrap: wrap;
    align-items: center;
  }
  .go-chat {
    flex: none;
  }
  /* 主操作给足横向留白, 让它比「保存」这一类的次级主按钮更有分量 */
  .btn.go-chat {
    height: var(--btn-h-md);
    padding: 0 var(--space-5);
  }

  /* ---- 精简人设卡区 ----
     卡片之间不再用 gap 分隔 (每张卡自己带一道顶线), 所以 gap 归零,
     由卡片自身的 border-top 完成分区, 避免「线 + 留白 + 留白」的双重间距。 */
  .lean-section {
    display: flex;
    flex-direction: column;
    gap: 0;
    margin-bottom: var(--space-2);
  }

  /* ---- 字段 ---- */
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .field-label {
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--text-2);
  }
  .field-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-2);
  }
  /* 计数: 3/3 时变成强调色, 让"已经满了"在点之前就能看见 */
  .field-count {
    font-size: var(--text-2xs);
    font-variant-numeric: tabular-nums;
    letter-spacing: var(--tracking-wide);
    color: var(--text-3);
  }

  /* ---- 性格标签 ----
     原来这些 chip 没有任何样式规则(类名写了但 CSS 不存在), 渲染成
     浏览器默认按钮: 灰底、1px 凸边、系统字体。在一屏暖纸底 + 细线
     的界面里, 那是最刺眼的一块"外来物"。
     新样式: 细描边胶囊, 选中时冷蓝浅底 + 冷蓝文字 + 冷蓝描边,
     形状与颜色两个通道同时表达"选中"。 */
  .tag-hint {
    margin: 0;
    font-size: var(--text-xs);
    line-height: 1.55;
    color: var(--text-3);
  }
  .tag-cloud {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin-top: var(--space-1);
  }
  .tag-chip {
    height: 28px;
    padding: 0 var(--optical-11);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-full);
    background: transparent;
    color: var(--text-2);
    font-family: inherit;
    font-size: var(--text-xs);
    letter-spacing: 0.01em;
    cursor: pointer;
    transition: background var(--transition), color var(--transition),
      border-color var(--transition), transform var(--transition);
  }
  .tag-chip:hover {
    background: var(--accent-wash);
    border-color: var(--accent-line);
    color: var(--accent);
  }
  .tag-chip:active { transform: scale(0.96); }
  .tag-chip.on {
    background: var(--accent-soft);
    border-color: var(--accent);
    color: var(--accent);
    font-weight: 500;
  }
  /* 已选满时未选中的项降权: 仍然可点(会提示), 但不再抢视线 */
  .tag-chip.is-full {
    opacity: 0.42;
    border-style: dashed;
  }
  .tag-chip.is-full:hover { opacity: 0.7; }
  @media (prefers-reduced-motion: reduce) {
    .tag-chip { transition: none; }
    .tag-chip:active { transform: none; }
  }

  /* ---- 草稿预览区 ----
     用左侧一道 2px 冷蓝竖线把它和上面的"选择区"分开: 上面是"挑",
     下面是"结果", 两种心理动作不该长得一样。
     底色用 --surface-inset (凹槽), 表达"这里是内容, 可以改"。 */
  .draft-block {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3) 0 var(--space-3) var(--space-3);
    border-left: 2px solid var(--accent-line);
  }
  .draft-reset {
    border: none;
    background: transparent;
    padding: 0;
    font-family: inherit;
    font-size: var(--text-2xs);
    letter-spacing: 0.02em;
    color: var(--accent);
    cursor: pointer;
    text-decoration: underline;
    text-underline-offset: 2px;
    text-decoration-thickness: 1px;
    text-decoration-color: var(--accent-line);
  }
  .draft-reset:hover { text-decoration-color: var(--accent); }
  .draft-row {
    display: flex;
    flex-direction: column;
    gap: var(--optical-5);
  }
  .draft-key {
    font-size: var(--text-2xs);
    font-weight: 600;
    letter-spacing: var(--tracking-wide);
    color: var(--text-3);
  }
  .draft-input {
    width: 100%;
    padding: var(--space-2) var(--space-3);
    background: var(--surface-inset);
    border: 1px solid var(--border);
    border-radius: var(--input-radius);
    color: var(--text-1);
    font-family: inherit;
    font-size: var(--text-sm);
    line-height: var(--leading-snug);
    resize: vertical;
    /* 自动增高(action)会写 inline height, 这里给个下限防止空内容塌成一条 */
    min-height: 3.2em;
    overflow-y: hidden;
    transition: border-color var(--transition), box-shadow var(--transition);
  }
  .draft-input:focus-visible {
    outline: none;
    border-color: var(--input-focus-border);
    box-shadow: var(--focus-ring);
  }
  .draft-input::placeholder { color: var(--input-placeholder); }

  /* ---- 空状态 ----
     原来只是「一段左对齐的灰字」, 在整片白底里没有被识别为一个
     状态, 看起来像页面没加载完。加一道 2px 左侧竖线做锚点:
     视线有落点, 同时竖线天然把「空状态」和「列表内容」区分开,
     不需要额外卡片或虚线框。 */
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    text-align: left;
    gap: var(--space-2);
    padding: var(--space-5) 0 var(--space-5) var(--space-4);
    border-left: 2px solid var(--border-strong);
  }
  .empty-icon {
    display: inline-flex;
    color: var(--empty-icon);
    margin-bottom: var(--space-1);
  }
  .empty-title {
    margin: 0;
    font-size: var(--text-lg);
    font-weight: 600;
    letter-spacing: var(--tracking-tight);
    color: var(--text-1);
    line-height: 1.3;
  }
  .empty-desc {
    margin: 0;
    font-size: var(--text-13);
    line-height: 1.72;
    color: var(--text-2);
    max-width: 46ch;
  }
  .empty-btn {
    margin-top: var(--space-2);
  }

  /* ---- 通用按钮 (对齐组件 token) ----
     字重从 600 降到 500: 中文在 14px 下 600 已经是伪粗体,
     一排按钮全粗会显得用力过猛; 500 + 略收字距更贴这套「安静的纸面」。 */
  .btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    border-radius: var(--btn-radius);
    font-size: var(--text-sm);
    font-weight: 500;
    letter-spacing: var(--tracking-tight);
    cursor: pointer;
    transition: background var(--transition), border-color var(--transition), transform var(--transition), box-shadow var(--transition);
    border: 1px solid transparent;
    white-space: nowrap;
  }
  .btn:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
  .btn:active:not(:disabled) { transform: scale(0.97); }
  .btn-primary {
    height: var(--btn-h-md);
    padding: 0 var(--space-4);
    background: var(--btn-primary-bg);
    color: var(--btn-primary-text);
    box-shadow: var(--btn-primary-shadow);
  }
  .btn-primary:hover:not(:disabled) { background: var(--btn-primary-hover); }
  .btn-outline {
    height: var(--btn-h-md);
    padding: 0 var(--space-4);
    background: var(--btn-outline-bg);
    border-color: var(--btn-outline-border);
    color: var(--btn-outline-text);
  }
  .btn-outline:hover:not(:disabled) { background: var(--btn-outline-hover); }
  .btn-ghost {
    height: var(--btn-h-md);
    padding: 0 var(--space-3);
    background: transparent;
    color: var(--text-2);
  }
  .btn-ghost:hover:not(:disabled) { background: var(--row-hover); }
  .btn-sm { height: var(--btn-h-sm); padding: 0 var(--space-3); font-size: var(--text-xs); }

  .icon-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: var(--btn-h-md);
    height: var(--btn-h-md);
    border-radius: var(--radius-xs);
    border: 1px solid var(--btn-outline-border);
    background: var(--btn-outline-bg);
    color: var(--btn-outline-text);
    cursor: pointer;
    transition: background var(--transition), color var(--transition), transform var(--transition);
  }
  .icon-btn:hover { background: var(--btn-outline-hover); color: var(--accent); }
  .icon-btn:active { transform: scale(0.94); }

  /* ---- 弹窗 ----
     「新建角色」是低频但高注意力的任务: 用户在这里填 5~8 个字段,
     需要完整专注。所以用 glass-3 (模态档) 而不是玻璃-1。
     z-index 全部走 --z-* 阶梯 —— 原来写死的 50 比 AppDialog 的 100 低,
     于是"新建角色"开着时触发全局 confirm 会被压在下面, 用户看不到。 */
  .overlay {
    position: fixed;
    inset: 0;
    z-index: var(--z-modal-scrim);
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--glass-0);
    padding: var(--space-4);
  }
  @supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
    .overlay {
      -webkit-backdrop-filter: blur(var(--glass-blur-0));
      backdrop-filter: blur(var(--glass-blur-0));
    }
  }
  .modal {
    width: 100%;
    max-width: 460px;
    max-height: calc(100dvh - var(--space-6));
    overflow-y: auto;
    padding: var(--space-5);
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    background: var(--surface);
    border: 1px solid var(--glass-border-2);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-4);
  }
  @supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
    .modal {
      background: var(--glass-3);
      -webkit-backdrop-filter: blur(var(--glass-blur-3)) saturate(var(--glass-sat-3));
      backdrop-filter: blur(var(--glass-blur-3)) saturate(var(--glass-sat-3));
      box-shadow: var(--glass-highlight), var(--shadow-4);
    }
  }
  @media (prefers-reduced-transparency: reduce) {
    .modal {
      background: var(--surface);
      -webkit-backdrop-filter: none;
      backdrop-filter: none;
    }
  }
  .modal-title {
    margin: 0 0 var(--space-1);
    font-size: var(--text-lg);
    font-weight: 700;
    color: var(--text-1);
  }
  .field-plain {
    width: 100%;
    padding: var(--space-2) var(--space-3);
    background: var(--input-bg);
    border: 1px solid var(--input-border);
    border-radius: var(--input-radius);
    color: var(--input-text);
    font-size: var(--text-base);
    line-height: var(--leading-snug);
  }
  .field-plain:focus-visible {
    outline: none;
    border-color: var(--input-focus-border);
    box-shadow: var(--focus-ring);
  }
  .field-plain::placeholder {
    color: var(--input-placeholder);
  }
  .modal-actions {
    display: flex;
    justify-content: flex-end;
    gap: var(--space-2);
    margin-top: var(--space-2);
  }

  /* 桌面区: 身份区给多一点底部留白, 但不回到盒子内边距 */
  @media (min-width: 768px) {
    .hero-card {
      padding: 0 0 var(--space-6);
      margin-bottom: var(--space-6);
    }
  }
</style>
