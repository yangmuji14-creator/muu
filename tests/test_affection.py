"""亲密度模块测试 — constants / schema / mapper / storage / migration。

约定同其它测试文件：只用 `tmp_path` 与 SQLite `:memory:`，不碰真实 `data/`。

这一套的价值在于把「钟形曲线 + 两端限速 + BASE_BONUS 只加正向」这几条
容易被后人「顺手简化掉」的规则钉死 —— 它们没有注释解释就看不出为什么。
"""

from __future__ import annotations

import json
import random
import sqlite3

import pytest

from core.social.affection.constants import (
    AFFECTION_BELL_CENTER,
    AFFECTION_BELL_SIGMA,
    AFFECTION_JITTER_RATIO,
    AFFECTION_MAX_MAP_STEP,
    AFFECTION_MIN_STEP,
    AFFECTION_PEAK_DELTA,
    AFFECTION_STRENGTH_POWER,
    BASE_BONUS,
    DIRECTION_LEVEL_MAP,
    MAX_AFFECTION,
    MAX_DIMENSION,
    MIN_AFFECTION,
    MIN_DIMENSION,
    PERSONALITY_SHIFT_MAP,
    AffectionDirection,
    AffectionLevel,
)
from core.social.affection.mapper import AffectionMapper
from core.social.affection.migration import (
    _parse_key,
    _validate_record,
    _write_marker,
    migrate_from_legacy,
    rollback_migration,
)
from core.social.affection.schema import (
    CREATE_TABLE_SQL,
    AffectionRecord,
    AffectionStats,
    AffectionStorage,
)
from core.social.affection.storage import UnifiedAffectionStorage


# ── 替身 ─────────────────────────────────────────────────


class _Boom:
    """每个操作都抛异常的连接替身 —— 用来验证「出错也不能炸调用方」。"""

    def execute(self, *args, **kwargs):
        raise sqlite3.OperationalError("boom")

    def commit(self):
        raise sqlite3.OperationalError("boom")

    def rollback(self):
        pass


class _CommitBoom:
    """读正常、只有 commit 失败 —— 用来命中「读完值之后才炸」的分支。"""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, *args, **kwargs):
        return self._conn.execute(*args, **kwargs)

    def commit(self):
        raise sqlite3.OperationalError("commit boom")

    def rollback(self):
        self._conn.rollback()


@pytest.fixture
def storage():
    backend = UnifiedAffectionStorage(":memory:")
    conn = backend._conn  # 有的用例会把 _conn 换成抛异常的替身，关原始连接
    yield backend
    conn.close()


@pytest.fixture
def no_jitter(monkeypatch):
    """把随机抖动掐成恒等，让幅度可被精确断言。"""
    monkeypatch.setattr(random, "gauss", lambda mu, sigma: mu)


# ── 常量与表结构 ─────────────────────────────────────────


