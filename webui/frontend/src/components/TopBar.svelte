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
  /* glass-1 (chrome 档): 顶栏是"浮在滚动内容之上"的 chrome,
     用最薄的一档玻璃 + 底部结构线。滚动时内容从底下透出, 层级
     由材质表达, 不再需要一条实心色带把页面切断。
     position: sticky 在这里才第一次有意义 —— 原来不透明底色让它
     和静态栏没有区别。 */
  .topbar {
    position: sticky;
    top: 0;
    z-index: var(--z-topbar);
    flex: none;
    display: flex;
    align-items: center;
    gap: var(--space-3);
    height: var(--topbar-h);
    padding: 0 var(--space-4);
    /* 兜底: 不支持 backdrop-filter 时是不透明 --surface */
    background: var(--surface);
    border-bottom: 1px solid var(--glass-border-2);
  }

  @supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
    .topbar {
      background: var(--glass-1);
      -webkit-backdrop-filter: blur(var(--glass-blur-1)) saturate(var(--glass-sat-1));
      backdrop-filter: blur(var(--glass-blur-1)) saturate(var(--glass-sat-1));
    }
  }

  @media (prefers-reduced-transparency: reduce) {
    .topbar {
      background: var(--surface);
      -webkit-backdrop-filter: none;
      backdrop-filter: none;
    }
  }

  .brand {
    display: flex;
    align-items: center;
    gap: var(--optical-9);
    min-width: 0;
  }

  /* 与桌面侧栏同一枚标识: 黑方块 + 右下 5px 冷蓝角 */
  .brand-mark {
    position: relative;
    flex: none;
    width: 11px;
    height: 11px;
    background: var(--text-1);
  }
  .brand-mark::after {
    content: '';
    position: absolute;
    right: -2px;
    bottom: -2px;
    width: 5px;
    height: 5px;
    background: var(--accent);
  }

  .brand-name {
    font-size: var(--text-13);
    font-weight: 600;
    letter-spacing: 0.12em;
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
