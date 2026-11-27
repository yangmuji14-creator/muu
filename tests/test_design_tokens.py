"""视觉 token 的对比度契约（tools/check_contrast.py + tokens.css/theme-liquid.css）。

为什么这件事值得一个测试：色值都带着「17.4:1」「6.18:1」这样的注释断言，
但注释不会因为改色值而报错。改一次颜色，断言就变成假的，而界面上
「稍微有点看不清」是没人会开 issue 的那种 bug。

契约范围（这一版液态玻璃）：
  · 主/次级文字：不透明表面上 4.5:1；玻璃压图片时 4.5 / 3.0:1；
  · 三级文字：设计上刻意压低到约 3:1，是**已知例外**，见
    TestTertiaryTextException —— 它记录例外的边界，而不是假装达标；
  · 玻璃材质本身：alpha 阶梯单调、列级同层同膜、舞台合成后更亮、
    兜底实色等于合成色。
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
    IMAGE_TINT_ALPHA,
    IMAGE_TINT_HEX,
    NOT_TEXT_FLOOR,
    PAIRS,
    THEME_LIQUID,
    TOKENS,
    check_glass,
    composite,
    contrast,
    glass_over_canvas,
    image_backdrop,
    load_css,
    parse_color,
    parse_hex,
    parse_theme,
    worst_backdrop,
)


@pytest.fixture(scope="module")
def css() -> str:
    # 主题色值住在 theme-liquid.css；只读 tokens.css 会全是空 var()。
    return load_css()


class TestTokensFileExists:
    def test_tokens_css_present(self):
        assert TOKENS.is_file(), f"找不到 {TOKENS}"

    def test_theme_layer_present(self):
        assert THEME_LIQUID.is_file(), f"找不到 {THEME_LIQUID}"

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

    这一版液态玻璃有意做得更薄（0.48 / 0.55），所以分两种情况验证：

      1. **真实画布**（列级玻璃叠自己的氛围色、浮层叠页面底）：
         text-1/2 必须 4.5:1 —— 这是每天看到的样子；
      2. **对抗性底图**（玻璃下面压着用户图片 #808080）：
         主文字必须 4.5:1；次级文字降到 WCAG AA 大字/UI 的 3.0:1。

    text-3 是刻意压低的元信息层（约 3:1），不在 AA 契约内，见
    TestTertiaryTextException。上一版契约要求所有档位、所有文字压图片
    都 4.5:1 —— 那要求玻璃接近不透明，等于否掉这一版的材质设计。
    """

    @pytest.mark.parametrize("theme", ["light", "dark"])
    @pytest.mark.parametrize("glass_name,label,need", GLASS_TIERS)
    @pytest.mark.parametrize("text_name", ["text-1", "text-2"])
    def test_text_readable_on_real_canvas(self, css, theme, glass_name, label, need, text_name):
        tokens = parse_theme(css, theme)
        over_canvas = glass_over_canvas(tokens, glass_name)
        fg = parse_hex(tokens.get(text_name, ""))
        assert over_canvas is not None, f"{theme}: 无法合成 --{glass_name}"
        assert fg is not None, f"{theme}: 缺少 --{text_name}"

        ratio = contrast(fg, over_canvas)
        # 列级玻璃的要求来自 GLASS_TIERS（4.5），浮层同理。
        assert ratio >= need, (
            f"{theme}: --{text_name} on --{glass_name} 叠画布 = {ratio:.2f} < {need}"
            f" ({label})"
        )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    @pytest.mark.parametrize("glass_name,label,need", GLASS_TIERS)
    def test_primary_text_survives_image_behind(self, css, theme, glass_name, label, need):
        """玻璃下面压着最坏端照片（含压色层）时，主文字仍须 AA。"""
        tokens = parse_theme(css, theme)
        glass = parse_color(tokens.get(glass_name, ""))
        fg = parse_hex(tokens.get("text-1", ""))
        assert glass is not None and fg is not None
        ratio = contrast(fg, composite(glass, image_backdrop(theme)))
        assert ratio >= need, (
            f"{theme}: text-1 on {glass_name} 叠图片 = {ratio:.2f} < {need} ({label})"
        )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    @pytest.mark.parametrize("glass_name,label,need", GLASS_TIERS)
    def test_secondary_text_survives_image_behind(self, css, theme, glass_name, label, need):
        """次级文字压在图片上按 WCAG 大字/UI 下限 3.0:1。"""
        tokens = parse_theme(css, theme)
        glass = parse_color(tokens.get(glass_name, ""))
        assert glass is not None
        over_worst = composite(glass, image_backdrop(theme))

        fg2 = parse_hex(tokens.get("text-2", ""))
        assert fg2 is not None
        r2 = contrast(fg2, over_worst)
        assert r2 >= NOT_TEXT_FLOOR, (
            f"{theme}: text-2 on {glass_name} 叠图片 = {r2:.2f} < {NOT_TEXT_FLOOR}"
        )

    def test_check_glass_helper_reports_no_problems(self, css):
        """check_glass 是给命令行用的同一套逻辑，它也必须报全绿。"""
        assert check_glass(css) == []


