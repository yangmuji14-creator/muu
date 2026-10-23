<script>
  // SettingsModel.svelte — 模型设置
  // 两个区块：模型角色（勾选「能看图」+ 分配语言/图片/语音） → 服务商（加 Key）
  // 设计原则（对齐 PawzoChat）：
  //   · 模型能否看图由用户勾选（models.<key>.multimodal），不按模型名字猜
  //   · 语言模型勾了「能看图」→ 图片直接发给它（一次调用）
  //   · 没勾 → 备用路线：图片先由「图片识别」模型转文字描述再交给语言模型（默认不用）
  //   · 同一信息只出现一次，没有第二处模型配置
  import SettingsShell from './SettingsShell.svelte';
  import EmptyState from './EmptyState.svelte';
  import SamplingPresets from './SamplingPresets.svelte';
  import UrlPreview from './UrlPreview.svelte';
  import './settings-base.css';
  import { I } from './icons.js';
  import { modelApi, bootstrapApi } from '../../lib/settingsApi.js';
  import { confirmDialog } from '../../lib/dialog.svelte.js';

  let { notify, onback } = $props();

  let model = $state(null);
  let providers = $state([]);
  let loading = $state(true);
  let saving = $state(false);

  let pf = $state({ key: '', provider: '', model_name: '', base_url: '', api_key: '', multimodal: false, temperature: null, max_tokens: null, presence_penalty: null, frequency_penalty: null });

  // ---- 服务商预设（卡片内联展开）----
  let presets = $state([]);          // /api/bootstrap/providers
  let presetsLoading = $state(true);
  let expandedPreset = $state(null); // 展开中的预设 key；'custom' = 自定义 OpenAI 兼容

  // ---- 模型角色 ----
  let roles = $state({
    chat: null, vision: null, tts: null,
    pool: [], image_chain: '',
  });
  let pullKey = $state('');     // 拉取来源提供商
  let pulled = $state([]);      // 拉取到的可用模型 id 列表
  let pulling = $state(false);
  let pullMsg = $state('');
  let assigning = $state('');   // 正在分配的操作（防连点）
  let checking = $state('');    // 正在切换勾选的条目

  // 预设服务商 catalog key 集合 (来自 /api/bootstrap/providers)
  let catalogKeys = $derived(presets.map((p) => p.key).filter(Boolean));
  let isPreset = $derived(catalogKeys.includes(pf.key));
  // 卡片内「拉取模型列表」
  let formPull = $state([]);
  let formPulling = $state(false);
  let formPullMsg = $state('');
  // 连接与测试反馈
  let testState = $state('idle'); // idle | testing | ok | fail
  let testMsg = $state('');

  $effect(() => {
    let alive = true;
    load();
    loadRoles();
    loadPresets();
    return () => (alive = false);
    async function loadPresets() {
      presetsLoading = true;
      try {
        const r = await bootstrapApi.providers();
        if (alive) {
          presets = Array.isArray(r.data?.providers) ? r.data.providers
            : Array.isArray(r.data) ? r.data : [];
        }
      } catch {
        if (alive) presets = [];
      }
      if (alive) presetsLoading = false;
    }
    async function load() {
      loading = true;
      try {
        const r = await modelApi.get();
        if (!alive) return;
        if (r.ok) {
          model = r.data || {};
          const avail = Array.isArray(r.data?.available) ? r.data.available : [];
          const provs = Array.isArray(r.data?.providers) ? r.data.providers : [];
          if (provs.length) {
            // 优先用 providers：带 base_url / multimodal，能直接渲染「已添加」列表
            providers = provs;
            model.available = provs.map((a) => a.key);
          } else if (avail.length && typeof avail[0] === 'object') {
            providers = avail;
            model.available = avail.map((a) => a.key ?? a.model_name ?? a.provider);
          } else {
            providers = avail.map((k) => ({ key: k, provider: k, model_name: k, base_url: '' }));
            model.available = avail;
          }
        } else notify(errMsg(r, '加载模型配置失败'), 'error');
      } catch (e) { notify(errMsg(e, '加载模型配置失败'), 'error'); }
      pullKey = pullKey || model?.current || providers[0]?.key || '';
      if (alive) loading = false;
    }
  });

  async function loadRoles() {
    try {
      const r = await modelApi.roles();
      if (r.ok && r.data) {
        const d = { ...r.data };
        delete d.video; // 预留槽位，前端不露出（后端 /api/model/role 仍支持）
        roles = { chat: null, vision: null, tts: null, pool: [], image_chain: '', ...d };
      }
    } catch { /* ignore */ }
  }

  // 用已保存的提供商密钥拉取可用模型（多提供商时用下拉选择来源）
  async function pullModels() {
    const key = pullKey || roles?.chat?.key || providers[0]?.key;
    if (!key) {
      notify('请先在下方「选择服务商」添加一家提供商（只需填 API Key）', 'error');
      return;
    }
    pulling = true;
    pullMsg = '';
    pulled = [];
    try {
      const r = await modelApi.discoverByKey(key);
      if (r.ok && r.data?.ok) {
        pulled = Array.isArray(r.data.models) ? r.data.models : [];
        pullMsg = r.data.message || `已找到 ${pulled.length} 个模型`;
      } else {
        const reason = errMsg(r, '拉取失败');
        const spec = presets.find((p) => p.key === key);
        if (spec?.default_model) {
          pulled = [spec.default_model];
          pullMsg = `${reason}，已显示该厂商默认模型`;
        } else {
          notify(reason, 'error');
        }
      }
    } catch (e) {
      notify(errMsg(e, '拉取模型失败'), 'error');
    } finally {
      pulling = false;
    }
  }

  // 展开/收起一个预设服务商卡片（就地填 Key，不跳转）
  function togglePreset(p) {
    if (expandedPreset === p.key) { expandedPreset = null; return; }
    applyPreset(p);
    expandedPreset = p.key;
  }
  function toggleCustom() {
    if (expandedPreset === 'custom') { expandedPreset = null; return; }
    resetPf();
    expandedPreset = 'custom';
  }
  function isAdded(key) {
    return providers.some((x) => x.key === key);
  }

  // 新增提供商表单：用表单里的 base_url + api_key 拉取模型列表
  async function pullFormModels() {
    if (!pf.base_url) {
      notify('请先填写 Base URL', 'error');
      return;
    }
    formPulling = true;
    formPullMsg = '';
    formPull = [];
    try {
      const r = await modelApi.discover(pf.base_url, pf.api_key);
      if (r.ok && r.data?.ok) {
        formPull = Array.isArray(r.data.models) ? r.data.models : [];
        formPullMsg = formPull.length
          ? `已找到 ${formPull.length} 个模型，点选一个`
          : '未找到可用模型，可手动输入模型名';
      } else {
        formPullMsg = errMsg(r, '拉取失败，可手动输入模型名');
      }
    } catch (e) {
      formPullMsg = errMsg(e, '拉取失败，可手动输入模型名');
    } finally {
      formPulling = false;
    }
  }

  // 分配角色。再点一次已分配的按钮 = 取消（语言模型除外）。
  // key = 提供商条目，后端据此写对条目（跨厂商分配不会写错）。
  async function assignRole(role, modelName, key = '') {
    const current = roles?.[role]?.model_name || '';
    if (current === modelName) {
      if (role === 'chat') {
        notify('语言模型必须保留一个 —— 点击其它模型的「语言」即可切换', 'error');
        return;
      }
      assigning = `${role}:clear`;
      try {
        const r = await modelApi.setRole(role, '', key);
        if (r.ok) {
          notify(r.data?.message || '已取消分配', 'success');
          await loadRoles();
        } else notify(errMsg(r, '取消失败'), 'error');
      } finally {
        assigning = '';
      }
      return;
    }
    assigning = `${role}:${modelName}`;
    try {
      const r = await modelApi.setRole(role, modelName, key);
      if (r.ok) {
        const label =
          role === 'chat' ? '语言模型'
          : role === 'vision' ? '备用识别模型'
          : '语音合成模型';
        notify(r.data?.message || `${label} 已设为 ${modelName}`, 'success');
        if (r.data?.image_chain) roles.image_chain = r.data.image_chain;
        await loadRoles();
      } else {
        notify(errMsg(r, '分配失败'), 'error');
      }
    } finally {
      assigning = '';
    }
  }

  // 勾选/取消「能看图」—— 用户显式声明该模型支持图片输入（不按名字猜）
  async function toggleVision(entry, checked) {
    checking = entry.key;
    try {
      const r = await modelApi.setMultimodal(entry.key, checked ? 'yes' : 'no');
      if (r.ok) {
        roles.pool = roles.pool.map((p) =>
          p.key === entry.key ? { ...p, multimodal: checked } : p);
        if (roles.chat?.key === entry.key) roles.chat = { ...roles.chat, multimodal: checked };
        if (r.data?.image_chain) roles.image_chain = r.data.image_chain;
      } else {
        notify(errMsg(r, '设置失败'), 'error');
      }
    } finally {
      checking = '';
    }
  }

  function errMsg(err, fallback) {
    const m = err?.data?.error || err?.data?.message || err?.data?.detail || err?.data;
    if (typeof m === 'string' && m) return m;
    return fallback || (err?.status ? `请求失败（HTTP ${err.status}）` : String(err?.message ?? err));
  }

  async function submitProvider(e) {
    e.preventDefault();
    if (!pf.model_name) {
      notify(isPreset ? '请先点「拉取模型列表」并点选一个模型' : '请填写或点选一个模型', 'error');
      return;
    }
    saving = true;
    try {
      const body = {};
      for (const [k, v] of Object.entries(pf)) {
        if (v === '' || v === null || v === undefined || v === false) continue;
        if (k === 'multimodal') { body.multimodal = 'yes'; continue; }
        body[k] = v;
      }
      const r = await modelApi.addProvider(body);
      if (r.ok) {
        notify(r.data?.restart_required ? '提供商已保存（重启后生效）' : '提供商已添加，立即可用', 'success');
        expandedPreset = null;
        await reloadModels();
        await loadRoles();
        // 自动用新提供商的密钥拉取模型列表，供上方直接点选分配
        pullKey = pf.key;
        pulling = true;
        try {
          const rr = await modelApi.discoverByKey(pf.key);
          if (rr.ok && rr.data?.ok) {
            pulled = Array.isArray(rr.data.models) ? rr.data.models : [];
            pullMsg = pulled.length
              ? `已找到 ${pulled.length} 个模型 —— 在上方点「语言 / 图片 / 语音」分配即可`
              : '';
          }
        } catch { /* ignore */ }
        pulling = false;
      } else notify(errMsg(r, '添加失败'), 'error');
    } finally { saving = false; }
  }

  async function removeProvider(key) {
    const ok = await confirmDialog(`删除提供商 ${key}？`, { title: '删除服务商', danger: true });
    if (!ok) return;
    saving = true;
    try {
      const r = await modelApi.remove(key);
      if (r.ok) {
        notify('已删除', 'success');
        providers = providers.filter((p) => p.key !== key);
        if (model?.available) model.available = model.available.filter((k) => k !== key);
        await loadRoles();
      } else notify(errMsg(r, '删除失败'), 'error');
    } finally { saving = false; }
  }

  // 模型用途判断：tts/asr 类不能当语言或图片模型
  function isTtsModel(name) {
    return /tts|voiceclone|voicedesign|asr|speech/i.test(String(name || ''));
  }

  async function reloadModels() {
    loading = true;
    model = null;
    providers = [];
    try {
      const r = await modelApi.get();
      if (r.ok) {
        model = r.data || {};
        const avail = Array.isArray(r.data?.available) ? r.data.available : [];
        const provs = Array.isArray(r.data?.providers) ? r.data.providers : [];
        if (provs.length) {
          providers = provs;
          model.available = provs.map((a) => a.key);
        } else if (avail.length && typeof avail[0] === 'object') {
          providers = avail;
          model.available = avail.map((a) => a.key ?? a.model_name ?? a.provider);
        } else {
          providers = avail.map((k) => ({ key: k, provider: k, model_name: k, base_url: '' }));
          model.available = avail;
        }
      }
    } catch { /* ignore */ }
    pullKey = pullKey || model?.current || providers[0]?.key || '';
    loading = false;
  }

  function resetPf() {
    pf = { key: '', provider: '', model_name: '', base_url: '', api_key: '', multimodal: false, temperature: null, max_tokens: null, presence_penalty: null, frequency_penalty: null };
    formPull = [];
    formPullMsg = '';
    testState = 'idle';
    testMsg = '';
  }

  function applyPreset(p) {
    pf = {
      key: p.key ?? '',
      provider: p.provider ?? p.key ?? '',
      model_name: p.default_model ?? '',
      base_url: p.base_url ?? '',
      api_key: '',
      multimodal: false,
      temperature: null,
      max_tokens: null,
      presence_penalty: null,
      frequency_penalty: null,
    };
    formPull = [];
    formPullMsg = '';
    testState = 'idle';
    testMsg = '';
  }

  // 采样预设: 仅当 values 非空(命中命名档位)才覆盖手填值 自定义(null)不动表单
  function applySampling(values) {
    if (!values) return;
    pf = { ...pf, ...values };
  }

  async function testConnection() {
    if (!pf.provider) {
      testState = 'fail';
      testMsg = '请先填写 Provider（或从预设服务商中选择）';
      return;
    }
    if (!catalogKeys.includes(pf.key)) {
      testState = 'fail';
      testMsg = '该服务商暂不支持在线测试';
      return;
    }
    testState = 'testing';
    testMsg = '';
    try {
      const body = { provider: pf.provider };
      if (pf.base_url) body.base_url = pf.base_url;
      if (pf.api_key) body.api_key = pf.api_key;
      if (pf.model_name) body.model_name = pf.model_name;
      const r = await bootstrapApi.test(body);
      if (r.ok) {
        const ok = r.data?.ok !== false;
        testState = ok ? 'ok' : 'fail';
        testMsg = ok
          ? (r.data?.message && typeof r.data.message === 'string' ? r.data.message : '连接成功')
          : (typeof r.data?.message === 'string' ? r.data.message : '连接失败');
      } else {
        const m = errMsg(r, '连接失败');
        testState = 'fail';
        testMsg = m.includes('暂不支持') ? '该服务商暂不支持在线测试' : m;
      }
    } catch (e) {
      testState = 'fail';
      testMsg = errMsg(e, '连接失败');
    }
  }
