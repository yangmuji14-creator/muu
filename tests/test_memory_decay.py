"""记忆衰减系统测试 —— `core/memory/decay.py` 的纯计算逻辑。

这个文件要守住两条线（见 docs/HANDOFF.md 第 3 节第 17 条）：
1. 遗忘衰减**只有这一套公式**，`MemoryManager._update_decay` 已删，别再引第二套。
2. 归档阈值只有 `_forget_threshold` 一个来源，不要在别处硬编码 0.8 / 0.9。
"""

from datetime import datetime, timedelta

import pytest

from core.memory.decay import MemoryDecaySystem
from core.memory.models import Memory


def _memory(
    mem_id: str = "m1",
    *,
    days_old: float = 0.0,
    level: int = 3,
    category: str = "other",
    access_count: int = 0,
    last_access_days: float | None = None,
    superseded_by: str = "",
    archived: bool = False,
    confidence: float = 0.7,
) -> Memory:
    created = datetime.now() - timedelta(days=days_old)
    if last_access_days is None:
        last_access_days = days_old
    accessed = datetime.now() - timedelta(days=last_access_days)
    return Memory(
        id=mem_id,
        content="测试记忆内容",
        level=level,
        category=category,
        created_at=created.isoformat(),
        last_accessed=accessed.isoformat(),
        access_count=access_count,
        superseded_by=superseded_by,
        archived=archived,
        confidence=confidence,
    )


class TestConstants:
    def test_level_multipliers_descend(self):
        m = MemoryDecaySystem.LEVEL_DECAY_MULTIPLIERS
        assert m[1] > m[2] > m[3] > m[4] > m[5]
        assert m[1] == 1.0

    def test_category_modifiers_cover_all_categories(self):
        from core.memory.models import MemoryCategory

        for cat in MemoryCategory:
            assert cat.value in MemoryDecaySystem.CATEGORY_DECAY_MODIFIERS

    def test_personal_decays_slowest(self):
        mods = MemoryDecaySystem.CATEGORY_DECAY_MODIFIERS
        # 个人信息最难忘，other 最快
        assert mods["personal"] == min(mods.values())
        assert mods["other"] == max(mods.values())


class TestCalculateForgetScore:
    def test_fresh_memory_near_zero(self):
        assert MemoryDecaySystem().calculate_forget_score(_memory()) < 0.01

    def test_older_scores_higher(self):
        sys_ = MemoryDecaySystem()
        young = sys_.calculate_forget_score(_memory(days_old=10))
        old = sys_.calculate_forget_score(_memory(days_old=300))
        assert old > young

    def test_higher_level_scores_lower(self):
        sys_ = MemoryDecaySystem()
        low = sys_.calculate_forget_score(_memory(days_old=100, level=1))
        high = sys_.calculate_forget_score(_memory(days_old=100, level=5))
        assert high < low

    def test_personal_slower_than_other(self):
        sys_ = MemoryDecaySystem()
        personal = sys_.calculate_forget_score(_memory(days_old=100, category="personal"))
        other = sys_.calculate_forget_score(_memory(days_old=100, category="other"))
        assert personal < other

    def test_unknown_category_falls_back_to_one(self):
        sys_ = MemoryDecaySystem()
        unknown = sys_.calculate_forget_score(_memory(days_old=100, category="nonexistent"))
        # 未知分类 modifier = 1.0，应高于 other(0.9)
        assert unknown > sys_.calculate_forget_score(_memory(days_old=100, category="other"))

    def test_access_count_reduces_score(self):
        sys_ = MemoryDecaySystem()
        cold = sys_.calculate_forget_score(_memory(days_old=100, access_count=0))
        warm = sys_.calculate_forget_score(_memory(days_old=100, access_count=20))
        assert warm < cold

    def test_recent_access_bonus(self):
        sys_ = MemoryDecaySystem()
        stale = sys_.calculate_forget_score(_memory(days_old=100, last_access_days=100))
        fresh = sys_.calculate_forget_score(_memory(days_old=100, last_access_days=0))
        assert fresh < stale

    def test_recent_window_is_24h(self):
        sys_ = MemoryDecaySystem()
        within = sys_.calculate_forget_score(_memory(days_old=100, last_access_days=0.5))
        outside = sys_.calculate_forget_score(_memory(days_old=100, last_access_days=2))
        assert within < outside

    def test_superseded_penalty(self):
        sys_ = MemoryDecaySystem()
        alive = sys_.calculate_forget_score(_memory(days_old=10))
        dead = sys_.calculate_forget_score(_memory(days_old=10, superseded_by="m2"))
        assert dead == pytest.approx(alive + 0.3, abs=1e-6)

    def test_never_negative(self):
        # 访问次数极多 + 刚访问过 → 分数会被减成负数，必须夹到 0
        sys_ = MemoryDecaySystem()
        score = sys_.calculate_forget_score(_memory(days_old=0, access_count=1000))
        assert score >= 0.0

    @pytest.mark.parametrize("bad", ["", "not-a-date", "2026-13-45"])
    def test_bad_timestamp_does_not_raise(self, bad):
        mem = _memory(days_old=100)
        mem.created_at = bad
        mem.last_accessed = bad
        assert MemoryDecaySystem().calculate_forget_score(mem) == pytest.approx(0.0)

    def test_custom_decay_rate_scales_linearly(self):
        slow = MemoryDecaySystem(base_decay_rate=0.01).calculate_forget_score(_memory(days_old=100, level=1))
        fast = MemoryDecaySystem(base_decay_rate=0.02).calculate_forget_score(_memory(days_old=100, level=1))
        assert fast == pytest.approx(slow * 2, rel=1e-3)


