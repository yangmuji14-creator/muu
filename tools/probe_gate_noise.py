"""噪声闸门测试：闲聊查询会不会把无关记忆灌进 prompt

审查报告称「真实 23 条记忆下『今天下雨了』过闸 8/23」—— 这与我用
「主题无关查询」测出的 4% 相差一个数量级。差异来源应该是语料：真实
记忆全是日常生活内容，闲聊查询也是日常生活内容，两者天然靠近。

这个脚本用日常记忆 × 日常闲聊查询重建那个场景，量出真实过闸率，并
对比几种闸门设计：
  A. 纯绝对阈值（现状）
  B. 绝对阈值 + 关键词兜底（现状真实形态）
  C. 两级闸门：严格阈值优先，不足时才放宽
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 日常记忆语料（模拟真实用户 23 条量级，覆盖生活各面）
MEMORIES = [
    "我养了一只叫小黑的猫，它很怕生",
    "用户最近在为考研焦虑，每天复习到凌晨",
    "我妈妈做的红烧肉最好吃",
    "用户是前端工程师，主要写 React",
    "用户喜欢听周杰伦的歌，尤其是早期的",
    "用户习惯晚上两点睡，早上十点起",
    "我最好的朋友叫阿哲，我们从初中就认识",
    "用户不喜欢吃香菜",
    "我小时候在南方长大，那边经常下雨",
    "用户有一只用了五年的旧手机舍不得换",
    "用户最近开始健身，每周去三次",
    "我爸爸是开出租车的",
    "用户讨厌开会的效率",
    "用户喜欢喝冰美式，不加糖",
    "我家的狗叫团子，是金毛",
    "用户上大学时学的是计算机",
    "用户最近在追一部叫《漫长的季节》的剧",
    "我住的城市冬天很冷，会下雪",
    "用户不太会用 Excel",
    "用户的生日是三月十七号",
    "我喜欢一个人待着，不太爱社交",
    "用户最近想换工作",
    "我租的房子在六楼没有电梯",
]

# 日常闲聊查询（与任何记忆都无实质关联）
CHITCHAT = [
    "今天下雨了",
    "我在想以后的事",
    "好无聊啊",
    "你在干嘛",
    "今天好累",
    "晚安",
    "有点饿",
    "嗯嗯",
    "随便聊聊",
    "你觉得呢",
]


def main() -> int:
    from core.memory.embedder import SentenceTransformerEmbedder
    from core.memory.manager import _keyword_tokens

    emb = SentenceTransformerEmbedder()
    if not emb.available:
        print(f"embedder 不可用：{emb.init_error}")
        return 1

    mem_vecs = np.array([emb.embed(m) for m in MEMORIES], dtype=np.float32)
    mem_vecs /= np.linalg.norm(mem_vecs, axis=1, keepdims=True)
    mem_tokens = [_keyword_tokens(m) for m in MEMORIES]
    print(f"记忆 {len(MEMORIES)} 条 × 闲聊查询 {len(CHITCHAT)} 个\n")

    # 每条查询的相似度分布
    all_sims: list[float] = []
    print(f"{'查询':<14} {'max':<7} {'p50':<7} {'≥0.35':<7} {'≥0.45':<7} {'≥0.50':<7}")
    print("-" * 56)
    for q in CHITCHAT:
        qv = np.array(emb.embed(q), dtype=np.float32)
        qv /= np.linalg.norm(qv)
        sims = mem_vecs @ qv
        all_sims.extend(sims.tolist())
        print(f"{q:<14} {sims.max():<7.3f} {np.median(sims):<7.3f} "
              f"{(sims >= 0.35).sum():<7} {(sims >= 0.45).sum():<7} "
              f"{(sims >= 0.50).sum():<7}")

    sims_a = np.array(all_sims)
    print(f"\n全部 {len(sims_a)} 对：mean={sims_a.mean():.3f} "
          f"p50={np.percentile(sims_a, 50):.3f} "
          f"p90={np.percentile(sims_a, 90):.3f} "
          f"p99={np.percentile(sims_a, 99):.3f} max={sims_a.max():.3f}")

    print(f"\n{'阈值':<8} {'过闸率':<10} {'平均每条查询过闸数':<20}")
    print("-" * 42)
    for t in (0.35, 0.40, 0.45, 0.50, 0.55, 0.60):
        rate = float((sims_a >= t).mean())
        print(f"{t:<8.2f} {rate:<10.1%} {rate * len(MEMORIES):<20.1f}")

    # 两级闸门：严格优先，不足才放宽
    print("\n=== 两级闸门（严格 0.50 优先，凑不满才放宽到 0.35）===")
    strict, loose, limit = 0.50, 0.35, 8
    for q in CHITCHAT[:5]:
        qv = np.array(emb.embed(q), dtype=np.float32)
        qv /= np.linalg.norm(qv)
        sims = mem_vecs @ qv
        strict_hits = int((sims >= strict).sum())
        kept = strict_hits if strict_hits >= 3 else int((sims >= loose).sum())
        print(f"  {q:<12} 严格命中 {strict_hits}  →  注入 {min(kept, limit)} 条")

    print("\n结论依据：")
    print(f"  闲聊查询的相似度 p99 = {np.percentile(sims_a, 99):.3f}，"
          f"max = {sims_a.max():.3f}")
    print("  相关查询的相似度 p10 = 0.378（见 calibrate 脚本）")
    print("  两者重叠区间决定了：任何单一绝对阈值都会在"
          "「漏掉弱相关」和「放进闲聊噪声」之间做取舍。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
