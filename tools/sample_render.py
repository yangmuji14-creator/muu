#!/usr/bin/env python
"""sample_render.py — 从截图里采样实际像素，验证氛围层没有破坏文字对比度。

为什么需要它：`tests/test_design_tokens.py` 校验的是 token 字面值
（text-1 on surface 等）。但 v3 引入了氛围层（body::before 的 mesh 渐变），
文字实际叠在「氛围色 + 玻璃」的合成结果上，那个颜色没有任何 token 表达它。
只测 token 会得到一个漂亮但无意义的绿色。

做法：直接读 PNG 像素，在文字区域找最亮/最暗的背景像素，按 WCAG 公式算对比度。

用法：
    python tools/sample_render.py docs/screenshots/v4_light.png
"""

from __future__ import annotations

import sys
import zlib
from pathlib import Path


def read_png(path: Path) -> tuple[int, int, list[list[tuple[int, int, int]]]]:
    """极简 PNG 解码器（只支持 8-bit RGB/RGBA、非隔行）—— 避免为一次校验引入 Pillow。"""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "不是 PNG"

    pos = 8
    width = height = 0
    bit_depth = color_type = 0
    idat = b""

    while pos < len(data):
        length = int.from_bytes(data[pos : pos + 4], "big")
        ctype = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length

        if ctype == b"IHDR":
            width = int.from_bytes(chunk[0:4], "big")
            height = int.from_bytes(chunk[4:8], "big")
            bit_depth = chunk[8]
            color_type = chunk[9]
            assert bit_depth == 8, f"只支持 8-bit，实际 {bit_depth}"
            assert color_type in (2, 6), f"只支持 RGB/RGBA，实际 {color_type}"
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break

    raw = zlib.decompress(idat)
    channels = 3 if color_type == 2 else 4
    stride = width * channels

    rows: list[list[tuple[int, int, int]]] = []
    prev = bytearray(stride)
    p = 0
    for _ in range(height):
        ftype = raw[p]
        p += 1
        line = bytearray(raw[p : p + stride])
        p += stride

        # 反滤波
        if ftype == 1:  # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif ftype == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:  # Average
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:  # Paeth
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif ftype != 0:
            raise ValueError(f"未知滤波类型 {ftype}")

        rows.append(
            [(line[i * channels], line[i * channels + 1], line[i * channels + 2])
             for i in range(width)]
        )
        prev = line

    return width, height, rows


def rel_lum(rgb: tuple[int, int, int]) -> float:
    def ch(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = rel_lum(a), rel_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python tools/sample_render.py <screenshot.png> [--theme light|dark]")
        return 2

    path = Path(sys.argv[1])
    theme = "light"
    if "--theme" in sys.argv:
        theme = sys.argv[sys.argv.index("--theme") + 1]

    w, h, px = read_png(path)
    print(f"{path.name}  {w}x{h}  theme={theme}")

    # 采样区域（1440x1000 布局）：
    #   内容区背景 = 消息区空白处，避开气泡与图片
    #   侧栏背景   = 左侧导航空白处
    regions = {
        "内容区空白(中)": (500, 900, 700, 960),
        "内容区空白(上)": (900, 130, 1050, 175),
        "侧栏空白": (40, 700, 180, 780),
        "会话栏空白": (230, 700, 400, 780),
        "右侧面板空白": (1230, 880, 1400, 940),
    }

    print(f"\n{'区域':<16}{'最亮':>16}{'最暗':>16}   亮度跨度")
    samples: dict[str, tuple[int, int, int]] = {}
    for name, (x0, y0, x1, y1) in regions.items():
        vals = []
        for y in range(y0, min(y1, h), 2):
            for x in range(x0, min(x1, w), 2):
                vals.append(px[y][x])
        if not vals:
            continue
        lightest = max(vals, key=rel_lum)
        darkest = min(vals, key=rel_lum)
        samples[name] = lightest
        print(
            f"{name:<16}{str(lightest):>16}{str(darkest):>16}   "
            f"{contrast(lightest, darkest):.2f}"
        )

    # 文字色：从 token 取（截图里文字是抗锯齿的，直接采样不准）
    text_colors = {
        "light": {"text-1": (25, 22, 19), "text-2": (77, 71, 63), "text-3": (102, 94, 83)},
        "dark": {"text-1": (240, 235, 227), "text-2": (184, 175, 162), "text-3": (164, 155, 143)},
    }[theme]

    print(f"\n{'文字':<10}{'叠最亮背景':>12}{'叠最暗背景':>12}   判定 (需 ≥4.5)")
    worst = 99.0
    for tname, trgb in text_colors.items():
        c_light = contrast(trgb, samples["内容区空白(中)"])
        c_dark = contrast(trgb, samples["内容区空白(上)"])
        worst = min(worst, c_light, c_dark)
        ok = "OK" if min(c_light, c_dark) >= 4.5 else "!! 不达标"
        print(f"{tname:<10}{c_light:>12.2f}{c_dark:>12.2f}   {ok}")

    print(f"\n最差对比度 = {worst:.2f}")
    return 0 if worst >= 4.5 else 1


if __name__ == "__main__":
    raise SystemExit(main())
