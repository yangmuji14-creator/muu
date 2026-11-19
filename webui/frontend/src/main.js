import { mount } from 'svelte';
import './styles/tokens.css';
import './styles/theme-liquid.css';

import App from './App.svelte';

// 主题初始化：默认浅色，读 localStorage `cc-theme`（light / dark）
const theme = (() => {
  try {
    const saved = localStorage.getItem('cc-theme');
    return saved === 'dark' || saved === 'light' ? saved : 'light';
  } catch {
    return 'light';
  }
})();
document.documentElement.setAttribute('data-theme', theme);

// 强调色初始化（cc-accent）: amber / blue / teal / rose / violet / slate
const accent = (() => {
  try {
    return localStorage.getItem('cc-accent') || 'amber';
  } catch {
    return 'amber';
  }
})();
document.documentElement.setAttribute('data-accent', accent);

const app = mount(App, {
  target: document.getElementById('app'),
});

export default app;
