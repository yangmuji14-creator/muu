<script>
  import './editor.css';
  // PersonaField.svelte — 根据 meta.type 分发渲染对应控件
  //
  // 输入: item = { meta, value } （来自父层 $state 表单对象的某字段）.
  // 直接修改 item.value（Svelte 5 rune 深响应），无需 bind: 回传。
  //
  // 支持的控件类型:
  //   text      > 单行输入
  //   number    > 数字输入
  //   textarea  > 多行文本 (+ 计数)
  //   select    > 下拉 (meta.options)
  //   range     > 滑杆 (meta.min/max/step, 百分比显示用 meta.percent)
  //   switch    > Switch 开关
  //   list      > 字符串列表编辑器
  //   list-dict > 两列 (名称+说明) 编辑器
  //   json      > 等宽 JSON 文本域 (用于 dict 类高级字段)
  import Switch from '../Switch.svelte';
  import PersonaListEditor from './PersonaListEditor.svelte';
  import PersonaListDictEditor from './PersonaListDictEditor.svelte';

  let { item } = $props();
  let meta = $derived(item.meta);
  let value = $derived(item.value);

  function setRaw(v) {
    item.value = v;
  }

  // 文本域字符计数
  let count = $derived(typeof value === 'string' ? value.length : 0);

  function rangeDisplay() {
    if (meta.percent) return `${Math.round(value * 100)}%`;
    return String(value);
  }
</script>

{#if meta.type === 'text'}
  <input class="persona-control" aria-label={meta.label} type="text" value={typeof value === 'string' ? value : ''}
    placeholder={meta.placeholder || ''} oninput={(e) => setRaw(e.currentTarget.value)} />
{:else if meta.type === 'number'}
  <input class="persona-control" aria-label={meta.label} type="number" value={value === '' || value == null ? '' : value}
    step={meta.step || 1} min={meta.min} max={meta.max}
    oninput={(e) => {
      const n = e.currentTarget.value;
      setRaw(n === '' ? '' : Number(n));
    }} />
{:else if meta.type === 'select'}
  <select class="persona-control" aria-label={meta.label} value={typeof value === 'string' ? value : ''} onchange={(e) => setRaw(e.currentTarget.value)}>
    {#if meta.optional}<option value="">不设定</option>{/if}
    {#each meta.options || [] as opt (opt)}
      <option value={opt}>{opt}</option>
    {/each}
  </select>
{:else if meta.type === 'range'}
  <div class="range-row">
    <input class="field-range" aria-label={meta.label} aria-valuetext={rangeDisplay()} type="range" value={value == null ? (meta.min ?? 0) : value}
      min={meta.min ?? 0} max={meta.max ?? 100} step={meta.step ?? 1}
      oninput={(e) => setRaw(Number(e.currentTarget.value))} />
    <span class="range-val">{rangeDisplay()}</span>
  </div>
{:else if meta.type === 'switch'}
  <div class="field-switch">
    <Switch checked={!!value} onchange={(v) => setRaw(v)} label={meta.label} />
  </div>
{:else if meta.type === 'list'}
  <PersonaListEditor bind:value={item.value} placeholder={meta.placeholder || ''} emptyHint={meta.emptyHint || '还没有内容，点「添加」新增一项'} />
{:else if meta.type === 'list-dict'}
  <PersonaListDictEditor bind:value={item.value} namePlaceholder={meta.namePlaceholder || '名称'} detailPlaceholder={meta.detailPlaceholder || '说明（可选）'} />
{:else if meta.type === 'json'}
  <textarea class="persona-control mono" aria-label={meta.label} rows={meta.rows || 4}
    value={typeof value === 'string' ? value : ''}
    placeholder={meta.placeholder || 'JSON 格式，保持默认即可'}
    oninput={(e) => setRaw(e.currentTarget.value)}></textarea>
{:else}
  <!-- textarea / 默认多行 -->
  <div class="textarea-wrap">
    <textarea class="persona-control" aria-label={meta.label} rows={meta.rows || 3}
      value={typeof value === 'string' ? value : ''}
      placeholder={meta.placeholder || ''}
      oninput={(e) => setRaw(e.currentTarget.value)}></textarea>
    {#if meta.counter !== false}
      <span class="char-count">{meta.maxLength ? `${count} / ${meta.maxLength}` : `${count} 字`}</span>
    {/if}
  </div>
{/if}

{#if meta.hint}
  <p class="persona-hint">{meta.hint}</p>
{/if}

<style>
  .range-row { display: flex; align-items: center; gap: var(--space-3); min-height: 40px; }
  .field-range { flex: 1; min-width: 0; height: 28px; margin: 0; accent-color: var(--accent); cursor: pointer; }
  .range-val, .char-count {
    color: var(--text-2);
    font-size: var(--text-xs);
    font-variant-numeric: tabular-nums;
  }
  .range-val { flex: none; min-width: 4ch; text-align: right; }
  .field-switch { display: flex; align-items: center; min-height: 42px; }
  .textarea-wrap { display: grid; gap: var(--space-1); min-width: 0; }
  .char-count { justify-self: end; }
</style>
