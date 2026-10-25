"""向量记忆路径的耗时基准

对比两条路径在真实规模下的耗时：
  A. 现在主对话走的路：每轮把候选记忆重新 embed（transformers 前向）
  B. 向量库该走的路：存好的向量直接点积

目的：给「主对话不读向量库」这个缺陷一个可量化的代价。
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

N = 200  # 模拟一个有 200 条记忆的用户


async def main() -> int:
    from core.memory.embedder import SentenceTransformerEmbedder
    from core.memory.manager import MemoryManager
    from core.memory.vector_store import VectorStore

    emb = SentenceTransformerEmbedder()
    if not emb.available:
        print("embedder 不可用，基准无意义")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="bench_vec_"))
    store = VectorStore(tmp / "vectors.db")
    mgr = MemoryManager(tmp, embedder=emb, vector_store=store)

    corpus = [
        f"第{i}条记忆：用户提到过一些关于生活琐事、工作压力、兴趣爱好方面的内容，编号{i}"
        for i in range(N)
    ]
    t0 = time.perf_counter()
    for c in corpus:
        await mgr.add_memory("u", c, level=3, category="life")
    build = time.perf_counter() - t0
    print(f"写入 {N} 条记忆（含 embed + 落库）：{build:.2f}s  "
          f"({build / N * 1000:.1f} ms/条)")
    print(f"vector count = {store.count('u')}  sqlite count = {mgr._storage.count('u')}")

    queries = ["宠物", "学业压力", "作息习惯", "朋友关系", "工作烦恼"]

    # A. 现在主对话走的路径
    ta: list[float] = []
    for q in queries:
        t = time.perf_counter()
        mgr.get_context_prompt("u", limit=8, query=q)
        ta.append((time.perf_counter() - t) * 1000)

    # B. 直接查向量库
    tb: list[float] = []
    for q in queries:
        t = time.perf_counter()
        qv = emb.embed(q)
        store.search("u", qv, top_k=8)
        tb.append((time.perf_counter() - t) * 1000)

    # C. 只 embed 一次查询（不含候选重算）
    tc: list[float] = []
    for q in queries:
        t = time.perf_counter()
        emb.embed(q)
        tc.append((time.perf_counter() - t) * 1000)

    def stat(name: str, xs: list[float]) -> None:
        print(f"  {name:<42} median={statistics.median(xs):8.1f} ms  "
              f"min={min(xs):7.1f}  max={max(xs):7.1f}")

    print(f"\n{N} 条记忆下，单次请求耗时（{len(queries)} 次取中位数）：")
    stat("A. get_context_prompt（现主路径，含候选重 embed）", ta)
    stat("B. embed(query) + vector_store.search", tb)
    stat("C. 只 embed(query)（B 的固定成本）", tc)
    print(f"\n  A/B 倍率 = {statistics.median(ta) / statistics.median(tb):.1f}x")
    print(f"  A 里纯向量检索该占的成本 = {statistics.median(tc):.1f} ms "
          f"({statistics.median(tc) / statistics.median(ta) * 100:.0f}% of A)")

    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
