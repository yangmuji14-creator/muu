import { useEffect, useRef, useState } from 'react';
import {
  ArrowsClockwise,
  Plus,
  QrCode,
  Trash,
  Wrench,
} from '@phosphor-icons/react';
import {
  McpServerItem,
  WechatAccountItem,
  mcpApi,
  pluginsApi,
  wechatApi,
} from '../../api/settings';
import { useApp } from '../../store/AppContext';

export function IntegrationsTab() {
  const { personas, notify, confirm } = useApp();

  const [wechatList, setWechatList] = useState<WechatAccountItem[]>([]);
  const [newAccId, setNewAccId] = useState('');
  const [qrModal, setQrModal] = useState<{ id: string; url?: string; b64?: string; status: string } | null>(null);
  const qrEsRef = useRef<EventSource | null>(null);

  const [mcpList, setMcpList] = useState<McpServerItem[]>([]);
  const [addingMcp, setAddingMcp] = useState(false);
  const [mcpForm, setMcpForm] = useState({ name: '', command: '', args: '' });

  const [plugins, setPlugins] = useState<Array<{ source: string; name: string; description: string }>>([]);

  const load = async () => {
    const [wRes, mRes, pRes] = await Promise.all([
      wechatApi.list(),
      mcpApi.list(),
      pluginsApi.list(),
    ]);
    if (wRes.ok && Array.isArray(wRes.data)) setWechatList(wRes.data);
    if (mRes.ok && mRes.data?.servers) setMcpList(mRes.data.servers);
    if (pRes.ok && pRes.data?.plugins) setPlugins(pRes.data.plugins);
  };

  useEffect(() => {
    load();
    return () => qrEsRef.current?.close();
  }, []);

  const startQrLogin = (accId: string) => {
    qrEsRef.current?.close();
    setQrModal({ id: accId, status: '正在获取登录二维码…' });
    const es = new EventSource(wechatApi.qrcodeUrl(accId));
    qrEsRef.current = es;
    es.addEventListener('qrcode', (e) => {
      try {
        const d = JSON.parse((e as MessageEvent).data);
        setQrModal((prev) => prev && { ...prev, url: d.qr_url, b64: d.qr_base64, status: '请使用微信扫码确认' });
      } catch { /* ignore */ }
    });
    es.addEventListener('status', (e) => {
      try {
        const d = JSON.parse((e as MessageEvent).data);
        setQrModal((prev) => prev && { ...prev, status: d.message || d.status });
      } catch { /* ignore */ }
    });
    es.addEventListener('done', (e) => {
      try {
        const d = JSON.parse((e as MessageEvent).data);
        if (d.ok) {
          notify('微信登录成功', 'success');
          setQrModal(null);
          load();
        } else {
          setQrModal((prev) => prev && { ...prev, status: d.error || '登录失败' });
        }
      } catch { /* ignore */ }
      es.close();
    });
  };

  const handleAddMcp = async () => {
    if (!mcpForm.name.trim() || !mcpForm.command.trim()) {
      notify('请填写服务名与启动命令', 'error');
      return;
    }
    const r = await mcpApi.add({
      name: mcpForm.name.trim(),
      command: mcpForm.command.trim(),
      args: mcpForm.args.trim() ? mcpForm.args.trim().split(/\s+/) : [],
      enabled: true,
    });
    if (r.ok) {
      setAddingMcp(false);
      setMcpForm({ name: '', command: '', args: '' });
      await load();
      notify('MCP 服务已添加', 'success');
    } else {
      notify(r.error || '添加失败', 'error');
    }
  };

  return (
    <div className="space-y-6">
      {/* WeChat Accounts */}
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-[15px] font-semibold text-[var(--c-text)]">微信连接</h3>
            <p className="text-[12.5px] text-[var(--c-text-2)]">扫码登录微信账号并绑定对应的伴侣角色。</p>
          </div>
          <div className="flex items-center gap-1.5">
            <input
              value={newAccId}
              onChange={(e) => setNewAccId(e.target.value)}
              placeholder="账号 ID（如 default）"
              className="w-36 rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] px-3 py-1.5 text-[12.5px] outline-none"
            />
            <button
              type="button"
              onClick={async () => {
                const id = newAccId.trim() || 'default';
                const r = await wechatApi.add({ id, persona_id: personas[0]?.id });
                if (r.ok) {
                  setNewAccId('');
                  load();
                  notify('微信账号已添加', 'success');
                } else notify(r.error || '添加失败', 'error');
              }}
              className="inline-flex items-center gap-1 rounded-[8px] bg-[var(--c-accent)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--c-on-accent)]"
            >
              <Plus size={14} weight="bold" />
              <span>新增账号</span>
            </button>
          </div>
        </div>

        {qrModal && (
          <div className="rounded-[12px] border border-[var(--c-accent-border)] bg-[var(--c-surface)] p-4 text-center">
            <div className="text-[13px] font-medium text-[var(--c-text)]">{qrModal.status}</div>
            {qrModal.b64 && (
              <img src={qrModal.b64} alt="微信登录二维码" className="mx-auto my-3 h-44 w-44 rounded-[8px] bg-white p-2" />
            )}
            <button
              type="button"
              onClick={() => {
                qrEsRef.current?.close();
                setQrModal(null);
              }}
              className="mt-1 rounded-[8px] border border-[var(--c-border)] px-3 py-1 text-[12px]"
            >
              取消扫码
            </button>
          </div>
        )}

        {wechatList.length === 0 ? (
          <div className="rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] p-4 text-[13px] text-[var(--c-text-2)]">
            暂无微信账号配置
          </div>
        ) : (
          <div className="space-y-2">
            {wechatList.map((acc) => (
              <div
                key={acc.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] px-4 py-3 text-[13px]"
              >
                <div>
                  <div className="font-semibold text-[var(--c-text)]">
                    {acc.id}{' '}
                    <span className="ml-1 text-[11.5px] font-normal text-[var(--c-text-2)]">
                      {acc.adapter_running ? '运行中' : acc.has_credentials ? '已登录' : '未扫码'}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <select
                    value={acc.persona_id}
                    onChange={async (e) => {
                      const r = await wechatApi.edit(acc.id, { persona_id: e.target.value });
                      if (r.ok) notify('绑定角色已更新', 'success');
                      load();
                    }}
                    className="rounded-[8px] border border-[var(--c-border)] bg-[var(--c-bg)] px-2.5 py-1 text-[12px]"
                  >
                    {personas.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => startQrLogin(acc.id)}
                    className="inline-flex items-center gap-1 rounded-[8px] border border-[var(--c-border)] px-2.5 py-1 text-[12px]"
                  >
                    <QrCode size={14} weight="duotone" />
                    <span>扫码</span>
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      if (await confirm(`删除微信账号 ${acc.id}？`, { danger: true })) {
                        await wechatApi.remove(acc.id);
                        load();
                      }
                    }}
                    className="rounded-[8px] p-1.5 text-[var(--c-text-2)] hover:text-[var(--c-error)]"
                  >
                    <Trash size={14} weight="duotone" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* MCP Servers */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-[15px] font-semibold text-[var(--c-text)]">MCP 扩展工具</h3>
            <p className="text-[12.5px] text-[var(--c-text-2)]">连接外部 Model Context Protocol 工具服务。</p>
          </div>
          <button
            type="button"
            onClick={() => setAddingMcp((v) => !v)}
            className="inline-flex items-center gap-1 rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--c-text)]"
          >
            <Plus size={14} weight="bold" />
            <span>添加 MCP</span>
          </button>
        </div>

        {addingMcp && (
          <div className="grid grid-cols-1 gap-2.5 rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] p-4 text-[13px] md:grid-cols-3">
            <input
              placeholder="服务名"
              value={mcpForm.name}
              onChange={(e) => setMcpForm({ ...mcpForm, name: e.target.value })}
              className="rounded-[8px] border border-[var(--c-border)] bg-[var(--c-bg)] px-3 py-1.5 outline-none"
            />
            <input
              placeholder="命令（如 npx）"
              value={mcpForm.command}
              onChange={(e) => setMcpForm({ ...mcpForm, command: e.target.value })}
              className="rounded-[8px] border border-[var(--c-border)] bg-[var(--c-bg)] px-3 py-1.5 outline-none"
            />
            <input
              placeholder="参数（空格分隔）"
              value={mcpForm.args}
              onChange={(e) => setMcpForm({ ...mcpForm, args: e.target.value })}
              className="rounded-[8px] border border-[var(--c-border)] bg-[var(--c-bg)] px-3 py-1.5 outline-none"
            />
            <div className="flex justify-end gap-2 md:col-span-3">
              <button
                type="button"
                onClick={() => setAddingMcp(false)}
                className="rounded-[8px] border border-[var(--c-border)] px-3 py-1 text-[12.5px]"
              >
                取消
              </button>
              <button
                type="button"
                onClick={handleAddMcp}
                className="rounded-[8px] bg-[var(--c-accent)] px-3.5 py-1 text-[12.5px] font-medium text-[var(--c-on-accent)]"
              >
                保存
              </button>
            </div>
          </div>
        )}

        <div className="space-y-2">
          {mcpList.map((srv) => (
            <div
              key={srv.name}
              className="flex flex-wrap items-center justify-between gap-2 rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] px-4 py-3 text-[13px]"
            >
              <div>
                <div className="font-semibold text-[var(--c-text)]">
                  {srv.name}
                  <span className="ml-2 text-[11.5px] font-normal text-[var(--c-text-2)]">
                    {srv._connected ? `已连接 · ${srv._tools ?? 0} 工具` : srv._state || '未连接'}
                  </span>
                </div>
                <div className="font-mono text-[11.5px] text-[var(--c-text-2)]">
                  {srv.command} {(srv.args || []).join(' ')}
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={async () => {
                    const act = srv._connected ? 'disconnect' : 'connect';
                    await mcpApi.action(srv.name, act);
                    load();
                  }}
                  className="rounded-[8px] border border-[var(--c-border)] px-2.5 py-1 text-[12px]"
                >
                  {srv._connected ? '断开' : '连接'}
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    await mcpApi.action(srv.name, 'refresh');
                    load();
                  }}
                  className="rounded-[8px] border border-[var(--c-border)] p-1.5"
                  title="刷新"
                >
                  <ArrowsClockwise size={14} weight="bold" />
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    if (await confirm(`删除 MCP 服务 ${srv.name}？`, { danger: true })) {
                      await mcpApi.remove(srv.name);
                      load();
                    }
                  }}
                  className="rounded-[8px] p-1.5 text-[var(--c-text-2)] hover:text-[var(--c-error)]"
                >
                  <Trash size={14} weight="duotone" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Plugins Directory */}
      <div className="overflow-hidden rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] shadow-2xs">
        <div
          className="flex items-center gap-2 border-b border-[var(--c-border)] px-4 py-2.5 text-[13px] font-semibold text-[var(--c-text)]"
          style={{ backgroundColor: 'var(--c-tone-amber-soft)' }}
        >
          <Wrench size={15} weight="duotone" style={{ color: 'var(--c-tone-amber)' }} />
          <span>已启用工具目录 ({plugins.length})</span>
        </div>
        <div className="grid grid-cols-1 gap-2 p-3.5 md:grid-cols-2">
          {plugins.slice(0, 10).map((pl, i) => (
            <div key={`${pl.name}-${i}`} className="rounded-[8px] border border-[var(--c-border)]/70 bg-[var(--c-bg)]/60 px-3 py-2 text-[12px]">
              <div className="font-mono font-medium text-[var(--c-text)]">{pl.name}</div>
              <div className="mt-0.5 line-clamp-1 text-[var(--c-text-2)]">{pl.description}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
