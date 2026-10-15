"""亲密度常量定义 — 方向、等级与映射表"""

from __future__ import annotations

from enum import Enum, auto


class AffectionDirection(Enum):
    """亲密度变化方向"""
    STRONG_POSITIVE = auto()
    POSITIVE = auto()
    SLIGHT_POSITIVE = auto()
    NEUTRAL = auto()
    SLIGHT_NEGATIVE = auto()
    NEGATIVE = auto()
    STRONG_NEGATIVE = auto()


class AffectionLevel(Enum):
    """亲密度变化幅度等级"""
    HIGH = auto()
    MEDIUM = auto()
    LOW = auto()


# ──────────────────────────────────────────────
# 方向 × 等级 → 数值增量映射表（共 21 项）
# NEUTRAL 方向忽略等级，统一为 0.0
# ──────────────────────────────────────────────
DIRECTION_LEVEL_MAP: dict[tuple[AffectionDirection, AffectionLevel], float] = {
    (AffectionDirection.STRONG_POSITIVE, AffectionLevel.HIGH): 15.0,
    (AffectionDirection.STRONG_POSITIVE, AffectionLevel.MEDIUM): 10.0,
    (AffectionDirection.STRONG_POSITIVE, AffectionLevel.LOW): 5.0,
    (AffectionDirection.POSITIVE, AffectionLevel.HIGH): 8.0,
    (AffectionDirection.POSITIVE, AffectionLevel.MEDIUM): 5.0,
    (AffectionDirection.POSITIVE, AffectionLevel.LOW): 2.0,
    (AffectionDirection.SLIGHT_POSITIVE, AffectionLevel.HIGH): 1.0,
    (AffectionDirection.SLIGHT_POSITIVE, AffectionLevel.MEDIUM): 0.5,
    (AffectionDirection.SLIGHT_POSITIVE, AffectionLevel.LOW): 0.2,
    (AffectionDirection.NEUTRAL, AffectionLevel.HIGH): 0.0,
    (AffectionDirection.NEUTRAL, AffectionLevel.MEDIUM): 0.0,
    (AffectionDirection.NEUTRAL, AffectionLevel.LOW): 0.0,
    (AffectionDirection.SLIGHT_NEGATIVE, AffectionLevel.HIGH): -1.0,
    (AffectionDirection.SLIGHT_NEGATIVE, AffectionLevel.MEDIUM): -0.5,
    (AffectionDirection.SLIGHT_NEGATIVE, AffectionLevel.LOW): -0.2,
    (AffectionDirection.NEGATIVE, AffectionLevel.HIGH): -8.0,
    (AffectionDirection.NEGATIVE, AffectionLevel.MEDIUM): -5.0,
    (AffectionDirection.NEGATIVE, AffectionLevel.LOW): -2.0,
    (AffectionDirection.STRONG_NEGATIVE, AffectionLevel.HIGH): -15.0,
    (AffectionDirection.STRONG_NEGATIVE, AffectionLevel.MEDIUM): -10.0,
    (AffectionDirection.STRONG_NEGATIVE, AffectionLevel.LOW): -5.0,
}

# ──────────────────────────────────────────────
# 人格维度偏移映射 — 每次亲密度变化时的微调量
# ──────────────────────────────────────────────
PERSONALITY_SHIFT_MAP: dict[str, dict[str, float]] = {
    "up": {
        "trust": 0.02,
        "dependence": 0.02,
        "openness": 0.01,
        "jealousy": -0.01,
        "affection": 0.02,
    },
    "down": {
        "trust": -0.02,
        "dependence": -0.02,
        "openness": -0.01,
        "jealousy": 0.01,
        "affection": -0.02,
    },
    "no_change": {
        "trust": 0.0,
        "dependence": 0.0,
        "openness": 0.0,
        "jealousy": 0.0,
        "affection": 0.0,
    },
}

# ──────────────────────────────────────────────
# 基础奖励 / 边界常量
# ──────────────────────────────────────────────
BASE_BONUS: float = 0.02

# ──────────────────────────────────────────────
# 增量曲线：正态（钟形）随「当前亲密度」
#
# 单条消息的增量幅度 = 峰值 × 钟形(当前亲密度) × 强度权重(由档位表归一) × 随机抖动
#   钟形(x) = exp(-(x - 中心)² / (2σ²))     —— 标准正态密度形状，中段 = 1.0
#
# 效果：中段（亲密度 50 附近）变化最快，上限就是 AFFECTION_PEAK_DELTA（当前 1.0/条）；
#       越靠近 0 或 100 越慢 —— **增长与下降对称受限**（取代了原来只管正向的线性边际递减）。
# ──────────────────────────────────────────────
AFFECTION_PEAK_DELTA: float = 1.0       # 中段峰值：单条消息最大增量
AFFECTION_BELL_CENTER: float = 50.0     # 钟形中心（亲密度中段）
AFFECTION_BELL_SIGMA: float = 20.0      # 钟形宽度：越大两端衰减越慢（20 ≈ 30~70 都较快）
AFFECTION_MAX_MAP_STEP: float = 15.0    # 档位表最大绝对值，用于把档位归一成强度 0~1
AFFECTION_STRENGTH_POWER: float = 0.5   # 强度归一后的软化指数（0.5=开方，避免弱档位小到看不见）
AFFECTION_JITTER_RATIO: float = 0.10    # 随机抖动比例（0 = 完全确定）
AFFECTION_MIN_STEP: float = 0.02        # 有方向时的最小步长（保证方向不被抖动反转）

MIN_AFFECTION: int = 0
MAX_AFFECTION: int = 100

MIN_DIMENSION: float = 0.0
MAX_DIMENSION: float = 1.0
