<script>
  // SettingsAppearance.svelte — 主题与界面
  // 三组：① 外观主题（含真实缩略预览）② 布局模式 ③ 当前生效一览
  // 预览不再画抽象的太阳/月亮图标，也不再写死十六进制色值 ——
  // 而是从 tokens.css 里把那套主题真实的四列底色、主色、气泡色读出来画一张缩略界面。
  // 这样 tokens 一改，预览自动跟着变，永远是「点下去长什么样」。
  import { onMount } from 'svelte';
  import SettingsShell from './SettingsShell.svelte';
  import ThemeToggle from '../ThemeToggle.svelte';
  import './settings-base.css';
  import { I } from './icons.js';
  import { LAYOUTS, LAYOUT_META, layout, setLayout } from '../../lib/layout.svelte.js';

  let { notify, onback } = $props();

  function applyLayout(key) {
    setLayout(key);
    notify(`已切换到「${LAYOUT_META[key].label}」`, 'success');
  }

  const THEME_MODES = [
    { value: 'light', icon: 'sun', label: '浅色', desc: '淡紫白 · 日光' },
    { value: 'dark', icon: 'moon', label: '深色', desc: '午夜紫 · 室内' },
    { value: 'system', icon: 'monitor', label: '跟随系统', desc: '按系统偏好自动切换' },
  ];

  // 从 tokens.css 读真实变量：给一个带 data-theme 的隐身探针，取完就删。
  const PROBE_VARS = [
    '--col-nav-solid', '--col-list-solid', '--col-content-solid',
    '--accent', '--bubble-self-bg', '--bubble-friend-bg', '--border', '--text-1',
  ];
  function readThemeVars(theme) {
    const el = document.createElement('div');
    el.setAttribute('data-theme', theme);
    el.style.cssText = 'position:absolute;left:-9999px;top:0;width:0;height:0;overflow:hidden;pointer-events:none';
    document.body.appendChild(el);
    const cs = getComputedStyle(el);
    const out = {};
    for (const k of PROBE_VARS) out[k] = cs.getPropertyValue(k).trim() || 'transparent';
    el.remove();
    return out;
  }

  let swatch = $state(null); // { light: {...}, dark: {...} }
  let effective = $state('dark');
  let panelOpen = $state(true);

  function syncEffective(mode) {
    return mode === 'system'
      ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : mode;
  }

  function readPanelPref() {
    try {
      const v = localStorage.getItem('cc-panel-open');
      return v === null ? true : v === '1';
    } catch { return true; }
  }

  onMount(() => {
    swatch = { light: readThemeVars('light'), dark: readThemeVars('dark') };
    effective = syncEffective(themeMode);
    panelOpen = readPanelPref();
  });

  let themeMode = $state((() => {
    try {
      const saved = localStorage.getItem('cc-theme');
      return saved === 'dark' || saved === 'light' || saved === 'system' ? saved : 'system';
    } catch { return 'system'; }
  })());

  // 系统偏好变化时，若当前是「跟随系统」，预览与一览也要跟着走
  $effect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const on = () => { if (themeMode === 'system') effective = syncEffective('system'); };
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  });

  function applyTheme(mode) {
    themeMode = mode;
    try {
      localStorage.setItem('cc-theme', mode);
      const eff = syncEffective(mode);
      document.documentElement.setAttribute('data-theme', eff);
      effective = eff;
      notify(mode === 'system' ? `已跟随系统（当前 ${eff === 'dark' ? '深色' : '浅色'}）` : `已切换到${mode === 'dark' ? '深色' : '浅色'}`, 'success');
    } catch { /* ignore */ }
  }
</script>

