<!-- BackgroundSettings.svelte - 背景图设置面板 -->
<script>
  import { backgroundManager, PRESETS } from '../lib/backgroundManager.js';

  let uploading = $state(false);
  let errorMsg = $state('');
  let okMsg = $state('');
  let fileInput = $state(null);
  let config = $state(backgroundManager.getConfig());
  // 缩略图要跟随当前主题：暗色下用浅色渐变预览会与实际应用不符
  let theme = $state(
    (typeof document !== 'undefined' &&
      document.documentElement.getAttribute('data-theme')) ||
      'light',
  );

  $effect(() => {
    const target = document.documentElement;
    const observer = new MutationObserver(() => {
      theme = target.getAttribute('data-theme') || 'light';
    });
    observer.observe(target, { attributes: true, attributeFilter: ['data-theme'] });
    return () => observer.disconnect();
  });

  function clearMessages() {
    errorMsg = '';
    okMsg = '';
  }

  function openPicker() {
    clearMessages();
    fileInput?.click();
  }

  async function handleUpload(e) {
    const input = e.currentTarget;
    const file = input?.files?.[0];
    // 必须清空 value：否则连续选择同一个文件不会触发 change（二次上传无反应）
    if (input) input.value = '';
    if (!file) return;

    clearMessages();
    uploading = true;
    try {
      await backgroundManager.uploadImage(file);
      config = backgroundManager.getConfig();
      okMsg = '✓ 已设置自定义背景';
    } catch (err) {
      errorMsg = err?.message || '背景上传失败';
    } finally {
      uploading = false;
    }
  }

  function applyPreset(index) {
    clearMessages();
    backgroundManager.setPreset(index);
    config = backgroundManager.getConfig();
  }

  function updateOpacity(e) {
    const val = parseFloat(e.target.value);
    backgroundManager.setOpacity(val);
    config = backgroundManager.getConfig();
  }

  function reset() {
    clearMessages();
    backgroundManager.reset();
    config = backgroundManager.getConfig();
    okMsg = '已恢复默认背景';
  }

  function swatchStyle(preset) {
    if (preset.light === 'none') return 'background: var(--surface-3)';
    return `background: ${preset[theme] || preset.light}`;
  }
</script>

<section class="settings-group settings-group-pad">
  <div class="section-head">
    <h2>背景图设置</h2>
  </div>

  <fieldset class="presets-group">
    <legend class="group-label">预设渐变</legend>
    <div class="presets-grid">
      {#each PRESETS as preset, i}
        <button
          type="button"
          class="preset-btn"
          class:active={(config.type === 'preset' || config.type === 'none') && config.preset === i}
          onclick={() => applyPreset(i)}
          aria-label={preset.name}
          aria-pressed={(config.type === 'preset' || config.type === 'none') && config.preset === i}
        >
          <span class="preset-swatch" style={swatchStyle(preset)} aria-hidden="true"></span>
          <span class="preset-name">{preset.name}</span>
        </button>
      {/each}
    </div>
  </fieldset>

  <!-- 自定义上传 -->
  <div class="upload-group">
    <span class="group-label">上传图片</span>
    <div class="upload-box">
      <input
        bind:this={fileInput}
        type="file"
        accept="image/*"
        onchange={handleUpload}
        disabled={uploading}
        class="file-input"
      />
      <!-- 用可聚焦的按钮触发隐藏 input：键盘用户也能打开文件选择器 -->
      <button
        type="button"
        class="upload-btn"
        onclick={openPicker}
        disabled={uploading}
      >
        {#if uploading}
          上传中…
        {:else}
          选择图片（限 3 MB）
        {/if}
      </button>
    </div>
    {#if errorMsg}
      <div class="badge error upload-status" role="alert">{errorMsg}</div>
    {:else if okMsg}
      <div class="badge ok upload-status" role="status">{okMsg}</div>
    {/if}
  </div>

  <!-- 透明度调节 -->
  <div class="opacity-group">
    <label class="group-label opacity-label" for="opacity-slider">
      <span>背景透明度</span>
      <span class="opacity-val" aria-hidden="true">{Math.round(config.opacity * 100)}%</span>
    </label>
    <input
      type="range"
      id="opacity-slider"
      aria-valuetext={Math.round(config.opacity * 100) + '%'}
      min="0.3"
      max="1"
      step="0.05"
      value={config.opacity}
      oninput={updateOpacity}
      class="settings-range"
      style:--range-progress={((config.opacity - 0.3) / 0.7) * 100 + '%'}
    />
  </div>

  <!-- 重置按钮 -->
  <div class="reset-btn-group">
    <button type="button" onclick={reset} class="reset-btn btn-outline">
      恢复默认
    </button>
  </div>
</section>

<style>
  .group-label {
    display: block;
    margin-bottom: var(--space-2);
    padding: 0;
    color: var(--text-2);
    font-size: var(--text-sm);
    font-weight: 550;
  }

  .presets-group,
  .upload-group,
  .opacity-group {
    margin: 0 0 var(--space-4);
  }

  .presets-group { min-width: 0; padding: 0; border: 0; }

  .presets-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(76px, 100%), 1fr));
    gap: var(--space-2);
  }

  .preset-btn {
    display: grid;
    min-width: 0;
    gap: var(--space-1);
    justify-items: stretch;
    padding: var(--space-1);
    border: 0;
    border-radius: var(--radius-md);
    background: var(--field-fill);
    color: var(--text-2);
    font: inherit;
    font-size: var(--text-xs);
    cursor: pointer;
  }

  .preset-btn:hover { background: var(--row-hover); color: var(--text-1); }
  .preset-btn.active { background: var(--accent-soft); color: var(--accent); font-weight: 650; }

  .preset-btn.active .preset-swatch {
    box-shadow: 0 0 0 1px var(--accent), 0 0 0 2px var(--accent-glow);
  }

  .preset-swatch {
    width: 100%;
    min-height: 48px;
    border-radius: var(--radius-sm);
    box-shadow: inset 0 0 0 1px var(--surface-divider);
  }

  .preset-name { overflow-wrap: anywhere; }

  .file-input { display: none; }

  .upload-btn {
    width: 100%;
    min-height: 48px;
    padding: var(--space-2) var(--space-3);
    border: 0;
    border-radius: var(--radius-sm);
    background: var(--field-fill);
    color: var(--text-1);
    font: inherit;
    font-size: var(--text-sm);
    cursor: pointer;
  }

  .upload-btn:hover:enabled { background: var(--accent-soft); color: var(--accent); }
  .upload-btn:disabled { opacity: 0.6; cursor: wait; }

  .upload-status {
    margin-top: var(--space-2);
    max-width: 100%;
    white-space: normal;
    overflow-wrap: anywhere;
  }

  .opacity-label {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    margin: 0;
  }

  .opacity-val { color: var(--accent); font-variant-numeric: tabular-nums; }

  .reset-btn-group { display: flex; }
  .reset-btn { flex: 1; min-height: 40px; }
</style>
