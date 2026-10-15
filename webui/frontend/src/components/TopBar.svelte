<script>
  // TopBar.svelte — 移动端顶栏 (品牌 + 右侧插槽)
  import ThemeToggle from './ThemeToggle.svelte';
</script>

<header class="topbar">
  <div class="brand">
    <span class="brand-mark" aria-hidden="true"></span>
    <span class="brand-name">慕</span>
  </div>

  <div class="actions">
    <slot name="actions">
      <ThemeToggle />
    </slot>
  </div>
</header>

<style>
  .topbar {
    position: sticky;
    top: 0;
    z-index: 30;
    flex: none;
    display: flex;
    align-items: center;
    gap: var(--space-3);
    height: var(--topbar-h);
    padding: 0 var(--space-4);
    background: var(--surface);
    border-bottom: 1px solid var(--border);
  }

  .brand {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
  }

  .brand-mark {
    flex: none;
    width: 10px;
    height: 10px;
    background: var(--text-1);
  }

  .brand-name {
    font-size: var(--text-sm);
    font-weight: 500;
    letter-spacing: 0.04em;
    color: var(--text-1);
    white-space: nowrap;
  }

  .actions {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
</style>
