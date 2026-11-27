import * as Switch from '@radix-ui/react-switch';
import { CursorClick, MoonStars, SunDim, Wind } from '@phosphor-icons/react';
import { useApp } from '../../store/AppContext';

export function AppearanceSettingsTab() {
  const {
    theme,
    setTheme,
    cursorEnabled,
    setCursorEnabled,
    welcomeGridEnabled,
    setWelcomeGridEnabled,
  } = useApp();

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-[15px] font-semibold text-[var(--c-text)]">外观与桌面交互</h3>
        <p className="mt-0.5 text-[12.5px] text-[var(--c-text-2)]">
          默认使用清透冷霜浅色主题；可随时切换深色冷曜，或开关自适应指针与欢迎页多彩微粒拖尾。
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <button
          type="button"
          data-cursor="block"
          onClick={() => setTheme('light')}
          className={`flex items-center justify-between rounded-[12px] border p-4 text-left transition ${
            theme === 'light'
              ? 'border-[var(--c-accent)] bg-[var(--c-accent-soft)]'
              : 'border-[var(--c-border)] bg-[var(--c-surface)]'
          }`}
        >
          <div>
            <div className="text-[14px] font-semibold text-[var(--c-text)]">浅色 · 冷霜 (默认)</div>
            <div className="mt-0.5 text-[12px] text-[var(--c-text-2)]">
              极净冷灰白基底 · 冰川钢蓝点缀
            </div>
          </div>
          <SunDim size={22} weight="duotone" style={{ color: 'var(--c-tone-amber)' }} />
        </button>

        <button
          type="button"
          data-cursor="block"
          onClick={() => setTheme('dark')}
          className={`flex items-center justify-between rounded-[12px] border p-4 text-left transition ${
            theme === 'dark'
              ? 'border-[var(--c-accent)] bg-[var(--c-accent-soft)]'
              : 'border-[var(--c-border)] bg-[var(--c-surface)]'
          }`}
        >
          <div>
            <div className="text-[14px] font-semibold text-[var(--c-text)]">深色 · 冷曜</div>
            <div className="mt-0.5 text-[12px] text-[var(--c-text-2)]">
              冷石墨深底 · 冰湖蓝通透光感
            </div>
          </div>
          <MoonStars size={22} weight="duotone" style={{ color: 'var(--c-tone-violet)' }} />
        </button>
      </div>

      <div className="overflow-hidden rounded-[12px] border border-[var(--c-border)] bg-[var(--c-surface)] shadow-2xs">
        <div
          className="flex items-center gap-2 border-b border-[var(--c-border)] px-4 py-2.5 text-[13px] font-semibold text-[var(--c-text)]"
          style={{ backgroundColor: 'var(--c-tone-rose-soft)' }}
        >
          <span className="h-3.5 w-[3px] rounded-full" style={{ backgroundColor: 'var(--c-tone-rose)' }} />
          <span>交互动效与指针</span>
        </div>

        <div className="space-y-2.5 p-3.5">
          <div className="flex items-center justify-between gap-4 rounded-[9px] border border-[var(--c-border)]/75 bg-[var(--c-bg)]/60 px-3.5 py-2.5">
            <div className="flex items-start gap-2.5">
              <CursorClick size={18} weight="duotone" style={{ color: 'var(--c-tone-blue)' }} className="mt-0.5 shrink-0" />
              <div>
                <div className="text-[13.5px] font-medium text-[var(--c-text)]">
                  自适应磁吸指针
                </div>
                <div className="mt-0.5 text-[12px] text-[var(--c-text-2)]">
                  悬停控件时留出宽松呼吸边距进行吸附高亮，进入输入区自动还原原生光标
                </div>
              </div>
            </div>
            <Switch.Root
              checked={cursorEnabled}
              onCheckedChange={setCursorEnabled}
              className="relative h-5 w-9 shrink-0 cursor-pointer rounded-full bg-[var(--c-surface-3)] transition data-[state=checked]:bg-[var(--c-accent)]"
            >
              <Switch.Thumb className="block h-4 w-4 translate-x-0.5 rounded-full bg-white shadow-2xs transition-transform data-[state=checked]:translate-x-[18px]" />
            </Switch.Root>
          </div>

          <div className="flex items-center justify-between gap-4 rounded-[9px] border border-[var(--c-border)]/75 bg-[var(--c-bg)]/60 px-3.5 py-2.5">
            <div className="flex items-start gap-2.5">
              <Wind size={18} weight="duotone" style={{ color: 'var(--c-tone-teal)' }} className="mt-0.5 shrink-0" />
              <div>
                <div className="text-[13.5px] font-medium text-[var(--c-text)]">
                  初始页多彩微粒与指针拖尾
                </div>
                <div className="mt-0.5 text-[12px] text-[var(--c-text-2)]">
                  在欢迎页呈现多彩失重微粒与流畅指针拖尾，移入控件自动避让
                </div>
              </div>
            </div>
            <Switch.Root
              checked={welcomeGridEnabled}
              onCheckedChange={setWelcomeGridEnabled}
              className="relative h-5 w-9 shrink-0 cursor-pointer rounded-full bg-[var(--c-surface-3)] transition data-[state=checked]:bg-[var(--c-accent)]"
            >
              <Switch.Thumb className="block h-4 w-4 translate-x-0.5 rounded-full bg-white shadow-2xs transition-transform data-[state=checked]:translate-x-[18px]" />
            </Switch.Root>
          </div>
        </div>
      </div>
    </div>
  );
}
