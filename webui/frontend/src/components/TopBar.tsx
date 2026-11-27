import { motion } from 'motion/react';
import {
  ChatTeardropDots,
  Feather,
  GearSix,
  Graph,
  MoonStars,
  NotePencil,
  SidebarSimple,
  SunDim,
  SunHorizon,
  UserCircle,
} from '@phosphor-icons/react';
import { NavTab, useApp } from '../store/AppContext';

const NAV_ITEMS: Array<{
  key: NavTab;
  label: string;
  icon: typeof ChatTeardropDots;
  tone: string;
}> = [
  { key: 'chat', label: '对话', icon: ChatTeardropDots, tone: 'var(--c-tone-blue)' },
  { key: 'today', label: '今日', icon: SunHorizon, tone: 'var(--c-tone-amber)' },
  { key: 'memory', label: '记忆', icon: Graph, tone: 'var(--c-tone-violet)' },
  { key: 'discover', label: '动态', icon: Feather, tone: 'var(--c-tone-teal)' },
  { key: 'personas', label: '角色', icon: UserCircle, tone: 'var(--c-tone-rose)' },
];

export function TopBar() {
  const {
    route,
    navigate,
    theme,
    toggleTheme,
    companionState,
    setHistoryDrawerOpen,
    setStateDrawerOpen,
    startNewConversation,
    openSettings,
  } = useApp();

  const personaName = companionState?.persona_name || '慕';
  const moodLabel = companionState?.mood?.label || '平静';

  return (
    <header className="liquid-glass-bar fixed inset-x-0 top-0 z-30 flex h-12 items-center justify-between gap-3 px-3 md:px-5">
      {/* Left: History Drawer + Quick New Chat + Minimal Companion Entry */}
      <div className="flex items-center gap-1">
        <button
          type="button"
          data-cursor="block"
          onClick={() => setHistoryDrawerOpen(true)}
          title="会话列表"
          aria-label="打开会话列表"
          className="glass-gleam relative flex h-8 w-8 items-center justify-center rounded-[8px] text-[var(--c-text-2)] transition hover:bg-[var(--c-surface-2)] hover:text-[var(--c-text)]"
        >
          <SidebarSimple size={17} weight="duotone" />
        </button>

        <button
          type="button"
          data-cursor="block"
          onClick={async () => {
            await startNewConversation();
            if (route !== 'chat') navigate('chat');
          }}
          title="新建对话"
          aria-label="新建对话"
          className="glass-gleam relative flex h-8 w-8 items-center justify-center rounded-[8px] text-[var(--c-text-2)] transition hover:bg-[var(--c-surface-2)] hover:text-[var(--c-text)]"
        >
          <NotePencil size={17} weight="duotone" />
        </button>

        <div className="mx-1 hidden h-4 w-px bg-[var(--c-border)] sm:block" />

        <button
          type="button"
          data-cursor="block"
          data-cursor-wide="1"
          onClick={() => setStateDrawerOpen(true)}
          title={`${personaName} · 当前心境：${moodLabel}（点击查看此刻状态）`}
          aria-label="查看伴侣状态"
          className="hidden h-8 items-center gap-2 rounded-[8px] px-2.5 text-[13px] font-medium text-[var(--c-text)] transition hover:bg-[var(--c-surface-2)]/80 sm:flex"
        >
          <span
            className="h-2 w-2 rounded-full"
            style={{
              background: 'linear-gradient(135deg, var(--c-tone-blue), var(--c-tone-violet))',
            }}
          />
          <span>{personaName}</span>
        </button>
      </div>

      {/* Center: Compact Segmented Navigation with Semantic Duotone Icons */}
      <nav
        aria-label="主导航"
        className="flex items-center gap-0.5 rounded-[10px] border border-[var(--c-border)] bg-[var(--c-surface-2)]/75 p-1"
      >
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = route === item.key;
          return (
            <button
              key={item.key}
              type="button"
              data-cursor="block"
              data-cursor-wide="1"
              onClick={() => navigate(item.key)}
              className={`relative flex h-7 items-center gap-1.5 rounded-[7px] px-3 text-[12.5px] transition-colors ${
                active
                  ? 'font-semibold text-[var(--c-text)]'
                  : 'font-medium text-[var(--c-text-2)] hover:text-[var(--c-text)]'
              }`}
            >
              {active && (
                <motion.span
                  layoutId="nav-pill-active"
                  transition={{ type: 'spring', stiffness: 420, damping: 32 }}
                  className="absolute inset-0 rounded-[7px] bg-[var(--c-surface)] shadow-2xs ring-1 ring-[var(--c-border)]"
                />
              )}
              <Icon
                size={15}
                weight="duotone"
                style={{ color: item.tone, opacity: active ? 1 : 0.72 }}
                className="relative z-10 transition-opacity"
              />
              <span className="relative z-10 hidden sm:inline">{item.label}</span>
            </button>
          );
        })}
      </nav>

      {/* Right: Clean Theme Toggle + Settings */}
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          data-cursor="block"
          onClick={toggleTheme}
          title={theme === 'light' ? '切换深色冷曜' : '切换浅色冷霜'}
          aria-label="切换主题"
          className="glass-gleam relative flex h-8 w-8 items-center justify-center rounded-[8px] text-[var(--c-text-2)] transition hover:bg-[var(--c-surface-2)] hover:text-[var(--c-text)]"
        >
          {theme === 'light' ? (
            <MoonStars size={17} weight="duotone" style={{ color: 'var(--c-tone-violet)' }} />
          ) : (
            <SunDim size={17} weight="duotone" style={{ color: 'var(--c-tone-amber)' }} />
          )}
        </button>

        <button
          type="button"
          data-cursor="block"
          data-cursor-wide="1"
          onClick={() => openSettings('model')}
          title="设置 (Ctrl+,)"
          aria-label="打开设置"
          className="glass-gleam relative flex h-8 items-center gap-1.5 rounded-[8px] border border-[var(--c-border)] bg-[var(--c-surface)]/80 px-2.5 text-[12.5px] font-medium text-[var(--c-text-2)] transition hover:border-[var(--c-border-strong)] hover:text-[var(--c-text)]"
        >
          <GearSix size={16} weight="duotone" />
          <span className="hidden lg:inline">设置</span>
        </button>
      </div>
    </header>
  );
}
