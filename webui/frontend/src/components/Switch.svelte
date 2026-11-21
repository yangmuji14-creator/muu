<script>
  // Switch.svelte — 开关 (使用 --switch-* 组件 token, 双向可控)
  let { checked = false, disabled = false, label = '', onchange } = $props();

  function toggle() {
    if (disabled) return;
    checked = !checked;
    onchange?.(checked);
  }
</script>

<button
  type="button"
  class="switch {checked ? 'is-on' : ''}"
  role="switch"
  aria-checked={checked}
  aria-label={label}
  disabled={disabled}
  onclick={toggle}
>
  <span class="knob"></span>
</button>

<style>
  .switch {
    position: relative;
    flex: none;
    width: var(--switch-w);
    height: max(36px, var(--switch-h));
    padding: 0;
    border: 0;
    border-radius: var(--radius-pill);
    background: transparent;
    cursor: pointer;
    touch-action: manipulation;
  }

  .switch::before,
  .switch::after {
    position: absolute;
    inset: calc((100% - var(--switch-h)) / 2) 0;
    border-radius: var(--radius-pill);
    content: '';
  }

  .switch::before {
    background: var(--switch-bg);
    box-shadow: inset 0 0 0 1px var(--surface-divider);
  }

  .switch::after {
    background: var(--switch-bg-on);
    box-shadow: var(--switch-shadow-on);
    opacity: 0;
    transition: opacity var(--transition);
  }

  .switch.is-on::after { opacity: 1; }

  .knob {
    position: absolute;
    inset-block-start: 50%;
    inset-inline-start: calc((var(--switch-h) - var(--switch-knob-size)) / 2);
    z-index: 1;
    width: var(--switch-knob-size);
    height: var(--switch-knob-size);
    border-radius: var(--radius-pill);
    background: var(--switch-knob);
    box-shadow: var(--switch-shadow);
    transform: translateY(-50%);
    transition: transform var(--transition-spring);
  }

  .switch.is-on .knob {
    transform: translate(calc(var(--switch-w) - var(--switch-h)), -50%);
    background: var(--switch-knob-on);
  }

  .switch:disabled { opacity: 0.5; cursor: not-allowed; }

  @media (forced-colors: active) {
    .switch::before { border: 1px solid ButtonText; }
    .switch::after { background: Highlight; }
    .knob { background: ButtonText; }
    .switch.is-on .knob { background: HighlightText; }
  }
</style>
