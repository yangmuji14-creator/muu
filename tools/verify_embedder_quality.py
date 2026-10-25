"""验证向量模型「真实可用」：不是能加载就算数，要证明它产出的向量有语义。

分五段：
1. 模型身份 —— 确认加载的是真的 BGE，不是空壳/随机权重
2. 向量健全性 —— 不是常数、不是全零、已 L2 归一化
3. 中文语义区分度 —— 相近句 vs 无关句的相似度分布
4. 真实记忆检索 —— 用本项目实际会存的记忆，测 recall@k
5. 与随机基线对比 —— 证明不是「什么都很像」

跑法：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tools/verify_embedder_quality.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from core.memory.embedder import SentenceTransformerEmbedder


def cosine(a, b) -> float:
    a, b = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    return float(a @ b)


def section(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main() -> int:
    emb = SentenceTransformerEmbedder()

    # ---- 1. 模型身份 ----
    section("1. 模型身份（加载的是不是真的 BGE）")
    print(f"  available      = {emb.available}")
    print(f"  dimension      = {emb.dimension}")
    print(f"  model_source   = {emb.model_source}")
    print(f"  init_error     = {emb.init_error}")
    if not emb.available:
        print("\n  ✗ 模型不可用，后续无法验证")
        return 1

    model = emb._model
    try:
        auto = model[0].auto_model
        cfg = auto.config
        n_params = sum(p.numel() for p in auto.parameters())
        print(f"  architecture   = {type(auto).__name__}")
        print(f"  hidden_size    = {cfg.hidden_size}")
        print(f"  num_layers     = {cfg.num_hidden_layers}")
        print(f"  vocab_size     = {cfg.vocab_size}")
        print(f"  参数量         = {n_params:,}  ({n_params * 4 / 1024 / 1024:.1f} MB fp32)")
        # BGE-small-zh 是 4 层 512 隐层，约 2400 万参数
        looks_real = (
            type(auto).__name__ == "BertModel"
            and cfg.hidden_size == 512
            and cfg.num_hidden_layers == 4
            and 20_000_000 < n_params < 30_000_000
        )
        print(f"  → 参数规模符合 BGE-small-zh：{'✓' if looks_real else '✗ 可疑'}")
    except Exception as e:
        print(f"  （无法读取内部结构：{e}）")
        looks_real = None

    # ---- 2. 向量健全性 ----
    section("2. 向量健全性（不是常数 / 全零 / 未归一化）")
    v = emb.embed("我养了一只猫")
    if v is None:
        print("  ✗ embed 返回 None")
        return 1
    arr = np.array(v, dtype=np.float32)
    print(f"  长度           = {len(v)}")
    print(f"  L2 范数        = {np.linalg.norm(arr):.6f}  (应≈1.0，已归一化)")
    print(f"  最小值/最大值  = {arr.min():.4f} / {arr.max():.4f}")
    print(f"  标准差         = {arr.std():.4f}  (接近 0 说明是常数向量)")
    print(f"  非零元素占比   = {(arr != 0).mean():.1%}")
    healthy = (
        len(v) == 512
        and abs(np.linalg.norm(arr) - 1.0) < 1e-3
        and arr.std() > 0.01
        and (arr != 0).mean() > 0.9
    )
    print(f"  → 向量健康：{'✓' if healthy else '✗'}")

    # 不同文本必须给出不同向量
    a = np.array(emb.embed("今天天气不错"), dtype=np.float32)
    b = np.array(emb.embed("今天天气不错"), dtype=np.float32)
    c = np.array(emb.embed("我的显卡是 4090"), dtype=np.float32)
    print(f"  同文本重复编码一致：{'✓' if np.allclose(a, b, atol=1e-6) else '✗'}")
    print(f"  不同文本向量不同：  {'✓' if not np.allclose(a, c, atol=1e-3) else '✗ 输出塌缩'}")

    # ---- 3. 中文语义区分度 ----
    section("3. 中文语义区分度（相近 vs 无关）")
    pairs = [
        ("我喜欢喝咖啡", "我每天都要来一杯美式", True),
        ("我在准备考研", "最近复习压力很大", True),
        ("我养了一只猫", "家里那只橘猫很粘人", True),
        ("我讨厌早起", "每天早上都起不来", True),
        ("我在学吉他", "最近在练指法", True),
        ("我喜欢喝咖啡", "我的显卡是 RTX 4090", False),
        ("我在准备考研", "今天吃了火锅", False),
        ("我养了一只猫", "股票又跌了", False),
        ("我讨厌早起", "这家店的拉面很好吃", False),
        ("我在学吉他", "明天下雨记得带伞", False),
    ]
    close_sims, far_sims = [], []
    print(f"  {'句子 A':<12} {'句子 B':<16} {'相似度':>7}  期望")
    print("  " + "-" * 60)
    for x, y, should_close in pairs:
        s = cosine(emb.embed(x), emb.embed(y))
        (close_sims if should_close else far_sims).append(s)
        mark = "相近" if should_close else "无关"
        ok = "✓" if (s > 0.5 if should_close else s < 0.5) else "✗"
        print(f"  {x:<12} {y:<16} {s:>7.4f}  {mark} {ok}")

    print()
    print(f"  相近句：mean={np.mean(close_sims):.4f}  min={np.min(close_sims):.4f}")
    print(f"  无关句：mean={np.mean(far_sims):.4f}  max={np.max(far_sims):.4f}")
    gap = np.mean(close_sims) - np.mean(far_sims)
    print(f"  区分度（均值差） = {gap:.4f}")
    separable = np.min(close_sims) > np.max(far_sims)
    print(f"  → 两类完全可分：{'✓' if separable else '△ 有重叠（正常，但需靠阈值区分）'}")

    # ---- 4. 真实记忆检索 recall@k ----
    section("4. 真实记忆检索（本项目会存的记忆）")
    memories = [
        "用户养了一只叫小黑的猫，它很怕生",
        "用户喜欢在深夜写代码，讨厌早起",
        "用户最近在准备考研，压力很大",
        "用户对花生过敏，不能吃坚果",
        "用户的显卡是 RTX 4090",
        "用户住在杭州，经常下雨",
        "用户的女朋友叫小雨，喜欢烘焙",
        "用户每周三晚上打羽毛球",
        "用户讨厌吃香菜",
        "用户在做一个人工智能陪伴项目",
        "用户的生日是 3 月 15 日",
        "用户喜欢喝冰美式，不加糖",
    ]
    queries = [
        ("我的猫怎么样了", "用户养了一只叫小黑的猫，它很怕生"),
        ("我什么时候写代码效率高", "用户喜欢在深夜写代码，讨厌早起"),
        ("最近学习压力大", "用户最近在准备考研，压力很大"),
        ("我能吃花生吗", "用户对花生过敏，不能吃坚果"),
        ("我电脑什么配置", "用户的显卡是 RTX 4090"),
        ("我住哪", "用户住在杭州，经常下雨"),
        ("我女朋友喜欢做什么", "用户的女朋友叫小雨，喜欢烘焙"),
        ("我有什么运动习惯", "用户每周三晚上打羽毛球"),
        ("我生日是哪天", "用户的生日是 3 月 15 日"),
        ("我爱喝什么咖啡", "用户喜欢喝冰美式，不加糖"),
    ]
    mem_vecs = [np.array(emb.embed(m), dtype=np.float32) for m in memories]
    mat = np.stack(mem_vecs)

    for k in (1, 3, 5):
        hits = 0
        for q, expected in queries:
            qv = np.array(emb.embed(q), dtype=np.float32)
            scores = mat @ qv
            top_idx = np.argsort(-scores)[:k]
            if memories.index(expected) in top_idx:
                hits += 1
        print(f"  recall@{k} = {hits}/{len(queries)} ({hits / len(queries):.0%})")

    print("\n  逐条明细（rank=命中位置，sim=相似度）：")
    rank1 = 0
    for q, expected in queries:
        qv = np.array(emb.embed(q), dtype=np.float32)
        scores = mat @ qv
        order = np.argsort(-scores)
        idx = memories.index(expected)
        rank = int(np.where(order == idx)[0][0]) + 1
        if rank == 1:
            rank1 += 1
        print(f"    rank={rank:<2} sim={scores[idx]:.4f}  {q}")
    print(f"\n  → Top-1 准确率 = {rank1}/{len(queries)} ({rank1 / len(queries):.0%})")

    # ---- 5. 随机基线对比 ----
    section("5. 与随机基线对比（证明不是「什么都很像」）")
    # 说明：BGE 这类模型天然各向异性（anisotropy），同领域文本的余弦会整体偏高，
    # 所以「两两相似度的标准差」不是判断结构的好指标 —— 随机高斯的 std≈0.045，
    # 真实记忆 std≈0.07，这个差别是各向异性造成的，不是语义能力。
    # 真正的证据是「检索命中率 vs 随机猜中率」：结构强则远超 chance。
    rng = np.random.default_rng(42)
    all_vecs = np.stack([np.array(emb.embed(m), dtype=np.float32) for m in memories])
    real_sims = (all_vecs @ all_vecs.T)[np.triu_indices(len(all_vecs), 1)]
    print(f"  真实记忆两两相似度（n={len(real_sims)}，全部同属「用户」域，偏高属正常）：")
    print(f"    mean = {np.mean(real_sims):.4f}   p50 = {np.percentile(real_sims, 50):.4f}")
    print(f"    p95  = {np.percentile(real_sims, 95):.4f}   max = {np.max(real_sims):.4f}")

    g = rng.normal(size=(200, 512)).astype(np.float32)
    g /= np.linalg.norm(g, axis=1, keepdims=True)
    gs = (g @ g.T)[np.triu_indices(200, 1)]
    print(f"\n  对照：随机高斯向量（512 维，各向同性）：")
    print(f"    mean = {np.mean(gs):.4f}   p95 = {np.percentile(gs, 95):.4f}"
          f"   max = {np.max(gs):.4f}")
    print(f"  → 真实分布右尾远厚于随机（p95 {np.percentile(real_sims, 95):.4f} vs"
          f" {np.percentile(gs, 95):.4f}）：说明向量间存在语义聚类，而非均匀散布")

    # 核心检验：随机基线（chance level）vs 实测 recall@1
    n_mem = len(memories)
    chance_at1 = 1.0 / n_mem
    observed_at1 = rank1 / len(queries)
    print(f"\n  随机猜中率（1/{n_mem}）      = {chance_at1:.1%}")
    print(f"  实测 Top-1 准确率        = {observed_at1:.1%}")
    print(f"  提升倍数                 = {observed_at1 / chance_at1:.1f}x")
    has_structure = observed_at1 >= max(0.7, chance_at1 * 5)
    print(f"  → 向量携带语义结构：{'✓' if has_structure else '✗'}")

    # 反证：把查询与记忆的配对打乱，准确率必须崩到 chance 附近
    shuffled_hits = 0
    for i, (q, _) in enumerate(queries):
        qv = np.array(emb.embed(q), dtype=np.float32)
        scores = mat @ qv
        wrong_target = (memories.index(queries[(i + 1) % len(queries)][1]))
        if int(np.argmax(scores)) == wrong_target:
            shuffled_hits += 1
    print(f"  反证：故意配错目标时命中 {shuffled_hits}/{len(queries)}"
          f"（应接近 0，证明不是「随便都能对上」）")

    section("结论")
    checks = {
        "模型可用": emb.available,
        "向量健康": healthy,
        "语义可分": separable or gap > 0.15,
        "检索有效": rank1 >= len(queries) * 0.7,
        "有结构": has_structure and shuffled_hits <= len(queries) * 0.2,
    }
    for name, ok in checks.items():
        print(f"  {name:<10} {'✓' if ok else '✗'}")
    all_ok = all(checks.values())
    print(f"\n  {'✓ 向量模型真实可用，语义检索是名副其实的' if all_ok else '✗ 存在未通过项，见上'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
