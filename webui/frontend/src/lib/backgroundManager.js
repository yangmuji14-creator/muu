/**
 * backgroundManager.js — 背景图管理
 *
 * 写入的变量:
 *   --ambient-image  铺在 body::before (z-index:-1), 所有玻璃层会 blur 它
 *   --ambient-scrim  铺在 html::after, 控制「背景图透明度」
 *
 * 存储策略:
 *   本机 localStorage 配额通常只有 ~5MB，base64 会膨胀 ~33%。
 *   自定义图片因此限制在 3MB（≈4MB base64），并且持久化失败会抛错，
 *   由设置页展示给用户 —— 绝不静默吞掉 QuotaExceededError。
 */

const STORAGE_KEY = 'muu:background';
const MAX_SIZE = 3 * 1024 * 1024; // 3MB -> base64 后约 4MB，留出配额余量
const SAVE_DEBOUNCE_MS = 300;

/**
 * data URL -> Blob URL。
 *
 * 为什么不能把 data URL 直接写进 CSS 变量：Chrome 对单条 CSS 声明的长度
 * 有上限（实测 ~1.6MB，2MB 起 setProperty 静默失败——不抛错、也读不回来）。
 * 一张 2.8MB 的壁纸 base64 后是 3.7MB，写进 --ambient-image 会被浏览器
 * 整条丢掉，界面看起来就是「上传成功但背景没变」。
 *
 * Blob URL 只有几十个字符，图片本体留在内存里；刷新后由 localStorage
 * 里的 data URL 重新生成（Blob URL 本身不跨文档存活）。
 */
function dataUrlToObjectUrl(dataUrl) {
  try {
    // 必须是 data: URL。旧/损坏的 localStorage 里可能存着 http URL（含逗号），
    // 直接 slice(5, comma) 会把 "//host/a" 当成 header，编出一个坏 Blob URL，
    // 反而盖掉本来能用的 url("...") 兜底。
    if (typeof dataUrl !== 'string' || !dataUrl.startsWith('data:')) return null;
    const comma = dataUrl.indexOf(',');
    if (comma === -1) return null;
    const header = dataUrl.slice(5, comma); // 去掉 "data:"
    const isBase64 = /;base64/i.test(header);
    const mime = header.split(';')[0] || 'application/octet-stream';
    const payload = dataUrl.slice(comma + 1);
    let bytes;
    if (isBase64) {
      const binary = atob(payload);
      bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    } else {
      bytes = new TextEncoder().encode(decodeURIComponent(payload));
    }
    return URL.createObjectURL(new Blob([bytes], { type: mime }));
  } catch {
    return null;
  }
}

