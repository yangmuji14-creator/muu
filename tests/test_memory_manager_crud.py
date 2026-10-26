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


class TestDecayFlush:
    """`get_memories` 里的衰减结果必须真的落库（第三批修复）

    之前 `get_memories` 只改内存对象、不写回，遗忘分永远停在创建时的值。
    """

    def test_get_memories_persists_forget_score(self, mgr) -> None:
        mgr._storage.save("u", [_old("stale", days=200, level=2, category="other")])
        # 绕开 manager，直接从存储层读，确认写回的是数据库而不是内存对象
        before = mgr._storage.get("u", "stale")
        assert before is not None
        assert before.forget_score == 0.0

        mgr.get_memories("u")

        after = mgr._storage.get("u", "stale")
        assert after is not None
        assert after.forget_score > 0

    def test_flush_is_throttled(self, mgr, monkeypatch) -> None:
        mgr._storage.save("u", [_old("stale", days=200, level=2, category="other")])
        mgr.get_memories("u")  # 第一次：落库

        calls: list[int] = []
        real = mgr._storage.update_many

        def spy(user_id, memories, columns=None):
            calls.append(len(memories))
            return real(user_id, memories, columns=columns)

        monkeypatch.setattr(mgr._storage, "update_many", spy)
        mgr.get_memories("u")  # 节流窗口内：不应再写
        assert calls == []

    def test_apply_decay_bypasses_throttle(self, mgr, monkeypatch) -> None:
        mgr._storage.save("u", [_old("stale", days=200, level=2, category="other")])
        mgr.get_memories("u")  # 把节流窗口打开

        calls: list[int] = []

        def spy(user_id, memories, columns=None):
            calls.append(len(memories))
            return real(user_id, memories, columns=columns)

        monkeypatch.setattr(mgr._storage, "update_many", spy)
        mgr.apply_decay("u")  # 显式调用必须立即写库
        assert calls == [1]

    def test_flush_failure_does_not_raise(self, mgr, monkeypatch) -> None:
        mgr._storage.save("u", [_old("stale", days=200, level=2, category="other")])

        def boom(user_id, memories, columns=None):
            raise RuntimeError("db gone")

        monkeypatch.setattr(mgr._storage, "update_many", boom)
        # 衰减落库失败不能把整轮对话搞挂
        assert len(mgr.get_memories("u")) == 1

    def test_flush_failure_does_not_arm_throttle(self, mgr, monkeypatch) -> None:
        """写库失败后不能在 5 分钟内「假装已经写过」。

        早先实现先更新节流时间戳再写库，失败路径把时间戳留了下来，
        于是注释承诺的「下一轮会再试一次」实际是「5 分钟后再试一次」，
        一次瞬时锁冲突就能让衰减在这一窗口内完全不落盘。
        """
        mgr._storage.save("u", [_old("stale", days=200, level=2, category="other")])

        def boom(user_id, memories, columns=None):
            raise RuntimeError("db gone")

        monkeypatch.setattr(mgr._storage, "update_many", boom)
        mgr.get_memories("u")  # 第一次写失败
        assert "u" not in mgr._decay_flushed_at

        calls: list[int] = []
        real = mgr._storage.update_many

        def spy(user_id, memories, columns=None):
            calls.append(len(memories))
            return real(user_id, memories, columns=columns)

        monkeypatch.setattr(mgr._storage, "update_many", spy)
        mgr.get_memories("u")  # 下一轮必须真的重试
        assert calls == [1]

    def test_skips_archived_and_superseded(self, mgr) -> None:
        mgr._storage.save("u", [
            _old("arch", days=200, level=2, archived=True),
            _old("super", days=200, level=2, superseded_by="x"),
            _old("live", days=200, level=2, category="other"),
        ])
        written = mgr._flush_decay("u", mgr._storage.load("u"), force=True)
        assert written == 1


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


