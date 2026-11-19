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

<section class="card card-pad bg-settings">
  <div class="section-head">
    <h4>📸 背景图设置</h4>
    <span class="head-sub">自定义应用背景，支持图片或渐变</span>
  </div>

  <!-- 预设渐变 -->
  <div class="presets-group">
    <label>预设渐变</label>
    <div class="presets-grid">
      {#each PRESETS as preset, i}
        <button
          type="button"
          class="preset-btn"
          class:active={(config.type === 'preset' || config.type === 'none') && config.preset === i}
          style={swatchStyle(preset)}
          title={preset.name}
          onclick={() => applyPreset(i)}
          aria-label={preset.name}
          aria-pressed={(config.type === 'preset' || config.type === 'none') && config.preset === i}
        >
          <span class="preset-name">{preset.name}</span>
        </button>
      {/each}
    </div>
  </div>

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
          💾 选择图片（限 3MB）
        {/if}
      </button>
    </div>
    {#if errorMsg}
      <div class="badge error upload-status" role="alert">{errorMsg}</div>
    {:else if okMsg}
      <div class="badge ok upload-status">{okMsg}</div>
    {/if}
  </div>

  <!-- 透明度调节 -->
  <div class="opacity-group">
    <label for="opacity-slider">
      背景透明度
      <span class="opacity-val">{Math.round(config.opacity * 100)}%</span>
    </label>
    <input
      type="range"
      id="opacity-slider"
      min="0.3"
      max="1"
      step="0.05"
      value={config.opacity}
      oninput={updateOpacity}
      class="slider"
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
  /* 根元素复用 settings-base 的 .card.card-pad：与其它设置分区同一套
     间距与分隔线，不再自带 16px 内边距。 */

  /* .section-head / .head-sub 复用 settings-base.css 的共享样式，
     这里不再另起一套字号与颜色。 */

  .group-label {
    display: block;
    font-size: var(--text-sm);
    font-weight: 500;
    color: var(--text-2);
    margin-bottom: var(--space-2);
  }

  .presets-group,
  .upload-group,
  .opacity-group {
    margin-bottom: var(--space-4);
  }

  label {
    display: block;
    font-size: var(--text-sm);
    font-weight: 500;
    color: var(--text-2);
    margin-bottom: var(--space-2);
  }

  .opacity-val {
    float: right;
    font-variant-numeric: tabular-nums;
    color: var(--text-3);
  }

  .presets-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(70px, 1fr));
    gap: var(--space-2);
  }

  .preset-btn {
    height: 60px;
    border: 2px solid var(--border);
    border-radius: var(--radius-md);
    cursor: pointer;
    transition: all var(--transition);
    position: relative;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .preset-btn:hover {
    border-color: var(--accent);
    transform: scale(1.05);
  }

  .preset-btn.active {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 15%, transparent);
  }

  .preset-name {
    position: absolute;
    font-size: 0.7rem;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.8);
    text-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
    pointer-events: none;
    opacity: 0;
    transition: opacity var(--transition);
  }

  .preset-btn:hover .preset-name {
    opacity: 1;
  }

  .upload-box {
    position: relative;
    border: 2px dashed var(--border);
    border-radius: var(--radius-md);
    padding: var(--space-4);
    text-align: center;
    transition: all var(--transition);
  }

  .file-input {
    display: none;
  }

  .upload-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    min-height: 60px;
    border: none;
    background: transparent;
    cursor: pointer;
    color: var(--text-2);
    font-family: inherit;
    font-size: var(--text-sm);
    transition: color var(--transition);
  }

  .upload-btn:hover:not(:disabled) {
    color: var(--text-1);
  }

  .upload-btn:disabled {
    opacity: 0.6;
    cursor: wait;
  }

  .upload-box:hover {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent) 4%, transparent);
  }

  .upload-status {
    margin-top: var(--space-2);
    max-width: 100%;
    white-space: normal;
  }

  .slider {
    width: 100%;
    height: 6px;
    border-radius: var(--radius-full);
    background: var(--surface-2);
    outline: none;
    -webkit-appearance: none;
    appearance: none;
  }

  .slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 18px;
    height: 18px;
    border-radius: var(--radius-full);
    background: var(--accent);
    cursor: pointer;
    transition: all var(--transition);
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
  }

  .slider::-moz-range-thumb {
    width: 18px;
    height: 18px;
    border-radius: var(--radius-full);
    background: var(--accent);
    cursor: pointer;
    border: none;
    transition: all var(--transition);
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
  }

  .slider::-webkit-slider-thumb:hover {
    transform: scale(1.2);
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.3);
  }

  .slider::-moz-range-thumb:hover {
    transform: scale(1.2);
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.3);
  }

  .reset-btn-group {
    display: flex;
    gap: var(--space-2);
  }

  /* 外观复用 settings-base 的 .btn-outline，这里只负责撑满一行 */
  .reset-btn {
    flex: 1;
  }

  @media (max-width: 640px) {
    .presets-grid {
      grid-template-columns: repeat(3, 1fr);
    }
  }
</style>
