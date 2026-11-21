<script>
  import './editor.css';
  // PersonaAdvanced.svelte — 「高级 / 全部字段」折叠区
  //
  // 默认收起；点击头部展开全部字段。展开后按原分组以手风琴展示
  // (每组一个可折叠面板)。精简卡里的字段不在这些分组中重复出现，
  // 因此分组 = 原 USER_GROUPS/ADV_GROUP 减去精简字段后的剩余。
  //
  // Props:
  //   groups     - [{ id, label, hint?, fields }] 剩余字段分组
  //   form       - 父层 $state 表单对象
  //   saving     - 保存中
  //   onsave     - (keys: string[]) => void
  import PersonaField from './PersonaField.svelte';

  let { groups = [], form = {}, saving = false, onsave } = $props();

  let expanded = $state(false); // 主区开关 (头部 "展开全部")
  let openGroups = $state({}); // 每组手风琴开合 { id: bool }

  const totalCount = $derived(groups.reduce((n, g) => n + g.fields.length, 0));

  function toggleGroup(id) {
    openGroups[id] = !openGroups[id];
  }

  function toggleAll() {
    expanded = !expanded;
    if (expanded) {
      // 展开时默认打开第一组, 其余收起, 保持清爽
      const first = groups[0]?.id;
      openGroups = {};
      if (first) openGroups[first] = true;
    } else {
      openGroups = {};
    }
  }

  function saveGroup(g) {
    onsave?.(g.fields.map((f) => f.key), g.label);
  }
</script>

<div class="advanced persona-surface">
  <button
    class="persona-disclosure"
    type="button"
    aria-expanded={expanded}
    onclick={toggleAll}
  >
    <span class="adv-label">高级 / 全部字段</span>
    <span class="persona-disclosure-meta">{totalCount} 个</span>
    <svg
      class="persona-chevron {expanded ? 'is-open' : ''}"
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    ><polyline points="6 9 12 15 18 9"/></svg>
  </button>

  {#if expanded}
    <div class="adv-groups persona-reveal">
      {#each groups as g (g.id)}
        <section class="adv-group">
          <button
            class="persona-disclosure"
            type="button"
            aria-expanded={!!openGroups[g.id]}
            onclick={() => toggleGroup(g.id)}
          >
            <span class="adv-group-label">{g.label}</span>
            <span class="persona-disclosure-meta">{g.fields.length}</span>
            <svg
              class="persona-chevron {openGroups[g.id] ? 'is-open' : ''}"
              viewBox="0 0 24 24"
              width="16"
              height="16"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            ><polyline points="6 9 12 15 18 9"/></svg>
          </button>

          {#if openGroups[g.id]}
            <div class="adv-group-body persona-reveal">
              {#if g.hint}
                <p class="persona-hint">{g.hint}</p>
              {/if}
              <div class="adv-fields">
                {#each g.fields as meta (meta.key)}
                  <div class="persona-field" role="group" aria-label={meta.label}>
                    <span class="persona-label">{meta.label}</span>
                    <PersonaField item={form[meta.key]} />
                  </div>
                {/each}
              </div>
              <div class="adv-save">
                <button class="persona-action" type="button" disabled={saving} onclick={() => saveGroup(g)}>
                  {saving ? '保存中…' : `保存${g.label}`}
                </button>
              </div>
            </div>
          {/if}
        </section>
      {/each}
    </div>
  {/if}
</div>

<style>
  .adv-label, .adv-group-label { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .adv-groups { display: grid; gap: var(--space-2); padding: var(--space-2) var(--space-3) var(--space-3); }
  .adv-group { min-width: 0; border-radius: var(--radius-md); background: var(--surface-2); }
  .adv-group-body, .adv-fields { display: grid; gap: var(--space-3); }
  .adv-group-body { padding: var(--space-3); }
  .adv-save { display: flex; justify-content: flex-end; }
</style>