class TestConstants:
    def test_direction_level_map_is_complete(self):
        """7 个方向 × 3 个等级，一格都不能少 —— 少一格就是 KeyError。"""
        assert len(DIRECTION_LEVEL_MAP) == 21
        for direction in AffectionDirection:
            for level in AffectionLevel:
                assert (direction, level) in DIRECTION_LEVEL_MAP

    def test_neutral_is_always_zero(self):
        """NEUTRAL 忽略等级。若不成立，每条中性消息都会悄悄加好感。"""
        for level in AffectionLevel:
            assert DIRECTION_LEVEL_MAP[(AffectionDirection.NEUTRAL, level)] == 0.0

    def test_map_is_symmetric(self):
        """正负两个方向必须镜像对称，否则聊天的净收益恒为正。"""
        for level in AffectionLevel:
            for pos, neg in (
                (AffectionDirection.STRONG_POSITIVE, AffectionDirection.STRONG_NEGATIVE),
                (AffectionDirection.POSITIVE, AffectionDirection.NEGATIVE),
                (AffectionDirection.SLIGHT_POSITIVE, AffectionDirection.SLIGHT_NEGATIVE),
            ):
                assert DIRECTION_LEVEL_MAP[(pos, level)] == -DIRECTION_LEVEL_MAP[(neg, level)]

    def test_level_ordering_per_direction(self):
        """同一方向里 HIGH > MEDIUM > LOW（按绝对值）。"""
        for direction in AffectionDirection:
            high = abs(DIRECTION_LEVEL_MAP[(direction, AffectionLevel.HIGH)])
            medium = abs(DIRECTION_LEVEL_MAP[(direction, AffectionLevel.MEDIUM)])
            low = abs(DIRECTION_LEVEL_MAP[(direction, AffectionLevel.LOW)])
            assert high >= medium >= low

    def test_max_map_step_matches_table(self):
        """归一化强度用的分母必须等于表里的最大绝对值。"""
        assert max(abs(v) for v in DIRECTION_LEVEL_MAP.values()) == AFFECTION_MAX_MAP_STEP

    def test_bounds(self):
        assert MIN_AFFECTION == 0
        assert MAX_AFFECTION == 100
        assert MIN_DIMENSION == 0.0
        assert MAX_DIMENSION == 1.0

    def test_personality_shift_map_shape(self):
        assert set(PERSONALITY_SHIFT_MAP) == {"up", "down", "no_change"}
        dimensions = set(PERSONALITY_SHIFT_MAP["up"])
        assert dimensions == {
            "trust", "dependence", "openness", "jealousy", "affection",
        }
        for shift in PERSONALITY_SHIFT_MAP.values():
            assert set(shift) == dimensions

    def test_personality_shift_up_down_are_mirrored(self):
        for key, value in PERSONALITY_SHIFT_MAP["up"].items():
            assert PERSONALITY_SHIFT_MAP["down"][key] == -value

    def test_no_change_is_all_zeros(self):
        assert all(v == 0.0 for v in PERSONALITY_SHIFT_MAP["no_change"].values())

    def test_tuning_constants_are_sane(self):
        assert 0 < AFFECTION_JITTER_RATIO < 1
        assert AFFECTION_PEAK_DELTA > AFFECTION_MIN_STEP
        assert AFFECTION_BELL_CENTER == 50.0
        assert AFFECTION_BELL_SIGMA > 0
        assert 0 < AFFECTION_STRENGTH_POWER <= 1
        assert BASE_BONUS > 0


class TestSchema:
    def test_dataclasses_are_plain(self):
        record = AffectionRecord(
            user_id="u1", persona_id="p1", level=50.0,
            message_count=0, positive_count=0, negative_count=0,
            last_interaction="2026-01-01T00:00:00", created_at="2026-01-01T00:00:00",
        )
        assert record.user_id == "u1"
        stats = AffectionStats(
            level=50.0, message_count=0,
            positive_count=0, negative_count=0, days_known=0,
        )
        assert stats.days_known == 0

    def test_create_table_sql_is_idempotent(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute(CREATE_TABLE_SQL)
            conn.execute(CREATE_TABLE_SQL)
            conn.commit()
            columns = {row[1] for row in conn.execute("PRAGMA table_info(affection)")}
            assert columns == {
                "user_id", "persona_id", "level", "message_count",
                "positive_count", "negative_count", "last_interaction", "created_at",
            }
        finally:
            conn.close()

    def test_default_level_is_50(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute(CREATE_TABLE_SQL)
            conn.execute(
                "INSERT INTO affection (user_id, last_interaction, created_at) "
                "VALUES ('u1', 'now', 'now')"
            )
            row = conn.execute("SELECT level, persona_id FROM affection").fetchone()
            assert row == (50.0, "default")
        finally:
            conn.close()

    def test_storage_satisfies_protocol(self, storage):
        assert isinstance(storage, AffectionStorage)


# ── 映射器 ───────────────────────────────────────────────


class TestParseDirection:
    @pytest.mark.parametrize("value", [None])
    def test_none_is_neutral(self, value):
        assert AffectionMapper._parse_direction(value) is AffectionDirection.NEUTRAL

    def test_enum_passthrough(self):
        for direction in AffectionDirection:
            assert AffectionMapper._parse_direction(direction) is direction

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("positive", AffectionDirection.POSITIVE),
            ("POSITIVE", AffectionDirection.POSITIVE),
            ("  Positive  ", AffectionDirection.POSITIVE),
            ("strong_negative", AffectionDirection.STRONG_NEGATIVE),
            ("slight_positive", AffectionDirection.SLIGHT_POSITIVE),
            ("neutral", AffectionDirection.NEUTRAL),
        ],
    )
    def test_string_is_case_and_space_insensitive(self, text, expected):
        assert AffectionMapper._parse_direction(text) is expected

    @pytest.mark.parametrize("text", ["", "unknown", "非常正面", "positive "[:-1] + "x"])
    def test_unknown_string_falls_back_to_neutral(self, text):
        assert AffectionMapper._parse_direction(text) is AffectionDirection.NEUTRAL

    def test_non_string_falls_back_to_neutral(self):
        """LLM 偶尔会吐数字/None 混进来 —— 不能因此抛 AttributeError。"""
        assert AffectionMapper._parse_direction(3) is AffectionDirection.NEUTRAL
        assert AffectionMapper._parse_direction([]) is AffectionDirection.NEUTRAL


