import { AdaptiveCursor } from './components/AdaptiveCursor';
import { ConfirmDialog } from './components/ConfirmDialog';
import { ConversationDrawer } from './components/ConversationDrawer';
import { StateDrawer } from './components/StateDrawer';
import { Toast } from './components/Toast';
import { TopBar } from './components/TopBar';
import { SettingsModal } from './components/settings/SettingsModal';
import { useApp } from './store/AppContext';
import { ChatView } from './views/ChatView';
import { DiscoverView } from './views/DiscoverView';
import { MemoryView } from './views/MemoryView';
import { PersonasView } from './views/PersonasView';
import { TodayView } from './views/TodayView';

export function App() {
  const { route } = useApp();

  return (
    <div className="relative h-full w-full overflow-hidden bg-[var(--c-bg)] text-[var(--c-text)]">
      <AdaptiveCursor />
      <TopBar />

      <main className="h-full w-full">
        <div className={route === 'chat' ? 'h-full w-full' : 'hidden'}>
          <ChatView />
        </div>
        {route === 'today' && <TodayView />}
        {route === 'memory' && <MemoryView />}
        {route === 'discover' && <DiscoverView />}
        {route === 'personas' && <PersonasView />}
      </main>

      <ConversationDrawer />
      <StateDrawer />
      <SettingsModal />
      <ConfirmDialog />
      <Toast />
    </div>
  );
}
