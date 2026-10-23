<script>
  // SettingsConversation.svelte — 对话设置 (schema 动态表单, 按 section 分组卡片)
  // - 按后端 /api/schema 的 section 字段把字段分为多张卡片
  // - bool 用共享 Switch; int/float 用精致滑杆 + 数值输入
  // - 加载用骨架屏, 保存用固定底栏 + live 热更新徽标
  import SettingsShell from './SettingsShell.svelte';
  import EmptyState from './EmptyState.svelte';
  import Switch from '../Switch.svelte';
  import './settings-base.css';
  import { settingsApi } from '../../lib/settingsApi.js';

  let { notify, onback } = $props();

  let schema = $state(null);
  let values = $state({});
  let loading = $state(true);
  let saving = $state(false);

  // 进入页面加载 (仅一次)
  $effect(() => {
    let alive = true;
    load();
    async function load() {
      loading = true;
      try {
        const rs = await settingsApi.schema();
        const rv = await settingsApi.get();
        if (!alive) return;
        if (rs.ok && Array.isArray(rs.data?.schema)) schema = rs.data.schema;
        if (rv.ok && rv.data?.values) values = { ...rv.data.values };
      } catch {
        /* 后端不可达时保持空, 由空状态兜底 */
      } finally {
        if (alive) loading = false;
      }
    }
    return () => (alive = false);
  });

  // 按 section 分组, 保持 schema 原顺序
  let sections = $derived.by(() => {
    if (!Array.isArray(schema)) return [];
    const map = new Map();
    for (const f of schema) {
      const sec = f.section || '通用设置';
      if (!map.has(sec)) map.set(sec, []);
      map.get(sec).push(f);
    }
    return [...map.entries()];
  });

  async function reset() {
    try {
      const r = await settingsApi.get();
      if (r.ok && r.data?.values) { values = { ...r.data.values }; notify('已恢复为最近保存值', 'info'); }
    } catch { notify('重置失败', 'error'); }
  }

  async function submit() {
    saving = true;
    try {
      const r = await settingsApi.save(values);
      if (r.ok) notify('设置已保存', 'success');
      else notify(errMsg(r, '保存失败'), 'error');
    } finally { saving = false; }
  }

  function errMsg(err, fallback) {
    const m = err?.data?.error || err?.data?.message || err?.data?.detail || err?.data;
    if (typeof m === 'string' && m) return m;
    return fallback || (err?.status ? `请求失败（HTTP ${err.status}）` : String(err?.message ?? err));
  }
</script>

