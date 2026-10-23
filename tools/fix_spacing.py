"""把残留的 sub-4px 硬编码间距换成光学校正 token。

背景：视觉整改的验收标准里有一条「硬编码 gap/padding/margin 必须为 0」。
但 4px 节奏覆盖不到 1~3px 这一档 —— chip 内边距、图标-文字缝、基线微调
都真实落在这里。直接套 4px 会把小标签撑成药丸。

所以先补一层 `--optical-*` token（见 tokens.css），再把散落的数字换掉。
这个脚本只做**机械替换**：数字 → 最接近的 token，且要求语义等价。

只替换纯数字值；`padding: 1px 7px` 这种多值写法逐项映射。
已经用 var() 的、以及 settings-base.css 里的既有例外，一律不碰。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path("webui/frontend/src")

# 数值 → token。只收 tokens.css 里真实定义过的档位。
MAP = {
    1: "--hair",
    2: "--optical-2",
    3: "--optical-3",
    4: "--optical-4",
    5: "--optical-5",
    6: "--optical-6",
    7: "--optical-7",
    9: "--optical-9",
    10: "--optical-10",
}

# 只动这三个属性。其它属性（width/height/top 等）的 px 有各自语义，不动。
PROP = re.compile(r"\b(gap|padding|margin)((?:-[a-z]+)*)\s*:\s*([^;{}]+);")

# 一个值里可能有多段: "1px 7px" / "6px 0 0" / "2px var(--space-2)"
PART = re.compile(r"(?<![\w.-])(\d+)px")


def convert_value(raw: str) -> tuple[str, int]:
    """把一段声明值里的 px 换成 token，返回 (新值, 替换数)。"""
    hits = 0

    def sub(m: re.Match[str]) -> str:
        nonlocal hits
        n = int(m.group(1))
        tok = MAP.get(n)
        if not tok:
            return m.group(0)  # 8px 及以上走 --space-*，不在这里处理
        hits += 1
        return f"var({tok})"

    return PART.sub(sub, raw), hits


def process(path: Path) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    total = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal total
        new_val, hits = convert_value(m.group(3))
        if hits == 0:
            return m.group(0)
        total += hits
        return f"{m.group(1)}{m.group(2)}: {new_val.strip()};"

    out = PROP.sub(repl, text)
    if total:
        path.write_text(out, encoding="utf-8")
    return total, out.count("var(--optical-") + out.count("var(--hair)")


def main() -> int:
    targets = [
        p
        for p in ROOT.rglob("*")
        if p.suffix in {".svelte", ".css", ".js"}
        and p.name != "settings-base.css"  # 既有例外，见方案文档 2.7
        and p.name != "tokens.css"  # token 定义本身
    ]
    grand = 0
    changed = 0
    for p in sorted(targets):
        n, _ = process(p)
        if n:
            changed += 1
            grand += n
            print(f"  {p.as_posix()}: {n}")
    print(f"\n共替换 {grand} 处，涉及 {changed} 个文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
