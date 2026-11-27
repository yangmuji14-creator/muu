import { useEffect, useState } from 'react';
import * as Switch from '@radix-ui/react-switch';
import { Feather, Play, Plus, Trash, Waveform } from '@phosphor-icons/react';
import { VoiceProviderItem, momentsAutoApi, voiceApi } from '../../api/settings';
import { useApp } from '../../store/AppContext';

export function VoiceMomentsTab() {
  const { notify, confirm } = useApp();

  const [voiceList, setVoiceList] = useState<VoiceProviderItem[]>([]);
  const [addingVoice, setAddingVoice] = useState(false);
  const [vf, setVf] = useState({ name: '', provider: 'openai', base_url: '', api_key: '', voice: '', model: '' });

  const [autoCfg, setAutoCfg] = useState({
    enabled: false,
    interval_minutes: 180,
    persona_id: '',
    active_start: 8,
    active_end: 22,
  });
  const [autoPersonas, setAutoPersonas] = useState<Array<{ id: string; name: string }>>([]);

  const load = async () => {
    const [vRes, mRes] = await Promise.all([voiceApi.list(), momentsAutoApi.config()]);
    if (vRes.ok && vRes.data) setVoiceList(vRes.data.providers || []);
    if (mRes.ok && mRes.data) {
      if (mRes.data.config) setAutoCfg(mRes.data.config);
      if (mRes.data.personas) setAutoPersonas(mRes.data.personas);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleAddVoice = async () => {
    if (!vf.name.trim()) {
      notify('请填写服务商名称', 'error');
      return;
    }
    const r = await voiceApi.add({ ...vf, enabled: true });
    if (r.ok) {
      setAddingVoice(false);
      setVf({ name: '', provider: 'openai', base_url: '', api_key: '', voice: '', model: '' });
      await load();
      notify('语音服务商已添加', 'success');
    } else {
      notify(r.error || '添加失败', 'error');
    }
  };

  const handleSaveAuto = async () => {
    const r = await momentsAutoApi.save(autoCfg);
    if (r.ok) notify('自动动态设置已保存', 'success');
    else notify(r.error || '保存失败', 'error');
  };

  return (
    <div className="space-y-6">
      {/* TTS Providers */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-[15px] font-semibold text-[var(--c-text)]">语音合成服务商 (TTS)</h3>
            <p className="text-[12.5px] text-[var(--c-text-2)]">配置后可在对话中合成并发回语音消息。</p>
          </div>
          <button
            type="button"
            onClick={() => setAddingVoice((v) => !v)}
            className="inline-flex items-center gap-1 rounded-[8px] bg-[var(--c-accent)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--c-on-accent)]"
          >
            <Plus size={14} weight="bold" />
            <span>添加语音</span>
          </button>
        </div>

        {addingVoice && (
          <div className="grid grid-cols-1 gap-2.5 rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] p-4 text-[13px] md:grid-cols-2">
            <input
              placeholder="名称（如 fish_tts）"
              value={vf.name}
              onChange={(e) => setVf({ ...vf, name: e.target.value })}
              className="rounded-[8px] border border-[var(--c-border)] bg-[var(--c-bg)] px-3 py-1.5 outline-none"
            />
            <input
              placeholder="音色 / Voice ID"
              value={vf.voice}
              onChange={(e) => setVf({ ...vf, voice: e.target.value })}
              className="rounded-[8px] border border-[var(--c-border)] bg-[var(--c-bg)] px-3 py-1.5 outline-none"
            />
            <input
              placeholder="Base URL"
              value={vf.base_url}
              onChange={(e) => setVf({ ...vf, base_url: e.target.value })}
              className="rounded-[8px] border border-[var(--c-border)] bg-[var(--c-bg)] px-3 py-1.5 outline-none"
            />
            <input
              type="password"
              placeholder="API Key"
              value={vf.api_key}
              onChange={(e) => setVf({ ...vf, api_key: e.target.value })}
              className="rounded-[8px] border border-[var(--c-border)] bg-[var(--c-bg)] px-3 py-1.5 outline-none"
            />
            <div className="flex justify-end gap-2 md:col-span-2">
              <button
                type="button"
                onClick={() => setAddingVoice(false)}
                className="rounded-[8px] border border-[var(--c-border)] px-3 py-1 text-[12.5px]"
              >
                取消
              </button>
              <button
                type="button"
                onClick={handleAddVoice}
                className="rounded-[8px] bg-[var(--c-accent)] px-3.5 py-1 text-[12.5px] font-medium text-[var(--c-on-accent)]"
              >
                保存
              </button>
            </div>
          </div>
        )}

        {voiceList.length === 0 ? (
          <div className="flex items-center gap-2 rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] p-4 text-[13px] text-[var(--c-text-2)]">
            <Waveform size={16} weight="duotone" style={{ color: 'var(--c-tone-teal)' }} />
            <span>尚未配置语音服务商</span>
          </div>
        ) : (
          <div className="space-y-2">
            {voiceList.map((v) => (
              <div
                key={v.name}
                className="flex items-center justify-between rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] px-4 py-3 text-[13px]"
              >
                <div>
                  <div className="font-semibold text-[var(--c-text)]">{v.name}</div>
                  <div className="text-[12px] text-[var(--c-text-2)]">
                    {v.provider} {v.voice ? `· ${v.voice}` : ''}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={async () => {
                      const r = await voiceApi.test(v.name);
                      if (r.ok) notify(`试听合成成功 (${r.data?.bytes ?? 0} bytes)`, 'success');
                      else notify(r.error || '测试失败', 'error');
                    }}
                    className="inline-flex items-center gap-1 rounded-[8px] border border-[var(--c-border)] px-2.5 py-1 text-[12px]"
                  >
                    <Play size={13} weight="duotone" />
                    <span>测试</span>
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      if (await confirm(`删除语音服务商 ${v.name}？`, { danger: true })) {
                        await voiceApi.remove(v.name);
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

      {/* Moments Auto Poster */}
      <div className="overflow-hidden rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] text-[13px] shadow-2xs">
        <div
          className="flex items-center justify-between border-b border-[var(--c-border)] px-4 py-2.5"
          style={{ backgroundColor: 'var(--c-tone-teal-soft)' }}
        >
          <div className="flex items-center gap-2">
            <span className="h-3.5 w-[3px] rounded-full" style={{ backgroundColor: 'var(--c-tone-teal)' }} />
            <span className="font-semibold text-[var(--c-text)]">自动发动态</span>
          </div>
          <Switch.Root
            checked={autoCfg.enabled}
            onCheckedChange={(c) => setAutoCfg({ ...autoCfg, enabled: c })}
            className="relative h-5 w-9 shrink-0 cursor-pointer rounded-full bg-[var(--c-surface-3)] transition data-[state=checked]:bg-[var(--c-accent)]"
          >
            <Switch.Thumb className="block h-4 w-4 translate-x-0.5 rounded-full bg-white shadow-2xs transition-transform data-[state=checked]:translate-x-[18px]" />
          </Switch.Root>
        </div>

        <div className="space-y-3.5 p-4">
          <div className="text-[12px] text-[var(--c-text-2)]">让伴侣按时间间隔分享生活日常</div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <div>
              <label className="mb-1 block text-[12px] text-[var(--c-text-2)]">发布角色</label>
              <select
                value={autoCfg.persona_id}
                onChange={(e) => setAutoCfg({ ...autoCfg, persona_id: e.target.value })}
                className="w-full rounded-[8px] border border-[var(--c-border)] bg-[var(--c-bg)] px-2.5 py-1.5 text-[var(--c-text)] outline-none"
              >
                <option value="">请选择</option>
                {autoPersonas.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[12px] text-[var(--c-text-2)]">间隔（分钟）</label>
              <input
                type="number"
                min={30}
                value={autoCfg.interval_minutes}
                onChange={(e) => setAutoCfg({ ...autoCfg, interval_minutes: Number(e.target.value) })}
                className="w-full rounded-[8px] border border-[var(--c-border)] bg-[var(--c-bg)] px-2.5 py-1.5 text-[var(--c-text)] outline-none"
              />
            </div>
            <div className="flex items-end gap-2">
              <button
                type="button"
                onClick={handleSaveAuto}
                className="rounded-[8px] bg-[var(--c-accent)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--c-on-accent)]"
              >
                保存
              </button>
              <button
                type="button"
                onClick={async () => {
                  const r = await momentsAutoApi.publish();
                  if (r.ok) notify('已触发发布一条动态', 'success');
                  else notify(r.error || '发布失败', 'error');
                }}
                className="inline-flex items-center gap-1 rounded-[8px] border border-[var(--c-border)] px-3 py-1.5 text-[12.5px]"
              >
                <Feather size={14} weight="duotone" style={{ color: 'var(--c-tone-teal)' }} />
                <span>立即发一条</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