class TestImageTintContract:
    """自定义壁纸的压色层必须够厚，否则薄玻璃上的文字在极端照片前失效。

    `backgroundManager.applyTint()` 给自定义照片保留一层 `--ambient-tint`。
    这组测试把「这层多厚才够」钉成可执行的事实，防止有人为了「让壁纸更清楚」
    把它调回 transparent —— 那会让顶栏/侧栏的次级文字在黑白照片前掉到
    1.5~1.8:1（check_contrast 用中位灰时永远测不出来）。
    """

    def test_tint_matches_runtime(self):
        """校验里的压色参数必须和 backgroundManager 实际写的一致（50%）。"""
        assert IMAGE_TINT_ALPHA == 0.50, (
            f"IMAGE_TINT_ALPHA={IMAGE_TINT_ALPHA} 与 applyTint() 的 50% 不一致；"
            "改一处要同步另一处"
        )

    def test_tint_colors_match_theme_bg(self, css):
        """压色用的是 --bg，校验里的常量必须等于主题 --bg。"""
        for theme in ("light", "dark"):
            tokens = parse_theme(css, theme)
            bg = parse_hex(tokens.get("bg", ""))
            assert bg is not None, f"{theme}: 缺少 --bg"
            assert bg == IMAGE_TINT_HEX[theme], (
                f"{theme}: IMAGE_TINT_HEX={IMAGE_TINT_HEX[theme]} ≠ --bg={bg}；"
                "theme-liquid.css 改了底色要同步 check_contrast"
            )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_worst_backdrop_is_the_true_extreme(self, theme):
        """最坏底必须是该主题的极端端，而不是中位灰。"""
        expected = (255, 255, 255) if theme == "dark" else (0, 0, 0)
        assert worst_backdrop(theme) == expected

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_image_backdrop_is_pulled_toward_canvas(self, theme):
        """压色后玻璃看到的底色应比原始最坏端更接近画布色（而不是更远）。"""
        raw = worst_backdrop(theme)
        tinted = image_backdrop(theme)
        tint = IMAGE_TINT_HEX[theme]
        # 每个通道都应向 tint 靠拢
        for i in range(3):
            assert abs(tinted[i] - tint[i]) < abs(raw[i] - tint[i]), (
                f"{theme}: image_backdrop {tinted} 没有向画布色 {tint} 靠拢"
            )


