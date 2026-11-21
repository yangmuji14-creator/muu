"""校验 tokens.css 里声明的对比度是否真的达标。

设计文档里写了「text-3 从 3.0:1 提到 4.3:1」这类断言，但断言是手算的，
改一次色值就可能悄悄失效。这个脚本把 tokens.css 当真值源，解析每个主题
的色值，按 WCAG 2.1 公式重算，不达标就退出码 1。

用法：
    python tools/check_contrast.py          # 检查并打印表格
    python tools/check_contrast.py -v       # 打印全部配对（含达标的）

只解析 `[data-theme='light']` / `[data-theme='dark']` 两个块里的
`--name: #hex` 形式。玻璃档位是 rgba，需要先按背景合成才谈得上对比度，
这里只校验「文字 on 不透明表面」这组核心配对 —— 玻璃上的文字由
`--glass-*` 的 alpha 设计保证（见 tokens.css 里的注释）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

STYLES = Path(__file__).resolve().parent.parent / "webui" / "frontend" / "src" / "styles"
TOKENS = STYLES / "tokens.css"
# 主题色值住在第二层：tokens.css 定义刻度与角色别名，theme-liquid.css
# 提供 light/dark 两套真实色值。只读 tokens.css 会解析到空的 var()。
THEME_LIQUID = STYLES / "theme-liquid.css"


def load_css() -> str:
    """合并两层样式表，作为对比度校验的输入。"""
    parts = [TOKENS.read_text(encoding="utf-8")]
    if THEME_LIQUID.is_file():
        parts.append(THEME_LIQUID.read_text(encoding="utf-8"))
    return "\n".join(parts)

# 需要校验的配对：(前景 token, 背景 token, 最低要求, 用途)
# 4.5 = 正文/次要文字 (WCAG AA normal text)
# 3.0 = 大字号/UI 结构线 (WCAG AA non-text / large text)
PAIRS = [
    ("text-1", "surface", 4.5, "主文字"),
    ("text-2", "surface", 4.5, "次要文字"),
    # text-3（元信息/时间戳层）刻意压低对比度，约 2.5~3.3:1 —— 这是设计
    # 选择，不是遗漏。它不进这组 AA 配对；由 TestTertiaryTextException
    # 记录「已知例外 + 层级不塌陷 + 不再继续下降」这三件事。
    ("text-1", "bg", 4.5, "主文字 on 页面底"),
    ("text-2", "bg", 4.5, "次要文字 on 页面底"),
    ("text-1", "surface-2", 4.5, "主文字 on hover 面"),
    ("text-2", "surface-2", 4.5, "次要文字 on hover 面"),
    ("text-1", "surface-3", 4.5, "主文字 on 按下态"),
    ("text-2", "surface-3", 4.5, "次要文字 on 按下态"),
    ("accent", "surface", 4.5, "强调色文字"),
    ("accent", "bg", 4.5, "强调色 on 页面底"),
    ("on-accent", "accent", 4.5, "强调色上的文字"),
    ("success", "surface", 4.5, "成功色文字"),
    ("warning", "surface", 4.5, "警告色文字"),
    ("error", "surface", 4.5, "错误色文字"),
    ("on-success", "success", 4.5, "成功底上的文字"),
    ("on-warning", "warning", 4.5, "警告底上的文字"),
    ("on-error", "error", 4.5, "错误底上的文字"),
    ("border-strong", "surface", 3.0, "结构线 (表单边界)"),
    ("border-strong", "bg", 3.0, "结构线 on 页面底"),
]

HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
RGBA_RE = re.compile(
    r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$"
)


def parse_color(value: str) -> tuple[tuple[int, int, int], float] | None:
    """解析 #hex 或 rgba()，返回 (rgb, alpha)。"""
    value = value.strip()
    rgb = parse_hex(value)
    if rgb is not None:
        return rgb, 1.0
    m = RGBA_RE.match(value)
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        a = float(m.group(4)) if m.group(4) is not None else 1.0
        return (r, g, b), a
    return None


def composite(
    fg: tuple[tuple[int, int, int], float], bg: tuple[int, int, int]
) -> tuple[int, int, int]:
    """把带 alpha 的前景合成到不透明背景上。"""
    (r, g, b), a = fg
    return (
        round(r * a + bg[0] * (1 - a)),
        round(g * a + bg[1] * (1 - a)),
        round(b * a + bg[2] * (1 - a)),
    )


