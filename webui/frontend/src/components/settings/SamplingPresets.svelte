<script>
  // SamplingPresets.svelte — 采样参数预设档位
  // 一排档位卡片, 点选即把推荐值填入表单; "自定义" 不覆盖手填值。
  // 组件根据当前 temperature/presence/frequency 是否精确命中某档来高亮。
  // 纯 UI 快捷填充, 不直接改 pf, 通过 onselect(presetValues | null) 回调交给父级。

  let { temperature = null, presence = null, frequency = null, onselect } = $props();

  const PRESETS = [
    {
      id: 'balanced',
      name: '标准对话',
      desc: '适合日常聊天',
      values: { temperature: 0.8, presence_penalty: 0.6, frequency_penalty: 0.5 },
    },
    {
      id: 'steady',
      name: '克制稳定',
      desc: '适合需要稳定回复的场合',
      values: { temperature: 0.5, presence_penalty: 0.2, frequency_penalty: 0.3 },
    },
    {
      id: 'playful',
      name: '活泼创新',
      desc: '提高回复的多样性',
      values: { temperature: 1.2, presence_penalty: 1.0, frequency_penalty: 0.8 },
    },
    { id: 'custom', name: '自定义', desc: '保留当前参数', values: null },
  ];

  let selectedId = $derived(matchPreset());

  function matchPreset() {
    for (const p of PRESETS) {
      if (!p.values) continue;
      const v = p.values;
      if (temperature === v.temperature && presence === v.presence_penalty && frequency === v.frequency_penalty) {
        return p.id;
      }
    }
    return 'custom';
  }

  function pick(p) {
    if (p.values) onselect?.(p.values);
    else onselect?.(null);
  }
</script>

<div class="sampling-presets" role="group" aria-label="采样参数预设档位">
  <span class="presets-title">采样预设</span>
  <div class="presets-grid">
    {#each PRESETS as p}
      <button
        type="button"
        class="preset-card"
        aria-pressed={selectedId === p.id}
        onclick={() => pick(p)}
      >
        <span class="preset-name">{p.name}</span>
        <span class="preset-desc">{p.desc}</span>
      </button>
    {/each}
  </div>
</div>

<style>
  .sampling-presets { display: grid; gap: var(--space-2); }
  .presets-title { font-size: var(--text-13); font-weight: 620; color: var(--text-2); }
  .presets-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 128px), 1fr)); gap: var(--space-2); }
  .preset-card {
    display: grid;
    align-content: start;
    gap: var(--space-1);
    min-width: 0;
    padding: var(--space-3);
    border: 0;
    border-radius: var(--radius-lg);
    background: var(--field-fill);
    color: var(--text-1);
    font: inherit;
    text-align: left;
    cursor: pointer;
    transition: background var(--transition), transform var(--transition-spring);
  }
  .preset-card:hover { background: var(--field-fill-focus); }
  .preset-card[aria-pressed='true'] { background: var(--settings-selected); box-shadow: inset 0 0 0 1px var(--accent-line); }
  .preset-card:active { transform: scale(.98); }
  .preset-name { font-size: var(--text-13); font-weight: 650; }
  .preset-desc { color: var(--text-2); font-size: var(--text-xs); line-height: 1.5; }
</style>
