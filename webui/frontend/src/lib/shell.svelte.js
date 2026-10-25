// ============================================================
// lib/shell.svelte.js — 外壳与页面之间的少量共享状态
//
// 只放「外壳(chrome)与页面必须协作」的东西，不放业务数据。
// 目前一处：窄屏下聊天页自己想管顶栏（它有会话标题/新建/重命名），
// 而「她的状态」抽屉归外壳所有，于是用这个 store 把按钮留在页内、
// 面板实体留在外壳 —— 避免出现两条叠在一起的顶栏。
// ============================================================

export const shell = $state({
  // 外壳是否提供状态面板 (layout.mode === 'panel' 且有 panel snippet)
  panelAvailable: false,
  // 窄屏状态抽屉是否打开
  panelSheetOpen: false,
  // 会话页把自己的顶栏动作登记到这里，由外壳统一渲染 —— 一个页面一条顶栏。
  // { title, canRename, openList(), rename() }
  chatHead: null,
});

export function openPanelSheet() {
  if (!shell.panelAvailable) return;
  shell.panelSheetOpen = true;
}

export function closePanelSheet() {
  shell.panelSheetOpen = false;
}

export function togglePanelSheet() {
  if (shell.panelSheetOpen) closePanelSheet();
  else openPanelSheet();
}
