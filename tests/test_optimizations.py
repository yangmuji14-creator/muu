"""优化功能的集成测试

测试项：
  1. 轻量化嵌入器的内存占用和性能
  2. 动态阈值系统
  3. 因果链识别
  4. 缓存命中率
"""

import pytest

# 导入优化模块
from core.memory.embedder_lite import LiteEmbedder
from core.memory.dynamic_gate import DynamicGateSystem
from core.memory.causal_linker import CausalLinker


@pytest.fixture
def lite_embedder():
    """创建轻量化嵌入器实例"""
    return LiteEmbedder(cache_size=128)


@pytest.fixture
def dynamic_gate():
    """创建动态闸门系统"""
    return DynamicGateSystem()


@pytest.fixture
def causal_linker():
    """创建因果链识别器"""
    return CausalLinker()


class TestLiteEmbedder:
    """轻量化嵌入器测试"""

    def test_embedder_available(self, lite_embedder):
        """测试嵌入器可用性"""
        # 注意：测试环境可能没有模型，应该有优雅的降级
        assert lite_embedder is not None

    def test_cache_hit(self, lite_embedder):
        """测试缓存命中（用计数而非墙钟，避免 CI 抖动）"""
        if not lite_embedder.available:
            pytest.skip("Embedder not available")

        text = "这是一个测试句子"
        result1 = lite_embedder.embed(text)
        result2 = lite_embedder.embed(text)

        assert result1 == result2, "Cache should return same result"
        stats = lite_embedder.cache_stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 1

    def test_batch_embedding(self, lite_embedder):
        """测试批量嵌入（不依赖 psutil，弱环境也能跑）"""
        if not lite_embedder.available:
            pytest.skip("Embedder not available")

        texts = ["测试句子" + str(i) for i in range(32)]
        results = lite_embedder.embed_batch(texts)

        assert results is not None
        assert len(results) == 32


class TestDynamicGateSystem:
    """动态阈值系统测试"""

    def test_new_user_threshold(self, dynamic_gate):
        """新手用户应该有更宽松的阈值"""
        threshold = dynamic_gate.compute_threshold(
            user_interaction_count=5,
            current_emotion=None,
        )
        
        # 新手期阈值应该更低（更宽松）
        assert threshold.absolute_min < 0.35

    def test_long_term_user_threshold(self, dynamic_gate):
        """长期用户应该有更严格的阈值"""
        threshold = dynamic_gate.compute_threshold(
            user_interaction_count=150,
            current_emotion=None,
        )
        
        # 长期用户阈值应该更高（更严格）
        assert threshold.absolute_min > 0.35

    def test_anxious_emotion_threshold(self, dynamic_gate):
        """焦虑情绪应该降低阈值（加载更多记忆）"""
        normal = dynamic_gate.compute_threshold(
            user_interaction_count=50,
            current_emotion=None,
        )
        anxious = dynamic_gate.compute_threshold(
            user_interaction_count=50,
            current_emotion="anxious",
        )
        
        assert anxious.absolute_min < normal.absolute_min

    def test_happy_emotion_threshold(self, dynamic_gate):
        """开心情绪应该略微宽松阈值"""
        normal = dynamic_gate.compute_threshold(
            user_interaction_count=50,
            current_emotion=None,
        )
        happy = dynamic_gate.compute_threshold(
            user_interaction_count=50,
            current_emotion="happy",
        )
        
        # 应该轻微改变（而非大幅变化）
        assert happy.absolute_min != normal.absolute_min


class TestCausalLinker:
    """因果链识别测试"""

    def test_find_causal_chains(self, causal_linker):
        """测试因果链识别"""
        memories = [
            {
                "id": "1",
                "content": "昨天下雨了，很冷",
                "timestamp": None,
            },
            {
                "id": "2",
                "content": "熬夜加班到凌晨",
                "timestamp": None,
            },
        ]

        chains = causal_linker.find_causal_chains(
            query_memory_id="3",
            query_content="今天感冒了，头疼",
            candidate_memories=memories,
        )

        # 应该找到"下雨 → 感冒"的因果关系
        assert any("下雨" in c.cause_content and "感冒" in "今天感冒了" for c in chains)

    def test_causal_confidence_calculation(self, causal_linker):
        """测试因果确信度计算"""
        conf = causal_linker._compute_causal_confidence(
            cause="下雨了",
            effect="感冒了",
            forward=True,
        )
        
        # 应该识别出中等以上的因果关系
        assert conf > 0.5

    def test_rank_with_causal_boost(self, causal_linker):
        """测试带因果加成的排序"""
        memories = [
            {"id": "m1", "content": "下雨", "timestamp": None},
            {"id": "m2", "content": "其他事", "timestamp": None},
        ]
        original_scores = {
            "m1": 0.5,
            "m2": 0.8,
        }

        boosted = causal_linker.rank_with_causal_boost(
            candidate_memories=memories,
            query_memory_id="q1",
            query_content="感冒了",
            original_scores=original_scores,
        )

        # m1 应该因为因果关系而获得加成
        assert boosted.get("m1", 0) >= original_scores["m1"]