class TestSemanticSearchFiltering:
    """`semantic_search` 必须过滤作废/归档/已删除的记忆（第五批修复）

    向量表只有 ``(user_id, memory_id, content, embedding, created_at)``，
    没有任何状态列。冲突取代、归档、删除都只改 ``memories`` 表，所以
    直接返回 ``vector_store.search()`` 的原始结果会把「已经不该被记起的
    内容」交给调用方 —— 用户能在管理界面搜到自相矛盾的记忆。
    """

    def test_superseded_excluded(self, mgr) -> None:
        old = mgr.add_memory_sync("u", "我喜欢喝咖啡", level=4)
        new = mgr.add_memory_sync("u", "我不喜欢喝咖啡了", level=4)
        assert old is not None and new is not None
        # 手工标记取代关系（冲突检测的判定逻辑另有测试）
        mgr._storage.update("u", _old(old.id, content="我喜欢喝咖啡",
                                      level=4, superseded_by=new.id))

        hits = mgr.semantic_search("u", "查询", top_k=10)
        ids = [h["memory_id"] for h in hits]
        assert old.id not in ids, "被取代的记忆不该被语义检索召回"
        assert new.id in ids

    def test_archived_excluded(self, mgr) -> None:
        mem = mgr.add_memory_sync("u", "相关内容", level=4)
        assert mem is not None
        mgr._storage.update("u", _old(mem.id, content="相关内容",
                                      level=4, archived=True))
        assert mgr.semantic_search("u", "查询", top_k=10) == []

    def test_orphan_vector_excluded(self, mgr, vs) -> None:
        """向量表里有、memories 表里没有 → 孤儿，不该被召回。"""
        mem = mgr.add_memory_sync("u", "相关内容", level=4)
        assert mem is not None
        mgr._storage.delete("u", mem.id)
        assert vs.count("u") == 1, "前置条件：向量还在"
        assert mgr.semantic_search("u", "查询", top_k=10) == []

    def test_top_k_still_satisfied_after_filtering(self, mgr) -> None:
        """作废记忆占多数时，过滤后仍要尽量凑够 top_k。"""
        keep = [mgr.add_memory_sync("u", f"相关的内容{i}", level=4) for i in range(3)]
        dead = [mgr.add_memory_sync("u", f"相关但作废{i}", level=4) for i in range(10)]
        for m in dead:
            assert m is not None
            mgr._storage.update("u", _old(m.id, content=f"相关但作废{dead.index(m)}",
                                          level=4, superseded_by="x"))
        hits = mgr.semantic_search("u", "查询", top_k=3)
        ids = {h["memory_id"] for h in hits}
        assert len(hits) == 3
        assert ids == {m.id for m in keep}

    def test_state_lookup_failure_returns_empty(self, mgr, monkeypatch) -> None:
        """查不到状态时返回空，而不是把作废内容漏出去。"""
        mgr.add_memory_sync("u", "相关内容", level=4)

        def boom(user_id):
            raise RuntimeError("memories.db gone")

        monkeypatch.setattr(mgr._storage, "load", boom)
        assert mgr.semantic_search("u", "查询") == []


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
        """向量表没覆盖到时退回现算路径，现算批量长度不符也要降级到重要度排序。"""
        # 直接写存储层，绕开 _index_memory → 向量表里没有这两条
        mgr._storage.save("u", [
            _old("a", content="内容记忆", level=4),
            _old("b", content="另一条记忆", level=4),
        ])
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
        mgr._storage.save("u", [_old("a", content="内容记忆", level=4)])
        monkeypatch.setattr(type(mgr._embedder), "embed", lambda self, text: None)
        prompt = mgr.get_context_prompt("u", query="查询")
        assert "内容记忆" in prompt

    def test_batch_empty_falls_back(self, mgr, monkeypatch) -> None:
        mgr._storage.save("u", [_old("a", content="内容记忆", level=4)])
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