class TestParseLevel:
    def test_none_is_low(self):
        assert AffectionMapper._parse_level(None) is AffectionLevel.LOW

    def test_enum_passthrough(self):
        for level in AffectionLevel:
            assert AffectionMapper._parse_level(level) is level

    @pytest.mark.parametrize(
        ("text", "expected"),
        [("high", AffectionLevel.HIGH), ("MEDIUM", AffectionLevel.MEDIUM),
         ("  low  ", AffectionLevel.LOW)],
    )
    def test_string_is_case_and_space_insensitive(self, text, expected):
        assert AffectionMapper._parse_level(text) is expected

    @pytest.mark.parametrize("text", ["", "huge", "很高"])
    def test_unknown_string_falls_back_to_low(self, text):
        assert AffectionMapper._parse_level(text) is AffectionLevel.LOW

    def test_non_string_falls_back_to_low(self):
        assert AffectionMapper._parse_level(3.5) is AffectionLevel.LOW


class TestGetDelta:
    def test_every_combination_is_reachable_by_string(self):
        """字符串路径必须能取到表里每一格 —— 解析器与表不能有一边掉队。"""
        for direction in AffectionDirection:
            for level in AffectionLevel:
                got = AffectionMapper.get_delta(direction.name.lower(), level.name.lower())
                assert got == DIRECTION_LEVEL_MAP[(direction, level)]

    def test_none_pair_defaults_to_neutral_low(self):
        assert AffectionMapper.get_delta(None, None) == 0.0

    def test_map_is_alias_of_get_delta(self):
        assert AffectionMapper.map("positive", "high") == AffectionMapper.get_delta(
            "positive", "high"
        )


class TestBellFactor:
    def test_none_means_no_attenuation(self):
        assert AffectionMapper.bell_factor(None) == 1.0

    def test_center_is_one(self):
        assert AffectionMapper.bell_factor(AFFECTION_BELL_CENTER) == pytest.approx(1.0)

    def test_decays_away_from_center(self):
        near = AffectionMapper.bell_factor(55)
        far = AffectionMapper.bell_factor(90)
        assert 0 < far < near < 1.0

    def test_symmetric_around_center(self):
        """两端限速必须对称 —— 涨得快跌得慢会让亲密度单向漂移。"""
        for offset in (5, 20, 45):
            up = AffectionMapper.bell_factor(AFFECTION_BELL_CENTER + offset)
            down = AffectionMapper.bell_factor(AFFECTION_BELL_CENTER - offset)
            assert up == pytest.approx(down)

    def test_matches_gaussian_formula(self):
        import math

        level = 70.0
        d = level - AFFECTION_BELL_CENTER
        expected = math.exp(-(d * d) / (2.0 * AFFECTION_BELL_SIGMA ** 2))
        assert AffectionMapper.bell_factor(level) == pytest.approx(expected)


