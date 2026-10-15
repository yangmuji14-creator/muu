// ============================================================
// lib/layout.svelte.js — 布局模式 (存 localStorage cc-layout)
//
// 三种模式:
//   panel     内心面板 — 对话 + 右侧状态面板
//   immersive 沉浸单栏 — 只有对话, 导航与状态收进抽屉
//   today     今天     — 打开先是今天的版面
// ============================================================

export const LAYOUT_KEY = 'cc-layout';

export const LAYOUTS = ['panel', 'immersive', 'today'];

export const LAYOUT_META = {
  panel: { label: '内心面板', desc: '对话 + 右侧状态面板' },
  immersive: { label: '沉浸单栏', desc: '只有对话，其余收进抽屉' },
  today: { label: '今天', desc: '打开先是今天的版面' },
};

function readMode() {
  try {
    const v = localStorage.getItem(LAYOUT_KEY);
    if (LAYOUTS.includes(v)) return v;
  } catch {
    /* ignore */
  }
  return 'panel';
}

export const layout = $state({ mode: readMode() });

export function setLayout(mode) {
  if (!LAYOUTS.includes(mode)) return;
  layout.mode = mode;
  try {
    localStorage.setItem(LAYOUT_KEY, mode);
  } catch {
    /* ignore */
  }
}
