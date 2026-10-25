#!/usr/bin/env python3
"""diagnose_palette.py — 配色体检: 把 tokens.css 里的颜色拉成 HSL / 对比度矩阵,
用数据说明「哪里难看」, 而不是靠感觉。

用法:
    .venv/Scripts/python.exe tools/diagnose_palette.py
    .venv/Scripts/python.exe tools/diagnose_palette.py --theme dark
"""
from __future__ import annotations

import argparse
import colorsys
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "webui" / "frontend" / "src" / "styles" / "tokens.css"

DECL_RE = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")


def parse_color(raw: str):
    """'#aabbcc' / 'rgba(1,2,3,.5)' / '#abc' -> (r,g,b,a) 或 None"""
    s = raw.strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{3,8})", s)
    if m:
        h = m.group(1)
        if len(h) == 3:
            r, g, b = (int(c * 2, 16) for c in h)
            return (r, g, b, 1.0)
        if len(h) == 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
        if len(h) == 8:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16),
                    int(h[6:8], 16) / 255.0)
        return None
    m = re.fullmatch(r"rgba?\(([^)]+)\)", s)
    if m:
        parts = [p.strip() for p in m.group(1).replace("/", " ").split(",")]
        if len(parts) >= 3:
            r, g, b = (int(float(p)) for p in parts[:3])
            a = float(parts[3]) if len(parts) > 3 else 1.0
            return (r, g, b, a)
    return None


def parse_theme(css: str, theme: str) -> dict[str, str]:
    """先铺 :root, 再用 [data-theme='x'] 覆盖"""
    vars_: dict[str, str] = {}
    blocks = []
    for m in re.finditer(r":root\s*\{([^}]*)\}", css):
        blocks.append(m.group(1))
    for m in re.finditer(r"\[data-theme=['\"]%s['\"]\]\s*\{([^}]*)\}" % theme, css):
        blocks.append(m.group(1))
    for body in blocks:
        for name, val in DECL_RE.findall(body):
            vars_[name] = val.strip()
    return vars_


def resolve(vars_: dict[str, str], val: str, depth: int = 8):
    """递归展开 var(--x)"""
    for _ in range(depth):
        m = re.search(r"var\(\s*(--[\w-]+)\s*\)", val)
        if not m:
            break
        name = m.group(1)
        if name not in vars_:
            return None
        val = val.replace(m.group(0), vars_[name])
    return parse_color(val)


def composite(fg, bg):
    r, g, b, a = fg
    br, bg_, bb, _ = bg
    return (round(r * a + br * (1 - a)),
            round(g * a + bg_ * (1 - a)),
            round(b * a + bb * (1 - a)), 1.0)


