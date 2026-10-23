<script>
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

<div class="advanced">
  <button
    class="adv-toggle"
    type="button"
    aria-expanded={expanded}
    onclick={toggleAll}
  >
    <span class="adv-label">高级 / 全部字段</span>
    <span class="adv-count">{totalCount} 个</span>
    <svg
      class="adv-arrow {expanded ? 'is-open' : ''}"
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
    <div class="adv-groups">
      {#each groups as g (g.id)}
        <section class="adv-group">
          <button
            class="adv-group-head"
            type="button"
            aria-expanded={!!openGroups[g.id]}
            onclick={() => toggleGroup(g.id)}
          >
            <span class="adv-group-label">{g.label}</span>
            <span class="adv-group-n">{g.fields.length}</span>
            <svg
              class="adv-arrow {openGroups[g.id] ? 'is-open' : ''}"
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
            <div class="adv-group-body">
              {#if g.hint}
                <p class="group-hint">{g.hint}</p>
              {/if}
              <div class="adv-fields">
                {#each g.fields as meta (meta.key)}
                  <label class="field">
                    <span class="field-label">{meta.label}</span>
                    <PersonaField item={form[meta.key]} />
                  </label>
                {/each}
              </div>
              <div class="adv-save">
                <button class="btn btn-outline btn-sm" type="button" disabled={saving} onclick={() => saveGroup(g)}>
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
  .advanced {
    margin-top: var(--space-2);
  }
  /* 折叠开关原来是「虚线圈」—— 虚线与这套设计语言里的实线分区语言冲突,
     且一圈虚线在页面底部非常显眼。改成一行带下划线的文字开关:
     左边 11px 微标签, 右边计数 + 箭头, 压在一条细线上。 */
  .adv-toggle {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    width: 100%;
    padding: var(--space-4) 0 var(--space-3);
    background: transparent;
    border: none;
    border-top: 1px solid var(--border-strong);
    border-radius: 0;
    color: var(--text-3);
    font-size: var(--text-2xs);
    font-weight: 500;
    letter-spacing: var(--tracking-wider);
    cursor: pointer;
    transition: color var(--transition), border-color var(--transition);
  }
  .adv-toggle:hover {
    color: var(--text-1);
    border-top-color: var(--accent-line);
  }
  .adv-label {
    flex: 1;
    text-align: left;
  }
  .adv-count {
    font-size: var(--text-2xs);
    font-weight: 500;
    letter-spacing: var(--tracking-wide);
    color: var(--text-3);
    background: var(--surface-2);
    border-radius: var(--radius-xs);
    padding: var(--hair) var(--optical-7);
  }
  .adv-arrow {
    transition: transform var(--transition);
    color: var(--text-3);
  }
  .adv-arrow.is-open {
    transform: rotate(180deg);
  }

  .adv-groups {
    display: flex;
    flex-direction: column;
    gap: 0;
    margin-top: 0;
  }
  /* 分组不再是卡片: 去掉背景/边框/圆角, 只用一道细线切段,
     组标题降为 13px/500。原先每组都是一张白卡套在折叠区里,
     展开后能看到 4-5 个盒子并排, 这就是「盒套盒」的来源。 */
  .adv-group {
    background: transparent;
    border: none;
    border-top: 1px solid var(--border);
    border-radius: 0;
    box-shadow: none;
    overflow: visible;
  }
  .adv-group:first-child {
    border-top: none;
  }
  .adv-group-head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    width: 100%;
    padding: var(--space-3) 0;
    background: transparent;
    border: none;
    color: var(--text-2);
    font-size: var(--text-13);
    font-weight: 500;
    letter-spacing: var(--tracking-tight);
    cursor: pointer;
    transition: color var(--transition);
  }
  .adv-group-head:hover {
    background: transparent;
    color: var(--text-1);
  }
  .adv-group-label {
    flex: 1;
    text-align: left;
  }
  .adv-group-n {
    font-size: var(--text-2xs);
    letter-spacing: var(--tracking-wide);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .adv-group-body {
    padding: 0 0 var(--space-5) 0;
    border-top: none;
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .group-hint {
    margin: 0;
    font-size: var(--text-2xs);
    line-height: 1.7;
    color: var(--text-3);
  }
  .adv-fields {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--optical-6);
  }
  /* 与 PersonaCard 的标签对齐: 13px/600 */
  .field-label {
    font-size: var(--text-13);
    font-weight: 600;
    letter-spacing: var(--tracking-tight);
    color: var(--text-2);
  }
  .adv-save {
    display: flex;
    justify-content: flex-end;
  }

  /* 按钮自带完整样式, 不依赖全局类 (同上, settings-base.css 已收进作用域)。 */
  .btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    height: var(--btn-h-md);
    padding: 0 var(--space-4);
    border: 1px solid transparent;
    border-radius: var(--btn-radius);
    font-family: var(--font-sans);
    font-size: var(--text-sm);
    font-weight: 500;
    letter-spacing: var(--tracking-tight);
    white-space: nowrap;
    cursor: pointer;
    transition: background var(--transition), border-color var(--transition), transform var(--transition);
  }
  .btn:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
  .btn:active:not(:disabled) {
    transform: scale(0.97);
  }
  .btn-outline {
    background: var(--btn-outline-bg);
    border-color: var(--btn-outline-border);
    color: var(--btn-outline-text);
  }
  .btn-outline:hover:not(:disabled) {
    background: var(--btn-outline-hover);
    border-color: var(--accent-line);
  }
  .btn-sm {
    height: var(--btn-h-sm);
    padding: 0 var(--space-3);
    font-size: var(--text-xs);
  }
</style>
