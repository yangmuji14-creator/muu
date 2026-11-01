"""InternalMoodSource — 情绪内生源：没有用户输入时，她也会变化。

为什么需要这一层：

MoodEngine 的既有机制只有「衰减」——valence/arousal 向原点回归、energy
按时段调整。衰减永远只会把她拉向 neutral，**永远不会自发产生情绪**。
于是她的全部情绪都来自对用户消息的反应：你不说话，她的情绪曲线就是
一条水平线。这是「14 个子系统全部关于用户」这个结构性问题在情绪层的
具体形态。

本模块补两个不依赖用户输入的源，全部**纯代码、零模型调用**：

1. **未闭合话题的压力**（"越想越重"）：她知道你下周要面试、知道答应过
   你的事还没做——open_loop 里每条 pending 事件都会给 valence 一个轻微
   的向下分量。事情越多越沉，做完（resolved）自然消失。
2. **孤独感**（时间跨度）：超过 ``LONELY_AFTER_HOURS`` 没有任何互动，
   valence 缓慢下偏、arousal 缓慢上偏——不是"难过"，是"想找人说两句"
   的那点不安。一夜没聊 ≈ 0.3 的偏移，足够把坐标从原点推进 lonely
   邻域，又不至于让她一觉醒来情绪崩溃。

关键约束（继承自优化方案改 B 的设计）：

- **量级必须小**：内生源是背景 hum，不是情节。单次 tick 的最大位移
  （0.04）比一次用户消息的最小影响（influence 0.4 × intensity）小一个
  数量级——用户的每一句话都应当比"她自己想东想西"更有分量。
- **不做 expires_at 处理**：内生源的偏移是小向量，不该重置情绪的
  自然到期节奏。
- **tick 幂等可重入**：调用方（ProactiveRunner）每 2 分钟跑一轮，
  这里自带 ``MIN_TICK_INTERVAL`` 节流，实际状态更新约 10 分钟一次。
"""

from __future__ import annotations

import threading
from datetime import datetime

from loguru import logger

from core.emotion.mood import MoodState

# 节流：内生源实际更新间隔。调用方可以更频繁地 tick。
MIN_TICK_INTERVAL_MINUTES = 10

# 源 1：每条未闭合事件每次 tick 的 valence 下压，封顶 4 条
OPEN_LOOP_PRESSURE_PER_ITEM = 0.01
OPEN_LOOP_PRESSURE_MAX_ITEMS = 4

# 源 2：超过该小时数没有任何互动才开始积累孤独感
LONELY_AFTER_HOURS = 6.0
LONELY_VALENCE_PER_TICK = 0.01
LONELY_AROUSAL_PER_TICK = 0.008


def clamp01(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class InternalMoodSource:
    """按 user_id 的情绪内生源。线程安全（ProactiveRunner 在事件循环里串行调用）。"""

    def __init__(
        self,
        mood_engine,
        open_loop=None,
        chat_history=None,
    ) -> None:
        self._mood_engine = mood_engine
        self._open_loop = open_loop
        self._chat_history = chat_history
        self._last_tick: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def tick(self, user_id: str) -> MoodState:
        """给这个身份的状态施加一次内生源偏移（自带节流，可直接高频调用）。"""
        now = datetime.now()
        with self._lock:
            last = self._last_tick.get(user_id)
            if last is not None:
                elapsed = (now - last).total_seconds() / 60.0
                if elapsed < MIN_TICK_INTERVAL_MINUTES:
                    return self._mood_engine.get_mood(user_id)
            self._last_tick[user_id] = now

        mood = self._mood_engine.get_mood(user_id)
        before = (round(mood.valence, 3), round(mood.arousal, 3))

        # 源 1：未闭合话题——"越想越重"
        pressure = self._open_loop_pressure(user_id)
        if pressure > 0:
            mood.valence = clamp01(mood.valence - pressure, -1.0, 1.0)

        # 源 2：孤独感——长时间没有互动
        lonely = self._lonely_shift(user_id)
        if lonely:
            mood.valence = clamp01(mood.valence - LONELY_VALENCE_PER_TICK, -1.0, 1.0)
            mood.arousal = clamp01(mood.arousal + LONELY_AROUSAL_PER_TICK, 0.0, 1.0)

        if (round(mood.valence, 3), round(mood.arousal, 3)) == before:
            return mood  # 无偏移就不落库，避免无谓写放大

        # 偏移后重判最近情绪（不改 expires_at：这是背景 hum，不是新刺激）
        nearest, _dist = self._mood_engine._find_nearest_mood(mood.valence, mood.arousal)
        mood.mood = nearest
        self._mood_engine._save(user_id, mood)
        logger.debug(
            f"InternalMoodSource[{user_id}]: {before} -> "
            f"({mood.valence:.3f}, {mood.arousal:.3f}) mood={nearest.value}"
        )
        return mood

    # ── 源实现 ──

    def _open_loop_pressure(self, user_id: str) -> float:
        if self._open_loop is None:
            return 0.0
        try:
            pending = self._open_loop.get_pending(user_id)
        except Exception as e:
            logger.debug(f"InternalMoodSource: open_loop lookup failed: {e}")
            return 0.0
        items = min(len(pending), OPEN_LOOP_PRESSURE_MAX_ITEMS)
        return items * OPEN_LOOP_PRESSURE_PER_ITEM

    def _lonely_shift(self, user_id: str) -> bool:
        if self._chat_history is None:
            return False
        try:
            messages = self._chat_history.get_messages(user_id)
        except Exception as e:
            logger.debug(f"InternalMoodSource: history lookup failed: {e}")
            return False
        if not messages:
            return False  # 从没聊过的不算"孤独"，交给亲密度门槛去挡
        stamp = messages[-1].get("timestamp") or ""
        try:
            last = datetime.fromisoformat(stamp)
        except (TypeError, ValueError):
            return False
        idle_hours = (datetime.now() - last).total_seconds() / 3600.0
        return idle_hours >= LONELY_AFTER_HOURS
