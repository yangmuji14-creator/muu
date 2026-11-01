"""VitalityMonitor — 回复自锁监控（优化方案第三部分）。

「她开始重复自己」是所有退化里最早能被仪器捕捉的一个：模型进入模板腔时，
最近回复的嵌入相似度会先于人的察觉爬过 0.9。等用户自己说「她最近好假」，
数据里早就有证据了。

机制：每当某个身份的 assistant 消息新增 ``CHECK_EVERY_NEW_MESSAGES`` 条，
取最近 ``WINDOW`` 条做两两余弦，平均分超过 ``LOCK_THRESHOLD`` 就告警。

刻意的克制：

- **只监控不自动干预**。发现自锁后打 warning 并把结果返回给调用方，
  「意外事件」的注入留给后续批次——自动改写回复的风险远大于收益。
- **节流按新增条数而不是时间**：没人聊天时反复算旧消息没有意义。
- 平均分而不是最高分：最高分对「同一句口头禅」过于敏感，平均分才
  反映「整段对话是不是在原地打转」。
"""

from __future__ import annotations

import math
from datetime import datetime

from loguru import logger


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class VitalityMonitor:
    """按身份监控最近回复的自锁程度。"""

    CHECK_EVERY_NEW_MESSAGES = 5
    WINDOW = 20
    LOCK_THRESHOLD = 0.92
    # 告警去抖：同一身份两次告警至少隔这么多新增消息
    ALERT_COOLDOWN_MESSAGES = 10

    def __init__(self, memory_manager, chat_history) -> None:
        self._memory_manager = memory_manager
        self._chat_history = chat_history
        self._last_checked: dict[str, int] = {}
        self._last_alert_count: dict[str, int] = {}

    def check(self, user_id: str) -> dict | None:
        """检查该身份最近回复是否自锁。返回结果 dict；未到检查点返回 None。"""
        try:
            messages = self._chat_history.get_messages(user_id)
        except Exception as e:
            logger.debug(f"VitalityMonitor: history lookup failed: {e}")
            return None

        assistant = [
            str(m.get("content", ""))
            for m in messages
            if m.get("role") == "assistant" and m.get("content")
        ]
        count = len(assistant)
        last = self._last_checked.get(user_id, 0)
        if count - last < self.CHECK_EVERY_NEW_MESSAGES:
            return None
        self._last_checked[user_id] = count

        if count - self._last_alert_count.get(user_id, 0) < self.ALERT_COOLDOWN_MESSAGES \
                and user_id in self._last_alert_count:
            return None

        recent = [c for c in assistant[-self.WINDOW:] if len(c) >= 4]
        if len(recent) < 4:
            return None

        embedder = getattr(self._memory_manager, "_embedder", None)
        if embedder is None or not getattr(embedder, "available", False):
            return None
        try:
            vectors = embedder.embed_batch(recent)
        except Exception as e:
            logger.debug(f"VitalityMonitor: embed failed: {e}")
            return None
        if not vectors or len(vectors) != len(recent):
            return None

        sims = [
            _cosine(vectors[i], vectors[j])
            for i in range(len(vectors))
            for j in range(i + 1, len(vectors))
        ]
        avg = sum(sims) / len(sims)
        result = {
            "user_id": user_id,
            "avg_similarity": round(avg, 4),
            "max_similarity": round(max(sims), 4),
            "window": len(recent),
            "locked": avg > self.LOCK_THRESHOLD,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }
        if result["locked"]:
            self._last_alert_count[user_id] = count
            logger.warning(
                f"VitalityMonitor: 自锁嫌疑 [{user_id}] avg={result['avg_similarity']} "
                f"max={result['max_similarity']}（阈值 {self.LOCK_THRESHOLD}）。"
                f"这是「她开始重复自己」的仪器信号——考虑注入意外事件或换话题源"
            )
        return result
