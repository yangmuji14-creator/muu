"""相对闸门标定：绝对阈值不够，要用「相对 top1」的比值

前两个脚本量出的矛盾：
  - 闲聊查询 × 日常记忆：0.35 过闸 53%（噪声全进来），0.50 才降到 4.8%
  - 相关查询：p10 = 0.378，0.50 会漏掉 33% 的相关对

单一绝对阈值无解，因为两类分布的相似度区间重叠。真实检索系统用的是
相对闸门：只看「和最好的那条差多远」。

闸门设计：
    keep if sim >= max(ABS_FLOOR, top1 * RATIO)
其中 ABS_FLOOR 防止全低分时仍保留，RATIO 控制相对宽松度。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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

CHITCHAT = [
    "今天下雨了", "我在想以后的事", "好无聊啊", "你在干嘛", "今天好累",
    "晚安", "有点饿", "嗯嗯", "随便聊聊", "你觉得呢",
]

# 与记忆真正相关的查询，以及「哪几条才算正确答案」（人工判定）
RELEVANT = [
    ("我家猫怎么样", {"我养了一只叫小黑的猫，它很怕生"}),
    ("团子最近怎么样", {"我家的狗叫团子，是金毛"}),
    ("最近压力好大", {"用户最近在为考研焦虑，每天复习到凌晨"}),
    ("我想吃妈妈做的菜", {"我妈妈做的红烧肉最好吃"}),
    ("我在忙什么工作", {"用户是前端工程师，主要写 React"}),
    ("有什么好听的歌推荐", {"用户喜欢听周杰伦的歌，尤其是早期的"}),
    ("我几点睡比较晚", {"用户习惯晚上两点睡，早上十点起"}),
    ("我朋友的事", {"我最好的朋友叫阿哲，我们从初中就认识"}),
    ("我不吃什么", {"用户不喜欢吃香菜"}),
    ("我老家那边天气", {"我小时候在南方长大，那边经常下雨"}),
]


def evaluate(emb, strict_floor: float, ratio: float, limit: int = 8):
    """返回 (相关查询的召回率, 闲聊查询的噪声条数均值)"""
    mem_vecs = np.array([emb.embed(m) for m in MEMORIES], dtype=np.float32)
    mem_vecs /= np.linalg.norm(mem_vecs, axis=1, keepdims=True)

    def gate(q: str) -> list[int]:
        qv = np.array(emb.embed(q), dtype=np.float32)
        qv /= np.linalg.norm(qv)
        sims = mem_vecs @ qv
        top1 = float(sims.max())
        cut = max(strict_floor, top1 * ratio)
        idx = np.where(sims >= cut)[0]
        idx = idx[np.argsort(-sims[idx])][:limit]
        return idx.tolist()

    # 召回：正确答案是否出现在结果里
    hit = 0
    # 相关查询下的「陪跑噪声」：有强匹配时还带进多少条无关记忆
    companion = 0
    for q, expected in RELEVANT:
        got = {MEMORIES[i] for i in gate(q)}
        if expected & got:
            hit += 1
        companion += len(got - expected)
    recall = hit / len(RELEVANT)
    companion /= len(RELEVANT)

    # 噪声：闲聊查询注入多少条
    noise = sum(len(gate(q)) for q in CHITCHAT) / len(CHITCHAT)
    return recall, noise, companion


def main() -> int:
    from core.memory.embedder import SentenceTransformerEmbedder

    emb = SentenceTransformerEmbedder()
    if not emb.available:
        print(f"embedder 不可用：{emb.init_error}")
        return 1

    print("目标：召回率尽量高，噪声条数尽量低\n")
    print(f"{'ABS_FLOOR':<11} {'RATIO':<8} {'召回率':<9} {'闲聊噪声':<10} {'陪跑噪声':<10}")
    print("-" * 54)

    rows = []
    for floor in (0.30, 0.35, 0.40):
        for ratio in (0.0, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90):
            rec, noise, companion = evaluate(emb, floor, ratio)
            rows.append((floor, ratio, rec, noise, companion))
            print(f"{floor:<11.2f} {ratio:<8.2f} {rec:<9.0%} "
                  f"{noise:<10.2f} {companion:<10.2f}")

    # 选：召回率 >= 0.8 里「闲聊噪声 + 陪跑噪声」最小的
    ok = [r for r in rows if r[2] >= 0.8]
    if ok:
        best = min(ok, key=lambda r: r[3] + r[4])
        print(f"\n推荐：ABS_FLOOR={best[0]:.2f} RATIO={best[1]:.2f} "
              f"→ 召回 {best[2]:.0%}，闲聊噪声 {best[3]:.2f}，"
              f"陪跑噪声 {best[4]:.2f}")

    print("\n对照（纯绝对阈值）：")
    for floor in (0.35, 0.45, 0.50):
        rec, noise, companion = evaluate(emb, floor, 0.0)
        print(f"  {floor:.2f}  → 召回 {rec:.0%}，闲聊噪声 {noise:.2f}，"
              f"陪跑噪声 {companion:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
