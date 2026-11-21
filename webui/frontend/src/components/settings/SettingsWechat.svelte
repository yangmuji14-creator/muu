<script>
  // SettingsWechat.svelte — 微信账号绑定（PawzoChat 式：选平台 → 扫码）
  import SettingsShell from './SettingsShell.svelte';
  import EmptyState from './EmptyState.svelte';
  import Switch from '../Switch.svelte';
  import './settings-base.css';
  import { I } from './icons.js';
  import { wechatApi } from '../../lib/settingsApi.js';
  import { confirmDialog } from '../../lib/dialog.svelte.js';
  import { get } from '../../lib/pages-api.js';

  let { notify, onback } = $props();

  let accounts = $state([]);
  // 通讯录角色目录（用于人设下拉，不让用户手输 ID）
  let personas = $state([]);
  let loaded = $state(false);
  let saving = $state(false);

  let wf = $state({ id: '', persona_id: '', enabled: true, auto_start: false });

  // 平台选择弹层
  let showPlatform = $state(false);
  // 扫码登录弹层
  let qrAccount = $state(null);
  let qrImg = $state('');
  let qrLink = $state('');
  let qrStatus = $state('');
  let qrStatusKind = $state('');
  let qrDone = $state(false);
  let qrEs = null;

  $effect(() => {
    let alive = true;
    (async () => {
      const r = await wechatApi.list();
      if (!alive) return;
      if (r.ok && Array.isArray(r.data)) accounts = r.data;
      else notify(errMsg(r, '加载账号失败'), 'error');
      loaded = true;
    })();
    // 角色目录：从通讯录（/api/persona）拉，供人设下拉使用
    (async () => {
      try {
        const rp = await get('/api/persona');
        if (alive && rp.ok && Array.isArray(rp.data)) personas = rp.data;
      } catch {
        /* 拉不到就退化为「仅不绑定」一个选项 */
      }
    })();
    return () => (alive = false);
  });

  /** 人设下拉的显示文案：小雨（girlfriend_001） */
  function personaLabel(p) {
    return p.name ? `${p.name}（${p.id}）` : p.id;
  }

  function errMsg(err, fallback) {
    const m = err?.data?.error || err?.data?.message || err?.data?.detail || err?.data;
    if (typeof m === 'string' && m) return m;
    return fallback || (err?.status ? `请求失败（HTTP ${err.status}）` : String(err?.message ?? err));
  }

  async function refresh() {
    const r = await wechatApi.list();
    if (r.ok && Array.isArray(r.data)) accounts = r.data;
  }

  // ---- 平台预设（当前仅微信 / iLink；结构与 PawzoChat 一致，便于日后扩展）----
  const PLATFORMS = [
    {
      key: 'wechat',
      label: '微信',
      desc: '通过 iLink 协议扫码登录，自动保持在线',
      icon: 'wechat',
    },
  ];

  // ---- 一键绑定：选平台 → 自动建号/复用 → 扫码 ----
  async function startBind() {
    showPlatform = true;
  }

  async function choosePlatform(key) {
    showPlatform = false;
    // 自动确定要登录的账号：优先复用「未登录」的已有账号，否则自动创建一个
    try {
      let target = (accounts || []).find((a) => !a.has_credentials || a.session_expired);
      if (!target) {
        // 自动创建一个免填的默认账号 id（后端允许 default）
        const nid = 'default';
        const r = await wechatApi.add({ id: nid, enabled: true, auto_start: true });
        if (!r.ok && r.status !== 409) {
          notify(errMsg(r, '自动创建账号失败，请手动新增'), 'error');
          return;
        }
        target = { id: nid };
        await refresh();
      }
      openQr(target.id);
    } catch (e) {
      notify(errMsg(e, '绑定失败'), 'error');
    }
  }

  function cancelPlatform() {
    showPlatform = false;
  }

  // ---- 高级：手动新增账号 ----
  async function submitAdd(e) {
    e.preventDefault();
    saving = true;
    try {
      const body = { id: wf.id };
      if (wf.persona_id) body.persona_id = wf.persona_id;
      body.enabled = wf.enabled;
      body.auto_start = wf.auto_start;
      const r = await wechatApi.add(body);
      if (r.ok) { notify('账号已添加', 'success'); wf = { id: '', persona_id: '', enabled: true, auto_start: false }; refresh(); }
      else notify(errMsg(r, '添加失败'), 'error');
    } finally { saving = false; }
  }

  // 直接改账号绑定的角色：下拉选完即保存，不用手输 ID、不用弹窗
  async function setAccountPersona(acc, personaId) {
    const next = String(personaId || '');
    if (next === String(acc.persona_id || '')) return;
    try {
      const r = await wechatApi.edit(acc.id, { persona_id: next });
      if (r.ok) {
        notify(next ? `已绑定「${personas.find((p) => p.id === next)?.name || next}」` : '已解除绑定', 'success');
        refresh();
      } else {
        notify(errMsg(r, '更新失败'), 'error');
        refresh(); // 失败时把下拉恢复成服务端的真实值
      }
    } catch (e) {
      notify(errMsg(e, '更新失败'), 'error');
      refresh();
    }
  }

  async function removeAccount(id) {
    const ok = await confirmDialog(`删除微信账号 ${id}？`, { title: '删除微信账号', danger: true });
    if (!ok) return;
    try {
      const r = await wechatApi.remove(id);
      if (r.ok) { notify('已删除', 'success'); refresh(); }
      else notify(errMsg(r, '删除失败'), 'error');
    } catch (e) { notify(errMsg(e, '删除失败'), 'error'); }
  }

  async function logoutAccount(id) {
    try {
      const r = await wechatApi.logout(id);
      if (r.ok) notify('已登出', 'success');
      else notify(errMsg(r, '登出失败'), 'error');
      refresh();
    } catch (e) { notify(errMsg(e, '登出失败'), 'error'); }
  }

  // ---- 扫码登录（固定后端命名 SSE 事件：qrcode / status / done）----
  // 后端发送具名事件（event: qrcode / status / done），必须用 addEventListener 而非
  // onmessage（后者只接收默认 message 事件）。连接中断 409 会自动重连，成功后保持连接。
  let qrReconnectTimer = null;
  let qrReconnectCount = 0;

  // 组件卸载时彻底断开扫码连接与重连定时器（review P2-11）：
  // 否则用户切到其它设置页后 EventSource 仍保持连接，断线还会 setTimeout 无限重连。
  $effect(() => () => {
    teardownEs();
    if (qrReconnectTimer) {
      clearTimeout(qrReconnectTimer);
      qrReconnectTimer = null;
    }
  });

  function openQr(id) {
    closeQr();
    qrAccount = id;
    qrDone = false;
    connectQr(id);
  }

  function teardownEs() {
    try { qrEs && qrEs.close(); } catch {}
    qrEs = null;
  }

  function connectQr(id) {
    teardownEs();
    qrReconnectCount = 0;
    qrEs = new EventSource(wechatApi.qrcodeUrl(id));

    const onQr = (payload) => {
      if (!payload || payload.qr_url === undefined) return;
      if (payload.qr_base64) {
        qrImg = payload.qr_base64;
        qrLink = '';
      } else {
        // 无 qrcode 库 → 后端给 qr_url（登录链接），展示为可打开的链接
        qrImg = '';
        qrLink = payload.qr_url;
      }
      qrStatus = '请使用微信扫一扫登录';
      qrStatusKind = 'ok';
    };
    const onStatus = (payload) => {
      if (!payload || payload.status === undefined) return;
      // 后端把 SDK 未识别的状态映射成 failed + "未知状态 X"（如 waiting），
      // 这并非真正失败，而是「正在等待扫码」——统一按正常等待处理。
      if (payload.status === 'failed' && typeof payload.message === 'string' && payload.message.includes('未知状态')) {
        qrStatus = '正在等待微信扫码…';
        qrStatusKind = '';
        return;
      }
      const map = { scanning: '已进入扫码状态，请在手机上确认', confirmed: '已确认，正在登录…', expired: '二维码已过期，请重新获取', failed: '登录失败，请重试' };
      qrStatus = payload.message || map[payload.status] || payload.status;
      qrStatusKind = payload.status === 'expired' || payload.status === 'failed' ? 'error' : 'ok';
    };
    const onDone = (payload) => {
      if (!payload || payload.ok === undefined) return;
      qrDone = true;
      teardownEs();
      if (qrReconnectTimer) { clearTimeout(qrReconnectTimer); qrReconnectTimer = null; }
      if (payload.ok) { qrStatus = '登录成功 ✓'; qrStatusKind = 'ok'; refresh(); }
      else { qrStatus = payload.error || '登录失败'; qrStatusKind = 'error'; }
    };

    qrEs.addEventListener('qrcode', (ev) => { try { onQr(JSON.parse(ev.data)); } catch {} });
    qrEs.addEventListener('status', (ev) => { try { onStatus(JSON.parse(ev.data)); } catch {} });
    qrEs.addEventListener('done', (ev) => { try { onDone(JSON.parse(ev.data)); } catch {} });
    // 兼容：万一代理把事件名剥离，回退到 onmessage 也能解析
    qrEs.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data);
        if (!payload) return;
        if (payload.qr_url !== undefined && !qrImg && !qrLink) onQr(payload);
        else if (payload.status !== undefined && !qrDone) onStatus(payload);
        else if (payload.ok !== undefined) onDone(payload);
      } catch {}
    };
    qrEs.onerror = () => {
      if (qrDone) return;
      // 先关闭当前连接，阻止 EventSource 自带的自动重连（否则会与我们的手动重连
      // 同时发起两个连接，同一账号 → 相互 409，导致卡住"）。
      teardownEs();
      // 服务端同一账号刚断开时锁可能尚未释放（最长约 5s），稍后重试即可。
      if (qrReconnectCount >= 5) {
        qrStatus = '连接失败，请点击「刷新二维码」重试';
        qrStatusKind = 'error';
        return;
      }
      qrReconnectCount += 1;
      if (qrImg || qrLink) {
        qrStatus = '连接中断，正在重连…';
        qrStatusKind = '';
      } else {
        qrStatus = '正在连接服务器…';
        qrStatusKind = '';
      }
      if (qrReconnectTimer) clearTimeout(qrReconnectTimer);
      qrReconnectTimer = setTimeout(() => {
        if (qrDone) return;
        connectQr(qrAccount);
      }, 3000);
    };
  }

  function openDialog(node) {
    queueMicrotask(() => {
      if (node.isConnected) node.showModal();
    });
    return { destroy: () => node.close() };
  }

  function closeQr() {
    if (qrReconnectTimer) { clearTimeout(qrReconnectTimer); qrReconnectTimer = null; }
    teardownEs();
    qrAccount = null;
    qrImg = '';
    qrLink = '';
    qrStatus = '';
    qrDone = false;
  }