class TestTertiaryTextException:
    """三级文字：保留设计原色后的**已知、已接受的 AA 例外**。

    `--text-3` 用于时间戳、元信息这类可以有但不必抢眼的文字。这一版
    颜色实测在表面上是 2.5~3.3:1，低于 AA 正文的 4.5:1 —— 这是产品
    选择（保留 GPT 原色），不是疏忽。

    所以这里不假装它达标，而是把例外钉成三条可执行的事实：

      1. 它确实低于 AA —— 哪天调色把它提上 4.5，这个用例会红，提醒我们
         删掉这条例外，而不是悄悄留着；
      2. 它不能继续往下掉（下限 2.9，实测最低 2.93）；
      3. 层级不能塌：text-3 必须在每一个表面上都明显弱于 text-2。
    """

    SURFACES = ("surface", "surface-2", "bg")
    AA = 4.5
    FLOOR = 2.9

    @pytest.mark.parametrize("theme", ["light", "dark"])
    @pytest.mark.parametrize("bg", SURFACES)
    def test_tertiary_is_a_documented_exception(self, css, theme, bg):
        tokens = parse_theme(css, theme)
        t3 = parse_hex(tokens.get("text-3", ""))
        t2 = parse_hex(tokens.get("text-2", ""))
        background = parse_hex(tokens.get(bg, ""))
        assert t3 and t2 and background, f"{theme}/{bg}: 缺少 token"

        ratio = contrast(t3, background)
        assert ratio < self.AA, (
            f"{theme}: text-3 on {bg} 已达 {ratio:.2f}:1（≥ AA）。"
            "好现象 —— 请把 text-3 加回 PAIRS 并删除这条例外测试"
        )
        assert ratio >= self.FLOOR, (
            f"{theme}: text-3 on {bg} 掉到 {ratio:.2f}:1（< {self.FLOOR}）—— "
            "连既有的层级下限都没有了"
        )
        assert ratio < contrast(t2, background), (
            f"{theme}: text-3 不比 text-2 弱（{ratio:.2f} vs "
            f"{contrast(t2, background):.2f}），三级层级塌陷"
        )


class TestChromeLayerUsage:
    """薄玻璃（alpha 0.48 / 0.55）上不布置三级文字。

    `--text-3` 只有约 3:1，在薄玻璃叠图片的极端情况下会更低。把「组件
    不这么用」变成可执行的检查：常驻 chrome（顶栏、底栏、外壳、状态栏）
    不得引用 --text-3。将来谁在 chrome 上加灰色元信息，这组测试会红，
    提醒他先确认那一层的底、或改用 text-2。
    """

    CHROME = [
        "components/TopBar.tsx",
        "components/Composer.tsx",
        "components/settings/SettingsModal.tsx",
        "components/StateDrawer.tsx",
    ]

    @pytest.mark.parametrize("rel", CHROME)
    def test_chrome_does_not_use_tertiary_text(self, rel):
        src = (ROOT / "webui" / "frontend" / "src" / rel).read_text(encoding="utf-8")
        assert "var(--text-3)" not in src, (
            f"{rel} 在薄玻璃层使用了 --text-3；"
            "三级文字压图片只有 3.0:1 以下的风险，请改用 text-2 或加厚玻璃"
        )


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



