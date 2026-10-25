"""向量记忆系统运行时探针

回答一个问题：**向量记忆到底有没有在真正运作？**
不是读代码猜，是真的建一个 manager、写入记忆、再语义检索，把每一步的实际
状态打出来。

跑法：
    ./.venv/Scripts/python.exe tools/probe_vector_memory.py
"""

from __future__ import annotations

import asyncio
import math
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def hr(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


async def main() -> int:
    hr("1. 依赖可用性")
    for mod in ("numpy", "sentence_transformers", "faiss", "sqlite_vec"):
        try:
            m = __import__(mod)
            print(f"  [ok]   {mod:<24} version={getattr(m, '__version__', '?')}")
        except Exception as e:
            print(f"  [MISS] {mod:<24} {type(e).__name__}: {e}")

    from core.memory.embedder import LOCAL_MODEL_DIRNAME, resolve_model_source

    src = resolve_model_source()
    print(f"  resolve_model_source() = {src}")
    print(f"  is_local_dir           = {Path(src).is_dir()}")
    local = ROOT / "models" / LOCAL_MODEL_DIRNAME
    print(f"  models/{LOCAL_MODEL_DIRNAME} exists = {local.is_dir()}")

    hr("2. Embedder 实际状态")
    from core.memory.embedder import SentenceTransformerEmbedder

    emb = SentenceTransformerEmbedder()
    print(f"  available    = {emb.available}")
    print(f"  dimension    = {emb.dimension}")
    print(f"  model_source = {emb.model_source}")
    print(f"  init_error   = {emb.init_error}")
    if emb.available:
        v = emb.embed("今天心情不错")
        print(f"  embed() len  = {len(v) if v else None}")
        if v:
            print(f"  L2 norm      = {math.sqrt(sum(x * x for x in v)):.6f}")
    else:
        print("  !! Embedder 不可用 —— 向量记忆必然全空转")

    hr("3. VectorStore 打开与规模")
    from core.memory.vector_store import VectorStore

    tmp = Path(tempfile.mkdtemp(prefix="probe_vec_"))
    store = VectorStore(tmp / "vectors.db")
    print(f"  data_dir  = {tmp}")
    print(f"  count(u)  = {store.count('u')}")
    print(f"  methods   = {[m for m in dir(store) if not m.startswith('_')]}")

    hr("4. 写入路径（async add_memory）")
    from core.memory.manager import MemoryManager

    mgr = MemoryManager(tmp, embedder=emb, vector_store=store)
    print(f"  embedding_status = {mgr.embedding_status()}")

    samples = [
        "我养了一只叫小黑的猫，它很怕生",
        "用户最近在准备考研，压力很大",
        "用户喜欢在深夜写代码，讨厌早起",
    ]
    for s in samples:
        m = await mgr.add_memory("u", s, level=3, category="life")
        print(f"  add_memory -> id={m.id} content={s}")

    print(f"  vector store count after adds = {store.count('u')}")
    print(f"  sqlite memory count           = {mgr._storage.count('u')}")
    print(f"  embedding_status (after)      = {mgr.embedding_status()}")

    hr("5. 检索路径（语义 vs 关键词）")
    queries = [
        ("宠物", "我养了一只叫小黑的猫，它很怕生"),
        ("学业压力", "用户最近在准备考研，压力很大"),
        ("作息习惯", "用户喜欢在深夜写代码，讨厌早起"),
    ]
    for q, expect in queries:
        print(f"\n  query = {q!r}  期望命中 = {expect}")
        sem = mgr.semantic_search("u", q, top_k=3)
        print(f"    semantic_search -> {len(sem)} 条")
        for h in sem:
            print(f"      {h}")
        kw = mgr.search_memories("u", q, limit=3)
        print(f"    search_memories(关键词) -> {len(kw)} 条")
        for r in kw:
            print(f"      content={r.content}")

    hr("6. 一致性检查")
    ids_sql = {m.id for m in mgr._storage.load("u")}
    ids_vec = {r["memory_id"] for r in store.list_all("u")}
    print(f"  sqlite ids = {len(ids_sql)}  vector ids = {len(ids_vec)}")
    print(f"  缺向量   = {sorted(ids_sql - ids_vec)}")
    print(f"  孤儿向量 = {sorted(ids_vec - ids_sql)}")
    print(f"  embedding_status = {mgr.embedding_status()}")

    hr("7. 主对话路径到底读不读向量库？（关键）")
    print("  get_context_prompt 是每轮对话注入 prompt 的唯一入口。")
    calls: list[str] = []
    real_get_emb = store.get_embeddings
    real_vs_search = store.search

    def ge_spy(user_id, memory_ids=None):
        calls.append(f"vector_store.get_embeddings({len(memory_ids) if memory_ids else 'all'} ids)")
        return real_get_emb(user_id, memory_ids)

    def vs_spy(user_id, qv, top_k=5):
        calls.append("vector_store.search")
        return real_vs_search(user_id, qv, top_k=top_k)

    store.get_embeddings = ge_spy  # type: ignore[method-assign]
    store.search = vs_spy  # type: ignore[method-assign]
    real_embed_batch = emb.embed_batch
    real_embed = emb.embed
    n_embed = {"n": 0}

    def e_spy(text):
        n_embed["n"] += 1
        return real_embed(text)

    def eb_spy(texts):
        calls.append(f"embedder.embed_batch({len(texts)} texts) [慢路径]")
        return real_embed_batch(texts)

    emb.embed = e_spy  # type: ignore[method-assign]
    emb.embed_batch = eb_spy  # type: ignore[method-assign]

    prompt = mgr.get_context_prompt("u", limit=8, query="宠物")
    print(f"  get_context_prompt -> {len(prompt)} chars")
    for line in prompt.splitlines():
        print(f"    | {line}")
    print("  期间发生的调用：")
    for c in calls or ["（没有任何向量相关调用）"]:
        print(f"    - {c}")
    print(f"  embedder.embed 调用次数 = {n_embed['n']}（应为 1，只 embed 查询）")
    if "vector_store.get_embeddings" in " ".join(calls):
        print("  ✓ 结论：主对话路径现在【读】memory_vectors 表，复用已建好的向量。")
    elif "embed_batch" in " ".join(calls):
        print("  !! 仍在走慢路径：每轮重新 embed 所有候选记忆。")
    else:
        print("  ?? 两条路径都没走，检查覆盖率判定。")

    store.get_embeddings = real_get_emb  # type: ignore[method-assign]
    store.search = real_vs_search  # type: ignore[method-assign]
    emb.embed = real_embed  # type: ignore[method-assign]
    emb.embed_batch = real_embed_batch  # type: ignore[method-assign]

    store.close()
    print("\n探针完成。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception:
        traceback.print_exc()
        sys.exit(1)
