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
  // 连接与测试反馈（新增表单里就地测试）
  let testState = $state('idle'); // idle | testing | ok | fail
  let testMsg = $state('');
  // ④ 连接测试区：对「已保存的服务商」单独测一次，不回显已存密钥
  let diagKey = $state('');
  let diagApiKey = $state('');
  let diagState = $state('idle'); // idle | testing | ok | fail
  let diagMsg = $state('');

  // ④ 选中服务商变化时清掉上一次的测试结果，避免旧结论挂在新的服务商上
  $effect(() => {
    void diagKey;
    diagState = 'idle';
    diagMsg = '';
  });

  // ② 服务商列表加载/变化后，把测试目标补一个默认选中项
  //    （reloadModels 里那句发生在 providers 还是空数组时，所以这里兜一次）
  $effect(() => {
    const first = providers[0]?.key || '';
    if (!first) return;
    if (!providers.some((p) => p.key === diagKey)) diagKey = first;
  });

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
    diagKey = diagKey || providers[0]?.key || '';
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

  // 区块跳转：标题区/总览里的按钮滚到对应区块，长表单不用手滑
  function jumpTo(id) {
    const el = document.getElementById(id);
    if (el?.scrollIntoView) el.scrollIntoView({ block: 'start' });
  }

  // ④ 用已保存服务商的 provider/base_url/model_name + 现场粘贴的密钥测一次
  async function testAddedProvider() {
    const p = providers.find((x) => x.key === diagKey) || providers[0];
    if (!p) {
      diagState = 'fail';
      diagMsg = '还没有可测试的服务商';
      return;
    }
    if (!diagApiKey) {
      diagState = 'fail';
      diagMsg = '请先粘贴该服务商的 API Key';
      return;
    }
    diagState = 'testing';
    diagMsg = '';
    try {
      const body = { provider: p.provider || p.key };
      if (p.base_url) body.base_url = p.base_url;
      if (p.model_name) body.model_name = p.model_name;
      body.api_key = diagApiKey;
      const r = await bootstrapApi.test(body);
      if (r.ok) {
        const ok = r.data?.ok !== false;
        diagState = ok ? 'ok' : 'fail';
        const msg = typeof r.data?.message === 'string' ? r.data.message : '';
        const ms = Number(r.data?.latency_ms);
        diagMsg = ok
          ? `${msg || '连接成功'}${Number.isFinite(ms) && ms > 0 ? `（${ms} ms）` : ''}`
          : (msg || '连接失败');
      } else {
        const m = errMsg(r, '连接失败');
        diagState = 'fail';
        diagMsg = m.includes('暂不支持') ? '该服务商暂不支持在线测试' : m;
      }
    } catch (e) {
      diagState = 'fail';
      diagMsg = errMsg(e, '连接失败');
    }
  }
</script>

