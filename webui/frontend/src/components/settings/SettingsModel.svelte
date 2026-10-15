<script>
  // SettingsModel.svelte — 模型设置
  // 服务商卡片列表 + 当前模型高亮 + 新增/删除 + 发现模型 + 视觉模型
  import SettingsShell from './SettingsShell.svelte';
  import EmptyState from './EmptyState.svelte';
  import ProviderPresetPicker from './ProviderPresetPicker.svelte';
  import SamplingPresets from './SamplingPresets.svelte';
  import UrlPreview from './UrlPreview.svelte';
  import './settings-base.css';
  import { I } from './icons.js';
  import { modelApi, visionApi, bootstrapApi } from '../../lib/settingsApi.js';
  import { confirmDialog } from '../../lib/dialog.svelte.js';

  let { notify, onback } = $props();

  let model = $state(null);
  let providers = $state([]);
  let loading = $state(true);
  let saving = $state(false);

  let showAddProvider = $state(false);
  let pf = $state({ key: '', provider: '', model_name: '', base_url: '', api_key: '', temperature: null, max_tokens: null, presence_penalty: null, frequency_penalty: null });
  let disc = $state({ base_url: '', api_key: '' });
  let vision = $state({ provider: '', model_name: '', base_url: '', api_key: '' });

  // ---- 多模态 / 图片处理 ----
  let mm = $state({
    declared: 'auto',   // 当前模型的多模态声明: auto | yes | no
    imageMode: 'auto',  // auto | direct | vision
    chain: '',          // 当前链路的人类可读描述
    resolved: false,    // 启发式 + 声明后的最终判定
    mainModel: '',
    busy: false,
  });
  let modelDefs = $state([]);   // [{key, model_name, multimodal}]

  // ---- 模型角色（语言 / 图片识别 / 视频识别）----
  let roles = $state({ chat: null, vision: null, video: null, tts: null, pool: [] });
  let pulled = $state([]);      // 拉取到的可用模型 id 列表
  let pulling = $state(false);
  let pullMsg = $state('');     // 拉取结果提示
  let assigning = $state('');   // 正在分配的角色

  // 预设服务商 catalog key 集合 (来自 /api/bootstrap/providers)
  let catalogKeys = $state([]);
  // 连接与测试反馈
  let testState = $state('idle'); // idle | testing | ok | fail
  let testMsg = $state('');

  $effect(() => {
    let alive = true;
    load();
    loadRoles();
    return () => (alive = false);
    async function load() {
      loading = true;
      try {
        const r = await modelApi.get();
        if (!alive) return;
        if (r.ok) {
          model = r.data || {};
          const avail = Array.isArray(r.data?.available) ? r.data.available : [];
          if (avail.length && typeof avail[0] === 'object') {
            providers = avail;
            model.available = avail.map((a) => a.key ?? a.model_name ?? a.provider);
          } else {
            providers = avail.map((k) => ({ key: k, provider: k, model_name: k, base_url: r.data?.base_url }));
          }
          modelDefs = applyModelData(r.data);
        } else notify(errMsg(r, '加载模型配置失败'), 'error');
      } catch (e) { notify(errMsg(e, '加载模型配置失败'), 'error'); }

      const rv = await visionApi.get();
      if (alive && rv.ok && rv.data) {
        vision = { provider: rv.data.provider ?? '', model_name: rv.data.model_name ?? '', base_url: rv.data.base_url ?? '', api_key: '' };
        mm.declared = rv.data.main_multimodal_declared || 'auto';
        mm.imageMode = rv.data.image_mode || 'auto';
        mm.chain = rv.data.image_chain || '';
        mm.resolved = !!rv.data.main_is_multimodal;
        mm.mainModel = rv.data.main_model || '';
      }
      if (alive) loading = false;
    }
  });

  // 模型角色分配（语言 / 图片识别 / 视频识别）
  async function loadRoles() {
    try {
      const r = await modelApi.roles();
      if (r.ok && r.data) roles = { chat: null, vision: null, video: null, tts: null, pool: [], ...r.data };
    } catch {
      /* ignore */
    }
  }

  // 用已保存的提供商密钥拉取可用模型
  async function pullModels() {
    const key = roles?.chat?.key || model?.current;
    if (!key) {
      notify('请先配置一个提供商', 'error');
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
        notify(errMsg(r, '拉取模型失败'), 'error');
      }
    } catch (e) {
      notify(errMsg(e, '拉取模型失败'), 'error');
    } finally {
      pulling = false;
    }
  }

  // 把某个模型分配到角色
  async function assignRole(role, modelName) {
    assigning = `${role}:${modelName}`;
    try {
      const r = await modelApi.setRole(role, modelName);
      if (r.ok) {
        const label =
          role === 'chat' ? '语言模型'
          : role === 'vision' ? '图片识别模型'
          : role === 'tts' ? '语音合成模型'
          : '视频识别模型';
        notify(r.data?.message || `${label} 已设为 ${modelName}`, 'success');
        await loadRoles();
        if (role === 'chat') {
          await reloadModels();
        } else if (role === 'vision') {
          // 同步视觉区块显示
          vision = { ...vision, model_name: modelName };
        }
      } else {
        notify(errMsg(r, '分配失败'), 'error');
      }
    } finally {
      assigning = '';
    }
  }

  function errMsg(err, fallback) {
    const m = err?.data?.error || err?.data?.message || err?.data?.detail || err?.data;
    if (typeof m === 'string' && m) return m;
    return fallback || (err?.status ? `请求失败（HTTP ${err.status}）` : String(err?.message ?? err));
  }

  async function switchModel(key) {
    saving = true;
    try {
      const r = await modelApi.set(key);
      if (r.ok) { model.current = key; notify('已切换当前模型', 'success'); }
      else notify(errMsg(r, '切换失败'), 'error');
    } finally { saving = false; }
  }

  async function submitProvider(e) {
    e.preventDefault();
    saving = true;
    try {
      const body = {};
      for (const [k, v] of Object.entries(pf)) {
        if (v === '' || v === null || v === undefined) continue;
        body[k] = v;
      }
      const r = await modelApi.addProvider(body);
      if (r.ok) {
        notify('提供商已添加', 'success');
        showAddProvider = false;
        await reloadModels();
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
      } else notify(errMsg(r, '删除失败'), 'error');
    } finally { saving = false; }
  }

  async function submitDiscover(e) {
    e.preventDefault();
    saving = true;
    try {
      const r = await modelApi.discover(disc.base_url, disc.api_key);
      if (r.ok) { notify('发现完成', 'success'); await reloadModels(); }
      else notify(errMsg(r, '发现失败'), 'error');
    } finally { saving = false; }
  }

  async function submitVision(e) {
    if (e && typeof e.preventDefault === 'function') e.preventDefault();
    saving = true;
    try {
      const body = { model_name: vision.model_name, image_mode: mm.imageMode };
      if (vision.provider) body.provider = vision.provider;
      if (vision.base_url) body.base_url = vision.base_url;
      if (vision.api_key) body.api_key = vision.api_key;
      if (mm.declared !== 'auto') body.multimodal = mm.declared;
      const r = await visionApi.set(body);
      if (r.ok) {
        notify('多模态与视觉配置已保存', 'success');
        if (r.data?.image_chain) mm.chain = r.data.image_chain;
        if (r.data?.image_mode) mm.imageMode = r.data.image_mode;
        if (r.data?.multimodal) mm.declared = r.data.multimodal;
        const rr = await modelApi.get();
        if (rr.ok && rr.data) applyModelData(rr.data);
      } else notify(errMsg(r, '保存失败'), 'error');
    } finally { saving = false; }
  }

  // 给某个模型单独设置多模态声明 (auto / yes / no)
  async function setMultimodal(key, value) {
    mm.busy = true;
    try {
      const r = await modelApi.setMultimodal(key, value);
      if (r.ok) {
        notify(
          `${key} 已设为「${value === 'yes' ? '支持图片' : value === 'no' ? '仅文字' : '自动'}」`,
          'success',
        );
        if (r.data?.image_chain) mm.chain = r.data.image_chain;
        if (key === model?.current && r.data?.multimodal) mm.declared = r.data.multimodal;
        // 同步该行的下拉显示
        modelDefs = modelDefs.map((d) => (d.key === key ? { ...d, multimodal: value } : d));
      } else notify(errMsg(r, '设置失败'), 'error');
    } finally { mm.busy = false; }
  }

  // 模型用途判断：tts/asr 类不能当语言或图片模型
  function isTtsModel(name) {
    return /tts|voiceclone|voicedesign|asr|speech/i.test(String(name || ''));
  }

  // 从 /api/model 响应里解析模型清单与各自的多模态声明
  function applyModelData(data) {
    let defs = [];
    const raw = data?.models;
    if (Array.isArray(raw)) {
      defs = raw.map((m) => ({ key: m.key ?? m.model_name, model_name: m.model_name ?? '', multimodal: m.multimodal || 'auto' }));
    } else if (raw && typeof raw === 'object') {
      defs = Object.entries(raw).map(([key, cfg]) => ({
        key, model_name: cfg?.model_name ?? cfg?.model ?? '', multimodal: cfg?.multimodal || 'auto',
      }));
    }
    return defs;
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
        if (avail.length && typeof avail[0] === 'object') {
          providers = avail;
          model.available = avail.map((a) => a.key ?? a.model_name ?? a.provider);
        } else {
          providers = avail.map((k) => ({ key: k, provider: k, model_name: k, base_url: r.data?.base_url }));
        }
        modelDefs = applyModelData(r.data);
      }
    } catch { /* ignore */ }
    loading = false;
  }

  function resetPf() {
    pf = { key: '', provider: '', model_name: '', base_url: '', api_key: '', multimodal: 'auto', temperature: null, max_tokens: null, presence_penalty: null, frequency_penalty: null };
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
      multimodal: 'auto',
      temperature: null,
      max_tokens: null,
      presence_penalty: null,
      frequency_penalty: null,
    };
    testState = 'idle';
    testMsg = '';
  }

  // 采样预设: 仅当 values 非空(命中命名档位)才覆盖手填值 自定义(null)不动表单
  function applySampling(values) {
    if (!values) return;
    pf = { ...pf, ...values };
  }

  function onPresetsLoaded(list) {
    catalogKeys = (Array.isArray(list) ? list : []).map((p) => p.key).filter(Boolean);
  }

  async function testConnection() {
    if (!pf.provider) {
      testState = 'fail';
      testMsg = '请先填写 Provider（或从预设服务商中选择）';
      return;
    }
    // 非 catalog 预设 → 提示不支持在线测试 不调后端
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
        // HTTP 200 = ok; 消息取后端 message 或成功文案
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

<SettingsShell title="模型设置" desc="切换模型、管理提供商、发现与视觉模型" {onback}>
  {#if loading}
    <div class="card card-pad">
      <EmptyState icon="cpu" title="正在加载模型配置…" compact />
    </div>
  {:else}
    <!-- ============ 模型角色：语言 / 图片识别 / 视频识别 ============ -->
    <section class="card card-pad">
      <div class="section-head">
        <h4>模型角色</h4>
        <span class="head-sub">给每个用途指定一个模型</span>
      </div>

      <div class="role-list">
        <div class="role-row">
          <span class="role-label">语言模型</span>
          <span class="role-value mono">{roles?.chat?.model_name || '未设置'}</span>
        </div>
        <div class="role-row">
          <span class="role-label">图片识别</span>
          <span class="role-value mono">{roles?.vision?.model_name || '未设置'}</span>
        </div>
        <div class="role-row">
          <span class="role-label">视频识别</span>
          <span class="role-value mono role-empty">{roles?.video?.model_name || '不可用（模型与识别链路均不支持）'}</span>
        </div>
        <div class="role-row">
          <span class="role-label">语音合成</span>
          <span class="role-value mono role-empty">{roles?.tts?.model_name || '未设置'}</span>
        </div>
      </div>

      <div class="pull-bar">
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
                <button class="mini-btn" type="button" disabled={!!assigning || isTtsModel(m)} onclick={() => assignRole('chat', m)}
                  title={isTtsModel(m) ? '语音类模型不能作为语言模型' : '设为语言模型'}
                  class:on={roles?.chat?.model_name === m}>语言</button>
                <button class="mini-btn" type="button" disabled={!!assigning || isTtsModel(m)} onclick={() => assignRole('vision', m)}
                  title={isTtsModel(m) ? '语音类模型不能作为图片识别模型' : '设为图片识别模型'}
                  class:on={roles?.vision?.model_name === m}>图片</button>
                <button class="mini-btn" type="button" disabled={!!assigning || isTtsModel(m)} onclick={() => assignRole('video', m)}
                  title={isTtsModel(m) ? '语音类模型不能作为视频识别模型' : '设为视频识别模型'}
                  class:on={roles?.video?.model_name === m}>视频</button>
                <button class="mini-btn" type="button" disabled={!!assigning || !isTtsModel(m)} onclick={() => assignRole('tts', m)}
                  title={isTtsModel(m) ? '设为语音合成模型' : '只有语音类模型（tts）可分配到这里'}
                  class:on={roles?.tts?.model_name === m}>语音</button>
              </div>
            </div>
          {/each}
        </div>
        <p class="hint">
          点「语言 / 图片 / 视频 / 语音」把该模型分配到对应角色。<strong>语言模型随时可换（如 Flash ↔ Pro），点一下立即生效</strong>；
          图片与语音分配后立即生效；语音合成走「语音服务商」配置，分配后会置为当前语音服务商。
          语音类模型（tts/asr）不能用作语言/图片/视频；视频识别为预留（识别链路尚未接入）。
        </p>
      {/if}
    </section>

    {#if model?.available?.length}
      <section class="card card-pad">
        <div class="section-head">
          <h4>切换当前模型</h4>
          <span class="head-sub">{model.current ? `当前：${model.current}` : '未选择'}</span>
        </div>
        <div class="card-list">
          {#each model.available as key}
            <button class="card-row model-row" class:on={key === model.current} type="button" onclick={() => switchModel(key)} disabled={saving}>
              <span class="row-main">
                <span class="row-title model-key">{key}</span>
              </span>
              {#if key === model.current}<span class="badge ok">当前</span>{/if}
            </button>
          {/each}
        </div>
      </section>
    {:else}
      <section class="card card-pad">
        <div class="no-model">
          <span class="micro-label">还没有可用的模型</span>
          <p class="no-model-desc">
            当前没有任何模型能回复消息 —— 最常见的原因是 API Key 没配对。
            从下面「选择服务商」里挑一家，填上 Key 就能开始。
          </p>
          <button class="btn-primary" type="button" onclick={() => { resetPf(); showAddProvider = true; }}>
            去配置模型
          </button>
        </div>
      </section>
    {/if}

    <section class="card card-pad">
      <div class="section-head">
        <h4>选择服务商</h4>
        <span class="head-sub">点一下自动填表单，你只需补 API Key</span>
      </div>
      <ProviderPresetPicker
        onselect={(p) => { applyPreset(p); showAddProvider = true; }}
        onloaded={onPresetsLoaded}
        {notify}
      />
      <p class="hint">
        没列出你要的厂商？这里是 12 家主流服务商；其他任何 OpenAI 兼容接口都可以点「新增提供商」手动填。
      </p>
    </section>

    <section class="card card-pad">
      <div class="section-head">
        <h4>提供商列表</h4>
        <button class="btn-primary sm" type="button" onclick={() => { resetPf(); showAddProvider = !showAddProvider; }}>{showAddProvider ? '收起' : '新增提供商'}</button>
      </div>
      {#if !providers.length}
        <EmptyState icon="cpu" title="暂无提供商" desc="点右上角「新增提供商」开始配置" compact />
      {:else}
        <div class="card-list">
          {#each providers as p}
            <div class="card-row">
              <span class="row-icon" aria-hidden="true">{@html `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${I.cpu}</svg>`}</span>
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
      {/if}
    </section>

    {#if showAddProvider}
      <section class="card card-pad">
        <div class="section-head"><h4>新增提供商</h4></div>

        <form class="form provider-form" onsubmit={submitProvider}>
          <div class="field-row">
            <label class="field"><span>Key</span><input class="input" type="text" bind:value={pf.key} placeholder="如 openai / anthropic" required /></label>
            <label class="field"><span>Provider</span><input class="input" type="text" bind:value={pf.provider} placeholder="如 openai" required /></label>
          </div>
          <label class="field"><span>模型名</span><input class="input" type="text" bind:value={pf.model_name} placeholder="如 gpt-4o" required /></label>
          <label class="field">
            <span>图片能力</span>
            <select class="input" bind:value={pf.multimodal}>
              <option value="auto">自动 — 按模型名猜测</option>
              <option value="yes">支持图片（多模态）</option>
              <option value="no">仅文字</option>
            </select>
          </label>
          <label class="field"><span>Base URL</span><input class="input" type="text" bind:value={pf.base_url} placeholder="https://api.openai.com/v1" required /></label>
          <UrlPreview base_url={pf.base_url} provider={pf.provider} />
          {#if pf.api_key}
            <label class="field"><span>API Key</span><input class="input" type="password" bind:value={pf.api_key} placeholder="留空则使用环境变量" /></label>
          {:else}
            <label class="field"><span>API Key</span><input class="input" type="password" bind:value={pf.api_key} placeholder="留空则用环境变量 {catalogKeys.includes(pf.key) ? pf.key.toUpperCase() + '_API_KEY' : '如 openai / anthropic'}" /></label>
          {/if}
          <div class="field-row">
            <label class="field"><span>Temperature</span><input class="input" type="number" step="0.1" min="0" max="2" bind:value={pf.temperature} placeholder="1.0" /></label>
            <label class="field"><span>Max Tokens</span><input class="input" type="number" min="1" bind:value={pf.max_tokens} placeholder="2048" /></label>
          </div>
          <p class="hint">温度越高，回复越随机发散（0~2，常用 0.6~1.3，1.0 默认）。想要赛博伴侣更放飞自我就调高一点~</p>

          <SamplingPresets
            temperature={pf.temperature}
            presence={pf.presence_penalty}
            frequency={pf.frequency_penalty}
            onselect={applySampling}
          />

          <div class="field-row">
            <label class="field">
              <span class="field-label">存在惩罚</span>
              <input class="input" type="number" step="0.1" min="-2" max="2" bind:value={pf.presence_penalty} placeholder="0.3" />
            </label>
            <label class="field">
              <span class="field-label">频率惩罚</span>
              <input class="input" type="number" step="0.1" min="-2" max="2" bind:value={pf.frequency_penalty} placeholder="0.3" />
            </label>
          </div>
          <p class="hint">存在惩罚：某个词只要“出现过”就降一次权，鼓励换新词、聊新话题（-2~2，0=不惩罚，正数促进多样性）。</p>
          <p class="hint">频率惩罚：按“出现次数”叠加降权，压复读、压重复措辞（-2~2，0=不惩罚）。正数让伴侣少说车辛辟话。</p>

          {#if testState !== 'idle'}
            <p class="test-msg {testState === 'ok' ? 'ok' : 'fail'}">
              {#if testState === 'testing'}
                <span class="spin" aria-hidden="true"></span> 正在测试连接…              {:else if testState === 'ok'}
                {@html `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${I.check}</svg>`}
                {testMsg}
              {:else}
                {@html `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${I.close}</svg>`}
                {testMsg}
              {/if}
            </p>
          {/if}

          <div class="form-actions">
            <button class="btn-outline" type="button" onclick={() => (showAddProvider = false)}>取消</button>
            <button class="btn-outline" type="button" onclick={() => testConnection()} disabled={saving || testState === 'testing'}>
              {@html `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${I.upload}</svg>`}
              测试连接
            </button>
            <button class="btn-primary" type="submit" disabled={saving}>保存提供商</button>
          </div>
        </form>
      </section>
    {/if}

    <section class="card card-pad">
      <div class="section-head"><h4>发现模型</h4></div>
      <form class="form" onsubmit={submitDiscover}>
        <label class="field"><span>Base URL</span><input class="input" type="text" bind:value={disc.base_url} placeholder="https://.../v1" required /></label>
        <label class="field"><span>API Key</span><input class="input" type="password" bind:value={disc.api_key} placeholder="sk-..." /></label>
        <div class="form-actions">
          <button class="btn-primary" type="submit" disabled={saving}>
            {@html `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${I.search}</svg>`}
            开始发现          </button>
        </div>
      </form>
    </section>

    <section class="card card-pad">
      <div class="section-head"><h4>多模态与图片识别</h4></div>

      <div class="mm-chain">
        <span class="micro-label">当前链路</span>
        <p class="mm-chain-text">{mm.chain || '—'}</p>
      </div>

      <label class="field">
        <span>当前模型（{mm.mainModel || '未选择'}）是否支持图片</span>
        <select class="input" bind:value={mm.declared} disabled={mm.busy}>
          <option value="auto">自动 — 按模型名猜测</option>
          <option value="yes">是 — 支持多模态</option>
          <option value="no">否 — 仅文字</option>
        </select>
      </label>
      <p class="hint">
        模型名匹配表覆盖不了所有厂商，猜错的代价是多发一次无意义的图片请求 —— 所以让你自己说了算。
        选「是」时图片会<strong>直接发给主模型，跳过中间的视觉识别层，回复更快</strong>。
      </p>

      <label class="field">
        <span>图片处理方式</span>
        <select class="input" bind:value={mm.imageMode} disabled={mm.busy}>
          <option value="auto">自动 — 按模型能力决定</option>
          <option value="direct">强制直连 — 总是发给主模型</option>
          <option value="vision">强制视觉链路 — 总是走视觉模型</option>
        </select>
      </label>
      <p class="hint">
        自动：主模型支持多模态 → 直连（最快）；不支持 → 走视觉模型（慢一层，但不挑主模型）。<br>
        强制直连：跳过中间的视觉层，但主模型不支多模态时会失败。<br>
        强制视觉链路：视觉模型先出描述、再交给主模型，慢一步但更稳。
      </p>

      <div class="form-actions">
        <button class="btn-primary" type="button" onclick={submitVision} disabled={mm.busy}>保存</button>
      </div>

      {#if modelDefs.length}
        <div class="mm-permodel">
          <span class="micro-label">按模型单独设置</span>
          <div class="card-list">
            {#each modelDefs as d}
              <div class="mm-row">
                <span class="mm-row-main">
                  <span class="row-title">{d.key}{d.model_name ? ` · ${d.model_name}` : ''}</span>
                  {#if model?.current === d.key}<span class="badge ok">当前</span>{/if}
                </span>
                <select
                  class="input mm-select"
                  value={d.multimodal}
                  onchange={(e) => setMultimodal(d.key, e.currentTarget.value)}
                  disabled={mm.busy}
                  aria-label="{d.key} 的多模态能力"
                >
                  <option value="auto">自动</option>
                  <option value="yes">支持图片</option>
                  <option value="no">仅文字</option>
                </select>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    </section>

    <section class="card card-pad">
      <div class="section-head"><h4>视觉模型</h4></div>
      <form class="form" onsubmit={submitVision}>
        <div class="field-row">
          <label class="field"><span>Provider</span><input class="input" type="text" bind:value={vision.provider} placeholder="如 openai" /></label>
          <label class="field"><span>模型名</span><input class="input" type="text" bind:value={vision.model_name} placeholder="如 gpt-4o" required /></label>
        </div>
        <div class="field-row">
          <label class="field"><span>Base URL</span><input class="input" type="text" bind:value={vision.base_url} placeholder="https://..." /></label>
          <label class="field"><span>API Key</span><input class="input" type="password" bind:value={vision.api_key} placeholder="sk-..." /></label>
        </div>
        <div class="form-actions">
          <button class="btn-primary" type="submit" disabled={saving}>保存视觉配置</button>
        </div>
      </form>
    </section>
  {/if}
</SettingsShell>

<style>
  .model-row { cursor: pointer; }
  .model-row.on { border-color: var(--accent); background: var(--tint); }
  .model-row:disabled { cursor: default; }
  .model-key { font-weight: 600; word-break: break-all; }

  /* ---- 模型角色 ---- */
  .role-list {
    display: flex;
    flex-direction: column;
    border-top: 1px solid var(--border);
    margin-bottom: var(--space-4);
  }
  .role-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-3) 0;
    border-bottom: 1px solid var(--border);
  }
  .role-label {
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--text-2);
  }
  .role-value {
    font-size: var(--text-sm);
    color: var(--text-1);
    word-break: break-all;
    text-align: right;
  }
  .role-value.role-empty { color: var(--text-3); }

  .pull-bar {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    margin-bottom: var(--space-3);
  }
  .pull-msg {
    font-size: var(--text-xs);
    color: var(--text-3);
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
    font-size: var(--text-sm);
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

  .spin {
    flex: none;
    width: 13px;
    height: 13px;
    border: 2px solid var(--border-strong);
    border-top-color: var(--accent);
    border-radius: var(--radius-xs);
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

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

  /* ---- 多模态 / 图片识别 ---- */
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
  .mm-permodel { margin-top: var(--space-4); }
  .mm-permodel .micro-label { display: block; margin-bottom: var(--space-2); }
  .mm-row {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--border);
  }
  .mm-row:last-child { border-bottom: none; }
  .mm-row-main {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
  }
  .mm-select {
    flex: none;
    width: 116px;
    padding: var(--space-1) var(--space-2);
    font-size: var(--text-xs);
  }
</style>