class TestVectorStoreRanking:
    """主对话召回必须复用 `memory_vectors` 里已建好的向量（第四批修复）

    历史缺陷：`get_context_prompt` 每轮把候选记忆全部重新 embed 一遍，
    写进向量库的索引只有管理界面的 `semantic_search` 在读 —— 用户写入的
    向量在主对话里从未被使用，200 条记忆规模下每轮白烧 ~140ms。
    """

    def test_uses_stored_vectors_without_reembedding(self, mgr, monkeypatch) -> None:
        mgr.add_memory_sync("u", "相关内容", level=4)
        mgr.add_memory_sync("u", "别的东西", level=4)

        batch_calls: list[int] = []
        monkeypatch.setattr(
            type(mgr._embedder), "embed_batch",
            lambda self, texts: batch_calls.append(len(texts)) or [],
        )
        get_emb_calls: list[list[str] | None] = []
        real = mgr._vector_store.get_embeddings

        def spy(user_id, memory_ids=None):
            get_emb_calls.append(memory_ids)
            return real(user_id, memory_ids)

        monkeypatch.setattr(mgr._vector_store, "get_embeddings", spy)

        prompt = mgr.get_context_prompt("u", query="查询")

        assert "相关内容" in prompt
        assert batch_calls == [], "不应该再逐条重算候选向量"
        assert get_emb_calls and get_emb_calls[0], "应该按 id 取回已存的向量"

    def test_query_embedded_exactly_once(self, mgr, monkeypatch) -> None:
        mgr.add_memory_sync("u", "相关内容", level=4)
        calls: list[str] = []
        real = mgr._embedder.embed

        def spy(text):
            calls.append(text)
            return real(text)

        monkeypatch.setattr(mgr._embedder, "embed", spy)
        mgr.get_context_prompt("u", query="查询")
        assert calls == ["查询"], f"查询只该 embed 一次，实际 {calls}"

    def test_missing_vector_falls_back_to_live_embed(self, mgr, monkeypatch) -> None:
        """向量表没覆盖到候选时，必须回退到现算路径而不是漏掉记忆。"""
        mgr._storage.save("u", [_old("a", content="查询相关的内容", level=4)])
        assert mgr._vector_store.count("u") == 0

        batch_calls: list[int] = []
        real_batch = mgr._embedder.embed_batch

        def spy(texts):
            batch_calls.append(len(texts))
            return real_batch(texts)

        monkeypatch.setattr(mgr._embedder, "embed_batch", spy)
        prompt = mgr.get_context_prompt("u", query="查询")
        assert "查询相关的内容" in prompt
        assert batch_calls == [1], "缺向量时应走现算回退路径"

    def test_partial_coverage_uses_fallback(self, mgr, monkeypatch) -> None:
        """只索引了一部分 → 整体回退，避免新旧向量混排导致排序不可解释。"""
        mgr.add_memory_sync("u", "有索引的内容", level=4)
        mgr._storage.add("u", _old("no_vec", content="没索引的内容", level=4))
        assert mgr._vector_store.count("u") == 1
        assert mgr._storage.count("u") == 2

        batch_calls: list[int] = []
        real_batch = mgr._embedder.embed_batch

        def spy(texts):
            batch_calls.append(len(texts))
            return real_batch(texts)

        monkeypatch.setattr(mgr._embedder, "embed_batch", spy)
        mgr.get_context_prompt("u", query="查询")
        assert batch_calls == [2], "覆盖不全时应回退到现算（2 条候选）"

    def test_vector_store_error_falls_back(self, mgr, monkeypatch) -> None:
        mgr.add_memory_sync("u", "相关内容", level=4)

        def boom(user_id, memory_ids=None):
            raise RuntimeError("vectors.db gone")

        monkeypatch.setattr(mgr._vector_store, "get_embeddings", boom)
        prompt = mgr.get_context_prompt("u", query="查询")
        assert "相关内容" in prompt

    def test_ranking_matches_live_path(self, mgr) -> None:
        """快路径与慢路径的排序结果必须一致（只是省掉了重算向量）。"""
        for content in ("查询相关的内容", "完全无关的话题", "查询这件事的细节"):
            mgr.add_memory_sync("u", content, level=4)

        fast = mgr.get_context_prompt("u", query="查询")

        # 手动走慢路径：清空向量库 → 触发回退
        mgr._vector_store.delete_all("u")
        slow = mgr.get_context_prompt("u", query="查询")

        assert fast == slow

    def test_stale_dimension_vectors_skipped(self, mgr) -> None:
        """索引里残留旧维度向量时，快路径要跳过它们而不是崩掉。

        换 embedding 模型（或改 `dim`）后，旧行仍留在 vectors.db 里，
        维度与当前 query 向量不一致。早先 ``_hybrid_rank_prompt`` 直接
        ``np.dot(query, mem.T)``，维度不等抛 ``ValueError: shapes not aligned``，
        而这个调用点没有被 try 包住，异常一路冒到 SSE 循环，
        用户看到的是整轮对话失败（"暂时无法生成回复"）。
        """
        mgr.add_memory_sync("u", "相关内容", level=4)
        mgr.add_memory_sync("u", "另外的内容", level=4)

        # 把其中一条改写成别的维度，模拟模型换代留下的陈旧行
        stale = mgr._storage.load("u")[0]
        mgr._vector_store.add("u", stale.id, "相关内容", unit(7, dim=16))

        prompt = mgr.get_context_prompt("u", query="查询")
        assert prompt, "维度不匹配不能让上下文构建整体返回空"

    def test_all_vectors_stale_falls_back(self, mgr, monkeypatch) -> None:
        """候选向量全是旧维度 → 快路径返回 None，回退现算，不能返回空上下文。"""
        mgr.add_memory_sync("u", "相关内容", level=4)
        for mem in mgr._storage.load("u"):
            mgr._vector_store.add("u", mem.id, mem.content, unit(9, dim=16))

        batch_calls: list[int] = []
        real_batch = mgr._embedder.embed_batch

        def spy(texts):
            batch_calls.append(len(texts))
            return real_batch(texts)

        monkeypatch.setattr(mgr._embedder, "embed_batch", spy)
        prompt = mgr.get_context_prompt("u", query="查询")
        assert "相关内容" in prompt
        assert batch_calls, "旧维度向量被全部跳过时应回退到现算路径"


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