<SettingsShell title="模型设置" desc="管理服务商、默认模型与识别和语音能力" {onback}>
  {#if loading}
    <div class="settings-group settings-group-pad">
      <EmptyState icon="cpu" title="正在加载模型配置…" compact />
    </div>
  {:else}
    <section class="settings-group settings-group-pad" id="overview">
      <div class="section-head">
        <h2>默认模型与状态</h2>
        <span class="head-sub">当前在用的语言模型与整体情况</span>
      </div>

      <div class="ov-grid">
        <div class="ov-item">
          <span class="ov-label">语言模型</span>
          <span class="ov-value mono" class:is-empty={!roles.chat?.model_name}>
            {roles.chat?.model_name || '未配置'}
          </span>
          <span class="ov-note">{roles.chat?.key || '还没有可以聊天的模型'}</span>
        </div>
        <div class="ov-item">
          <span class="ov-label">已配置模型</span>
          <span class="ov-value">{model?.available?.length || 0}</span>
          <span class="ov-note">
            {#if model?.available?.length}来自 {providers.length} 家服务商{:else}还没有任何模型{/if}
          </span>
        </div>
        <div class="ov-item">
          <span class="ov-label">备用识别</span>
          <span class="ov-value mono" class:is-empty={!roles.vision?.model_name}>
            {roles.vision?.model_name || '未设置'}
          </span>
          <span class="ov-note">
            {roles.vision?.model_name ? '图片先转文字再交给语言模型' : '由语言模型直接看图'}
          </span>
        </div>
        <div class="ov-item">
          <span class="ov-label">语音合成</span>
          <span class="ov-value mono" class:is-empty={!roles.tts?.model_name}>
            {roles.tts?.model_name || '未设置'}
          </span>
          <span class="ov-note">{roles.tts?.model_name ? '生成型模型，单独设置' : '当前不发语音'}</span>
        </div>
      </div>

      <div class="ov-chain">
        <span class="micro-label">识别流程</span>
        <p class="ov-chain-text">{roles.image_chain || '—'}</p>
      </div>

      {#if !model?.available?.length}
        <div class="ov-warn">
          <p class="ov-warn-text">
            添加带有有效 API Key 的服务商并选择模型后，即可使用聊天。
          </p>
          <button class="btn-outline sm" type="button" onclick={() => jumpTo('providers')}>去添加服务商</button>
        </div>
      {/if}
    </section>

    <section class="settings-group settings-group-pad" id="providers">
      <div class="section-head">
        <h2>服务商</h2>
        <span class="head-sub">查看已配置的接口，或通过预设添加服务商。</span>
      </div>

      {#if providers.length}
        <div class="card-list">
          {#each providers as p}
            <div class="settings-row">
              <div class="row-main">
                <span class="row-title">{p.provider || p.key}{#if p.model_name}<span class="dim"> · {p.model_name}</span>{/if}</span>
                <span class="row-sub">{p.base_url || '未配置地址'}</span>
              </div>
              <div class="row-actions">
                {#if p.key === model.current}<span class="badge ok">使用中</span>{/if}
                <button class="icon-btn danger" type="button" aria-label={`删除 ${p.provider || p.key}`} title="删除" onclick={() => removeProvider(p.key)}>
                  {@html `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${I.trash}</svg>`}
                </button>
              </div>
            </div>
          {/each}
        </div>
      {:else}
        <EmptyState icon="cpu" title="尚未添加服务商" desc="选择下方预设或使用自定义接口。" compact />
      {/if}

      <div class="add-head">
        <span class="micro-label">新增服务商</span>
      </div>

      {#if presetsLoading}
        <div class="preset-grid">
          {#each [1, 2, 3, 4] as _}
            <div class="preset-card skeleton"></div>
          {/each}
        </div>
      {:else}
        <div class="preset-grid">
          {#each presets as p (p.key)}
            <div class="preset-item">
              <button class="preset-card" class:on={expandedPreset === p.key} aria-expanded={expandedPreset === p.key} type="button" onclick={() => togglePreset(p)}>
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
                    <p role="status" class="test-msg {testState === 'ok' ? 'ok' : 'fail'}">{testMsg}</p>
                  {/if}
                  {#if formPullMsg}<p class="pull-msg">{formPullMsg}</p>{/if}

                  {#if formPull.length}
                    <div class="form-model-pick">
                      <span class="micro-label">点选默认模型（再点一次取消）</span>
                      <div class="pick-list">
                        {#each formPull as m (m)}
                          <button type="button" class="pick-row" class:on={pf.model_name === m} aria-pressed={pf.model_name === m} onclick={() => (pf.model_name = pf.model_name === m ? '' : m)}>
                            <span class="pool-name mono">{m}</span>
                            {#if pf.model_name === m}<span class="badge ok">已选</span>{/if}
                          </button>
                        {/each}
                      </div>
                    </div>
                  {/if}

                  {@render samplingFields()}

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
            <button class="preset-card" class:on={expandedPreset === 'custom'} aria-expanded={expandedPreset === 'custom'} type="button" onclick={toggleCustom}>
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
                        <button type="button" class="pick-row" class:on={pf.model_name === m} aria-pressed={pf.model_name === m} onclick={() => (pf.model_name = pf.model_name === m ? '' : m)}>
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

                {@render samplingFields()}

                <div class="form-actions">
                  <button class="btn-outline sm" type="button" onclick={() => (expandedPreset = null)}>取消</button>
                  <button class="btn-primary sm" type="submit" disabled={saving}>保存</button>
                </div>
              </form>
            {/if}
          </div>
        </div>
      {/if}
    </section>

    <section class="settings-group settings-group-pad" id="capability">
      <div class="section-head">
        <h2>模型能力与用途</h2>
        <span class="head-sub">谁聊天、谁看图、谁发语音</span>
      </div>

      {#if roles.pool.length}
        <div class="card-list">
          {#each roles.pool as entry (entry.key)}
            <div class="settings-row entry-row">
              <div class="entry-head">
                <span class="entry-name mono">
                  {entry.model_name || entry.key}
                  <span class="entry-key">{entry.key}</span>
                </span>
                {#if entry.is_current}<span class="badge ok">语言</span>{/if}
                {#if roles.vision?.model_name === entry.model_name && !entry.is_current}<span class="badge">识别</span>{/if}
              </div>
              <div class="entry-controls">
                <label class="check-line" title="勾选 = 该模型是多模态：看图、听语音这类识别都直接发给它（快）。是否真的支持以实测为准——勾错的模型收到图片会报错">
                  <input
                    type="checkbox"
                    checked={entry.multimodal}
                    disabled={!!checking}
                    onchange={(e) => toggleVision(entry, e.currentTarget.checked)}
                  />
                  <span>多模态</span>
                </label>
                <div class="settings-segmented" role="group" aria-label="模型用途">
                  <button type="button" disabled={!!assigning || isTtsModel(entry.model_name)}
                    onclick={() => assignRole('chat', entry.model_name, entry.key)}
                    title={entry.is_current ? '当前语言模型' : '设为语言模型'}
                    aria-pressed={entry.is_current}>语言</button>
                  <button type="button" disabled={!!assigning || isTtsModel(entry.model_name)}
                    onclick={() => assignRole('vision', entry.model_name, entry.key)}
                    title={roles.vision?.model_name === entry.model_name ? '再次点击取消（备用识别）' : '设为备用识别模型（图片/语音转文字）'}
                    aria-pressed={roles.vision?.model_name === entry.model_name}>识别</button>
                  <button type="button" disabled={!!assigning || !isTtsModel(entry.model_name)}
                    onclick={() => assignRole('tts', entry.model_name, entry.key)}
                    title={roles.tts?.model_name === entry.model_name ? '再次点击取消' : '只有语音合成类模型（tts）可分配'}
                    aria-pressed={roles.tts?.model_name === entry.model_name}>语音</button>
                </div>
              </div>
            </div>
          {/each}
        </div>

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
            <div class="card-list model-pool">
              {#each pulled as m (m)}
                <div class="settings-row pool-row">
                  <span class="pool-name mono">{m}</span>
                  <div class="settings-segmented" role="group" aria-label="模型用途">
                    <button type="button" disabled={!!assigning || isTtsModel(m)}
                      onclick={() => assignRole('chat', m, pullKey)}
                      title="把 {pullKey} 条目切到此模型，并设为语言模型"
                      aria-pressed={roles.chat?.model_name === m && roles.chat?.key === pullKey}>语言</button>
                    <button type="button" disabled={!!assigning || isTtsModel(m)}
                      onclick={() => assignRole('vision', m, pullKey)}
                      title={roles.vision?.model_name === m ? '再次点击取消' : '设为备用识别模型（图片/语音转文字）'}
                      aria-pressed={roles.vision?.model_name === m}>识别</button>
                    <button type="button" disabled={!!assigning || !isTtsModel(m)}
                      onclick={() => assignRole('tts', m, pullKey)}
                      title={roles.tts?.model_name === m ? '再次点击取消' : '只有语音类模型（tts）可分配'}
                      aria-pressed={roles.tts?.model_name === m}>语音</button>
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        {/if}

        <p class="hint">
          启用多模态后，图片直接发给语言模型。也可以另选备用识别模型，将图片转成文字后交给语言模型。
        </p>
      {:else}
        <p class="hint">还没有模型条目 —— 先在「服务商」里添加一家并保存，这里就会出现可分配的角色。</p>
      {/if}
    </section>

    <section class="settings-group settings-group-pad" id="diagnostics">
      <div class="section-head">
        <h2>连接测试</h2>
        <span class="head-sub">发一条最小请求，验证地址、密钥与模型名</span>
      </div>

      {#if providers.length}
        <div class="diag">
          <div class="field-row">
            <label class="field">
              <span>测哪个服务商</span>
              <select class="input" bind:value={diagKey}>
                {#each providers as p (p.key)}
                  <option value={p.key}>{p.provider || p.key}{#if p.model_name} · {p.model_name}{/if}</option>
                {/each}
              </select>
            </label>
            <label class="field">
              <span>API Key</span>
              <input class="input" type="password" bind:value={diagApiKey} placeholder="已保存的密钥不回显，粘贴一次即可测试" />
            </label>
          </div>
          <div class="diag-actions">
            <button class="btn-primary sm" type="button"
              disabled={diagState === 'testing' || !diagApiKey}
              onclick={testAddedProvider}>
              {diagState === 'testing' ? '测试中…' : '测试连接'}
            </button>
            {#if diagState !== 'idle'}
              <p class="test-msg {diagState === 'ok' ? 'ok' : 'fail'}">{diagMsg}</p>
            {/if}
          </div>
        </div>
      {:else}
        <p class="hint">还没有服务商可测试 —— 先在上面添加一家。</p>
      {/if}
    </section>
  {/if}
</SettingsShell>

{#snippet samplingFields()}
  <details class="adv-details">
    <summary>
      <span>高级参数</span>
      <span class="adv-hint">留空使用服务商默认值</span>
    </summary>
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
{/snippet}

<style>
  .ov-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 146px), 1fr));
    gap: var(--space-2);
  }
  .ov-item {
    display: grid;
    align-content: start;
    gap: var(--space-1);
    min-width: 0;
    padding: var(--space-3);
    border-radius: var(--radius-lg);
    background: var(--settings-control);
  }
  .ov-label, .micro-label { color: var(--text-2); font-size: var(--text-xs); font-weight: 650; }
  .ov-value { color: var(--text-1); font-size: var(--text-sm); font-weight: 650; overflow-wrap: anywhere; }
  .ov-value.is-empty, .ov-note { color: var(--text-2); }
  .ov-note { font-size: var(--text-xs); line-height: 1.5; overflow-wrap: anywhere; }
  .ov-chain { margin-top: var(--space-3); }
  .ov-chain-text { margin: var(--space-1) 0 0; color: var(--text-2); font-size: var(--text-13); overflow-wrap: anywhere; }
  .ov-warn {
    display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;
    gap: var(--space-2); margin-top: var(--space-3); padding: var(--space-3);
    border-radius: var(--radius-lg); background: var(--settings-selected);
  }
  .ov-warn-text { flex: 1 1 180px; margin: 0; font-size: var(--text-13); line-height: 1.55; }
  .add-head { margin: var(--space-4) 0 var(--space-2); }
  .preset-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 160px), 1fr));
    gap: var(--space-2);
    align-items: start;
  }
  .preset-item { min-width: 0; }
  .preset-item:has(.inline-form) { grid-column: 1 / -1; }
  .preset-item:not(:has(.inline-form)) { align-self: stretch; }
  .preset-item:not(:has(.inline-form)) > .preset-card { height: 100%; }
  .preset-card, .pick-row {
    display: grid;
    width: 100%;
    min-width: 0;
    gap: var(--space-2);
    padding: var(--space-3);
    border: 0;
    border-radius: var(--radius-lg);
    background: var(--settings-control);
    color: var(--text-1);
    font: inherit;
    text-align: left;
    cursor: pointer;
    overflow-wrap: anywhere;
    transition: background var(--transition);
  }
  .preset-card { min-height: 88px; align-content: start; }
  .preset-card:hover, .pick-row:hover { background: var(--field-fill-focus); }
  .preset-card.on, .pick-row.on { background: var(--settings-selected); box-shadow: inset 0 0 0 1px var(--accent-line); }
  .skeleton { cursor: default; }
  .pc-head { display: flex; justify-content: space-between; gap: var(--space-1) var(--space-2); flex-wrap: wrap; }
  .pc-label { font-size: var(--text-sm); font-weight: 650; }
  .pc-key, .pc-desc { color: var(--text-2); font-size: var(--text-xs); line-height: 1.45; }
  .inline-form {
    display: grid;
    gap: var(--space-3);
    margin-top: var(--space-2);
    padding: var(--settings-inset);
    border-radius: var(--radius-lg);
    background: var(--surface-2);
  }
  .pull-bar, .diag-actions, .entry-controls { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); }
  .pull-bar, .diag-actions { margin-top: var(--space-2); }
  .pull-provider { max-width: 240px; }
  .pull-msg, .test-msg { min-width: 0; margin: 0; color: var(--text-2); font-size: var(--text-xs); overflow-wrap: anywhere; }
  .test-msg.ok { color: var(--success); }
  .test-msg.fail:not(:empty) { color: var(--error); }
  .form-model-pick { display: grid; gap: var(--space-2); }
  .pick-list { display: grid; gap: var(--space-1); max-height: 240px; overflow: auto; padding: var(--space-1); }
  .pick-row { grid-template-columns: minmax(0, 1fr) auto; align-items: center; }
  .adv-details { padding: var(--space-3); border-radius: var(--radius-lg); background: var(--surface); }
  .adv-details summary { color: var(--text-1); font-size: var(--text-13); font-weight: 620; cursor: pointer; }
  .adv-details[open] > :not(summary) { margin-top: var(--space-3); }
  .adv-hint { display: inline-block; margin-inline-start: var(--space-2); color: var(--text-2); font-size: var(--text-xs); font-weight: 400; }
  .entry-row, .pool-row { justify-content: space-between; flex-wrap: wrap; }
  .entry-head { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); flex: 1 1 180px; min-width: 0; }
  .entry-name, .pool-name { color: var(--text-1); font-size: var(--text-13); overflow-wrap: anywhere; min-width: 0; }
  .entry-key { display: block; color: var(--text-2); font-size: var(--text-xs); }
  .check-line { display: inline-flex; align-items: center; gap: var(--space-2); font-size: var(--text-13); color: var(--text-2); }
  .check-line input { width: 16px; height: 16px; margin: 0; flex: none; }
  .model-pool { margin-top: var(--space-2); max-height: 320px; overflow: auto; }
</style>
