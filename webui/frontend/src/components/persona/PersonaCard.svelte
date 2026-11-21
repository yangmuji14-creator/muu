<script>
  import './editor.css';
  // PersonaCard.svelte — 精简人设卡 (PawzoChat 式)
  //
  // 结构: 标题头 + 一组核心字段 + 单个「保存」按钮。
  // 只提交本卡涉及的字段 (复用父层按字段过滤的保存机制)。
  //
  // Props:
  //   form      - 父层 $state 表单对象 { key: { meta, value, orig? } }
  //   fields    - 本卡字段 metas 数组 (含 key/label/type/...)
  //   saving    - 保存中状态
  //   onsave    - (keys: string[]) => void  父层真正提交
  import PersonaField from './PersonaField.svelte';

  let { title, subtitle = '', fields = [], form = {}, saving = false, onsave } = $props();

  const keys = $derived(fields.map((f) => f.key));

  function handleSave() {
    onsave?.(keys, title);
  }
</script>

<section class="persona-card persona-surface">
  <header class="pc-head">
    <div class="pc-head-txt">
      <h3 class="pc-title">{title}</h3>
      {#if subtitle}
        <p class="pc-sub">{subtitle}</p>
      {/if}
    </div>
    <button class="persona-action primary" type="button" disabled={saving} onclick={handleSave}>
      {saving ? '保存中…' : '保存'}
    </button>
  </header>

  <div class="pc-fields">
    {#each fields as meta (meta.key)}
      <div class="persona-field" role="group" aria-label={meta.label}>
        <span class="persona-label">
          {meta.label}{meta.type === 'number' && meta.key === 'age' ? ' (岁)' : ''}
        </span>
        <PersonaField item={form[meta.key]} />
      </div>
    {/each}
  </div>
</section>

<style>
  .persona-card { display: grid; gap: var(--space-3); padding: clamp(12px, 3vw, 20px); }

  .pc-head { display: flex; align-items: start; justify-content: space-between; gap: var(--space-2); }
  .pc-head-txt { min-width: 0; }
  .pc-title { margin: 0; color: var(--text-1); font-size: var(--text-base); line-height: var(--leading-tight); }
  .pc-sub { margin: var(--space-1) 0 0; color: var(--text-2); font-size: var(--text-xs); }
  .pc-fields { display: grid; gap: var(--space-3); }
</style>
