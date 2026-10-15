<script>
  // Avatar.svelte — 方角头像 (有图显示图, 无图用姓名哈希的冷蓝淡调色块)
  //
  // 注意: 色块只用 accent(冷蓝) 的不同淡化程度, 不再映射到 success/warning/error
  // 这类语义状态色 —— 那会让某个名字恰好撞上"错误红", 语义错且视觉跳。
  let { name = '', src = '', size = 44 } = $props();

  const HUES = ['h0', 'h1', 'h2', 'h3', 'h4'];

  function hashName(n) {
    let h = 0;
    for (let i = 0; i < n.length; i++) h = (h * 31 + n.charCodeAt(i)) >>> 0;
    return h;
  }

  let hue = $derived(HUES[hashName(name || '?') % HUES.length]);
  let initial = $derived((name || '?').trim().charAt(0).toUpperCase());
</script>

<span class="avatar" style="--asize:{size}px" aria-hidden={src ? undefined : 'true'}>
  {#if src}
    <img src={src} alt="" />
  {:else}
    <span class="avatar-fallback {hue}">{initial}</span>
  {/if}
</span>

<style>
  .avatar {
    flex: none;
    width: var(--asize, 44px);
    height: var(--asize, 44px);
    border-radius: var(--radius-xs);
    overflow: hidden;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: var(--surface-2);
    border: 1px solid var(--avatar-border);
    box-shadow: var(--avatar-shadow);
  }
  .avatar img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .avatar-fallback {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-1);
    font-weight: 500;
    font-size: calc(var(--asize, 44px) * 0.42);
    user-select: none;
    letter-spacing: 0.02em;
  }
  /* 冷蓝淡调: 只调 accent 的混入比例, 深浅主题自动跟随 */
  .h0 { background: color-mix(in srgb, var(--accent) 16%, var(--surface-2)); }
  .h1 { background: color-mix(in srgb, var(--accent) 8%, var(--surface-2)); }
  .h2 { background: color-mix(in srgb, var(--accent) 22%, var(--surface-2)); }
  .h3 { background: var(--surface-3); }
  .h4 { background: color-mix(in srgb, var(--accent) 12%, var(--surface-3)); }
</style>
