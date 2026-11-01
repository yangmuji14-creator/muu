"""LLM 情感分析器（升级版）

升级为默认分析器：
- 对所有消息用 LLM 分析（不再是 fallback）
- 支持上下文感知（带最近对话历史）
- 支持情感轨迹追踪
- 关键词分析作为快速 fallback（LLM 不可用时）
- 输出丰富的情感理解、亲密度影响、人格偏移、回复指导

策略：关键词分析快速通过 + LLM 精确分析。
"""

import json
import re
from collections import deque
from loguru import logger

from core.utils import parse_json_response
from .analyzer import EmotionAnalyzer, EmotionType, EmotionResult
from ..llm.base import BaseLLM
from ..social.affection.mapper import AffectionMapper
from ..social.affection.constants import AffectionDirection, AffectionLevel


# ── 丰富输出解析 ────────────────────────────────────────────

def parse_enriched_output(json_str: str) -> dict:
    """解析 LLM 返回的丰富情感分析 JSON。

    处理新旧两种格式：
    - 新格式：emotion_understanding, affection_impact, personality_shift, response_guidance
    - 旧格式：emotion, intensity, reason → 转换为带 _old_* 字段的向前兼容格式

    Args:
        json_str: LLM 原始响应文本

    Returns:
        解析后的丰富 dict，解析完全失败时返回默认值
    """
    if not json_str or not json_str.strip():
        return _default_enriched()

    data = None
    # 尝试纯 JSON 解析
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        # 尝试从 markdown 代码块中提取
        match = re.search(r"```(?:json)?\s*\n(.*?)\n```", json_str, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

    if not isinstance(data, dict):
        return _default_enriched()

    # 旧格式检测：包含 emotion 键（非 emotion_understanding）
    if "emotion" in data and "intensity" in data:
        # intensity 可能是 null / 字符串 / 带百分号 —— 直接 float() 会 TypeError。
        # 这个解析器一路「从不抛异常」，模型抽风时也要保住这条。
        raw_intensity = data.get("intensity", 0.5)
        try:
            old_intensity = float(raw_intensity)
        except (TypeError, ValueError):
            old_intensity = 0.5
        return {
            "emotion_understanding": data.get("reason", ""),
            "emotional_needs": [],
            "affection_impact": {
                "direction": "neutral",
                "level": "low",
                "reason": data.get("reason", ""),
            },
            "personality_shift": {},
            "response_guidance": {"tone": "", "key_points": [], "avoid": []},
            "_old_emotion": data.get("emotion", "中性"),
            "_old_intensity": old_intensity,
            "_old_reason": data.get("reason", ""),
        }

    # 新格式 — 逐字段验证填充
    result = {}
    result["emotion_understanding"] = data.get("emotion_understanding", "")

    raw_needs = data.get("emotional_needs")
    result["emotional_needs"] = raw_needs if isinstance(raw_needs, list) else []

    raw_ai = data.get("affection_impact")
    if isinstance(raw_ai, dict):
        result["affection_impact"] = {
            "direction": raw_ai.get("direction", "neutral"),
            "level": raw_ai.get("level", "low"),
            "reason": raw_ai.get("reason", ""),
        }
    else:
        result["affection_impact"] = {"direction": "neutral", "level": "low", "reason": ""}

    raw_ps = data.get("personality_shift")
    result["personality_shift"] = raw_ps if isinstance(raw_ps, dict) else {}

    raw_rg = data.get("response_guidance")
    if isinstance(raw_rg, dict):
        result["response_guidance"] = {
            "tone": raw_rg.get("tone", ""),
            "key_points": raw_rg.get("key_points", []),
            "avoid": raw_rg.get("avoid", []),
        }
    else:
        result["response_guidance"] = {"tone": "", "key_points": [], "avoid": []}

    return result


def _default_enriched() -> dict:
    """返回默认的丰富分析结果（解析失败时的回退值）。"""
    return {
        "emotion": "",
        "intensity": None,
        "emotion_understanding": "",
        "emotional_needs": [],
        "affection_impact": {
            "direction": "neutral",
            "level": "low",
            "reason": "",
        },
        "personality_shift": {},
        "response_guidance": {"tone": "", "key_points": [], "avoid": []},
    }


# 情感类型中文映射
EMOTION_CN_MAP = {
    EmotionType.HAPPY: "开心",
    EmotionType.SAD: "难过",
    EmotionType.ANGRY: "生气",
    EmotionType.NEUTRAL: "中性",
    EmotionType.EXCITED: "兴奋",
    EmotionType.LONELY: "孤独",
    EmotionType.ANXIOUS: "焦虑",
    EmotionType.LOVE: "爱意",
}

# 中文 → 情感类型反向映射
CN_EMOTION_MAP = {v: k for k, v in EMOTION_CN_MAP.items()}


class EmotionTrajectory:
    """情感轨迹追踪器

    追踪最近 N 条消息的情绪变化趋势。
    """

    def __init__(self, window_size: int = 10):
        self._window_size = window_size
        self._history: deque[EmotionResult] = deque(maxlen=window_size)

    def add(self, emotion: EmotionResult) -> None:
        """添加一条情感记录"""
        self._history.append(emotion)

    def get_trend(self) -> str:
        """获取情感趋势

        Returns:
            "improving" = 情绪好转
            "declining" = 情绪恶化
            "stable" = 稳定
            "insufficient" = 数据不足
        """
        if len(self._history) < 3:
            return "insufficient"

        # 情感效价（正面=正数，负面=负数，中性=0）
        valence_map = {
            EmotionType.HAPPY: 1.0,
            EmotionType.EXCITED: 1.0,
            EmotionType.LOVE: 0.8,
            EmotionType.NEUTRAL: 0.0,
            EmotionType.LONELY: -0.5,
            EmotionType.ANXIOUS: -0.5,
            EmotionType.SAD: -1.0,
            EmotionType.ANGRY: -1.0,
        }

        recent = list(self._history)[-5:]  # 最近 5 条
        scores = [
            valence_map.get(e.emotion, 0) * e.intensity
            for e in recent
        ]

        if len(scores) < 3:
            # 不可达：进到这里时 `len(self._history) >= 3` 已成立，
            # 而 `recent = list(self._history)[-5:]` 不会变短。留作防御。
            return "stable"  # pragma: no cover

        # 比较前半和后半
        mid = len(scores) // 2
        early_avg = sum(scores[:mid]) / max(mid, 1)
        late_avg = sum(scores[mid:]) / max(len(scores) - mid, 1)

        diff = late_avg - early_avg
        if diff > 0.3:
            return "improving"
        elif diff < -0.3:
            return "declining"
        else:
            return "stable"

    def get_dominant_emotion(self) -> EmotionType | None:
        """获取近期主导情感"""
        if not self._history:
            return None
        from collections import Counter
        emotions = Counter(e.emotion for e in self._history)
        return emotions.most_common(1)[0][0]

    def get_avg_intensity(self) -> float:
        """获取平均情感强度"""
        if not self._history:
            return 0.0
        return sum(e.intensity for e in self._history) / len(self._history)

    def is_persistent_negative(self) -> bool:
        """是否持续低落（最近 3+ 条都是负面情绪）"""
        if len(self._history) < 3:
            return False
        negative = {EmotionType.SAD, EmotionType.ANGRY, EmotionType.ANXIOUS, EmotionType.LONELY}
        recent = list(self._history)[-3:]
        return all(e.emotion in negative for e in recent)

    def clear(self) -> None:
        """清空轨迹"""
        self._history.clear()


class LLMEmotionAnalyzer:
    """LLM 情感分析器（升级版）

    策略：
    1. 对所有消息用 LLM 分析（带上下文 + 丰富字段）
    2. 如果 LLM 不可用，回退到关键词分析
    3. 追踪情感轨迹，提供趋势信息
    4. 连续失败 → 降级模式（避免浪费 token）
    5. 输出 emotion_understanding / affection_impact / personality_shift / response_guidance
    """

    ENRICHED_ANALYZE_PROMPT = """分析用户消息的情感状态。

最近对话上下文：
{context}

用户消息：{text}

以 JSON 格式输出：
{{
  "emotion": "最贴近的一个，只能从这八个里选：开心 | 难过 | 生气 | 中性 | 兴奋 | 孤独 | 焦虑 | 爱意",
  "intensity": 0.0 到 1.0 之间的小数，表示这种情绪的强度,
  "emotion_understanding": "用户此刻的真实情绪——表面之下在感受什么",
  "emotional_needs": ["需要1", "需要2"],
  "affection_impact": {{
    "direction": "strong_positive|positive|slight_positive|neutral|slight_negative|negative|strong_negative",
    "level": "high|medium|low",
    "reason": "简要原因"
  }}
}}

注意：`emotion` 是给人格状态机读的字段，必须是上面八个标签之一，不要写别的词。
`emotion_understanding` 可以自由描述，不要只复述 emotion 标签。

只输出 JSON。"""

    # 结构化 emotion 字段的白名单：中文标签和英文枚举值都认，其余一概不认。
    _EMOTION_LABELS: dict[str, EmotionType] = {
        **{label: emotion for emotion, label in EMOTION_CN_MAP.items()},
        **{emotion.value: emotion for emotion in EmotionType},
    }

    def __init__(self, llm: BaseLLM | None = None):
        self._llm = llm
        self._trajectory = EmotionTrajectory()
        self._failure_count = 0
        self._degraded = False
        self._max_failures = 3

    def set_llm(self, llm: BaseLLM) -> None:
        """延迟设置 LLM（首次对话时初始化）"""
        self._llm = llm

    @property
    def trajectory(self) -> EmotionTrajectory:
        """获取情感轨迹"""
        return self._trajectory

    @staticmethod
    def parse_affection_llm_output(data: dict | str) -> dict:
        """解析 LLM 输出为亲密度系统可消费的丰富 dict。

        同时是测试入口（``test_affection_llm_parse.py``
        通过 ``LLMEmotionAnalyzer.parse_affection_llm_output()`` 调用）。

        Args:
            data: dict（已解析的 JSON）或 str（原始 LLM 输出文本）

        Returns:
            Dict 包含 emotion_understanding、affection_impact（含 delta）、
            personality_shift（含所有 4 维度）、response_guidance。
        """
        # ── 字符串输入：尝试 JSON 解析，失败则回退到关键词分析 ──
        if isinstance(data, str):
            parsed = parse_json_response(data)
            if parsed is not None:
                return LLMEmotionAnalyzer.parse_affection_llm_output(parsed)
            # 纯文本 → EmotionAnalyzer + 中性亲密度
            emotion_result = EmotionAnalyzer.analyze(data)
            return {
                "emotion": emotion_result.emotion,
                "emotion_understanding": "",
                "emotional_needs": [],
                "affection_impact": {
                    "direction": AffectionDirection.NEUTRAL,
                    "level": AffectionLevel.LOW,
                    "reason": "",
                    "delta": 0.0,
                },
                "personality_shift": {
                    "trust": "no_change",
                    "dependence": "no_change",
                    "openness": "no_change",
                    "jealousy": "no_change",
                },
                "response_guidance": {"tone": "", "key_points": [], "avoid": []},
            }

        # ── dict 输入：提取 + 验证 + 补充默认值 ──
        result: dict = {}

        # emotion / intensity —— 人格状态机的直接输入，原样透传给 analyze()。
        # 放在这里而不是在 analyze() 里再读一次原始 JSON，是为了让所有
        # 「模型输出 → 结构化结果」的规范化只发生在一个地方。
        result["emotion"] = data.get("emotion", "")
        result["intensity"] = data.get("intensity")

        # emotion_understanding
        result["emotion_understanding"] = data.get("emotion_understanding", "")

        # emotional_needs
        raw_needs = data.get("emotional_needs")
        result["emotional_needs"] = raw_needs if isinstance(raw_needs, list) else []

        # affection_impact → 含 delta 计算
        raw_ai = data.get("affection_impact", {})
        if isinstance(raw_ai, dict):
            direction_str = raw_ai.get("direction", "neutral")
            level_str = raw_ai.get("level", "low")
            reason = raw_ai.get("reason", "")
        else:
            direction_str = "neutral"
            level_str = "low"
            reason = ""

        dir_enum = AffectionMapper._parse_direction(direction_str)
        lvl_enum = AffectionMapper._parse_level(level_str)
        delta = AffectionMapper.get_delta(dir_enum, lvl_enum)

        result["affection_impact"] = {
            "direction": dir_enum,
            "level": lvl_enum,
            "reason": reason,
            "delta": delta,
        }

        # personality_shift → 4 维度全量填充
        raw_ps = data.get("personality_shift", {})
        if isinstance(raw_ps, dict):
            result["personality_shift"] = {
                "trust": raw_ps.get("trust", "no_change"),
                "dependence": raw_ps.get("dependence", "no_change"),
                "openness": raw_ps.get("openness", "no_change"),
                "jealousy": raw_ps.get("jealousy", "no_change"),
                "affection": raw_ps.get("affection", "no_change"),
            }
        else:
            result["personality_shift"] = {
                "trust": "no_change",
                "dependence": "no_change",
                "openness": "no_change",
                "jealousy": "no_change",
                "affection": "no_change",
            }

        # response_guidance
        raw_rg = data.get("response_guidance", {})
        if isinstance(raw_rg, dict):
            result["response_guidance"] = {
                "tone": raw_rg.get("tone", ""),
                "key_points": raw_rg.get("key_points", []),
                "avoid": raw_rg.get("avoid", []),
            }
        else:
            result["response_guidance"] = {"tone": "", "key_points": [], "avoid": []}

        return result

    async def analyze(
        self, text: str, recent_messages: list[dict] | None = None
    ) -> tuple[EmotionResult, dict]:
        """分析文本情感（带上下文感知 + 丰富字段 + 降级机制）

        Args:
            text: 要分析的文本
            recent_messages: 最近几条消息（用于上下文感知）

        Returns:
            (EmotionResult, enriched_dict) 元组。
            enriched_dict 包含 emotion_understanding、affection_impact、personality_shift、response_guidance。
        """
        if not text:
            result = EmotionResult(EmotionType.NEUTRAL, 0.0, [])
            self._trajectory.add(result)
            return result, _default_enriched()

        result = None
        enriched = None

        # 第一步：尝试 LLM 丰富分析（即使降级也试一次 — 用于恢复）
        if self._llm:
            try:
                enriched = await self._llm_enriched_analyze(text, recent_messages)

                # 旧格式向前兼容
                if "_old_emotion" in enriched:
                    emotion_cn = enriched["_old_emotion"]
                    intensity = float(enriched.get("_old_intensity", 0.5))
                    reason = enriched.get("_old_reason", "")
                    emotion_type = CN_EMOTION_MAP.get(emotion_cn, EmotionType.NEUTRAL)
                    intensity = max(0.0, min(1.0, intensity))
                    result = EmotionResult(
                        emotion=emotion_type,
                        intensity=round(intensity, 2),
                        keywords=[f"LLM:{reason}"] if reason else [],
                    )
                else:
                    # 新格式：优先读结构化 emotion 字段（模型直接给八选一的枚举），
                    # 拿不到才回退到从 emotion_understanding 里猜子串。
                    # 旧实现只做后者，「用户有点委屈，但没直接说」会被判成 neutral，
                    # 而 neutral 的坐标正好是原点 —— 每一次误判都在把她往清零拉。
                    emotion_type = self.parse_emotion_label(enriched.get("emotion"))
                    if emotion_type is None:
                        emotion_type = self._map_emotion(
                            enriched.get("emotion_understanding", "")
                        )
                    reason = enriched.get("affection_impact", {}).get("reason", "")
                    result = EmotionResult(
                        emotion=emotion_type,
                        intensity=self.parse_emotion_intensity(enriched.get("intensity")),
                        keywords=[f"LLM:{reason}"] if reason else [],
                    )

                # 成功：重置失败计数
                self._failure_count = 0
                self._degraded = False
                logger.debug(f"LLM emotion: {result.emotion.value} ({result.intensity:.2f})")

            except Exception as e:
                logger.debug(f"LLM emotion analysis failed: {e}")
                self._failure_count += 1
                if self._failure_count >= self._max_failures:
                    self._degraded = True

        # 第二步：LLM 失败 → 回退到关键词分析
        if result is None:
            result = EmotionAnalyzer.analyze(text)
            enriched = _default_enriched()
            logger.debug(f"Using keyword emotion: {result.emotion.value}")

        # 记录到轨迹
        self._trajectory.add(result)
        return result, enriched

    # ── 内部方法 ──────────────────────────────────────────────

    @classmethod
    def parse_emotion_label(cls, raw) -> EmotionType | None:
        """把模型返回的 ``emotion`` 字段解析成 EmotionType，不认识就返回 None。

        只认白名单（八个中文标签 + 八个英文枚举值），不做模糊匹配。
        返回 None 时调用方会回退到 ``_map_emotion`` 的子串匹配，
        两层兜底比一层含糊更可靠。
        """
        if not isinstance(raw, str):
            return None
        key = raw.strip().strip("。.，,、\"'“”「」").lower()
        return cls._EMOTION_LABELS.get(key)

    @staticmethod
    def parse_emotion_intensity(raw, default: float = 0.5) -> float:
        """解析情绪强度并 clamp 到 [0, 1]。

        历史缺陷：``analyze()`` 里 intensity 原本硬编码为 0.5，于是
        ``mood.influence = intensity * 0.4`` 恒等于 0.2 ——「这次刺激有多强」
        这个维度整体不存在，每轮位移都一样。
        """
        if isinstance(raw, bool):  # bool 是 int 子类，True 会被读成 1.0
            return default
        try:
            return max(0.0, min(1.0, float(raw)))
        except (TypeError, ValueError):
            return default

    def _map_emotion(self, text: str) -> EmotionType:
        """将情感理解文本映射为 EmotionType。

        这是**回退路径**：只在模型没有给出结构化 ``emotion`` 字段时使用。
        它是 8 个中文词对自由文本做子串匹配，实测命中率很低（"用户有点委屈"
        → neutral），所以正常路径应当依赖 ``parse_emotion_label``。

        依次尝试：中文情感词 → 英文情感词 → NEUTRAL。
        """
        if not text:
            return EmotionType.NEUTRAL

        # 中文优先
        for cn_label, emotion_type in CN_EMOTION_MAP.items():
            if cn_label in text:
                return emotion_type

        # 英文关键词
        text_lower = text.lower()
        eng_map: dict[EmotionType, list[str]] = {
            EmotionType.HAPPY: ["happy", "joy", "glad", "pleased", "cheerful", "delighted"],
            EmotionType.SAD: ["sad", "unhappy", "depressed", "grief", "sorrow", "heartbroken"],
            EmotionType.ANGRY: ["angry", "mad", "frustrated", "irritated", "furious"],
            EmotionType.EXCITED: ["excited", "thrilled", "amazed", "astonished", "wow"],
            EmotionType.LONELY: ["lonely", "alone", "isolated", "abandoned", "solitary"],
            EmotionType.ANXIOUS: ["anxious", "worried", "nervous", "fearful", "tense", "uneasy"],
            EmotionType.LOVE: ["love", "affection", "adore", "cherish", "fond", "tender"],
        }
        for emotion_type, keywords in eng_map.items():
            for kw in keywords:
                if kw in text_lower:
                    return emotion_type

        return EmotionType.NEUTRAL

    async def _llm_enriched_analyze(
        self, text: str, recent_messages: list[dict] | None = None
    ) -> dict:
        """用 LLM 分析情感（丰富字段），返回 enriched dict。

        Raises:
            RuntimeError: 无 LLM 可用
            Exception: LLM 调用或解析失败 → 由调用方降级处理
        """
        if not self._llm:
            raise RuntimeError("No LLM available")

        # 构建上下文
        context = ""
        if recent_messages:
            recent = recent_messages[-6:]  # 最近 3 轮
            lines = []
            for msg in recent:
                role = "用户" if msg.get("role") == "user" else "助手"
                content = msg.get("content", "")[:80]
                lines.append(f"{role}: {content}")
            context = "\n".join(lines)
        else:
            context = "（无历史上下文）"

        prompt = self.ENRICHED_ANALYZE_PROMPT.format(
            context=context,
            text=text,
        )

        response = await self._llm.chat(
            messages=[{"role": "user", "content": text}],
            system_prompt=prompt,
            max_tokens=300,
            temperature=0.1,
        )

        enriched = parse_enriched_output(response.content)

        # 无有效数据 → 触发调用方降级
        if (
            not enriched.get("emotion_understanding")
            and "_old_emotion" not in enriched
            and not enriched.get("affection_impact", {}).get("reason")
        ):
            raise ValueError("No usable emotion data from LLM response")

        return enriched
