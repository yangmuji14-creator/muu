"""InternalMoodSource：情绪内生源的量级与边界。

设计红线（全部来自优化方案改 B 的约束）：
- 纯代码零模型调用
- 内生源是背景 hum，不是情节：单次位移必须比一次用户消息的影响
  小一个数量级
- 节流后 10 分钟一次；节流窗口内重复 tick 必须无副作用
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.emotion.internal_source import (
    LONELY_AFTER_HOURS,
    InternalMoodSource,
)


class FakeMoodEngine:
    """记录 save 调用；get_mood 返回同一个可变 state（模拟引擎缓存语义）。"""

    def __init__(self, valence=0.0, arousal=0.0):
        self.state = {
            "mood": None, "valence": valence, "arousal": arousal,
            "energy": 0.5, "intensity": 1.0,
            "updated_at": datetime.now().isoformat(),
            "last_decay_at": datetime.now().isoformat(),
            "expires_at": None,
        }
        from core.emotion.mood import MoodState
        self.state_obj = MoodState(**self.state)
        self.saved = 0

    def get_mood(self, user_id):
        return self.state_obj

    def _save(self, user_id, state):
        self.saved += 1

    @staticmethod
    def _find_nearest_mood(valence, arousal):
        from core.emotion.mood import MoodType, MOOD_COORDS
        nearest, best = MoodType.NEUTRAL, float("inf")
        for mood, (mv, ma) in MOOD_COORDS.items():
            d = ((valence - mv) ** 2 + (arousal - ma) ** 2) ** 0.5
            if d < best:
                nearest, best = mood, d
        return nearest, best


class FakeOpenLoop:
    def __init__(self, pending=0):
        self._pending = [{"id": f"l{i}"} for i in range(pending)]

    def get_pending(self, user_id):
        return list(self._pending)


class FakeHistory:
    def __init__(self, hours_idle=None, empty=False):
        self.empty = empty
        self._hours = hours_idle

    def get_messages(self, user_id):
        if self.empty:
            return []
        stamp = (datetime.now() - timedelta(hours=self._hours or 0)).isoformat()
        return [{"role": "user", "content": "hi", "timestamp": stamp}]


def _source(mood_engine, **kw):
    return InternalMoodSource(
        mood_engine=mood_engine,
        open_loop=kw.get("open_loop"),
        chat_history=kw.get("chat_history"),
    )


class TestOpenLoopPressure:
    def test_pending_items_push_valence_down(self) -> None:
        engine = FakeMoodEngine()
        src = _source(engine, open_loop=FakeOpenLoop(pending=3))
        src.tick("u1")
        assert engine.state_obj.valence == pytest.approx(-0.03)

    def test_pressure_is_capped(self) -> None:
        engine = FakeMoodEngine()
        src = _source(engine, open_loop=FakeOpenLoop(pending=50))
        src.tick("u1")
        assert engine.state_obj.valence == pytest.approx(-0.04)  # 4 条封顶

    def test_resolved_pressure_disappears(self) -> None:
        engine = FakeMoodEngine()
        loop = FakeOpenLoop(pending=2)
        src = _source(engine, open_loop=loop)
        src.tick("u1")
        v_with = engine.state_obj.valence
        loop._pending = []
        src._last_tick.clear()  # 跳过节流
        src.tick("u1")
        assert engine.state_obj.valence == pytest.approx(v_with)  # 无 pending 不再下压


class TestLonelyShift:
    def test_long_idle_pushes_lonely_direction(self) -> None:
        engine = FakeMoodEngine()
        src = _source(engine, chat_history=FakeHistory(hours_idle=LONELY_AFTER_HOURS + 2))
        src.tick("u1")
        assert engine.state_obj.valence < 0
        assert engine.state_obj.arousal > 0  # 想找人，不是单纯难过

    def test_recent_talk_does_not(self) -> None:
        engine = FakeMoodEngine()
        src = _source(engine, chat_history=FakeHistory(hours_idle=1))
        src.tick("u1")
        assert engine.state_obj.valence == 0.0
        assert engine.saved == 0  # 无偏移不落库

    def test_never_talked_is_not_lonely(self) -> None:
        """从没聊过的不算孤独——新会话不该凭空掉心情。"""
        engine = FakeMoodEngine()
        src = _source(engine, chat_history=FakeHistory(empty=True))
        src.tick("u1")
        assert engine.state_obj.valence == 0.0


class TestMagnitude:
    def test_background_hum_is_an_order_smaller_than_user_message(self) -> None:
        """一次用户消息的位移 = intensity(0.5) × 0.4 = 0.2；
        内生源单次最多 0.04，必须小一个数量级——用户每句话都比她瞎想更有分量。"""
        engine = FakeMoodEngine()
        src = _source(engine, open_loop=FakeOpenLoop(pending=4),
                      chat_history=FakeHistory(hours_idle=48))
        src.tick("u1")
        # 双源叠加：0.04 + 0.01 = 0.05，仍远小于 0.2
        assert engine.state_obj.valence == pytest.approx(-0.05)
        assert abs(engine.state_obj.valence) < 0.2


class TestThrottle:
    def test_rerun_within_window_is_noop(self) -> None:
        engine = FakeMoodEngine()
        src = _source(engine, open_loop=FakeOpenLoop(pending=4))
        src.tick("u1")
        v1 = engine.state_obj.valence
        saved1 = engine.saved
        src.tick("u1")  # 10 分钟窗口内
        assert engine.state_obj.valence == pytest.approx(v1)
        assert engine.saved == saved1

    def test_zero_shift_does_not_persist(self) -> None:
        engine = FakeMoodEngine()
        src = _source(engine)  # 两个源都无输入
        src.tick("u1")
        assert engine.saved == 0


class TestDependencies:
    def test_missing_deps_are_safe(self) -> None:
        engine = FakeMoodEngine()
        src = _source(engine)  # 无 open_loop / 无 history
        src.tick("u1")
        assert engine.state_obj.valence == 0.0

    def test_open_loop_error_is_swallowed(self) -> None:
        class Broken:
            def get_pending(self, user_id):
                raise RuntimeError("boom")

        engine = FakeMoodEngine()
        src = _source(engine, open_loop=Broken())
        src.tick("u1")  # 不抛出即通过
        assert engine.state_obj.valence == 0.0