</script>

<SettingsShell title="模型设置" desc="加厂商 → 拉模型 → 分配角色" {onback}>
  {#if loading}
    <div class="card card-pad">
      <EmptyState icon="cpu" title="正在加载模型配置…" compact />
    </div>
  {:else}
    <!-- ============ ① 模型角色 ============ -->
    <section class="card card-pad">
      <div class="section-head">
        <h4>模型角色</h4>
        <span class="head-sub">谁聊天、谁看图、谁发语音</span>
      </div>

      <!-- 识别流程：何时直连 / 何时走备用，一句话讲清 -->
      <div class="mm-chain">
        <span class="micro-label">识别流程</span>
        <p class="mm-chain-text">{roles.image_chain || '—'}</p>
      </div>

      <!-- 已添加的模型（一个条目 = 一个模型槽位） -->
      {#if roles.pool.length}
        <div class="entry-list">
          {#each roles.pool as entry (entry.key)}
            <div class="entry-row">
              <div class="entry-head">
                <span class="entry-name mono">
                  {entry.model_name || entry.key}
                  <span class="entry-key">{entry.key}</span>
                </span>
                {#if entry.is_current}<span class="badge ok">语言</span>{/if}
                {#if roles.vision?.model_name === entry.model_name && !entry.is_current}<span class="badge">识别</span>{/if}
              </div>
              <div class="entry-controls">
                <label class="check-line" title="勾选 = 该模型是多模态：看图、听语音这类识别都直接发给它（快）">
                  <input
                    type="checkbox"
                    checked={entry.multimodal}
                    disabled={!!checking}
                    onchange={(e) => toggleVision(entry, e.currentTarget.checked)}
                  />
                  <span>多模态</span>
                </label>
                <span class="ctl-sep"></span>
                <button class="mini-btn" type="button" disabled={!!assigning || isTtsModel(entry.model_name)}
                  onclick={() => assignRole('chat', entry.model_name, entry.key)}
                  title={entry.is_current ? '当前语言模型' : '设为语言模型'}
                  class:on={entry.is_current}>语言</button>
                <button class="mini-btn" type="button" disabled={!!assigning || isTtsModel(entry.model_name)}
                  onclick={() => assignRole('vision', entry.model_name, entry.key)}
                  title={roles.vision?.model_name === entry.model_name ? '再次点击取消（备用识别）' : '设为备用识别模型（图片/语音转文字）'}
                  class:on={roles.vision?.model_name === entry.model_name}>识别</button>
                <button class="mini-btn" type="button" disabled={!!assigning || !isTtsModel(entry.model_name)}
                  onclick={() => assignRole('tts', entry.model_name, entry.key)}
                  title={roles.tts?.model_name === entry.model_name ? '再次点击取消' : '只有语音合成类模型（tts）可分配'}
                  class:on={roles.tts?.model_name === entry.model_name}>语音</button>
              </div>
            </div>
          {/each}
        </div>
        <p class="hint">
          <strong>多模态</strong>：勾了 → 图片（和之后的语音）直接发给语言模型识别（一次调用，备用识别不启用）；
          没勾 → 需把另一个模型设为「识别」（备用：图片先转文字描述再交给语言模型）。
          语音合成是生成型模型，用「语音」单独设。
        </p>
      {:else}
        <p class="hint">还没有模型 —— 在下方「选择服务商」点一张卡片，填上 API Key 保存即可。</p>
      {/if}

      <!-- 拉取：切换条目用哪个具体模型名 -->
      {#if providers.length}
        <div class="pull-bar">
          {#if providers.length > 1}
            <select class="input pull-provider" bind:value={pullKey} aria-label="选择拉取来源提供商">
              {#each providers as p (p.key)}
                <option value={p.key}>{p.key}</option>
              {/each}
            </select>
          {/if}
          <button class="btn-outline" type="button" disabled={pulling} onclick={pullModels}>
            {pulling ? '正在拉取…' : '拉取可用模型'}
          </button>
          {#if pullMsg}<span class="pull-msg">{pullMsg}</span>{/if}
        </div>
        {#if pulled.length}
          <div class="model-pool">
            {#each pulled as m (m)}
              <div class="pool-row">
                <span class="pool-name mono">{m}</span>
                <div class="pool-actions">
                  <button class="mini-btn" type="button" disabled={!!assigning || isTtsModel(m)}
                    onclick={() => assignRole('chat', m, pullKey)}
                    title="把 {pullKey} 条目切到此模型，并设为语言模型"
                    class:on={roles.chat?.model_name === m && roles.chat?.key === pullKey}>语言</button>
                  <button class="mini-btn" type="button" disabled={!!assigning || isTtsModel(m)}
                    onclick={() => assignRole('vision', m, pullKey)}
                    title={roles.vision?.model_name === m ? '再次点击取消' : '设为备用识别模型（图片/语音转文字）'}
                    class:on={roles.vision?.model_name === m}>识别</button>
                  <button class="mini-btn" type="button" disabled={!!assigning || !isTtsModel(m)}
                    onclick={() => assignRole('tts', m, pullKey)}
                    title={roles.tts?.model_name === m ? '再次点击取消' : '只有语音类模型（tts）可分配'}
                    class:on={roles.tts?.model_name === m}>语音</button>
                </div>
              </div>
            {/each}
          </div>
          <p class="hint">拉取的是厂商的模型名列表 —— 点「语言」= 把该厂商条目切到此模型；点「识别」= 设为备用识别。</p>
        {/if}
      {/if}
    </section>

    {#if !model?.available?.length}
      <section class="card card-pad">
        <div class="no-model">
          <span class="micro-label">还没有可用的模型</span>
          <p class="no-model-desc">
            当前没有任何模型能回复消息 —— 最常见的原因是 API Key 没配对。
            从下面「选择服务商」里挑一家，填上 Key 就能开始。
          </p>
        </div>
      </section>
    {/if}

    <!-- ============ ② 选择服务商 ============ -->
    <section class="card card-pad" id="preset-section">
      <div class="section-head">
        <h4>选择服务商</h4>
        <span class="head-sub">点卡片展开，填 API Key 即可</span>
      </div>

      {#if presetsLoading}
        <div class="preset-grid">
          {#each [1, 2, 3, 4] as _}
            <div class="preset-card skeleton" style="height: 88px;"></div>
          {/each}
        </div>
      {:else}
        <div class="preset-grid">
          {#each presets as p (p.key)}
            <div class="preset-item">
              <button class="preset-card" class:on={expandedPreset === p.key} type="button" onclick={() => togglePreset(p)}>
                <span class="pc-head">
                  <span class="pc-label">{p.label}</span>
                  <span class="pc-key">{p.key}</span>
                </span>
                {#if p.description}<span class="pc-desc">{p.description}</span>{/if}
                {#if isAdded(p.key)}
                  <span class="pc-meta"><span class="badge ok">已添加</span></span>
                {/if}
              </button>

              {#if expandedPreset === p.key}
                <form class="inline-form" onsubmit={submitProvider}>
                  <label class="field"><span>API Key</span><input class="input" type="password" bind:value={pf.api_key} placeholder="粘贴 {p.label} 的 API Key" required /></label>
                  <div class="pull-bar">
                    <button class="btn-outline sm" type="button" disabled={formPulling || !pf.api_key} onclick={pullFormModels}>
                      {formPulling ? '正在拉取…' : '拉取模型列表'}
                    </button>
                    <button class="btn-outline sm" type="button" onclick={() => testConnection()} disabled={saving || testState === 'testing'}>
                      {testState === 'testing' ? '测试中…' : '测试连接'}
                    </button>
                  </div>
                  {#if testState !== 'idle'}
                    <p class="test-msg {testState === 'ok' ? 'ok' : 'fail'}">{testMsg}</p>
                  {/if}
                  {#if formPullMsg}<p class="pull-msg">{formPullMsg}</p>{/if}

                  {#if formPull.length}
                    <div class="form-model-pick">
                      <span class="micro-label">点选默认模型（再点一次取消）</span>
                      <div class="pick-list">
                        {#each formPull as m (m)}
                          <button type="button" class="pick-row" class:on={pf.model_name === m} onclick={() => (pf.model_name = pf.model_name === m ? '' : m)}>
                            <span class="pool-name mono">{m}</span>
                            {#if pf.model_name === m}<span class="badge ok">已选</span>{/if}
                          </button>
                        {/each}
                      </div>
                    </div>
                  {/if}

                  <div class="form-actions">
                    <button class="btn-outline sm" type="button" onclick={() => (expandedPreset = null)}>取消</button>
                    <button class="btn-primary sm" type="submit" disabled={saving}>保存</button>
                  </div>
                </form>
              {/if}
            </div>
          {/each}

          <!-- 自定义 OpenAI 兼容接口 -->
          <div class="preset-item">
            <button class="preset-card" class:on={expandedPreset === 'custom'} type="button" onclick={toggleCustom}>
              <span class="pc-head">
                <span class="pc-label">自定义</span>
                <span class="pc-key">OpenAI 兼容</span>
              </span>
              <span class="pc-desc">中转 / 私有部署，需填地址</span>
            </button>

            {#if expandedPreset === 'custom'}
              <form class="inline-form" onsubmit={submitProvider}>
                <div class="field-row">
                  <label class="field"><span>名称</span><input class="input" type="text" bind:value={pf.key} placeholder="如 my-relay" required /></label>
                  <label class="field"><span>Provider</span><input class="input" type="text" bind:value={pf.provider} placeholder="一般填 openai" required /></label>
                </div>
                <label class="field"><span>Base URL</span><input class="input" type="text" bind:value={pf.base_url} placeholder="https://api.openai.com/v1" required /></label>
                <UrlPreview base_url={pf.base_url} provider={pf.provider} />
                <label class="field"><span>API Key</span><input class="input" type="password" bind:value={pf.api_key} placeholder="sk-..." required /></label>

                <div class="pull-bar">
                  <button class="btn-outline sm" type="button" disabled={formPulling || !pf.base_url} onclick={pullFormModels}>
                    {formPulling ? '正在拉取…' : '拉取模型列表'}
                  </button>
                </div>
                {#if formPullMsg}<p class="pull-msg">{formPullMsg}</p>{/if}
                {#if formPull.length}
                  <div class="form-model-pick">
                    <span class="micro-label">点选一个模型（再点一次取消；或手动输入）</span>
                    <div class="pick-list">
                      {#each formPull as m (m)}
                        <button type="button" class="pick-row" class:on={pf.model_name === m} onclick={() => (pf.model_name = pf.model_name === m ? '' : m)}>
                          <span class="pool-name mono">{m}</span>
                          {#if pf.model_name === m}<span class="badge ok">已选</span>{/if}
                        </button>
                      {/each}
                    </div>
                  </div>
                {/if}
                <label class="field"><span>模型名</span><input class="input" type="text" bind:value={pf.model_name} placeholder="可点选上方列表，或手动输入" required /></label>

                <label class="check-line" title="勾选 = 该模型支持图片输入，图片直接发给它">
                  <input type="checkbox" bind:checked={pf.multimodal} />
                  <span>支持图像识别（模型能直接看图就勾上）</span>
                </label>

                <details class="adv-details">
                  <summary>高级选项（采样参数）</summary>
                  <div class="field-row">
                    <label class="field"><span>Temperature</span><input class="input" type="number" step="0.1" min="0" max="2" bind:value={pf.temperature} placeholder="1.0" /></label>
                    <label class="field"><span>Max Tokens</span><input class="input" type="number" min="1" bind:value={pf.max_tokens} placeholder="2048" /></label>
                  </div>
                  <SamplingPresets
                    temperature={pf.temperature}
                    presence={pf.presence_penalty}
                    frequency={pf.frequency_penalty}
                    onselect={applySampling}
                  />
                  <div class="field-row">
                    <label class="field"><span class="field-label">存在惩罚</span><input class="input" type="number" step="0.1" min="-2" max="2" bind:value={pf.presence_penalty} placeholder="0.3" /></label>
                    <label class="field"><span class="field-label">频率惩罚</span><input class="input" type="number" step="0.1" min="-2" max="2" bind:value={pf.frequency_penalty} placeholder="0.3" /></label>
                  </div>
                </details>

                <div class="form-actions">
                  <button class="btn-outline sm" type="button" onclick={() => (expandedPreset = null)}>取消</button>
                  <button class="btn-primary sm" type="submit" disabled={saving}>保存</button>
                </div>
              </form>
            {/if}
          </div>
        </div>
      {/if}

      {#if providers.length}
        <div class="added-block">
          <span class="micro-label">已添加</span>
          <div class="card-list">
            {#each providers as p}
              <div class="card-row">
                <div class="row-main">
                  <span class="row-title">{p.provider || p.key}{#if p.model_name}<span class="dim"> · {p.model_name}</span>{/if}</span>
                  <span class="row-sub">{p.base_url || '未配置地址'}</span>
                </div>
                <div class="row-actions">
                  {#if p.key === model.current}<span class="badge ok">使用中</span>{/if}
                  <button class="icon-btn danger" type="button" title="删除" onclick={() => removeProvider(p.key)}>
                    {@html `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${I.trash}</svg>`}
                  </button>
                </div>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    </section>
  {/if}
</SettingsShell>

<style>
  /* ---- 图片流程说明 ---- */
  .mm-chain {
    padding: var(--space-3);
    margin-bottom: var(--space-3);
    border-left: 2px solid var(--accent);
    background: var(--surface-2);
  }
  .mm-chain-text {
    margin: var(--space-1) 0 0;
    font-size: var(--text-sm);
    line-height: 1.6;
    color: var(--text-1);
  }

  /* ---- 已添加模型条目 ---- */
  .entry-list {
    display: flex;
    flex-direction: column;
    margin-bottom: var(--space-3);
  }
  .entry-row {
    padding: var(--space-3) 0;
    border-bottom: 1px solid var(--border);
  }
  .entry-row:last-child { border-bottom: none; }
  .entry-head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
    margin-bottom: var(--space-2);
  }
  .entry-name {
    font-size: var(--text-sm);
    color: var(--text-1);
    word-break: break-all;
  }
  .entry-key {
    font-size: var(--text-xs);
    color: var(--text-3);
    margin-left: var(--space-1);
  }
  .entry-controls {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
  }
  .ctl-sep {
    width: 1px;
    height: 16px;
    background: var(--border);
  }

  /* ---- 勾选框 ---- */
  .check-line {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    color: var(--text-2);
    cursor: pointer;
    user-select: none;
  }
  .check-line input {
    width: 16px;
    height: 16px;
    accent-color: var(--accent);
    cursor: pointer;
  }

  .pull-bar {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    margin-bottom: var(--space-3);
    flex-wrap: wrap;
  }
  .pull-provider {
    width: auto;
    min-width: 140px;
    height: 32px;
    padding: 0 var(--space-2);
    font-size: var(--text-sm);
  }
  .pull-msg {
    font-size: var(--text-xs);
    color: var(--text-3);
  }

  /* ---- 选择服务商：卡片 + 内联展开 ----
     原来 12 张卡挤在 220px 网格里, 每张内部是「名称 14px + key 12px +
     描述 12px」三行同权重的小字, 一屏 12 个方块看不出主次, 也不知道
     点下去是什么。现在:
       ① 网格放宽到 240px 最小宽, 一屏 3 列, 每张卡有足够宽度放一行描述
       ② 卡片标题 13px/500, key 走 11px 等宽字, 描述 11px 两行截断 ——
          名称是主体, key 与描述是附注, 三层重量区分开
       ③ 卡片左侧留 2px 竖线, 展开时变冷蓝, 与 card-row 的 hover 语言一致
       ④ 展开区与卡片同宽同边 (border-top:none), 视觉上确实是「卡片就地长出来」*/
  .preset-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(236px, 1fr));
    gap: var(--space-2);
  }
  .preset-item {
    display: flex;
    flex-direction: column;
    gap: 0;
  }
  .preset-item .inline-form {
    border: 1px solid var(--accent-line);
    border-top: none;
    border-radius: 0 0 var(--radius-sm) var(--radius-sm);
    padding: var(--space-3);
    background: var(--surface-2);
  }
  .preset-card {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: var(--optical-3);
    width: 100%;
    padding: var(--space-3);
    border: 1px solid var(--border);
    border-left: 2px solid var(--border-strong);
    border-radius: var(--radius-sm);
    background: var(--surface);
    color: var(--text-1);
    cursor: pointer;
    text-align: left;
    transition: border-color var(--transition), background var(--transition), box-shadow var(--transition);
  }
  .preset-card:hover {
    border-color: var(--border-strong);
    border-left-color: var(--accent);
    background: var(--surface-2);
  }
  .preset-card.on {
    border-color: var(--accent-line);
    border-left-color: var(--accent);
    border-radius: var(--radius-sm) var(--radius-sm) 0 0;
    background: var(--accent-wash);
  }
  .pc-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-2);
  }
  .pc-label {
    font-weight: 500;
    font-size: var(--text-13);
    letter-spacing: var(--tracking-tight);
    color: var(--text-1);
  }
  .pc-key {
    flex: none;
    font-family: var(--font-mono);
    font-size: var(--text-2xs);
    letter-spacing: 0.02em;
    color: var(--text-3);
  }
  .pc-desc {
    font-size: var(--text-2xs);
    color: var(--text-2);
    line-height: 1.55;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .pc-meta {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-height: 0;
    margin-top: var(--optical-2);
  }
  .inline-form { margin-bottom: 0; }
  .inline-form .pull-bar { margin: var(--space-2) 0; }
  .inline-form .form-actions { margin-top: var(--space-3); }

  /* ---- 已添加提供商列表 ---- */
  .added-block {
    margin-top: var(--space-4);
  }
  .added-block .micro-label {
    display: block;
    margin-bottom: var(--space-2);
  }

  .form-model-pick {
    margin-bottom: var(--space-3);
  }
  .form-model-pick .micro-label {
    display: block;
    margin-bottom: var(--space-2);
  }
  .pick-list {
    max-height: 220px;
    overflow-y: auto;
    border-top: 1px solid var(--border);
  }
  .pick-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    width: 100%;
    padding: var(--space-2) var(--space-1);
    border: none;
    border-bottom: 1px solid var(--border);
    background: transparent;
    color: inherit;
    cursor: pointer;
    text-align: left;
    transition: background var(--transition);
  }
  .pick-row:hover { background: var(--surface-2); }
  .pick-row.on { background: var(--accent-wash); border-left: 2px solid var(--accent); padding-left: var(--optical-6); }

  .adv-details {
    margin-bottom: var(--space-3);
  }
  .adv-details summary {
    cursor: pointer;
    font-size: var(--text-13);
    color: var(--text-2);
    margin-bottom: var(--space-3);
    user-select: none;
  }

  .model-pool {
    display: flex;
    flex-direction: column;
    border-top: 1px solid var(--border);
  }
  .pool-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--border);
  }
  .pool-name {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--text-1);
    word-break: break-all;
  }
  .pool-actions { display: flex; gap: var(--space-1); flex: none; }
  .mini-btn {
    height: 24px;
    padding: 0 var(--space-2);
    font-size: var(--text-xs);
    border: 1px solid var(--border);
    border-radius: var(--radius-xs);
    background: transparent;
    color: var(--text-2);
    cursor: pointer;
    transition: background var(--transition), color var(--transition), border-color var(--transition);
  }
  .mini-btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
  .mini-btn.on {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--on-accent);
  }
  .mini-btn:disabled { opacity: 0.5; cursor: default; }

  /* 采样参数: 字段标签小字 */
  .field-label {
    font-size: var(--text-xs);
    color: var(--text-2);
    font-weight: 500;
  }

  /* 连接与测试反馈 */
  .test-msg {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin: 0;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-sm);
    font-size: var(--text-xs);
    line-height: var(--leading-snug);
    word-break: break-all;
  }
  .test-msg.ok { color: var(--success); background: var(--success-soft); }
  .test-msg.fail { color: var(--error); background: var(--error-soft); }

  /* ---- 无可用模型时的引导 ---- */
  .no-model {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-2);
  }
  .no-model-desc {
    margin: 0;
    font-size: var(--text-sm);
    line-height: 1.7;
    color: var(--text-2);
  }
</style>