def parse_hex(value: str) -> tuple[int, int, int] | None:
    value = value.strip()
    if not HEX_RE.match(value):
        return None
    h = value[1:]
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rel_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    l1, l2 = rel_luminance(fg), rel_luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_at_rule_blocks(css: str) -> str:
    """删除 `@media` / `@supports` / `@keyframes` 等 at-rule 的整块内容。

    它们内部的规则（如 `@media (prefers-reduced-motion: reduce) { :root {
    --dur-1: 0ms } }`）不是无条件生效的，混进基础层会让 `parse_theme`
    把「减弱动效」下的值当成默认值 —— 颜色若哪天也放进 @media，就会
    按永不生效的条件校验。at-rule 的括号是按字符扫描配对的，不用正则，
    因为正则在嵌套块上会错位。
    """
    out = []
    i = 0
    n = len(css)
    while i < n:
        at = css.find("@", i)
        if at == -1:
            out.append(css[i:])
            break
        out.append(css[i:at])
        # 找到 at-rule 的名字与其后的第一个 `{`
        brace = css.find("{", at)
        semi = css.find(";", at)
        if brace == -1 or (semi != -1 and semi < brace):
            # 无块 at-rule（如 @import ...;）—— 原样跳过到分号
            out.append(css[at:semi + 1] if semi != -1 else css[at:])
            i = (semi + 1) if semi != -1 else n
            continue
        depth = 0
        j = brace
        while j < n:
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
                if depth == 0:
                    j += 1
                    break
            j += 1
        i = j
    return "".join(out)


def _blocks(css: str):
    """逐个产出 (选择器列表, 声明体)。只关心没有嵌套规则的普通规则块。

    先剥掉注释：正则 `([^{}]+)\\{` 会把块前紧邻的 `/* ... */` 当成选择器
    文本的一部分，于是 `:root { ... }` 前面只要有注释，选择器就变成
    `/* ... */\\n:root`，`_has_selector(sel, ':root')` 返回 False —— 整个
    基础层（字体/间距/圆角/字号刻度）被静默丢掉。tokens.css 的第一个
    `:root` 正好前面有注释，所以这条不是理论问题。

    再剥掉 at-rule 块：`@media` 里的规则只在特定条件下生效，不能当作
    基础层的默认值（否则「减弱动效」的 `--dur-*: 0ms` 会顶掉真实值）。
    """
    css = COMMENT_RE.sub("", css)
    css = _strip_at_rule_blocks(css)
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        yield selector, body


def _collect(css: str, want) -> dict[str, str]:
    """把选择器满足 `want` 的所有块里的 `--name: value;` 合并成扁平 dict。

    `want(selector)` 收到整段选择器列表。用谓词而不是单个正则，是因为
    一个块可能同时挂多个选择器：`:root, [data-theme], [data-accent] { ... }`。
    旧实现用 `:root\\s*\\{` 精确匹配，遇到这种选择器列表会整块漏掉 ——
    `--glass-*` 别名因此从来解析不到。任何按选择器抓 token 的地方都必须
    先按逗号拆开再看，而不是对整段选择器跑正则。
    """
    out: dict[str, str] = {}
    for selector, body in _blocks(css):
        if not want(selector):
            continue
        for name, value in re.findall(r"--([\w-]+)\s*:\s*([^;]+);", body):
            out[name] = value.strip()
    return out


def _has_selector(selector: str, target: str) -> bool:
    """选择器列表里是否含完全等于 `target` 的一项（忽略空白）。"""
    return any(part.strip() == target for part in selector.split(","))


def parse_theme(css: str, theme: str) -> dict[str, str]:
    """解析某个主题下的全部 token。

    tokens.css 是**三层结构**：
      1. `:root`（Layer 1：尺寸/间距/圆角）
      2. `[data-theme='light'|'dark']`（theme-liquid.css：语义色）
      3. 第二个 `:root`（Layer 3：组件角色 token —— toast / input / glass 别名）

    只读主题块会漏掉第 3 层，于是 `--toast-success-text` 这类 token
    在解析结果里根本不存在。之前正是这样漏掉了「深色 toast 白字只有
    2.17:1」这个真实缺陷 —— 测试没报错，是因为它压根没读到那个 token。

    所以这里先铺 `:root` / `[data-theme]` / `[data-accent]` 作为基础层，
    再用本主题的块覆盖。传入的 css 应包含 tokens.css + theme-liquid.css
    （见 `load_css`）。
    """
    themed_selector = f"[data-theme='{theme}']"
    themed_value = re.compile(r"\[data-theme=['\"](?:light|dark)['\"]\]")

    def is_theme_block(sel: str) -> bool:
        return any(themed_value.fullmatch(part.strip()) for part in sel.split(","))

    def is_base_block(sel: str) -> bool:
        # 主题专属块（含 `:root, [data-theme='light']` 这种混写）不能进基础层，
        # 否则算深色时会先铺一层浅色值，漏掉的 token 就会串主题。
        if is_theme_block(sel):
            return False
        return (
            _has_selector(sel, ":root")
            or _has_selector(sel, "[data-theme]")
            or _has_selector(sel, "[data-accent]")
        )

    base = _collect(css, is_base_block)
    themed = _collect(css, lambda sel: _has_selector(sel, themed_selector))
    if not themed:
        raise SystemExit(f"样式表里找不到 {themed_selector} 块")

    raw = {**base, **themed}

    # 解析 var(--x) 引用（可能嵌套，本文件最多三层）
    def resolve(name: str, depth: int = 0) -> str:
        if depth > 6:
            return ""
        val = raw.get(name, "")
        vm = re.fullmatch(r"var\(--([\w-]+)\)", val)
        if vm:
            return resolve(vm.group(1), depth + 1)
        return val

    return {name: resolve(name) for name in raw}


