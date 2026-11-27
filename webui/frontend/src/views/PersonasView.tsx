import { useEffect, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {
  CaretDown,
  ChatTeardropDots,
  Plus,
  Trash,
  UploadSimple,
  X,
} from '@phosphor-icons/react';
import {
  PersonaDetail,
  PersonaSummary,
  PersonaTagsMeta,
  personasApi,
} from '../api/personas';
import { useApp } from '../store/AppContext';

const TAG_TONES = [
  { color: 'var(--c-tone-blue)', soft: 'var(--c-tone-blue-soft)' },
  { color: 'var(--c-tone-violet)', soft: 'var(--c-tone-violet-soft)' },
  { color: 'var(--c-tone-teal)', soft: 'var(--c-tone-teal-soft)' },
  { color: 'var(--c-tone-amber)', soft: 'var(--c-tone-amber-soft)' },
  { color: 'var(--c-tone-rose)', soft: 'var(--c-tone-rose-soft)' },
];

export function PersonasView() {
  const {
    personas,
    reloadPersonas,
    startNewConversation,
    navigate,
    confirm,
    notify,
  } = useApp();

  const [selected, setSelected] = useState<PersonaDetail | null>(null);
  const [advanced, setAdvanced] = useState<Record<string, unknown> | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [savingEdit, setSavingEdit] = useState(false);

  const [createOpen, setCreateOpen] = useState(false);
  const [tagsMeta, setTagsMeta] = useState<PersonaTagsMeta | null>(null);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [drafts, setDrafts] = useState({ speaking: '', emotion: '', relationship: '' });
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    personasApi.tags().then((r) => {
      if (r.ok && r.data) setTagsMeta(r.data);
    });
  }, []);

  const openEditor = async (p: PersonaSummary) => {
    setShowAdvanced(false);
    setAdvanced(null);
    const r = await personasApi.get(p.id);
    if (r.ok && r.data) setSelected(r.data);
    else notify(r.error || '读取角色失败', 'error');
  };

  const toggleTag = async (tag: string) => {
    let next: string[];
    if (selectedTags.includes(tag)) {
      next = selectedTags.filter((t) => t !== tag);
    } else {
      const limit = tagsMeta?.max_tags || 3;
      const mutex = (tagsMeta?.mutex_groups || []).filter((g) => g.includes(tag)).flat();
      next = [...selectedTags.filter((t) => !mutex.includes(t)), tag].slice(0, limit);
    }
    setSelectedTags(next);
    if (next.length > 0) {
      const r = await personasApi.previewTags(next);
      if (r.ok && r.data) {
        setDrafts({
          speaking: r.data.speaking || '',
          emotion: r.data.emotion || '',
          relationship: r.data.relationship || '',
        });
      }
    } else {
      setDrafts({ speaking: '', emotion: '', relationship: '' });
    }
  };

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name || creating) return;
    setCreating(true);
    const r = await personasApi.create({
      name,
      description: newDesc.trim() || undefined,
      personality: selectedTags,
      drafts:
        drafts.speaking || drafts.emotion || drafts.relationship ? drafts : undefined,
    });
    setCreating(false);
    if (r.ok) {
      setCreateOpen(false);
      setNewName('');
      setNewDesc('');
      setSelectedTags([]);
      setDrafts({ speaking: '', emotion: '', relationship: '' });
      await reloadPersonas();
      notify('角色已创建', 'success');
    } else {
      notify(r.error || '创建失败', 'error');
    }
  };

  const handleSaveEdit = async () => {
    if (!selected || savingEdit) return;
    setSavingEdit(true);
    const fields: Record<string, unknown> = {
      name: selected.name,
      age: selected.age ?? null,
      gender: selected.gender ?? '',
      occupation: selected.occupation ?? '',
      background: selected.background ?? '',
      speaking_style: selected.speaking_style ?? '',
      relationship: selected.relationship ?? '',
      ...(showAdvanced && advanced ? advanced : {}),
    };
    delete fields.id;
    const r = await personasApi.update(selected.id, fields);
    setSavingEdit(false);
    if (r.ok) {
      await reloadPersonas();
      setSelected(null);
      notify('角色设定已保存', 'success');
    } else {
      notify(r.error || '保存失败', 'error');
    }
  };

  const handleDelete = async (p: PersonaSummary) => {
    const ok = await confirm(`确定删除角色「${p.name}」吗？`, {
      title: '删除角色',
      danger: true,
    });
    if (!ok) return;
    const r = await personasApi.remove(p.id);
    if (r.ok) {
      await reloadPersonas();
      notify('角色已删除', 'success');
    } else {
      notify(r.error || '无法删除该角色', 'error');
    }
  };

  return (
    <div className="h-full overflow-y-auto px-4 pb-16 pt-16 md:px-8">
      <div className="mx-auto max-w-[960px] space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-[22px] font-semibold tracking-tight text-[var(--c-text)]">角色</h1>
            <p className="mt-0.5 text-[13px] text-[var(--c-text-2)]">
              管理伴侣人设、说话方式与关系设定
            </p>
          </div>

          <button
            type="button"
            data-cursor="block"
            onClick={() => setCreateOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-[8px] bg-[var(--c-accent)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--c-on-accent)] transition hover:bg-[var(--c-accent-hover)]"
          >
            <Plus size={15} weight="bold" />
            <span>新建角色</span>
          </button>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {personas.map((p) => (
            <div
              key={p.id}
              className="flex flex-col justify-between rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] p-5 shadow-2xs"
            >
              <div>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-3">
                    {p.avatar && (
                      <img
                        src={p.avatar}
                        alt={p.name}
                        className="h-11 w-11 rounded-[10px] border border-[var(--c-border)] object-cover"
                      />
                    )}
                    <div>
                      <h2 className="text-[16px] font-semibold text-[var(--c-text)]">{p.name}</h2>
                      <div className="mt-0.5 text-[12px] text-[var(--c-text-2)]">
                        {[p.occupation, p.gender, p.age ? `${p.age} 岁` : '']
                          .filter(Boolean)
                          .join(' · ') || p.id}
                      </div>
                    </div>
                  </div>

                  <button
                    type="button"
                    data-cursor="block"
                    onClick={() => handleDelete(p)}
                    className="rounded-[8px] p-1.5 text-[var(--c-text-3)] hover:bg-[var(--c-surface-2)] hover:text-[var(--c-error)]"
                    title="删除角色"
                  >
                    <Trash size={15} weight="duotone" />
                  </button>
                </div>

                {p.summary && (
                  <p className="mt-3 line-clamp-2 text-[13.5px] leading-relaxed text-[var(--c-text-2)]">
                    {p.summary}
                  </p>
                )}

                {p.personality && p.personality.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {p.personality.map((tag, tIdx) => {
                      const tone = TAG_TONES[tIdx % TAG_TONES.length];
                      return (
                        <span
                          key={tag}
                          className="rounded-[6px] px-2 py-0.5 text-[11.5px] font-medium"
                          style={{ backgroundColor: tone.soft, color: tone.color }}
                        >
                          {tag}
                        </span>
                      );
                    })}
                  </div>
                )}
              </div>

              <div className="mt-5 flex items-center gap-2 border-t border-[var(--c-border)] pt-3.5">
                <button
                  type="button"
                  data-cursor="block"
                  onClick={async () => {
                    await startNewConversation(p.id);
                    navigate('chat');
                  }}
                  className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-[8px] bg-[var(--c-accent)] py-2 text-[13px] font-medium text-[var(--c-on-accent)] transition hover:bg-[var(--c-accent-hover)]"
                >
                  <ChatTeardropDots size={15} weight="duotone" />
                  <span>开启对话</span>
                </button>
                <button
                  type="button"
                  data-cursor="block"
                  onClick={() => openEditor(p)}
                  className="rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] px-4 py-2 text-[13px] font-medium text-[var(--c-text)] transition hover:bg-[var(--c-surface-2)]"
                >
                  编辑设定
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Create Persona Dialog */}
      <Dialog.Root open={createOpen} onOpenChange={setCreateOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/35 backdrop-blur-xs" />
          <Dialog.Content className="liquid-glass-modal fixed left-1/2 top-1/2 z-50 max-h-[86vh] w-[min(94vw,520px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-[14px] p-6 outline-none">
            <div className="flex items-center justify-between pb-4">
              <Dialog.Title className="text-[16px] font-semibold text-[var(--c-text)]">
                新建伴侣角色
              </Dialog.Title>
              <button
                type="button"
                onClick={() => setCreateOpen(false)}
                className="rounded-[8px] p-1 text-[var(--c-text-2)] hover:bg-[var(--c-surface-2)]"
              >
                <X size={16} weight="bold" />
              </button>
            </div>

            <div className="space-y-4 text-[13px]">
              <div>
                <label className="mb-1 block font-medium text-[var(--c-text-2)]">称呼 / 名字</label>
                <input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="例如：林澄"
                  className="w-full rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] px-3 py-2 text-[var(--c-text)] outline-none focus:border-[var(--c-accent-border)]"
                />
              </div>

              <div>
                <label className="mb-1 block font-medium text-[var(--c-text-2)]">人物背景简介</label>
                <textarea
                  rows={2}
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  placeholder="简短描述她的身份、生活习惯或你们的相遇…"
                  className="w-full resize-none rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] px-3 py-2 text-[var(--c-text)] outline-none focus:border-[var(--c-accent-border)]"
                />
              </div>

              {tagsMeta && tagsMeta.tags.length > 0 && (
                <div>
                  <label className="mb-1.5 block font-medium text-[var(--c-text-2)]">
                    性格特质（最多 {tagsMeta.max_tags} 个）
                  </label>
                  <div className="flex flex-wrap gap-1.5">
                    {tagsMeta.tags.map((t) => {
                      const on = selectedTags.includes(t);
                      return (
                        <button
                          key={t}
                          type="button"
                          onClick={() => toggleTag(t)}
                          className={`rounded-[7px] border px-2.5 py-1 text-[12px] transition ${
                            on
                              ? 'border-[var(--c-accent)] bg-[var(--c-accent-soft)] font-medium text-[var(--c-accent)]'
                              : 'border-[var(--c-border)] bg-[var(--c-surface)] text-[var(--c-text-2)]'
                          }`}
                        >
                          {t}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {(drafts.speaking || drafts.emotion || drafts.relationship) && (
                <div className="space-y-2.5 rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] p-3.5">
                  <div className="text-[12px] font-medium text-[var(--c-text-2)]">
                    行为风格草稿（可微调）
                  </div>
                  <textarea
                    rows={2}
                    value={drafts.speaking}
                    onChange={(e) => setDrafts((d) => ({ ...d, speaking: e.target.value }))}
                    placeholder="说话风格"
                    className="w-full rounded-[8px] border border-[var(--c-border)] bg-[var(--c-bg)] p-2 text-[12.5px] text-[var(--c-text)] outline-none"
                  />
                  <textarea
                    rows={2}
                    value={drafts.emotion}
                    onChange={(e) => setDrafts((d) => ({ ...d, emotion: e.target.value }))}
                    placeholder="情绪表达"
                    className="w-full rounded-[8px] border border-[var(--c-border)] bg-[var(--c-bg)] p-2 text-[12.5px] text-[var(--c-text)] outline-none"
                  />
                </div>
              )}
            </div>

            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setCreateOpen(false)}
                className="rounded-[8px] border border-[var(--c-border)] px-4 py-1.5 text-[13px] text-[var(--c-text-2)]"
              >
                取消
              </button>
              <button
                type="button"
                disabled={!newName.trim() || creating}
                onClick={handleCreate}
                className="rounded-[8px] bg-[var(--c-accent)] px-4 py-1.5 text-[13px] font-medium text-[var(--c-on-accent)] disabled:opacity-40"
              >
                {creating ? '创建中…' : '创建'}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      {/* Edit Persona Dialog */}
      <Dialog.Root open={Boolean(selected)} onOpenChange={(o) => !o && setSelected(null)}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/35 backdrop-blur-xs" />
          <Dialog.Content className="liquid-glass-modal fixed left-1/2 top-1/2 z-50 max-h-[86vh] w-[min(94vw,560px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-[14px] p-6 outline-none">
            {selected && (
              <>
                <div className="flex items-center justify-between pb-4">
                  <Dialog.Title className="text-[16px] font-semibold text-[var(--c-text)]">
                    编辑 · {selected.name}
                  </Dialog.Title>
                  <button
                    type="button"
                    onClick={() => setSelected(null)}
                    className="rounded-[8px] p-1 text-[var(--c-text-2)] hover:bg-[var(--c-surface-2)]"
                  >
                    <X size={16} weight="bold" />
                  </button>
                </div>

                <div className="space-y-3.5 text-[13px]">
                  <div className="flex items-center justify-between rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] p-3">
                    <div className="flex items-center gap-3">
                      {selected.avatar ? (
                        <img
                          src={selected.avatar}
                          alt={selected.name}
                          className="h-10 w-10 rounded-[8px] object-cover"
                        />
                      ) : (
                        <div className="text-[12px] text-[var(--c-text-2)]">未设置形象图（可选）</div>
                      )}
                    </div>
                    <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-[8px] border border-[var(--c-border)] px-3 py-1.5 text-[12px] font-medium text-[var(--c-text)] hover:bg-[var(--c-surface-2)]">
                      <UploadSimple size={14} weight="duotone" />
                      <span>上传形象图</span>
                      <input
                        type="file"
                        accept="image/*"
                        className="hidden"
                        onChange={async (e) => {
                          const file = e.target.files?.[0];
                          if (!file) return;
                          const r = await personasApi.uploadAvatar(selected.id, file);
                          if (r.ok && r.data?.avatar_url) {
                            setSelected({ ...selected, avatar: r.data.avatar_url });
                            await reloadPersonas();
                            notify('形象图已更新', 'success');
                          } else {
                            notify(r.error || '上传失败', 'error');
                          }
                        }}
                      />
                    </label>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="mb-1 block text-[var(--c-text-2)]">名字</label>
                      <input
                        value={selected.name || ''}
                        onChange={(e) => setSelected({ ...selected, name: e.target.value })}
                        className="w-full rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] px-3 py-1.5 text-[var(--c-text)] outline-none"
                      />
                    </div>
                    <div>
                      <label className="mb-1 block text-[var(--c-text-2)]">职业</label>
                      <input
                        value={selected.occupation || ''}
                        onChange={(e) => setSelected({ ...selected, occupation: e.target.value })}
                        className="w-full rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] px-3 py-1.5 text-[var(--c-text)] outline-none"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="mb-1 block text-[var(--c-text-2)]">背景故事</label>
                    <textarea
                      rows={3}
                      value={selected.background || ''}
                      onChange={(e) => setSelected({ ...selected, background: e.target.value })}
                      className="w-full rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] p-2.5 text-[var(--c-text)] outline-none"
                    />
                  </div>

                  <div>
                    <label className="mb-1 block text-[var(--c-text-2)]">说话风格</label>
                    <textarea
                      rows={2}
                      value={selected.speaking_style || ''}
                      onChange={(e) => setSelected({ ...selected, speaking_style: e.target.value })}
                      className="w-full rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] p-2.5 text-[var(--c-text)] outline-none"
                    />
                  </div>

                  <button
                    type="button"
                    onClick={async () => {
                      const next = !showAdvanced;
                      setShowAdvanced(next);
                      if (next && !advanced) {
                        const r = await personasApi.getAdvanced(selected.id);
                        if (r.ok && r.data) setAdvanced(r.data);
                      }
                    }}
                    className="inline-flex items-center gap-1 text-[12.5px] font-medium text-[var(--c-accent)]"
                  >
                    <CaretDown
                      size={14}
                      weight="bold"
                      className={`transition ${showAdvanced ? 'rotate-180' : ''}`}
                    />
                    <span>高级提示词与硬规则</span>
                  </button>

                  {showAdvanced && advanced && (
                    <div className="space-y-2.5 rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] p-3.5">
                      {Object.entries(advanced).map(([k, v]) =>
                        typeof v === 'string' ? (
                          <div key={k}>
                            <label className="mb-1 block font-mono text-[11px] text-[var(--c-text-3)]">
                              {k}
                            </label>
                            <textarea
                              rows={2}
                              value={v}
                              onChange={(e) =>
                                setAdvanced({ ...advanced, [k]: e.target.value })
                              }
                              className="w-full rounded-[8px] border border-[var(--c-border)] bg-[var(--c-bg)] p-2 text-[12.5px] text-[var(--c-text)] outline-none"
                            />
                          </div>
                        ) : null,
                      )}
                    </div>
                  )}
                </div>

                <div className="mt-6 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setSelected(null)}
                    className="rounded-[8px] border border-[var(--c-border)] px-4 py-1.5 text-[13px] text-[var(--c-text-2)]"
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    disabled={savingEdit}
                    onClick={handleSaveEdit}
                    className="rounded-[8px] bg-[var(--c-accent)] px-4 py-1.5 text-[13px] font-medium text-[var(--c-on-accent)] disabled:opacity-40"
                  >
                    {savingEdit ? '保存中…' : '保存修改'}
                  </button>
                </div>
              </>
            )}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
