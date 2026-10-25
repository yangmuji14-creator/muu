#!/usr/bin/env python3
"""design_palette.py — 色板求解 / 验收台。

为什么要一个求解器而不是手挑 #hex:
    用户看到的列颜色不是 `--ambient-*`, 也不是 `--glass-*`, 而是
        comp = alpha·glass + (1−alpha)·ambient
    再叠 backdrop-filter 的 blur/saturate。手挑 hex 时人脑算的是 ambient,
    屏幕显示的是 comp —— 两者在 alpha 0.5 处差了一倍。这就是「改了半天
    看不出变化」的机械原因。所以这里反过来解: 先定屏幕上该出现什么色
    (色相 / 彩度 / 感知明度), 再反解 ambient, 再反解兜底实色。

      comp  →  amb = (comp − alpha·glass) / (1 − alpha)

    反解可能出界 (amb 通道 <0 或 >255): 那是「这个色在物理上做不到」,
    不是浮点误差。出界时静默夹取, 但必须打印被压了多少 —— 压得多说明
    目标本身不现实, 得改目标而不是改色值。

用法:
    .venv/Scripts/python.exe tools/design_palette.py
    .venv/Scripts/python.exe tools/design_palette.py --emit   # 打印 CSS
"""
from __future__ import annotations

import argparse
import colorsys
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from check_contrast import (  # noqa: E402
    PAIRS,
    WORST_BG,
    composite,
    contrast,
    parse_color,
    parse_hex,
)

# ============================================================================
# 设计意图 —— 唯一需要手改的地方
# ============================================================================

# 每列的目标**屏幕色**: (色相, 彩度HSL, 感知明度 rel_lum)
#
# 三个数字对应三件不同的事, 互不牵制:
#   hue  —— 这一列在蓝→紫扫描线上的位置。侧栏最蓝(214)、右栏最紫(288)。
#   sat  —— 这块颜色有多"有颜色"。原值是 ambient S=86% (霓虹), 这里直接
#           降到位: 浅色 30~42% / 深色 22~30%。彩度是"难看"的主要来源。
#   lum  —— 感知明度 (0~100, 亮度加权, 不是 HSL 的 L)。按"谁该退后"排。
#           原实现 light 四列 L69~79, 差 10 点但被高饱和淹没; 拉开到 13 点。
COLUMN = {
    "light": {
        "nav":     (214.0, 0.42, 74.0),   # 雾蓝, 最暗所以最艳
        "aside":   (288.0, 0.38, 79.0),   # 雾紫, 次级信息
        "list":    (248.0, 0.34, 83.0),   # 雾靛, 可扫读的一层
        "content": (266.0, 0.28, 87.5),   # 雾紫罗兰, 正文"纸", 最亮最淡
    },
    "dark": {
        # 深色下正文最暗: 正文是纸, 纸在暗房里比墙更暗
        "content": (266.0, 0.26,  9.0),
        "nav":     (214.0, 0.40, 11.0),
        "aside":   (288.0, 0.34, 13.5),
        "list":    (248.0, 0.30, 16.0),
    },
}

# 玻璃: 中性 (四列必须完全相同 —— tests 的 test_glass_itself_is_neutral)。
# 颜色不再是纯白 250 —— 降到 243~247 给反解留出 7~10 个通道的余量,
# 否则像 nav(H214) 这种低红通道色相会被 250 的玻璃直接夹死, 色出不来。
GLASS_RGB = {"light": (246, 248, 252), "dark": (11, 13, 20)}
GLASS_ALPHA = {
    "light": {"1": 0.66, "2": 0.74, "3": 0.82, "col": 0.60},
    "dark":  {"1": 0.74, "2": 0.81, "3": 0.87, "col": 0.70},
}

# 其余色值 —— 手选。文字层级是本轮第二大修改:
#   text-2 / text-3 原来只差 3.7 个明度点 (对比度比 0.871 = 塌陷),
#   现在压到 0.66 —— 三级文字必须能一眼分出三档。
LIGHT = {
    "bg": "#e4e8ef",
    "surface": "#fafbfd",
    "surface-2": "#edf0f5",
    "surface-3": "#dee3eb",
    "surface-inset": "#f1f4f8",
    "text-1": "#0d131b",
    "text-2": "#2c3745",
    "text-3": "#434e5c",
    "text-inverse": "#f7f9fc",
    "border": "#ccd3de",
    "border-strong": "#657287",
    "accent": "#245b9c",
    "accent-strong": "#17417a",
    "accent-soft": "#e3ecf7",
    "on-accent": "#ffffff",
    "success": "#2a6450",
    "warning": "#73511c",
    "error": "#9c382c",
    "info": "#245b9c",
    "on-success": "#ffffff",
    "on-warning": "#ffffff",
    "on-error": "#ffffff",
}

