// ============================================================
// lib/settingsNav.svelte.js — 设置分类导航
//
// 分类数据 + 「内联」标志。
// inline=true 时(桌面端), 分类列表渲染在左侧边栏, 子页不再显示返回箭头;
// inline=false 时(窄屏), 仍走「索引页 → 子页 + 返回」的老流程。
// ============================================================

export const SETTINGS_GROUPS = [
  {
    key: 'conn',
    title: '连接 / 服务',
    icon: 'link',
    desc: '模型、账号与外部能力接入',
    items: [
      { key: 'model', icon: 'cpu', title: '模型设置', desc: '切换模型与管理提供商' },
      { key: 'wechat', icon: 'wechat', title: '微信账号', desc: '账号绑定与扫码登录' },
      { key: 'mcp', icon: 'plug', title: 'MCP 扩展', desc: '外部能力服务器接入' },
      { key: 'voice', icon: 'voice', title: '语音服务商', desc: 'TTS 合成与试听' },
      { key: 'plugins', icon: 'puzzle', title: '插件 / 工具', desc: '已装能力概览（只读）' },
    ],
  },
  {
    key: 'behavior',
    title: '对话 / 行为',
    icon: 'message',
    desc: '回复风格与主动消息偏好',
    items: [
      { key: 'conversation', icon: 'message', title: '对话设置', desc: '回复风格、智能开关与主动消息' },
      { key: 'moments', icon: 'moments', title: '朋友圈自动发布', desc: '定时自动发朋友圈' },
    ],
  },
  {
    key: 'system',
    title: '系统',
    icon: 'monitor',
    desc: '数据、诊断与外观',
    items: [
      { key: 'data', icon: 'data', title: '数据与关于', desc: '诊断、备份与恢复' },
      { key: 'monitor', icon: 'monitor', title: '系统监控 / 日志', desc: '运行状态、诊断检查与运维指标' },
      { key: 'appearance', icon: 'palette', title: '主题与界面', desc: '主题与布局' },
    ],
  },
];

/** 全部合法子页 key (顺序即导航顺序) */
export const SETTINGS_KEYS = SETTINGS_GROUPS.flatMap((g) => g.items.map((i) => i.key));

/** 桌面端内联到侧栏时为 true */
export const settingsNav = $state({ inline: false });
