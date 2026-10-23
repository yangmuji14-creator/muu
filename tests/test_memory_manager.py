"""记忆管理器测试：混合排序、索引维护、降级路径。

覆盖:
- embedding_status()：结构完整，ready 与 embedder 一致
- reindex_all()：幂等（第二次全 skipped）、force 重建、缺 embedder 时安全返回
- _hybrid_rank_prompt()：语义 0.5 + 重要度 0.3 + 时效 0.2 的混合排序
- 低相似度且无关键词重叠的候选必须被过滤（MIN_SEMANTIC_SIMILARITY = 0.35）
- get_context_prompt() 在 embedder 缺失时降级到重要度排序，不抛异常

全部使用 tmp_path 隔离，不碰真实 data/。
"""

from datetime import datetime, timedelta

import numpy as np
import pytest

from core.memory.manager import MemoryManager
from core.memory.models import Memory


def unit(seed: int, dim: int = 8) -> list[float]:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=dim).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


class FakeEmbedder:
    """可预测的嵌入器：词表映射到固定向量，便于断言排序。"""

    def __init__(self, mapping: dict[str, list[float]], dim: int = 8):
        self._mapping = mapping
        self._dim = dim
        self.available = True
        self.init_error = None
        self.dimension = dim
        self.dim = dim
        self.model_source = "fake://test"

    def _vec(self, text: str) -> list[float]:
        for key, vec in self._mapping.items():
            if key in text:
                return vec
        return unit(4242, self._dim)

    def embed(self, text: str) -> list[float]:
        return self._vec(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class DisabledEmbedder:
    available = False
    init_error = "model missing"
    dimension = 0
    dim = 0
    model_source = ""

    def embed(self, text):
        return None

    def embed_batch(self, texts):
        return None


@pytest.fixture()
def mgr(tmp_path):
    """带真实 VectorStore 的 manager，嵌入器用假的。"""
    from core.memory.vector_store import VectorStore

    emb = FakeEmbedder({"查询": unit(1), "相关": unit(1), "无关": unit(99)})
    vs = VectorStore(tmp_path / "vectors.db")
    m = MemoryManager(tmp_path, embedder=emb, vector_store=vs)
    yield m
    vs.close()


class TestEmbeddingStatus:
    def test_structure(self, mgr):
        status = mgr.embedding_status()
        assert set(status) >= {
            "ready", "dimension", "model_source", "error", "indexed_by_user", "missing",
        }
        assert status["ready"] is True
        assert status["dimension"] == 8

    def test_missing_counts_unindexed(self, mgr):
        mgr.add_memory_sync("u1", "他养了一只猫", level=4)
        mgr.add_memory_sync("u1", "他喜欢烤红薯", level=3)
        status = mgr.embedding_status()
        assert status["indexed_by_user"]["u1"]["memories"] == 2
        assert status["indexed_by_user"]["u1"]["indexed"] == 2
        assert status["missing"] == 0

    def test_disabled_embedder_reports_not_ready(self, tmp_path):
        from core.memory.vector_store import VectorStore

        vs = VectorStore(tmp_path / "v.db")
        m = MemoryManager(tmp_path, embedder=DisabledEmbedder(), vector_store=vs)
        status = m.embedding_status()
        assert status["ready"] is False
        assert status["error"] == "model missing"
        vs.close()

    def test_no_embedder_does_not_raise(self, tmp_path):
        m = MemoryManager(tmp_path)
        status = m.embedding_status()
        assert status["ready"] is False
        assert status["dimension"] == 0


class TestReindex:
    """reindex_all 针对的是「写入时没有向量」的历史记忆。

    正常写入路径会立刻建索引，所以这些用例先把向量清空来还原该场景。
    """

    @staticmethod
    def _strip_vectors(mgr, *user_ids):
        for uid in user_ids:
            mgr._vector_store.delete_all(uid)

    def test_first_run_indexes_all(self, mgr):
        mgr.add_memory_sync("u1", "相关的事情", level=4)
        mgr.add_memory_sync("u1", "别的事情", level=3)
        self._strip_vectors(mgr, "u1")
        assert mgr.embedding_status()["missing"] == 2

        result = mgr.reindex_all()
        assert result["users"] == 1
        assert result["indexed"] == 2
        assert result["failed"] == 0
        assert mgr.embedding_status()["missing"] == 0

    def test_second_run_is_idempotent(self, mgr):
        mgr.add_memory_sync("u1", "相关的事情", level=4)
        self._strip_vectors(mgr, "u1")
        first = mgr.reindex_all()
        assert first["indexed"] == 1

        again = mgr.reindex_all()
        assert again["indexed"] == 0
        assert again["skipped"] == 1

    def test_force_rebuilds(self, mgr):
        mgr.add_memory_sync("u1", "相关的事情", level=4)
        first = mgr.reindex_all(force=True)
        assert first["indexed"] == 1

    def test_specific_user_only(self, mgr):
        mgr.add_memory_sync("u1", "相关的事情", level=4)
        mgr.add_memory_sync("u2", "别的事情", level=4)
        self._strip_vectors(mgr, "u1", "u2")

        result = mgr.reindex_all(user_id="u1")
        assert result["users"] == 1
        assert mgr.embedding_status()["indexed_by_user"]["u1"]["indexed"] == 1
        assert mgr.embedding_status()["indexed_by_user"]["u2"]["indexed"] == 0

    def test_missing_embedder_returns_zeros(self, tmp_path):
        m = MemoryManager(tmp_path)
        assert m.reindex_all() == {"users": 0, "indexed": 0, "skipped": 0, "failed": 0}

    def test_disabled_embedder_returns_zeros(self, tmp_path):
        from core.memory.vector_store import VectorStore

        vs = VectorStore(tmp_path / "v.db")
        m = MemoryManager(tmp_path, embedder=DisabledEmbedder(), vector_store=vs)
        assert m.reindex_all()["indexed"] == 0
        vs.close()


class TestHybridRanking:
    def _mem(self, content, level, days_old=0):
        created = (datetime.now() - timedelta(days=days_old)).isoformat()
        return Memory(id=f"m_{abs(hash(content)) % 10000}", content=content,
                      level=level, created_at=created, last_accessed=created)

    def test_semantically_relevant_ranks_first(self, mgr):
        query = "查询"
        qv = unit(1)
        cands = [self._mem("无关的内容", 5), self._mem("相关的内容", 3)]
        vecs = [unit(99), unit(1)]
        out = mgr._hybrid_rank_prompt(cands, vecs, qv, limit=2, query=query)
        assert "相关的内容" in out
        assert out.index("相关的内容") < out.index("无关的内容") if "无关的内容" in out else True

    def test_low_similarity_without_keyword_filtered_out(self, mgr):
        # 语义相似度低（正交向量 → 0.0）且无关键词重叠 → 必须被丢弃
        cands = [self._mem("完全无关的话题", 5)]
        out = mgr._hybrid_rank_prompt(cands, [unit(99)], unit(1), limit=5, query="查询")
        assert out == ""

    def test_low_similarity_but_keyword_overlap_kept(self, mgr):
        # 相似度低但共享关键词 → 保留
        cands = [self._mem("查询这件事的细节", 3)]
        out = mgr._hybrid_rank_prompt(cands, [unit(99)], unit(1), limit=5, query="查询")
        assert "查询这件事的细节" in out

    def test_dedup_by_content_prefix(self, mgr):
        text = "重复内容前缀一模一样"
        cands = [self._mem(text, 4), self._mem(text, 3)]
        out = mgr._hybrid_rank_prompt(cands, [unit(1), unit(1)], unit(1), limit=5, query="查询")
        assert out.count(text) == 1

    def test_limit_respected(self, mgr):
        cands = [self._mem(f"相关内容{i}", 3) for i in range(6)]
        out = mgr._hybrid_rank_prompt(cands, [unit(1)] * 6, unit(1), limit=2, query="查询")
        assert out.count("相关内容") == 2

    def test_empty_candidates_returns_empty(self, mgr):
        assert mgr._hybrid_rank_prompt([], [], unit(1), limit=5, query="查询") == ""

    def test_bad_created_at_does_not_crash(self, mgr):
        mem = Memory(id="m1", content="相关内容", level=3, created_at="not-a-date")
        out = mgr._hybrid_rank_prompt([mem], [unit(1)], unit(1), limit=5, query="查询")
        assert "相关内容" in out


class TestContextPromptFallback:
    def test_no_embedder_falls_back_to_importance(self, tmp_path):
        m = MemoryManager(tmp_path)
        m.add_memory_sync("u1", "低重要度记忆", level=2)
        m.add_memory_sync("u1", "高重要度记忆", level=5)
        out = m.get_context_prompt("u1", query="随便问问")
        assert "高重要度记忆" in out

    def test_no_memories_returns_empty(self, tmp_path):
        m = MemoryManager(tmp_path)
        assert m.get_context_prompt("nobody", query="x") == ""

    def test_min_similarity_threshold_value(self):
        """阈值是行为契约，改动会静默影响召回质量。"""
        assert MemoryManager.MIN_SEMANTIC_SIMILARITY == 0.35


def _old_memory(mem_id: str, days: int, level: int = 2, category: str = "other") -> Memory:
    """造一条 N 天前的记忆（时间衰减靠 created_at 推进）。"""
    created = (datetime.now() - timedelta(days=days)).isoformat()
    return Memory(
        id=mem_id,
        content=f"{mem_id} 的内容",
        level=level,
        category=category,
        created_at=created,
        last_accessed=created,
    )


class TestDecaySingleSource:
    """遗忘评分只允许一套公式。

    历史上 `MemoryManager._update_decay` 与 `MemoryDecaySystem.calculate_forget_score`
    各算各的（前者 `days*0.01*importance*recency - access/50`，后者
    `days*base*level_mult*cat_mod - access*0.005 - 近期奖励`），导致详情页显示的
    遗忘指数和清理时真正用的分数不是一个数。`_update_decay` 已删除。
    """

    def test_update_decay_removed(self):
        assert not hasattr(MemoryManager, "_update_decay"), (
            "_update_decay 已随衰减统一删除；别再引回第二套公式"
        )

    def test_cleanup_uses_decay_system_score(self, tmp_path):
        m = MemoryManager(tmp_path, max_memories=1)
        old = _old_memory("m_old", days=60, level=2)
        new = _old_memory("m_new", days=0, level=5)
        out = m._cleanup_old_memories([old, new])
        expected_old = m._decay_system.calculate_forget_score(old)
        assert old.forget_score == pytest.approx(expected_old)
        # 上限 1 条 → 保留高重要度的新的
        kept_ids = {x.id for x in out}
        assert "m_new" in kept_ids

    def test_archived_flag_is_persisted(self, tmp_path):
        """归档必须写进 archived 列，不能只是个内存标记。"""
        from core.memory.storage import MemoryStorage

        m = MemoryManager(tmp_path, max_memories=500)
        mem = _old_memory("m_ancient", days=4000, level=1, category="other")
        m._cleanup_old_memories([mem])
        assert mem.archived is True, "level 1 且极老的记忆应被归档"

        m._storage.save("u1", [mem])
        reloaded = MemoryStorage(tmp_path).get("u1", "m_ancient")
        assert reloaded is not None
        assert reloaded.archived is True

    def test_fresh_memory_not_archived(self, tmp_path):
        m = MemoryManager(tmp_path)
        mem = _old_memory("m_fresh", days=0, level=1)
        m._cleanup_old_memories([mem])
        assert mem.archived is False


class TestArchivedVisibility:
    """归档的记忆：管理界面看得到，喂给模型的上下文看不到。"""

    def test_get_memories_includes_archived_by_default(self, tmp_path):
        m = MemoryManager(tmp_path)
        mem = m.add_memory_sync("u1", "归档候选记忆内容", level=3)
        mem.archived = True
        m._storage.save("u1", [mem])
        listed = m.get_memories("u1", limit=10)
        assert [x.id for x in listed] == [mem.id]

    def test_get_memories_can_exclude_archived(self, tmp_path):
        m = MemoryManager(tmp_path)
        mem = m.add_memory_sync("u1", "归档候选记忆内容", level=3)
        mem.archived = True
        m._storage.save("u1", [mem])
        assert m.get_memories("u1", limit=10, include_archived=False) == []

    def test_context_prompt_skips_archived(self, tmp_path):
        """「已经忘掉的事」不能再被注入 prompt。"""
        m = MemoryManager(tmp_path)
        mem = m.add_memory_sync("u1", "我养过一只叫团子的猫", level=5)
        mem.archived = True
        m._storage.save("u1", [mem])
        assert m.get_context_prompt("u1", query="团子") == ""

