"""measure_vitality.py — 「她像不像一个人」的五个数（优化方案第四部分）。

改之前先跑一遍存档——没有对照就没有证据。全部从本地数据计算，不联网、
不调模型、只读 data/ 与 logs/。

    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m tools.measure_vitality
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m tools.measure_vitality --save

五个数的现状（哪些现在算得出来，哪些算不了，都如实标注）：

1. **情绪→长度相关性**：assistant 消息的情绪强度 vs 回复字数。
   0.2.0 起有了输出约束（max_tokens 跟 energy），这个数应当 > 0.2；
   改前结构上必然 ≈ 0。
2. **emoji 覆盖率**：非中性情绪的 assistant 消息里带表情/颜文字的比例。
   0.2.0 前结构上必然 ≈ 100%（闸门就是那天加的），健康值 < 35%。
3. **自我指涉密度**：assistant 消息里「我 + 动词」开头的短句占比。
   她的念头宾语全部是"他"时这个数接近 0。
4. **心情→主动相关性**：proactive 触发时刻的 mood.valence 分布。
   0.2.0 起主动消息才存在，样本还少，如实报样本量。
5. **反应方差**（同一句话问十遍的两两相似度）——**本脚本算不了**：
   需要主动发同句探测，会消耗模型调用且打扰数据。列为人工项，
   建议换 key 后手动测一次并记录。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "companion.db"
CHAT_DIR = DATA_DIR / "chat_history"

EMOJI_RE = re.compile(
    r"[\U0001F000-\U0001FAFF\u2600-\u27BF]"   # emoji 区块
    r"|[(（][^()（）]{1,8}[)）]"                # 颜文字/括号表情
)
SELF_REF_RE = re.compile(r"^(我|人家|本[人大])")
MOOD_RE = re.compile(r'"mood":\s*"(\w+)"')
VALENCE_RE = re.compile(r'"valence":\s*(-?[\d.]+)')


def _iter_histories() -> list[tuple[str, list[dict]]]:
    """(来源名, 消息列表)。扫 chat_history 三个代次目录。"""
    out: list[tuple[str, list[dict]]] = []
    for path in sorted(CHAT_DIR.rglob("*.json")):
        if path.suffix != ".json" or path.name.endswith(".tmp"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        messages = data.get("messages", []) if isinstance(data, dict) else data
        if isinstance(messages, list) and messages:
            out.append((str(path.relative_to(CHAT_DIR)), messages))
    return out


def _assistant_msgs(messages: list[dict]) -> list[dict]:
    return [m for m in messages if m.get("role") == "assistant" and m.get("content")]


def _has_emoji(text: str) -> bool:
    return bool(EMOJI_RE.search(text))


def metric_emoji_coverage() -> dict:
    total, with_emoji = 0, 0
    per_source: dict[str, tuple[int, int]] = {}
    for name, messages in _iter_histories():
        s_total = s_hit = 0
        for m in _assistant_msgs(messages):
            s_total += 1
            if _has_emoji(m["content"]):
                s_hit += 1
        if s_total:
            total += s_total
            with_emoji += s_hit
            per_source[name] = (s_hit, s_total)
    rate = with_emoji / total if total else 0.0
    return {
        "metric": "emoji 覆盖率（assistant 消息带表情/颜文字比例）",
        "value": round(rate, 3),
        "healthy": "< 0.35",
        "sample": total,
        "per_source": {k: f"{h}/{t}" for k, (h, t) in per_source.items()},
    }


def metric_emotion_length_corr() -> dict:
    """情绪强度 vs 回复字数的皮尔逊相关。"""
    xs, ys = [], []
    for _name, messages in _iter_histories():
        for m in _assistant_msgs(messages):
            intensity = m.get("emotion_intensity")
            if intensity is None:
                continue
            xs.append(float(intensity))
            ys.append(len(str(m["content"])))
    n = min(len(xs), len(ys))
    if n < 10:
        return {
            "metric": "情绪→长度相关性（intensity vs 回复字数）",
            "value": None, "healthy": "> 0.2",
            "note": f"样本不足（{n} 条带情绪标注的 assistant 消息），暂无法计算",
        }
    mean_x, mean_y = sum(xs[:n]) / n, sum(ys[:n]) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs[:n], ys[:n]))
    var_x = sum((x - mean_x) ** 2 for x in xs[:n])
    var_y = sum((y - mean_y) ** 2 for y in ys[:n])
    if var_x == 0 or var_y == 0:
        corr = 0.0
    else:
        corr = cov / math.sqrt(var_x * var_y)
    return {
        "metric": "情绪→长度相关性（intensity vs 回复字数）",
        "value": round(corr, 3), "healthy": "> 0.2", "sample": n,
    }


def metric_self_reference() -> dict:
    total, self_start = 0, 0
    for _name, messages in _iter_histories():
        for m in _assistant_msgs(messages):
            for line in str(m["content"]).split("\n"):
                line = line.strip()
                if len(line) < 2:
                    continue
                total += 1
                if SELF_REF_RE.match(line):
                    self_start += 1
    rate = self_start / total if total else 0.0
    return {
        "metric": "自我指涉密度（以「我」开头的句子占比）",
        "value": round(rate, 3), "healthy": "> 0.05 且随情绪波动",
        "sample": total,
        "note": "代理指标：只算句首「我」。文献口径是整句自指，此处从宽",
    }


def metric_proactive_mood() -> dict:
    """主动消息时刻的心情分布（0.2.0 起才有数据，样本会很少）。"""
    if not DB_PATH.exists():
        return {"metric": "心情→主动相关性", "value": None,
                "note": "数据库不存在"}
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT state FROM moods"
        ).fetchall()
    finally:
        conn.close()
    moods = []
    for (state_json,) in rows:
        try:
            state = json.loads(state_json)
        except json.JSONDecodeError:
            continue
        moods.append((state.get("mood", "?"), state.get("valence", 0.0)))
    return {
        "metric": "心情→主动相关性",
        "value": None,
        "healthy": "valence 显著负相关（低落时主动更谨慎）",
        "note": f"当前 mood 作用域 {len(moods)} 个：{moods[:4]}…。"
                f"主动消息 0.2.0 起才有数据，需积累一周样本后再算相关",
    }


def metric_reaction_variance() -> dict:
    return {
        "metric": "反应方差（同句问 10 遍的两两相似度）",
        "value": None,
        "healthy": "< 0.9",
        "note": "需要主动发同句探测（消耗模型调用且会写入真实历史），"
                "列为人工项。方法：换 key 后同一句话发 10 遍，取回复做嵌入算两两余弦",
    }


def collect() -> list[dict]:
    return [
        metric_emoji_coverage(),
        metric_emotion_length_corr(),
        metric_self_reference(),
        metric_proactive_mood(),
        metric_reaction_variance(),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="她像不像一个人的五个数（基线）")
    parser.add_argument("--save", action="store_true",
                        help="把本次结果存档到 data/vitality_baseline.json")
    args = parser.parse_args(argv)

    results = collect()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n=== 五个数基线 · {stamp} ===\n")
    for r in results:
        value = r.get("value")
        value_str = "—" if value is None else f"{value}"
        print(f"● {r['metric']}")
        print(f"    现值: {value_str}    健康线: {r.get('healthy', '—')}    样本: {r.get('sample', '—')}")
        if r.get("note"):
            print(f"    ※ {r['note']}")
        if r.get("per_source"):
            for k, v in r["per_source"].items():
                print(f"      - {k}: {v}")
        print()

    if args.save:
        out = DATA_DIR / "vitality_baseline.json"
        out.write_text(
            json.dumps({"captured_at": stamp, "results": results},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"已存档 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
