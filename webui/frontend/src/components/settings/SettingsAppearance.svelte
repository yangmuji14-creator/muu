<script>
  import { onMount } from 'svelte';
  import SettingsShell from './SettingsShell.svelte';
  import './settings-base.css';
  import { I } from './icons.js';
  import { LAYOUTS, LAYOUT_META, layout, setLayout } from '../../lib/layout.svelte.js';
  import BackgroundSettings from '../BackgroundSettings.svelte';

  let { notify, onback } = $props();

  function applyLayout(key) {
    setLayout(key);
    notify(`已切换到「${LAYOUT_META[key].label}」`, 'success');
  }

  const THEME_MODES = [
    { value: 'light', label: '浅色' },
    { value: 'dark', label: '深色' },
    { value: 'system', label: '跟随系统' },
  ];

  // 从 tokens.css 读真实变量：给一个带 data-theme 的隐身探针，取完就删。
  const PROBE_VARS = [
    '--col-nav-solid', '--col-list-solid', '--col-content-solid',
    '--accent', '--bubble-self-bg', '--bubble-friend-bg', '--border', '--text-1',
  ];
  function readThemeVars(theme, accentKey, vars = PROBE_VARS) {
    const el = document.createElement('div');
    el.setAttribute('data-theme', theme);
    // 缩略图必须带上当前强调色，否则换色后预览仍画默认的琥珀
    el.setAttribute('data-accent', accentKey);
    el.style.cssText = 'position:absolute;left:-9999px;top:0;width:0;height:0;overflow:hidden;pointer-events:none';
    document.body.appendChild(el);
    const cs = getComputedStyle(el);
    const out = {};
    for (const k of vars) out[k] = cs.getPropertyValue(k).trim() || 'transparent';
    el.remove();
    return out;
  }

  let swatch = $state(null); // { light: {...}, dark: {...} }
  let effective = $state('dark');
  let palettes = $state({});
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

  // 外壳顶栏的 ThemeToggle 也会改 cc-theme（它写具体 light/dark）。它改完会
  // 派发 cc-theme-change；这里同步 themeMode/effective，否则设置页会一直
  // 高亮「跟随系统」、而页面其实已经是固定主题。
  $effect(() => {
    const onThemeChange = (event) => {
      const mode = event?.detail;
      if (mode !== 'light' && mode !== 'dark' && mode !== 'system') return;
      themeMode = mode;
      effective = syncEffective(mode);
    };
    window.addEventListener('cc-theme-change', onThemeChange);
    return () => window.removeEventListener('cc-theme-change', onThemeChange);
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

  // ---- 强调色 ----
  // data-accent 挂在 <html> 上，theme-liquid.css 里按主题分别给出变量，
  // 深色模式不再被锁死在琥珀色。
  const ACCENTS = [
    { key: 'amber', label: '琥珀' },
    { key: 'blue', label: '海蓝' },
    { key: 'teal', label: '青绿' },
    { key: 'rose', label: '玫瑰' },
    { key: 'violet', label: '紫罗兰' },
    { key: 'slate', label: '石墨' },
  ];
  let accent = $state((() => {
    try {
      const saved = localStorage.getItem('cc-accent');
      return ACCENTS.some((a) => a.key === saved) ? saved : 'amber';
    } catch { return 'amber'; }
  })());

  function applyAccent(key) {
    accent = key;
    try {
      localStorage.setItem('cc-accent', key);
      document.documentElement.setAttribute('data-accent', key);
      const label = ACCENTS.find((a) => a.key === key)?.label ?? key;
      notify(`强调色已切换为「${label}」`, 'success');
    } catch { /* ignore */ }
  }

  $effect(() => {
    // 进入本页时同步强调色到 DOM，并按新颜色重算主题缩略图
    // （此前 swatch 只在 onMount 算一次，换海蓝后预览仍是琥珀）
    const key = accent;
    try {
      document.documentElement.setAttribute('data-accent', key);
      swatch = {
        light: readThemeVars('light', key),
        dark: readThemeVars('dark', key),
      };
    } catch { /* ignore */ }
  });
  $effect(() => {
    // 强调色样本只需要主色与自己的气泡色；只探这两个，别为 6 个色各读 8 个变量。
    const PALETTE_VARS = ['--accent', '--bubble-self-bg'];
    palettes = Object.fromEntries(
      ACCENTS.map(({ key }) => [key, readThemeVars(effective, key, PALETTE_VARS)]),
    );
  });
</script>

<SettingsShell title="主题与界面" desc="自定义主题、强调色、布局和背景图" {onback}>
  <section class="settings-group settings-group-pad">
    <div class="section-head">
      <h2>外观主题</h2>

    </div>
    <div class="theme-options" role="group" aria-label="外观主题">
      {#each THEME_MODES as m}
        <button
          class="theme-opt {themeMode === m.value ? 'on' : ''}"
          type="button" aria-pressed={themeMode === m.value}
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
            </span>
          </span>
          {#if themeMode === m.value}
            <svg viewBox="0 0 24 24" class="theme-check" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{@html I.check}</svg>
          {/if}
        </button>
      {/each}
    </div>

    <div class="settings-row quick-toggle">
      <div class="row-main">
        <span class="row-title">快速切换</span>
        <span class="row-sub">在浅色与深色之间一键来回</span>
      </div>
      <button class="btn-outline sm" type="button" onclick={() => applyTheme(effective === 'light' ? 'dark' : 'light')}>
        {effective === 'light' ? '切换到深色' : '切换到浅色'}
      </button>
    </div>
  </section>

  <section class="settings-group settings-group-pad">
    <div class="section-head">
      <h2>强调色</h2>
      <span class="head-sub">适用于按钮、选中状态和发出的消息。</span>
    </div>
    <div class="accent-row" role="radiogroup" aria-label="强调色">
      {#each ACCENTS as a}
        <button
          class="accent-opt {accent === a.key ? 'on' : ''}"
          type="button" role="radio" aria-checked={accent === a.key}
          title={a.label}
          onclick={() => applyAccent(a.key)}
        >
          <span class="accent-sample" aria-hidden="true">
            <span class="accent-dot" style:background={palettes[a.key]?.['--accent']}></span>
            <span class="accent-bubble" style:background={palettes[a.key]?.['--bubble-self-bg']}></span>
          </span>
          <span class="accent-label">{a.label}</span>
        </button>
      {/each}
    </div>
  </section>

  <section class="settings-group settings-group-pad">
    <div class="section-head">
      <h2>布局模式</h2>
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
  </section>

  <BackgroundSettings />

  <section class="settings-group settings-group-pad">
    <div class="section-head">
      <h2>当前生效</h2>
    </div>
    <dl class="card-list now">
      <div class="settings-row now-row">
        <dt>外观</dt>
        <dd>{effective === 'dark' ? '深色 · Midnight Violet' : '浅色 · 淡紫日光'}{themeMode === 'system' ? '（跟随系统）' : ''}</dd>
      </div>
      <div class="settings-row now-row">
        <dt>布局</dt>
        <dd>{LAYOUT_META[layout.mode].label}</dd>
      </div>
      <div class="settings-row now-row">
        <dt>聊天三栏</dt>
        <dd>导航 · 会话 · 正文{layout.mode === 'panel' ? ` · 状态（${panelOpen ? '展开' : '收起'}）` : '（该布局不显示状态栏）'}</dd>
      </div>
      <div class="settings-row now-row">
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
  <span class="layout-preview" aria-hidden="true">
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
  .theme-options, .layout-options, .accent-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 146px), 1fr));
    gap: var(--space-2);
  }
  .theme-options { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .accent-row { grid-template-columns: repeat(auto-fit, minmax(min(100%, 92px), 1fr)); }
  .theme-opt, .layout-opt, .accent-opt {
    position: relative;
    display: grid;
    align-content: start;
    gap: var(--space-2);
    min-width: 0;
    padding: var(--space-2);
    border: 1px solid transparent;
    border-radius: var(--radius-lg);
    background: var(--settings-control);
    color: var(--text-1);
    font: inherit;
    text-align: left;
    cursor: pointer;
    transition: background var(--transition), border-color var(--transition);
  }
  .theme-opt:hover, .layout-opt:hover, .accent-opt:hover { background: var(--field-fill-focus); }
  .theme-opt.on, .layout-opt.on, .accent-opt.on { border-color: var(--accent); background: var(--settings-selected); }
  .theme-opt-main, .layout-txt { display: grid; gap: var(--space-2); min-width: 0; }
  .theme-opt-txt, .layout-txt { padding: var(--space-1); }
  .theme-opt-label, .layout-label, .accent-label { display: block; font-size: var(--text-13); font-weight: 650; }
  .layout-label { padding-inline-end: 28px; }
  .layout-desc { color: var(--text-2); font-size: var(--text-xs); line-height: 1.5; }
  .theme-check {
    position: absolute;
    top: var(--space-3);
    right: var(--space-3);
    padding: 3px;
    box-sizing: content-box;
    border-radius: var(--radius-pill);
    background: var(--accent);
    color: var(--on-accent);
  }
  .theme-swatch {
    display: grid;
    grid-template-columns: 14% 29% 1fr;
    height: 78px;
    min-width: 0;
    overflow: hidden;
    border-radius: var(--radius-md);
  }
  .theme-swatch.placeholder { background: var(--surface-3); }
  .swatch-pair { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 2px; }
  .sw-list, .sw-stage { display: grid; align-content: center; gap: var(--space-1); min-width: 0; padding: var(--space-1); }
  .sw-pill { display: block; height: 4px; border-radius: var(--radius-pill); }
  .sw-bub { display: block; width: 65%; height: 13px; border: 1px solid transparent; border-radius: var(--radius-md); }
  .sw-bub.self { width: 55%; justify-self: end; }
  .quick-toggle { justify-content: space-between; flex-wrap: wrap; margin-top: var(--space-2); }
  .accent-opt { justify-items: center; text-align: center; }
  .accent-sample { display: flex; align-items: center; gap: var(--space-1); min-height: 30px; }
  .accent-dot { width: 22px; height: 22px; border-radius: 50%; }
  .accent-bubble { width: 24px; height: 13px; border-radius: var(--radius-pill); }
  .layout-preview {
    display: flex; gap: var(--space-1); height: 64px; padding: var(--space-2);
    border-radius: var(--radius-md); background: var(--surface-2);
  }
  .layout-preview:has(.bar) { flex-direction: column; }
  .lp { display: block; min-width: 0; border-radius: var(--radius-sm); background: var(--surface-3); }
  .lp.rail, .lp.bar { background: var(--accent-soft); }
  .lp.rail { flex: 1; }
  .lp.list, .lp.panel { flex: 2; }
  .lp.stage { flex: 4; background: var(--surface); }
  .lp.bar { height: 8px; }
  .lp.bar.low { opacity: .6; }
  .lp-row { display: flex; gap: var(--space-1); flex: 1; }
  .lp.card { flex: 1; background: var(--surface); }
  .now { margin: 0; }
  .now-row { justify-content: space-between; flex-wrap: wrap; font-size: var(--text-13); }
  .now-row dt { flex: 0 0 auto; color: var(--text-2); }
  .now-row dd { margin: 0; overflow-wrap: anywhere; }
  @media (max-width: 600px) {
    .theme-swatch { height: 52px; }
    .theme-opt-txt { padding-inline: 0; }
    .theme-opt .theme-check { top: var(--space-2); right: var(--space-2); width: 14px; height: 14px; }
  }
</style>
