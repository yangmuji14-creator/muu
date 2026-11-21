<script>
  // TopBar.svelte — 窄屏顶栏（品牌 + 右侧动作）
  //
  // brand 片段：页面可接管左侧。会话页需要「汉堡开列表 + 当前会话名」，
  //   若页面再自己画一条标题栏，窄屏就会出现两条顶栏叠在一起 ——
  //   所以内容由页面给，这条栏本身只有一个。
  import ThemeToggle from './ThemeToggle.svelte';

  let { brand = null, actions = null } = $props();
</script>

<header class="topbar glass-1">
  {#if brand}
    <div class="brand brand-page">{@render brand()}</div>
  {:else}
    <div class="brand">
      <span class="brand-mark" aria-hidden="true"></span>
      <span class="brand-name">慕</span>
    </div>
  {/if}

  <div class="actions">
    {#if actions}
      {@render actions()}
    {:else}
      <ThemeToggle />
    {/if}
  </div>
</header>

<style>
  .topbar {
    position: relative;
    z-index: var(--z-topbar);
    display: flex;
    flex: none;
    align-items: center;
    gap: var(--space-2);
    min-height: calc(var(--topbar-h) + var(--space-1));
    padding: calc(var(--space-1) + env(safe-area-inset-top, 0px)) var(--space-3) var(--space-1);
    box-shadow: inset 0 -0.5px 0 var(--surface-divider);
  }

  .brand,
  .actions {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  .brand { flex: 1; min-width: 0; }
  .brand-page { gap: var(--space-1); }

  .brand-name {
    color: var(--text-1);
    font-size: var(--text-base);
    font-weight: 700;
    white-space: nowrap;
  }

  .actions { flex: none; gap: var(--space-1); }
</style>
