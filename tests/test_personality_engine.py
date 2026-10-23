"""人格引擎（core/personality/engine.py）。

这是「动态人格成长」那套五维模型：trust / dependence / openness /
affection / jealousy，每个维度 0~1。测试重点是三件容易错的事：

1. 衰减要记账 —— 每次 get_state 都按旧时间戳重复扣减会把值几小时内打到下限；
2. 模板只在「全新用户」时生效，已有状态不能被 profile 参数覆盖；
3. 维度值必须夹在 [MIN_DIMENSION, MAX_DIMENSION] 内（LLM 给的偏移可以叠加很多次）。

用 tmp_path 隔离数据库，不碰真实 data/。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.personality.engine import PersonalityEngine, PersonalityState
from core.social.affection.constants import MAX_DIMENSION, MIN_DIMENSION


@pytest.fixture()
def engine(tmp_path):
    eng = PersonalityEngine(tmp_path)
    yield eng
    eng.close()


def _backdate(state: PersonalityState, days: float) -> None:
    state.last_interaction = (datetime.now() - timedelta(days=days)).isoformat()


class TestPersonalityStateModel:
    def test_defaults(self):
        state = PersonalityState()
        assert (state.trust, state.dependence, state.openness, state.affection, state.jealousy) == (
            0.3,
            0.2,
            0.3,
            0.2,
            0.3,
        )
        assert state.total_interactions == 0

    def test_to_dict_rounds_to_three(self):
        state = PersonalityState(trust=0.123456789)
        assert state.to_dict()["trust"] == 0.123

    def test_to_dict_has_all_metadata_keys(self):
        keys = set(PersonalityState().to_dict())
        assert keys == {
            "trust",
            "dependence",
            "openness",
            "affection",
            "jealousy",
            "total_interactions",
            "total_duration_minutes",
            "last_interaction",
            "created_at",
            "positive_count",
            "negative_count",
            "neutral_count",
        }

    def test_from_dict_roundtrip(self):
        src = PersonalityState(
            trust=0.61,
            dependence=0.42,
            openness=0.55,
            affection=0.73,
            jealousy=0.14,
            total_interactions=12,
            positive_count=7,
            negative_count=2,
            neutral_count=3,
        )
        restored = PersonalityState.from_dict(src.to_dict())
        assert restored.to_dict() == src.to_dict()

    def test_from_dict_fills_defaults(self):
        """缺字段用默认值补，不能 KeyError。"""
        restored = PersonalityState.from_dict({"trust": 0.9})
        assert restored.trust == 0.9
        assert restored.dependence == 0.2
        assert restored.jealousy == 0.3

    def test_json_serializable(self):
        import json

        json.dumps(PersonalityState().to_dict())


class TestBaseProfiles:
    def test_profiles_are_all_in_range(self):
        for name, state in PersonalityEngine.BASE_PROFILES.items():
            for dim in ("trust", "dependence", "openness", "affection", "jealousy"):
                val = getattr(state, dim)
                assert MIN_DIMENSION <= val <= MAX_DIMENSION, f"{name}.{dim}={val}"

    def test_expected_profile_names(self):
        assert set(PersonalityEngine.BASE_PROFILES) == {"热情", "高冷", "温柔", "活泼", "傲娇"}

    def test_profiles_differ(self):
        """五个模板必须真的不一样，否则 profile 参数就是摆设。"""
        seen = {
            tuple(
                getattr(s, d) for d in ("trust", "dependence", "openness", "affection", "jealousy")
            )
            for s in PersonalityEngine.BASE_PROFILES.values()
        }
        assert len(seen) == len(PersonalityEngine.BASE_PROFILES)


class TestGetState:
    def test_new_user_gets_defaults(self, engine):
        state = engine.get_state("u1")
        assert state.trust == 0.3
        assert state.total_interactions == 0

    def test_profile_applied_to_new_user(self, engine):
        state = engine.get_state("u1", profile="高冷")
        assert state.trust == 0.2
        assert state.jealousy == 0.4

    def test_unknown_profile_falls_back_to_defaults(self, engine):
        state = engine.get_state("u1", profile="不存在的模板")
        assert state.trust == 0.3

    def test_profile_does_not_override_existing_state(self, engine):
        """老用户传 profile 不该重置 —— 只有 total_interactions==0 才套模板。"""
        engine.update_from_llm("u1", personality_shift={"trust": "up"})
        state = engine.get_state("u1", profile="高冷")
        assert state.trust != 0.2
        assert state.total_interactions >= 1

    def test_cached_between_calls(self, engine):
        a = engine.get_state("u1")
        b = engine.get_state("u1")
        assert a is b

    def test_persisted_across_instances(self, tmp_path):
        eng1 = PersonalityEngine(tmp_path)
        eng1.update_from_llm("u1", personality_shift={"trust": "up"})
        trust = eng1.get_state("u1").trust
        eng1.close()

        eng2 = PersonalityEngine(tmp_path)
        try:
            assert eng2.get_state("u1").trust == pytest.approx(trust)
        finally:
            eng2.close()


class TestDecay:
    def test_no_decay_within_one_day(self, engine):
        state = engine.get_state("u1")
        before = state.trust
        _backdate(state, 0.5)
        engine.get_state("u1")
        assert state.trust == before

    def test_decay_after_days(self, engine):
        state = engine.get_state("u1")
        before = state.trust
        _backdate(state, 5)
        engine.get_state("u1")
        assert state.trust < before

    def test_decay_is_capped_at_ten_percent(self, engine):
        state = engine.get_state("u1")
        before = state.trust
        _backdate(state, 365)
        engine.get_state("u1")
        assert before - state.trust == pytest.approx(0.1)

    def test_decay_floor(self, engine):
        """连续衰减不得跌破 0.1（五个维度的硬下限）。"""
        state = engine.get_state("u1")
        state.trust = 0.11
        for _ in range(5):
            _backdate(state, 30)
            engine.get_state("u1")
        assert state.trust == pytest.approx(0.1)

    def test_dependence_decays_faster(self, engine):
        state = engine.get_state("u1")
        state.trust = 0.8
        state.dependence = 0.8
        _backdate(state, 10)
        engine.get_state("u1")
        assert 0.8 - state.dependence > 0.8 - state.trust

    def test_decay_updates_last_interaction(self, engine):
        """关键回归点：衰减后必须把时间戳推到当下。"""
        state = engine.get_state("u1")
        _backdate(state, 10)
        old_stamp = state.last_interaction
        engine.get_state("u1")
        assert state.last_interaction != old_stamp

    def test_repeated_get_state_does_not_double_decay(self, engine):
        """不记账的话，同一天里每调一次 get_state 就再扣一次。"""
        state = engine.get_state("u1")
        _backdate(state, 10)
        engine.get_state("u1")
        after_first = state.trust
        for _ in range(5):
            engine.get_state("u1")
        assert state.trust == after_first

    def test_broken_timestamp_survives(self, engine):
        state = engine.get_state("u1")
        state.last_interaction = "不是时间"
        assert engine.get_state("u1") is state

    def test_none_timestamp_survives(self, engine):
        state = engine.get_state("u1")
        state.last_interaction = None
        assert engine.get_state("u1") is state


class TestUpdateFromLlm:
    def test_shift_up_increases(self, engine):
        before = engine.get_state("u1").trust
        engine.update_from_llm("u1", personality_shift={"trust": "up"})
        assert engine.get_state("u1").trust == pytest.approx(before + 0.02)

    def test_shift_down_decreases(self, engine):
        before = engine.get_state("u1").trust
        engine.update_from_llm("u1", personality_shift={"trust": "down"})
        assert engine.get_state("u1").trust == pytest.approx(before - 0.02)

    def test_no_change_keeps_value(self, engine):
        before = engine.get_state("u1").trust
        engine.update_from_llm("u1", personality_shift={"trust": "no_change"})
        assert engine.get_state("u1").trust == pytest.approx(before)

    def test_unknown_dimension_ignored(self, engine):
        before = engine.get_state("u1").trust
        engine.update_from_llm("u1", personality_shift={"不存在的维度": "up"})
        assert engine.get_state("u1").trust == pytest.approx(before)

    def test_unknown_direction_ignored(self, engine):
        before = engine.get_state("u1").trust
        engine.update_from_llm("u1", personality_shift={"trust": "乱写"})
        assert engine.get_state("u1").trust == pytest.approx(before)

    def test_none_shift_only_counts_interaction(self, engine):
        engine.update_from_llm("u1", personality_shift=None)
        assert engine.get_state("u1").total_interactions == 1

    def test_interaction_counter_increments(self, engine):
        for i in range(3):
            engine.update_from_llm("u1", personality_shift={"trust": "up"})
            assert engine.get_state("u1").total_interactions == i + 1

    def test_update_touches_last_interaction(self, engine):
        state = engine.get_state("u1")
        _backdate(state, 3)
        engine.update_from_llm("u1", personality_shift={"trust": "up"})
        assert state.last_interaction > (datetime.now() - timedelta(minutes=1)).isoformat()

    def test_clamped_at_max(self, engine):
        state = engine.get_state("u1")
        state.trust = MAX_DIMENSION - 0.01
        engine.update_from_llm("u1", personality_shift={"trust": "up"})
        assert state.trust == pytest.approx(MAX_DIMENSION)

    def test_clamped_at_min(self, engine):
        state = engine.get_state("u1")
        state.trust = MIN_DIMENSION + 0.01
        engine.update_from_llm("u1", personality_shift={"trust": "down"})
        assert state.trust == pytest.approx(MIN_DIMENSION)

    def test_many_updates_never_exceed_bounds(self, engine):
        for _ in range(200):
            engine.update_from_llm(
                "u1", personality_shift={d: "up" for d in ("trust", "dependence", "openness")}
            )
        state = engine.get_state("u1")
        for dim in ("trust", "dependence", "openness", "affection", "jealousy"):
            assert MIN_DIMENSION <= getattr(state, dim) <= MAX_DIMENSION

    def test_affection_impact_accepted_without_crash(self, engine):
        """签名里有 affection_impact，当前实现不消费 —— 传了也不该炸。"""
        engine.update_from_llm(
            "u1",
            affection_impact={"direction": "positive", "level": "high", "reason": "夸他"},
            personality_shift={"trust": "up"},
            persona_id="girlfriend_001",
        )
        assert engine.get_state("u1").total_interactions == 1

    def test_only_shifts_listed_dimensions(self, engine):
        state = engine.get_state("u1")
        openness_before = state.openness
        engine.update_from_llm("u1", personality_shift={"trust": "up"})
        assert state.openness == openness_before


class TestPersonalityContext:
    def test_header(self, engine):
        text = engine.get_personality_context("u1")
        assert text.startswith("【当前人格状态】")

    def test_five_dimensions_listed(self, engine):
        text = engine.get_personality_context("u1")
        for label in ("信任", "依赖", "开放", "好感", "醋意"):
            assert f"{label}：" in text

    def test_real_newlines_not_literal_backslash_n(self, engine):
        """回归点：这里如果用 `\\\\n`（双反斜杠）会把 prompt 打成一行。"""
        text = engine.get_personality_context("u1")
        assert "\\n" not in text
        assert text.count("\n") == 5

    def test_high_dimension_uses_high_label(self, engine):
        state = engine.get_state("u1")
        state.trust = 0.95
        assert "很信任你" in engine.get_personality_context("u1")

    def test_mid_dimension_uses_mid_label(self, engine):
        state = engine.get_state("u1")
        state.trust = 0.5
        assert "比较信任你" in engine.get_personality_context("u1")

    def test_low_dimension_uses_low_label(self, engine):
        state = engine.get_state("u1")
        state.trust = 0.1
        assert "还在观察你" in engine.get_personality_context("u1")

    def test_thresholds_are_inclusive(self, engine):
        state = engine.get_state("u1")
        state.trust = 0.7
        assert "很信任你" in engine.get_personality_context("u1")
        state.trust = 0.4
        assert "比较信任你" in engine.get_personality_context("u1")


class TestReset:
    def test_reset_clears_to_defaults(self, engine):
        for _ in range(5):
            engine.update_from_llm("u1", personality_shift={"trust": "up"})
        engine.reset("u1")
        state = engine.get_state("u1")
        assert state.trust == 0.3
        assert state.total_interactions == 0

    def test_reset_with_profile(self, engine):
        engine.reset("u1", profile="傲娇")
        state = engine.get_state("u1")
        assert state.jealousy == 0.6

    def test_reset_with_unknown_profile(self, engine):
        engine.reset("u1", profile="乱写")
        assert engine.get_state("u1").trust == 0.3

    def test_reset_persists(self, tmp_path):
        eng = PersonalityEngine(tmp_path)
        eng.update_from_llm("u1", personality_shift={"trust": "up"})
        eng.reset("u1")
        eng.close()

        eng2 = PersonalityEngine(tmp_path)
        try:
            assert eng2.get_state("u1").trust == pytest.approx(0.3)
        finally:
            eng2.close()


class TestStorage:
    def test_users_isolated(self, engine):
        engine.update_from_llm("u1", personality_shift={"trust": "up"})
        assert engine.get_state("u2").trust == pytest.approx(0.3)

    def test_corrupted_row_falls_back(self, engine):
        """DB 里存了坏 JSON → 返回默认状态，不抛。"""
        engine._conn.execute(
            "INSERT OR REPLACE INTO personalities (user_id, state) VALUES (?, ?)",
            ("broken", "{ not json"),
        )
        engine._conn.commit()
        assert engine.get_state("broken").trust == pytest.approx(0.3)

    def test_missing_keys_in_row_filled(self, engine):
        engine._conn.execute(
            "INSERT OR REPLACE INTO personalities (user_id, state) VALUES (?, ?)",
            ("partial", '{"trust": 0.88}'),
        )
        engine._conn.commit()
        state = engine.get_state("partial")
        assert state.trust == pytest.approx(0.88)
        assert state.dependence == pytest.approx(0.2)

    def test_close_is_idempotent(self, tmp_path):
        eng = PersonalityEngine(tmp_path)
        eng.close()
        eng.close()
