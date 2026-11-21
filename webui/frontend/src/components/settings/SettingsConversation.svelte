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

  function rangeProgress(value, min, max) {
    const ratio = value == null || value === '' ? NaN : (value - min) / (max - min);
    return Number.isFinite(ratio) ? `${ratio * 100}%` : '50%';
  }

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

<SettingsShell showFooter={!loading && sections.length > 0} title="对话设置" desc="回复风格、智能开关与主动消息偏好" {onback}>
  {#if loading}
    <div class="skeleton-list" aria-label="加载中">
      {#each [0, 1, 2] as n}
        <div class="settings-group settings-group-pad skeleton-card">
          <div class="sk sk-title" style="width:{60 - n * 10}%"></div>
          <div class="sk sk-line" style="width:100%"></div>
          <div class="sk sk-line" style="width:80%"></div>
        </div>
      {/each}
    </div>
  {:else if !sections.length}
    <div class="settings-group settings-group-pad">
      <EmptyState icon="message" title="没有可配置的设置项" desc="后端未返回任何设置项" compact />
    </div>
  {:else}
    <form class="conv-form" onsubmit={(e) => { e.preventDefault(); submit(); }}>
      {#each sections as [sec, fields]}
        <section class="settings-group settings-group-pad">
          <div class="section-head">
            <h2>{sec}</h2>
            {#if fields.some((f) => f.live)}
              <span class="badge info">实时生效</span>
            {/if}
          </div>
          <div class="card-list">
            {#each fields as f (f.key)}
              <div class="settings-row conv-field">
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
                        class="settings-range"
                        style:--range-progress={rangeProgress(values[f.key], f.min, f.max)}
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
                    aria-label={f.label || f.key}
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
  {#snippet footer()}
    <div class="save-bar">
      <button class="btn-primary" type="button" onclick={submit} disabled={saving}>
        {saving ? '保存中…' : '保存对话设置'}
      </button>
      <button class="btn-outline" type="button" onclick={reset} disabled={saving}>重置</button>
    </div>
  {/snippet}
</SettingsShell>

<style>
  .conv-form, .skeleton-list { display: grid; gap: var(--space-4); }
  .conv-field { justify-content: space-between; flex-wrap: wrap; }
  .conv-label { display: grid; gap: var(--space-1); flex: 1 1 170px; min-width: 0; }
  .conv-name { color: var(--text-1); font-size: var(--text-sm); font-weight: 620; }
  .conv-hint { color: var(--text-2); font-size: var(--text-xs); line-height: 1.5; }
  .num-control { display: flex; flex-direction: column; gap: var(--space-3); flex: 1 1 128px; max-width: 240px; min-width: 0; }
  .num-value { text-align: center; max-width: 100px; align-self: flex-end; font-variant-numeric: tabular-nums; }
  .conv-text { flex: 1 1 128px; max-width: 240px; }
  .save-bar { display: flex; gap: var(--space-2); flex-wrap: wrap; }
  .skeleton-card { display: grid; gap: var(--space-3); }
  .sk { border-radius: var(--radius-pill); background: var(--field-fill); }
  .sk-title { height: 16px; }
  .sk-line { height: 12px; }
</style>
