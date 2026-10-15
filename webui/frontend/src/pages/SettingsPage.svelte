<script>
  // SettingsPage.svelte — 设置中心
  //
  // 两种形态:
  //   桌面端 (inline): 分类列表在左侧边栏 (SettingsNav), 这里只渲染当前子页, 无返回箭头。
  //   窄屏:            走「索引页 (SettingsIndex) → 子页 + 返回」的老流程。
  //
  // 子页组件在 src/components/settings/, 通过 props 接收 { notify, onback }。
  // route: 让 #/settings/<sub> 直接打开对应子页。
  import { route } from '../lib/router.js';
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

  let current = $state(null);

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

  function open(key) {
    current = key;
  }
  function back() {
    current = null;
  }

  // 同步路由子路径 -> 当前子页。
  // 桌面端且无子路径时, 默认落到第一个分类, 不再显示索引页。
  $effect(() => {
    const key = Array.isArray($route.sub) && $route.sub.length > 0 ? $route.sub[0] : null;
    if (key && SUB[key]) {
      current = key;
    } else if (!key && settingsNav.inline && !current) {
      current = SETTINGS_KEYS[0];
    }
  });

  let Active = $derived(current && SUB[current] ? SUB[current] : null);
</script>

{#if settingsNav.inline}
  {#if Active}
    <Active notify={notify} onback={back} />
  {/if}
{:else if !current}
  <SettingsIndex onopen={open} />
{:else if Active}
  <Active notify={notify} onback={back} />
{/if}

<Toast {toast} />
