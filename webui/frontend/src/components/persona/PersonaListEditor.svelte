<script>
  import './editor.css';
  // PersonaListEditor.svelte — 通用"每行一项"字符串列表编辑器
  //
  // bind:value 双向（$bindable），行内编辑不丢数据。
  // 允许空行被"添加"临时存在；保存时由上层过滤空项。
  let { value = $bindable([]), placeholder = '', emptyHint = '还没有内容，点「添加」新增一项' } = $props();

  function addRow() {
    value = [...value, ''];
  }
  function removeRow(i) {
    const next = value.slice();
    next.splice(i, 1);
    value = next;
  }
  function setRow(i, v) {
    const next = value.slice();
    next[i] = v;
    value = next;
  }
</script>

<div class="list-editor persona-inset">
  {#if value.length === 0}
    <p class="persona-hint">{emptyHint}</p>
  {:else}
    <div class="rows">
      {#each value as row, i (i)}
        <div class="row">
          <input
            class="persona-control"
            type="text"
            value={row}
            placeholder={placeholder}
            oninput={(e) => setRow(i, e.currentTarget.value)}
            aria-label="列表项 {i + 1}"
          />
          <button class="persona-action remove" type="button" title="删除此项" onclick={() => removeRow(i)} aria-label="删除列表项">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
      {/each}
    </div>
  {/if}
  <button class="persona-action" type="button" onclick={addRow}>
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
    添加
  </button>
</div>

<style>
  .list-editor, .rows { display: grid; gap: var(--space-2); }
  .list-editor > button { justify-self: start; }
  .row { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: var(--space-2); }
</style>
