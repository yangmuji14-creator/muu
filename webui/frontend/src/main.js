import { mount } from 'svelte';
import './styles/tokens.css';
import './styles/theme-liquid.css';

import App from './App.svelte';

// 主题初始化：默认浅色，读 localStorage `cc-theme`（light / dark / system）
// 'system' 只是偏好值，落到 <html> 上的必须是解析后的 light/dark，
// 否则 CSS 的 [data-theme='dark'] 永远匹配不到。
const themeMode = (() => {
  try {
    const saved = localStorage.getItem('cc-theme');
    // 没选过就跟随系统 —— 设置页的默认选中项也是「跟随系统」，
    // 两处必须一致，否则用户看到的是「已选中系统」但页面其实是浅色。
    return saved === 'dark' || saved === 'light' || saved === 'system' ? saved : 'system';
  } catch {
    return 'light';
  }
})();

const systemDark = window.matchMedia('(prefers-color-scheme: dark)');

function resolveTheme(mode) {
  if (mode !== 'system') return mode;
  return systemDark.matches ? 'dark' : 'light';
}

document.documentElement.setAttribute('data-theme', resolveTheme(themeMode));

// 「跟随系统」时，系统主题切换要实时生效（设置页的预览也监听同一个事件）
systemDark.addEventListener('change', () => {
  let mode = 'system';
  try {
    mode = localStorage.getItem('cc-theme') || 'system';
  } catch {
    /* 隐私模式下读不到，按默认的「跟随系统」处理 */
  }
  if (mode === 'system') {
    document.documentElement.setAttribute('data-theme', resolveTheme('system'));
  }
});

// 强调色初始化（cc-accent）: amber / blue / teal / rose / violet / slate
const ACCENTS = ['amber', 'blue', 'teal', 'rose', 'violet', 'slate'];
const accent = (() => {
  try {
    const saved = localStorage.getItem('cc-accent');
    return ACCENTS.includes(saved) ? saved : 'amber';
  } catch {
    return 'amber';
  }
})();
document.documentElement.setAttribute('data-accent', accent);

const app = mount(App, {
  target: document.getElementById('app'),
});

export default app;
