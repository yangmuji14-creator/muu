"""视觉 token 的对比度契约（tools/check_contrast.py + tokens.css）。

为什么这件事值得一个测试：`tokens.css` 里的每个色值都带着「17.4:1」
「6.18:1」这样的注释断言，但注释不会因为改色值而报错。改一次颜色，
断言就变成假的，而界面上「稍微有点看不清」是没人会开 issue 的那种 bug。

所以把断言变成可执行的：任何一次色值改动，只要跌破 WCAG AA，测试就红。
两个主题 × 22 组表面配对 + 3 档玻璃 × 3 级文字 × 2 种底层 = 54 项。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from check_contrast import (  # noqa: E402
    GLASS_TIERS,
    PAIRS,
    TOKENS,
    WORST_BG,
    check_glass,
    composite,
    contrast,
    parse_color,
    parse_hex,
    parse_theme,
)


@pytest.fixture(scope="module")
def css() -> str:
    return TOKENS.read_text(encoding="utf-8")


class TestTokensFileExists:
    def test_tokens_css_present(self):
        assert TOKENS.is_file(), f"找不到 {TOKENS}"

    def test_both_themes_declared(self, css):
        assert "[data-theme='light']" in css
        assert "[data-theme='dark']" in css


class TestSurfaceContrast:
    """文字/结构线在不透明表面上的对比度。"""

    @pytest.mark.parametrize("theme", ["light", "dark"])
    @pytest.mark.parametrize("fg,bg,need,label", PAIRS)
    def test_pair_meets_wcag(self, css, theme, fg, bg, need, label):
        tokens = parse_theme(css, theme)
        fg_hex = tokens.get(fg)
        bg_hex = tokens.get(bg)
        assert fg_hex, f"缺少 --{fg} ({theme})"
        assert bg_hex, f"缺少 --{bg} ({theme})"
        fg_rgb = parse_hex(fg_hex)
        bg_rgb = parse_hex(bg_hex)
        assert fg_rgb and bg_rgb, f"色值不是 hex: {fg_hex} / {bg_hex}"
        ratio = contrast(fg_rgb, bg_rgb)
        assert ratio >= need, (
            f"{theme}: --{fg} on --{bg} = {ratio:.2f} < {need} ({label})"
        )


class TestGlassContrast:
    """玻璃上的文字 —— glassmorphism 唯一的真实风险点。

    玻璃底下的内容不可控（用户会发图片），所以必须按「最坏底」验证，
    而不是按页面底色验证。只测页面底会得到一个漂亮但无意义的数字。
    """

    @pytest.mark.parametrize("theme", ["light", "dark"])
    @pytest.mark.parametrize("glass_name,label,need", GLASS_TIERS)
    @pytest.mark.parametrize("text_name", ["text-1", "text-2", "text-3"])
    def test_text_readable_over_worst_case(self, css, theme, glass_name, label, need, text_name):
        tokens = parse_theme(css, theme)
        glass = parse_color(tokens.get(glass_name, ""))
        assert glass is not None, f"{theme}: 无法解析 --{glass_name}"
        fg = parse_hex(tokens.get(text_name, ""))
        assert fg is not None, f"{theme}: 缺少 --{text_name}"

        over_worst = composite(glass, WORST_BG)
        ratio = contrast(fg, over_worst)
        assert ratio >= need, (
            f"{theme}: --{text_name} on --{glass_name} 叠最坏底 = {ratio:.2f} < {need}"
            f" ({label}) —— 用户发的图片会成为玻璃底色"
        )

    def test_check_glass_helper_reports_no_problems(self, css):
        """check_glass 是给命令行用的同一套逻辑，它也必须报全绿。"""
        assert check_glass(css) == []


class TestGlassTierOrdering:
    """四档玻璃必须单调递增：越靠上的一层越不透明。

    顺序错了不会报错，只会让「模态看起来比抽屉还透」这种层级倒挂出现，
    而层级倒挂会直接破坏「谁在最上面」的视觉认知。
    """

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_alpha_increases_with_tier(self, css, theme):
        tokens = parse_theme(css, theme)
        alphas = []
        for name in ("glass-1", "glass-2", "glass-3"):
            parsed = parse_color(tokens.get(name, ""))
            assert parsed is not None, f"{theme}: 无法解析 --{name}"
            alphas.append(parsed[1])
        assert alphas == sorted(alphas), f"{theme}: 玻璃档位 alpha 未递增: {alphas}"

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_glass_alpha_is_thick_enough(self, css, theme):
        """alpha 低于 0.70 的玻璃在这个配色下撑不住正文对比度。"""
        tokens = parse_theme(css, theme)
        for name in ("glass-1", "glass-2", "glass-3"):
            parsed = parse_color(tokens.get(name, ""))
            assert parsed is not None
            assert parsed[1] >= 0.70, (
                f"{theme}: --{name} alpha={parsed[1]} 过薄，"
                "薄玻璃会让文字对比度随底层内容波动到不达标"
            )


class TestToastContrast:
    """Toast 的状态色对：深色主题下状态色是**浅色**，白字压上去只有 2.17:1。

    这是最容易漏的一类 bug —— 浅色主题下 #fff 恰好正确（6.17 / 7.14），
    所以「写死 #ffffff」在浅色下永远测不出来。必须用 on-* token。
    """

    TOAST_PAIRS = [
        ("toast-success-text", "toast-success-bg", "成功 toast"),
        ("toast-error-text", "toast-error-bg", "错误 toast"),
        ("toast-info-text", "toast-info-bg", "信息 toast"),
    ]

    @pytest.mark.parametrize("theme", ["light", "dark"])
    @pytest.mark.parametrize("fg,bg,label", TOAST_PAIRS)
    def test_toast_readable(self, css, theme, fg, bg, label):
        tokens = parse_theme(css, theme)
        fg_hex, bg_hex = tokens.get(fg), tokens.get(bg)
        assert fg_hex, f"缺少 --{fg} ({theme})"
        assert bg_hex, f"缺少 --{bg} ({theme})"
        fg_rgb, bg_rgb = parse_hex(fg_hex), parse_hex(bg_hex)
        assert fg_rgb and bg_rgb, f"色值不是 hex: {fg_hex} / {bg_hex}"
        ratio = contrast(fg_rgb, bg_rgb)
        assert ratio >= 4.5, f"{theme}: {label} {ratio:.2f} < 4.5"

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_toast_text_not_hardcoded_white(self, css, theme):
        """状态 toast 的文字色必须走 on-* token，不能写死 #ffffff。

        注意要读**原始声明**而不是解析后的值：`parse_theme` 会把
        `var(--on-success)` 解析成 `#0d1117`，从解析结果里根本看不出
        它当初是不是写死的白 —— 那正是这个 bug 能活下来的原因。

        toast token 住在第三个 `:root`（Layer 3）而不是主题块里，
        所以要在整个文件里找声明（它们本身就是主题无关的角色 token）。
        """
        for name in ("toast-success-text", "toast-error-text"):
            m = re.search(r"--" + name + r"\s*:\s*([^;]+);", css)
            assert m, f"缺少 --{name} 声明"
            raw = m.group(1).strip()
            assert raw.lower() not in ("#ffffff", "#fff", "white"), (
                f"--{name} = {raw!r} 写死了白色；"
                "深色主题的状态色是浅色，白字只有 2.17:1"
            )
            assert "on-" in raw, f"--{name} = {raw!r} 应指向 on-* token"
