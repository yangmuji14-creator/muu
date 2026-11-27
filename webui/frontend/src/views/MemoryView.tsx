import { useCallback, useEffect, useState } from 'react';
import {
  ArrowsClockwise,
  GitBranch,
  Graph,
  ListBullets,
  MagnifyingGlass,
  Trash,
  X,
} from '@phosphor-icons/react';
import {
  LifeSummaryItem,
  MemoryDetail,
  MemoryItem,
  MemoryStatus,
  SemanticSearchResult,
  memoryApi,
} from '../api/memory';
import { friendlyTime } from '../lib/format';
import { useApp } from '../store/AppContext';
import { MemoryMindMap } from './MemoryMindMap';
import { MemoryThoughtChain } from './MemoryThoughtChain';

type MemoryViewMode = 'mindmap' | 'chain' | 'list';

export function MemoryView() {
  const {
    activeConversationId,
    companionState,
    stateRevision,
    confirm,
    notify,
  } = useApp();

  const [mode, setMode] = useState<MemoryViewMode>('mindmap');
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [summaries, setSummaries] = useState<LifeSummaryItem[]>([]);
  const [status, setStatus] = useState<MemoryStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [reindexing, setReindexing] = useState(false);

  const [query, setQuery] = useState('');
  const [semanticHits, setSemanticHits] = useState<SemanticSearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);

  const [selectedMemory, setSelectedMemory] = useState<MemoryItem | null>(null);
  const [detail, setDetail] = useState<MemoryDetail | null>(null);

  const personaId = companionState?.persona_id || undefined;
  const scopeOpts = {
    conversation_id: activeConversationId || undefined,
    persona_id: personaId,
  };

  const loadAll = useCallback(async () => {
    setLoading(true);
    const [memRes, sumRes, stRes] = await Promise.all([
      memoryApi.list({ ...scopeOpts, offset: 0, limit: 80, level_min: 1, level_max: 5 }),
      memoryApi.lifeSummaries({ ...scopeOpts, limit: 30 }),
      memoryApi.status(),
    ]);
    if (memRes.ok && memRes.data) setMemories(memRes.data.messages || []);
    if (sumRes.ok && sumRes.data) setSummaries(sumRes.data.summaries || []);
    if (stRes.ok && stRes.data) setStatus(stRes.data);
    setLoading(false);
  }, [activeConversationId, personaId]);

  useEffect(() => {
    loadAll();
  }, [loadAll, stateRevision]);

  const handleSelectMemory = async (m: MemoryItem) => {
    setSelectedMemory(m);
    setDetail(null);
    const r = await memoryApi.detail(m.id, scopeOpts);
    if (r.ok && r.data) setDetail(r.data);
  };

  const handleSearch = async () => {
    const q = query.trim();
    if (!q) {
      setSemanticHits(null);
      return;
    }
    setSearching(true);
    const r = await memoryApi.search(q, { ...scopeOpts, top_k: 10 });
    setSearching(false);
    if (r.ok && r.data) {
      setSemanticHits(r.data.results || []);
      setMode('list');
    } else {
      notify(r.error || '检索失败', 'error');
    }
  };

  const handleReindex = async () => {
    setReindexing(true);
    const r = await memoryApi.reindex({ ...scopeOpts, force: false });
    setReindexing(false);
    if (r.ok) {
      notify('记忆向量索引已更新', 'success');
      const stRes = await memoryApi.status();
      if (stRes.ok && stRes.data) setStatus(stRes.data);
    } else {
      notify(r.error || '重建索引失败', 'error');
    }
  };

  const handleDelete = async (m: MemoryItem) => {
    const ok = await confirm('确定删除这条记忆吗？删除后无法恢复。', {
      title: '删除记忆',
      confirmText: '删除',
      danger: true,
    });
    if (!ok) return;
    const r = await memoryApi.remove(m.id, scopeOpts);
    if (r.ok) {
      setMemories((prev) => prev.filter((x) => x.id !== m.id));
      if (selectedMemory?.id === m.id) {
        setSelectedMemory(null);
        setDetail(null);
      }
      notify('记忆已删除', 'success');
    } else {
      notify(r.error || '删除失败', 'error');
    }
  };

  const personaName = companionState?.persona_name || '慕';

  return (
    <div className="h-full overflow-y-auto px-4 pb-14 pt-16 md:px-8">
      <div className="mx-auto max-w-[1060px] space-y-5">
        {/* Header & Mode Switch */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-[22px] font-semibold tracking-tight text-[var(--c-text)]">
              记忆与思维图谱
            </h1>
            <p className="mt-0.5 text-[13px] text-[var(--c-text-2)]">
              {memories.length} 条重要记忆 · {summaries.length} 篇成长摘要
              {status?.loaded !== undefined && (
                <span> · 向量索引 {status.loaded ? '已就绪' : '关键词模式'}</span>
              )}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* Search Box */}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleSearch();
              }}
              className="flex items-center gap-1.5 rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] px-2.5 py-1.5"
            >
              <MagnifyingGlass size={14} weight="duotone" className="text-[var(--c-text-2)]" />
              <input
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  if (!e.target.value.trim()) setSemanticHits(null);
                }}
                placeholder="语义检索记忆…"
                className="w-36 bg-transparent text-[13px] text-[var(--c-text)] placeholder-[var(--c-text-3)] outline-none md:w-48"
              />
              {searching && (
                <ArrowsClockwise size={14} weight="bold" className="animate-spin text-[var(--c-accent)]" />
              )}
            </form>

            <button
              type="button"
              data-cursor="block"
              onClick={handleReindex}
              disabled={reindexing}
              className="inline-flex items-center gap-1.5 rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] px-3 py-1.5 text-[12.5px] font-medium text-[var(--c-text-2)] transition hover:text-[var(--c-text)]"
            >
              <ArrowsClockwise size={14} weight="bold" className={reindexing ? 'animate-spin' : ''} />
              <span>重建索引</span>
            </button>

            {/* 3-mode Switch */}
            <div className="flex items-center gap-0.5 rounded-[10px] border border-[var(--c-border)] bg-[var(--c-surface)] p-1">
              <button
                type="button"
                data-cursor="block"
                onClick={() => setMode('mindmap')}
                className={`inline-flex items-center gap-1.5 rounded-[7px] px-2.5 py-1 text-[12.5px] font-medium transition ${
                  mode === 'mindmap'
                    ? 'bg-[var(--c-accent)] text-[var(--c-on-accent)]'
                    : 'text-[var(--c-text-2)] hover:text-[var(--c-text)]'
                }`}
              >
                <Graph size={14} weight="duotone" />
                <span>思维导图</span>
              </button>
              <button
                type="button"
                data-cursor="block"
                onClick={() => setMode('chain')}
                className={`inline-flex items-center gap-1.5 rounded-[7px] px-2.5 py-1 text-[12.5px] font-medium transition ${
                  mode === 'chain'
                    ? 'bg-[var(--c-accent)] text-[var(--c-on-accent)]'
                    : 'text-[var(--c-text-2)] hover:text-[var(--c-text)]'
                }`}
              >
                <GitBranch size={14} weight="duotone" />
                <span>思维链</span>
              </button>
              <button
                type="button"
                data-cursor="block"
                onClick={() => setMode('list')}
                className={`inline-flex items-center gap-1.5 rounded-[7px] px-2.5 py-1 text-[12.5px] font-medium transition ${
                  mode === 'list'
                    ? 'bg-[var(--c-accent)] text-[var(--c-on-accent)]'
                    : 'text-[var(--c-text-2)] hover:text-[var(--c-text)]'
                }`}
              >
                <ListBullets size={14} weight="duotone" />
                <span>清单</span>
              </button>
            </div>
          </div>
        </div>

        {/* Main Content + Optional Node Inspector */}
        {loading ? (
          <div className="flex h-72 items-center justify-center rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] text-[14px] text-[var(--c-text-2)]">
            正在加载记忆网络…
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
            <div className={selectedMemory ? 'lg:col-span-8' : 'lg:col-span-12'}>
              {mode === 'mindmap' && (
                <MemoryMindMap
                  personaName={personaName}
                  memories={memories}
                  selectedId={selectedMemory?.id || null}
                  onSelect={handleSelectMemory}
                />
              )}

              {mode === 'chain' && (
                <MemoryThoughtChain
                  summaries={summaries}
                  memories={memories}
                  selectedId={selectedMemory?.id || null}
                  onSelectMemory={handleSelectMemory}
                />
              )}

              {mode === 'list' && (
                <div className="space-y-2.5">
                  {semanticHits ? (
                    semanticHits.length === 0 ? (
                      <div className="rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] p-8 text-center text-[13.5px] text-[var(--c-text-2)]">
                        未检索到与「{query}」相关的记忆
                      </div>
                    ) : (
                      semanticHits.map((hit, i) => (
                        <div
                          key={`${hit.id || i}`}
                          className="rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] p-4"
                        >
                          <div className="flex items-center justify-between text-[12px] text-[var(--c-text-2)]">
                            <span>{hit.category || '检索匹配'}</span>
                            {typeof hit.score === 'number' && (
                              <span className="font-mono text-[var(--c-accent)]">
                                相关度 {(hit.score * 100).toFixed(0)}%
                              </span>
                            )}
                          </div>
                          <p className="mt-1.5 text-[14px] leading-relaxed text-[var(--c-text)]">
                            {hit.content}
                          </p>
                        </div>
                      ))
                    )
                  ) : memories.length === 0 ? (
                    <div className="rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] p-8 text-center text-[13.5px] text-[var(--c-text-2)]">
                      暂无记忆记录
                    </div>
                  ) : (
                    memories.map((m) => (
                      <button
                        key={m.id}
                        type="button"
                        data-cursor="block"
                        onClick={() => handleSelectMemory(m)}
                        className={`w-full rounded-[12px] border p-4 text-left transition ${
                          selectedMemory?.id === m.id
                            ? 'border-[var(--c-accent)] bg-[var(--c-accent-soft)]'
                            : 'border-[var(--c-border)] bg-[var(--c-surface)] hover:border-[var(--c-accent-border)]'
                        }`}
                      >
                        <div className="flex items-center justify-between text-[12px] text-[var(--c-text-2)]">
                          <span>
                            {m.category || '日常'} · 重要度 {m.level}
                          </span>
                          <span>{friendlyTime(m.created_at)}</span>
                        </div>
                        <p className="mt-1.5 text-[14px] leading-relaxed text-[var(--c-text)]">
                          {m.content}
                        </p>
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>

            {/* Selected Node Inspector */}
            {selectedMemory && (
              <aside className="liquid-glass-strong overflow-hidden rounded-[12px] lg:col-span-4">
                <div
                  className="flex items-center justify-between border-b border-[var(--c-border)] px-4 py-3"
                  style={{ backgroundColor: 'var(--c-tone-violet-soft)' }}
                >
                  <span className="text-[13.5px] font-semibold text-[var(--c-text)]">
                    记忆节点详情
                  </span>
                  <button
                    type="button"
                    data-cursor="block"
                    onClick={() => setSelectedMemory(null)}
                    className="rounded-[6px] p-1 text-[var(--c-text-2)] hover:bg-[var(--c-surface-2)] hover:text-[var(--c-text)]"
                  >
                    <X size={15} weight="bold" />
                  </button>
                </div>

                <div className="p-4">
                  <p className="text-[14px] leading-relaxed text-[var(--c-text)]">
                    {selectedMemory.content}
                  </p>

                  <div className="mt-4 grid grid-cols-2 gap-2 rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] p-3 text-[12px]">
                    <div>
                      <div className="text-[var(--c-text-3)]">分类</div>
                      <div className="mt-0.5 font-medium text-[var(--c-text)]">
                        {selectedMemory.category || '未分类'}
                      </div>
                    </div>
                    <div>
                      <div className="text-[var(--c-text-3)]">重要度</div>
                      <div className="mt-0.5 font-medium" style={{ color: 'var(--c-tone-violet)' }}>
                        Level {selectedMemory.level}
                      </div>
                    </div>
                    <div>
                      <div className="text-[var(--c-text-3)]">置信度</div>
                      <div className="mt-0.5 font-mono text-[var(--c-text)]">
                        {Math.round((selectedMemory.confidence || 0) * 100)}%
                      </div>
                    </div>
                    <div>
                      <div className="text-[var(--c-text-3)]">访问次数</div>
                      <div className="mt-0.5 font-mono text-[var(--c-text)]">
                        {detail?.access_count ?? '—'}
                      </div>
                    </div>
                  </div>

                  {selectedMemory.tags?.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {selectedMemory.tags.map((t) => (
                        <span
                          key={t}
                          className="rounded-[6px] border border-[var(--c-border)] bg-[var(--c-surface)] px-2 py-0.5 text-[11.5px] text-[var(--c-text-2)]"
                        >
                          #{t}
                        </span>
                      ))}
                    </div>
                  )}

                  <button
                    type="button"
                    data-cursor="block"
                    onClick={() => handleDelete(selectedMemory)}
                    className="mt-5 flex w-full items-center justify-center gap-1.5 rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)] py-2 text-[13px] font-medium text-[var(--c-error)] transition hover:bg-[var(--c-surface-2)]"
                  >
                    <Trash size={14} weight="duotone" />
                    <span>删除此记忆</span>
                  </button>
                </div>
              </aside>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
