<script>
  // SettingsPage.svelte — 设置中心
  //
  // 两种形态:
  //   桌面端 (inline): 分类列表在左侧边栏 (SettingsNav), 这里只渲染当前子页, 无返回箭头。
  //   窄屏:            走「索引页 (SettingsIndex) → 子页 + 返回」的老流程。
  //
  // 子页组件在 src/components/settings/, 通过 props 接收 { notify, onback }。
  // route: 让 #/settings/<sub> 直接打开对应子页。
  import { navigate, route } from '../lib/router.js';
  import Toast from '../components/Toast.svelte';
  import SettingsIndex from '../components/settings/SettingsIndex.svelte';
  import SettingsModel from '../components/settings/SettingsModel.svelte';
  import SettingsConversation from '../components/settings/SettingsConversation.svelte';
  import SettingsWechat from '../components/settings/SettingsWechat.svelte';
  import SettingsMcp from '../components/settings/SettingsMcp.svelte';
  import SettingsPlugins from '../components/settings/SettingsPlugins.svelte';
  import SettingsMoments from '../components/settings/SettingsMoments.svelte';
  import SettingsVoice from '../components/settings/SettingsVoice.svelte';
  import SettingsData from '../components/settings/SettingsData.svelte';
  import SettingsMonitor from '../components/settings/SettingsMonitor.svelte';
  import SettingsAppearance from '../components/settings/SettingsAppearance.svelte';
  import { settingsNav, SETTINGS_KEYS } from '../lib/settingsNav.svelte.js';

  const SUB = {
    model: SettingsModel,
    conversation: SettingsConversation,
    wechat: SettingsWechat,
    mcp: SettingsMcp,
    plugins: SettingsPlugins,
    moments: SettingsMoments,
    voice: SettingsVoice,
    data: SettingsData,
    monitor: SettingsMonitor,
    appearance: SettingsAppearance,
  };

  // 桌面端: 分类已在侧栏, 子页内联渲染
  $effect(() => {
    const mq = window.matchMedia('(min-width: 768px)');
    const apply = () => (settingsNav.inline = mq.matches);
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  });

  // ---- toast (统一反馈) ----
  let toast = $state(null);
  let toastTimer = null;
  function notify(msg, kind = 'info') {
    toast = { type: kind, text: msg };
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast = null), 3200);
  }

  $effect(() => () => clearTimeout(toastTimer));

  const current = $derived($route.sub[0]);
  const Active = $derived(
    Object.hasOwn(SUB, current) ? SUB[current] : settingsNav.inline ? SUB[SETTINGS_KEYS[0]] : null,
  );
</script>

{#if Active}
  <Active notify={notify} onback={() => navigate('settings')} />
{:else}
  <SettingsIndex onopen={(key) => navigate(`settings/${key}`)} />
{/if}

<Toast {toast} />