class TestIntegration:
    """集成测试"""

    def test_pipeline_with_optimizations(self, lite_embedder, dynamic_gate, causal_linker):
        """完整流程测试"""
        # 这是一个集成点，验证三个优化模块能否协作
        
        # 1. 获取动态阈值
        threshold = dynamic_gate.compute_threshold(
            user_interaction_count=50,
            current_emotion="calm",
        )
        assert threshold.absolute_min > 0

        # 2. 嵌入查询
        query = "今天感冒了"
        if lite_embedder.available:
            embedding = lite_embedder.embed(query)
            assert embedding is not None

        # 3. 识别因果链
        chains = causal_linker.find_causal_chains(
            query_memory_id="current",
            query_content=query,
            candidate_memories=[
                {"id": "m1", "content": "昨天下雨", "timestamp": None},
            ],
        )
        # chains 可能为空或有结果，都是合理的
        assert isinstance(chains, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ────────── 回归测试：时间字段 / 阈值一致性 / 契约 ──────────

from datetime import datetime, timedelta

from core.memory.lifecycle_manager import MemoryLifecycleManager
from core.memory.manager import MemoryManager


def _mem_dict(days_old: int, access: int = 0):
    return {
        "id": "m1",
        "content": "测试记忆",
        "created_at": (datetime.now() - timedelta(days=days_old)).isoformat(),
        "access_count": access,
    }


class TestLifecycleManager:
    def test_accepts_iso_string_and_datetime(self):
        mgr = MemoryLifecycleManager()
        now = datetime.now()
        iso = _mem_dict(400)
        as_dt = dict(iso)
        as_dt["created_at"] = datetime.fromisoformat(iso["created_at"])

        # 两种输入都不能抛 TypeError，且分数必须一致且 > 0
        #（datetime 曾被 decay 的 fromisoformat 吞掉，静默变成 0）
        iso_score = mgr.compute_forget_score("m1", iso, now)
        dt_score = mgr.compute_forget_score("m1", as_dt, now)
        assert iso_score == pytest.approx(dt_score)
        assert iso_score > 0

    def test_accepts_timezone_aware_timestamps(self):
        mgr = MemoryLifecycleManager()
        mem = _mem_dict(400)
        mem["created_at"] = "2026-01-01T00:00:00+08:00"
        # 不能抛 "can't subtract offset-naive and offset-aware datetimes"
        assert mgr.compute_forget_score("m1", mem, datetime.now()) >= 0.0
        assert mgr.is_archive_candidate(mem, datetime.now()) in (True, False)
        assert mgr.get_lifecycle_report({"m1": mem})["total"] == 1

    def test_old_neglected_memory_can_be_marked(self):
        mgr = MemoryLifecycleManager()
        memories = {"m1": _mem_dict(4000)}  # 10 年未访问
        assert mgr.mark_for_forgetting(["m1"], memories) == ["m1"]

    def test_report_matches_archive_rule(self):
        mgr = MemoryLifecycleManager()
        now = datetime.now()
        memories = {
            "a": _mem_dict(200),
            "b": _mem_dict(200, access=5),
            "c": _mem_dict(10),
        }
        report = mgr.get_lifecycle_report(memories)
        expected = sum(
            mgr.is_archive_candidate(mem, now) for mem in memories.values()
        )
        assert report["archived_candidate"] == expected

    def test_follows_injected_decay_threshold(self):
        from core.memory.decay import MemoryDecaySystem

        mgr = MemoryLifecycleManager(decay=MemoryDecaySystem(forget_threshold=0.8))
        assert mgr._forget_threshold == 0.8

    def test_high_level_or_archived_never_archive_candidate(self):
        """与 MemoryDecaySystem.should_archive 一致：level>=3 / 已归档不参与摘要归档。"""
        mgr = MemoryLifecycleManager()
        now = datetime.now()
        high = _mem_dict(200)
        high["level"] = 5
        archived = _mem_dict(200)
        archived["archived"] = True

        assert mgr.is_archive_candidate(high, now) is False
        assert mgr.is_archive_candidate(archived, now) is False
        assert mgr.get_lifecycle_report({"h": high, "a": archived})["archived_candidate"] == 0


class TestCausalTimeWindow:
    def test_accepts_created_at_iso_and_downweights_old_cause(self):
        linker = CausalLinker()
        old = (datetime.now() - timedelta(hours=49)).isoformat()
        chains = linker.find_causal_chains(
            "q1",
            "今天感冒了",
            [{"id": "c1", "content": "昨天下雨了", "created_at": old}],
        )
        # 窗口外应降权但仍保留，而不是被 0.5 门槛硬切断
        assert chains, "超出窗口的因果链不应被直接丢弃"
        assert chains[0].confidence < 0.7

    def test_accepts_timezone_aware_timestamp(self):
        linker = CausalLinker()
        chains = linker.find_causal_chains(
            "q1",
            "今天感冒了",
            [{"id": "c1", "content": "昨天下雨了", "created_at": "2026-11-15T09:00:00+08:00"}],
        )
        assert chains, "带时区的时间戳不应让因果链崩溃"


class TestGateCalibration:
    def test_uses_manager_calibrated_constants(self):
        gate = DynamicGateSystem()
        assert gate._base_absolute == MemoryManager.MIN_SEMANTIC_SIMILARITY
        assert gate._base_relative == MemoryManager.RELATIVE_SIMILARITY_RATIO

    def test_strict_topic_consistency_actually_tightens(self):
        gate = DynamicGateSystem()
        base = gate.compute_threshold(50, None, 0.5)
        strict = gate.compute_threshold(50, None, 0.99)
        assert strict.absolute_min > base.absolute_min
        assert strict.relative_ratio > base.relative_ratio


class TestLiteEmbedderContract:
    def test_substitutes_base_embedder(self):
        from core.memory.embedder import BaseEmbedder

        embedder = LiteEmbedder(cache_size=4)
        assert isinstance(embedder, BaseEmbedder)
        # embedding_status() 诊断依赖这两个属性
        assert isinstance(embedder.model_source, str)
        assert embedder.init_error is None or isinstance(embedder.init_error, str)

    def test_cache_stats_shape(self):
        stats = LiteEmbedder(cache_size=4).cache_stats()
        assert {"size", "max_size", "hits", "misses", "hit_rate"} <= set(stats)
