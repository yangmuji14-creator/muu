"""`core/emotion/mood.py` 的测试

情绪状态机：2D 坐标（valence / arousal）、衰减回归中性、按时间调节精力、
SQLite 持久化、上下文与 emoji 渲染。

⚠️ 关键契约（改之前先读）：
- `get_mood()` **每次调用都会尝试衰减**，但半小时内不动（除非 ``force``）。
- 衰减后的 mood 由坐标重新查最近邻得到，不是记住旧值。
- `to_dict()` 只在 `expires_at` 非空时才带这个键 —— 反序列化必须能补默认。
- `_init_db` 显式 `conn.close()`：`with open_db(...)` 只管事务不关连接。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from core.emotion.analyzer import EMOTION_LABELS, EmotionResult, EmotionType
from core.emotion.mood import (
    EMOTION_TO_MOOD,
    MOOD_BEHAVIOR,
    MOOD_COORDS,
    MOOD_DURATION_HOURS,
    MOOD_EMOJI_MAP,
    MoodEngine,
    MoodState,
    MoodType,
)


def _emotion(kind: EmotionType = EmotionType.HAPPY, intensity: float = 0.8) -> EmotionResult:
    return EmotionResult(emotion=kind, intensity=intensity, keywords=[])


@pytest.fixture()
def engine(tmp_path):
    e = MoodEngine(tmp_path)
    yield e
    e.close()


# --------------------------------------------------------------------------- #
# 常量表
# --------------------------------------------------------------------------- #


class TestConstants:
    def test_every_mood_has_coords(self) -> None:
        assert set(MOOD_COORDS) == set(MoodType)

    def test_every_mood_has_emoji(self) -> None:
        assert set(MOOD_EMOJI_MAP) == set(MoodType)

    def test_every_mood_has_behavior(self) -> None:
        assert set(MOOD_BEHAVIOR) == set(MoodType)

    def test_every_mood_has_duration(self) -> None:
        assert set(MOOD_DURATION_HOURS) == set(MoodType)

    def test_neutral_duration_zero(self) -> None:
        """中性不过期，用 0 表示「永不到期」。"""
        assert MOOD_DURATION_HOURS[MoodType.NEUTRAL] == 0.0

    def test_coords_in_range(self) -> None:
        for mood, (v, a) in MOOD_COORDS.items():
            assert -1.0 <= v <= 1.0, mood
            assert 0.0 <= a <= 1.0, mood

    def test_neutral_at_origin(self) -> None:
        assert MOOD_COORDS[MoodType.NEUTRAL] == (0.0, 0.0)

    def test_emotion_to_mood_covers_emotion_type(self) -> None:
        assert set(EMOTION_TO_MOOD) == set(EmotionType)

    def test_emotion_to_mood_targets_are_moods(self) -> None:
        for target in EMOTION_TO_MOOD.values():
            assert isinstance(target, MoodType)

    def test_every_mood_has_chinese_label(self) -> None:
        """`get_mood_context` 会把枚举值翻成中文，缺了就会拼出「比较happy」。"""
        missing = [m.value for m in MoodType if m.value not in EMOTION_LABELS]
        assert missing == []


# --------------------------------------------------------------------------- #
# MoodState
# --------------------------------------------------------------------------- #


class TestMoodState:
    def test_defaults(self) -> None:
        state = MoodState()
        assert state.mood is MoodType.NEUTRAL
        assert state.valence == 0.0
        assert state.arousal == 0.0
        assert state.intensity == 0.0
        assert state.energy == 0.5
        assert state.expires_at is None

    def test_to_dict_rounds_floats(self) -> None:
        state = MoodState(valence=0.123456, arousal=0.987654)
        data = state.to_dict()
        assert data["valence"] == 0.123
        assert data["arousal"] == 0.988

    def test_to_dict_uses_enum_value(self) -> None:
        assert MoodState(mood=MoodType.HAPPY).to_dict()["mood"] == "happy"

    def test_to_dict_omits_empty_expires(self) -> None:
        assert "expires_at" not in MoodState().to_dict()

    def test_to_dict_keeps_expires(self) -> None:
        state = MoodState(expires_at="2030-01-01T00:00:00")
        assert state.to_dict()["expires_at"] == "2030-01-01T00:00:00"

    def test_roundtrip(self) -> None:
        state = MoodState(mood=MoodType.LOVE, valence=0.9, arousal=0.5,
                          intensity=0.7, energy=0.8,
                          expires_at="2030-01-01T00:00:00")
        restored = MoodState.from_dict(state.to_dict())
        assert restored.mood is MoodType.LOVE
        assert restored.valence == 0.9
        assert restored.arousal == 0.5
        assert restored.intensity == 0.7
        assert restored.energy == 0.8
        assert restored.expires_at == "2030-01-01T00:00:00"

    def test_from_dict_fills_defaults(self) -> None:
        restored = MoodState.from_dict({})
        assert restored.mood is MoodType.NEUTRAL
        assert restored.energy == 0.5
        assert restored.expires_at is None

    def test_from_dict_unknown_mood_raises(self) -> None:
        with pytest.raises(ValueError):
            MoodState.from_dict({"mood": "not-a-mood"})

    def test_is_expired_without_expiry(self) -> None:
        assert MoodState().is_expired() is False

    def test_is_expired_past(self) -> None:
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        assert MoodState(expires_at=past).is_expired() is True

    def test_is_expired_future(self) -> None:
        future = (datetime.now() + timedelta(hours=1)).isoformat()
        assert MoodState(expires_at=future).is_expired() is False

    def test_is_expired_bad_value(self) -> None:
        assert MoodState(expires_at="not-a-date").is_expired() is False


# --------------------------------------------------------------------------- #
# SQLite 持久化
# --------------------------------------------------------------------------- #


class TestPersistence:
    def test_fresh_user_gets_neutral(self, engine) -> None:
        assert engine.get_mood("u1").mood is MoodType.NEUTRAL

    def test_state_survives_new_engine(self, tmp_path) -> None:
        first = MoodEngine(tmp_path)
        first._save("u1", MoodState(mood=MoodType.HAPPY, valence=0.8,
                                    arousal=0.6, intensity=0.7))
        first.close()

        second = MoodEngine(tmp_path)
        try:
            restored = second.get_mood("u1")
            assert restored.mood is MoodType.HAPPY
            assert restored.valence == pytest.approx(0.8, abs=0.2)
        finally:
            second.close()

    def test_users_isolated(self, engine) -> None:
        engine._save("a", MoodState(mood=MoodType.ANGRY, valence=-0.8, arousal=0.9))
        assert engine.get_mood("b").mood is MoodType.NEUTRAL

    def test_corrupt_json_falls_back_to_neutral(self, engine) -> None:
        engine._conn.execute(
            "INSERT OR REPLACE INTO moods (user_id, state) VALUES (?, ?)",
            ("bad", "{not json"),
        )
        engine._conn.commit()
        assert engine.get_mood("bad").mood is MoodType.NEUTRAL

    def test_unknown_mood_value_falls_back(self, engine) -> None:
        engine._conn.execute(
            "INSERT OR REPLACE INTO moods (user_id, state) VALUES (?, ?)",
            ("weird", json.dumps({"mood": "tornado", "valence": 0.5})),
        )
        engine._conn.commit()
        assert engine.get_mood("weird").mood is MoodType.NEUTRAL

    def test_missing_keys_fall_back(self, engine) -> None:
        engine._conn.execute(
            "INSERT OR REPLACE INTO moods (user_id, state) VALUES (?, ?)",
            ("partial", json.dumps({"mood": "happy"})),
        )
        engine._conn.commit()
        assert engine.get_mood("partial").mood is MoodType.HAPPY

    def test_table_created(self, engine) -> None:
        rows = engine._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='moods'"
        ).fetchall()
        assert len(rows) == 1

    def test_cache_used_on_second_read(self, engine) -> None:
        first = engine.get_mood("u1")
        engine._cache["u1"].energy = 0.11
        assert engine.get_mood("u1").energy == 0.11
        assert first is engine.get_mood("u1")

    def test_reset_writes_neutral(self, engine) -> None:
        engine._save("u1", MoodState(mood=MoodType.ANGRY, valence=-0.8, arousal=0.9))
        engine.reset("u1")
        mood = engine.get_mood("u1")
        assert mood.mood is MoodType.NEUTRAL
        assert mood.valence == 0.0

    def test_close_is_idempotent(self, tmp_path) -> None:
        e = MoodEngine(tmp_path)
        e.get_mood("u1")
        e.close()
        e.close()  # 不该抛

    def test_close_before_any_query(self, tmp_path) -> None:
        """`close()` 里 `hasattr(self._local, "conn")` 为假时的兜底分支。"""
        e = MoodEngine(tmp_path)
        e.close()  # 没查过任何 user，thread-local 上还没有 conn

    def test_close_survives_broken_checkpoint(self, tmp_path, monkeypatch) -> None:
        """`PRAGMA wal_checkpoint` 失败不该阻断 close（连接会泄漏）。"""
        e = MoodEngine(tmp_path)
        e.get_mood("u1")
        conn = e._local.conn

        class BrokenConn:
            def execute(self, *a, **k):
                raise RuntimeError("checkpoint failed")

            def close(self):
                conn.close()

        e._local.conn = BrokenConn()
        e.close()
        assert e._local.conn is None


# --------------------------------------------------------------------------- #
# update_from_emotion
# --------------------------------------------------------------------------- #


class TestUpdateFromEmotion:
    def test_moves_toward_detected_mood(self, engine) -> None:
        mood = engine.update_from_emotion("u1", _emotion(EmotionType.HAPPY, 1.0))
        assert mood.valence > 0
        assert mood.arousal > 0

    def test_negative_emotion_moves_valence_down(self, engine) -> None:
        mood = engine.update_from_emotion("u1", _emotion(EmotionType.SAD, 1.0))
        assert mood.valence < 0

    def test_influence_scales_with_intensity(self, engine) -> None:
        weak = engine.update_from_emotion("a", _emotion(EmotionType.HAPPY, 0.1))
        strong = engine.update_from_emotion("b", _emotion(EmotionType.HAPPY, 1.0))
        assert strong.valence > weak.valence

    def test_positive_emotion_raises_energy(self, engine) -> None:
        engine._save("u1", MoodState(energy=0.5))
        assert engine.update_from_emotion("u1", _emotion(EmotionType.HAPPY, 1.0)).energy > 0.5

    def test_negative_emotion_lowers_energy(self, engine) -> None:
        engine._save("u1", MoodState(energy=0.5))
        assert engine.update_from_emotion("u1", _emotion(EmotionType.SAD, 1.0)).energy < 0.5

    def test_energy_clamped_high(self, engine) -> None:
        engine._save("u1", MoodState(energy=0.99))
        assert engine.update_from_emotion("u1", _emotion(EmotionType.HAPPY, 1.0)).energy <= 1.0

    def test_energy_clamped_low(self, engine) -> None:
        engine._save("u1", MoodState(energy=0.01))
        assert engine.update_from_emotion("u1", _emotion(EmotionType.SAD, 1.0)).energy >= 0.0

    def test_valence_clamped(self, engine) -> None:
        for _ in range(20):
            mood = engine.update_from_emotion("u1", _emotion(EmotionType.EXCITED, 1.0))
        assert -1.0 <= mood.valence <= 1.0
        assert 0.0 <= mood.arousal <= 1.0

    def test_sets_nearest_mood(self, engine) -> None:
        mood = engine.update_from_emotion("u1", _emotion(EmotionType.LOVE, 1.0))
        for _ in range(15):
            mood = engine.update_from_emotion("u1", _emotion(EmotionType.LOVE, 1.0))
        assert mood.mood is MoodType.LOVE

    def test_expires_at_set_for_non_neutral(self, engine) -> None:
        mood = engine.update_from_emotion("u1", _emotion(EmotionType.HAPPY, 1.0))
        if mood.mood is not MoodType.NEUTRAL:
            assert mood.expires_at is not None

    def test_expired_state_resets_first(self, engine) -> None:
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        engine._save("u1", MoodState(mood=MoodType.ANGRY, valence=-0.9,
                                      arousal=0.9, expires_at=past))
        engine._cache.pop("u1", None)
        mood = engine.update_from_emotion("u1", _emotion(EmotionType.HAPPY, 1.0))
        assert mood.valence > -0.9

    def test_updated_at_refreshed(self, engine) -> None:
        before = engine.get_mood("u1").updated_at
        mood = engine.update_from_emotion("u1", _emotion(EmotionType.HAPPY, 1.0))
        assert mood.updated_at >= before

    def test_neutral_emotion_leaves_energy_untouched(self, engine) -> None:
        """目标 valence 正好是 0（NEUTRAL）时，两个 energy 分支都不进 ——
        `if > 0` / `elif < 0` 都不成立，精力保持原值。"""
        engine._save("u1", MoodState(energy=0.42))
        mood = engine.update_from_emotion("u1", _emotion(EmotionType.NEUTRAL, 0.0))
        assert mood.energy == pytest.approx(0.42)

    def test_persisted_after_update(self, engine) -> None:
        engine.update_from_emotion("u1", _emotion(EmotionType.HAPPY, 1.0))
        row = engine._conn.execute(
            "SELECT state FROM moods WHERE user_id=?", ("u1",)
        ).fetchone()
        assert row is not None


# --------------------------------------------------------------------------- #
# 过期时间
# --------------------------------------------------------------------------- #


class TestSetExpiresAt:
    def test_neutral_clears_expiry(self) -> None:
        state = MoodState(mood=MoodType.NEUTRAL, expires_at="2030-01-01T00:00:00")
        MoodEngine._set_expires_at(state)
        assert state.expires_at is None

    def test_zero_duration_clears_expiry(self, monkeypatch) -> None:
        state = MoodState(mood=MoodType.HAPPY)
        monkeypatch.setitem(MOOD_DURATION_HOURS, MoodType.HAPPY, 0.0)
        MoodEngine._set_expires_at(state)
        assert state.expires_at is None

    def test_scaled_by_intensity(self) -> None:
        weak = MoodState(mood=MoodType.SAD, intensity=0.1)
        strong = MoodState(mood=MoodType.SAD, intensity=1.0)
        MoodEngine._set_expires_at(weak)
        MoodEngine._set_expires_at(strong)
        assert datetime.fromisoformat(strong.expires_at) > datetime.fromisoformat(weak.expires_at)

    def test_future_timestamp(self) -> None:
        state = MoodState(mood=MoodType.CALM, intensity=0.5)
        MoodEngine._set_expires_at(state)
        assert datetime.fromisoformat(state.expires_at) > datetime.now()

    def test_all_durations_positive_except_neutral(self) -> None:
        """`_set_expires_at` 走 `MOOD_DURATION_HOURS.get(mood, 0.0)`，
        所以表里缺项等于「永不过期」。除 NEUTRAL 外都该有正值。"""
        for mood, hours in MOOD_DURATION_HOURS.items():
            if mood is MoodType.NEUTRAL:
                continue
            assert hours > 0, mood


# --------------------------------------------------------------------------- #
# 衰减
# --------------------------------------------------------------------------- #


class TestDecay:
    def test_skipped_within_half_hour(self, engine) -> None:
        engine._save("u1", MoodState(mood=MoodType.HAPPY, valence=0.8, arousal=0.6))
        engine.get_mood("u1")  # 首次加载触发衰减
        before = engine._cache["u1"].valence
        engine.get_mood("u1")
        assert engine._cache["u1"].valence == before

    def test_force_bypasses_window(self, engine) -> None:
        """`force=True` 只跳过「不足半小时」的时间窗，不改变衰减系数本身：
        刚保存的 state 距上次衰减 0 小时，乘以系数后仍是原值。所以这里
        先把 `last_decay_at` 推到 5 小时前，验证 force 能越过窗口设置。"""
        state = MoodState(mood=MoodType.HAPPY, valence=0.8, arousal=0.6,
                          last_decay_at=(datetime.now() - timedelta(hours=5)).isoformat())
        engine._apply_decay(state, force=True)
        assert abs(state.valence) < 0.8

    def test_pulls_toward_zero(self, engine) -> None:
        state = MoodState(mood=MoodType.ANGRY, valence=-0.8, arousal=0.9,
                          last_decay_at=(datetime.now() - timedelta(hours=5)).isoformat())
        engine._apply_decay(state)
        assert state.valence > -0.8
        assert state.arousal < 0.9

    def test_decay_capped_at_half(self, engine) -> None:
        state = MoodState(valence=1.0, arousal=1.0,
                          last_decay_at=(datetime.now() - timedelta(days=30)).isoformat())
        engine._apply_decay(state)
        assert state.valence == pytest.approx(0.5, abs=0.01)

    def test_bad_timestamp_treated_as_now(self, engine) -> None:
        state = MoodState(mood=MoodType.HAPPY, valence=0.8,
                          last_decay_at="not-a-date")
        engine._apply_decay(state, force=True)
        assert abs(state.valence) <= 0.8

    def test_near_zero_becomes_neutral(self, engine) -> None:
        state = MoodState(mood=MoodType.HAPPY, valence=0.01, arousal=0.01,
                          last_decay_at=(datetime.now() - timedelta(hours=10)).isoformat())
        engine._apply_decay(state)
        assert state.mood is MoodType.NEUTRAL
        assert state.intensity == 0.0

    def test_energy_pulled_to_time_target(self, engine) -> None:
        state = MoodState(energy=0.0,
                          last_decay_at=(datetime.now() - timedelta(hours=3)).isoformat())
        engine._apply_decay(state)
        assert state.energy > 0.0

    def test_energy_clamped(self, engine) -> None:
        state = MoodState(energy=2.0,
                          last_decay_at=(datetime.now() - timedelta(hours=3)).isoformat())
        engine._apply_decay(state)
        assert state.energy <= 1.0

    def test_decay_moves_mood_to_new_nearest(self, engine) -> None:
        state = MoodState(mood=MoodType.ECSTATIC, valence=0.6, arousal=0.6,
                          last_decay_at=(datetime.now() - timedelta(hours=8)).isoformat())
        engine._apply_decay(state)
        assert state.mood is not MoodType.ECSTATIC

    def test_last_decay_at_refreshed(self, engine) -> None:
        old = (datetime.now() - timedelta(hours=5)).isoformat()
        state = MoodState(valence=0.5, last_decay_at=old)
        engine._apply_decay(state)
        assert state.last_decay_at != old

    def test_decay_mood_public_api(self, engine) -> None:
        engine._save("u1", MoodState(mood=MoodType.HAPPY, valence=0.8, arousal=0.6))
        engine.decay_mood("u1")
        assert abs(engine._cache["u1"].valence) <= 0.8

    @pytest.mark.parametrize("hour,target", [
        (8, 0.7), (14, 0.6), (20, 0.5), (2, 0.3),
    ])
    def test_time_of_day_targets(self, engine, monkeypatch, hour, target) -> None:
        class FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 10, 22, hour, 0, 0)

        monkeypatch.setattr("core.emotion.mood.datetime", FakeDatetime)
        state = MoodState(energy=target, last_decay_at=datetime(2026, 10, 22, hour, 0, 0).isoformat())
        engine._apply_decay(state, force=True)
        # 已在该时段目标附近 → 不会被推离太远
        assert abs(state.energy - target) < 0.1


# --------------------------------------------------------------------------- #
# 最近邻
# --------------------------------------------------------------------------- #


class TestFindNearestMood:
    def test_origin_is_neutral(self) -> None:
        mood, dist = MoodEngine._find_nearest_mood(0.0, 0.0)
        assert mood is MoodType.NEUTRAL
        assert dist == 0.0

    def test_high_high_is_excited_or_ecstatic(self) -> None:
        mood, _ = MoodEngine._find_nearest_mood(0.95, 0.95)
        assert mood in {MoodType.EXCITED, MoodType.ECSTATIC}

    def test_low_low_is_sad(self) -> None:
        mood, _ = MoodEngine._find_nearest_mood(-0.6, 0.2)
        assert mood is MoodType.SAD

    def test_distance_is_euclidean(self) -> None:
        _, dist = MoodEngine._find_nearest_mood(0.3, 0.1)
        assert dist == pytest.approx(0.0, abs=0.1)  # 正好是 CALM 的坐标

    def test_returns_tuple(self) -> None:
        result = MoodEngine._find_nearest_mood(0.5, 0.5)
        assert len(result) == 2
        assert isinstance(result[0], MoodType)
        assert isinstance(result[1], float)


# --------------------------------------------------------------------------- #
# 上下文 / emoji
# --------------------------------------------------------------------------- #


class TestContext:
    def test_starts_with_prefix(self, engine) -> None:
        assert engine.get_mood_context("u1").startswith("你现在的情绪状态：")

    def test_chinese_label_not_english(self, engine) -> None:
        """英文枚举值不能直接拼中文句子（曾出现「比较happy」）。"""
        ctx = engine.get_mood_context("u1")
        assert "happy" not in ctx
        assert "neutral" not in ctx

    @pytest.mark.parametrize("intensity,prefix", [
        (0.1, "稍微"), (0.3, ""), (0.6, "比较"), (0.9, "非常"),
    ])
    def test_intensity_prefix(self, engine, intensity, prefix) -> None:
        engine._save("u1", MoodState(mood=MoodType.CALM, intensity=intensity,
                                      valence=0.3, arousal=0.1))
        ctx = engine.get_mood_context("u1")
        assert f"情绪状态：{prefix}" in ctx

    def test_contains_behavior(self, engine) -> None:
        engine._save("u1", MoodState(mood=MoodType.LOVE, intensity=0.8,
                                      valence=0.9, arousal=0.5))
        assert MOOD_BEHAVIOR[MoodType.LOVE] in engine.get_mood_context("u1")

    def test_emoji_for_neutral(self, engine) -> None:
        assert engine.get_mood_emoji("u1") == MOOD_EMOJI_MAP[MoodType.NEUTRAL]

    def test_emoji_follows_mood(self, engine) -> None:
        engine._save("u1", MoodState(mood=MoodType.LOVE, valence=0.9, arousal=0.5))
        assert engine.get_mood_emoji("u1") == MOOD_EMOJI_MAP[MoodType.LOVE]


# --------------------------------------------------------------------------- #
# 初始化细节
# --------------------------------------------------------------------------- #


class TestInit:
    def test_creates_data_dir(self, tmp_path) -> None:
        target = tmp_path / "nested" / "dir"
        e = MoodEngine(target)
        try:
            assert target.exists()
        finally:
            e.close()

    def test_db_path_under_data_dir(self, tmp_path) -> None:
        e = MoodEngine(tmp_path)
        try:
            assert e._db_path.parent == tmp_path
        finally:
            e.close()

    def test_repeated_instantiation_is_safe(self, tmp_path) -> None:
        """`_init_db` 每次实例化都开一次连接，必须自己关掉。"""
        for _ in range(3):
            MoodEngine(tmp_path).close()
