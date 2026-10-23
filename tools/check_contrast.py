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

TOKENS = Path(__file__).resolve().parent.parent / "webui" / "frontend" / "src" / "styles" / "tokens.css"

# 需要校验的配对：(前景 token, 背景 token, 最低要求, 用途)
# 4.5 = 正文/次要文字 (WCAG AA normal text)
# 3.0 = 大字号/UI 结构线 (WCAG AA non-text / large text)
PAIRS = [
    ("text-1", "surface", 4.5, "主文字"),
    ("text-2", "surface", 4.5, "次要文字"),
    ("text-3", "surface", 4.5, "弱化文字"),
    ("text-1", "bg", 4.5, "主文字 on 页面底"),
    ("text-2", "bg", 4.5, "次要文字 on 页面底"),
    ("text-3", "bg", 4.5, "弱化文字 on 页面底"),
    ("text-1", "surface-2", 4.5, "主文字 on hover 面"),
    ("text-2", "surface-2", 4.5, "次要文字 on hover 面"),
    ("text-3", "surface-2", 4.5, "弱化文字 on hover 面"),
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


def _collect(css: str, pattern: str) -> dict[str, str]:
    """把匹配到的所有块里的 `--name: value;` 合并成一个扁平 dict。"""
    out: dict[str, str] = {}
    for block in re.findall(pattern, css, re.DOTALL):
        for name, value in re.findall(r"--([\w-]+)\s*:\s*([^;]+);", block):
            out[name] = value.strip()
    return out


def parse_theme(css: str, theme: str) -> dict[str, str]:
    """解析某个主题下的全部 token。

    tokens.css 是**三层结构**：
      1. `:root`（Layer 1：尺寸/间距/圆角）
      2. `[data-theme='light'|'dark']`（Layer 2：语义色）
      3. 第二个 `:root`（Layer 3：组件角色 token —— toast / input / glass 别名）

    只读主题块会漏掉第 3 层，于是 `--toast-success-text` 这类 token
    在解析结果里根本不存在。之前正是这样漏掉了「深色 toast 白字只有
    2.17:1」这个真实缺陷 —— 测试没报错，是因为它压根没读到那个 token。

    所以这里先铺 `:root` 作为基础层，再用主题块覆盖。
    """
    base = _collect(css, r":root\s*\{(.*?)\n\}")
    themed = _collect(
        css, r"\[data-theme=['\"]" + theme + r"['\"]\]\s*\{(.*?)\n\}"
    )
    if not themed:
        raise SystemExit(f"tokens.css 里找不到 [data-theme='{theme}'] 块")

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
# 最坏情况不是页面底色，而是玻璃下面压着一张中位灰的图片（用户发的照片、
# 头像、封面图都会这样）。取 #808080 作为最坏底，是行业里常用的保守假设：
# 任何比它更亮或更暗的底，合成后的对比度都更好。
WORST_BG = (128, 128, 128)

GLASS_TIERS = [
    ("glass-1", "chrome 档：顶栏/底栏/侧栏", 4.5),
    ("glass-2", "sheet 档：抽屉/底部面板", 4.5),
    ("glass-3", "modal 档：模态弹窗", 4.5),
]


def check_glass(css: str) -> list[str]:
    """校验四档玻璃上 text-1/2/3 在「页面底」和「最坏内容」两种情况下的对比度。"""
    problems: list[str] = []
    print("\n=== 玻璃档位上的文字对比度 ===")
    print(f"{'档位':<12}{'文字':<10}{'叠页面底':>10}{'叠最坏内容':>12}  结论")

    for theme in ("light", "dark"):
        tokens = parse_theme(css, theme)
        page_bg = parse_hex(tokens.get("bg", "")) or (255, 255, 255)
        print(f"\n[{theme}]")
        for glass_name, label, need in GLASS_TIERS:
            raw = tokens.get(glass_name, "")
            parsed = parse_color(raw)
            if parsed is None:
                problems.append(f"{theme}: 无法解析 --{glass_name} = {raw!r}")
                continue
            over_page = composite(parsed, page_bg)
            over_worst = composite(parsed, WORST_BG)
            for text_name in ("text-1", "text-2", "text-3"):
                fg = parse_hex(tokens.get(text_name, ""))
                if fg is None:
                    problems.append(f"{theme}: 缺少 --{text_name}")
                    continue
                r_page = contrast(fg, over_page)
                r_worst = contrast(fg, over_worst)
                worst = min(r_page, r_worst)
                ok = worst >= need
                if not ok:
                    problems.append(
                        f"{theme}: {text_name} on {glass_name} 最差 {worst:.2f} < {need} ({label})"
                    )
                print(
                    f"  {glass_name:<10}{text_name:<10}{r_page:>10.2f}{r_worst:>12.2f}"
                    f"  {'OK ' if ok else 'FAIL'} {label}"
                )
    return problems


def main() -> int:
    verbose = "-v" in sys.argv
    css = TOKENS.read_text(encoding="utf-8")

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
