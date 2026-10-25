"""MIN_SEMANTIC_SIMILARITY 阈值标定

审查报告说 0.35 实测几乎不构成闸门（bge-small-zh 的相似度普遍挤在
0.35–0.6）。这个脚本用真实模型测出：
  1. 「相关」与「无关」两类的相似度分布
  2. 各候选阈值下的召回率 / 误召回率
  3. 推荐阈值

不猜数字，用分布说话。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 每对：(记忆内容, 相关的查询列表, 无关的查询列表)
# 覆盖真实陪伴场景的记忆类型：偏好、事件、关系、状态、习惯
CASES = [
    ("我养了一只叫小黑的猫，它很怕生",
     ["宠物", "猫", "我家猫怎么样", "小黑的性格"],
     ["今天天气如何", "帮我写代码", "数学作业", "股票行情"]),
    ("用户最近在为考研焦虑，每天复习到凌晨",
     ["学业压力", "最近心情", "复习进度", "考试"],
     ["推荐一部电影", "晚饭吃什么", "怎么修水管", "足球比赛"]),
    ("我妈妈做的红烧肉最好吃",
     ["家人", "做饭", "妈妈的菜", "想念家里"],
     ["编程语言", "显卡型号", "机票价格", "健身计划"]),
    ("用户是前端工程师，主要写 React",
     ["工作", "技术栈", "职业", "最近在忙什么"],
     ["猫咪生病", "菜谱", "星座运势", "电视剧推荐"]),
    ("用户喜欢听周杰伦的歌，尤其是早期的",
     ["音乐", "歌手", "喜欢的歌", "演唱会"],
     ["数据库优化", "房租多少", "体检报告", "驾照考试"]),
    ("用户习惯晚上两点睡，早上十点起",
     ["作息", "睡眠", "生活习惯", "几点睡"],
     ["量子力学", "汇率换算", "烘焙配方", "登山装备"]),
]


def main() -> int:
    from core.memory.embedder import SentenceTransformerEmbedder

    emb = SentenceTransformerEmbedder()
    if not emb.available:
        print(f"embedder 不可用：{emb.init_error}")
        return 1
    print(f"模型：{emb.model_source}  dim={emb.dimension}\n")

    def cos(a, b) -> float:
        va = np.array(emb.embed(a), dtype=np.float32)
        vb = np.array(emb.embed(b), dtype=np.float32)
        return float(np.dot(va, vb))

    rel: list[float] = []
    irr: list[float] = []
    print(f"{'记忆':<28} {'相关查询 sim':<22} {'无关查询 sim':<22}")
    print("-" * 76)
    for content, rel_qs, irr_qs in CASES:
        rs = [cos(content, q) for q in rel_qs]
        is_ = [cos(content, q) for q in irr_qs]
        rel.extend(rs)
        irr.extend(is_)
        print(f"{content[:26]:<28} "
              f"{min(rs):.3f}–{max(rs):.3f} (μ{np.mean(rs):.3f})  "
              f"{min(is_):.3f}–{max(is_):.3f} (μ{np.mean(is_):.3f})")

    rel_a = np.array(rel)
    irr_a = np.array(irr)
    print(f"\n相关对 n={len(rel_a)}  mean={rel_a.mean():.3f} "
          f"p10={np.percentile(rel_a, 10):.3f} p50={np.percentile(rel_a, 50):.3f}")
    print(f"无关对 n={len(irr_a)}  mean={irr_a.mean():.3f} "
          f"p90={np.percentile(irr_a, 90):.3f} p99={np.percentile(irr_a, 99):.3f}")

    print(f"\n{'阈值':<8} {'召回率':<10} {'误召回率':<10} {'F1':<8}")
    print("-" * 40)
    best = (0.0, -1.0)
    for t in np.arange(0.20, 0.75, 0.025):
        rec = float((rel_a >= t).mean())
        fpr = float((irr_a >= t).mean())
        prec = rec * len(rel_a) / max(rec * len(rel_a) + fpr * len(irr_a), 1e-9)
        f1 = 2 * prec * rec / max(prec + rec, 1e-9)
        mark = ""
        if f1 > best[1]:
            best = (float(t), f1)
            mark = "  <- best"
        print(f"{t:<8.3f} {rec:<10.2f} {fpr:<10.2f} {f1:<8.3f}{mark}")

    print(f"\n纯阈值最优 ≈ {best[0]:.3f} (F1={best[1]:.3f})")

    # ---- 关键：真实闸门是 `sim >= T or keyword_overlap`，不是纯阈值 ----
    # 只按纯阈值标定会低估召回、高估误召回，因为关键词兜底会救回一批
    # 语义弱但字面重叠的候选。这里按真实闸门重算。
    from core.memory.manager import _keyword_tokens

    print("\n=== 真实闸门（sim >= T or keyword_overlap）===")
    print(f"{'阈值':<8} {'召回率':<10} {'误召回率':<10} {'F1':<8} {'被关键词救回'}")
    print("-" * 56)
    gate_best = (0.0, -1.0)
    for t in np.arange(0.20, 0.75, 0.025):
        rec_hits = 0
        fpr_hits = 0
        rescued = 0
        for content, rel_qs, irr_qs in CASES:
            mem_tokens = _keyword_tokens(content)
            for q in rel_qs:
                sim = cos(content, q)
                overlap = bool(mem_tokens & _keyword_tokens(q))
                if sim >= t or overlap:
                    rec_hits += 1
                    if sim < t:
                        rescued += 1
            for q in irr_qs:
                sim = cos(content, q)
                overlap = bool(mem_tokens & _keyword_tokens(q))
                if sim >= t or overlap:
                    fpr_hits += 1
        rec = rec_hits / len(rel)
        fpr = fpr_hits / len(irr)
        prec = rec * len(rel) / max(rec * len(rel) + fpr * len(irr), 1e-9)
        f1 = 2 * prec * rec / max(prec + rec, 1e-9)
        mark = ""
        if f1 > gate_best[1]:
            gate_best = (float(t), f1)
            mark = "  <- best"
        print(f"{t:<8.3f} {rec:<10.2f} {fpr:<10.2f} {f1:<8.3f} {rescued:<6}{mark}")

    print(f"\n真实闸门最优阈值 ≈ {gate_best[0]:.3f} (F1={gate_best[1]:.3f})")
    for name, t in (("当前 0.35", 0.35), ("报告建议 0.45", 0.45),
                    (f"真实最优 {gate_best[0]:.2f}", gate_best[0])):
        rec_hits = fpr_hits = 0
        for content, rel_qs, irr_qs in CASES:
            mem_tokens = _keyword_tokens(content)
            for q in rel_qs:
                if cos(content, q) >= t or (mem_tokens & _keyword_tokens(q)):
                    rec_hits += 1
            for q in irr_qs:
                if cos(content, q) >= t or (mem_tokens & _keyword_tokens(q)):
                    fpr_hits += 1
        print(f"  {name:<16} 召回 {rec_hits/len(rel):.0%}  "
              f"误召回 {fpr_hits/len(irr):.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
