"""视觉 token 的对比度契约（tools/check_contrast.py + tokens.css）。

为什么这件事值得一个测试：`tokens.css` 里的每个色值都带着「17.4:1」
「6.18:1」这样的注释断言，但注释不会因为改色值而报错。改一次颜色，
断言就变成假的，而界面上「稍微有点看不清」是没人会开 issue 的那种 bug。

所以把断言变成可执行的：任何一次色值改动，只要跌破 WCAG AA，测试就红。
两个主题 × 22 组表面配对 + 3 档玻璃 × 3 级文字 × 2 种底层 = 54 项。
"""

from __future__ import annotations

import colorsys
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

    # alpha 下限按主题分别设定，不是全局一个数。
    #   浅色 .50：玻璃必须是「近白霜」（spread 只有 4），颜色全靠 50% 的
    #     环境光透上来。这里 alpha 是**上限约束的反面** —— 越厚越白，越白
    #     色相越出不来，所以浅色的下限只守「文字别再随底图波动」这件事。
    #     曾经是 .55，但 .55 时 nav 列合成 #9cc0f7 spread 只有 91、整体
    #     明度压在 rel-L 74 以上，蓝紫渐变读起来像水彩；降到 .50 后
    #     nav 合成 #8ab5f6 spread 108、最暗一列 rel-L 69，渐变才立得住。
    #     代价是 text-2/text-3 必须同步压深（见 --text-2/--text-3 注释）。
    #   深色 .66：深玻璃本来就压得住最坏底，但低于 .66 之后 text-3 会掉到
    #     4.5 以下（深色底 + 中位灰图会把玻璃提亮到 (54,51,49)）。
    MIN_ALPHA = {"light": 0.50, "dark": 0.66}

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_glass_alpha_is_thick_enough(self, css, theme):
        """alpha 跌破该主题的下限后，正文对比度会随底层内容波动到不达标。"""
        tokens = parse_theme(css, theme)
        need = self.MIN_ALPHA[theme]
        for name in (
            "glass-1",
            "glass-2",
            "glass-3",
            "glass-nav",
            "glass-list",
            "glass-content",
            "glass-aside",
        ):
            parsed = parse_color(tokens.get(name, ""))
            assert parsed is not None, f"{theme}: 缺少或无法解析 --{name}"
            assert parsed[1] >= need, (
                f"{theme}: --{name} alpha={parsed[1]} 低于下限 {need}，"
                "薄玻璃会让文字对比度随底层内容波动到不达标"
            )