export const PRESETS = [
  {
    name: '暖阳',
    light:
      'radial-gradient(ellipse 50% 38% at 6% -6%, #ffd9ad, transparent 62%), radial-gradient(ellipse 44% 34% at 96% 4%, #ffe8c4, transparent 60%), radial-gradient(ellipse 56% 38% at 55% 108%, #f4d9cf, transparent 64%), linear-gradient(120deg, #f6ecdb 0%, #efe6d4 100%)',
    dark:
      'radial-gradient(ellipse 50% 38% at 6% -6%, #6b3f16, transparent 62%), radial-gradient(ellipse 44% 34% at 96% 4%, #4a3320, transparent 60%), radial-gradient(ellipse 56% 38% at 55% 108%, #4a2a26, transparent 64%), linear-gradient(120deg, #1d1712 0%, #12100d 100%)',
  },
  {
    name: '晨雾',
    light:
      'radial-gradient(ellipse 46% 36% at 8% 0%, #dfe9f3, transparent 60%), radial-gradient(ellipse 42% 32% at 94% 8%, #f2ede4, transparent 58%), radial-gradient(ellipse 54% 36% at 50% 106%, #e6e2d8, transparent 62%), linear-gradient(135deg, #f3f4f2 0%, #e9e7e0 100%)',
    dark:
      'radial-gradient(ellipse 46% 36% at 8% 0%, #22303a, transparent 60%), radial-gradient(ellipse 42% 32% at 94% 8%, #2a2622, transparent 58%), radial-gradient(ellipse 54% 36% at 50% 106%, #1c2226, transparent 62%), linear-gradient(135deg, #15181a 0%, #0e1113 100%)',
  },
  {
    name: '黄昏',
    light:
      'radial-gradient(ellipse 48% 36% at 4% -4%, #ffb677, transparent 60%), radial-gradient(ellipse 44% 34% at 98% 2%, #f78d6b, transparent 58%), radial-gradient(ellipse 56% 38% at 52% 108%, #b98aa8, transparent 64%), linear-gradient(140deg, #f7c9a4 0%, #e8a07e 55%, #c98a98 100%)',
    dark:
      'radial-gradient(ellipse 48% 36% at 4% -4%, #7a3f14, transparent 60%), radial-gradient(ellipse 44% 34% at 98% 2%, #5a2a20, transparent 58%), radial-gradient(ellipse 56% 38% at 52% 108%, #3e2140, transparent 64%), linear-gradient(140deg, #2a1a12 0%, #1c1210 100%)',
  },
  {
    name: '夜灯',
    light:
      'radial-gradient(ellipse 48% 36% at 2% 0%, #f3d9b8, transparent 62%), radial-gradient(ellipse 42% 34% at 98% 6%, #e8e0d2, transparent 60%), radial-gradient(ellipse 58% 38% at 55% 108%, #e6d9c8, transparent 64%), linear-gradient(150deg, #f4ece0 0%, #e9e1d3 100%)',
    dark:
      'radial-gradient(ellipse 48% 36% at 2% 0%, #4a2c12, transparent 62%), radial-gradient(ellipse 42% 34% at 98% 6%, #2a1e28, transparent 60%), radial-gradient(ellipse 58% 38% at 55% 108%, #1c2a22, transparent 64%), linear-gradient(150deg, #17120d 0%, #0e0c0a 100%)',
  },
  {
    name: '松林',
    light:
      'radial-gradient(ellipse 46% 36% at 6% -2%, #cfe0cf, transparent 60%), radial-gradient(ellipse 44% 34% at 96% 4%, #d8e4e0, transparent 58%), radial-gradient(ellipse 54% 38% at 50% 106%, #dfe8dc, transparent 64%), linear-gradient(140deg, #eef2ec 0%, #e3e9e1 100%)',
    dark:
      'radial-gradient(ellipse 46% 36% at 6% -2%, #2f4a38, transparent 60%), radial-gradient(ellipse 44% 34% at 96% 4%, #22303a, transparent 58%), radial-gradient(ellipse 54% 38% at 50% 106%, #14352a, transparent 64%), linear-gradient(140deg, #1a241d 0%, #101512 100%)',
  },
  {
    name: '樱花',
    light:
      'radial-gradient(ellipse 48% 36% at 4% -4%, #ffd6e0, transparent 60%), radial-gradient(ellipse 44% 34% at 98% 6%, #ffeaf0, transparent 58%), radial-gradient(ellipse 54% 38% at 54% 108%, #f7dbe4, transparent 64%), linear-gradient(135deg, #fdf2f4 0%, #f3e4ea 100%)',
    dark:
      'radial-gradient(ellipse 48% 36% at 4% -4%, #5c2436, transparent 60%), radial-gradient(ellipse 44% 34% at 98% 6%, #3e1f2a, transparent 58%), radial-gradient(ellipse 54% 38% at 54% 108%, #351e28, transparent 64%), linear-gradient(135deg, #241419 0%, #160e12 100%)',
  },
  {
    name: '纯色',
    light: 'none',
    dark: 'none',
  },
];

function currentTheme() {
  const attr = document.documentElement.getAttribute('data-theme');
  if (attr === 'dark' || attr === 'light') return attr;
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
}

function defaultConfig() {
  return { type: 'preset', preset: 0, value: '', opacity: 0.9 };
}