<SettingsShell title="对话设置" desc="回复风格、智能开关与主动消息偏好" {onback}>
  {#if loading}
    <div class="skeleton-list" aria-label="加载中">
      {#each [0, 1, 2] as n}
        <div class="card card-pad skeleton-card">
          <div class="sk sk-title" style="width:{60 - n * 10}%"></div>
          <div class="sk sk-line" style="width:100%"></div>
          <div class="sk sk-line" style="width:80%"></div>
        </div>
      {/each}
    </div>
  {:else if !sections.length}
    <div class="card card-pad">
      <EmptyState icon="message" title="没有可配置的设置项" desc="后端未返回任何设置项" compact />
    </div>
  {:else}
    <form class="conv-form" onsubmit={(e) => { e.preventDefault(); submit(); }}>
      {#each sections as [sec, fields]}
        <section class="card card-pad conv-section">
          <div class="section-head">
            <h4>{sec}</h4>
            {#if fields.some((f) => f.live)}
              <span class="badge info live-badge">实时生效</span>
            {/if}
          </div>
          <div class="conv-fields">
            {#each fields as f, i}
              <div class="conv-field" class:has-divider={i > 0}>
                <div class="conv-label">
                  <span class="conv-name">{f.label || f.key}</span>
                  {#if f.hint}<span class="conv-hint">{f.hint}</span>{/if}
                </div>

                {#if f.type === 'bool' || f.type === 'boolean'}
                  <Switch checked={!!values[f.key]} onchange={(v) => (values[f.key] = v)} label={f.label || f.key} />
                {:else if f.type === 'float' || f.type === 'int'}
                  <div class="num-control">
                    <input
                      class="input num-value"
                      type="number"
                      step={f.step ?? (f.type === 'float' ? 'any' : '1')}
                      min={f.min}
                      max={f.max}
                      value={values[f.key]}
                      oninput={(e) => (values[f.key] = e.currentTarget.value)}
                      aria-label={f.label || f.key}
                    />
                    {#if f.min !== undefined && f.max !== undefined}
                      <input
                        class="num-slider"
                        type="range"
                        min={f.min}
                        max={f.max}
                        step={f.step ?? (f.type === 'float' ? 'any' : '1')}
                        value={values[f.key]}
                        oninput={(e) => (values[f.key] = Number(e.currentTarget.value))}
                        aria-label={f.label || f.key}
                      />
                    {/if}
                  </div>
                {:else}
                  <input
                    class="input conv-text"
                    type="text"
                    value={values[f.key] ?? ''}
                    oninput={(e) => (values[f.key] = e.currentTarget.value)}
                    placeholder={f.placeholder || ''}
                  />
                {/if}
              </div>
            {/each}
          </div>
        </section>
      {/each}
    </form>
  {/if}
</SettingsShell>

{#if !loading && sections.length}
  <div class="save-bar card">
    <button class="btn-primary" type="button" onclick={submit} disabled={saving}>
      {saving ? '保存中…' : '保存对话设置'}
    </button>
    <button class="btn-outline" type="button" onclick={reset} disabled={saving}>重置</button>
  </div>
{/if}

<style>
  .conv-form { display: flex; flex-direction: column; gap: var(--space-4); }
  .live-badge { flex: none; }
  .conv-fields { display: flex; flex-direction: column; }
  .conv-field {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-4);
    padding: var(--space-3) 0;
  }
  .conv-field.has-divider { border-top: 1px solid var(--border); }
  .conv-label { display: flex; flex-direction: column; gap: var(--optical-2); min-width: 0; flex: 1; }
  .conv-name { font-weight: 600; color: var(--text-1); font-size: var(--text-sm); }
  .conv-hint { font-size: var(--text-xs); color: var(--text-3); line-height: var(--leading-snug); }

  .num-control { display: flex; flex-direction: column; gap: var(--space-2); flex: none; max-width: 240px; min-width: 180px; }
  .num-value { text-align: center; max-width: 130px; align-self: flex-end; }
  /* 滑杆原来只设了 accent-color, 用的是浏览器原生样式:
     轨道是 8px 圆头厚条、滑块是圆润的水滴 —— 在一个通篇 2-6px 方角的
     界面里, 它是最不像「这套设计语言」的一个控件, 而且是设置页里
     出现次数最多的控件 (一屏 6 条)。
     改为自绘: 轨道 3px 方角 + 冷蓝填充, 滑块 10x16 方角 + 1px 描边,
     hover/active 时滑块变高一点作为触感反馈。 */
  .num-slider {
    -webkit-appearance: none;
    appearance: none;
    width: 100%;
    height: 18px;
    margin: 0;
    background: transparent;
    cursor: pointer;
  }
  .num-slider::-webkit-slider-runnable-track {
    height: 3px;
    background: var(--surface-3);
    border-radius: var(--radius-xs);
  }
  .num-slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 10px;
    height: 16px;
    margin-top: -6.5px;
    background: var(--accent);
    border: 1px solid var(--accent-strong);
    border-radius: var(--radius-xs);
    transition: background var(--transition), transform var(--transition);
  }
  .num-slider:hover::-webkit-slider-thumb { background: var(--accent-strong); }
  .num-slider:active::-webkit-slider-thumb { transform: scaleY(1.1); }
  .num-slider::-moz-range-track {
    height: 3px;
    background: var(--surface-3);
    border-radius: var(--radius-xs);
  }
  .num-slider::-moz-range-progress {
    height: 3px;
    background: var(--accent);
    border-radius: var(--radius-xs);
  }
  .num-slider::-moz-range-thumb {
    width: 8px;
    height: 14px;
    background: var(--accent);
    border: 1px solid var(--accent-strong);
    border-radius: var(--radius-xs);
  }
  .num-slider:focus-visible { outline: none; box-shadow: var(--focus-ring); }

  .conv-text { max-width: 240px; }

  /* 骨架屏 */
  .skeleton-list { display: flex; flex-direction: column; gap: var(--space-4); }
  .skeleton-card { display: flex; flex-direction: column; gap: var(--space-3); }
  .sk { border-radius: var(--radius-sm); background: var(--surface-3); animation: sk-pulse 1.4s var(--ease-in-out) infinite; }
  .sk-title { height: 16px; }
  .sk-line { height: 12px; }
  @keyframes sk-pulse { 0%,100% { opacity: 0.5; } 50% { opacity: 1; } }

  /* 底部固定保存条
     .card / .btn-* 已收归 .settings-main 作用域, 而这条保存条挂在
     SettingsShell 外面, 所以这里自带背景与按钮样式。
     它是 sticky 到内容区底部的 chrome, 用 glass-1 让下面的表单透出来 ——
     实心底色会把最后一行字段切成两半, 玻璃反而让"还有内容在下面"可读。 */
  .save-bar {
    position: sticky;
    bottom: 0;
    z-index: var(--z-sticky);
    display: flex;
    gap: var(--space-2);
    margin-top: var(--space-4);
    padding: var(--space-3);
    background: var(--surface);
    border: 1px solid var(--glass-border-2);
    border-radius: var(--radius);
    box-shadow: var(--shadow-md);
  }
  @supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
    .save-bar {
      background: var(--glass-1);
      -webkit-backdrop-filter: blur(var(--glass-blur-1)) saturate(var(--glass-sat-1));
      backdrop-filter: blur(var(--glass-blur-1)) saturate(var(--glass-sat-1));
    }
  }
  @media (prefers-reduced-transparency: reduce) {
    .save-bar {
      background: var(--surface);
      -webkit-backdrop-filter: none;
      backdrop-filter: none;
    }
  }
  .save-bar .btn-primary,
  .save-bar .btn-outline {
    flex: 1;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    height: var(--btn-h-lg);
    padding: 0 var(--space-4);
    border-radius: var(--btn-radius);
    font-family: inherit;
    font-size: var(--text-13);
    font-weight: 500;
    cursor: pointer;
    transition: background var(--transition), border-color var(--transition), transform var(--transition);
  }
  .save-bar .btn-primary {
    background: var(--accent);
    color: var(--on-accent);
    border: 1px solid transparent;
  }
  .save-bar .btn-primary:hover { background: var(--accent-strong); }
  .save-bar .btn-primary:disabled { opacity: 0.5; cursor: default; }
  .save-bar .btn-outline {
    background: var(--btn-outline-bg);
    color: var(--btn-outline-text);
    border: 1px solid var(--btn-outline-border);
  }
  .save-bar .btn-outline:hover { background: var(--btn-outline-hover); border-color: var(--border-strong); }
  .save-bar .btn-primary:active,
  .save-bar .btn-outline:active { transform: scale(0.98); }
</style>