DARK = {
    "bg": "#12161c",
    "surface": "#191e25",
    "surface-2": "#222832",
    "surface-3": "#2d3440",
    "surface-inset": "#0d1015",
    "text-1": "#e9edf3",
    "text-2": "#c4cdd9",
    "text-3": "#9aa4b1",
    "text-inverse": "#12161c",
    "border": "#333b46",
    "border-strong": "#6b7789",
    "accent": "#8fb6e6",
    "accent-strong": "#b6d0ee",
    "accent-soft": "#1b2a3c",
    "on-accent": "#0b0f14",
    "success": "#8bc9b2",
    "warning": "#d5b678",
    "error": "#e5948b",
    "info": "#8fb6e6",
    "on-success": "#0b0f14",
    "on-warning": "#0b0f14",
    "on-error": "#0b0f14",
}

AMBIENT_OF = {"nav": "ambient-a", "aside": "ambient-b",
              "content": "ambient-c", "list": "ambient-d"}
LADDER = {
    "light": ["nav", "aside", "list", "content"],
    "dark": ["content", "nav", "aside", "list"],
}
MIN_ALPHA = {"light": 0.50, "dark": 0.66}
MIN_GAP = 1.2
MIN_HUE_SPAN = 55.0
SPAN_NEED = {"light": 8.0, "dark": 4.5}
TOAST_PAIRS = [
    ("toast-success-text", "toast-success-bg", "成功"),
    ("toast-error-text", "toast-error-bg", "错误"),
    ("toast-info-text", "toast-info-bg", "信息"),
]


# ---------------------------------------------------------------------------
# 色彩数学
# ---------------------------------------------------------------------------

def rel_lum(c) -> float:
    """感知明度 0~100 —— 亮度加权, 对深色也敏感 (HSL 的 L 不是)。"""
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255 * 100


def hue_of(c) -> float:
    r, g, b = (max(0, min(255, round(v))) / 255 for v in c)
    h, _l, _s = colorsys.rgb_to_hls(r, g, b)
    return h * 360


def hsl_of(c):
    r, g, b = (max(0, min(255, round(v))) / 255 for v in c)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h * 360, s * 100, l * 100


def hx(c) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in c)


def make_comp(hue: float, sat: float, target_lum: float):
    """在给定色相/彩度下, 解出让感知明度 = target 的屏幕色。

    rel_lum 对通道是线性的, 所以在固定 hue+sat 的前提下, 只有 HSL 的 L
    一个自由度 —— 二分 L 即可, 不需要暴力扫 1000×100。
    """
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        r, g, b = colorsys.hls_to_rgb(hue / 360, mid, sat)
        c = (r * 255, g * 255, b * 255)
        if rel_lum(c) < target_lum:
            lo = mid
        else:
            hi = mid
    r, g, b = colorsys.hls_to_rgb(hue / 360, (lo + hi) / 2, sat)
    return (r * 255, g * 255, b * 255)


def invert_ambient(comp, glass, alpha):
    """comp = alpha·glass + (1−alpha)·amb  →  amb"""
    return tuple((comp[i] - alpha * glass[i]) / (1 - alpha) for i in range(3))


def solve_theme(theme: str):
    pal = dict(LIGHT if theme == "light" else DARK)
    glass = GLASS_RGB[theme]
    alphas = GLASS_ALPHA[theme]
    a_col = alphas["col"]

    print(f"  [{theme}] 反解 amb = (comp − {a_col}·glass) / {1 - a_col:.2f}")
    for col, (hue, sat, lum) in COLUMN[theme].items():
        comp = make_comp(hue, sat, lum)
        amb = invert_ambient(comp, glass, a_col)
        clipped = [i for i in range(3) if amb[i] < 0 or amb[i] > 255]
        amb_c = tuple(max(0, min(255, v)) for v in amb)
        # 夹取后重新合成, 看实际落到屏幕上是什么
        comp_real = tuple(a_col * glass[i] + (1 - a_col) * amb_c[i] for i in range(3))
        d_lum = rel_lum(comp_real) - lum
        d_hue = hue_of(comp_real) - hue
        flag = ""
        if clipped:
            flag = (f"  [!] 通道 {'/'.join('rgb'[i] for i in clipped)} 出界, "
                    f"夹取后 Δlum={d_lum:+.1f} Δhue={d_hue:+.1f}")
        print(f"    {col:<8} comp={hx(comp)} → amb={hx(amb_c)}  "
              f"实际 comp={hx(comp_real)}{flag}")
        pal[AMBIENT_OF[col]] = "rgba(%d, %d, %d, 1)" % tuple(round(v) for v in amb_c)

    gr, gg, gb = glass
    for k in "123":
        pal[f"glass-{k}"] = "rgba(%d, %d, %d, %.2f)" % (gr, gg, gb, alphas[k])
    for col in ("nav", "aside", "list", "content"):
        pal[f"glass-{col}"] = "rgba(%d, %d, %d, %.2f)" % (gr, gg, gb, a_col)
    pal["glass-0"] = ("rgba(9, 14, 21, 0.38)" if theme == "light"
                      else "rgba(0, 0, 0, 0.64)")
    return pal


