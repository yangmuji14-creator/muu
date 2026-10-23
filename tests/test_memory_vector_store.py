"""向量存储测试（隔离的临时 SQLite，不碰真实 data/）。

覆盖:
- add / count / search / list_all / delete / delete_all 的基本语义
- search 的余弦排序正确性
- 同一 (user_id, memory_id) 的重复写入是覆盖而不是重复
- user_id 之间的隔离
"""

import numpy as np
import pytest

from core.memory.vector_store import VectorStore


def rand_vec(seed: int, dim: int = 8) -> list[float]:
    rng = np.random.default_rng(seed)
    return rng.normal(size=dim).astype(np.float32).tolist()


@pytest.fixture()
def store(tmp_path):
    s = VectorStore(tmp_path / "vectors.db")
    yield s
    s.close()


class TestBasicOps:
    def test_starts_empty(self, store):
        assert store.count("u1") == 0
        assert store.list_all("u1") == []
        assert store.search("u1", rand_vec(0)) == []

    def test_add_then_count(self, store):
        store.add("u1", "m1", "内容一", rand_vec(1))
        store.add("u1", "m2", "内容二", rand_vec(2))
        assert store.count("u1") == 2

    def test_add_is_upsert(self, store):
        v = rand_vec(1)
        store.add("u1", "m1", "旧内容", v)
        store.add("u1", "m1", "新内容", v)
        assert store.count("u1") == 1
        assert store.list_all("u1")[0]["content"] == "新内容"

    def test_list_all_returns_ids_and_content(self, store):
        store.add("u1", "m1", "内容一", rand_vec(1))
        rows = store.list_all("u1")
        assert {r["memory_id"] for r in rows} == {"m1"}
        assert rows[0]["content"] == "内容一"
        assert "embedding" not in rows[0]

    def test_delete_returns_true_when_removed(self, store):
        store.add("u1", "m1", "内容", rand_vec(1))
        assert store.delete("u1", "m1") is True
        assert store.count("u1") == 0

    def test_delete_missing_returns_false(self, store):
        assert store.delete("u1", "nope") is False

    def test_delete_all_clears_only_target_user(self, store):
        store.add("u1", "m1", "a", rand_vec(1))
        store.add("u2", "m2", "b", rand_vec(2))
        removed = store.delete_all("u1")
        assert removed == 1
        assert store.count("u1") == 0
        assert store.count("u2") == 1


class TestSearch:
    def test_exact_match_scores_highest(self, store):
        target = rand_vec(7)
        store.add("u1", "exact", "精确", target)
        store.add("u1", "other", "无关", rand_vec(99))
        hits = store.search("u1", target, top_k=2)
        assert hits[0]["memory_id"] == "exact"

    def test_results_sorted_descending(self, store):
        q = rand_vec(1)
        for i in range(5):
            store.add("u1", f"m{i}", f"内容{i}", rand_vec(i))
        hits = store.search("u1", q, top_k=5)
        scores = [h["score"] for h in hits]
        assert scores == sorted(scores, reverse=True)

    def test_top_k_respected(self, store):
        for i in range(6):
            store.add("u1", f"m{i}", f"内容{i}", rand_vec(i))
        assert len(store.search("u1", rand_vec(1), top_k=3)) == 3

    def test_search_isolated_by_user(self, store):
        store.add("u1", "m1", "u1 的记忆", rand_vec(1))
        store.add("u2", "m2", "u2 的记忆", rand_vec(2))
        hits = store.search("u2", rand_vec(1), top_k=5)
        assert [h["memory_id"] for h in hits] == ["m2"]

    def test_scores_are_rounded(self, store):
        store.add("u1", "m1", "内容", rand_vec(1))
        score = store.search("u1", rand_vec(1), top_k=1)[0]["score"]
        assert round(score, 4) == score
