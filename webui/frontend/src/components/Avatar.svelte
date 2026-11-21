<script>
  let { name = '', src = '', size = 44, online = false } = $props();

  const HUES = ['h0', 'h1', 'h2', 'h3', 'h4'];

  function hashName(n) {
    let h = 0;
    for (let i = 0; i < n.length; i++) h = (h * 31 + n.charCodeAt(i)) >>> 0;
    return h;
  }

  let hue = $derived(HUES[hashName(name || '?') % HUES.length]);
  let initial = $derived((name || '?').trim().charAt(0).toUpperCase());
</script>

<span class="avatar" style="--asize:{size}px">
  {#if src}
    <img src={src} alt="" />
  {:else}
    <span class="avatar-fallback {hue}" aria-hidden="true">{initial}</span>
  {/if}
  {#if online}<span class="avatar-status" role="img" aria-label="在线"></span>{/if}
</span>

<style>
  .avatar {
    position: relative;
    display: inline-grid;
    flex: none;
    width: var(--asize, 44px);
    height: var(--asize, 44px);
    border-radius: var(--radius-avatar);
    background: var(--surface-2);
  }

  .avatar::after {
    position: absolute;
    inset: 0;
    z-index: 1;
    border-radius: inherit;
    box-shadow: var(--avatar-shadow);
    content: '';
    pointer-events: none;
  }

  .avatar img,
  .avatar-fallback {
    width: 100%;
    height: 100%;
    min-width: 0;
    border-radius: inherit;
  }

  .avatar img { display: block; object-fit: cover; }

  .avatar-fallback {
    display: grid;
    place-items: center;
    color: var(--text-1);
    font-size: calc(var(--asize, 44px) * 0.42);
    font-weight: 650;
    user-select: none;
  }

  .avatar-status {
    position: absolute;
    inset-inline-end: 0;
    inset-block-end: 0;
    z-index: 2;
    width: clamp(7px, 24%, 14px);
    aspect-ratio: 1;
    border-radius: var(--radius-pill);
    background: var(--success);
    box-shadow: 0 0 0 2px var(--avatar-ring, var(--surface));
  }

  .h0 { background: color-mix(in srgb, var(--accent) 16%, var(--surface-2)); }
  .h1 { background: color-mix(in srgb, var(--accent) 8%, var(--surface-2)); }
  .h2 { background: color-mix(in srgb, var(--accent) 22%, var(--surface-2)); }
  .h3 { background: var(--surface-3); }
  .h4 { background: color-mix(in srgb, var(--accent) 12%, var(--surface-3)); }
</style>