class TestColumnGlassLadder:
    """四列必须构成一条**可读的明度阶梯**，而且整页必须读得出蓝→紫。

    历史 bug 1（结构）：sidebar / conv-panel / panel-col 三列共用 --glass-1，
    于是无论怎么调这个 token，三列都同进同退。实测四列合成明度是
    93.5 / 95.2 / 92.3 / 91.0 —— 跨度 4.2 点，肉眼就是一片白。

    历史 bug 2（配色）：四列玻璃各带自己的色相（#072246 / #400e4d / ...），
    改一次氛围色就得重解一遍玻璃，两边互相稀释，二十几轮迭代都在这里打转。
    现在四列玻璃**完全相同**（浅色 rgba(250,251,254,.58) / 深色 rgba(11,13,20,.68)），
    所有颜色都由氛围层透上来 —— 于是「阶梯」和「色相」变成两条独立的、
    可以分别守住的契约。

    所以这组测试守三件事：
      1. 四列玻璃 token 各自存在（不会被合并回去）；
      2. 合成明度成阶梯（层次读得出来）；
      3. 合成色相跨度够宽（蓝→紫读得出来，不是单色淡蓝）。
    """

    # 每列在明度阶梯上的位置：浅色 content 最亮，深色 content 最暗。
    LADDER = {
        "light": ["glass-nav", "glass-aside", "glass-list", "glass-content"],
        "dark": ["glass-content", "glass-nav", "glass-aside", "glass-list"],
    }

    # 列 → 它脚下那块氛围色 token。radial-gradient 的四个色团分别压在这四列上。
    AMBIENT_OF = {
        "nav": "ambient-a",      # 左上
        "aside": "ambient-b",    # 右上
        "content": "ambient-c",  # 底部中偏右
        "list": "ambient-d",     # 左下
    }

    # 相邻两档的最小合成明度差。实测浅色 3.0/3.5/3.6、深色 2.0/2.0/2.0，
    # 取 1.2 留余量，但足以拦住「又被调回同一个色」这类回归。
    MIN_GAP = 1.2

    # 色相跨度门限。设计承诺是「横向蓝→紫」，锁的是**渲染后的合成色**。
    # 实测浅色 216→284 = 68°、深色 216→285 = 69°，取 55 留余量。
    MIN_HUE_SPAN = 55.0

    @staticmethod
    def _rel_lum(rgb: tuple[float, float, float]) -> float:
        """感知明度（0~100）。用亮度权重而不是 HSL 明度。

        HSL 的 (hi+lo)/2 对深色几乎不敏感：深色四列合成色 HSL 明度差
        1.4~3.0，换成感知明度后只剩零点几，正是「测试全绿、肉眼塌了」的由来。
        """
        r, g, b = rgb
        return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 * 100

    @staticmethod
    def _hue(rgb: tuple[float, float, float]) -> float:
        """色相角（0~360）。整数化后再算，避免浮点抖动导致色相跳崖。"""
        r, g, b = (round(c) / 255 for c in rgb)
        h, _l, _s = colorsys.rgb_to_hls(r, g, b)
        return h * 360

    def _composite(self, css: str, theme: str, name: str) -> tuple[float, float, float]:
        """玻璃叠在它**自己脚下那块氛围**上的合成色 —— 屏幕上真正看到的颜色。

        这是本轮配色的唯一模型：`屏幕色 = alpha·玻璃 + (1−alpha)·氛围`。
        只算玻璃自身色是没意义的 —— 四列玻璃现在完全相同，玻璃色恒等于
        一个中性色，任何基于它的断言都会「全绿而肉眼没变化」。

        预测值与截图实测差一个恒定偏移（backdrop blur 与 saturate 的再加工，
        约 -1.1 明度点），**排序、相邻差、色相基本一致**，用它守回归是可靠的。
        """
        tokens = parse_theme(css, theme)
        glass = parse_color(tokens.get(name, ""))
        assert glass is not None, f"{theme}: 无法解析 --{name}"
        amb_name = self.AMBIENT_OF[name.split("-", 1)[1]]
        amb = parse_color(tokens.get(amb_name, ""))
        assert amb is not None, f"{theme}: 无法解析 --{amb_name}（四列的氛围色）"
        (g_rgb, alpha), (a_rgb, _) = glass, amb
        return tuple(alpha * g_rgb[i] + (1 - alpha) * a_rgb[i] for i in range(3))

    def _glass_lightness(self, css: str, theme: str, name: str) -> float:
        """兼容旧调用：返回合成明度（阶梯的唯一有效指标）。"""
        return self._rel_lum(self._composite(css, theme, name))

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_column_glass_tokens_exist(self, css, theme):
        tokens = parse_theme(css, theme)
        for name in ("glass-nav", "glass-aside", "glass-list", "glass-content"):
            assert parse_color(tokens.get(name, "")) is not None, (
                f"{theme}: 缺少 --{name} —— 四列必须各有一档玻璃，"
                "否则会退回「三列共用 --glass-1」的老问题"
            )
        for name in self.AMBIENT_OF.values():
            assert parse_color(tokens.get(name, "")) is not None, (
                f"{theme}: 缺少 --{name} —— 四列的颜色全靠它，玻璃是中性霜"
            )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_ladder_is_monotonic(self, css, theme):
        order = self.LADDER[theme]
        vals = [self._glass_lightness(css, theme, n) for n in order]
        assert vals == sorted(vals), (
            f"{theme}: 明度阶梯方向错了 —— 按 {order} 应单调，实测 {[round(v,1) for v in vals]}"
        )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_adjacent_gaps_are_visible(self, css, theme):
        order = self.LADDER[theme]
        vals = [self._glass_lightness(css, theme, n) for n in order]
        gaps = [round(b - a, 2) for a, b in zip(vals, vals[1:])]
        for gap, (a, b) in zip(gaps, zip(order, order[1:])):
            assert gap >= self.MIN_GAP, (
                f"{theme}: --{a} → --{b} 只差 {gap} 个明度点 "
                f"(要求 ≥{self.MIN_GAP})，这个差距在屏幕上读不出层次"
            )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_total_span_is_wide_enough(self, css, theme):
        """总跨度是「四列看着是不是同一块」的直接指标。"""
        vals = [self._glass_lightness(css, theme, n) for n in self.LADDER[theme]]
        span = vals[-1] - vals[0]
        need = 8.0 if theme == "light" else 4.5
        assert span >= need, (
            f"{theme}: 四列总跨度只有 {span:.1f} 个明度点 (要求 ≥{need})，"
            "会退回整改前「四块一样白/一样黑」的状态"
        )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_hue_span_reads_blue_to_violet(self, css, theme):
        """整页必须读得出「蓝 → 紫」，不能是单色淡蓝。

        这是用户 m03422 的直接诉求（"你不是蓝色和紫色的渐变色吗，
        我现在只看到淡蓝色"）。前二十几轮之所以失败，是因为色相虽然排开了
        (H214→H288)，但合成明度全落在 L85~L94 —— **在 L88 处 HSL 的 S 是失真的**：
        S100 的 #f8f3ff 通道差只有 34，人眼读成"白里带一点粉"。
        所以这条测试必须锁**合成色**的色相，而不是氛围色的色相。
        """
        hues = {n.split("-", 1)[1]: self._hue(self._composite(css, theme, n))
                for n in ("glass-nav", "glass-aside", "glass-list", "glass-content")}
        lo = min(hues.values())
        hi = max(hues.values())
        span = hi - lo
        assert span >= self.MIN_HUE_SPAN, (
            f"{theme}: 四列合成色相只跨了 {span:.0f}° "
            f"(要求 ≥{self.MIN_HUE_SPAN:.0f}°)，整页会读成单色而不是蓝→紫渐变："
            f"{ {k: round(v) for k, v in hues.items()} }"
        )
        # 方向也要对：侧栏最蓝、右栏最紫。反了就不是「蓝→紫」而是「紫→蓝」，
        # 左右视觉重心会跟着颠倒（深色下正文最暗那条规则同理）。
        assert hues["nav"] == lo, (
            f"{theme}: 侧栏不是最蓝的一端（nav H{round(hues['nav'])} vs 最小 H{round(lo)}）"
        )
        assert hues["aside"] == hi, (
            f"{theme}: 右栏不是最紫的一端（aside H{round(hues['aside'])} vs 最大 H{round(hi)}）"
        )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_glass_itself_is_neutral(self, css, theme):
        """四列玻璃必须是**中性**的（四者完全相同），颜色只由氛围提供。

        这是 v6 的结构性决定，也是本次求解能收敛的原因：
        玻璃若各带色相，就会和脚下氛围互相稀释，反解公式失效，
        每改一次氛围都要重解一遍玻璃 —— 那就是前二十几轮的死循环。
        """
        tokens = parse_theme(css, theme)
        seen = {}
        for name in ("glass-nav", "glass-aside", "glass-list", "glass-content"):
            parsed = parse_color(tokens.get(name, ""))
            assert parsed is not None, f"{theme}: 无法解析 --{name}"
            seen[name] = tuple(round(c) for c in parsed[0])
        assert len(set(seen.values())) == 1, (
            f"{theme}: 四列玻璃不再中性：{seen} —— "
            "玻璃带色相会和氛围互相稀释，颜色就调不出来了"
        )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_solid_fallback_equals_composite(self, css, theme):
        """减弱透明模式的兜底实色必须等于**合成色**，不是玻璃色。

        兜底如果退回 --bg 或退成玻璃自己的近白/近黑，四列会在无障碍模式下
        被压成同一个色 —— 等于「开了减弱透明就退回整改前」，
        这是最容易被忽略的回归。所以这里比的是合成色，容差 3。
        """
        tokens = parse_theme(css, theme)
        for col in ("nav", "aside", "list", "content"):
            solid = parse_hex(tokens.get(f"col-{col}-solid", ""))
            assert solid is not None, f"{theme}: 缺少兜底实色 --col-{col}-solid"
            comp = self._composite(css, theme, f"glass-{col}")
            diff = max(abs(solid[i] - round(comp[i])) for i in range(3))
            assert diff <= 3, (
                f"{theme}: --col-{col}-solid 与玻璃×氛围的合成色差 {diff} "
                f"(要求 ≤3)：实色 {solid} vs 合成 {tuple(round(c) for c in comp)}"
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