# ---------------------------------------------------------------------------
# 验收
# ---------------------------------------------------------------------------

def verify(theme: str, pal: dict) -> list[str]:
    problems: list[str] = []
    print("\n" + "=" * 80)
    print(f"  THEME = {theme}")
    print("=" * 80)

    print("\n[1] WCAG AA 表面配对")
    print(f"   {'pair':<32}{'ratio':>8}{'need':>6}")
    for fg, bg, need, label in PAIRS:
        f, b = parse_hex(pal.get(fg, "")), parse_hex(pal.get(bg, ""))
        if f is None or b is None:
            problems.append(f"{theme}: 缺少 {fg}/{bg}")
            continue
        r = contrast(f, b)
        if r < need:
            problems.append(f"{theme}: {fg} on {bg} = {r:.2f} < {need} ({label})")
        print(f"   {fg + ' on ' + bg:<32}{r:>8.2f}{need:>6.1f}  "
              f"{'OK' if r >= need else 'FAIL'}")

    print("\n[2] 玻璃叠最坏底 (128,128,128) 上的文字")
    print(f"   {'tier':<16}{'alpha':>7}{'over':>10}   text-1  text-2  text-3")
    for tier in ("glass-1", "glass-2", "glass-3", "glass-nav", "glass-aside",
                 "glass-list", "glass-content"):
        g = parse_color(pal[tier])
        assert g is not None
        over = composite(g, WORST_BG)
        cells = []
        for t in ("text-1", "text-2", "text-3"):
            r = contrast(parse_hex(pal[t]), over)
            cells.append(r)
            if r < 4.5:
                problems.append(f"{theme}: {t} on {tier} 叠最坏底 = {r:.2f} < 4.5")
        if g[1] < MIN_ALPHA[theme]:
            problems.append(f"{theme}: {tier} alpha={g[1]} < {MIN_ALPHA[theme]}")
        print(f"   {tier:<16}{g[1]:>7.2f}{hx(over):>10}   "
              + "".join(f"{c:>7.2f}" for c in cells))

    alphas = [parse_color(pal[f"glass-{i}"])[1] for i in (1, 2, 3)]
    if alphas != sorted(alphas):
        problems.append(f"{theme}: 玻璃档位 alpha 未递增 {alphas}")
    cols = {tuple(round(v) for v in parse_color(pal[f"glass-{c}"])[0])
            for c in ("nav", "aside", "list", "content")}
    if len(cols) != 1:
        problems.append(f"{theme}: 四列玻璃不中性 {cols}")

    print("\n[3] 四列屏幕色: 明度阶梯 + 色相扫描")
    print(f"   {'col':<10}{'rel_lum':>9}{'hue':>8}{'sat%':>7}{'gap':>8}   comp")
    order = LADDER[theme]
    vals, hues, prev = [], {}, None
    for col in order:
        gr, a = parse_color(pal[f"glass-{col}"])
        am, _ = parse_color(pal[AMBIENT_OF[col]])
        comp = tuple(a * gr[i] + (1 - a) * am[i] for i in range(3))
        L, H, S, _L = rel_lum(comp), hue_of(comp), *hsl_of(comp)[1:]
        vals.append(L)
        hues[col] = H
        gap = "" if prev is None else f"{L - prev:.2f}"
        print(f"   {col:<10}{L:>9.2f}{H:>8.1f}{S:>7.1f}{gap:>8}   {hx(comp)}")
        prev = L
    gaps = [b - a for a, b in zip(vals, vals[1:])]
    span = vals[-1] - vals[0]
    print(f"   gaps={[round(g, 2) for g in gaps]}  span={span:.2f} "
          f"(need ≥{SPAN_NEED[theme]}, 每段 ≥{MIN_GAP})")
    for g_, n in zip(gaps, order[1:]):
        if g_ < MIN_GAP:
            problems.append(f"{theme}: {n} 相邻明度差 {g_:.2f} < {MIN_GAP}")
    if span < SPAN_NEED[theme]:
        problems.append(f"{theme}: 总跨度 {span:.2f} < {SPAN_NEED[theme]}")
    hspan = max(hues.values()) - min(hues.values())
    print(f"   hue span={hspan:.1f}° (need ≥{MIN_HUE_SPAN})  "
          f"{ {k: round(v) for k, v in hues.items()} }")
    if hspan < MIN_HUE_SPAN:
        problems.append(f"{theme}: 色相跨度 {hspan:.1f}° < {MIN_HUE_SPAN}°")
    if hues["nav"] != min(hues.values()):
        problems.append(f"{theme}: nav 不是最蓝 (H{round(hues['nav'])})")
    if hues["aside"] != max(hues.values()):
        problems.append(f"{theme}: aside 不是最紫 (H{round(hues['aside'])})")

    print("\n[4] 兜底实色 (--col-*-solid 必须 = 合成色)")
    for col in ("nav", "aside", "list", "content"):
        gr, a = parse_color(pal[f"glass-{col}"])
        am, _ = parse_color(pal[AMBIENT_OF[col]])
        comp = tuple(a * gr[i] + (1 - a) * am[i] for i in range(3))
        print(f"   --col-{col}-solid: {hx(comp)};")

    surf = parse_hex(pal["surface"])
    t = [contrast(parse_hex(pal[f"text-{i}"]), surf) for i in (1, 2, 3)]
    ratio = t[2] / t[1]
    print(f"\n[5] 文字层级  text-1 {t[0]:.2f} / text-2 {t[1]:.2f} / text-3 {t[2]:.2f}"
          f"   text-3÷text-2 = {ratio:.3f} "
          f"({'OK' if ratio <= 0.85 else 'FAIL 二三档塌陷'})")
    if ratio > 0.85:
        problems.append(f"{theme}: text-3/text-2 = {ratio:.2f} 塌陷 (>0.85)")

    print("\n[6] 氛围层彩度")
    sats = []
    for k in "abcd":
        h_, s_, l_ = hsl_of(parse_color(pal[f"ambient-{k}"])[0])
        sats.append(s_)
        print(f"   ambient-{k}  H={h_:6.1f}  S={s_:5.1f}%  L={l_:5.1f}%")
    avg = sum(sats) / 4
    print(f"   -> 平均饱和度 {avg:.1f}%  {'克制' if avg <= 65 else '仍偏艳'}")

    print("\n[7] Toast 状态配对 (token: toast-*-text on toast-*-bg)")
    # toast-bg 指向状态色, toast-*-text 指向 on-* —— 按 tokens.css Layer 3 的
    # 真实指向解析, 不要在这里再造一套命名规则。
    TOAST_MAP = {
        "成功": ("on-success", "success"),
        "错误": ("on-error", "error"),
        "信息": ("surface", "text-1"),   # toast-info-bg: var(--text-1)
    }
    for label, (fg_key, bg_key) in TOAST_MAP.items():
        f, b = parse_hex(pal[fg_key]), parse_hex(pal[bg_key])
        if f is None or b is None:
            problems.append(f"{theme}: toast {label} 解析失败 ({fg_key}/{bg_key})")
            continue
        r = contrast(f, b)
        if r < 4.5:
            problems.append(f"{theme}: toast {label} = {r:.2f} < 4.5")
        print(f"   {label:<6} {fg_key} on {bg_key:<10}{r:>8.2f}  "
              f"{'OK' if r >= 4.5 else 'FAIL'}")

    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", action="store_true")
    args = ap.parse_args()

    solved, problems = {}, []
    for theme in ("light", "dark"):
        print("=" * 80)
        solved[theme] = solve_theme(theme)
        problems += verify(theme, solved[theme])

    if args.emit:
        order = ["bg", "surface", "surface-2", "surface-3", "surface-inset",
                 "text-1", "text-2", "text-3", "text-inverse",
                 "border", "border-strong",
                 "accent", "accent-strong", "accent-soft", "on-accent",
                 "success", "warning", "error", "info",
                 "on-success", "on-warning", "on-error",
                 "ambient-a", "ambient-b", "ambient-c", "ambient-d",
                 "glass-0", "glass-1", "glass-2", "glass-3",
                 "glass-nav", "glass-aside", "glass-list", "glass-content"]
        for theme in ("light", "dark"):
            pal = solved[theme]
            print("\n" + "=" * 80)
            print(f"  EMIT [{theme}]")
            print("=" * 80)
            for k in order:
                print(f"  --{k}: {pal[k]};")
            for col in ("nav", "aside", "list", "content"):
                gr, a = parse_color(pal[f"glass-{col}"])
                am, _ = parse_color(pal[AMBIENT_OF[col]])
                comp = tuple(a * gr[i] + (1 - a) * am[i] for i in range(3))
                print(f"  --col-{col}-solid: {hx(comp)};")

    print("\n" + "=" * 80)
    if problems:
        print(f"  {len(problems)} 项不达标:")
        for p in problems:
            print("   - " + p)
        return 1
    print("  ALL PASS —— 可以写进 tokens.css")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