# --------------------------------------------------------------------------- #
# 孤儿向量：记忆被裁掉 / 清空后，向量必须同步消失
# --------------------------------------------------------------------------- #


class TestOrphanVectors:
    """`memory_vectors` 不允许比 `memories` 长出孤儿行。

    孤儿向量是用户可感知的正确性缺陷：`semantic_search` 会把「已经不在
    memories 里、管理界面也看不到」的内容召回进 prompt。
    """

    def test_cleanup_prunes_dropped_vectors(self, tmp_path, vs) -> None:
        mgr = MemoryManager(tmp_path, max_memories=3, embedder=FakeEmbedder(), vector_store=vs)
        for i in range(6):
            mgr.add_memory_sync("u", f"内容{i}", level=3)
        assert mgr._storage.count("u") == 3
        assert vs.count("u") == 3, "被裁掉的记忆必须同时删掉向量"

    def test_cleanup_kept_memories_still_searchable(self, tmp_path, vs) -> None:
        mgr = MemoryManager(tmp_path, max_memories=2, embedder=FakeEmbedder(), vector_store=vs)
        for i in range(5):
            mgr.add_memory_sync("u", f"内容{i}", level=4)
        alive = {m.id for m in mgr._storage.load("u")}
        indexed = {r["memory_id"] for r in vs.list_all("u")}
        assert indexed == alive

    def test_semantic_search_never_returns_dead_memory(self, tmp_path, vs) -> None:
        mgr = MemoryManager(tmp_path, max_memories=2, embedder=FakeEmbedder(), vector_store=vs)
        for i in range(5):
            mgr.add_memory_sync("u", f"内容{i}", level=4)
        alive = {m.id for m in mgr._storage.load("u")}
        hits = mgr.semantic_search("u", "查询", top_k=10)
        assert hits, "向量检索应仍有结果"
        assert all(h["memory_id"] in alive for h in hits), "不能召回已不存在的记忆"

    def test_cleanup_without_user_id_does_not_touch_vectors(self, tmp_path, vs) -> None:
        """私有方法被直接调用（无 user_id）时不做 IO，保持旧行为。"""
        mgr = MemoryManager(tmp_path, max_memories=1, embedder=FakeEmbedder(), vector_store=vs)
        mgr.add_memory_sync("u", "保留", level=5)
        extra = Memory(id="m_extra", content="多余的", level=1)
        out = mgr._cleanup_old_memories(
            [Memory(id="m_keep", content="保留的", level=5), extra]
        )
        assert [m.id for m in out] == ["m_keep"]
        assert vs.count("u") == 1, "没传 user_id 时不应误删别的向量"

    def test_new_memory_dropped_by_cleanup_is_not_indexed(self, tmp_path, vs) -> None:
        """新记忆自己刚被裁掉时，不能再给它写向量。

        写入顺序原本是「落库 → 清理（可能把这条新记忆自己裁掉）→ 索引」，
        于是刚被删掉的记忆又拿到一行向量，`embedding_status` 会把它报成
        orphaned，`semantic_search` 得靠 `_filter_searchable` 兜底才不召回。
        """
        mgr = MemoryManager(tmp_path, max_memories=1, embedder=FakeEmbedder(), vector_store=vs)
        mgr._storage.save("u", [_old("old", content="旧的压舱记忆", level=5, days=30)])
        # 同等重要度、但更新的一条把旧记忆挤出配额（裁剪按 level/forget_score/时间排）
        survivor = mgr.add_memory_sync("u", "刚说的重要的事", level=5)

        alive = {m.id for m in mgr._storage.load("u")}
        indexed = {r["memory_id"] for r in vs.list_all("u")}
        assert survivor is not None and survivor.id in alive, "前提：新记忆保留下来"
        assert "old" not in alive, "前提：旧记忆被裁掉了"
        assert indexed == alive, "被裁掉的记忆不能留下向量"

    def test_trim_keeps_newest_when_otherwise_equal(self, tmp_path, vs) -> None:
        """重要度、新鲜度都一样时，裁剪必须淘汰旧的而不是刚写进来的。

        早先排序后截断对「新写入的行」天然不利：同一时刻写入的多条
        ``created_at`` / ``last_accessed`` 完全相同，先后取决于列表顺序，
        再加上 SQLite 的时间串精度，刚加进来的记忆可能刚写完就被自己踢掉。
        """
        mgr = MemoryManager(tmp_path, max_memories=2, embedder=FakeEmbedder(), vector_store=vs)
        mgr._storage.save("u", [
            _old("old1", content="旧内容一", level=5, days=60),
            _old("old2", content="旧内容二", level=5, days=30),
        ])
        new = mgr.add_memory_sync("u", "刚刚说的重要的事", level=5)

        alive = {m.id for m in mgr._storage.load("u")}
        assert new is not None
        assert new.id in alive, "刚写入的记忆不该被自己触发的裁剪淘汰"
        assert "old1" not in alive

    def test_vector_delete_failure_is_swallowed(self, tmp_path, vs, monkeypatch) -> None:
        """单条向量删除失败不能打断整轮清理。"""
        mgr = MemoryManager(tmp_path, max_memories=1, embedder=FakeEmbedder(), vector_store=vs)

        def boom(*args, **kwargs):
            raise RuntimeError("delete failed")

        monkeypatch.setattr(type(vs), "delete", boom)
        mgr.add_memory_sync("u", "内容一", level=4)
        mgr.add_memory_sync("u", "内容二", level=5)
        assert mgr._storage.count("u") == 1, "清理本身仍要成功"

    def test_reindex_prunes_orphans_without_force(self, tmp_path, vs) -> None:
        mgr = MemoryManager(tmp_path, embedder=FakeEmbedder(), vector_store=vs)
        mgr.add_memory_sync("u", "活着的内容", level=4)
        vs.add("u", "m_ghost", "早已不存在的内容", unit(7))
        assert vs.count("u") == 2

        result = mgr.reindex_all()
        assert result["pruned"] == 1
        assert vs.count("u") == 1
        assert {r["memory_id"] for r in vs.list_all("u")} != {"m_ghost"}

    def test_reindex_prune_is_idempotent(self, tmp_path, vs) -> None:
        mgr = MemoryManager(tmp_path, embedder=FakeEmbedder(), vector_store=vs)
        mgr.add_memory_sync("u", "活着的内容", level=4)
        vs.add("u", "m_ghost", "幽灵内容", unit(7))
        assert mgr.reindex_all()["pruned"] == 1
        assert mgr.reindex_all()["pruned"] == 0

    def test_reindex_prune_specific_user_only(self, tmp_path, vs) -> None:
        mgr = MemoryManager(tmp_path, embedder=FakeEmbedder(), vector_store=vs)
        mgr.add_memory_sync("u1", "用户一", level=4)
        mgr.add_memory_sync("u2", "用户二", level=4)
        vs.add("u1", "m_ghost1", "幽灵一", unit(7))
        vs.add("u2", "m_ghost2", "幽灵二", unit(8))

        result = mgr.reindex_all(user_id="u1")
        assert result["pruned"] == 1
        assert vs.count("u2") == 2, "只清指定用户的孤儿"

    def test_reindex_prune_failure_is_swallowed(self, tmp_path, vs, monkeypatch) -> None:
        mgr = MemoryManager(tmp_path, embedder=FakeEmbedder(), vector_store=vs)
        mgr.add_memory_sync("u", "活着的内容", level=4)
        vs.add("u", "m_ghost", "幽灵内容", unit(7))

        def boom(*args, **kwargs):
            raise RuntimeError("delete failed")

        monkeypatch.setattr(type(vs), "delete", boom)
        result = mgr.reindex_all()
        assert result["pruned"] == 0
        assert result["failed"] == 0, "孤儿清理失败不算索引失败"