class BackgroundManager {
  constructor() {
    this.config = defaultConfig();
    this._saveTimer = null;
    // 当前图片对应的 Blob URL 与它的来源 data URL（用于判断是否需要重建）
    this._objectUrl = null;
    this._objectSource = '';
    this.loadFromStorage();
    this.applyImage();
    this.applyScrim();
    this.watchTheme();
  }

  /** 释放旧 Blob URL：换图/换预设/重置时都要调用，否则内存会一直涨。 */
  releaseObjectUrl() {
    if (this._objectUrl) {
      URL.revokeObjectURL(this._objectUrl);
      this._objectUrl = null;
    }
    this._objectSource = '';
  }

  /** 当前自定义图片在 CSS 里的 URL。优先 Blob URL，失败才退回短 data URL。 */
  imageCssUrl() {
    const value = this.config.value;
    if (this._objectSource !== value || !this._objectUrl) {
      this.releaseObjectUrl();
      this._objectUrl = dataUrlToObjectUrl(value);
      this._objectSource = this._objectUrl ? value : '';
    }
    if (this._objectUrl) return `url("${this._objectUrl}")`;
    // 极小图片理论上走不到这里；真走不到说明 data URL 本身坏了。
    return value.length < 1_500_000 ? `url("${value}")` : 'none';
  }

  /* ────────── 持久化 ────────── */

