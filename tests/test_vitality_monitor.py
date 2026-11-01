"""VitalityMonitor：自锁监控的判定与节流。

全部用字典驱动的确定性伪嵌入，不碰真实模型、不依赖 hash 偶然性。
"""

from __future__ import annotations

from core.runtime.vitality_monitor import VitalityMonitor

SIMILAR = ["今天天气挺好的呀", "今天天气真不错呢", "今天天气看着很好哦",
           "今天天气感觉蛮好的", "今天天气挺好的呀"]

DIFFERENT = [
    "面试准备得怎么样了？我有点担心你昨晚又熬夜。",
    "刚看到一只橘猫趴在窗台上，想起你说过的那只。",
    "我在试新的洗发水，味道像柚子，有点好闻。",
    "你上次说想吃的那家面馆，周末要不要去？",
    "降温了，围巾我记得在你抽屉第二层。",
]

_LOCK_VEC = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3]


def _one_hot(index: int, dim: int = 8) -> list[float]:
    vec = [0.0] * dim
    vec[index % dim] = 1.0
    return vec


class FakeEmbedder:
    """字典驱动的确定性伪嵌入。"""

    available = True

    def __init__(self, vectors: dict[str, list[float]]):
        self._vectors = vectors

    def embed_batch(self, texts):
        out = []
        for t in texts:
            out.append(list(self._vectors[t]) if t in self._vectors else [0.0] * 8)
        return out


class FakeMemoryManager:
    def __init__(self, embedder):
        self._embedder = embedder


class FakeHistory:
    def __init__(self, contents: list[str]):
        self._contents = contents

    def get_messages(self, user_id):
        return [
            {"role": "assistant", "content": c, "timestamp": "2026-01-01T00:00:00"}
            for c in self._contents
        ]


def _monitor(contents: list[str]) -> VitalityMonitor:
    vectors = (
        {c: _LOCK_VEC for c in SIMILAR} if contents is SIMILAR
        else {c: _one_hot(i) for i, c in enumerate(DIFFERENT)}
    )
    return VitalityMonitor(
        memory_manager=FakeMemoryManager(FakeEmbedder(vectors)),
        chat_history=FakeHistory(contents),
    )


class TestLockDetection:
    def test_locked_replies_alert(self) -> None:
        """五句共享同一向量 → 两两余弦 1.0，必触发。"""
        result = _monitor(SIMILAR).check("u1")
        assert result is not None
        assert result["locked"] is True
        assert result["avg_similarity"] > 0.92

    def test_varied_replies_do_not_alert(self) -> None:
        """正交向量两两余弦 0 → 不锁。"""
        result = _monitor(DIFFERENT).check("u1")
        assert result is not None
        assert result["locked"] is False


class TestThrottle:
    def test_no_new_messages_no_recheck(self) -> None:
        monitor = _monitor(SIMILAR)
        monitor.check("u1")
        # 新增 0 条，未过 CHECK_EVERY_NEW_MESSAGES → 不重复检查
        assert monitor.check("u1") is None

    def test_alert_has_cooldown(self) -> None:
        monitor = _monitor(SIMILAR)
        monitor.check("u1")
        monitor._last_checked["u1"] = 0  # 强制重查
        # 冷却期内：不重复告警
        assert monitor.check("u1") is None


class TestDegradation:
    def test_no_embedder_is_silent(self) -> None:
        monitor = VitalityMonitor(
            memory_manager=FakeMemoryManager(None),
            chat_history=FakeHistory(SIMILAR),
        )
        assert monitor.check("u1") is None

    def test_too_few_replies_is_silent(self) -> None:
        monitor = _monitor(["嗯", "好"])
        assert monitor.check("u1") is None

    def test_history_error_is_swallowed(self) -> None:
        class Broken:
            def get_messages(self, user_id):
                raise RuntimeError("boom")

        monitor = VitalityMonitor(
            memory_manager=FakeMemoryManager(FakeEmbedder({})),
            chat_history=Broken(),
        )
        assert monitor.check("u1") is None
