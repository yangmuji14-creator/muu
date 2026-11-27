import React, { useMemo, useState } from 'react';
import { ArrowsOutSimple, MagnifyingGlassMinus, MagnifyingGlassPlus } from '@phosphor-icons/react';
import { MemoryItem } from '../api/memory';

const CAT_TONES = [
  'var(--c-tone-blue)',
  'var(--c-tone-violet)',
  'var(--c-tone-teal)',
  'var(--c-tone-amber)',
  'var(--c-tone-rose)',
];

interface NodePoint {
  id: string;
  label: string;
  fullText: string;
  kind: 'root' | 'category' | 'memory';
  x: number;
  y: number;
  level?: number;
  category?: string;
  tone?: string;
  tags?: string[];
  memory?: MemoryItem;
}

interface EdgeItem {
  id: string;
  from: string;
  to: string;
  kind: 'tree' | 'cross';
  sharedTag?: string;
}

export function MemoryMindMap({
  personaName,
  memories,
  selectedId,
  onSelect,
}: {
  personaName: string;
  memories: MemoryItem[];
  selectedId: string | null;
  onSelect: (m: MemoryItem) => void;
}) {
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [dragging, setDragging] = useState(false);
  const [dragOrigin, setDragOrigin] = useState({ x: 0, y: 0 });
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const { nodes, edges, relatedMap } = useMemo(() => {
    const outNodes: NodePoint[] = [];
    const outEdges: EdgeItem[] = [];
    const adj = new Map<string, Set<string>>();

    const linkAdj = (a: string, b: string) => {
      if (!adj.has(a)) adj.set(a, new Set());
      if (!adj.has(b)) adj.set(b, new Set());
      adj.get(a)!.add(b);
      adj.get(b)!.add(a);
    };

    const cx = 480;
    const cy = 290;
    const rootId = '__root__';
    outNodes.push({
      id: rootId,
      label: `${personaName} · 记忆图谱`,
      fullText: `共 ${memories.length} 条长期记忆`,
      kind: 'root',
      x: cx,
      y: cy,
    });

    // Group memories by category
    const catMap = new Map<string, MemoryItem[]>();
    for (const m of memories) {
      const cat = m.category || '日常片段';
      if (!catMap.has(cat)) catMap.set(cat, []);
      catMap.get(cat)!.push(m);
    }

    const categories = Array.from(catMap.entries());
    const catCount = Math.max(1, categories.length);
    const catRadius = categories.length <= 2 ? 150 : 185;

    categories.forEach(([cat, items], cIdx) => {
      const catAngle = (cIdx / catCount) * Math.PI * 2 - Math.PI / 2;
      const catX = cx + Math.cos(catAngle) * catRadius;
      const catY = cy + Math.sin(catAngle) * catRadius;
      const catId = `cat:${cat}`;
      const catTone = CAT_TONES[cIdx % CAT_TONES.length];

      outNodes.push({
        id: catId,
        label: `${cat} (${items.length})`,
        fullText: cat,
        kind: 'category',
        x: catX,
        y: catY,
        category: cat,
        tone: catTone,
      });

      outEdges.push({ id: `e:${rootId}:${catId}`, from: rootId, to: catId, kind: 'tree' });
      linkAdj(rootId, catId);

      // Fan out up to 10 memories cleanly around category outward arc
      const visibleItems = items.slice(0, 10);
      const spread = Math.min(Math.PI * 0.95, Math.max(0.45, visibleItems.length * 0.24));
      visibleItems.forEach((m, mIdx) => {
        const offset =
          visibleItems.length === 1
            ? 0
            : ((mIdx / (visibleItems.length - 1)) - 0.5) * spread;
        const mAngle = catAngle + offset;
        const mDist = 138 + (mIdx % 2) * 34;
        const mx = catX + Math.cos(mAngle) * mDist;
        const my = catY + Math.sin(mAngle) * mDist;
        const short = m.content.length > 16 ? `${m.content.slice(0, 16)}…` : m.content;

        outNodes.push({
          id: m.id,
          label: short,
          fullText: m.content,
          kind: 'memory',
          x: mx,
          y: my,
          level: m.level,
          category: cat,
          tone: catTone,
          tags: Array.isArray(m.tags) ? m.tags : [],
          memory: m,
        });

        outEdges.push({ id: `e:${catId}:${m.id}`, from: catId, to: m.id, kind: 'tree' });
        linkAdj(catId, m.id);
      });
    });

    // Cross-links between memory nodes sharing tags
    const memNodes = outNodes.filter((n) => n.kind === 'memory');
    const seenCross = new Set<string>();
    for (let i = 0; i < memNodes.length; i++) {
      for (let j = i + 1; j < memNodes.length; j++) {
        const a = memNodes[i];
        const b = memNodes[j];
        const shared = (a.tags || []).find((t) => (b.tags || []).includes(t));
        if (shared) {
          const key = `${a.id}::${b.id}`;
          if (!seenCross.has(key)) {
            seenCross.add(key);
            outEdges.push({
              id: `x:${key}`,
              from: a.id,
              to: b.id,
              kind: 'cross',
              sharedTag: shared,
            });
            linkAdj(a.id, b.id);
          }
        }
      }
    }

    return { nodes: outNodes, edges: outEdges, relatedMap: adj };
  }, [personaName, memories]);

  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const focusId = hoveredId || selectedId;
  const focusNeighbors = focusId ? relatedMap.get(focusId) : undefined;

  if (memories.length === 0) {
    return (
      <div className="flex h-[460px] items-center justify-center rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] text-[14px] text-[var(--c-text-2)]">
        当前会话还没有形成长期记忆节点，聊几轮后这里会自动生长出记忆思维导图。
      </div>
    );
  }

  function handlePointerDown(e: React.PointerEvent<SVGSVGElement>) {
    if ((e.target as Element).closest('[data-node]')) return;
    setDragging(true);
    setDragOrigin({ x: e.clientX - pan.x, y: e.clientY - pan.y });
  }

  function handlePointerMove(e: React.PointerEvent<SVGSVGElement>) {
    if (!dragging) return;
    setPan({ x: e.clientX - dragOrigin.x, y: e.clientY - dragOrigin.y });
  }

  return (
    <div className="relative h-[540px] w-full overflow-hidden rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)]">
      {/* Subtle blueprint dot pattern */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-45"
        style={{
          backgroundImage: 'radial-gradient(var(--c-border-strong) 1px, transparent 1px)',
          backgroundSize: '22px 22px',
        }}
      />

      {/* Zoom Controls */}
      <div className="liquid-glass absolute bottom-3 right-3 z-10 flex items-center gap-0.5 rounded-[10px] p-1">
        <button
          type="button"
          data-cursor="block"
          onClick={() => setZoom((z) => Math.max(0.55, +(z - 0.15).toFixed(2)))}
          className="flex h-7 w-7 items-center justify-center rounded-[7px] text-[var(--c-text-2)] hover:bg-[var(--c-surface-2)] hover:text-[var(--c-text)]"
          title="缩小"
        >
          <MagnifyingGlassMinus size={14} weight="duotone" />
        </button>
        <span className="px-1.5 font-mono text-[11px] text-[var(--c-text-2)]">
          {Math.round(zoom * 100)}%
        </span>
        <button
          type="button"
          data-cursor="block"
          onClick={() => setZoom((z) => Math.min(1.85, +(z + 0.15).toFixed(2)))}
          className="flex h-7 w-7 items-center justify-center rounded-[7px] text-[var(--c-text-2)] hover:bg-[var(--c-surface-2)] hover:text-[var(--c-text)]"
          title="放大"
        >
          <MagnifyingGlassPlus size={14} weight="duotone" />
        </button>
        <button
          type="button"
          data-cursor="block"
          onClick={() => {
            setZoom(1);
            setPan({ x: 0, y: 0 });
          }}
          className="flex h-7 w-7 items-center justify-center rounded-[7px] text-[var(--c-text-2)] hover:bg-[var(--c-surface-2)] hover:text-[var(--c-text)]"
          title="重置视角"
        >
          <ArrowsOutSimple size={14} weight="duotone" />
        </button>
      </div>

      {/* Legend */}
      <div className="liquid-glass absolute left-3 top-3 z-10 rounded-[8px] px-3 py-1 text-[11.5px] text-[var(--c-text-2)]">
        拖拽空白处平移 · 悬停高亮关联 · 点击节点查看详情
      </div>

      <svg
        viewBox="0 0 960 580"
        className={`h-full w-full touch-none ${dragging ? 'cursor-grabbing' : 'cursor-grab'}`}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={() => setDragging(false)}
        onPointerLeave={() => setDragging(false)}
        onWheel={(e) => {
          e.preventDefault();
          const delta = e.deltaY < 0 ? 0.08 : -0.08;
          setZoom((z) => Math.min(1.85, Math.max(0.55, +(z + delta).toFixed(2))));
        }}
      >
        <g transform={`translate(${pan.x}, ${pan.y}) translate(480, 290) scale(${zoom}) translate(-480, -290)`}>
          {/* Edges */}
          {edges.map((edge) => {
            const a = nodeById.get(edge.from);
            const b = nodeById.get(edge.to);
            if (!a || !b) return null;
            const mx = (a.x + b.x) / 2;
            const my = (a.y + b.y) / 2;
            const ctrlX = edge.kind === 'cross' ? mx + (a.y - b.y) * 0.14 : mx;
            const ctrlY = edge.kind === 'cross' ? my + (b.x - a.x) * 0.14 : a.y * 0.35 + b.y * 0.65;
            const d = `M ${a.x} ${a.y} Q ${ctrlX} ${ctrlY} ${b.x} ${b.y}`;

            const highlighted =
              !focusId ||
              edge.from === focusId ||
              edge.to === focusId;

            return (
              <path
                key={edge.id}
                d={d}
                fill="none"
                stroke={
                  edge.kind === 'cross'
                    ? 'var(--c-accent)'
                    : 'var(--c-border-strong)'
                }
                strokeWidth={edge.kind === 'cross' ? 1.4 : 1.5}
                strokeDasharray={edge.kind === 'cross' ? '4 4' : undefined}
                opacity={highlighted ? (edge.kind === 'cross' ? 0.55 : 0.72) : 0.16}
                style={{ transition: 'opacity 180ms ease' }}
              />
            );
          })}

          {/* Nodes */}
          {nodes.map((node) => {
            const isHighlighted =
              !focusId || node.id === focusId || Boolean(focusNeighbors?.has(node.id));
            const isSelected = node.id === selectedId;

            if (node.kind === 'root') {
              return (
                <g key={node.id} transform={`translate(${node.x}, ${node.y})`}>
                  <rect
                    x={-76}
                    y={-22}
                    width={152}
                    height={44}
                    rx={9}
                    fill="var(--c-accent)"
                    className="shadow-sm"
                  />
                  <text
                    textAnchor="middle"
                    dominantBaseline="central"
                    fill="var(--c-on-accent)"
                    fontSize={13}
                    fontWeight={600}
                  >
                    {node.label}
                  </text>
                </g>
              );
            }

            if (node.kind === 'category') {
              const w = Math.max(88, node.label.length * 10 + 24);
              const catStroke = node.tone || 'var(--c-accent-border)';
              return (
                <g
                  key={node.id}
                  data-node="1"
                  transform={`translate(${node.x}, ${node.y})`}
                  opacity={isHighlighted ? 1 : 0.25}
                  onMouseEnter={() => setHoveredId(node.id)}
                  onMouseLeave={() => setHoveredId(null)}
                  style={{ transition: 'opacity 180ms ease', cursor: 'pointer' }}
                >
                  <rect
                    x={-w / 2}
                    y={-17}
                    width={w}
                    height={34}
                    rx={8}
                    fill="var(--c-surface-2)"
                    stroke={catStroke}
                    strokeWidth={1.3}
                  />
                  <text
                    textAnchor="middle"
                    dominantBaseline="central"
                    fill={catStroke}
                    fontSize={12}
                    fontWeight={600}
                  >
                    {node.label}
                  </text>
                </g>
              );
            }

            const w = Math.min(180, Math.max(106, node.label.length * 10.5 + 28));
            const memTone = node.tone || 'var(--c-accent)';
            return (
              <g
                key={node.id}
                data-node="1"
                transform={`translate(${node.x}, ${node.y})`}
                opacity={isHighlighted ? 1 : 0.24}
                onMouseEnter={() => setHoveredId(node.id)}
                onMouseLeave={() => setHoveredId(null)}
                onClick={() => node.memory && onSelect(node.memory)}
                style={{ transition: 'opacity 180ms ease', cursor: 'pointer' }}
              >
                <rect
                  x={-w / 2}
                  y={-16}
                  width={w}
                  height={32}
                  rx={7}
                  fill={isSelected ? 'var(--c-accent-soft)' : 'var(--c-surface)'}
                  stroke={isSelected ? memTone : 'var(--c-border-strong)'}
                  strokeWidth={isSelected ? 1.8 : 1}
                />
                <circle
                  cx={-w / 2 + 12}
                  cy={0}
                  r={3.5}
                  fill={(node.level || 1) >= 4 ? memTone : 'var(--c-text-3)'}
                />
                <text
                  x={8}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fill="var(--c-text)"
                  fontSize={11.5}
                  fontWeight={isSelected ? 600 : 500}
                >
                  {node.label}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
