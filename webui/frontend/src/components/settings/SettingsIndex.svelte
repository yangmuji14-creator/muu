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
    <h2>设置</h2>
    <p>管理模型、对话、扩展与系统偏好</p>
  </header>

  <div class="index-groups">
    {#each GROUPS as g}
      <section class="card index-group" aria-label={g.title}>
        <div class="group-head">
          <span class="group-icon" aria-hidden="true">{@html renderIcon(g.icon, 18)}</span>
          <div class="group-head-txt">
            <span class="group-title">{g.title}</span>
            <span class="group-desc">{g.desc}</span>
          </div>
        </div>
        <div class="card-list">
          {#each g.items as item}
            <button class="card-row group-row" type="button" onclick={() => onopen(item.key)}>
              <span class="row-icon" aria-hidden="true">{@html renderIcon(item.icon, 20)}</span>
              <span class="row-main">
                <span class="row-title">{item.title}</span>
                <span class="row-sub">{item.desc}</span>
              </span>
              <svg viewBox="0 0 24 24" class="chevron" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{@html I.chevron}</svg>
            </button>
          {/each}
        </div>
      </section>
    {/each}
  </div>
</div>

<style>
  .index-head { padding: var(--space-2) 0 var(--space-4); }
  .index-head h2 { margin: 0; font-size: var(--text-xl); font-weight: 700; color: var(--text-1); }
  .index-head p { margin: 2px 0 0; font-size: var(--text-xs); color: var(--text-3); }

  .index-groups { display: flex; flex-direction: column; gap: var(--space-4); }

  .index-group { padding: var(--card-pad); }

  .group-head { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-3); }
  .group-icon {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 34px;
    height: 34px;
    border-radius: var(--radius);
    background: var(--tint);
    color: var(--tab-active);
  }
  .group-head-txt { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
  .group-title { font-weight: 700; color: var(--text-1); font-size: var(--text-base); }
  .group-desc { font-size: var(--text-xs); color: var(--text-3); }

  .group-row { cursor: pointer; transition: background var(--transition), transform var(--transition); }
  .group-row:hover { background: var(--row-hover); transform: translateX(2px); }
  .group-row:focus-visible { box-shadow: var(--focus-ring); }
</style>
