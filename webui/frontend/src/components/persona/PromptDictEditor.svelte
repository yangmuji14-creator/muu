<script>
  import './editor.css';
  // PromptDictEditor.svelte — 友好键值表单 (用于 dict 类高级字段)
  //
  // 只渲染 spec.fields 里声明的输入框, 每个输入框对应一个后端 dict key。
  // 未知 key 不会出现在 UI, 但被保留在 value 对象中原样传回(不丢字段)。
  //
  // Props:
  //   value  - 绑定对象编辑态 (含 spec.keys 及可能的历史未知 key)
  //   fields - [{ key, label, placeholder?, rows?, mono? }]
  let { value = $bindable({}), fields = [] } = $props();
</script>

<div class="dict-editor">
  {#each fields as spec (spec.key)}
    <label class="persona-field">
      <span class="persona-label">{spec.label}</span>
      <textarea
        class="persona-control {spec.mono ? 'mono' : ''}"
        rows={spec.rows || 2}
        value={value[spec.key] ?? ''}
        placeholder={spec.placeholder || ''}
        oninput={(e) => (value[spec.key] = e.currentTarget.value)}
      ></textarea>
    </label>
  {/each}
</div>

<style>
  .dict-editor {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 205px), 1fr));
    gap: var(--space-3);
  }
</style>