<SettingsShell title="主题与界面" desc="外观主题、布局模式与当前生效状态" {onback}>
  <section class="card card-pad">
    <div class="section-head">
      <h4>外观主题</h4>
      <span class="head-sub">缩略图就是这套主题的真实配色</span>
    </div>
    <div class="theme-options" role="radiogroup" aria-label="外观主题">
      {#each THEME_MODES as m}
        <button
          class="theme-opt {themeMode === m.value ? 'on' : ''}"
          type="button" role="radio" aria-checked={themeMode === m.value}
          onclick={() => applyTheme(m.value)}
        >
          <span class="theme-opt-main">
            {#if swatch}
              {#if m.value === 'system'}
                <span class="swatch-pair" aria-hidden="true">
                  {@render mini(swatch.light)}
                  {@render mini(swatch.dark)}
                </span>
              {:else}
                {@render mini(swatch[m.value])}
              {/if}
            {:else}
              <span class="theme-swatch placeholder" aria-hidden="true"></span>
            {/if}
            <span class="theme-opt-txt">
              <span class="theme-opt-label">{m.label}</span>
              <span class="theme-opt-desc">{m.desc}</span>
            </span>
          </span>
          {#if themeMode === m.value}
            <svg viewBox="0 0 24 24" class="theme-check" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{@html I.check}</svg>
          {/if}
        </button>
      {/each}
    </div>

    <div class="quick-toggle card-row">
      <div class="row-main">
        <span class="row-title">快速切换</span>
        <span class="row-sub">在浅色与深色之间一键来回</span>
      </div>
      <ThemeToggle />
    </div>
    <p class="hint">选择记忆在本机（cc-theme）；「跟随系统」会在系统主题变化时自动同步。</p>
  </section>

  <section class="card card-pad">
    <div class="section-head">
      <h4>布局模式</h4>
      <span class="head-sub">三档布局共用同一套配色与组件</span>
    </div>
    <div class="layout-options" role="radiogroup" aria-label="布局模式">
      {#each LAYOUTS as key}
        <button
          class="layout-opt {layout.mode === key ? 'on' : ''}"
          type="button" role="radio" aria-checked={layout.mode === key}
          onclick={() => applyLayout(key)}
        >
          {@render layoutPreview(key)}
          <span class="layout-txt">
            <span class="layout-label">{LAYOUT_META[key].label}</span>
            <span class="layout-desc">{LAYOUT_META[key].desc}</span>
          </span>
          {#if layout.mode === key}
            <svg viewBox="0 0 24 24" class="theme-check" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{@html I.check}</svg>
          {/if}
        </button>
      {/each}
    </div>
    <p class="hint">选择记忆在本机（cc-layout），切换后立即生效。</p>
  </section>

  <section class="card card-pad">
    <div class="section-head">
      <h4>当前生效</h4>
      <span class="head-sub">只读，改动请在上面的分组里操作</span>
    </div>
    <dl class="now">
      <div class="now-row">
        <dt>外观</dt>
        <dd>{effective === 'dark' ? '深色 · Midnight Violet' : '浅色 · 淡紫日光'}{themeMode === 'system' ? '（跟随系统）' : ''}</dd>
      </div>
      <div class="now-row">
        <dt>布局</dt>
        <dd>{LAYOUT_META[layout.mode].label}</dd>
      </div>
      <div class="now-row">
        <dt>聊天三栏</dt>
        <dd>导航 · 会话 · 正文{layout.mode === 'panel' ? ` · 状态（${panelOpen ? '展开' : '收起'}）` : '（该布局不显示状态栏）'}</dd>
      </div>
      <div class="now-row">
        <dt>阅读宽度</dt>
        <dd>正文单栏最宽 680px，超宽屏居中不拉长</dd>
      </div>
    </dl>
  </section>
</SettingsShell>

{#snippet mini(v)}
  <!-- 一张 72×44 的缩略界面：导航条 + 会话列 + 正文（含一条 AI 气泡与一条我方气泡）。
       颜色全部来自真实 token，没有一处写死。 -->
  <span class="theme-swatch" aria-hidden="true">
    <span class="sw-nav" style="background:{v['--col-nav-solid']}"></span>
    <span class="sw-list" style="background:{v['--col-list-solid']}">
      <span class="sw-pill" style="background:{v['--accent']};opacity:.85"></span>
      <span class="sw-pill" style="background:{v['--text-1']};opacity:.22"></span>
      <span class="sw-pill" style="background:{v['--text-1']};opacity:.16"></span>
    </span>
    <span class="sw-stage" style="background:{v['--col-content-solid']}">
      <span class="sw-bub" style="background:{v['--bubble-friend-bg']};border-color:{v['--border']}"></span>
      <span class="sw-bub self" style="background:{v['--bubble-self-bg']}"></span>
    </span>
  </span>
{/snippet}

{#snippet layoutPreview(key)}
  <span class="layout-preview" class:col={key === 'immersive'} aria-hidden="true">
    {#if key === 'panel'}
      <span class="lp rail"></span>
      <span class="lp list"></span>
      <span class="lp stage"></span>
      <span class="lp panel"></span>
    {:else if key === 'immersive'}
      <span class="lp bar"></span>
      <span class="lp stage"></span>
      <span class="lp bar low"></span>
    {:else}
      <span class="lp bar"></span>
      <span class="lp-row">
        <span class="lp card"></span>
        <span class="lp card"></span>
        <span class="lp card"></span>
      </span>
      <span class="lp bar low"></span>
    {/if}
  </span>
{/snippet}

<style>
  /* ---- 主题选项 ---- */
  .theme-options { display: flex; flex-direction: column; gap: var(--space-2); }
  .theme-opt {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
    cursor: pointer;
    transition: border-color var(--transition), background var(--transition), transform var(--transition);
    font-family: inherit;
  }
  .theme-opt:hover { background: var(--row-hover); }
  .theme-opt:active { transform: scale(0.995); }
  .theme-opt.on { border-color: var(--accent); background: var(--tint); }
  .theme-opt-main { display: flex; align-items: center; gap: var(--space-3); min-width: 0; }
  .theme-opt-txt { display: flex; flex-direction: column; gap: var(--hair); text-align: left; min-width: 0; }
  .theme-opt-label { font-weight: 600; color: var(--text-1); font-size: var(--text-sm); }
  .theme-opt-desc { font-size: var(--text-xs); color: var(--text-3); }
  .theme-check { flex: none; color: var(--accent); }

  /* ---- 真实缩略预览 ---- */
  .theme-swatch {
    flex: none;
    display: flex;
    width: 72px;
    height: 44px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    overflow: hidden;
  }
  .theme-swatch.placeholder { background: var(--surface-2); }
  .theme-opt.on .theme-swatch { border-color: var(--accent-line); }
  .swatch-pair { flex: none; display: flex; gap: 4px; }
  .swatch-pair .theme-swatch { width: 40px; }
  .swatch-pair .theme-swatch .sw-list { display: none; }

  .sw-nav { width: 12px; flex: none; }
  .sw-list {
    width: 22px;
    flex: none;
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
    gap: 3px;
    padding: 5px 4px;
  }
  .sw-pill { height: 3px; border-radius: 1px; width: 100%; }
  .sw-stage {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 4px;
    padding: 5px 5px;
  }
  .sw-bub { height: 8px; border-radius: 3px; width: 78%; border: 1px solid transparent; }
  .sw-bub.self { width: 56%; align-self: flex-end; }

  /* ---- 布局预览 ---- */
  .layout-options { display: flex; flex-direction: column; gap: var(--space-2); }
  .layout-opt {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
    cursor: pointer;
    transition: border-color var(--transition), background var(--transition);
    font-family: inherit;
  }
  .layout-opt:hover { background: var(--row-hover); }
  .layout-opt.on { border-color: var(--accent); background: var(--tint); }
  .layout-txt { display: flex; flex-direction: column; gap: var(--hair); text-align: left; min-width: 0; flex: 1; }
  .layout-label { font-weight: 500; color: var(--text-1); font-size: var(--text-sm); }
  .layout-desc { font-size: var(--text-xs); color: var(--text-3); }

  /* 布局示意按真实比例画：panel = 导航/会话/正文/状态四柱；
     immersive = 顶栏/正文/输入条；today = 顶栏/三卡/底栏。 */
  .layout-preview {
    flex: none;
    display: flex;
    gap: 2px;
    width: 64px;
    height: 40px;
    padding: 3px;
    border: 1px solid var(--border);
    border-radius: var(--radius-xs);
    background: var(--surface-2);
  }
  .layout-preview.col { flex-direction: column; }
  .lp { border-radius: 1px; background: var(--surface-3); }
  .layout-opt.on .lp { background: var(--accent-soft); }
  .lp.rail { width: 5px; flex: none; }
  .lp.list { width: 10px; flex: none; }
  .lp.panel { width: 8px; flex: none; }
  .lp.stage { flex: 1; }
  .lp.bar { height: 4px; flex: none; }
  .lp.bar.low { opacity: .7; }
  .lp-row { display: flex; gap: 2px; flex: 1; }
  .lp.card { flex: 1; }

  /* ---- 当前生效一览 ---- */
  .now { margin: 0; display: flex; flex-direction: column; }
  .now-row {
    display: flex;
    align-items: baseline;
    gap: var(--space-3);
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--border);
  }
  .now-row:last-child { border-bottom: none; padding-bottom: 0; }
  .now-row dt {
    flex: none;
    width: 76px;
    font-size: var(--text-2xs);
    letter-spacing: var(--tracking-wide);
    color: var(--text-3);
  }
  .now-row dd {
    margin: 0;
    flex: 1;
    min-width: 0;
    font-size: var(--text-13);
    line-height: 1.6;
    color: var(--text-1);
  }

  .quick-toggle { margin-top: var(--space-3); border-top: 1px solid var(--border); padding-top: var(--space-3); }
  .quick-toggle > :global(.theme-toggle) { flex: none; }
</style>
