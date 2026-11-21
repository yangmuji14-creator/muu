<script>
  // SettingsPlugins.svelte — 工具与能力 (只读概览)
  //
  // 注意：名字里没有「插件」。GET /api/plugins 回的是「内置工具（ToolRegistry）
  // + 已连接 MCP 服务器提供的工具」的拼盘，不是什么可加载的插件包 ——
  // plugins/ 那个包在第三十八批已整目录删除。页面标题跟着如实写。
  import SettingsShell from './SettingsShell.svelte';
  import EmptyState from './EmptyState.svelte';
  import './settings-base.css';
  import { I } from './icons.js';
  import { pluginsApi } from '../../lib/settingsApi.js';

  let { notify, onback } = $props();

  let plugins = $state(null);
  let loaded = $state(false);

  $effect(() => {
    let alive = true;
    (async () => {
      const r = await pluginsApi.list();
      if (!alive) return;
      if (r.ok) plugins = r.data || {};
      else notify(errMsg(r, '加载工具列表失败'), 'error');
      loaded = true;
    })();
    return () => (alive = false);
  });

  function errMsg(err, fallback) {
    const m = err?.data?.error || err?.data?.message || err?.data?.detail || err?.data;
    if (typeof m === 'string' && m) return m;
    return fallback || (err?.status ? `请求失败（HTTP ${err.status}）` : String(err?.message ?? err));
  }

  // mcp_status 是 { 服务器名: { state, connected, tools } } 的对象。
  // 原来直接把对象插进模板, 页面上就印出一行「MCP 状态: [object Object]」。
  // 这里拆成服务器列表, 用与诊断页一致的方式展示「名字 + 状态 + 工具数」。
  let mcpServers = $derived(
    plugins?.mcp_status && typeof plugins.mcp_status === 'object'
      ? Object.entries(plugins.mcp_status).map(([name, s]) => ({
          name,
          state: s?.state ?? (s?.connected ? 'ready' : 'unknown'),
          connected: !!s?.connected,
          tools: s?.tools ?? 0,
        }))
      : [],
  );
  const MCP_STATE_LABEL = {
    ready: '已连接',
    connected: '已连接',
    connecting: '连接中',
    error: '异常',
    closed: '未连接',
    disconnected: '未连接',
    disabled: '已停用',
    unknown: '未知',
  };
  function mcpLabel(s) {
    return MCP_STATE_LABEL[String(s).toLowerCase()] || s;
  }
</script>

<SettingsShell title="工具与能力" desc="内置工具 + MCP 工具（只读）" {onback}>
  {#if !loaded}
    <div class="settings-group settings-group-pad"><EmptyState icon="puzzle" title="正在加载…" compact /></div>
  {:else if !plugins?.plugins?.length}
    <div class="settings-group settings-group-pad">
      <EmptyState icon="puzzle" title="暂无工具" desc="当前没有内置工具或已连接的 MCP 工具" />
    </div>
  {:else}
    <section class="settings-group settings-group-pad">
      <div class="section-head">
        <h2>工具列表</h2>
        <span class="head-sub">{plugins.builtin_count ?? 0} 内置 · {plugins.mcp_count ?? 0} MCP</span>
      </div>
      <div class="card-list">
        {#each plugins.plugins as p}
          <div class="settings-row">
            <span class="row-icon" aria-hidden="true">{@html `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${I.puzzle}</svg>`}</span>
            <div class="row-main">
              <span class="row-title">{p.name}</span>
              {#if p.description}<span class="row-sub">{p.description}</span>{/if}
            </div>
            <span class="badge {p.source === 'builtin' ? 'info' : 'ok'}">{p.source === 'builtin' ? '内置' : (p.source ?? 'MCP')}</span>
          </div>
        {/each}
      </div>
      {#if mcpServers.length}
        <ul class="card-list mcp-status">
          {#each mcpServers as s (s.name)}
            <li class="settings-row mcp-row">
              <span class="mcp-dot" class:on={s.connected} aria-hidden="true"></span>
              <span class="mcp-name">{s.name}</span>
              <span class="mcp-state">{mcpLabel(s.state)}</span>
              <span class="mcp-tools mono">{s.tools} 工具</span>
            </li>
          {/each}
        </ul>
      {/if}
    </section>
  {/if}
</SettingsShell>

<style>
  .mcp-status {
    margin: var(--space-3) 0 0;
    padding: var(--space-2);
    list-style: none;
    border-radius: var(--radius-lg);
    background: var(--settings-control);
  }
  .mcp-row { font-size: var(--text-xs); flex-wrap: wrap; }
  .mcp-dot { flex: none; width: 6px; height: 6px; border-radius: 50%; background: var(--text-3); }
  .mcp-dot.on { background: var(--success); }
  .mcp-name { flex: 1 1 100px; min-width: 0; overflow-wrap: anywhere; }
  .mcp-state, .mcp-tools { color: var(--text-2); }
</style>
