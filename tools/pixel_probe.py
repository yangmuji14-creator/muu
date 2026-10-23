#!/usr/bin/env python
"""pixel_probe.py — 沿一条线打印像素颜色，用来定位「哪一层把颜色吃掉了」。

背景：氛围层加了三轮，截图看着还是白的。靠肉眼看截图无法判断
到底是「氛围层没渲染」「被某层不透明背景盖住」还是「玻璃 alpha 太高」。
这个脚本把一行像素全打出来，谁在哪一段变白一目了然。

用法:
    python tools/pixel_probe.py <png> --y 500 --x 0,1440,40
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sample_render import read_png  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python tools/pixel_probe.py <png> --y 500 --x 0,1440,40")
        return 2
    path = Path(sys.argv[1])
    w, h, px = read_png(path)

    y = int(sys.argv[sys.argv.index("--y") + 1]) if "--y" in sys.argv else h // 2
    if "--x" in sys.argv:
        x0, x1, step = (int(v) for v in sys.argv[sys.argv.index("--x") + 1].split(","))
    else:
        x0, x1, step = 0, w, 60

    print(f"{path.name}  {w}x{h}  y={y}")
    for x in range(x0, min(x1, w), step):
        r, g, b = px[y][x]
        # 用 R-G 差值当「有没有暖色」的探针，B-R 当「有没有冷色」
        print(f"  x={x:5d}  rgb({r:3d},{g:3d},{b:3d})  R-G={r-g:+4d}  B-R={b-r:+4d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
