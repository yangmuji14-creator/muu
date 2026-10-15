"""情感分析器"""

from enum import Enum
from dataclasses import dataclass


class EmotionType(str, Enum):
    """情感类型"""
    HAPPY = "happy"       # 开心
    SAD = "sad"           # 难过
    ANGRY = "angry"       # 生气
    NEUTRAL = "neutral"   # 中性
    EXCITED = "excited"   # 兴奋
    LONELY = "lonely"     # 孤独
    ANXIOUS = "anxious"   # 焦虑
    LOVE = "love"         # 爱意/亲密


@dataclass
class EmotionResult:
    """情感分析结果"""
    emotion: EmotionType
    intensity: float  # 0.0 - 1.0 强度
    keywords: list[str]  # 触发的关键词


# 情感值 -> 中文标签。
# 用于把内部枚举（happy / neutral …）翻译成人话，避免 "他好像neutral的样子" 这类英文泄漏。
# 覆盖 EmotionType 的 8 个值 + LLM 分析器可能给出的常见情绪词。
EMOTION_LABELS: dict[str, str] = {
    # EmotionType
    "happy": "开心",
    "sad": "难过",
    "angry": "生气",
    "neutral": "平静",
    "excited": "兴奋",
    "lonely": "孤单",
    "anxious": "焦虑",
    "love": "喜欢",
    # LLM 分析器常见输出
    "calm": "平静",
    "tired": "疲惫",
    "depressed": "低落",
    "frustrated": "烦躁",
    "grateful": "感激",
    "content": "满足",
    "ecstatic": "特别高兴",
    "surprised": "意外",
    "confused": "困惑",
    "bored": "无聊",
    "proud": "自豪",
    "relieved": "松了一口气",
    "hopeful": "有盼头",
}


def emotion_label(value) -> str:
    """把情感值翻成中文；翻不出来返回空串（调用方应据此跳过该句）。"""
    raw = str(getattr(value, "value", value) or "").strip()
    if not raw:
        return ""
    return EMOTION_LABELS.get(raw.lower(), "")


# 情感关键词表
EMOTION_KEYWORDS: dict[EmotionType, list[str]] = {
    EmotionType.HAPPY: [
        "开心", "高兴", "快乐", "哈哈", "嘻嘻", "太好了", "棒", "赞",
        "幸福", "满足", "喜欢", "爱", "好看", "好玩",
        "🎉", "😊", "😄", "😁", "🥰", "❤️", "💕",
    ],
    EmotionType.SAD: [
        "难过", "伤心", "哭", "不开心", "失望", "寂寞", "孤独",
        "累", "烦", "无聊", "唉", "哎", "心痛", "想哭",
        "😢", "😭", "😞", "💔", "😔",
    ],
    EmotionType.ANGRY: [
        "生气", "愤怒", "讨厌", "烦死了", "气死", "可恶", "混蛋",
        "恶心", "受不了", "崩溃",
        "😡", "🤬", "💢",
    ],
    EmotionType.EXCITED: [
        "太棒了", "厉害", "牛", "绝了", "amazing", "wow", "天哪",
        "不敢相信", "震惊", "惊喜", "超", "超级",
        "🤩", "😱", "🎉", "✨",
    ],
    EmotionType.LONELY: [
        "一个人", "孤单", "寂寞", "没人", "陪我", "想你", "想念",
        "好久没", "很久没", "无聊",
        "🥺", "😿",
    ],
    EmotionType.ANXIOUS: [
        "担心", "焦虑", "紧张", "害怕", "恐惧", "不安", "慌",
        "怎么办", "完了", "糟糕", "考试", "面试",
        "😰", "😨", "😟",
    ],
    EmotionType.LOVE: [
        "爱你", "喜欢你", "想你", "亲爱的", "宝贝", "抱抱", "亲亲",
        "在一起", "永远", "一辈子", "最喜欢",
        "💕", "💖", "💗", "🥰", "😘", "💋",
    ],
}

# 情感强度修饰词
INTENSITY_BOOSTERS = ["非常", "特别", "超级", "太", "好", "真的", "very", "so", "!!!"]
INTENSITY_REDUCERS = ["有点", "稍微", "一点点", "可能", "也许"]

# 否定词（出现在关键词前面会反转情感）
# 注意："非" 单独不是否定词（"非常"="very"），只保留明确的否定词
NEGATION_WORDS = ["不", "没", "没有", "别", "莫", "未", "无", "不是", "不喜欢", "不想", "不爱"]


class EmotionAnalyzer:
    """情感分析器

    基于关键词匹配的情感分析，轻量级、无外部依赖。
    可以后续升级为 LLM 辅助分析。
    """

    @staticmethod
    def _is_negated(text: str, keyword: str) -> bool:
        """检查关键词是否被否定词修饰

        Args:
            text: 完整文本
            keyword: 要检查的关键词

        Returns:
            True 如果关键词前面有否定词
        """
        idx = text.find(keyword)
        if idx <= 0:
            return False
        # 检查关键词前面 3 个字符内是否有否定词
        prefix = text[max(0, idx - 3):idx]
        return any(neg in prefix for neg in NEGATION_WORDS)

    @staticmethod
    def analyze(text: str) -> EmotionResult:
        """分析文本情感

        Args:
            text: 要分析的文本

        Returns:
            EmotionResult 包含情感类型、强度和触发词
        """
        if not text:
            return EmotionResult(EmotionType.NEUTRAL, 0.0, [])

        # 统计各情感的匹配分数
        scores: dict[EmotionType, float] = {}
        matched_keywords: dict[EmotionType, list[str]] = {}

        for emotion, keywords in EMOTION_KEYWORDS.items():
            score = 0.0
            matched = []
            for kw in keywords:
                if kw in text:
                    # 否定词检测：被否定的关键词不计入正面/负面情感
                    if EmotionAnalyzer._is_negated(text, kw):
                        continue
                    score += 1.0
                    matched.append(kw)
            if score > 0:
                scores[emotion] = score
                matched_keywords[emotion] = matched

        if not scores:
            return EmotionResult(EmotionType.NEUTRAL, 0.0, [])

        # 找到最高分的情感
        best_emotion = max(scores, key=scores.get)  # type: ignore
        raw_score = scores[best_emotion]

        # 计算强度（归一化到 0-1）
        intensity = min(raw_score / 3.0, 1.0)

        # 强度修饰
        for booster in INTENSITY_BOOSTERS:
            if booster in text:
                intensity = min(intensity * 1.3, 1.0)
                break

        for reducer in INTENSITY_REDUCERS:
            if reducer in text:
                intensity = max(intensity * 0.7, 0.1)
                break

        return EmotionResult(
            emotion=best_emotion,
            intensity=round(intensity, 2),
            keywords=matched_keywords.get(best_emotion, []),
        )