class TestSampleDelta:
    def test_neutral_direction_returns_zero(self, no_jitter):
        assert AffectionMapper.sample_delta("neutral", "high", 50) == 0.0
        assert AffectionMapper.sample_delta(None, None, 50) == 0.0

    def test_sign_follows_direction(self, no_jitter):
        assert AffectionMapper.sample_delta("positive", "high", 50) > 0
        assert AffectionMapper.sample_delta("negative", "high", 50) < 0

    def test_capped_at_peak_delta(self, no_jitter):
        """中段也不能一步跳到底 —— 否则两三句话就满分。"""
        for direction in AffectionDirection:
            for level in AffectionLevel:
                value = AffectionMapper.sample_delta(direction, level, AFFECTION_BELL_CENTER)
                assert abs(value) <= AFFECTION_PEAK_DELTA

    def test_full_strength_at_center(self, no_jitter):
        assert AffectionMapper.sample_delta(
            "strong_positive", "high", AFFECTION_BELL_CENTER
        ) == pytest.approx(AFFECTION_PEAK_DELTA)

    def test_weak_level_is_not_below_min_step(self, no_jitter):
        """弱档位在两端会被钟形压得极小，必须有 MIN_STEP 保底，否则方向被噪声吃掉。"""
        value = AffectionMapper.sample_delta("slight_positive", "low", 0.0)
        assert value == pytest.approx(AFFECTION_MIN_STEP)

    def test_extremes_slower_than_center(self, no_jitter):
        center = abs(AffectionMapper.sample_delta("positive", "high", 50))
        edge = abs(AffectionMapper.sample_delta("positive", "high", 2))
        assert edge < center

    def test_jitter_is_clamped(self, monkeypatch):
        """抖动最多压到一半、放大也只能顶到峰值 —— 不能越界。"""
        monkeypatch.setattr(random, "gauss", lambda mu, sigma: 0.0)
        stunted = AffectionMapper.sample_delta("strong_positive", "high", 50)
        assert stunted == pytest.approx(AFFECTION_PEAK_DELTA * 0.5)

        monkeypatch.setattr(random, "gauss", lambda mu, sigma: 100.0)
        huge = AffectionMapper.sample_delta("strong_positive", "high", 50)
        assert huge == pytest.approx(AFFECTION_PEAK_DELTA)

    def test_none_level_does_not_crash(self, no_jitter):
        assert AffectionMapper.sample_delta("positive", None, None) > 0


class TestMapPersonalityShift:
    def test_up(self):
        assert AffectionMapper.map_personality_shift({"trust": "up"}) == {
            "trust": PERSONALITY_SHIFT_MAP["up"]["trust"]
        }

    def test_down(self):
        assert AffectionMapper.map_personality_shift({"trust": "down"}) == {
            "trust": PERSONALITY_SHIFT_MAP["down"]["trust"]
        }

    def test_unknown_shift_falls_back_to_no_change(self):
        assert AffectionMapper.map_personality_shift({"trust": "sideways"}) == {
            "trust": 0.0
        }

    def test_unknown_dimension_is_skipped(self):
        """未知维度不能塞进返回值 —— 上层会拿它去 update 人格引擎。"""
        assert AffectionMapper.map_personality_shift({"mystery": "up"}) == {}

    def test_empty(self):
        assert AffectionMapper.map_personality_shift({}) == {}

    def test_mixed(self):
        result = AffectionMapper.map_personality_shift(
            {"trust": "up", "openness": "down", "mystery": "up"}
        )
        assert result == {
            "trust": PERSONALITY_SHIFT_MAP["up"]["trust"],
            "openness": PERSONALITY_SHIFT_MAP["down"]["openness"],
        }


# ── 存储后端 ─────────────────────────────────────────────


