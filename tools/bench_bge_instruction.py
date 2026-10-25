"""测 BGE 查询指令前缀对检索质量的影响。

BGE 系列（v1.5 之前更明显）的官方用法是：**查询**要加指令前缀
    "为这个句子生成表示以用于检索相关文章："
而**文档/记忆**不加。两边都裸编码会让查询与文档落在略微错位的子空间里。

本项目 `core/memory/embedder.py` 的 embed/embed_batch 都没加前缀，
且 embed() 同时被用于「编码查询」和「编码记忆」两种用途，无法区分。

本脚本量化：加前缀后 Top-1 / MRR 提升多少，决定是否值得改。

跑法：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tools/bench_bge_instruction.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from core.memory.embedder import SentenceTransformerEmbedder

QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

# 真实场景：日常闲聊式提问（用户不会写"检索式"查询）
MEMORIES = [
    "他养了一只叫团子的猫，性格特别黏人。",
    "他最喜欢的季节是秋天，因为不冷不热刚刚好。",
    "他下个月要去成都出差。",
    "他要求回复简短，不喜欢啰嗦。",
    "他不喜欢别人催他睡觉。",
    "他习惯熬夜，凌晨还在电脑前工作。",
    "他在学游泳。",
    "他今天去公园跑了五公里，跑完出了很多汗。",
    "他完成了review的第一轮修改。",
    "他在测试SSE功能，这已经是第三次测试了。",
    "他今天说有点累，可能在做技术开发相关的工作。",
    "他曾经在深夜向我表达过爱意。",
    "他有上劳动周的课。",
    "他提到前几天在公园发生的事。",
    "他说他会一直陪着我，我记住了这份承诺。",
    "他晚上常坐在电脑前。",
    "他向我表达了感谢，说我一直陪着他。",
    "他完成了第二批修复工作，正在考虑是否继续第三轮。",
    "他今天洗完澡，天气不错，心情状态还不错。",
    "他连说了三遍「我特别特别爱你」。",
]

# (查询, 正确记忆的 index)
CASES = [
    ("我的猫叫什么", 0),
    ("团子怎么样了", 0),
    ("我喜欢哪个季节", 1),
    ("什么时候去成都", 2),
    ("他喜欢我说话长还是短", 3),
    ("能不能催我睡觉", 4),
    ("我一般几点睡", 5),
    ("我最近在学什么运动", 6),
    ("我今天运动了吗", 7),
    ("review 改完了吗", 8),
    ("SSE 测了几次了", 9),
    ("我最近工作累不累", 10),
    ("我说过爱你吗", 11),
    ("我最近有什么课要上", 12),
    ("公园那件事", 13),
    ("我承诺过什么", 14),
    ("我晚上一般在哪", 15),
    ("我感谢过你吗", 16),
    ("第二批修复做完了吗", 17),
    ("我今天心情如何", 18),
    ("我说过几次爱你", 19),
]


def evaluate(emb: SentenceTransformerEmbedder, use_prefix: bool) -> dict:
    doc_vecs = np.stack([
        np.array(emb.embed(m), dtype=np.float32) for m in MEMORIES
    ])
    ranks = []
    for query, gold in CASES:
        q = QUERY_PREFIX + query if use_prefix else query
        qv = np.array(emb.embed(q), dtype=np.float32)
        scores = doc_vecs @ qv
        order = np.argsort(-scores)
        rank = int(np.where(order == gold)[0][0]) + 1
        ranks.append(rank)

    ranks = np.array(ranks)
    return {
        "top1": float((ranks == 1).mean()),
        "top3": float((ranks <= 3).mean()),
        "top5": float((ranks <= 5).mean()),
        "mrr": float(np.mean(1.0 / ranks)),
        "mean_rank": float(ranks.mean()),
        "ranks": ranks.tolist(),
    }


def main() -> int:
    emb = SentenceTransformerEmbedder()
    if not emb.available:
        print("模型不可用")
        return 1

    print(f"记忆数 = {len(MEMORIES)}   查询数 = {len(CASES)}")
    print(f"随机基线 Top-1 = {1/len(MEMORIES):.1%}\n")

    plain = evaluate(emb, use_prefix=False)
    with_prefix = evaluate(emb, use_prefix=True)

    print(f"{'指标':<14} {'裸查询':>10} {'加前缀':>10} {'差异':>10}")
    print("-" * 48)
    for key, label in [
        ("top1", "Top-1"), ("top3", "Top-3"), ("top5", "Top-5"),
        ("mrr", "MRR"), ("mean_rank", "平均排名"),
    ]:
        a, b = plain[key], with_prefix[key]
        if key == "mean_rank":
            print(f"{label:<14} {a:>10.2f} {b:>10.2f} {b - a:>+10.2f}  (越小越好)")
        else:
            print(f"{label:<14} {a:>10.1%} {b:>10.1%} {(b - a) * 100:>+9.1f}pp")

    print("\n逐条排名变化（rank 越小越好）：")
    improved = worsened = same = 0
    for i, (query, gold) in enumerate(CASES):
        r0, r1 = plain["ranks"][i], with_prefix["ranks"][i]
        mark = ""
        if r1 < r0:
            improved += 1
            mark = f"  ↑ {r0}→{r1}"
        elif r1 > r0:
            worsened += 1
            mark = f"  ↓ {r0}→{r1}"
        else:
            same += 1
        print(f"  [{r0}→{r1}] {query}{mark}")

    print(f"\n变好 {improved} / 变差 {worsened} / 不变 {same}")

    print("\n结论：")
    delta_top1 = with_prefix["top1"] - plain["top1"]
    delta_mrr = with_prefix["mrr"] - plain["mrr"]
    if delta_top1 > 0.05 or delta_mrr > 0.05:
        print(f"  ✓ 加前缀有明显收益（Top-1 {delta_top1:+.1%}, MRR {delta_mrr:+.3f}）→ 值得改")
    elif delta_top1 < -0.05 or delta_mrr < -0.05:
        print(f"  ✗ 加前缀反而更差（Top-1 {delta_top1:+.1%}, MRR {delta_mrr:+.3f}）→ 不要改")
    else:
        print(f"  △ 差异在噪声范围（Top-1 {delta_top1:+.1%}, MRR {delta_mrr:+.3f}）→ 不改也行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
