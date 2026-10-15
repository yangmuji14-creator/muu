// ============================================================
// lib/router.js — 手写轻量 hash 路由 (零依赖)
//
// - 单个 writable store 存当前路由解析结果
// - hashchange 监听更新
// - 支持子级路径: #/settings/mcp -> { page:'settings', parts:['settings','mcp'] }
// - localStorage 记住上次 Tab (cc-page), 打开时恢复
//
// 路由形态:
//   #/chat        -> { path:'/chat', page:'chat', parts:['chat'] }
//   #/settings/mcp-> { path:'/settings/mcp', page:'settings', parts:['settings','mcp'] }
//   空 / #        -> fallback 到默认 page
//
// 默认 page 依布局模式而定:
//   layout_mode = today -> 'today' (今天版面作为落地页)
//   其它                -> 'chat'
// 「今天」页签只在 today 模式下出现在导航里。
// ============================================================

import { writable } from 'svelte/store';

// 顶层 Tab, 顺序即导航顺序
export const TABS = ['chat', 'contacts', 'discover', 'memory', 'settings'];

// 「今天」页签: 仅 today 模式启用
export const TODAY_TAB = 'today';

// 所有合法顶层页 (含今天)
const VALID_PAGES = [TODAY_TAB, ...TABS];

// Tab -> 显示文案
export const TAB_LABELS = {
  today: '今天',
  chat: '聊天',
  contacts: '通讯录',
  discover: '发现',
  memory: '记忆',
  settings: '设置',
};

const STORE_KEY = 'cc-page';
const LAYOUT_KEY = 'cc-layout';

/** 当前布局模式 (直接读 localStorage, 避免与 layout.svelte.js 循环依赖) */
function layoutMode() {
  try {
    return localStorage.getItem(LAYOUT_KEY) || 'panel';
  } catch {
    return 'panel';
  }
}

/** 该模式下的导航页签列表 */
export function navTabs(mode) {
  return mode === 'today' ? [TODAY_TAB, ...TABS] : TABS;
}

/** 该模式下的默认落地页 */
export function defaultPage(mode) {
  return mode === 'today' ? TODAY_TAB : 'chat';
}

function parseHash() {
  let raw = window.location.hash || '';
  if (raw.startsWith('#')) raw = raw.slice(1); // 去掉 '#'
  if (!raw.startsWith('/')) raw = '/' + raw;

  // 拆路径段, 过滤空段
  const parts = raw
    .split('/')
    .filter((p) => p.length > 0)
    .map((p) => decodeURIComponent(p));

  const top = parts[0] ?? '';
  const fallback = defaultPage(layoutMode());
  // 顶层必须是合法页, 否则回退默认
  const page = VALID_PAGES.includes(top) ? top : fallback;

  // 子段归一: 若顶层非法被回退, 丢弃整条非法路径, 保留默认页自身
  const segments = VALID_PAGES.includes(top) ? parts : [fallback];

  return {
    path: '/' + segments.join('/'),
    page, // 顶层 Tab
    parts: segments, // 完整路径段数组 (含子级)
    sub: segments.slice(1), // 子级路径段 (无子级则为 [])
  };
}

function readStoredPage() {
  try {
    const saved = localStorage.getItem(STORE_KEY);
    if (saved && VALID_PAGES.includes(saved)) return saved;
  } catch {
    /* ignore */
  }
  return null;
}

// 初始路由: 优先 hash, 否则本地记忆, 否则默认
function initialPath() {
  const hash = window.location.hash;
  if (hash && hash.length > 1) return hash;
  const stored = readStoredPage();
  if (stored) return `#/${stored}`;
  return `#/${defaultPage(layoutMode())}`;
}

// ---- 状态: 当前路由解析结果 ----
export const route = writable(parseHash());

// 底层原始 hash 更新函数, 供 navigate 使用
function updateFromHash() {
  if (window.location.hash && window.location.hash.length > 1) {
    route.set(parseHash());
  } else {
    // hash 被清空: 回退到记忆/默认, 并写回
    const stored = readStoredPage();
    const target = stored ?? defaultPage(layoutMode());
    window.location.hash = `/${target}`;
    route.set(parseHash());
  }
}

let started = false;

// 启动监听 (幂等)
export function startRouter() {
  if (started) return;
  started = true;

  // 首次进入: 若有记忆且当前无有效 hash, 写入
  if (window.location.hash.replace('#', '').length <= 1) {
    const stored = readStoredPage();
    if (stored) {
      window.location.hash = `/${stored}`;
    }
  }

  route.set(parseHash());
  window.addEventListener('hashchange', updateFromHash);
}

// 编程式导航: 跳到一个 Tab(或子路径)。例如 navigate('chat') / navigate('settings/mcp')
export function navigate(path) {
  let target = String(path || '').trim();
  if (target.startsWith('/')) {
    target = target.slice(1);
  }
  if (!VALID_PAGES.includes(target.split('/')[0])) {
    target = defaultPage(layoutMode());
  }
  // 记录顶层 Tab
  try {
    localStorage.setItem(STORE_KEY, target.split('/')[0]);
  } catch {
    /* ignore */
  }
  window.location.hash = `/${target}`;
}

// 顶层 Tab 切换 (不带子路径)
export function goTab(page) {
  navigate(page);
}
