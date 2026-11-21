<script>
  // ThemeToggle.svelte — 深浅主题切换 (cc-theme localStorage + data-theme)
  // 自包含: 读取/写入 DOM 的 data-theme 属性。
  let theme = $state(
    (() => {
      try {
        return document.documentElement.getAttribute('data-theme') || 'light';
      } catch {
        return 'light';
      }
    })()
  );

  $effect(() => {
    const root = document.documentElement;
    const observer = new MutationObserver(() => {
      theme = root.getAttribute('data-theme') || 'light';
    });
    observer.observe(root, { attributes: true, attributeFilter: ['data-theme'] });
    return () => observer.disconnect();
  });

  function toggle() {
    theme = theme === 'light' ? 'dark' : 'light';
    try {
      document.documentElement.setAttribute('data-theme', theme);
      // 用户明确点了切换 → 落到一个具体主题（这正是「跟随系统」之外的显式选择）。
      // 但设置页的「跟随系统」选中态读的是同一份 cc-theme，必须让它知道
      // 偏好变了，否则设置页仍高亮「跟随系统」、而页面已经是固定主题。
      localStorage.setItem('cc-theme', theme);
      window.dispatchEvent(new CustomEvent('cc-theme-change', { detail: theme }));
    } catch {
      /* ignore */
    }
  }
</script>

<button
  class="theme-toggle"
  type="button"
  onclick={toggle}
  aria-label={theme === 'light' ? '切换到深色' : '切换到浅色'}
  title={theme === 'light' ? '深色模式' : '浅色模式'}
>
  {#key theme}
    <span class="theme-icon">
      {#if theme === 'light'}
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
      {:else}
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
      {/if}
    </span>
  {/key}
</button>

<style>
  .theme-toggle {
    display: inline-grid;
    flex: none;
    place-items: center;
    width: 36px;
    height: 36px;
    padding: 0;
    border: 0;
    border-radius: var(--radius-sm);
    background: var(--field-fill);
    color: var(--text-2);
    cursor: pointer;
  }

  .theme-toggle:hover {
    background: var(--accent-soft);
    color: var(--accent);
  }

  .theme-icon {
    display: inline-flex;
    animation: theme-pop var(--transition-spring);
  }

  @keyframes theme-pop {
    from { opacity: 0; transform: translateY(var(--motion-offset)); }
    to { opacity: 1; transform: translateY(0); }
  }
</style>