class TestClearMemories:
    """整用户级删除必须同时清 memories 和 memory_vectors。

    `/memories clear` 曾经自建 MemoryStorage 直接 delete_all，绕过向量库 ——
    用户清空记忆后 semantic_search 仍能召回已删除内容。
    """

    def test_clear_removes_both_sides(self, tmp_path, vs) -> None:
        mgr = MemoryManager(tmp_path, embedder=FakeEmbedder(), vector_store=vs)
        mgr.add_memory_sync("u", "内容一", level=4)
        mgr.add_memory_sync("u", "内容二", level=4)
        assert mgr._storage.count("u") == 2
        assert vs.count("u") == 2

        removed = mgr.clear_memories("u")
        assert removed == 2
        assert mgr._storage.count("u") == 0
        assert vs.count("u") == 0

    def test_clear_makes_semantic_search_empty(self, tmp_path, vs) -> None:
        mgr = MemoryManager(tmp_path, embedder=FakeEmbedder(), vector_store=vs)
        mgr.add_memory_sync("u", "查询相关的秘密", level=5)
        assert mgr.semantic_search("u", "查询", top_k=10)

        mgr.clear_memories("u")
        assert mgr.semantic_search("u", "查询", top_k=10) == [], (
            "清空后语义检索必须一条都召不回来"
        )

    def test_clear_does_not_touch_other_users(self, tmp_path, vs) -> None:
        mgr = MemoryManager(tmp_path, embedder=FakeEmbedder(), vector_store=vs)
        mgr.add_memory_sync("u1", "用户一的内容", level=4)
        mgr.add_memory_sync("u2", "用户二的内容", level=4)

        mgr.clear_memories("u1")
        assert mgr._storage.count("u1") == 0
        assert vs.count("u1") == 0
        assert mgr._storage.count("u2") == 1
        assert vs.count("u2") == 1

    def test_clear_without_vector_store(self, tmp_path) -> None:
        mgr = MemoryManager(tmp_path, embedder=FakeEmbedder())
        mgr.add_memory_sync("u", "内容一", level=4)
        assert mgr.clear_memories("u") == 1
        assert mgr._storage.count("u") == 0

    def test_clear_empty_user_returns_zero(self, tmp_path, vs) -> None:
        mgr = MemoryManager(tmp_path, embedder=FakeEmbedder(), vector_store=vs)
        assert mgr.clear_memories("nobody") == 0

    def test_clear_survives_vector_failure(self, tmp_path, vs, monkeypatch) -> None:
        mgr = MemoryManager(tmp_path, embedder=FakeEmbedder(), vector_store=vs)
        mgr.add_memory_sync("u", "内容一", level=4)

        def boom(*args, **kwargs):
            raise RuntimeError("vector clear failed")

        monkeypatch.setattr(type(vs), "delete_all", boom)
        assert mgr.clear_memories("u") == 1
        assert mgr._storage.count("u") == 0, "向量清空失败不能回滚记忆清空"
