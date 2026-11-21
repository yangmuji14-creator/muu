<script>
  import './editor.css';
  import { I } from '../settings/icons.js';
  // PromptExampleDialogsEditor.svelte — 结构化示例对话列表编辑器
  //
  // 每条: scenario (场景) + reply[] (TA 可能的回话, 可多条)。
  // 保存时由上层 denorm 过滤掉空场景的条目、剔除空回复。
  //
  // Props:
  //   value - bind 数组 [{ scenario, reply: [] }]
  let {
    value = $bindable([]),
    scenarioPlaceholder = '场景，如 深夜你发来消息',
    replyPlaceholder = 'TA 会怎么回',
    emptyHint = '还没有示例对话，点「添加」新增一条',
  } = $props();

  function addRow() {
    value = [...value, { scenario: '', reply: [''] }];
  }
  function removeRow(i) {
    const next = value.slice();
    next.splice(i, 1);
    value = next;
  }
  function setScenario(i, v) {
    const next = value.slice();
    next[i] = { ...next[i], scenario: v };
    value = next;
  }
  function addReply(i) {
    const next = value.slice();
    next[i] = { ...next[i], reply: [...(next[i].reply || []), ''] };
    value = next;
  }
  function setReply(i, j, v) {
    const next = value.slice();
    const reply = (next[i].reply || []).slice();
    reply[j] = v;
    next[i] = { ...next[i], reply };
    value = next;
  }
  function removeReply(i, j) {
    const next = value.slice();
    const reply = (next[i].reply || []).slice();
    reply.splice(j, 1);
    next[i] = { ...next[i], reply };
    value = next;
  }
</script>

<div class="dialog-editor">
  {#each value as row, index (index)}
    <section class="dialog-entry persona-inset" aria-label={'示例对话 ' + (index + 1)}>
      <div class="scene-line">
        <label class="scene-bubble">
          <span class="speaker">你 · 场景</span>
          <textarea
            class="bubble-input"
            rows="2"
            value={row.scenario || ''}
            placeholder={scenarioPlaceholder}
            oninput={(event) => setScenario(index, event.currentTarget.value)}
            aria-label={'场景 ' + (index + 1)}
          ></textarea>
        </label>
        <button class="persona-action remove" type="button" title="删除示例" aria-label="删除示例" onclick={() => removeRow(index)}>
          {@render icon(I.close)}
        </button>
      </div>

      {#each row.reply || [] as reply, replyIndex (replyIndex)}
        <div class="reply-line">
          <label class="reply-bubble">
            <span class="speaker">TA · 回复</span>
            <textarea
              class="bubble-input"
              rows="2"
              value={reply}
              placeholder={replyPlaceholder}
              oninput={(event) => setReply(index, replyIndex, event.currentTarget.value)}
              aria-label={'回复 ' + (index + 1) + ' 第 ' + (replyIndex + 1) + ' 句'}
            ></textarea>
          </label>
          <button class="persona-action remove" type="button" title="删除回复" aria-label="删除回复" onclick={() => removeReply(index, replyIndex)}>
            {@render icon(I.close)}
          </button>
        </div>
      {/each}

      <button class="persona-action add-reply" type="button" onclick={() => addReply(index)}>{@render icon(I.plus)} 添加回复</button>
    </section>
  {:else}
    <p class="persona-hint">{emptyHint}</p>
  {/each}

  <button class="persona-action" type="button" onclick={addRow}>{@render icon(I.plus)} 添加示例</button>

  {#snippet icon(path)}
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{@html path}</svg>
  {/snippet}
</div>

<style>
  .dialog-editor, .dialog-entry { display: grid; gap: var(--space-2); min-width: 0; }
  .dialog-editor > button, .add-reply { justify-self: start; }
  .dialog-entry { gap: var(--space-3); }

  .scene-line, .reply-line { display: flex; align-items: flex-start; gap: var(--space-1); min-width: 0; }
  .scene-line { justify-content: flex-end; }

  .scene-bubble, .reply-bubble {
    display: grid;
    gap: var(--optical-2);
    width: min(84%, 520px);
    min-width: 0;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--accent-soft);
    color: var(--text-1);
  }

  .scene-bubble { border-end-end-radius: var(--radius-xs); }
  .reply-bubble { border-end-start-radius: var(--radius-xs); background: var(--surface); box-shadow: var(--shadow-1); }
  .scene-bubble:focus-within, .reply-bubble:focus-within { background: var(--field-fill-focus); box-shadow: var(--focus-ring); }
  .speaker { color: var(--accent); font-size: var(--text-xs); font-weight: 680; }

  .bubble-input {
    width: 100%;
    min-width: 0;
    min-height: 42px;
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--text-1);
    font: inherit;
    font-size: var(--text-sm);
    line-height: 1.65;
    resize: vertical;
  }

  .bubble-input::placeholder { color: var(--text-2); }
  .bubble-input:focus { outline: 0; box-shadow: none; }

  @supports (field-sizing: content) {
    .bubble-input { field-sizing: content; }
  }

  @media (max-width: 600px) {
    .bubble-input { font-size: var(--text-base); }
  }
</style>
