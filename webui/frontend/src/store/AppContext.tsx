import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import {
  ConversationBinding,
  createConversation,
  listConversations,
} from '../api/chat';
import { PersonaSummary, personasApi } from '../api/personas';
import { ModelResponse, modelApi } from '../api/settings';
import { CompanionState, fetchState } from '../api/state';

export type NavTab = 'chat' | 'today' | 'memory' | 'discover' | 'personas';
export type SettingsTabKey = 'model' | 'params' | 'appearance' | 'voice' | 'integrations' | 'system';
export type ThemeMode = 'light' | 'dark';

export interface ToastMessage {
  id: number;
  text: string;
  type: 'info' | 'success' | 'error';
}

export interface ConfirmRequest {
  title: string;
  message: string;
  confirmText?: string;
  danger?: boolean;
  resolve: (ok: boolean) => void;
}

interface AppContextValue {
  route: NavTab;
  navigate: (tab: NavTab) => void;
  theme: ThemeMode;
  setTheme: (theme: ThemeMode) => void;
  toggleTheme: () => void;
  cursorEnabled: boolean;
  setCursorEnabled: (v: boolean) => void;
  welcomeGridEnabled: boolean;
  setWelcomeGridEnabled: (v: boolean) => void;

  conversations: ConversationBinding[];
  activeConversationId: string | null;
  activeConversation: ConversationBinding | null;
  setActiveConversationId: (id: string | null) => void;
  reloadConversations: () => Promise<ConversationBinding[]>;
  startNewConversation: (personaId?: string) => Promise<ConversationBinding | null>;

  personas: PersonaSummary[];
  reloadPersonas: () => Promise<void>;

  companionState: CompanionState | null;
  stateRevision: number;
  bumpState: () => void;

  modelSummary: ModelResponse | null;
  reloadModels: () => Promise<void>;

  historyDrawerOpen: boolean;
  setHistoryDrawerOpen: (v: boolean) => void;
  stateDrawerOpen: boolean;
  setStateDrawerOpen: (v: boolean) => void;
  settingsOpen: boolean;
  settingsTab: SettingsTabKey;
  openSettings: (tab?: SettingsTabKey) => void;
  closeSettings: () => void;

  toast: ToastMessage | null;
  notify: (text: string, type?: 'info' | 'success' | 'error') => void;

  confirmRequest: ConfirmRequest | null;
  confirm: (message: string, opts?: { title?: string; confirmText?: string; danger?: boolean }) => Promise<boolean>;
  resolveConfirm: (ok: boolean) => void;
}

const AppContext = createContext<AppContextValue | null>(null);

const VALID_TABS: NavTab[] = ['chat', 'today', 'memory', 'discover', 'personas'];