class TestShouldArchive:
    def test_archived_stays_archived(self):
        assert MemoryDecaySystem().should_archive(_memory(archived=True)) is False

    def test_superseded_always_archivable(self):
        # 已被取代的记忆直接清，不看分数也不看重要度
        assert MemoryDecaySystem().should_archive(_memory(level=5, superseded_by="m2")) is True

    def test_high_level_never_archived(self):
        assert MemoryDecaySystem().should_archive(_memory(days_old=4000, level=3)) is False
        assert MemoryDecaySystem().should_archive(_memory(days_old=4000, level=5)) is False

    def test_ancient_low_level_archived(self):
        assert MemoryDecaySystem().should_archive(_memory(days_old=4000, level=1)) is True

    def test_fresh_low_level_not_archived(self):
        assert MemoryDecaySystem().should_archive(_memory(days_old=0, level=1)) is False

    def test_threshold_is_single_source(self):
        # 阈值只来自构造函数，默认 1.0
        sys_ = MemoryDecaySystem()
        assert sys_._forget_threshold == 1.0
        mem = _memory(days_old=365, level=2, category="other")
        score = sys_.calculate_forget_score(mem)
        assert sys_.should_archive(mem) is (score >= 1.0)

    def test_custom_threshold_changes_verdict(self):
        mem = _memory(days_old=365, level=2, category="other")
        strict = MemoryDecaySystem(forget_threshold=1e9)
        loose = MemoryDecaySystem(forget_threshold=0.0)
        assert strict.should_archive(mem) is False
        assert loose.should_archive(mem) is True


class TestGetRetrievalWeight:
    def test_archived_is_zero(self):
        assert MemoryDecaySystem().get_retrieval_weight(_memory(archived=True)) == 0.0

    def test_superseded_is_zero(self):
        assert MemoryDecaySystem().get_retrieval_weight(_memory(superseded_by="m2")) == 0.0

    def test_higher_level_weighs_more(self):
        sys_ = MemoryDecaySystem()
        low = sys_.get_retrieval_weight(_memory(level=1))
        high = sys_.get_retrieval_weight(_memory(level=5))
        assert high > low

    def test_higher_confidence_weighs_more(self):
        sys_ = MemoryDecaySystem()
        low = sys_.get_retrieval_weight(_memory(confidence=0.3))
        high = sys_.get_retrieval_weight(_memory(confidence=0.9))
        assert high > low

    def test_recent_access_weighs_more(self):
        sys_ = MemoryDecaySystem()
        stale = sys_.get_retrieval_weight(_memory(days_old=100, last_access_days=100))
        fresh = sys_.get_retrieval_weight(_memory(days_old=100, last_access_days=0))
        assert fresh > stale

    def test_upper_bound(self):
        # 三项上限 0.4 + 0.3 + 0.2 + 0.1 = 1.0
        best = Memory(
            id="x", content="c", level=5, confidence=1.0, access_count=100,
            created_at=datetime.now().isoformat(),
            last_accessed=datetime.now().isoformat(),
        )
        assert MemoryDecaySystem().get_retrieval_weight(best) == pytest.approx(1.0, abs=1e-6)


class TestArchiveMemory:
    def test_sets_flag_and_returns_same_object(self):
        mem = _memory()
        assert MemoryDecaySystem.archive_memory(mem) is mem
        assert mem.archived is True

    def test_idempotent(self):
        mem = _memory()
        MemoryDecaySystem.archive_memory(mem)
        MemoryDecaySystem.archive_memory(mem)
        assert mem.archived is True


class TestApplyForgetDecay:
    def test_updates_scores_in_place(self):
        memories = [_memory("m1", days_old=100), _memory("m2", days_old=0)]
        MemoryDecaySystem().apply_forget_decay("u1", memories)
        assert memories[0].forget_score > memories[1].forget_score

    def test_counts_only_increased(self):
        memories = [
            _memory("m1", days_old=100),
            _memory("m2", days_old=100, archived=True),
            _memory("m3", days_old=100, superseded_by="m1"),
        ]
        # 只有 m1 参与统计（archived / superseded 会被 skip，分数不更新）
        assert MemoryDecaySystem().apply_forget_decay("u1", memories) == 1

    def test_skips_archived_and_superseded(self):
        memories = [
            _memory("m1", days_old=100, archived=True),
            _memory("m2", days_old=100, superseded_by="m1"),
        ]
        assert MemoryDecaySystem().apply_forget_decay("u1", memories) == 0
        assert all(m.forget_score == 0.0 for m in memories)

    def test_empty_list(self):
        assert MemoryDecaySystem().apply_forget_decay("u1", []) == 0


class TestProcessMemories:
    def test_returns_same_length(self):
        memories = [_memory("m1"), _memory("m2"), _memory("m3")]
        assert len(MemoryDecaySystem().process_memories(memories)) == 3

    def test_archives_ancient_low_level(self):
        memories = [_memory("m1", days_old=4000, level=1, category="other")]
        result = MemoryDecaySystem().process_memories(memories)
        assert result[0].archived is True

    def test_keeps_fresh_memory(self):
        memories = [_memory("m1", days_old=0, level=1)]
        result = MemoryDecaySystem().process_memories(memories)
        assert result[0].archived is False

    def test_already_archived_untouched(self):
        mem = _memory("m1", days_old=4000, level=1, archived=True)
        MemoryDecaySystem().process_memories([mem])
        # 已归档的不再重算分数（保持原值 0.0）
        assert mem.forget_score == 0.0

    def test_scores_written_back(self):
        mem = _memory("m1", days_old=50, level=5)
        MemoryDecaySystem().process_memories([mem])
        assert mem.forget_score > 0.0
