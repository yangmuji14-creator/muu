<script>
  // SettingsIndex.svelte — 设置中心分类导航首页 (窄屏使用)
  // 分类数据与侧栏版共用 lib/settingsNav.svelte.js, 避免两处维护。
  import './settings-base.css';
  import { I } from './icons.js';
  import { SETTINGS_GROUPS as GROUPS } from '../../lib/settingsNav.svelte.js';

  let { onopen } = $props(); // (key) => void

  function renderIcon(name, size) {
    return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${I[name] || ''}</svg>`;
  }
</script>

<div class="settings-main">
  <header class="index-head">
    <span class="index-eyebrow">设置</span>
    <h2>全部设置</h2>
    <p>管理模型、对话、扩展与系统偏好</p>
  </header>

  <div class="index-groups">
    {#each GROUPS as g}
      <section class="card index-group" aria-label={g.title}>
        <div class="group-head">
          <span class="group-icon" aria-hidden="true">{@html renderIcon(g.icon, 16)}</span>
          <div class="group-head-txt">
            <span class="group-title">{g.title}</span>
            <span class="group-desc">{g.desc}</span>
          </div>
        </div>
        <div class="card-list">
          {#each g.items as item}
            <button class="card-row group-row" type="button" onclick={() => onopen(item.key)}>
              <span class="row-icon" aria-hidden="true">{@html renderIcon(item.icon, 18)}</span>
              <span class="row-main">
                <span class="row-title">{item.title}</span>
                <span class="row-sub">{item.desc}</span>
              </span>
              <svg viewBox="0 0 24 24" class="chevron" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{@html I.chevron}</svg>
            </button>
          {/each}
        </div>
      </section>
    {/each}
  </div>
</div>

<style>
  .index-head { padding: 0 0 var(--space-5); }
  .index-eyebrow {
    display: block;
    margin-bottom: var(--optical-6);
    font-size: var(--text-2xs);
    font-weight: 500;
    letter-spacing: var(--tracking-wider);
    color: var(--text-3);
  }
  .index-head h2 {
    margin: 0;
    font-size: var(--text-display);
    font-weight: 600;
    letter-spacing: var(--tracking-tight);
    line-height: 1.12;
    color: var(--text-1);
  }
  .index-head p { margin: var(--optical-6) 0 0; font-size: var(--text-13); line-height: 1.65; color: var(--text-2); }

  .index-groups { display: flex; flex-direction: column; gap: var(--space-2); }

  .index-group { padding: var(--space-4) 0 var(--space-2); }

  .group-head { display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-3); }
  .group-icon {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    border-radius: var(--radius-xs);
    background: var(--surface-2);
    color: var(--text-2);
  }
  .group-head-txt { display: flex; align-items: baseline; gap: var(--space-2); min-width: 0; flex-wrap: wrap; }
  .group-title {
    font-weight: 500;
    color: var(--text-1);
    font-size: var(--text-2xs);
    letter-spacing: var(--tracking-wider);
    text-transform: uppercase;
  }
  .group-desc { font-size: var(--text-2xs); color: var(--text-3); }

  .group-row { cursor: pointer; transition: background var(--transition), border-color var(--transition); }
  .group-row:hover { background: var(--row-hover); border-color: var(--border-strong); }
  .group-row:focus-visible { box-shadow: var(--focus-ring); }
</style>