function parseHashTab(): NavTab {
  const raw = window.location.hash.replace(/^#\/?/, '').split('/')[0];
  if (VALID_TABS.includes(raw as NavTab)) return raw as NavTab;
  return 'chat';
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [route, setRoute] = useState<NavTab>(() => parseHashTab());

  const [theme, setThemeState] = useState<ThemeMode>(() => {
    try {
      return localStorage.getItem('cc-theme') === 'dark' ? 'dark' : 'light';
    } catch {
      return 'light';
    }
  });

  const [cursorEnabled, setCursorState] = useState<boolean>(() => {
    try {
      return localStorage.getItem('cc-cursor') !== 'off';
    } catch {
      return true;
    }
  });

  const [welcomeGridEnabled, setWelcomeGridState] = useState<boolean>(() => {
    try {
      return localStorage.getItem('cc-welcome-grid') !== 'off';
    } catch {
      return true;
    }
  });

  const [conversations, setConversations] = useState<ConversationBinding[]>([]);
  const [activeConversationId, setActiveConvState] = useState<string | null>(null);
  const [conversationsLoaded, setConversationsLoaded] = useState(false);
  const [personas, setPersonas] = useState<PersonaSummary[]>([]);
  const [companionState, setCompanionState] = useState<CompanionState | null>(null);
  const [stateRevision, setStateRevision] = useState(0);
  const [modelSummary, setModelSummary] = useState<ModelResponse | null>(null);

  const [historyDrawerOpen, setHistoryDrawerOpen] = useState(false);
  const [stateDrawerOpen, setStateDrawerOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<SettingsTabKey>('model');

  const [toast, setToast] = useState<ToastMessage | null>(null);
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);

  const notify = useCallback((text: string, type: 'info' | 'success' | 'error' = 'info') => {
    const id = Date.now();
    setToast({ id, text, type });
    window.setTimeout(() => {
      setToast((prev) => (prev?.id === id ? null : prev));
    }, 2800);
  }, []);

  const confirm = useCallback(
    (
      message: string,
      opts?: { title?: string; confirmText?: string; danger?: boolean },
    ) => {
      return new Promise<boolean>((resolve) => {
        setConfirmRequest({
          title: opts?.title || '请确认',
          message,
          confirmText: opts?.confirmText || '确认',
          danger: opts?.danger,
          resolve,
        });
      });
    },
    [],
  );

  const resolveConfirm = useCallback(
    (ok: boolean) => {
      setConfirmRequest((curr) => {
        curr?.resolve(ok);
        return null;
      });
    },
    [],
  );

  const navigate = useCallback((tab: NavTab) => {
    setRoute(tab);
    window.location.hash = `/${tab}`;
  }, []);

  useEffect(() => {
    const onHash = () => setRoute(parseHashTab());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const setTheme = useCallback((next: ThemeMode) => {
    setThemeState(next);
    document.documentElement.setAttribute('data-theme', next);
    try {
      localStorage.setItem('cc-theme', next);
    } catch {
      /* ignore */
    }
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(theme === 'light' ? 'dark' : 'light');
  }, [theme, setTheme]);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  const setCursorEnabled = useCallback((v: boolean) => {
    setCursorState(v);
    try {
      localStorage.setItem('cc-cursor', v ? 'on' : 'off');
    } catch {
      /* ignore */
    }
  }, []);

  const setWelcomeGridEnabled = useCallback((v: boolean) => {
    setWelcomeGridState(v);
    try {
      localStorage.setItem('cc-welcome-grid', v ? 'on' : 'off');
    } catch {
      /* ignore */
    }
  }, []);

  const setActiveConversationId = useCallback((id: string | null) => {
    setActiveConvState(id);
    try {
      if (id) localStorage.setItem('cc-active-conv', id);
      else localStorage.removeItem('cc-active-conv');
    } catch {
      /* ignore */
    }
  }, []);

  const reloadConversations = useCallback(async () => {
    try {
      const list = await listConversations();
      const webFirst = list.filter((c) => c.platform === 'web' || !c.platform);
      setConversations(list);
      setActiveConvState((curr) => {
        let saved: string | null = null;
        try {
          saved = localStorage.getItem('cc-active-conv');
        } catch {
          /* ignore */
        }
        const candidate = curr || saved;
        if (candidate && list.some((c) => c.conversation_id === candidate)) {
          return candidate;
        }
        const pick = webFirst[0]?.conversation_id || list[0]?.conversation_id || null;
        try {
          if (pick) localStorage.setItem('cc-active-conv', pick);
          else localStorage.removeItem('cc-active-conv');
        } catch {
          /* ignore */
        }
        return pick;
      });
      setConversationsLoaded(true);
      return list;
    } catch {
      setConversationsLoaded(true);
      return [];
    }
  }, []);

  const reloadPersonas = useCallback(async () => {
    const r = await personasApi.list();
    if (r.ok && Array.isArray(r.data)) setPersonas(r.data);
  }, []);

  const reloadModels = useCallback(async () => {
    const r = await modelApi.get();
    if (r.ok && r.data) setModelSummary(r.data);
  }, []);

  const startNewConversation = useCallback(
    async (personaId?: string) => {
      try {
        const pid = personaId || personas[0]?.id || 'girlfriend_001';
        const created = await createConversation(pid, 'web');
        await reloadConversations();
        setActiveConversationId(created.conversation_id);
        return created;
      } catch (err) {
        notify(err instanceof Error ? err.message : '新建会话失败', 'error');
        return null;
      }
    },
    [personas, reloadConversations, setActiveConversationId, notify],
  );

  const bumpState = useCallback(() => setStateRevision((n) => n + 1), []);

  useEffect(() => {
    reloadConversations();
    reloadPersonas();
    reloadModels();
  }, [reloadConversations, reloadPersonas, reloadModels]);

  useEffect(() => {
    if (!conversationsLoaded) return;
    let alive = true;
    fetchState(activeConversationId)
      .then((d) => {
        if (alive) setCompanionState(d);
      })
      .catch(() => {
        if (alive) setCompanionState(null);
      });
    return () => {
      alive = false;
    };
  }, [activeConversationId, stateRevision, conversationsLoaded]);

  const openSettings = useCallback((tab: SettingsTabKey = 'model') => {
    setSettingsTab(tab);
    setSettingsOpen(true);
  }, []);

  const closeSettings = useCallback(() => {
    setSettingsOpen(false);
    reloadModels();
    reloadPersonas();
    bumpState();
  }, [reloadModels, reloadPersonas, bumpState]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === ',') {
        e.preventDefault();
        setSettingsOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const activeConversation = useMemo(
    () => conversations.find((c) => c.conversation_id === activeConversationId) || null,
    [conversations, activeConversationId],
  );

  const value: AppContextValue = {
    route,
    navigate,
    theme,
    setTheme,
    toggleTheme,
    cursorEnabled,
    setCursorEnabled,
    welcomeGridEnabled,
    setWelcomeGridEnabled,
    conversations,
    activeConversationId,
    activeConversation,
    setActiveConversationId,
    reloadConversations,
    startNewConversation,
    personas,
    reloadPersonas,
    companionState,
    stateRevision,
    bumpState,
    modelSummary,
    reloadModels,
    historyDrawerOpen,
    setHistoryDrawerOpen,
    stateDrawerOpen,
    setStateDrawerOpen,
    settingsOpen,
    settingsTab,
    openSettings,
    closeSettings,
    toast,
    notify,
    confirmRequest,
    confirm,
    resolveConfirm,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used inside AppProvider');
  return ctx;
}