def lum(c) -> float:
    def ch(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def contrast(a, b) -> float:
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def hsl(c):
    h, l, s = colorsys.rgb_to_hls(c[0] / 255, c[1] / 255, c[2] / 255)
    return h * 360, s * 100, l * 100


def hexs(c) -> str:
    return "#%02x%02x%02x" % (c[0], c[1], c[2])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default=None, choices=["light", "dark"])
    args = ap.parse_args()

    css = TOKENS.read_text(encoding="utf-8")
    themes = [args.theme] if args.theme else ["light", "dark"]

    for theme in themes:
        v = parse_theme(css, theme)
        print("=" * 78)
        print(f"  THEME = {theme}")
        print("=" * 78)

        groups = [
            ("背景 / 表面层", ["--bg", "--surface", "--surface-2", "--surface-3",
                            "--surface-inset"]),
            ("文字层级", ["--text-1", "--text-2", "--text-3", "--text-inverse"]),
            ("边框", ["--border", "--border-strong"]),
            ("强调色", ["--accent", "--accent-strong", "--accent-soft", "--on-accent"]),
            ("状态色", ["--success", "--warning", "--error", "--info"]),
            ("氛围层", ["--ambient-a", "--ambient-b", "--ambient-c", "--ambient-d"]),
            ("列玻璃", ["--glass-nav", "--glass-aside", "--glass-list", "--glass-content"]),
        ]
        for title, names in groups:
            print(f"\n-- {title} " + "-" * (60 - len(title)))
            print(f"   {'token':<20}{'value':<26}{'hex':<10}{'H':>7}{'S%':>7}{'L%':>7}")
            for n in names:
                raw = v.get(n)
                if raw is None:
                    continue
                col = resolve(v, raw)
                if col is None:
                    print(f"   {n:<20}{raw[:24]:<26}(unresolved)")
                    continue
                h, s, l = hsl(col)
                short = raw if len(raw) <= 24 else raw[:21] + "..."
                print(f"   {n:<20}{short:<26}{hexs(col):<10}{h:>7.1f}{s:>7.1f}{l:>7.1f}")

        # 文字层级塌陷检测
        print(f"\n-- 文字层级区分度 " + "-" * 50)
        t2 = resolve(v, v.get("--text-2", ""))
        t3 = resolve(v, v.get("--text-3", ""))
        surf = resolve(v, v.get("--surface", ""))
        bg = resolve(v, v.get("--bg", ""))
        if t2 and t3 and surf:
            d = contrast(t3, surf) / contrast(t2, surf)
            print(f"   text-3 / text-2 对比度比 = {contrast(t3, surf):.2f} / "
                  f"{contrast(t2, surf):.2f} = {d:.3f}")
            print("   " + ("[!] 塌陷: 三级文字几乎无差别" if d > 0.85 else "[ok] 有区分"))

        # 表面层阶梯
        print(f"\n-- 表面层明度阶梯 " + "-" * 50)
        chain = ["--bg", "--surface-inset", "--surface", "--surface-2", "--surface-3"]
        prev = None
        for n in chain:
            col = resolve(v, v.get(n, ""))
            if col is None:
                continue
            _, s, l = hsl(col)
            gap = "" if prev is None else f"  ΔL={l - prev:+.1f}"
            print(f"   {n:<18} L={l:5.1f}%  S={s:5.1f}%{gap}")
            prev = l

        # 氛围层彩度检查
        print(f"\n-- 氛围层彩度/色相跨度 " + "-" * 46)
        amb = {}
        for k in "abcd":
            col = resolve(v, v.get(f"--ambient-{k}", ""))
            if col:
                h, s, l = hsl(col)
                amb[k] = (h, s, l)
                print(f"   ambient-{k}  H={h:6.1f}  S={s:5.1f}%  L={l:5.1f}%")
        if amb:
            hs = [x[0] for x in amb.values()]
            ss = [x[1] for x in amb.values()]
            print(f"   → 色相跨度 {max(hs) - min(hs):.1f}°   平均饱和度 "
                  f"{sum(ss) / len(ss):.1f}%  (S>80 = 墙面被染色)")

        # 前景 / 背景对比度全矩阵
        print(f"\n-- 对比度矩阵 " + "-" * 55)
        fgs = ["--text-1", "--text-2", "--text-3", "--accent", "--border-strong"]
        bgs = ["--surface", "--bg", "--surface-2", "--surface-3"]
        hdr = "".join(f"{b.replace('--', ''):>14}" for b in bgs)
        print(f"   {'':<16}{hdr}")
        for f in fgs:
            fc = resolve(v, v.get(f, ""))
            if fc is None:
                continue
            row = ""
            for b in bgs:
                bc = resolve(v, v.get(b, ""))
                if bc is None:
                    row += f"{'-':>14}"
                    continue
                c = contrast(fc, bc)
                mark = "" if c >= 4.5 else ("!" if c >= 3.0 else "x")
                row += f"{c:>12.2f}{mark:<2}"
            print(f"   {f.replace('--', ''):<16}{row}")
        print("   图例: 无标记 >=4.5 AA正文 | ! 3.0-4.5 仅大字/图形 | x <3.0 不合格")

        # 玻璃透明度
        print(f"\n-- 玻璃层通透度 " + "-" * 52)
        for n in ["--glass-1", "--glass-2", "--glass-3", "--glass-nav",
                  "--glass-aside", "--glass-list", "--glass-content"]:
            raw = v.get(n)
            key = n if raw else n.replace("--glass-", "--glass-")
            col = resolve(v, raw) if raw else None
            if col is None:
                continue
            print(f"   {n:<18} alpha={col[3]:.2f}  "
                  f"{'偏透(氛围色会透出)' if col[3] < 0.60 else '偏实'}")

        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
