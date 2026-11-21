<script>
  // PromptAdvancedPanel.svelte — 高级 Prompt 区 (友好、分层、不吓人)
  //
  // 结构与职责:
  //   1. 顶部「保持默认」引导条 — 安抚用户, 明确「不改也完全正常」。
  //   2. 「微调你的角色」折叠面板 (默认收起) — 5 个常用可调字段, 友好控件。
  //   3. 「深度设置（通常无需修改）」折叠面板 (默认收起, 弱化视觉):
  //      - 3 个结构化 dict 表单 + 示例对话 + 核心记忆
  //      - 内层「旧版/深度字段」次级折叠收纳 6 个旧版字段 (保持原控件)
  //
  // Props:
  //   form   - 父层 $state 表单对象 { key: { meta, value, orig? } }
  //   saving - 保存中
  //   onsave - (keys: string[], label: string) => void
  //
  // 字段来源 promptFields.js (单一事实来源, 与后端 key 精确映射)。
  import './editor.css';
  import PersonaField from './PersonaField.svelte';
  import PersonaListEditor from './PersonaListEditor.svelte';
  import PromptPanel from './PromptPanel.svelte';
  import PromptDictEditor from './PromptDictEditor.svelte';
  import PromptExampleDialogsEditor from './PromptExampleDialogsEditor.svelte';
  import {
    PROMPT_TUNE,
    PROMPT_DEEP,
    PROMPT_LEGACY,
  } from './promptFields.js';

  let { form = {}, saving = false, onsave } = $props();

  let tuneOpen = $state(false);
  let deepOpen = $state(false);
  let legacyOpen = $state(false);

  const tuneKeys = $derived(PROMPT_TUNE.map((f) => f.key));
  const deepKeys = $derived([...PROMPT_DEEP.map((f) => f.key), ...PROMPT_LEGACY.map((f) => f.key)]);
  const legacyKeys = $derived(PROMPT_LEGACY.map((f) => f.key));

  const tuneMeta = PROMPT_TUNE;
  const deepMeta = PROMPT_DEEP;
  const legacyMeta = PROMPT_LEGACY;

  function saveTune() {
    onsave?.(tuneKeys, '微调你的角色');
  }
  function saveDeep() {
    onsave?.(deepKeys, '深度设置');
  }
</script>

<div class="prompt-advanced">
  <header class="prompt-heading">
    <h3>提示词工坊</h3>
    <p class="persona-hint">编辑角色语气、规则和示例对话。</p>
  </header>

  <!-- 微调你的角色 -->
  <PromptPanel title="微调你的角色" badge="{tuneKeys.length} 个" tier={1} bind:open={tuneOpen}>
    {#snippet children()}
      {#each tuneMeta as meta (meta.key)}
        {#if meta.type === 'list'}
          <div class="persona-field" role="group" aria-label={meta.label}>
            <span class="persona-label">{meta.label}</span>
            <PersonaListEditor bind:value={form[meta.key].value} emptyHint={meta.emptyHint || '点「添加」新增一项'} />
            {#if meta.hint}<p class="persona-hint">{meta.hint}</p>{/if}
          </div>
        {:else}
          <label class="persona-field">
            <span class="persona-label">{meta.label}</span>
            <textarea
              class="persona-control {meta.mono ? 'mono' : ''}"
              rows={meta.rows || 3}
              value={typeof form[meta.key].value === 'string' ? form[meta.key].value : ''}
              placeholder={meta.placeholder || ''}
              oninput={(e) => (form[meta.key].value = e.currentTarget.value)}
            ></textarea>
            {#if meta.hint}<span class="persona-hint">{meta.hint}</span>{/if}
          </label>
        {/if}
      {/each}
    {/snippet}

    {#snippet actions()}
      <button class="persona-action primary" type="button" disabled={saving} onclick={saveTune}>
        {saving ? '保存中…' : '保存微调'}
      </button>
    {/snippet}
  </PromptPanel>

  <!-- 深度设置 -->
  <PromptPanel title="深度设置" badge="{deepKeys.length} 个" tier={2} bind:open={deepOpen}>
    {#snippet children()}
      {#each deepMeta.slice(0, 3) as meta (meta.key)}
        <div class="persona-field persona-inset" role="group" aria-label={meta.label}>
          <span class="persona-label">{meta.label}</span>
          {#if meta.hint}<p class="persona-hint">{meta.hint}</p>{/if}
          <PromptDictEditor bind:value={form[meta.key].value} fields={meta.spec.fields} />
        </div>
      {/each}

      <div class="persona-field" role="group" aria-label={deepMeta[3].label}>
        <span class="persona-label">{deepMeta[3].label}</span>
        {#if deepMeta[3].hint}<p class="persona-hint">{deepMeta[3].hint}</p>{/if}
        <PromptExampleDialogsEditor bind:value={form[deepMeta[3].key].value} />
      </div>

      <div class="persona-field" role="group" aria-label={deepMeta[4].label}>
        <span class="persona-label">{deepMeta[4].label}</span>
        <PersonaListEditor bind:value={form[deepMeta[4].key].value} emptyHint={deepMeta[4].emptyHint} />
      </div>

      <!-- 旧版 / 深度字段 (次级折叠, 保持原控件) -->
      <PromptPanel title="旧版 / 深度字段" badge="{legacyKeys.length} 个" tier={2} bind:open={legacyOpen}>
        {#snippet children()}
          {#each legacyMeta as meta (meta.key)}
            <div class="persona-field" role="group" aria-label={meta.label}>
              <span class="persona-label">{meta.label}</span>
              <PersonaField item={form[meta.key]} />
            </div>
          {/each}
        {/snippet}
      </PromptPanel>
    {/snippet}

    {#snippet actions()}
      <button class="persona-action primary" type="button" disabled={saving} onclick={saveDeep}>
        {saving ? '保存中…' : '保存深度设置'}
      </button>
    {/snippet}
  </PromptPanel>
</div>

<style>
  .prompt-advanced { display: grid; gap: var(--space-2); min-width: 0; }
  .prompt-heading { display: grid; gap: var(--space-1); padding-inline: var(--space-1); }
  .prompt-heading h3 { margin: 0; color: var(--text-1); font-size: var(--text-base); }
</style>