# 玻璃上的文字必须考虑「底下是什么」——这是 glassmorphism 唯一的真实风险。
#
# 关键修正：中位灰 #808080 **不是**最坏底。对半透明玻璃而言，最坏底是
# 「把合成色拉得离文字色最近」的那一端：
#   · 浅色主题文字是深色 → 越暗的底，合成色越暗，越贴近文字 → 最坏底是黑；
#   · 深色主题文字是浅色 → 越亮的底，合成色越亮，越贴近文字 → 最坏底是白。
# 旧代码只取 #808080，于是「用户设一张深色壁纸、浅色主题下顶栏/侧栏的
# 次级文字掉到 1.8:1」这种情况全绿通过。现在按主题分别取最坏端。
WORST_BG_LIGHT = (0, 0, 0)        # 浅色主题：深色文字，最坏底是黑
WORST_BG_DARK = (255, 255, 255)   # 深色主题：浅色文字，最坏底是白
WORST_BG = (128, 128, 128)        # 保留：中位灰，供外部/旧调用方引用


def worst_backdrop(theme: str) -> tuple[int, int, int]:
    """该主题下玻璃背后真正最坏的那一端底色。"""
    return WORST_BG_DARK if theme == "dark" else WORST_BG_LIGHT


# 自定义壁纸在背景图之上还有一层 `--ambient-tint`（见 backgroundManager.applyTint）。
# 压色把最坏底从纯黑/纯白拉回中间。校验「照片当底」时必须先叠这层压色，
# 否则测的是「用户关掉压色」的假设，而不是实际渲染条件。
IMAGE_TINT_ALPHA = 0.50

# 与 theme-liquid.css 的 --bg 保持一致；改主题底色时同步这里。
IMAGE_TINT_HEX = {
    "light": (0xF6, 0xF5, 0xF2),
    "dark": (0x0D, 0x0E, 0x12),
}


def image_backdrop(theme: str) -> tuple[int, int, int]:
    """照片当壁纸时，玻璃真正看到的底色：最坏端照片 + 压色层。"""
    tint = IMAGE_TINT_HEX[theme]
    alpha = IMAGE_TINT_ALPHA
    worst = worst_backdrop(theme)
    return tuple(round(tint[i] * alpha + worst[i] * (1 - alpha)) for i in range(3))


GLASS_TIERS = [
    ("glass-1", "chrome 档：顶栏/底栏/浮层通用", 4.5),
    ("glass-2", "sheet 档：抽屉/底部面板", 4.5),
    ("glass-3", "modal 档：模态弹窗", 4.5),
    # 列级玻璃：四列各用一档，明度阶梯靠它们撑开。
    # 这几档是主界面停留时间最长的表面，必须和最薄的 chrome 档同等要求。
    ("glass-nav", "列级：侧栏（四列里最暗/最亮的一端）", 4.5),
    ("glass-list", "列级：会话列表栏", 4.5),
    ("glass-content", "列级：正文区（明度阶梯的锚点）", 4.5),
    ("glass-aside", "列级：右栏（她的状态）", 4.5),
]


# 玻璃背后真正的底：列级玻璃叠在各自的氛围色上（四列靠色相方向区分），
# 浮层（chrome/sheet/modal）叠在页面底上。这是用户每天看到的真实条件，
# 也是这一版液态玻璃的校验基准 —— 上一版把「任意用户照片」当作所有玻璃的底，
# 那条契约要求玻璃接近不透明；这一版有意用更薄的玻璃，改用真实画布验证。
COLUMN_CANVAS = {
    "nav": "ambient-a",      # 左上
    "aside": "ambient-b",    # 右上
    "content": "ambient-c",  # 底部中偏右
    "list": "ambient-d",     # 左下
}

# 只有这几档浮层会整片压在滚动内容（可能含图片）之上；列级玻璃下面
# 始终是自己的氛围色。所以「对抗性底图」的检查只针对浮层 + 主文字/次级文字。
FLOATING_TIERS = ("glass-1", "glass-2", "glass-3")

# WCAG AA 对大字/UI 元素的下限；用于玻璃压在图片上的次级文字。
NOT_TEXT_FLOOR = 3.0