class TestConstruction:
    def test_memory_mode(self):
        backend = UnifiedAffectionStorage(":memory:")
        try:
            assert backend.get_level("u1") == 50.0
        finally:
            backend._conn.close()

    def test_file_mode(self, tmp_path):
        backend = UnifiedAffectionStorage(tmp_path)
        try:
            backend.update("u1", "positive", "high")
            assert backend.get_level("u1") > 50.0
        finally:
            backend._conn.close()
        assert (tmp_path / "companion.db").exists()

    def test_connection_injection(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(CREATE_TABLE_SQL)
        conn.commit()
        backend = UnifiedAffectionStorage(conn)
        try:
            assert backend._conn is conn
            assert backend._owns_conn is False
            assert backend.get_level("u1") == 50.0
        finally:
            conn.close()

    def test_file_mode_owns_connection(self, tmp_path):
        backend = UnifiedAffectionStorage(tmp_path)
        assert backend._owns_conn is True
        backend._conn.close()


class TestEnsureRecord:
    def test_creates_default_row(self, storage):
        storage._ensure_record("u1")
        row = storage._conn.execute(
            "SELECT level, message_count, positive_count, negative_count "
            "FROM affection WHERE user_id='u1' AND persona_id='default'"
        ).fetchone()
        assert tuple(row) == (50.0, 0, 0, 0)

    def test_is_idempotent(self, storage):
        """第二次调用走 no-op 分支，绝不能把计数清零或堆行。"""
        storage._ensure_record("u1")
        storage._ensure_record("u1")
        count = storage._conn.execute(
            "SELECT COUNT(*) FROM affection WHERE user_id='u1'"
        ).fetchone()[0]
        assert count == 1

    def test_persona_is_part_of_key(self, storage):
        storage._ensure_record("u1", "p1")
        storage._ensure_record("u1", "p2")
        count = storage._conn.execute(
            "SELECT COUNT(*) FROM affection WHERE user_id='u1'"
        ).fetchone()[0]
        assert count == 2


class TestGetLevel:
    def test_default_is_50(self, storage):
        assert storage.get_level("nobody") == 50.0

    def test_reads_written_value(self, storage):
        storage._conn.execute(
            "INSERT INTO affection (user_id, level, last_interaction, created_at) "
            "VALUES ('u1', 77.5, 'now', 'now')"
        )
        storage._conn.commit()
        assert storage.get_level("u1") == 77.5

    def test_persona_isolation(self, storage):
        storage.update("u1", "positive", "high", persona_id="p1")
        assert storage.get_level("u1", "p1") > 50.0
        assert storage.get_level("u1", "p2") == 50.0

    def test_error_returns_default(self, storage):
        storage._conn = _Boom()
        assert storage.get_level("u1") == 50.0


class TestUpdate:
    def test_positive_increases(self, storage, no_jitter):
        assert storage.update("u1", "positive", "high") > 50.0

    def test_negative_decreases(self, storage, no_jitter):
        assert storage.update("u1", "negative", "high") < 50.0

    def test_neutral_keeps_level(self, storage, no_jitter):
        """BASE_BONUS 只加正向。中性必须严格 0，否则每条闲聊都在偷偷涨好感。"""
        assert storage.update("u1", "neutral", "high") == 50.0

    def test_base_bonus_applies_only_to_positive(self, storage, no_jitter):
        before = storage.get_level("u1")
        after = storage.update("u1", "slight_positive", "low")
        raw = AffectionMapper.sample_delta("slight_positive", "low", before)
        assert after == pytest.approx(min(before + raw + BASE_BONUS, MAX_AFFECTION))

    def test_negative_is_not_softened_by_bonus(self, storage, no_jitter):
        """给负向也加 BASE_BONUS 会让高分端无法掉好感 —— 这是回归点。"""
        after = storage.update("u1", "slight_negative", "low")
        assert after < 50.0

    def test_counts_positive(self, storage):
        storage.update("u1", "positive", "high")
        stats = storage.get_stats("u1")
        assert stats.positive_count == 1
        assert stats.negative_count == 0

    def test_counts_negative(self, storage):
        storage.update("u1", "negative", "high")
        stats = storage.get_stats("u1")
        assert stats.negative_count == 1
        assert stats.positive_count == 0

    def test_neutral_counts_neither(self, storage):
        storage.update("u1", "neutral", "high")
        stats = storage.get_stats("u1")
        assert (stats.positive_count, stats.negative_count) == (0, 0)

    def test_message_count_increments(self, storage):
        storage.update("u1", "neutral", "high")
        storage.update("u1", "neutral", "high")
        assert storage.get_stats("u1").message_count == 2

    def test_clamped_at_max(self, storage, no_jitter):
        storage._conn.execute(
            "INSERT INTO affection (user_id, level, last_interaction, created_at) "
            "VALUES ('u1', 99.99, 'now', 'now')"
        )
        storage._conn.commit()
        assert storage.update("u1", "strong_positive", "high") == MAX_AFFECTION

    def test_clamped_at_min(self, storage, no_jitter):
        storage._conn.execute(
            "INSERT INTO affection (user_id, level, last_interaction, created_at) "
            "VALUES ('u1', 0.01, 'now', 'now')"
        )
        storage._conn.commit()
        assert storage.update("u1", "strong_negative", "high") == MIN_AFFECTION

    def test_accepts_enum_direction_and_level(self, storage, no_jitter):
        after = storage.update("u1", AffectionDirection.POSITIVE, AffectionLevel.HIGH)
        assert after > 50.0

    def test_error_returns_last_read_level(self, storage):
        storage._conn = _Boom()
        assert storage.update("u1", "positive", "high") == 50.0

    def test_commit_failure_returns_read_level(self, storage, no_jitter):
        storage._ensure_record("u1")
        storage._conn = _CommitBoom(storage._conn)
        assert storage.update("u1", "positive", "high") == 50.0


class TestGetStats:
    def test_default_stats(self, storage):
        stats = storage.get_stats("nobody")
        assert stats == AffectionStats(
            level=50.0, message_count=0,
            positive_count=0, negative_count=0, days_known=0,
        )

    def test_days_known(self, storage):
        storage._conn.execute(
            "INSERT INTO affection (user_id, level, last_interaction, created_at) "
            "VALUES ('u1', 60.0, '2026-01-01T00:00:00', '2020-01-01T00:00:00')"
        )
        storage._conn.commit()
        assert storage.get_stats("u1").days_known > 365

    def test_error_returns_default(self, storage):
        storage._conn = _Boom()
        assert storage.get_stats("u1").level == 50.0


class TestGetLastInteraction:
    def test_returns_isoformat(self, storage):
        value = storage.get_last_interaction("u1")
        assert isinstance(value, str)
        assert "T" in value

    def test_updates_after_update(self, storage):
        first = storage.get_last_interaction("u1")
        storage.update("u1", "neutral", "high")
        second = storage.get_last_interaction("u1")
        assert second >= first

    def test_error_returns_none(self, storage):
        storage._conn = _Boom()
        assert storage.get_last_interaction("u1") is None


class TestApplyDecay:
    def _set_idle_days(self, storage, days: int, level: float = 80.0) -> None:
        from datetime import datetime, timedelta

        when = (datetime.now() - timedelta(days=days)).isoformat()
        storage._conn.execute(
            "INSERT OR REPLACE INTO affection "
            "(user_id, persona_id, level, message_count, positive_count, "
            " negative_count, last_interaction, created_at) "
            "VALUES ('u1', 'default', ?, 0, 0, 0, ?, ?)",
            (level, when, when),
        )
        storage._conn.commit()

    def test_fresh_does_not_decay(self, storage):
        self._set_idle_days(storage, 2)
        assert storage.apply_decay("u1") == pytest.approx(80.0)

    def test_exactly_three_days_does_not_decay(self, storage):
        self._set_idle_days(storage, 3)
        assert storage.apply_decay("u1") == pytest.approx(80.0)

    def test_decays_after_grace_period(self, storage):
        self._set_idle_days(storage, 10)
        assert storage.apply_decay("u1") == pytest.approx(80.0 - 7 * 0.05)

    def test_clamped_at_min(self, storage):
        self._set_idle_days(storage, 400, level=0.1)
        assert storage.apply_decay("u1") == MIN_AFFECTION

    def test_persists(self, storage):
        self._set_idle_days(storage, 10)
        storage.apply_decay("u1")
        assert storage.get_level("u1") == pytest.approx(80.0 - 7 * 0.05)

    def test_error_returns_default(self, storage):
        storage._conn = _Boom()
        assert storage.apply_decay("u1") == 50.0

    def test_commit_failure_returns_last_known(self, storage):
        self._set_idle_days(storage, 10)
        storage._conn = _CommitBoom(storage._conn)
        assert storage.apply_decay("u1") == pytest.approx(80.0)


class TestMigrateFromJson:
    def _write(self, tmp_path, payload):
        path = tmp_path / "affection.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_flat_key_with_persona(self, storage, tmp_path):
        path = self._write(tmp_path, {"u1__p1": {"level": 88.0, "message_count": 3}})
        assert storage.migrate_from_json(str(path)) is True
        assert storage.get_level("u1", "p1") == 88.0
        assert storage.get_stats("u1", "p1").message_count == 3

    def test_flat_key_without_persona(self, storage, tmp_path):
        path = self._write(tmp_path, {"u1": {"level": 70.0}})
        storage.migrate_from_json(str(path))
        assert storage.get_level("u1", "default") == 70.0

    def test_nested_key(self, storage, tmp_path):
        path = self._write(tmp_path, {"u1": {"p1": {"level": 66.0}}})
        storage.migrate_from_json(str(path))
        assert storage.get_level("u1", "p1") == 66.0

    def test_non_dict_value_is_skipped(self, storage, tmp_path):
        path = self._write(tmp_path, {"u1": 5})
        assert storage.migrate_from_json(str(path)) is True
        assert storage.get_level("u1") == 50.0

    def test_missing_defaults(self, storage, tmp_path):
        path = self._write(tmp_path, {"u1": {"level": 60.0}})
        storage.migrate_from_json(str(path))
        stats = storage.get_stats("u1")
        assert (stats.message_count, stats.positive_count, stats.negative_count) == (0, 0, 0)

    def test_missing_file_returns_false(self, storage, tmp_path):
        assert storage.migrate_from_json(str(tmp_path / "nope.json")) is False

    def test_bad_json_returns_false(self, storage, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        assert storage.migrate_from_json(str(path)) is False

    def test_replace_is_idempotent(self, storage, tmp_path):
        path = self._write(tmp_path, {"u1": {"level": 90.0}})
        storage.migrate_from_json(str(path))
        storage.migrate_from_json(str(path))
        assert storage.get_level("u1") == 90.0


# ── 旧版 JSON 迁移工具 ───────────────────────────────────


class TestParseKey:
    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            ("user1__tsundere", ("user1", "tsundere")),
            ("user2", ("user2", "default")),
            ("a__b__c", ("a", "b__c")),
            ("", ("", "default")),
        ],
    )
    def test_parse(self, key, expected):
        assert _parse_key(key) == expected