</script>

<SettingsShell title="微信账号" desc="绑定微信账号并管理登录状态与人设" {onback}>
  <!-- 一键绑定引导卡 -->
  <section class="settings-group settings-group-pad bind-hero">
    <div class="bind-hero-icon" aria-hidden="true">{@html `<svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${I.wechat}</svg>`}</div>
    <div class="bind-hero-text">
      <h2>绑定微信账号</h2>
      <p class="bind-hero-desc">选择平台后，使用微信扫描登录二维码。</p>
    </div>
    <button class="btn-primary" type="button" onclick={startBind}>开始扫码绑定</button>
  </section>

  <section class="settings-group settings-group-pad">
    <div class="section-head">
      <h2>已绑定账号</h2>
    </div>

    {#if !loaded}
      <EmptyState icon="wechat" title="正在加载…" compact />
    {:else if !accounts.length}
      <EmptyState icon="wechat" title="暂未绑定" compact />
    {:else}
      <div class="card-list">
        {#each accounts as acc (acc.id)}
          <div class="settings-row account-row">
            <span class="row-icon" aria-hidden="true">{@html `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${I.wechat}</svg>`}</span>
            <div class="row-main">
              <span class="row-title">{acc.id}</span>
              <span class="row-sub">
                {#if acc.enabled}<span class="badge ok">启用</span>{:else}<span class="badge">停用</span>{/if}
                {#if acc.adapter_running}<span class="badge ok">运行中</span>{/if}
                {#if acc.session_expired}<span class="badge error">会话过期</span>{/if}
                {#if acc.auto_start}<span class="badge info">开机自启</span>{/if}
                {#if acc.persona_name}<span class="badge">{acc.persona_name}</span>{/if}
              </span>
            </div>
            <div class="row-actions wrap">
              {#if acc.has_credentials && !acc.session_expired}
                <button class="btn-outline sm" type="button" onclick={() => logoutAccount(acc.id)}>登出</button>
              {/if}
              {#if !acc.has_credentials || acc.session_expired}
                <button class="btn-primary sm" type="button" onclick={() => openQr(acc.id)}>扫码登录</button>
              {/if}
              <select
                class="input sm persona-select"
                value={acc.persona_id || ''}
                onchange={(e) => setAccountPersona(acc, e.currentTarget.value)}
                aria-label={`账号 ${acc.id} 绑定的人设`}
                title="绑定人设（角色来自通讯录，选完即生效）"
              >
                {#if !acc.persona_id}
                  <option value="">（未绑定）</option>
                {/if}
                {#if acc.persona_id && !personas.some((p) => p.id === acc.persona_id)}
                  <!-- 绑定的人设已被删除：补一个失效占位，避免 select 显示第一项误导用户 -->
                  <option value={acc.persona_id}>（已失效：{acc.persona_id}）</option>
                {/if}
                {#each personas as p (p.id)}
                  <option value={p.id}>{personaLabel(p)}</option>
                {/each}
              </select>
              <button class="icon-btn danger" type="button" aria-label={`删除账号 ${acc.id}`} title="删除" onclick={() => removeAccount(acc.id)}>
                {@html `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${I.trash}</svg>`}
              </button>
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </section>

  <details class="settings-group settings-group-pad advanced-group">
    <summary><h2>手动添加账号</h2></summary>
    <p class="field-hint">自动绑定失败时，可以指定账号 ID 和人设。</p>
    <form class="form" onsubmit={submitAdd}>
      <label class="field"><span>Account ID</span><input class="input" type="text" bind:value={wf.id} placeholder="如 wx_001" required /></label>
      <label class="field">
        <span>人设（来自通讯录）</span>
        <select class="input" bind:value={wf.persona_id}>
          <option value="">不指定</option>
          {#each personas as p (p.id)}
            <option value={p.id}>{personaLabel(p)}</option>
          {/each}
        </select>
      </label>
      <div class="settings-row switch-row"><span class="switch-label">启用</span><Switch checked={wf.enabled} onchange={(v) => (wf.enabled = v)} label="启用" /></div>
      <div class="settings-row switch-row"><span class="switch-label">自动启动</span><Switch checked={wf.auto_start} onchange={(v) => (wf.auto_start = v)} label="自动启动" /></div>
      <div class="form-actions">
        <button class="btn-primary" type="submit" disabled={saving}>保存账号</button>
      </div>
    </form>
  </details>

  <!-- 平台选择弹层 -->
  {#if showPlatform}
    <dialog class="settings-group-pad settings-dialog glass-3" aria-labelledby="platform-title"
      use:openDialog oncancel={(e) => { e.preventDefault(); cancelPlatform(); }}>
      <div>
        <div class="section-head">
          <h2 id="platform-title">选择平台</h2>
          <button class="icon-btn" type="button" aria-label="关闭" title="关闭" onclick={cancelPlatform}>
            {@html `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${I.close}</svg>`}
          </button>
        </div>
        <div class="platform-list">
          {#each PLATFORMS as p}
            <button class="platform-item" type="button" onclick={() => choosePlatform(p.key)}>
              <span class="platform-icon" aria-hidden="true">{@html `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${I[p.icon] || I.wechat}</svg>`}</span>
              <span class="platform-main">
                <span class="platform-label">{p.label}</span>
                <span class="platform-desc">{p.desc}</span>
              </span>
              <svg viewBox="0 0 24 24" class="chevron" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{@html I.chevron}</svg>
            </button>
          {/each}
        </div>
      </div>
    </dialog>
  {/if}

  <!-- 扫码登录弹层 -->
  {#if qrAccount}
    <dialog class="settings-group-pad settings-dialog qr-card glass-3" aria-labelledby="qr-title"
      use:openDialog oncancel={(e) => { e.preventDefault(); closeQr(); }}>
      <div>
        <div class="section-head">
          <h2 id="qr-title">微信扫码登录 · {qrAccount}</h2>
          <button class="icon-btn" type="button" title="关闭" onclick={closeQr}>
            {@html `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${I.close}</svg>`}
          </button>
        </div>
        {#if qrImg}
          <img class="qr-img" src={qrImg} alt="微信登录二维码" />
        {:else if qrLink}
          <a class="qr-link" href={qrLink} target="_blank" rel="noopener noreferrer">点击在浏览器打开登录链接</a>
        {:else}
          <div class="qr-wait"><span class="badge info">等待二维码…</span></div>
        {/if}
        {#if qrStatus}
          <p role="status" class="qr-status {qrStatusKind === 'error' ? 'is-error' : qrStatusKind === 'ok' ? 'is-ok' : 'is-muted'}">{qrStatus}</p>
        {/if}
        <div class="qr-actions">
          <button class="btn-outline sm" type="button" onclick={() => openQr(qrAccount)}>
            {qrDone ? (qrImg || qrLink ? '重新获取二维码' : '重试') : '刷新二维码'}
          </button>
        </div>
      </div>
    </dialog>
  {/if}
</SettingsShell>

<style>
  .bind-hero {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--space-3);
    background: color-mix(in srgb, var(--accent) 9%, var(--surface));
  }
  .bind-hero-icon, .platform-icon {
    flex: none;
    display: grid;
    place-items: center;
    width: 48px;
    height: 48px;
    border-radius: var(--radius-lg);
    color: var(--accent-strong);
    background: var(--settings-selected);
  }
  .bind-hero-text { flex: 1 1 190px; min-width: 0; }
  .bind-hero-text h2, .advanced-group h2 { margin: 0; font-size: var(--text-base); font-weight: 650; }
  .bind-hero-desc { margin: var(--space-1) 0 0; color: var(--text-2); font-size: var(--text-13); line-height: 1.5; }
  .advanced-group summary { color: var(--text-1); cursor: pointer; }
  .advanced-group h2 { display: inline; margin-inline-start: var(--space-1); }
  .advanced-group .form { margin-top: var(--space-3); }
  .account-row { flex-wrap: wrap; }
  .account-row .row-main { flex: 1 1 120px; }
  .persona-select { width: 14rem; max-width: 100%; }
  .settings-dialog {
    width: min(420px, calc(100% - 32px));
    max-height: calc(100% - 32px);
    box-sizing: border-box;
    border: 1px solid var(--glass-border-2);
    border-radius: var(--radius-xl);
    color: var(--text-1);
    overflow: auto;
  }
  .settings-dialog::backdrop { background: var(--scrim); }
  .platform-list { display: grid; gap: var(--space-2); }
  .platform-item {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    width: 100%;
    padding: var(--space-3);
    border: 0;
    border-radius: var(--radius-lg);
    background: var(--settings-control);
    color: var(--text-1);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .platform-item:hover { background: var(--settings-selected); }
  .platform-main { display: grid; gap: var(--space-1); flex: 1 1 auto; min-width: 0; }
  .platform-label { font-size: var(--text-sm); font-weight: 650; }
  .platform-desc { color: var(--text-2); font-size: var(--text-xs); line-height: 1.5; }
  .qr-card { text-align: center; }
  .qr-card .section-head { text-align: start; }
  .qr-img {
    display: block;
    width: min(200px, 100%);
    aspect-ratio: 1;
    margin: var(--space-3) auto;
    object-fit: contain;
    border-radius: var(--radius-md);
    background: white;
  }
  .qr-link { display: inline-block; margin: var(--space-3) auto; color: var(--accent-strong); font-size: var(--text-sm); overflow-wrap: anywhere; }
  .qr-wait { padding: var(--space-4); }
  .qr-status { margin: 0; color: var(--text-2); font-size: var(--text-sm); overflow-wrap: anywhere; }
  .qr-status.is-ok { color: var(--success); }
  .qr-status.is-error { color: var(--error); }
  .qr-actions { display: flex; justify-content: center; margin-top: var(--space-3); }
  @media (max-width: 600px) {
    .account-row .row-actions { flex-basis: 100%; }
  }
</style>
