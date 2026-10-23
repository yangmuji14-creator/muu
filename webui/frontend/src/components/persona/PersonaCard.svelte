<script>
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

<section class="persona-card">
  <header class="pc-head">
    <div class="pc-head-txt">
      <h3 class="pc-title">{title}</h3>
      {#if subtitle}
        <p class="pc-sub">{subtitle}</p>
      {/if}
    </div>
    <!-- 保存按钮从「区块底部右对齐」提到标题行右侧:
         原来它悬在表单下方一屏之外, 看起来像没有归属的悬浮按钮;
         放在标题行后, 每个区块= 标签 + 保存 一条横轴, 视线不用来回跳。 -->
    <button class="btn btn-primary btn-sm pc-save" type="button" disabled={saving} onclick={handleSave}>
      {saving ? '保存中…' : '保存'}
    </button>
  </header>

  <div class="pc-fields">
    {#each fields as meta (meta.key)}
      <label class="field">
        <span class="field-label">
          {meta.label}{meta.type === 'number' && meta.key === 'age' ? ' (岁)' : ''}
        </span>
        <PersonaField item={form[meta.key]} />
      </label>
    {/each}
  </div>
</section>

<style>
  /* 人设卡与设置子页共用同一套区块语言: 去掉「盒套盒」的边框 + 圆角,
     改用一道更重的顶线分区, 区块标题降成 11px 微标签。
     这样一屏里 3-4 个卡片不再互相抢注意力, 内容(输入框)回到第一层。 */
  .persona-card {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    padding: var(--space-5) 0 var(--space-2);
    background: transparent;
    border: none;
    border-top: 1px solid var(--border-strong);
    border-radius: 0;
    box-shadow: none;
  }
  .persona-card:first-child {
    border-top: none;
    padding-top: 0;
  }
  .pc-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--space-3);
  }
  .pc-head-txt {
    display: flex;
    flex-direction: column;
    gap: var(--optical-3);
    min-width: 0;
  }
  .pc-title {
    margin: 0;
    font-size: var(--text-2xs);
    font-weight: 500;
    letter-spacing: var(--tracking-wider);
    color: var(--text-3);
  }
  .pc-sub {
    margin: 0;
    font-size: var(--text-13);
    line-height: 1.6;
    color: var(--text-2);
  }
  .pc-save {
    flex: none;
  }
  .pc-fields {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--optical-6);
  }
  /* 标签 14px/600 → 13px/600: 与输入框内 15px 正文拉开一档半,
     原来两者只差 2px 且都用 --text-sm 家族, 读起来「标签就是正文加粗」。 */
  .field-label {
    font-size: var(--text-13);
    font-weight: 600;
    letter-spacing: var(--tracking-tight);
    color: var(--text-2);
  }
  .pc-save {
    display: flex;
    justify-content: flex-end;
    padding-top: var(--space-2);
  }

  /* 按钮自带完整样式, 不依赖任何全局类。
     原来 PersonaCard 只写了 class="btn btn-primary btn-sm" 却没定义规则,
     靠 settings-base.css 里未加作用域的 .btn-primary 顺带生效 ——
     那份文件收进 .settings-main 作用域后就断了, 这里补齐。 */
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
  .btn-primary {
    background: var(--btn-primary-bg);
    color: var(--btn-primary-text);
  }
  .btn-primary:hover:not(:disabled) {
    background: var(--btn-primary-hover);
  }
  .btn-sm {
    height: var(--btn-h-sm);
    padding: 0 var(--space-3);
    font-size: var(--text-xs);
  }
</style>