class TestColumnGlassLadder:
    """四层景深：L1 辅助栏一层膜，L2 主舞台另一层膜。

    历史契约（蓝→紫色相阶梯）已被新设计取代 —— 现在是暖瓷白 /
    黑曜石岩灰，四列**不该**再靠色相区分。区分它们的是三件事：
    谁更实（alpha）、谁更有投影（elev）、谁被留白隔开（layout）。

    所以这组测试守的是新契约：

      1. L1 三列（nav / list / aside）共用同一层中性膜 ——
         同层级的表面必须同材质，否则界面读成三块不同的板；
      2. L2 主舞台**合成后**必须比 L1 更亮 —— 两档玻璃色膜相同，
         亮度差全部来自 alpha，所以要比屏幕上的合成色；
      3. alpha 上 L1 < L2：辅助栏更透、主舞台更实；
      4. 冷暖方向一致：浅色 R≥B（暖），深色 B≥R（冷）——
         防的是「暖瓷白里混进一撮蓝」这类跑色，对比度测不出来，
         但整页会立刻显脏；
      5. 减弱透明模式的兜底实色必须等于合成色，不能退回 --bg。
    """

    L1 = ("glass-nav", "glass-list", "glass-aside")

    AMBIENT_OF = {
        "nav": "ambient-a",      # 左上
        "aside": "ambient-b",    # 右上
        "content": "ambient-c",  # 底部中偏右
        "list": "ambient-d",     # 左下
    }

    @staticmethod
    def _rel_lum(rgb: tuple[float, float, float]) -> float:
        """感知明度（0~100）。用亮度权重而不是 HSL 明度。

        HSL 的 (hi+lo)/2 对深色几乎不敏感：深色四列合成色 HSL 明度差
        1.4~3.0，换成感知明度后只剩零点几，正是「测试全绿、肉眼塌了」的由来。
        """
        r, g, b = rgb
        return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 * 100

    def _composite(self, css: str, theme: str, name: str) -> tuple[float, float, float]:
        """玻璃叠在它**自己脚下那块氛围**上的合成色 —— 屏幕上真正看到的颜色。

        这是本轮配色的唯一模型：`屏幕色 = alpha·玻璃 + (1−alpha)·氛围`。
        只算玻璃自身色是没意义的 —— 同一层的玻璃色恒等于一个中性色，
        任何基于它的断言都会「全绿而肉眼没变化」。
        """
        tokens = parse_theme(css, theme)
        glass = parse_color(tokens.get(name, ""))
        assert glass is not None, f"{theme}: 无法解析 --{name}"
        amb_name = self.AMBIENT_OF[name.split("-", 1)[1]]
        amb = parse_color(tokens.get(amb_name, ""))
        assert amb is not None, f"{theme}: 无法解析 --{amb_name}（四列的氛围色）"
        (g_rgb, alpha), (a_rgb, _) = glass, amb
        return tuple(alpha * g_rgb[i] + (1 - alpha) * a_rgb[i] for i in range(3))

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
    def test_l1_columns_share_one_film(self, css, theme):
        """L1 三列必须同材质：它们承担的是同一层级的信息（导航/列表/状态）。"""
        tokens = parse_theme(css, theme)
        seen = {}
        for name in self.L1:
            parsed = parse_color(tokens.get(name, ""))
            assert parsed is not None, f"{theme}: 无法解析 --{name}"
            seen[name] = tuple(round(c) for c in parsed[0])
        assert len(set(seen.values())) == 1, (
            f"{theme}: L1 三列的玻璃色膜不一致：{seen} —— "
            "同一层级不同材质会读成三块拼贴的板"
        )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_stage_reads_brighter_than_l1(self, css, theme):
        """L2 主舞台**看上去**必须比 L1 亮 —— 比合成色，不比玻璃自身色。

        这一版的 L1 与 L2 玻璃色膜都是同一种白/深灰，区别只在 alpha：
        舞台更实，所以叠在同一块画布上之后更亮。只比玻璃自身 RGB 会让
        这条永远失败（两档都是 #fff），比的必须是屏幕上真正看到的颜色。
        """
        tokens = parse_theme(css, theme)
        stage = glass_over_canvas(tokens, "glass-content")
        assert stage is not None
        stage_lum = self._rel_lum(stage)
        for name in self.L1:
            l1 = glass_over_canvas(tokens, name)
            assert l1 is not None, f"{theme}: 无法合成 --{name}"
            assert stage_lum > self._rel_lum(l1), (
                f"{theme}: --glass-content 合成色不比 --{name} 亮 "
                f"({stage_lum:.1f} vs {self._rel_lum(l1):.1f})，"
                "主舞台会失去视觉焦点"
            )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_alpha_ladder_puts_stage_on_top(self, css, theme):
        """辅助栏更透、主舞台更实。"""
        tokens = parse_theme(css, theme)
        stage = parse_color(tokens.get("glass-content", ""))
        assert stage is not None
        for name in self.L1:
            l1 = parse_color(tokens.get(name, ""))
            assert l1 is not None
            assert stage[1] > l1[1], (
                f"{theme}: --glass-content alpha={stage[1]} 不高于 --{name} "
                f"alpha={l1[1]}，主舞台会比辅助栏还透"
            )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_color_temperature_is_consistent(self, css, theme):
        """整页只允许一个冷暖方向：浅色偏暖（R≥B），深色偏冷（B≥R）。

        这条抓的是色相跑偏 —— 例如往暖白玻璃里掺一点冷蓝，
        对比度全部达标，但整页会读成「脏灰」。
        """
        for name in ("glass-nav", "glass-aside", "glass-list", "glass-content"):
            comp = self._composite(css, theme, name)
            r, _g, b = (round(c) for c in comp)
            if theme == "light":
                assert r >= b, f"light: --{name} 合成色偏冷 (R{r} < B{b})"
            else:
                assert b >= r, f"dark: --{name} 合成色偏暖 (B{b} < R{r})"

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
