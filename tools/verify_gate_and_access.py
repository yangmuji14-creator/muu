"""批次7 运行时验证：相对闸门在真实模型上的收益与代价

同一份语料、同一个模型，跑两种配置对比：
  A. 只有绝对阈值 0.35（改前）
  B. 绝对阈值 + 相对闸门 0.9（改后）

指标：
  1. 闲聊查询平均注入多少条（噪声）
  2. 相关查询正确答案召回率（代价）
  3. access_count / forget_score 是否真的落库
"""

from __future__ import annotations

import sys
from pathlib import Path

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

RELEVANT = [
    ("我家猫怎么样", "我养了一只叫小黑的猫，它很怕生"),
    ("团子最近怎么样", "我家的狗叫团子，是金毛"),
    ("最近压力好大", "用户最近在为考研焦虑，每天复习到凌晨"),
    ("我想吃妈妈做的菜", "我妈妈做的红烧肉最好吃"),
    ("我在忙什么工作", "用户是前端工程师，主要写 React"),
    ("有什么好听的歌推荐", "用户喜欢听周杰伦的歌，尤其是早期的"),
    ("我几点睡比较晚", "用户习惯晚上两点睡，早上十点起"),
    ("我不吃什么", "用户不喜欢吃香菜"),
    ("我老家那边天气", "我小时候在南方长大，那边经常下雨"),
]


def count_injected(prompt: str) -> int:
    return sum(1 for line in prompt.splitlines() if line.startswith("- "))


def run_config(emb, tmp: Path, ratio: float, tag: str) -> None:
    from core.memory.manager import MemoryManager
    from core.memory.vector_store import VectorStore

    vs = VectorStore(tmp / f"v_{tag}.db")
    mgr = MemoryManager(tmp / f"d_{tag}", embedder=emb, vector_store=vs)
    mgr.RELATIVE_SIMILARITY_RATIO = ratio
    for content in MEMORIES:
        mgr.add_memory_sync("u", content, level=3)

    noise_total = 0
    for q in CHITCHAT:
        noise_total += count_injected(mgr.get_context_prompt("u", query=q))
    noise = noise_total / len(CHITCHAT)

    hit = 0
    missed = []
    for q, expected in RELEVANT:
        prompt = mgr.get_context_prompt("u", query=q)
        if expected in prompt:
            hit += 1
        else:
            missed.append(q)

    label = "A. 只有绝对阈值 0.35" if ratio == 0.0 else "B. + 相对闸门 0.9"
    print(f"{label}")
    print(f"   闲聊注入   {noise:.1f} 条/查询")
    print(f"   相关召回   {hit}/{len(RELEVANT)} ({hit / len(RELEVANT):.0%})")
    if missed:
        print(f"   未召回     {', '.join(missed)}")

    stored = mgr._storage.load("u")
    touched = sum(1 for m in stored if m.access_count > 0)
    print(f"   access_count>0  {touched}/{len(stored)} 条")

    # 刚创建的记忆 forget_score 天然是 0，要造几条旧的才看得出衰减
    from datetime import datetime, timedelta

    old = mgr.add_memory_sync("u", "很久以前的一件小事", level=2)
    old.created_at = (datetime.now() - timedelta(days=200)).isoformat()
    old.last_accessed = old.created_at
    mgr._storage.update("u", old)
    before = mgr._storage.get("u", old.id).forget_score
    # 前面的 get_context_prompt 已经触发过落库并开了 5 分钟节流窗口，
    # 这里清掉时间戳才能看到「衰减值真的写进库」这件事。
    mgr._decay_flushed_at.clear()
    mgr.get_memories("u", limit=100)
    after = mgr._storage.get("u", old.id).forget_score
    print(f"   forget_score 旧记忆  改前 {before:.4f} → 改后 {after:.4f}"
          f" {'✓ 已落库' if after > before else '✗ 未落库'}")
    vs.close()
    return noise, hit


def main() -> int:
    from core.memory.embedder import SentenceTransformerEmbedder

    emb = SentenceTransformerEmbedder()
    if not emb.available:
        print(f"embedder 不可用：{emb.init_error}")
        return 1

    base = ROOT / "tmp_verify_gate"
    base.mkdir(exist_ok=True)
    print(f"语料 {len(MEMORIES)} 条记忆，模型 {emb.model_source}\n")

    run_config(emb, base, 0.0, "absolute")
    print()
    run_config(emb, base, 0.9, "relative")
    print(f"\n（临时目录 {base}，验证完可手工删除）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
