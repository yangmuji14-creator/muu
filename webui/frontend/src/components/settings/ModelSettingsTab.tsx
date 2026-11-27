import { useEffect, useState } from 'react';
import {
  ArrowsClockwise,
  Check,
  Eye,
  Lightning,
  Plus,
  Trash,
} from '@phosphor-icons/react';
import {
  BootstrapProvider,
  ModelProviderItem,
  ModelRolesResponse,
  bootstrapApi,
  modelApi,
  visionApi,
} from '../../api/settings';
import { useApp } from '../../store/AppContext';

export function ModelSettingsTab() {
  const { modelSummary, reloadModels, confirm, notify } = useApp();

  const [presets, setPresets] = useState<BootstrapProvider[]>([]);
  const [roles, setRoles] = useState<ModelRolesResponse | null>(null);
  const [imageChain, setImageChain] = useState('');

  // Add Provider form state (Chatbox-style)
  const [addingOpen, setAddingOpen] = useState(false);
  const [selectedPresetKey, setSelectedPresetKey] = useState<string>('custom');
  const [form, setForm] = useState({
    key: '',
    provider: 'openai',
    model_name: '',
    base_url: '',
    api_key: '',
    multimodal: 'auto' as 'auto' | 'yes' | 'no',
  });
  const [discovered, setDiscovered] = useState<string[]>([]);
  const [discovering, setDiscovering] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [saving, setSaving] = useState(false);

  const loadAll = async () => {
    await reloadModels();
    const [pRes, rRes, vRes] = await Promise.all([
      bootstrapApi.providers(),
      modelApi.roles(),
      visionApi.get(),
    ]);
    if (pRes.ok && pRes.data?.providers) setPresets(pRes.data.providers);
    if (rRes.ok && rRes.data) setRoles(rRes.data);
    if (vRes.ok && vRes.data) setImageChain(vRes.data.image_chain || '');
  };

  useEffect(() => {
    loadAll();
  }, []);

  const providers: ModelProviderItem[] = modelSummary?.providers || [];
  const currentKey = modelSummary?.current || '';

  const applyPreset = (p: BootstrapProvider | null) => {
    setTestResult(null);
    setDiscovered([]);
    if (!p) {
      setSelectedPresetKey('custom');
      setForm({
        key: '',
        provider: 'openai',
        model_name: '',
        base_url: '',
        api_key: '',
        multimodal: 'auto',
      });
      return;
    }
    setSelectedPresetKey(p.key);
    setForm({
      key: p.key,
      provider: p.provider || p.key,
      model_name: p.default_model || '',
      base_url: p.base_url || '',
      api_key: '',
      multimodal: 'auto',
    });
  };

  const handleDiscover = async () => {
    if (!form.base_url.trim()) {
      notify('请先填写 API Base URL', 'error');
      return;
    }
    setDiscovering(true);
    const r = await modelApi.discover(form.base_url.trim(), form.api_key.trim());
    setDiscovering(false);
    if (r.ok && r.data?.ok) {
      const list = r.data.models || [];
      setDiscovered(list);
      if (list.length > 0 && !form.model_name) {
        setForm((f) => ({ ...f, model_name: list[0] }));
      }
      notify(`已拉取 ${list.length} 个可用模型`, 'success');
    } else {
      notify(r.data?.message || r.error || '拉取模型失败，请手动填写模型名', 'error');
    }
  };

  const handleTest = async () => {
    if (!form.base_url.trim() || !form.api_key.trim() || !form.model_name.trim()) {
      notify('请完整填写地址、模型名与 API Key', 'error');
      return;
    }
    setTesting(true);
    setTestResult(null);
    const r = await bootstrapApi.test({
      provider: form.provider || form.key || 'openai',
      base_url: form.base_url.trim(),
      api_key: form.api_key.trim(),
      model_name: form.model_name.trim(),
    });
    setTesting(false);
    setTestResult({
      ok: Boolean(r.ok && r.data?.ok),
      text: r.data?.message || r.error || (r.ok ? '连接正常' : '连接测试失败'),
    });
  };

  const handleSaveProvider = async () => {
    if (!form.key.trim() || !form.model_name.trim() || !form.base_url.trim() || !form.api_key.trim()) {
      notify('请填写配置键名、Base URL、模型名与 API Key', 'error');
      return;
    }
    setSaving(true);
    const r = await modelApi.addProvider({
      key: form.key.trim(),
      provider: form.provider.trim() || 'openai',
      model_name: form.model_name.trim(),
      base_url: form.base_url.trim().replace(/\/+$/, ''),
      api_key: form.api_key.trim(),
      multimodal: form.multimodal,
    });
    setSaving(false);
    if (r.ok) {
      setAddingOpen(false);
      applyPreset(null);
      await loadAll();
      notify('模型提供商已添加并激活', 'success');
    } else {
      notify(r.error || '添加失败', 'error');
    }
  };

  const handleSetDefault = async (key: string) => {
    const r = await modelApi.set(key);
    if (r.ok) {
      await loadAll();
      notify(`默认模型已切换为 ${key}`, 'success');
    } else {
      notify(r.error || '切换失败', 'error');
    }
  };

  const handleToggleVision = async (p: ModelProviderItem) => {
    const next = p.multimodal === 'yes' ? 'no' : 'yes';
    const r = await modelApi.setMultimodal(p.key, next);
    if (r.ok) {
      await loadAll();
      notify(next === 'yes' ? '已启用原生看图' : '已关闭原生看图', 'success');
    } else {
      notify(r.error || '更新失败', 'error');
    }
  };

  const handleRemove = async (key: string) => {
    const ok = await confirm(`确定移除模型提供商「${key}」吗？`, {
      title: '移除提供商',
      confirmText: '移除',
      danger: true,
    });
    if (!ok) return;
    const r = await modelApi.remove(key);
    if (r.ok) {
      await loadAll();
      notify('已移除提供商', 'success');
    } else {
      notify(r.error || '移除失败', 'error');
    }
  };

  return (
    <div className="space-y-5">
      {/* Header Action Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-[15px] font-semibold text-[var(--c-text)]">模型提供商</h3>
          <p className="mt-0.5 text-[12.5px] text-[var(--c-text-2)]">
            像 Chatbox 一样自由接入兼容 OpenAI 协议的模型服务商，密钥保存在本地配置中。
          </p>
        </div>

        <button
          type="button"
          data-cursor="block"
          onClick={() => {
            if (!addingOpen) applyPreset(null);
            setAddingOpen((v) => !v);
          }}
          className="inline-flex items-center gap-1.5 rounded-[8px] bg-[var(--c-accent)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--c-on-accent)] transition hover:bg-[var(--c-accent-hover)]"
        >
          <Plus size={15} weight="bold" />
          <span>{addingOpen ? '收起添加面板' : '添加模型提供商'}</span>
        </button>
      </div>

      {/* Add Provider Form */}
      {addingOpen && (
        <div className="overflow-hidden rounded-[12px] border border-[var(--c-accent-border)] bg-[var(--c-surface)] shadow-2xs">
          <div
            className="flex items-center gap-2 border-b border-[var(--c-border)] px-4 py-2.5 text-[13px] font-semibold text-[var(--c-text)]"
            style={{ backgroundColor: 'var(--c-tone-blue-soft)' }}
          >
            <span className="h-3.5 w-[3px] rounded-full" style={{ backgroundColor: 'var(--c-tone-blue)' }} />
            <span>配置新模型端点</span>
          </div>

          <div className="space-y-4 p-4">
            {presets.length > 0 && (
              <div>
                <div className="mb-2 text-[12px] font-medium text-[var(--c-text-2)]">
                  快速选择预设或自定义端点
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {presets.map((p) => (
                    <button
                      key={p.key}
                      type="button"
                      onClick={() => applyPreset(p)}
                      className={`rounded-[7px] border px-2.5 py-1 text-[12px] transition ${
                        selectedPresetKey === p.key
                          ? 'border-[var(--c-accent)] bg-[var(--c-accent-soft)] font-medium text-[var(--c-accent)]'
                          : 'border-[var(--c-border)] bg-[var(--c-surface-2)] text-[var(--c-text-2)] hover:text-[var(--c-text)]'
                      }`}
                    >
                      {p.label}
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={() => applyPreset(null)}
                    className={`rounded-[7px] border px-2.5 py-1 text-[12px] transition ${
                      selectedPresetKey === 'custom'
                        ? 'border-[var(--c-accent)] bg-[var(--c-accent-soft)] font-medium text-[var(--c-accent)]'
                        : 'border-[var(--c-border)] bg-[var(--c-surface-2)] text-[var(--c-text-2)] hover:text-[var(--c-text)]'
                    }`}
                  >
                    自定义 OpenAI 兼容
                  </button>
                </div>
              </div>
            )}

            <div className="grid grid-cols-1 gap-3 text-[13px] md:grid-cols-2">
              <div>
                <label className="mb-1 block text-[12px] text-[var(--c-text-2)]">配置标识 Key</label>
                <input
                  value={form.key}
                  onChange={(e) => setForm({ ...form, key: e.target.value })}
                  placeholder="例如：openai / siliconflow / local"
                  className="w-full rounded-[8px] border border-[var(--c-border)] bg-[var(--c-bg)] px-3 py-1.5 text-[var(--c-text)] outline-none focus:border-[var(--c-accent-border)]"
                />
              </div>

              <div>
                <label className="mb-1 block text-[12px] text-[var(--c-text-2)]">接口协议 Provider</label>
                <input
                  value={form.provider}
                  onChange={(e) => setForm({ ...form, provider: e.target.value })}
                  placeholder="openai / deepseek"
                  className="w-full rounded-[8px] border border-[var(--c-border)] bg-[var(--c-bg)] px-3 py-1.5 text-[var(--c-text)] outline-none focus:border-[var(--c-accent-border)]"
                />
              </div>

              <div className="md:col-span-2">
                <label className="mb-1 block text-[12px] text-[var(--c-text-2)]">API Base URL</label>
                <input
                  value={form.base_url}
                  onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                  placeholder="https://api.example.com/v1"
                  className="w-full rounded-[8px] border border-[var(--c-border)] bg-[var(--c-bg)] px-3 py-1.5 font-mono text-[12.5px] text-[var(--c-text)] outline-none focus:border-[var(--c-accent-border)]"
                />
              </div>

              <div className="md:col-span-2">
                <label className="mb-1 block text-[12px] text-[var(--c-text-2)]">API Key</label>
                <input
                  type="password"
                  value={form.api_key}
                  onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                  placeholder="sk-..."
                  className="w-full rounded-[8px] border border-[var(--c-border)] bg-[var(--c-bg)] px-3 py-1.5 font-mono text-[12.5px] text-[var(--c-text)] outline-none focus:border-[var(--c-accent-border)]"
                />
              </div>

              <div className="md:col-span-2">
                <div className="mb-1 flex items-center justify-between">
                  <label className="text-[12px] text-[var(--c-text-2)]">模型 ID (model_name)</label>
                  <button
                    type="button"
                    onClick={handleDiscover}
                    disabled={discovering}
                    className="inline-flex items-center gap-1 text-[12px] font-medium text-[var(--c-accent)] hover:underline"
                  >
                    <ArrowsClockwise size={13} weight="bold" className={discovering ? 'animate-spin' : ''} />
                    <span>从服务商拉取模型</span>
                  </button>
                </div>
                <input
                  value={form.model_name}
                  onChange={(e) => setForm({ ...form, model_name: e.target.value })}
                  placeholder="输入模型名称，或点击右上角自动拉取"
                  className="w-full rounded-[8px] border border-[var(--c-border)] bg-[var(--c-bg)] px-3 py-1.5 font-mono text-[12.5px] text-[var(--c-text)] outline-none focus:border-[var(--c-accent-border)]"
                />
                {discovered.length > 0 && (
                  <div className="mt-2 flex max-h-24 flex-wrap gap-1 overflow-y-auto rounded-[8px] border border-[var(--c-border)] bg-[var(--c-bg)] p-2">
                    {discovered.map((id) => (
                      <button
                        key={id}
                        type="button"
                        onClick={() => setForm({ ...form, model_name: id })}
                        className={`rounded-[6px] px-2 py-0.5 font-mono text-[11px] ${
                          form.model_name === id
                            ? 'bg-[var(--c-accent)] text-[var(--c-on-accent)]'
                            : 'bg-[var(--c-surface)] text-[var(--c-text-2)] hover:text-[var(--c-text)]'
                        }`}
                      >
                        {id}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {testResult && (
              <div
                className={`rounded-[8px] px-3 py-2 text-[12.5px] ${
                  testResult.ok
                    ? 'bg-emerald-500/10 text-[var(--c-success)]'
                    : 'bg-rose-500/10 text-[var(--c-error)]'
                }`}
              >
                {testResult.text}
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
              <button
                type="button"
                onClick={handleTest}
                disabled={testing}
                className="inline-flex items-center gap-1.5 rounded-[8px] border border-[var(--c-border)] px-3 py-1.5 text-[12.5px] font-medium text-[var(--c-text)] hover:bg-[var(--c-surface-2)]"
              >
                <Lightning size={15} weight="duotone" style={{ color: 'var(--c-tone-amber)' }} />
                <span>{testing ? '测试中…' : '测试连通性'}</span>
              </button>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setAddingOpen(false)}
                  className="rounded-[8px] border border-[var(--c-border)] px-3.5 py-1.5 text-[12.5px] text-[var(--c-text-2)]"
                >
                  取消
                </button>
                <button
                  type="button"
                  disabled={saving}
                  onClick={handleSaveProvider}
                  className="rounded-[8px] bg-[var(--c-accent)] px-4 py-1.5 text-[12.5px] font-medium text-[var(--c-on-accent)] disabled:opacity-40"
                >
                  {saving ? '保存中…' : '保存提供商'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Configured Providers List (100% dynamic from backend) */}
      {providers.length === 0 ? (
        <div className="rounded-[12px] border border-dashed border-[var(--c-border-strong)] bg-[var(--c-surface)] p-8 text-center">
          <div className="text-[14px] font-medium text-[var(--c-text)]">尚未添加任何模型提供商</div>
          <p className="mt-1 text-[12.5px] text-[var(--c-text-2)]">
            点击右上角「添加模型提供商」，填写 API 地址与密钥即可启用流式对话。
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {providers.map((p) => {
            const isCurrent = p.key === currentKey;
            const mmYes = p.multimodal === 'yes';
            return (
              <div
                key={p.key}
                className={`rounded-[12px] border p-4 transition ${
                  isCurrent
                    ? 'border-[var(--c-accent)] bg-[var(--c-accent-soft)]'
                    : 'border-[var(--c-border)] bg-[var(--c-surface)]'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-[14px] font-semibold text-[var(--c-text)]">
                        {p.model_name || p.key}
                      </span>
                      {isCurrent && (
                        <span className="inline-flex items-center gap-0.5 rounded-[6px] bg-[var(--c-accent)] px-2 py-0.5 text-[10.5px] font-medium text-[var(--c-on-accent)]">
                          <Check size={11} weight="bold" />
                          默认
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 truncate font-mono text-[11.5px] text-[var(--c-text-2)]">
                      {p.key} · {p.base_url || '未配置地址'}
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={() => handleRemove(p.key)}
                    className="rounded-[8px] p-1.5 text-[var(--c-text-2)] hover:bg-[var(--c-surface-2)] hover:text-[var(--c-error)]"
                    title="删除提供商"
                  >
                    <Trash size={15} weight="duotone" />
                  </button>
                </div>

                <div className="mt-3.5 flex flex-wrap items-center gap-2">
                  {!isCurrent && (
                    <button
                      type="button"
                      onClick={() => handleSetDefault(p.key)}
                      className="rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] px-2.5 py-1 text-[12px] font-medium text-[var(--c-text)] hover:border-[var(--c-accent-border)]"
                    >
                      设为默认
                    </button>
                  )}

                  <button
                    type="button"
                    onClick={() => handleToggleVision(p)}
                    className={`inline-flex items-center gap-1 rounded-[8px] border px-2.5 py-1 text-[12px] transition ${
                      mmYes
                        ? 'border-[var(--c-accent-border)] bg-[var(--c-surface)] font-medium text-[var(--c-accent)]'
                        : 'border-[var(--c-border)] bg-[var(--c-surface)] text-[var(--c-text-2)]'
                    }`}
                  >
                    <Eye size={13} weight="duotone" />
                    <span>{mmYes ? '支持原生看图' : '纯文本'}</span>
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Role Summary */}
      {roles && (
        <div className="overflow-hidden rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] text-[12.5px] shadow-2xs">
          <div
            className="flex items-center gap-2 border-b border-[var(--c-border)] px-4 py-2.5 font-semibold text-[var(--c-text)]"
            style={{ backgroundColor: 'var(--c-tone-violet-soft)' }}
          >
            <span className="h-3.5 w-[3px] rounded-full" style={{ backgroundColor: 'var(--c-tone-violet)' }} />
            <span>当前模型职责分配</span>
          </div>
          <div className="grid grid-cols-1 gap-2 p-3.5 md:grid-cols-3">
            <div className="rounded-[8px] bg-[var(--c-bg)]/70 px-3 py-2 border border-[var(--c-border)]/70">
              <div className="text-[11px] text-[var(--c-text-2)]">主对话语言模型</div>
              <div className="mt-0.5 truncate font-mono text-[var(--c-text)]">
                {roles.chat?.model_name || '未分配'}
              </div>
            </div>
            <div className="rounded-[8px] bg-[var(--c-bg)]/70 px-3 py-2 border border-[var(--c-border)]/70">
              <div className="text-[11px] text-[var(--c-text-2)]">备用图片识别</div>
              <div className="mt-0.5 truncate font-mono text-[var(--c-text)]">
                {roles.vision?.model_name || '随主模型直连'}
              </div>
            </div>
            <div className="rounded-[8px] bg-[var(--c-bg)]/70 px-3 py-2 border border-[var(--c-border)]/70">
              <div className="text-[11px] text-[var(--c-text-2)]">图片链路状态</div>
              <div className="mt-0.5 truncate text-[var(--c-text)]">
                {imageChain || '自动检测'}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