class TestValidateRecord:
    def test_valid(self):
        assert _validate_record({"level": 80}) is True
        assert _validate_record({"level": 80.5}) is True

    def test_missing_level_uses_default(self):
        assert _validate_record({}) is True

    def test_non_dict(self):
        assert _validate_record("not a dict") is False
        assert _validate_record(None) is False

    def test_wrong_level_type(self):
        assert _validate_record({"level": "high"}) is False
        assert _validate_record({"level": None}) is False


class TestWriteMarker:
    def test_creates_file_and_parents(self, tmp_path):
        marker = tmp_path / "deep" / "nested" / "migration_v1.json"
        _write_marker(marker)
        payload = json.loads(marker.read_text(encoding="utf-8"))
        assert payload["version"] == 1
        assert "migrated_at" in payload


class TestMigrateFromLegacy:
    def _storage(self):
        return UnifiedAffectionStorage(":memory:")

    def test_missing_file_returns_false(self, tmp_path):
        backend = self._storage()
        try:
            assert migrate_from_legacy(backend, tmp_path / "nope.json") is False
        finally:
            backend._conn.close()

    def test_creates_backup(self, tmp_path):
        backend = self._storage()
        try:
            path = tmp_path / "relationships.json"
            path.write_text(json.dumps({"u1": {"level": 70.0}}), encoding="utf-8")
            migrate_from_legacy(backend, path)
            assert (tmp_path / "relationships.json.bak").exists()
        finally:
            backend._conn.close()

    def test_marker_makes_it_idempotent(self, tmp_path):
        backend = self._storage()
        try:
            path = tmp_path / "relationships.json"
            path.write_text(json.dumps({"u1": {"level": 70.0}}), encoding="utf-8")
            assert migrate_from_legacy(backend, path) is True
            # 改数据后再跑一次：标记已存在，必须原样跳过而不是覆盖
            path.write_text(json.dumps({"u1": {"level": 10.0}}), encoding="utf-8")
            assert migrate_from_legacy(backend, path) is True
            assert backend.get_level("u1") == 70.0
        finally:
            backend._conn.close()

    def test_empty_json_writes_marker(self, tmp_path):
        backend = self._storage()
        try:
            path = tmp_path / "relationships.json"
            path.write_text("{}", encoding="utf-8")
            assert migrate_from_legacy(backend, path) is True
            assert (tmp_path / "migration_v1.json").exists()
        finally:
            backend._conn.close()

    def test_flat_records_migrated(self, tmp_path):
        backend = self._storage()
        try:
            path = tmp_path / "relationships.json"
            path.write_text(
                json.dumps({
                    "u1__p1": {"level": 88.0, "message_count": 4, "positive_count": 2},
                    "u2": {"level": 12.0},
                }),
                encoding="utf-8",
            )
            assert migrate_from_legacy(backend, path) is True
            assert backend.get_level("u1", "p1") == 88.0
            assert backend.get_stats("u1", "p1").message_count == 4
            assert backend.get_level("u2", "default") == 12.0
        finally:
            backend._conn.close()

    def test_all_invalid_returns_false_without_marker(self, tmp_path):
        """一条都没成功就不能写标记 —— 否则用户修好数据也不会再迁移一次。"""
        backend = self._storage()
        try:
            path = tmp_path / "relationships.json"
            path.write_text(json.dumps({"u1": {"level": "high"}}), encoding="utf-8")
            assert migrate_from_legacy(backend, path) is False
            assert not (tmp_path / "migration_v1.json").exists()
        finally:
            backend._conn.close()

    def test_partial_failure_still_migrates_rest(self, tmp_path):
        backend = self._storage()
        try:
            path = tmp_path / "relationships.json"
            path.write_text(
                json.dumps({"u1": {"level": 75.0}, "u2": {"level": "bad"}}),
                encoding="utf-8",
            )
            assert migrate_from_legacy(backend, path) is True
            assert backend.get_level("u1") == 75.0
            assert (tmp_path / "migration_v1.json").exists()
        finally:
            backend._conn.close()

    def test_bad_json_returns_false(self, tmp_path):
        backend = self._storage()
        try:
            path = tmp_path / "relationships.json"
            path.write_text("{broken", encoding="utf-8")
            assert migrate_from_legacy(backend, path) is False
        finally:
            backend._conn.close()

    def test_existing_backup_is_overwritten(self, tmp_path):
        backend = self._storage()
        try:
            path = tmp_path / "relationships.json"
            (tmp_path / "relationships.json.bak").write_text("old", encoding="utf-8")
            path.write_text(json.dumps({"u1": {"level": 70.0}}), encoding="utf-8")
            assert migrate_from_legacy(backend, path) is True
            assert json.loads(
                (tmp_path / "relationships.json.bak").read_text(encoding="utf-8")
            ) == {"u1": {"level": 70.0}}
        finally:
            backend._conn.close()


class TestRollback:
    def test_restores_from_backup(self, tmp_path):
        path = tmp_path / "relationships.json"
        path.write_text("new", encoding="utf-8")
        (tmp_path / "relationships.json.bak").write_text("old", encoding="utf-8")
        assert rollback_migration(path) is True
        assert path.read_text(encoding="utf-8") == "old"

    def test_missing_backup_returns_false(self, tmp_path):
        path = tmp_path / "relationships.json"
        path.write_text("new", encoding="utf-8")
        assert rollback_migration(path) is False
        assert path.read_text(encoding="utf-8") == "new"
