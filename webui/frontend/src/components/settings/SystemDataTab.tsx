import { useEffect, useState } from 'react';
import { ArrowsClockwise, DownloadSimple, Pulse, UploadSimple } from '@phosphor-icons/react';
import { diagApi, monitorApi } from '../../api/settings';
import { formatDuration } from '../../lib/format';
import { useApp } from '../../store/AppContext';

export function SystemDataTab() {
  const { notify, confirm } = useApp();
  const [health, setHealth] = useState<{
    ok: boolean;
    models: number;
    mcp_servers: number;
    runtime?: { uptime_seconds?: number };
  } | null>(null);
  const [diag, setDiag] = useState<{
    overall: string;
    summary: { ok: number; warn: number; error: number };
    checks: Array<{ name: string; status: string; message: string }>;
  } | null>(null);
  const [about, setAbout] = useState<{
    name: string;
    version: string;
    storage: string;
    privacy: string;
    tagline: string;
  } | null>(null);

  const load = async () => {
    const [hRes, dRes, aRes] = await Promise.all([
      monitorApi.health(),
      monitorApi.diagnostics(),
      diagApi.about(),
    ]);
    if (hRes.ok && hRes.data) setHealth(hRes.data);
    if (dRes.ok && dRes.data) setDiag(dRes.data);
    if (aRes.ok && aRes.data) setAbout(aRes.data);
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-[15px] font-semibold text-[var(--c-text)]">系统运行与本地数据</h3>
          <p className="text-[12.5px] text-[var(--c-text-2)]">
            健康诊断、完整配置备份导出及恢复。
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          className="inline-flex items-center gap-1.5 rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] px-3.5 py-1.5 text-[12.5px]"
        >
          <ArrowsClockwise size={14} weight="bold" />
          <span>刷新状态</span>
        </button>
      </div>

      {health && (
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] p-3.5">
            <div className="text-[11.5px] text-[var(--c-text-2)]">运行状态</div>
            <div className="mt-1 text-[15px] font-semibold text-[var(--c-success)]">
              {health.ok ? '正常' : '异常'}
            </div>
          </div>
          <div className="rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] p-3.5">
            <div className="text-[11.5px] text-[var(--c-text-2)]">已加载模型</div>
            <div className="mt-1 font-mono text-[15px] font-semibold" style={{ color: 'var(--c-tone-blue)' }}>
              {health.models}
            </div>
          </div>
          <div className="rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] p-3.5">
            <div className="text-[11.5px] text-[var(--c-text-2)]">运行时长</div>
            <div className="mt-1 font-mono text-[15px] font-semibold" style={{ color: 'var(--c-tone-teal)' }}>
              {formatDuration(health.runtime?.uptime_seconds || 0)}
            </div>
          </div>
        </div>
      )}

      {diag && (
        <div className="overflow-hidden rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] text-[12.5px] shadow-2xs">
          <div
            className="flex items-center justify-between border-b border-[var(--c-border)] px-4 py-2.5 font-semibold text-[var(--c-text)]"
            style={{ backgroundColor: 'var(--c-tone-blue-soft)' }}
          >
            <span className="flex items-center gap-2">
              <Pulse size={15} weight="duotone" style={{ color: 'var(--c-tone-blue)' }} />
              <span>自检结果（{diag.summary.ok} 正常 / {diag.summary.warn} 警告 / {diag.summary.error} 错误）</span>
            </span>
          </div>
          <div className="max-h-40 space-y-1.5 overflow-y-auto p-3.5">
            {diag.checks.map((c, i) => (
              <div
                key={`${c.name}-${i}`}
                className="flex items-center justify-between rounded-[8px] border border-[var(--c-border)]/70 bg-[var(--c-bg)]/60 px-3 py-1.5"
              >
                <span className="font-medium text-[var(--c-text)]">{c.name}</span>
                <span className="text-[var(--c-text-2)]">{c.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Backup & Restore */}
      <div className="flex flex-wrap items-center gap-2.5">
        <button
          type="button"
          onClick={async () => {
            const r = await diagApi.backup();
            if (r.ok) notify('完整数据备份已开始下载', 'success');
            else notify(r.error || '备份失败', 'error');
          }}
          className="inline-flex items-center gap-1.5 rounded-[8px] bg-[var(--c-accent)] px-4 py-2 text-[13px] font-medium text-[var(--c-on-accent)]"
        >
          <DownloadSimple size={15} weight="duotone" />
          <span>导出数据备份 (.zip)</span>
        </button>

        <button
          type="button"
          onClick={() => diagApi.exportDiagnostics()}
          className="inline-flex items-center gap-1.5 rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] px-4 py-2 text-[13px] text-[var(--c-text)]"
        >
          <DownloadSimple size={15} weight="duotone" />
          <span>导出脱敏诊断包</span>
        </button>

        <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] px-4 py-2 text-[13px] text-[var(--c-text)]">
          <UploadSimple size={15} weight="duotone" />
          <span>从备份恢复</span>
          <input
            type="file"
            accept=".zip"
            className="hidden"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              e.target.value = '';
              if (!file) return;
              if (!(await confirm(`确定使用备份包 ${file.name} 排队恢复吗？`))) return;
              const r = await diagApi.restore(file);
              if (r.ok) notify('恢复已排队，重启服务后生效', 'success');
              else notify(r.error || '恢复失败', 'error');
            }}
          />
        </label>
      </div>

      {about && (
        <div className="rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] p-4 text-[12.5px] text-[var(--c-text-2)] space-y-1">
          <div className="font-semibold text-[var(--c-text)]">
            {about.name} v{about.version}
          </div>
          <div>数据目录：{about.storage}</div>
          <div>{about.privacy}</div>
        </div>
      )}
    </div>
  );
}
