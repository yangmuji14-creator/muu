"""亲密度映射器 — 方向/等级 → 数值增量 & 人格偏移映射"""

from __future__ import annotations

import math
import random

from core.social.affection.constants import (
    AFFECTION_BELL_CENTER,
    AFFECTION_BELL_SIGMA,
    AFFECTION_JITTER_RATIO,
    AFFECTION_MAX_MAP_STEP,
    AFFECTION_MIN_STEP,
    AFFECTION_PEAK_DELTA,
    AFFECTION_STRENGTH_POWER,
    AffectionDirection,
    AffectionLevel,
    DIRECTION_LEVEL_MAP,
    PERSONALITY_SHIFT_MAP,
)


class AffectionMapper:
    """纯函数映射器：将 (方向, 等级) 字符串/枚举对转换为数值增量。

    所有方法均为静态方法（无状态），被 UnifiedAffectionStorage.update()
    用于将 LLM 输出的方向/等级文本转换为可应用的数值修正量。
    """

    # ── 核心映射（测试入口） ──────────────────────────────

    @staticmethod
    def get_delta(
        direction: str | AffectionDirection | None,
        level: str | AffectionLevel | None,
    ) -> float:
        """将方向 + 等级映射为数值增量（不含 BASE_BONUS）。

        参数:
            direction: 方向字符串、枚举或 None
            level: 等级字符串、枚举或 None

        返回:
            映射后的浮点数值增量
        """
        dir_enum = AffectionMapper._parse_direction(direction)
        lvl_enum = AffectionMapper._parse_level(level)
        return DIRECTION_LEVEL_MAP[(dir_enum, lvl_enum)]

    # ── 规范映射方法 ──────────────────────────────────────

    @staticmethod
    def map(
        direction: str | AffectionDirection | None,
        level: str | AffectionLevel | None,
    ) -> float:
        """同 get_delta — 返回 BASE_BONUS 之前的原始增量。"""
        return AffectionMapper.get_delta(direction, level)

    @staticmethod
    def bell_factor(current_level: float | None) -> float:
        """钟形系数（标准正态密度形状）：中心 = 1.0，越远离中心越小。

        current_level 为 None 时返回 1.0（调用方未提供亲密度时不衰减）。
        """
        if current_level is None:
            return 1.0
        d = float(current_level) - AFFECTION_BELL_CENTER
        return math.exp(-(d * d) / (2.0 * AFFECTION_BELL_SIGMA ** 2))

    @staticmethod
    def sample_delta(
        direction: str | AffectionDirection | None,
        level: str | AffectionLevel | None,
        current_level: float | None = None,
    ) -> float:
        """按「钟形曲线 × 强度权重」计算本次亲密度增量。

        为什么不在 get_delta 里做：get_delta 是纯函数（测试/展示依赖固定档位值）。
        这里才是**实际生效**的幅度：

            幅度 = 峰值 × 钟形(当前亲密度) × 强度权重 × 随机抖动
            强度权重 = min(1, |档位值| / 档位最大值) ** 软化指数

        特点：
          - 中段（亲密度 50 附近）幅度最大，上限 AFFECTION_PEAK_DELTA（当前 1.0，见 constants.py）；
          - 越靠近 0 / 100，钟形系数越小 → **增长与下降对称限速**；
          - 方向由档位表符号决定，**恒定不反转**（有 MIN_STEP 保底）；
          - neutral（档位值 0）直接返回 0，不引入噪声。
        """
        base = AffectionMapper.get_delta(direction, level)
        if base == 0.0:
            return 0.0

        sign = 1.0 if base > 0 else -1.0
        strength = min(1.0, abs(base) / AFFECTION_MAX_MAP_STEP) ** AFFECTION_STRENGTH_POWER
        bell = AffectionMapper.bell_factor(current_level)

        magnitude = AFFECTION_PEAK_DELTA * strength * bell
        if AFFECTION_JITTER_RATIO > 0:
            magnitude *= max(0.5, random.gauss(1.0, AFFECTION_JITTER_RATIO))
        magnitude = min(magnitude, AFFECTION_PEAK_DELTA)
        return sign * max(magnitude, AFFECTION_MIN_STEP)

    @staticmethod
    def map_personality_shift(shift: dict[str, str]) -> dict[str, float]:
        """将人格偏移关键词映射为各维度的数值调整量。

        示例:
            {"trust": "up", "dependence": "down"}
            → {"trust": 0.02, "dependence": -0.02}

        参数:
            shift: {维度名: 偏移方向} 字典，如 {"trust": "up"}

        返回:
            {维度名: 增量值} 字典，未知偏移方向 → no_change，
            未知维度名 → 跳过
        """
        result: dict[str, float] = {}
        for dimension, shift_value in shift.items():
            # 未知 shift_value → 默认 no_change
            shift_entry = PERSONALITY_SHIFT_MAP.get(
                shift_value, PERSONALITY_SHIFT_MAP["no_change"]
            )
            # 只包含 PERSONALITY_SHIFT_MAP 中明确存在的维度
            if dimension in shift_entry:
                result[dimension] = shift_entry[dimension]
        return result

    # ── 内部解析辅助 ──────────────────────────────────────

    @staticmethod
    def _parse_direction(value: str | AffectionDirection | None) -> AffectionDirection:
        """将字符串或 None 解析为 AffectionDirection 枚举。

        - None → NEUTRAL
        - 已为枚举 → 直接返回
        - 大小写不敏感字符串 → 对应枚举
        - 未知字符串 → NEUTRAL
        """
        if value is None:
            return AffectionDirection.NEUTRAL
        if isinstance(value, AffectionDirection):
            return value
        try:
            return AffectionDirection[value.upper().strip()]
        except (KeyError, AttributeError):
            return AffectionDirection.NEUTRAL

    @staticmethod
    def _parse_level(value: str | AffectionLevel | None) -> AffectionLevel:
        """将字符串或 None 解析为 AffectionLevel 枚举。

        - None → LOW
        - 已为枚举 → 直接返回
        - 大小写不敏感字符串 → 对应枚举
        - 未知字符串 → LOW
        """
        if value is None:
            return AffectionLevel.LOW
        if isinstance(value, AffectionLevel):
            return value
        try:
            return AffectionLevel[value.upper().strip()]
        except (KeyError, AttributeError):
            return AffectionLevel.LOW
