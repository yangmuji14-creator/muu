<script>
  // UrlPreview.svelte — base_url 实时最终请求地址预览
  // 纯前端字符串拼接: base_url + "/chat/completions" (deepseek/openai 类型),
  // anthropic 类型 → "/messages"。base_url 为空显示 "—"。
  let { base_url = '', provider = '' } = $props();

  let preview = $derived(buildPreview(base_url, provider));

  function buildPreview(url, prov) {
    const u = (url ?? '').trim();
    if (!u) return '';
    const base = u.replace(/\/+$/, '');
    const isAnthropic = (prov ?? '').toLowerCase().includes('anthropic');
    return `${base}${isAnthropic ? '/messages' : '/chat/completions'}`;
  }
</script>

<div class="url-preview">
  <span class="up-label">请求地址</span>
  {#if preview}
    <code class="up-code">{preview}</code>
  {:else}
    <span class="up-empty">—</span>
  {/if}
</div>

<style>
  .url-preview {
    display: grid;
    gap: var(--space-1);
    min-width: 0;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: var(--field-fill);
    font-size: var(--text-xs);
  }
  .up-label, .up-empty { color: var(--text-2); }
  .up-code { color: var(--accent-strong); font-family: var(--font-mono); overflow-wrap: anywhere; }
</style>
