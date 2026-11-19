"""动态记忆闸门 — 根据情绪/上下文调整相似度阈值

不再硬编码 MIN_SEMANTIC_SIMILARITY = 0.35，而是动态计算：
  - 用户新手期：阈值宽松（更多背景噪声，帮助理解对话模式）
  - 长期用户：阈值严格（只要最相关的记忆）
  - 焦虑/低落情绪：加载更多相关记忆（寻求安慰）
  - 放松/欢快情绪：阈值宽松（容纳更多话题变化）
"""

from dataclasses import dataclass
from typing import Optional

from loguru import logger

# 生产校准值的兜底；正常情况下 __init__ 会从 MemoryManager 读取，
# 避免这里再抄一份常量导致重新校准时两套数字漂移。
_FALLBACK_ABSOLUTE = 0.35
_FALLBACK_RELATIVE = 0.9


@dataclass
class DynamicThreshold:
    """动态阈值计算结果"""
    absolute_min: float  # 绝对下限
    relative_ratio: float  # 相对比率（与最佳候选的差距容限）
    reason: str  # 调整原因（日志用）


class DynamicGateSystem:
    """动态闸门系统"""

    def __init__(
        self,
        base_absolute: float | None = None,
        base_relative: float | None = None,
    ):
        """基础阈值默认取 MemoryManager 的校准常量（可显式覆盖）。"""
        if base_absolute is None or base_relative is None:
            calibrated_abs, calibrated_rel = self._calibrated_bases()
            if base_absolute is None:
                base_absolute = calibrated_abs
            if base_relative is None:
                base_relative = calibrated_rel
        self._base_absolute = base_absolute
        self._base_relative = base_relative
        self._recent_emotions: list[str] = []

    @staticmethod
    def _calibrated_bases() -> tuple[float, float]:
        try:
            from .manager import MemoryManager

            return (
                float(MemoryManager.MIN_SEMANTIC_SIMILARITY),
                float(MemoryManager.RELATIVE_SIMILARITY_RATIO),
            )
        except Exception:  # pragma: no cover - 极端导入失败时兜底
            return _FALLBACK_ABSOLUTE, _FALLBACK_RELATIVE

    def compute_threshold(
        self,
        user_interaction_count: int,
        current_emotion: Optional[str] = None,
        conversation_topic_consistency: float = 0.5,
    ) -> DynamicThreshold:
        """
        根据用户状态计算动态阈值

        Args:
            user_interaction_count: 用户与 AI 的交互轮次
            current_emotion: 当前情绪（"happy", "anxious", "sad", "calm", None）
            conversation_topic_consistency: 当前对话与历史话题的相关度（0-1）

        Returns:
            DynamicThreshold 对象
        """

        # 基础阈值来自 MemoryManager 的校准常量
        base_absolute = self._base_absolute
        base_relative = self._base_relative

        # 1. 新手期调整（前 20 次对话）
        if user_interaction_count < 20:
            base_absolute *= 0.85  # 宽松 15%
            reason = f"新手期 ({user_interaction_count}/20)"
        # 2. 长期用户调整（>100 次对话）
        elif user_interaction_count > 100:
            base_absolute *= 1.15  # 严格 15%
            reason = f"长期用户 ({user_interaction_count})"
        else:
            reason = f"常规用户 ({user_interaction_count})"

        # 3. 情绪驱动调整
        if current_emotion == "anxious" or current_emotion == "sad":
            # 焦虑/低落：加载更多相关背景
            base_absolute *= 0.8  # 阈值下降 20%
            base_relative *= 0.95  # 相对宽松
            reason += f" | 情绪:{current_emotion}(宽松)"
        elif current_emotion == "happy" or current_emotion == "excited":
            # 欢快：可以接受更多话题变化
            base_absolute *= 0.9
            base_relative *= 0.92
            reason += f" | 情绪:{current_emotion}(轻松)"
        elif current_emotion == "calm":
            # 平静：保持中立
            reason += " | 情绪:calm"

        # 4. 对话连贯性调整
        if conversation_topic_consistency > 0.8:
            # 话题高度一致：真正收紧 —— 绝对下限抬 8%，相对比率抬 4%
            # （此前 *= 1.0 是空操作，reason 却写「严格」）
            base_absolute *= 1.08
            base_relative *= 1.04
            reason += " | 话题连贯(严格)"
        elif conversation_topic_consistency < 0.4:
            # 话题差异大：宽松过滤（容纳更多跳跃）
            base_absolute *= 0.85
            base_relative *= 0.88
            reason += " | 话题多样(宽松)"

        # 阈值上下限保护
        absolute_min = max(0.2, min(0.6, base_absolute))
        relative_ratio = max(0.75, min(0.98, base_relative))

        logger.debug(f"Dynamic threshold: abs={absolute_min:.3f}, rel={relative_ratio:.3f} [{reason}]")

        return DynamicThreshold(
            absolute_min=absolute_min,
            relative_ratio=relative_ratio,
            reason=reason,
        )

    def update_emotion(self, emotion: str):
        """记录最近情绪（用于趋势分析）"""
        self._recent_emotions.append(emotion)
        if len(self._recent_emotions) > 10:
            self._recent_emotions.pop(0)

    def get_emotion_trend(self) -> Optional[str]:
        """推断最近情绪趋势"""
        if not self._recent_emotions:
            return None
        # 简单逻辑：多数情绪为趋势
        from collections import Counter
        counts = Counter(self._recent_emotions)
        trend, _ = counts.most_common(1)[0]
        return trend
