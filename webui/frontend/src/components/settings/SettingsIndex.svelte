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
    <h1>设置</h1>
  </header>

  <div class="index-groups">
    {#each GROUPS as g}
      <section class="settings-group settings-group-pad" aria-label={g.title}>
        <div class="group-head">
          <div class="group-head-txt">
            <h2 class="group-title">{g.title}</h2>
            <span class="group-desc">{g.desc}</span>
          </div>
        </div>
        <div class="card-list">
          {#each g.items as item}
            <button class="settings-row group-row" type="button" onclick={() => onopen(item.key)}>
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
  .index-head h1 { margin: 0; font-size: var(--text-display); font-weight: 680; letter-spacing: var(--tracking-tight); }
  .index-groups { display: grid; gap: var(--space-4); }
  .group-head { margin-bottom: var(--space-3); }
  .group-head-txt { display: flex; align-items: baseline; gap: var(--space-2); flex-wrap: wrap; }
  .group-title { margin: 0; font-size: var(--text-sm); font-weight: 650; }
  .group-desc { font-size: var(--text-xs); color: var(--text-2); }
</style>
