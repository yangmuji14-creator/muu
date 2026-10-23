#!/usr/bin/env python
"""measure_ambient.py — 量化「氛围层透过玻璃后还剩多少」。

为什么需要它：v3 加了氛围层，但它是否可见不能靠肉眼看截图判断 ——
我在第一版就误判过一次（alpha 0.5 的色团被 0.62 的玻璃稀释后，
数学上存在、视觉上不存在）。这个脚本直接读像素，输出一个可比较的数字。

指标定义：
  取内容区的「纯背景像素」（排除文字、图片、气泡等有色块），
  计算它们在 CIELAB 空间的 ΔE 跨度。ΔE < 3 人眼基本看不出，
  3~6 是「隐约有层次」，> 6 是「明确可见的渐变」。

用法：
    python tools/measure_ambient.py <screenshot.png> [--region x0,y0,x1,y1]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sample_render import read_png  # noqa: E402


def rgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    def lin(c: float) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(float(c)) for c in rgb)
    x = r * 0.4124 + g * 0.3576 + b * 0.1805
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = r * 0.0193 + g * 0.1192 + b * 0.9505

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x / 0.95047), f(y / 1.0), f(z / 1.08883)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def is_background(rgb: tuple[int, int, int]) -> bool:
    """判定「这是背景色而不是文字/图片/色块」。

    背景在这个设计系统里永远是高明度低饱和的暖白系：
      - 三通道都 > 200（排除文字、图标、深色块）
      - 通道极差 < 40（排除彩色气泡、图片里的红蓝块）
    """
    r, g, b = rgb
    if min(rgb) <= 200:
        return False
    if max(rgb) - min(rgb) >= 40:
        return False
    return True


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python tools/measure_ambient.py <screenshot.png> [--region x0,y0,x1,y1]")
        return 2

    path = Path(sys.argv[1])
    w, h, px = read_png(path)

    region = None
    if "--region" in sys.argv:
        raw = sys.argv[sys.argv.index("--region") + 1]
        region = tuple(int(v) for v in raw.split(","))
    else:
        # 默认取消息区（1440 布局下 520..1040），避开左右两栏的 chrome
        region = (520, 20, 1040, min(h - 100, 880))

    x0, y0, x1, y1 = region
    labs: list[tuple[float, float, float]] = []
    rgbs: list[tuple[int, int, int]] = []

    for y in range(y0, min(y1, h), 3):
        for x in range(x0, min(x1, w), 3):
            rgb = px[y][x]
            if is_background(rgb):
                rgbs.append(rgb)
                labs.append(rgb_to_lab(rgb))

    if not labs:
        print("该区域没有采样到背景像素（可能全被内容覆盖）")
        return 1

    # 最远点对（近似）：用质心到最远点 × 2 估算跨度
    n = len(labs)
    cx = sum(p[0] for p in labs) / n
    cy = sum(p[1] for p in labs) / n
    cz = sum(p[2] for p in labs) / n
    centroid = (cx, cy, cz)
    max_d = max(delta_e(centroid, p) for p in labs)
    spread = max_d * 2

    print(f"{path.name}  区域 {region}  背景像素 {n} 个")
    print(f"  质心 Lab = ({cx:.1f}, {cy:.1f}, {cz:.1f})")
    print(f"  最大偏离 = {max_d:.2f}   →  ΔE 跨度 ≈ {spread:.2f}")

    if spread < 3:
        verdict = "不可见 —— 玻璃底下等于纯色，磨砂效果不会成立"
    elif spread < 6:
        verdict = "隐约可见 —— 有层次但需要仔细看"
    elif spread < 12:
        verdict = "明确可见 —— 能看出渐变与光感"
    else:
        verdict = "强烈 —— 注意是否抢了文字的注意力"
    print(f"  判定: {verdict}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
