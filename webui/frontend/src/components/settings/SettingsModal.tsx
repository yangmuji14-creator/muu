import * as Dialog from '@radix-ui/react-dialog';
import * as Tabs from '@radix-ui/react-tabs';
import { motion } from 'motion/react';
import {
  Faders,
  PlugsConnected,
  Pulse,
  PuzzlePiece,
  Swatches,
  Waveform,
  X,
} from '@phosphor-icons/react';
import { SettingsTabKey, useApp } from '../../store/AppContext';
import { AppearanceSettingsTab } from './AppearanceSettingsTab';
import { IntegrationsTab } from './IntegrationsTab';
import { ModelSettingsTab } from './ModelSettingsTab';
import { ParamsSettingsTab } from './ParamsSettingsTab';
import { SystemDataTab } from './SystemDataTab';
import { VoiceMomentsTab } from './VoiceMomentsTab';

const SETTINGS_TABS: Array<{
  key: SettingsTabKey;
  label: string;
  icon: typeof PlugsConnected;
  tone: string;
}> = [
  { key: 'model', label: '模型提供商', icon: PlugsConnected, tone: 'var(--c-tone-blue)' },
  { key: 'params', label: '对话参数', icon: Faders, tone: 'var(--c-tone-violet)' },
  { key: 'appearance', label: '外观与指针', icon: Swatches, tone: 'var(--c-tone-rose)' },
  { key: 'voice', label: '语音与动态', icon: Waveform, tone: 'var(--c-tone-teal)' },
  { key: 'integrations', label: '微信与扩展', icon: PuzzlePiece, tone: 'var(--c-tone-amber)' },
  { key: 'system', label: '监控与数据', icon: Pulse, tone: 'var(--c-tone-blue)' },
];

export function SettingsModal() {
  const { settingsOpen, settingsTab, openSettings, closeSettings } = useApp();

  return (
    <Dialog.Root
      open={settingsOpen}
      onOpenChange={(open) => {
        if (!open) closeSettings();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/35 backdrop-blur-xs" />

        <Dialog.Content className="liquid-glass-modal fixed left-1/2 top-1/2 z-50 flex h-[min(86vh,680px)] w-[min(94vw,860px)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-[14px] outline-none">
          <motion.div
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ type: 'spring', stiffness: 400, damping: 32 }}
            className="flex h-full flex-col"
          >
            {/* Header + Underline Tabs with wide hover breathing room */}
            <div className="border-b border-[var(--c-border)] bg-[var(--c-surface)]/80 px-6 pt-4">
              <div className="flex items-center justify-between pb-3">
                <Dialog.Title className="text-[15.5px] font-semibold tracking-tight text-[var(--c-text)]">
                  控制中心 · 设置
                </Dialog.Title>
                <Dialog.Description className="sr-only">
                  配置模型提供商、对话参数、外观指针、语音和扩展集成
                </Dialog.Description>
                <button
                  type="button"
                  data-cursor="block"
                  onClick={closeSettings}
                  aria-label="关闭设置"
                  className="flex h-7 w-7 items-center justify-center rounded-[8px] text-[var(--c-text-2)] transition hover:bg-[var(--c-surface-2)] hover:text-[var(--c-text)]"
                >
                  <X size={16} weight="bold" />
                </button>
              </div>

              <Tabs.Root
                value={settingsTab}
                onValueChange={(v) => openSettings(v as SettingsTabKey)}
              >
                <Tabs.List className="-mb-px flex gap-1.5 overflow-x-auto">
                  {SETTINGS_TABS.map((t) => {
                    const Icon = t.icon;
                    const active = settingsTab === t.key;
                    return (
                      <Tabs.Trigger
                        key={t.key}
                        value={t.key}
                        data-cursor="block"
                        data-cursor-wide="1"
                        style={
                          active
                            ? { borderBottomColor: t.tone, color: t.tone }
                            : undefined
                        }
                        className={`inline-flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-[13px] font-medium transition outline-none ${
                          active
                            ? 'font-semibold'
                            : 'border-transparent text-[var(--c-text-2)] hover:text-[var(--c-text)]'
                        }`}
                      >
                        <Icon
                          size={15}
                          weight="duotone"
                          style={{ color: t.tone, opacity: active ? 1 : 0.72 }}
                        />
                        <span>{t.label}</span>
                      </Tabs.Trigger>
                    );
                  })}
                </Tabs.List>
              </Tabs.Root>
            </div>

            {/* Layered Scrollable Body */}
            <div className="flex-1 overflow-y-auto bg-[var(--c-bg)]/85 p-6">
              {settingsTab === 'model' && <ModelSettingsTab />}
              {settingsTab === 'params' && <ParamsSettingsTab />}
              {settingsTab === 'appearance' && <AppearanceSettingsTab />}
              {settingsTab === 'voice' && <VoiceMomentsTab />}
              {settingsTab === 'integrations' && <IntegrationsTab />}
              {settingsTab === 'system' && <SystemDataTab />}
            </div>
          </motion.div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
