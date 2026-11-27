import { useEffect, useState } from 'react';
import * as Switch from '@radix-ui/react-switch';
import { FloppyDisk } from '@phosphor-icons/react';
import { SchemaField, settingsApi } from '../../api/settings';
import { useApp } from '../../store/AppContext';

const SECTION_TONES = [
  { color: 'var(--c-tone-blue)', soft: 'var(--c-tone-blue-soft)' },
  { color: 'var(--c-tone-violet)', soft: 'var(--c-tone-violet-soft)' },
  { color: 'var(--c-tone-teal)', soft: 'var(--c-tone-teal-soft)' },
  { color: 'var(--c-tone-amber)', soft: 'var(--c-tone-amber-soft)' },
  { color: 'var(--c-tone-rose)', soft: 'var(--c-tone-rose-soft)' },
];

export function ParamsSettingsTab() {
  const { notify } = useApp();
  const [schema, setSchema] = useState<SchemaField[]>([]);
  const [values, setValues] = useState<Record<string, number | boolean>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    Promise.all([settingsApi.schema(), settingsApi.get()]).then(([sRes, vRes]) => {
      if (sRes.ok && sRes.data?.schema) setSchema(sRes.data.schema);
      if (vRes.ok && vRes.data?.values) setValues(vRes.data.values);
      setLoading(false);
    });
  }, []);

  const handleSave = async () => {
    setSaving(true);
    const r = await settingsApi.save(values);
    setSaving(false);
    if (r.ok) {
      if (r.data?.values) setValues(r.data.values);
      notify('参数已保存并实时生效', 'success');
    } else {
      notify(r.error || '保存失败', 'error');
    }
  };

  const sections = Array.from(new Set(schema.map((f) => f.section)));

  if (loading) {
    return <div className="py-10 text-center text-[13px] text-[var(--c-text-2)]">加载配置项…</div>;
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-[15px] font-semibold text-[var(--c-text)]">对话与行为参数</h3>
          <p className="mt-0.5 text-[12.5px] text-[var(--c-text-2)]">
            直接由后端 Schema 生成，覆盖温度、分段节奏、主动关怀与记忆提取策略。
          </p>
        </div>

        <button
          type="button"
          data-cursor="block"
          disabled={saving}
          onClick={handleSave}
          className="inline-flex items-center gap-1.5 rounded-[8px] bg-[var(--c-accent)] px-4 py-1.5 text-[12.5px] font-medium text-[var(--c-on-accent)] hover:bg-[var(--c-accent-hover)] disabled:opacity-40"
        >
          <FloppyDisk size={15} weight="duotone" />
          <span>{saving ? '保存中…' : '保存更改'}</span>
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {sections.map((section, sIdx) => {
          const tone = SECTION_TONES[sIdx % SECTION_TONES.length];
          const sectionFields = schema.filter((f) => f.section === section);
          return (
            <div
              key={section}
              className="overflow-hidden rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] shadow-2xs"
            >
              {/* Layer 1: Tinted Header Band */}
              <div
                className="flex items-center justify-between border-b border-[var(--c-border)] px-4 py-2.5"
                style={{ backgroundColor: tone.soft }}
              >
                <div className="flex items-center gap-2">
                  <span
                    className="h-3.5 w-[3px] rounded-full"
                    style={{ backgroundColor: tone.color }}
                  />
                  <span className="text-[13.5px] font-semibold text-[var(--c-text)]">
                    {section}
                  </span>
                </div>
                <span
                  className="rounded-[6px] px-2 py-0.5 text-[11px] font-medium"
                  style={{ backgroundColor: 'var(--c-surface)', color: tone.color }}
                >
                  {sectionFields.length} 项
                </span>
              </div>

              {/* Layer 2: Soft Recessed Control Rows */}
              <div className="space-y-2.5 p-3.5">
                {sectionFields.map((field) => {
                  const val = values[field.key] ?? field.default;
                  if (field.type === 'bool') {
                    const checked = Boolean(val);
                    return (
                      <div
                        key={field.key}
                        className="flex items-start justify-between gap-3 rounded-[9px] border border-[var(--c-border)]/75 bg-[var(--c-bg)]/60 px-3.5 py-2.5 transition hover:border-[var(--c-border-strong)]"
                      >
                        <div>
                          <div className="text-[13px] font-medium text-[var(--c-text)]">
                            {field.label}
                          </div>
                          {field.hint && (
                            <div className="mt-0.5 text-[11.5px] text-[var(--c-text-2)]">
                              {field.hint}
                            </div>
                          )}
                        </div>
                        <Switch.Root
                          checked={checked}
                          onCheckedChange={(c) =>
                            setValues((v) => ({ ...v, [field.key]: c }))
                          }
                          style={checked ? { backgroundColor: tone.color } : undefined}
                          className="relative mt-0.5 h-5 w-9 shrink-0 cursor-pointer rounded-full bg-[var(--c-surface-3)] transition"
                        >
                          <Switch.Thumb className="block h-4 w-4 translate-x-0.5 rounded-full bg-white shadow-2xs transition-transform data-[state=checked]:translate-x-[18px]" />
                        </Switch.Root>
                      </div>
                    );
                  }

                  const numVal = Number(val ?? field.default);
                  return (
                    <div
                      key={field.key}
                      className="rounded-[9px] border border-[var(--c-border)]/75 bg-[var(--c-bg)]/60 px-3.5 py-2.5 transition hover:border-[var(--c-border-strong)]"
                    >
                      <div className="mb-1.5 flex items-center justify-between text-[13px]">
                        <span className="font-medium text-[var(--c-text)]">{field.label}</span>
                        <span
                          className="rounded-[6px] px-2 py-0.5 font-mono text-[11.5px] font-semibold"
                          style={{ backgroundColor: tone.soft, color: tone.color }}
                        >
                          {field.type === 'float' ? numVal.toFixed(2) : numVal}
                        </span>
                      </div>
                      <input
                        type="range"
                        min={field.min ?? 0}
                        max={field.max ?? 100}
                        step={field.step ?? (field.type === 'float' ? 0.05 : 1)}
                        value={numVal}
                        onChange={(e) =>
                          setValues((v) => ({ ...v, [field.key]: Number(e.target.value) }))
                        }
                        style={{ accentColor: tone.color }}
                        className="w-full cursor-pointer"
                      />
                      {field.hint && (
                        <div className="mt-1 text-[11.5px] text-[var(--c-text-2)]">{field.hint}</div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