def glass_backdrop(tokens: dict[str, str], glass_name: str) -> str:
    """某一档玻璃背后真正的底色 token 名。"""
    suffix = glass_name[len("glass-"):]
    return COLUMN_CANVAS.get(suffix, "bg")


def glass_over_canvas(tokens: dict[str, str], glass_name: str):
    """玻璃叠在它自己那块画布上的合成色 —— 屏幕上真正看到的颜色。"""
    glass = parse_color(tokens.get(glass_name, ""))
    backdrop = parse_color(tokens.get(glass_backdrop(tokens, glass_name), ""))
    if glass is None or backdrop is None:
        return None
    return composite(glass, backdrop[0])


def check_glass(css: str) -> list[str]:
    """校验玻璃上的文字：真实画布上必须 AA；压在图片上时主文字必须 AA。

    与上一版契约的差别（有意为之，见 theme-liquid.css 的材质说明）：
      · 常态背景（列级氛围 / 页面底）：text-1/2 4.5:1；
      · 对抗性底图（该主题最坏的一端：浅色→黑、深色→白）：
        主文字 4.5:1，次级文字 3.0:1；
      · text-3 是刻意压低的元信息层（约 3:1），不在此契约内，
        由 tests/test_design_tokens.py 的 TestTertiaryTextException 记录。
    """
    problems: list[str] = []
    print("\n=== 玻璃档位上的文字对比度 ===")
    print(f"{'档位':<12}{'文字':<10}{'叠画布':>8}{'叠图片':>8}  结论")

    for theme in ("light", "dark"):
        tokens = parse_theme(css, theme)
        print(f"\n[{theme}]")
        for glass_name, label, need in GLASS_TIERS:
            raw = tokens.get(glass_name, "")
            parsed = parse_color(raw)
            if parsed is None:
                problems.append(f"{theme}: 无法解析 --{glass_name} = {raw!r}")
                continue
            over_canvas = glass_over_canvas(tokens, glass_name)
            if over_canvas is None:
                problems.append(
                    f"{theme}: 无法合成 --{glass_name} 的画布底色"
                    f"（--{glass_backdrop(tokens, glass_name)}）"
                )
                continue
            over_worst = composite(parsed, image_backdrop(theme))
            # text-3 不在 AA 契约里（见 PAIRS 上方说明），这里只校验 1/2 级。
            for text_name in ("text-1", "text-2"):
                fg = parse_hex(tokens.get(text_name, ""))
                if fg is None:
                    problems.append(f"{theme}: 缺少 --{text_name}")
                    continue
                r_canvas = contrast(fg, over_canvas)
                r_worst = contrast(fg, over_worst)
                # 图片上的门槛：主文字 AA，次级按 UI 下限。
                floor = need if text_name == "text-1" else NOT_TEXT_FLOOR
                ok = r_canvas >= need and r_worst >= floor
                if not ok:
                    if r_canvas < need:
                        problems.append(
                            f"{theme}: {text_name} on {glass_name} 叠画布 {r_canvas:.2f} < {need} ({label})"
                        )
                    else:
                        problems.append(
                            f"{theme}: {text_name} on {glass_name} 叠图片 {r_worst:.2f} < {floor} ({label})"
                        )
                print(
                    f"  {glass_name:<10}{text_name:<10}{r_canvas:>8.2f}{r_worst:>8.2f}"
                    f"  {'OK ' if ok else 'FAIL'} {label}"
                )
    return problems


def main() -> int:
    verbose = "-v" in sys.argv
    css = load_css()

    failures: list[str] = []
    for theme in ("light", "dark"):
        tokens = parse_theme(css, theme)
        print(f"\n=== {theme} ===")
        print(f"{'配对':<34}{'实测':>7}{'要求':>7}  结论")
        for fg_name, bg_name, need, label in PAIRS:
            fg_hex, bg_hex = tokens.get(fg_name), tokens.get(bg_name)
            if not fg_hex or not bg_hex:
                failures.append(f"{theme}: 缺少 token --{fg_name} 或 --{bg_name}")
                continue
            ratio = contrast(parse_hex(fg_hex), parse_hex(bg_hex))
            ok = ratio >= need
            if not ok:
                failures.append(
                    f"{theme}: {fg_name} on {bg_name} = {ratio:.2f} < {need} ({label})"
                )
            if verbose or not ok:
                mark = "OK " if ok else "FAIL"
                print(
                    f"  {fg_name} on {bg_name:<14}{ratio:>7.2f}{need:>7.1f}  {mark} {label}"
                )

    total = len(PAIRS) * 2
    print(f"\n{total - len([f for f in failures if 'glass' not in f])}/{total} 表面配对达标")

    glass_problems = check_glass(css)
    if glass_problems:
        failures.extend(glass_problems)

    if failures:
        print("\n不达标：")
        for f in failures:
            print("  -", f)
        return 1
    print("\n全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