  loadFromStorage() {
    let parsed = null;
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) parsed = JSON.parse(stored);
    } catch {
      parsed = null;
    }
    if (!parsed || typeof parsed !== 'object') return;

    const type = parsed.type;
    if (type === 'image' && typeof parsed.value === 'string' && parsed.value) {
      this.config.type = 'image';
      this.config.value = parsed.value;
    } else if (type === 'none') {
      this.config.type = 'none';
      this.config.preset = Number.isInteger(parsed.preset) ? parsed.preset : 6;
    } else if (type === 'preset' && Number.isInteger(parsed.preset)) {
      this.config.type = 'preset';
      this.config.preset = parsed.preset;
    } else if (type === 'gradient' && typeof parsed.value === 'string') {
      // 旧版 schema（只有 value 字符串）：匹配到同值预设，否则当作纯色
      const idx = PRESETS.findIndex((p) => p.light === parsed.value);
      if (idx >= 0) {
        this.config.type = PRESETS[idx].light === 'none' ? 'none' : 'preset';
        this.config.preset = idx;
      }
    } else if (type === 'custom' && typeof parsed.value === 'string') {
      // 更旧的 schema：custom = data URL
      this.config.type = 'image';
      this.config.value = parsed.value;
    }

    if (typeof parsed.opacity === 'number') {
      this.config.opacity = Math.max(0.3, Math.min(1, parsed.opacity));
    }
  }

  /** 立即写库；失败时抛错，绝不静默吞掉配额错误。 */
  saveNow() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(this.config));
  }

  /** 防抖写库（滑块这类高频操作）。 */
  scheduleSave() {
    if (this._saveTimer) clearTimeout(this._saveTimer);
    this._saveTimer = setTimeout(() => {
      this._saveTimer = null;
      try {
        this.saveNow();
      } catch (err) {
        console.error('背景设置保存失败:', err);
      }
    }, SAVE_DEBOUNCE_MS);
  }

  /* ────────── 应用 ────────── */

  applyImage() {
    const c = this.config;
    let image = 'none';
    if (c.type === 'image' && c.value) {
      image = this.imageCssUrl();
    } else if (c.type === 'preset') {
      this.releaseObjectUrl();
      const preset = PRESETS[c.preset] || PRESETS[0];
      image = preset[currentTheme()] || preset.light;
    } else {
      this.releaseObjectUrl();
    }
    document.documentElement.style.setProperty('--ambient-image', image);
    this.applyTint();
  }

  /**
   * 主题里的 `--ambient-tint` 是给背景压色用的（浅色 58% 画布色 / 深色 70%）。
   *
   * 早期版本给自定义照片把 tint 直接设成 transparent，让照片完全露出来。
   * 但顶栏/侧栏/底栏是 48%~55% 的薄玻璃：照片如果是纯黑或纯白，玻璃后
   * 的合成色会被拉到极端，叠在上面的次级文字只有 1.5~1.8:1 —— 基本读不出。
   * 所以照片保留一层**较薄但非零**的 tint（50%），既让壁纸仍清晰可见，
   * 又把最坏底拉回 AA。这个下限由 tests/test_design_tokens.py 的
   * TestImageTintContract 守住：调低它，测试会红。
   */
  applyTint() {
    const root = document.documentElement;
    if (this.config.type === 'image' && this.config.value) {
      // 50% 画布色压在图上层：实测浅色/深色两种主题、黑白两种极端照片下，
      // 顶栏次级文字都能回到 3.0:1 以上（纯黑照片浅色主题 3.98、纯白照片
      // 深色主题 3.40）。低于 0.43 时深色主题会跌破 3.0。
      root.style.setProperty('--ambient-tint', 'color-mix(in srgb, var(--bg) 50%, transparent)');
    } else {
      root.style.removeProperty('--ambient-tint');
    }
  }

  applyScrim() {
    const alpha = Math.round(
      (1 - Math.max(0, Math.min(1, this.config.opacity))) * 100,
    );
    document.documentElement.style.setProperty(
      '--ambient-scrim',
      `color-mix(in srgb, var(--bg) ${alpha}%, transparent)`,
    );
  }

  watchTheme() {
    if (typeof MutationObserver === 'undefined') return;
    new MutationObserver(() => this.applyImage()).observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    });
  }

  /* ────────── 修改 ────────── */

  setPreset(index) {
    const preset = PRESETS[index];
    if (!preset) return false;
    this.config = {
      ...this.config,
      type: preset.light === 'none' ? 'none' : 'preset',
      preset: index,
      // 切换预设要丢掉旧的自定义图片：留着 dataURL 会继续占满
      // localStorage 配额，而且用户已经看不到它了。
      value: '',
    };
    try {
      this.saveNow();
    } catch {
      // 预设体积很小，写失败通常只是存储被禁用；本次会话仍然生效
    }
    this.applyImage();
    return true;
  }

  async uploadImage(file) {
    if (!file || !file.type.startsWith('image/')) {
      throw new Error('仅支持图片文件');
    }
    if (file.size > MAX_SIZE) {
      throw new Error(
        `图片过大：${(file.size / 1024 / 1024).toFixed(1)}MB，上限 ${MAX_SIZE / 1024 / 1024}MB`,
      );
    }

    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error('文件读取失败'));
      reader.readAsDataURL(file);
    });

    const previous = { ...this.config };
    this.config = { ...this.config, type: 'image', value: dataUrl, opacity: 0.85 };
    try {
      this.saveNow();
    } catch (err) {
      // 持久化失败：回滚，并让界面显示原因
      this.config = previous;
      this.applyImage();
      this.applyScrim();
      throw new Error('背景图片无法保存到本机存储（空间不足或存储被禁用），请换一张更小的图片');
    }
    this.applyImage();
    // 上传会把透明度重置为 0.85，遮罩必须同步，否则图片仍按旧透明度压暗
    this.applyScrim();
    return true;
  }

  setOpacity(opacity) {
    this.config.opacity = Math.max(0.3, Math.min(1, Number(opacity) || 0.9));
    // 拖动期间只改遮罩，不重设图片、不做同步 JSON 序列化
    this.applyScrim();
    this.scheduleSave();
  }

  getConfig() {
    return { ...this.config };
  }

  reset() {
    this.config = defaultConfig();
    try {
      this.saveNow();
    } catch {
      /* 存储被禁用时至少让本次会话恢复默认 */
    }
    this.applyImage();
    this.applyScrim();
  }
}

export const backgroundManager = new BackgroundManager();
