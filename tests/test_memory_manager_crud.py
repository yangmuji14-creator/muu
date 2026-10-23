"""`MemoryManager` 的 CRUD / 衰减 / 上下文编排测试

补的是 `tests/test_memory_manager.py` 没覆盖的那半边：增删改查、过滤条件、
衰减触发、向量维护的异常分支、导入导出。

全部 ``tmp_path`` 隔离。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from core.memory.manager import MemoryManager, _keyword_tokens
from core.memory.models import Memory
from core.memory.scorer import MemoryScorer
from core.memory.vector_store import VectorStore


def unit(seed: int, dim: int = 8) -> list[float]:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=dim).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


class FakeEmbedder:
    """词表映射到固定向量；没命中就给同一个兜底向量。"""

    def __init__(self, mapping=None, dim=8, fail=False, empty=False):
        self._mapping = mapping or {"查询": unit(1), "相关": unit(1)}
        self._dim = dim
        self.available = True
        self.init_error = None
        self.dimension = dim
        self.dim = dim
        self.model_source = "fake://test"
        self._fail = fail
        self._empty = empty

    def _vec(self, text):
        if self._empty:
            return None
        if self._fail:
            raise RuntimeError("embed boom")
        for key, vec in self._mapping.items():
            if key in text:
                return vec
        return unit(4242, self._dim)

    def embed(self, text):
        return self._vec(text)

    def embed_batch(self, texts):
        if self._empty:
            return []
        return [self._vec(t) for t in texts]


@pytest.fixture()
def vs(tmp_path):
    store = VectorStore(tmp_path / "vectors.db")
    yield store
    store.close()


@pytest.fixture()
def mgr(tmp_path, vs):
    return MemoryManager(tmp_path, embedder=FakeEmbedder(), vector_store=vs)


def _old(mem_id="m", days=0, level=3, category="other", **kwargs) -> Memory:
    created = (datetime.now() - timedelta(days=days)).isoformat()
    return Memory(id=mem_id, content=kwargs.pop("content", "内容"),
                  level=level, category=category,
                  created_at=created, last_accessed=created, **kwargs)


# --------------------------------------------------------------------------- #
# 基础属性
# --------------------------------------------------------------------------- #


class TestBasics:
    def test_data_dir(self, mgr, tmp_path) -> None:
        assert mgr.data_dir == tmp_path

    def test_set_llm(self, mgr) -> None:
        sentinel = object()
        mgr.set_llm(sentinel)
        assert mgr._llm_scorer._llm is sentinel


class TestKeywordTokens:
    def test_single_char_cjk_skipped(self) -> None:
        """单字块不够成词，直接跳过（不然 2-gram 会造出空 token）。"""
        assert _keyword_tokens("我 查") == set()

    def test_two_char_gets_bigram(self) -> None:
        assert _keyword_tokens("查询") == {"查询"}

    def test_long_cjk_gets_all_bigrams(self) -> None:
        tokens = _keyword_tokens("查询这件事")
        assert {"查询", "询这", "这件", "件事"} <= tokens

    def test_english_and_numbers(self) -> None:
        assert {"python", "2026"} <= _keyword_tokens("python 2026")

    def test_empty(self) -> None:
        assert _keyword_tokens("") == set()
        assert _keyword_tokens(None) == set()


# --------------------------------------------------------------------------- #
# 增
# --------------------------------------------------------------------------- #


class TestAddMemory:
    async def test_rule_scoring(self, mgr) -> None:
        memory = await mgr.add_memory("u", "我的生日是5月20日", level=None)
        assert memory is not None
        assert memory.level >= 4

    async def test_explicit_level_skips_scorer(self, mgr) -> None:
        memory = await mgr.add_memory("u", "随便什么内容", level=4)
        assert memory is not None
        assert memory.level == 4

    async def test_llm_path_overrides(self, mgr) -> None:
        """规则不确定时用 LLM 结论覆盖 level 与 category。"""
        mgr.set_llm(object())
        mgr._scorer.needs_llm_evaluation = lambda content: True

        async def fake_evaluate(content):
            return 5, "personal"

        mgr._llm_scorer.evaluate = fake_evaluate
        memory = await mgr.add_memory("u", "他在做一个项目", level=None)
        assert memory is not None
        assert memory.level == 5
        assert memory.category == "personal"

    async def test_llm_none_keeps_rule_result(self, mgr) -> None:
        """LLM 返回 None 时保留规则评分结果（不是丢弃这条记忆）。"""
        mgr.set_llm(object())
        mgr._scorer.needs_llm_evaluation = lambda content: True

        async def fake_evaluate(content):
            return None

        mgr._llm_scorer.evaluate = fake_evaluate
        content = "我喜欢跑步"
        memory = await mgr.add_memory("u", content, level=None)
        assert memory is not None
        assert memory.level == MemoryScorer.score(content)[0]
        assert memory.category == Memory.classify(content)

    async def test_llm_skipped_without_instance(self, mgr) -> None:
        """没有 LLM 实例时 needs_llm_evaluation 为真也不调用。"""
        mgr._scorer.needs_llm_evaluation = lambda content: True

        async def boom(content):
            raise AssertionError("不该被调用")

        mgr._llm_scorer.evaluate = boom
        memory = await mgr.add_memory("u", "我喜欢跑步", level=None)
        assert memory is not None

    async def test_llm_skipped_when_rules_confident(self, mgr) -> None:
        """规则评分确信时不调 LLM（needs_llm_evaluation 为假）。"""
        mgr.set_llm(object())

        async def boom(content):
            raise AssertionError("不该被调用")

        mgr._llm_scorer.evaluate = boom
        memory = await mgr.add_memory("u", "我叫小林，今年24岁", level=None)
        assert memory is not None

    async def test_llm_keeps_explicit_category(self, mgr) -> None:
        """调用方显式给了 category 时，LLM 的 category 不能覆盖。"""
        mgr.set_llm(object())
        mgr._scorer.needs_llm_evaluation = lambda content: True

        async def fake_evaluate(content):
            return 5, "emotion"

        mgr._llm_scorer.evaluate = fake_evaluate
        memory = await mgr.add_memory("u", "我喜欢跑步", level=None,
                                      category="personal")
        assert memory is not None
        assert memory.level == 5
        assert memory.category == "personal"

    def test_sync_uses_rule_scorer(self, mgr) -> None:
        memory = mgr.add_memory_sync("u", "我叫小林")
        assert memory is not None
        assert memory.level >= 4

    def test_low_importance_dropped(self, mgr) -> None:
        assert mgr.add_memory_sync("u", "嗯嗯", level=1) is None
        assert mgr._storage.count("u") == 0

    def test_category_auto_classified(self, mgr) -> None:
        memory = mgr.add_memory_sync("u", "我喜欢吃火锅", level=3)
        assert memory is not None
        assert memory.category in {"emotion", "preference"}

    def test_explicit_category_kept(self, mgr) -> None:
        memory = mgr.add_memory_sync("u", "我喜欢吃火锅", level=3, category="personal")
        assert memory is not None
        assert memory.category == "personal"

    def test_confidence_from_content(self, mgr) -> None:
        from core.memory.models import Memory as M

        sure = mgr.add_memory_sync("u", "我的生日是5月20日", level=4)
        vague = mgr.add_memory_sync("u", "他好像要搬家了", level=4)
        assert sure is not None and vague is not None
        assert sure.confidence == M.classify_confidence("我的生日是5月20日")
        assert vague.confidence == M.classify_confidence("他好像要搬家了")
        assert sure.confidence > vague.confidence

    def test_conflict_supersedes_old(self, mgr) -> None:
        old = mgr.add_memory_sync("u", "我喜欢猫", level=4)
        assert old is not None
        new = mgr.add_memory_sync("u", "我不喜欢猫", level=4)
        assert new is not None
        reloaded = mgr.get_memory("u", old.id)
        assert reloaded is not None
        assert reloaded.superseded_by == new.id
        assert old.id in new.related_memory_ids

    def test_conflict_ignores_already_superseded(self, mgr) -> None:
        """已被取代的记忆不再参与冲突检测，但仍然活跃的那条会。"""
        first = mgr.add_memory_sync("u", "我喜欢猫", level=4)
        assert first is not None
        second = mgr.add_memory_sync("u", "我不喜欢猫", level=4)
        assert second is not None
        assert mgr.get_memory("u", first.id).superseded_by == second.id

        third = mgr.add_memory_sync("u", "我喜欢猫", level=4)
        assert third is not None
        # first 已被取代 → 跳过；second 仍活跃 → 被 third 取代
        assert third.related_memory_ids == [second.id]
        assert mgr.get_memory("u", first.id).superseded_by == second.id
        assert mgr.get_memory("u", second.id).superseded_by == third.id

    def test_cleanup_triggered_past_cap(self, tmp_path, vs) -> None:
        manager = MemoryManager(tmp_path, max_memories=1,
                                embedder=FakeEmbedder(), vector_store=vs)
        manager.add_memory_sync("u", "第一条记忆内容", level=5)
        manager.add_memory_sync("u", "第二条记忆内容", level=3)
        assert manager._storage.count("u") == 1


class TestIndexMemory:
    def test_none_embedder_noop(self, tmp_path, vs) -> None:
        manager = MemoryManager(tmp_path, vector_store=vs)
        memory = _old("m1")
        manager._index_memory("u", memory)
        assert vs.count("u") == 0

    def test_none_vector_store_noop(self, tmp_path) -> None:
        manager = MemoryManager(tmp_path, embedder=FakeEmbedder())
        manager._index_memory("u", _old("m1"))  # 不该抛

    def test_disabled_embedder_noop(self, tmp_path, vs) -> None:
        class Disabled:
            available = False

        manager = MemoryManager(tmp_path, embedder=Disabled(), vector_store=vs)
        manager._index_memory("u", _old("m1"))
        assert vs.count("u") == 0

    def test_empty_vector_noop(self, tmp_path, vs) -> None:
        manager = MemoryManager(tmp_path, embedder=FakeEmbedder(empty=True),
                                vector_store=vs)
        manager._index_memory("u", _old("m1"))
        assert vs.count("u") == 0

    def test_embed_exception_swallowed(self, tmp_path, vs) -> None:
        manager = MemoryManager(tmp_path, embedder=FakeEmbedder(fail=True),
                                vector_store=vs)
        manager._index_memory("u", _old("m1"))  # 不该抛
        assert vs.count("u") == 0

    def test_success_writes_vector(self, mgr, vs) -> None:
        memory = mgr.add_memory_sync("u", "相关的内容", level=4)
        assert memory is not None
        assert vs.count("u") == 1


# --------------------------------------------------------------------------- #
# 查
# --------------------------------------------------------------------------- #


class TestGetMemories:
    def _seed(self, mgr) -> None:
        mgr._storage.save("u", [
            Memory(id="keep", content="保留", level=3),
            Memory(id="super", content="被取代", level=3, superseded_by="keep"),
            Memory(id="arch", content="已归档", level=3, archived=True),
            Memory(id="low", content="太低", level=1),
            Memory(id="high", content="太高", level=5),
            Memory(id="cat", content="别的分类", level=3, category="emotion"),
            Memory(id="conf", content="低置信", level=3, confidence=0.1),
        ])

    def test_default_excludes_superseded(self, mgr) -> None:
        self._seed(mgr)
        ids = {m.id for m in mgr.get_memories("u", limit=99)}
        assert "super" not in ids
        assert "keep" in ids

    def test_include_superseded(self, mgr) -> None:
        self._seed(mgr)
        ids = {m.id for m in mgr.get_memories("u", limit=99, include_superseded=True)}
        assert "super" in ids

    def test_archived_included_by_default(self, mgr) -> None:
        self._seed(mgr)
        assert "arch" in {m.id for m in mgr.get_memories("u", limit=99)}

    def test_archived_excluded(self, mgr) -> None:
        self._seed(mgr)
        assert "arch" not in {m.id for m in mgr.get_memories("u", limit=99, include_archived=False)}

    def test_level_range(self, mgr) -> None:
        self._seed(mgr)
        ids = {m.id for m in mgr.get_memories("u", level_min=3, level_max=3, limit=99)}
        assert "low" not in ids and "high" not in ids and "keep" in ids

    def test_category_filter(self, mgr) -> None:
        self._seed(mgr)
        ids = {m.id for m in mgr.get_memories("u", category="emotion", limit=99)}
        assert ids == {"cat"}

    def test_min_confidence_filter(self, mgr) -> None:
        self._seed(mgr)
        assert "conf" not in {m.id for m in mgr.get_memories("u", min_confidence=0.5, limit=99)}

    def test_limit(self, mgr) -> None:
        self._seed(mgr)
        assert len(mgr.get_memories("u", limit=2)) == 2

    def test_sorted_by_level_then_access(self, mgr) -> None:
        mgr._storage.save("u", [
            Memory(id="a", content="a", level=3, last_accessed="2026-01-01T00:00:00"),
            Memory(id="b", content="b", level=5, last_accessed="2026-01-01T00:00:00"),
        ])
        assert [m.id for m in mgr.get_memories("u")] == ["b", "a"]

    def test_empty_user(self, mgr) -> None:
        assert mgr.get_memories("nobody") == []


class TestApplyDecay:
    def test_returns_affected_count(self, mgr) -> None:
        mgr._storage.save("u", [
            _old("fresh", days=0, level=3),
            _old("stale", days=90, level=2, category="other"),
        ])
        assert mgr.apply_decay("u") >= 1

    def test_persists_forget_score(self, mgr) -> None:
        mgr._storage.save("u", [_old("stale", days=200, level=2, category="other")])
        mgr.apply_decay("u")
        reloaded = mgr.get_memory("u", "stale")
        assert reloaded is not None
        assert reloaded.forget_score > 0

    def test_skips_archived_and_superseded(self, mgr) -> None:
        mgr._storage.save("u", [
            _old("arch", days=200, level=2, archived=True),
            _old("super", days=200, level=2, superseded_by="x"),
        ])
        assert mgr.apply_decay("u") == 0

    def test_empty_user(self, mgr) -> None:
        assert mgr.apply_decay("nobody") == 0


class TestListAndSearch:
    def test_list_all_paginates(self, mgr) -> None:
        mgr._storage.save("u", [_old(f"m{i}", level=i + 1) for i in range(5)])
        page, total = mgr.list_all_memories("u", offset=1, limit=2)
        assert total == 5
        assert len(page) == 2

    def test_list_all_excludes_superseded(self, mgr) -> None:
        mgr._storage.save("u", [
            _old("a"), _old("b", superseded_by="a"),
        ])
        _, total = mgr.list_all_memories("u")
        assert total == 1

    def test_search_touches_access(self, mgr) -> None:
        memory = mgr.add_memory_sync("u", "我喜欢跑步", level=4)
        assert memory is not None
        results = mgr.search_memories("u", "跑步")
        assert results[0].access_count == 1
        assert mgr.get_memory("u", memory.id).access_count == 1

    def test_semantic_search(self, mgr) -> None:
        memory = mgr.add_memory_sync("u", "相关的内容", level=4)
        assert memory is not None
        hits = mgr.semantic_search("u", "查询", top_k=3)
        assert hits and hits[0]["memory_id"] == memory.id

    def test_semantic_search_without_embedder(self, tmp_path, vs) -> None:
        manager = MemoryManager(tmp_path, vector_store=vs)
        assert manager.semantic_search("u", "查询") == []

    def test_semantic_search_without_store(self, tmp_path) -> None:
        manager = MemoryManager(tmp_path, embedder=FakeEmbedder())
        assert manager.semantic_search("u", "查询") == []

    def test_semantic_search_empty_vector(self, tmp_path, vs) -> None:
        manager = MemoryManager(tmp_path, embedder=FakeEmbedder(empty=True),
                                vector_store=vs)
        assert manager.semantic_search("u", "查询") == []

    def test_semantic_search_exception(self, tmp_path, vs) -> None:
        manager = MemoryManager(tmp_path, embedder=FakeEmbedder(fail=True),
                                vector_store=vs)
        assert manager.semantic_search("u", "查询") == []


class TestMemoryDetail:
    def test_calculates_forget_score(self, mgr) -> None:
        memory = mgr.add_memory_sync("u", "旧内容记忆", level=2)
        assert memory is not None
        # 把创建时间改到过去，逼出非零遗忘分
        stored = mgr.get_memory("u", memory.id)
        assert stored is not None
        stored.created_at = (datetime.now() - timedelta(days=200)).isoformat()
        mgr._storage.update("u", stored)

        detail = mgr.memory_detail("u", memory.id)
        assert detail is not None
        assert detail.forget_score > 0

    def test_missing_returns_none(self, mgr) -> None:
        assert mgr.memory_detail("u", "nope") is None

    def test_calc_exception_keeps_stored_value(self, mgr, monkeypatch) -> None:
        memory = mgr.add_memory_sync("u", "内容记忆", level=3)
        assert memory is not None

        def boom(self, mem):
            raise RuntimeError("calc failed")

        monkeypatch.setattr(type(mgr._decay_system), "calculate_forget_score", boom)
        detail = mgr.memory_detail("u", memory.id)
        assert detail is not None
        assert detail.forget_score == 0.0

    def test_does_not_write(self, mgr) -> None:
        memory = mgr.add_memory_sync("u", "内容记忆", level=3)
        assert memory is not None
        mgr.memory_detail("u", memory.id)
        assert mgr.get_memory("u", memory.id).forget_score == 0.0


# --------------------------------------------------------------------------- #
# 向量维护的异常分支
# --------------------------------------------------------------------------- #


class TestReindexBranches:
    def test_skips_empty_user_id(self, tmp_path, vs, monkeypatch) -> None:
        manager = MemoryManager(tmp_path, embedder=FakeEmbedder(), vector_store=vs)
        monkeypatch.setattr(type(manager._storage), "list_users",
                            lambda self: ["", "u1"])
        result = manager.reindex_all()
        assert result["users"] == 1

    def test_load_failure_counts_failed(self, tmp_path, vs, monkeypatch) -> None:
        manager = MemoryManager(tmp_path, embedder=FakeEmbedder(), vector_store=vs)
        monkeypatch.setattr(type(manager._storage), "list_users", lambda self: ["u"])

        def boom(self, uid):
            raise RuntimeError("load failed")

        monkeypatch.setattr(type(manager._storage), "load", boom)
        result = manager.reindex_all()
        assert result["failed"] == 1
        assert result["indexed"] == 0

    def test_batch_mismatch_counts_failed(self, tmp_path, vs, monkeypatch) -> None:
        manager = MemoryManager(tmp_path, embedder=FakeEmbedder(), vector_store=vs)
        manager.add_memory_sync("u", "内容一", level=4)
        manager.add_memory_sync("u", "内容二", level=4)
        vs.delete_all("u")
        monkeypatch.setattr(type(manager._embedder), "embed_batch",
                            lambda self, texts: [unit(1)])
        result = manager.reindex_all()
        assert result["failed"] == 2

    def test_insert_failure_counts_failed(self, tmp_path, vs, monkeypatch) -> None:
        manager = MemoryManager(tmp_path, embedder=FakeEmbedder(), vector_store=vs)
        manager.add_memory_sync("u", "内容一", level=4)
        vs.delete_all("u")

        def boom(*args, **kwargs):
            raise RuntimeError("insert failed")

        monkeypatch.setattr(type(vs), "add", boom)
        result = manager.reindex_all()
        assert result["failed"] == 1

    def test_existing_ids_without_store(self, tmp_path) -> None:
        manager = MemoryManager(tmp_path, embedder=FakeEmbedder())
        assert manager._existing_vector_ids("u") == set()

    def test_existing_ids_list_failure(self, tmp_path, vs, monkeypatch) -> None:
        manager = MemoryManager(tmp_path, embedder=FakeEmbedder(), vector_store=vs)

        def boom(uid):
            raise RuntimeError("list failed")

        monkeypatch.setattr(type(vs), "list_all", boom)
        assert manager._existing_vector_ids("u") == set()

    def test_embedding_status_swallows_errors(self, tmp_path, vs, monkeypatch) -> None:
        manager = MemoryManager(tmp_path, embedder=FakeEmbedder(), vector_store=vs)

        def boom(self):
            raise RuntimeError("list users failed")

        monkeypatch.setattr(type(manager._storage), "list_users", boom)
        status = manager.embedding_status()
        assert status["ready"] is True
        assert status["indexed_by_user"] == {}


# --------------------------------------------------------------------------- #
# 删 / 改
# --------------------------------------------------------------------------- #


class TestDeleteAndUpdate:
    def test_delete_removes_vector(self, mgr, vs) -> None:
        memory = mgr.add_memory_sync("u", "相关内容", level=4)
        assert memory is not None
        assert vs.count("u") == 1
        assert mgr.delete_memory("u", memory.id) is True
        assert vs.count("u") == 0
        assert mgr.get_memory("u", memory.id) is None

    def test_delete_missing(self, mgr) -> None:
        assert mgr.delete_memory("u", "nope") is False

    def test_delete_without_store(self, tmp_path) -> None:
        manager = MemoryManager(tmp_path, embedder=FakeEmbedder())
        memory = manager.add_memory_sync("u", "内容记忆", level=4)
        assert memory is not None
        assert manager.delete_memory("u", memory.id) is True

    def test_update_content(self, mgr) -> None:
        memory = mgr.add_memory_sync("u", "旧内容", level=3)
        assert memory is not None
        updated = mgr.update_memory("u", memory.id, content="新内容")
        assert updated is not None
        assert updated.content == "新内容"
        assert mgr.get_memory("u", memory.id).content == "新内容"

    def test_update_level_and_category(self, mgr) -> None:
        memory = mgr.add_memory_sync("u", "内容", level=2)
        assert memory is not None
        updated = mgr.update_memory("u", memory.id, level=5, category="personal")
        assert updated is not None
        assert updated.level == 5
        assert updated.category == "personal"

    def test_update_touches_last_accessed(self, mgr) -> None:
        memory = mgr.add_memory_sync("u", "内容", level=3)
        assert memory is not None
        before = mgr.get_memory("u", memory.id).last_accessed
        updated = mgr.update_memory("u", memory.id, level=4)
        assert updated is not None
        assert updated.last_accessed >= before

    def test_update_content_reindexes(self, mgr, vs) -> None:
        memory = mgr.add_memory_sync("u", "旧内容", level=3)
        assert memory is not None
        mgr.update_memory("u", memory.id, content="相关的内容")
        assert vs.count("u") == 1

    def test_update_missing(self, mgr) -> None:
        assert mgr.update_memory("u", "nope", content="x") is None

    def test_update_without_embedder(self, tmp_path) -> None:
        manager = MemoryManager(tmp_path)
        memory = manager.add_memory_sync("u", "内容", level=3)
        assert memory is not None
        assert manager.update_memory("u", memory.id, content="新内容") is not None


# --------------------------------------------------------------------------- #
# 上下文 prompt
# --------------------------------------------------------------------------- #


class TestContextPrompt:
    def test_hybrid_path_used_with_query(self, mgr) -> None:
        mgr.add_memory_sync("u", "相关的内容", level=4)
        mgr.add_memory_sync("u", "别的东西", level=4)
        prompt = mgr.get_context_prompt("u", query="查询")
        assert prompt.startswith("【与当前话题相关的记忆】")
        assert "相关的内容" in prompt

    def test_hybrid_falls_back_on_embed_error(self, tmp_path, vs) -> None:
        manager = MemoryManager(tmp_path, embedder=FakeEmbedder(fail=True),
                                vector_store=vs)
        manager.add_memory_sync("u", "内容记忆", level=4)
        prompt = manager.get_context_prompt("u", query="查询")
        assert "内容记忆" in prompt

    def test_hybrid_falls_back_on_batch_mismatch(self, mgr, monkeypatch) -> None:
        mgr.add_memory_sync("u", "内容记忆", level=4)
        mgr.add_memory_sync("u", "另一条记忆", level=4)
        monkeypatch.setattr(type(mgr._embedder), "embed_batch",
                            lambda self, texts: [unit(1)])
        prompt = mgr.get_context_prompt("u", query="查询")
        assert "【与当前话题相关的记忆】" in prompt

    def test_query_ignored_without_embedder(self, tmp_path) -> None:
        manager = MemoryManager(tmp_path)
        manager.add_memory_sync("u", "内容记忆", level=4)
        prompt = manager.get_context_prompt("u", query="查询")
        assert "内容记忆" in prompt

    def test_embed_none_falls_back(self, mgr, monkeypatch) -> None:
        """embed() 返回 None（不是抛异常）也要走降级路径。"""
        mgr.add_memory_sync("u", "内容记忆", level=4)
        monkeypatch.setattr(type(mgr._embedder), "embed", lambda self, text: None)
        prompt = mgr.get_context_prompt("u", query="查询")
        assert "内容记忆" in prompt

    def test_batch_empty_falls_back(self, mgr, monkeypatch) -> None:
        mgr.add_memory_sync("u", "内容记忆", level=4)
        monkeypatch.setattr(type(mgr._embedder), "embed_batch",
                            lambda self, texts: [])
        prompt = mgr.get_context_prompt("u", query="查询")
        assert "内容记忆" in prompt

    def test_category_label_rendered(self, mgr) -> None:
        mgr.add_memory_sync("u", "我喜欢跑步", level=4, category="emotion")
        prompt = mgr.get_context_prompt("u")
        assert "[情感]" in prompt

    def test_unknown_category_no_label(self, mgr) -> None:
        mgr.add_memory_sync("u", "内容记忆", level=4, category="weird")
        prompt = mgr.get_context_prompt("u")
        assert "[]" not in prompt

    def test_stars_by_level(self, mgr) -> None:
        mgr.add_memory_sync("u", "内容记忆", level=3)
        assert "⭐⭐⭐" in mgr.get_context_prompt("u")

    def test_low_level_excluded(self, mgr) -> None:
        mgr._storage.save("u", [Memory(id="low", content="不重要", level=1)])
        assert mgr.get_context_prompt("u") == ""

    def test_limit(self, mgr) -> None:
        for i in range(6):
            mgr.add_memory_sync("u", f"内容条目{i}", level=4)
        lines = mgr.get_context_prompt("u", limit=2).splitlines()
        assert len(lines) == 3  # 标题 + 2 条

    def test_duplicate_prefix_deduped(self, mgr) -> None:
        """内容去重只发生在混合评分路径（降级路径不去重）。"""
        mgr._storage.save("u", [
            Memory(id="a", content="查询相关的内容条目", level=4),
            Memory(id="b", content="查询相关的内容条目", level=4),
        ])
        prompt = mgr.get_context_prompt("u", query="查询")
        assert prompt.count("查询相关的内容条目") == 1

    def test_fallback_path_keeps_duplicates(self, mgr) -> None:
        """降级路径（无 query）不去重 —— 断言这个差异，避免以后误以为是 bug。"""
        mgr._storage.save("u", [
            Memory(id="a", content="查询相关的内容条目", level=4),
            Memory(id="b", content="查询相关的内容条目", level=4),
        ])
        assert mgr.get_context_prompt("u").count("查询相关的内容条目") == 2


# --------------------------------------------------------------------------- #
# 分类 / 导入导出
# --------------------------------------------------------------------------- #


class TestCategoryAndTransfer:
    def test_get_by_category(self, mgr) -> None:
        mgr.add_memory_sync("u", "我喜欢跑步", level=4, category="emotion")
        mgr.add_memory_sync("u", "内容记忆", level=4, category="other")
        results = mgr.get_memories_by_category("u", "emotion")
        assert len(results) == 1
        assert results[0].category == "emotion"

    def test_import(self, mgr) -> None:
        count = mgr.import_memories("u", [
            {"id": "x1", "content": "导入一", "level": 4},
            {"id": "x2", "content": "导入二", "level": 3},
        ])
        assert count == 2
        assert mgr._storage.count("u") == 2

    def test_import_indexes(self, mgr, vs) -> None:
        mgr.import_memories("u", [{"id": "x1", "content": "相关内容", "level": 4}])
        assert vs.count("u") == 1

    def test_import_appends(self, mgr) -> None:
        mgr.add_memory_sync("u", "已有内容", level=4)
        mgr.import_memories("u", [{"id": "x1", "content": "导入一", "level": 4}])
        assert mgr._storage.count("u") == 2

    def test_export_excludes_superseded(self, mgr) -> None:
        mgr._storage.save("u", [
            Memory(id="a", content="保留"),
            Memory(id="b", content="被取代", superseded_by="a"),
        ])
        assert [m.id for m in mgr.export_memories("u")] == ["a"]

    def test_export_empty(self, mgr) -> None:
        assert mgr.export_memories("nobody") == []
