"""`core/emotion/llm_analyzer.py` 的测试

三块：
1. `parse_enriched_output` / `_default_enriched` —— LLM 原始文本 → 结构化 dict
2. `EmotionTrajectory` —— 滑动窗口情感轨迹
3. `LLMEmotionAnalyzer` —— LLM 分析 + 关键词降级 + 连续失败降级

⚠️ 关键契约（改之前先读）：
- `parse_enriched_output` **从不抛异常**：空串、非 JSON、非 dict、坏的
  markdown 代码块都返回 `_default_enriched()`。
- 旧格式判定是 `"emotion" in data and "intensity" in data` 两个键同时存在，
  返回值多带 `_old_emotion` / `_old_intensity` / `_old_reason` 三个键 ——
  `analyze()` 就靠 `"_old_emotion" in enriched` 走旧格式分支。
- `EmotionTrajectory.get_trend()` 需要 **≥3 条**才返回真实趋势；2 条返回
  `"insufficient"`，而 ≥5 条时才只看最近 5 条。
- `LLMEmotionAnalyzer` 连续失败 `_max_failures = 3` 次后置 `_degraded = True`，
  但**降级只是标记位，下一次仍然会试 LLM**（代码注释：「即使降级也试一次 ——
  用于恢复」）。`_degraded` 目前没有任何读取方，属观测字段。
- `analyze("")` 不调 LLM，直接返回 NEUTRAL 且**仍会写进轨迹**。
"""

from __future__ import annotations

import json

import pytest

from core.emotion.analyzer import EmotionResult, EmotionType
from core.emotion.llm_analyzer import (
    CN_EMOTION_MAP,
    EMOTION_CN_MAP,
    EmotionTrajectory,
    LLMEmotionAnalyzer,
    _default_enriched,
    parse_enriched_output,
)
from core.llm.base import LLMResponse
from core.social.affection.constants import AffectionDirection, AffectionLevel


class FakeLLM:
    """只实现 `chat()`，返回给定文本或抛异常。"""

    def __init__(self, *responses, error: Exception | None = None):
        self._responses = list(responses)
        self._error = error
        self.calls: list[dict] = []

    async def chat(self, messages, system_prompt=None, **kwargs):
        self.calls.append({"messages": messages, "system_prompt": system_prompt, **kwargs})
        if self._error:
            raise self._error
        text = self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        return LLMResponse(content=text, model="fake")


ENRICHED_JSON = json.dumps({
    "emotion_understanding": "他今天很开心，但有点累",
    "emotional_needs": ["被理解", "休息"],
    "affection_impact": {
        "direction": "positive",
        "level": "high",
        "reason": "他主动分享了好消息",
    },
}, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# parse_enriched_output
# --------------------------------------------------------------------------- #


class TestParseEnrichedOutput:
    @pytest.mark.parametrize("raw", ["", "   ", "\n\n"])
    def test_empty_returns_default(self, raw) -> None:
        assert parse_enriched_output(raw) == _default_enriched()

    def test_non_json_returns_default(self) -> None:
        assert parse_enriched_output("这不是 JSON") == _default_enriched()

    def test_json_array_returns_default(self) -> None:
        """顶层是数组也当无效 —— 只接受 dict。"""
        assert parse_enriched_output('[{"a": 1}]') == _default_enriched()

    def test_json_scalar_returns_default(self) -> None:
        assert parse_enriched_output("42") == _default_enriched()

    def test_plain_json_dict(self) -> None:
        result = parse_enriched_output(ENRICHED_JSON)
        assert result["emotion_understanding"] == "他今天很开心，但有点累"
        assert result["emotional_needs"] == ["被理解", "休息"]
        assert result["affection_impact"]["direction"] == "positive"
        assert result["affection_impact"]["level"] == "high"

    def test_markdown_fence(self) -> None:
        raw = f"```json\n{ENRICHED_JSON}\n```"
        assert parse_enriched_output(raw)["affection_impact"]["level"] == "high"

    def test_markdown_fence_without_lang(self) -> None:
        raw = f"```\n{ENRICHED_JSON}\n```"
        assert parse_enriched_output(raw)["emotion_understanding"] != ""

    def test_broken_fence_returns_default(self) -> None:
        assert parse_enriched_output("```json\n{not json}\n```") == _default_enriched()

    def test_chatter_around_json_not_extracted(self) -> None:
        """只有用 ``` 围起来才提取；裸的前后废话不处理。"""
        raw = f"好的，分析结果：{ENRICHED_JSON}"
        assert parse_enriched_output(raw) == _default_enriched()

    # ---- 旧格式 ---- #

    def test_old_format_detected(self) -> None:
        raw = json.dumps({"emotion": "开心", "intensity": 0.8, "reason": "他说了好事"})
        result = parse_enriched_output(raw)
        assert result["_old_emotion"] == "开心"
        assert result["_old_intensity"] == 0.8
        assert result["_old_reason"] == "他说了好事"

    def test_old_format_fills_placeholders(self) -> None:
        raw = json.dumps({"emotion": "开心", "intensity": 0.8})
        result = parse_enriched_output(raw)
        assert result["emotion_understanding"] == ""
        assert result["emotional_needs"] == []
        assert result["personality_shift"] == {}
        assert result["response_guidance"]["tone"] == ""

    def test_requires_both_keys(self) -> None:
        """只有 emotion 没有 intensity → 不算旧格式，走新格式分支。"""
        result = parse_enriched_output(json.dumps({"emotion": "开心"}))
        assert "_old_emotion" not in result

    def test_only_intensity_also_new_format(self) -> None:
        result = parse_enriched_output(json.dumps({"intensity": 0.8}))
        assert "_old_emotion" not in result

    def test_old_intensity_default_when_missing(self) -> None:
        raw = json.dumps({"emotion": "开心", "intensity": None})
        result = parse_enriched_output(raw)
        assert result["_old_intensity"] == 0.5

    # ---- 新格式字段验证 ---- #

    def test_needs_non_list_becomes_empty(self) -> None:
        raw = json.dumps({"emotional_needs": "被理解"})
        assert parse_enriched_output(raw)["emotional_needs"] == []

    def test_affection_impact_non_dict_becomes_default(self) -> None:
        raw = json.dumps({"affection_impact": "positive"})
        assert parse_enriched_output(raw)["affection_impact"] == {
            "direction": "neutral", "level": "low", "reason": "",
        }

    def test_affection_impact_partial_filled(self) -> None:
        raw = json.dumps({"affection_impact": {"direction": "negative"}})
        impact = parse_enriched_output(raw)["affection_impact"]
        assert impact["direction"] == "negative"
        assert impact["level"] == "low"
        assert impact["reason"] == ""

    def test_personality_shift_non_dict_becomes_empty(self) -> None:
        raw = json.dumps({"personality_shift": ["trust"]})
        assert parse_enriched_output(raw)["personality_shift"] == {}

    def test_response_guidance_non_dict_becomes_default(self) -> None:
        raw = json.dumps({"response_guidance": "温柔"})
        assert parse_enriched_output(raw)["response_guidance"] == {
            "tone": "", "key_points": [], "avoid": [],
        }

    def test_response_guidance_passthrough(self) -> None:
        raw = json.dumps({"response_guidance": {
            "tone": "温柔", "key_points": ["问问他今天"], "avoid": ["别追问"],
        }})
        assert parse_enriched_output(raw)["response_guidance"]["tone"] == "温柔"

    def test_never_raises(self) -> None:
        for raw in [None, "", "{}", "[]", "null", "{", "```json\n\n```"]:
            assert isinstance(parse_enriched_output(raw), dict)  # type: ignore[arg-type]


class TestDefaultEnriched:
    def test_shape(self) -> None:
        data = _default_enriched()
        assert set(data) == {
            "emotion", "intensity",
            "emotion_understanding", "emotional_needs", "affection_impact",
            "personality_shift", "response_guidance",
        }

    def test_structured_emotion_defaults_are_empty(self) -> None:
        """默认值必须让 `parse_emotion_label` 返回 None、强度回落到 0.5，
        否则 analyze() 会把「没分析出结果」误当成「判定为中性」。"""
        data = _default_enriched()
        assert LLMEmotionAnalyzer.parse_emotion_label(data["emotion"]) is None
        assert LLMEmotionAnalyzer.parse_emotion_intensity(data["intensity"]) == 0.5

    def test_no_old_keys(self) -> None:
        assert "_old_emotion" not in _default_enriched()

    def test_fresh_copy(self) -> None:
        """每次返回新对象，调用方改了不会污染下一次。"""
        first = _default_enriched()
        first["emotional_needs"].append("x")
        assert _default_enriched()["emotional_needs"] == []


# --------------------------------------------------------------------------- #
# 映射表
# --------------------------------------------------------------------------- #


class TestEmotionMaps:
    def test_covers_all_emotion_types(self) -> None:
        assert set(EMOTION_CN_MAP) == set(EmotionType)

    def test_reverse_map_roundtrip(self) -> None:
        for emotion, label in EMOTION_CN_MAP.items():
            assert CN_EMOTION_MAP[label] is emotion

    def test_chinese_labels_unique(self) -> None:
        assert len(set(EMOTION_CN_MAP.values())) == len(EMOTION_CN_MAP)


# --------------------------------------------------------------------------- #
# EmotionTrajectory
# --------------------------------------------------------------------------- #


def _er(kind: EmotionType, intensity: float = 0.8) -> EmotionResult:
    return EmotionResult(emotion=kind, intensity=intensity, keywords=[])


class TestTrajectory:
    def test_empty(self) -> None:
        t = EmotionTrajectory()
        assert t.get_trend() == "insufficient"
        assert t.get_dominant_emotion() is None
        assert t.get_avg_intensity() == 0.0
        assert t.is_persistent_negative() is False

    def test_insufficient_below_three(self) -> None:
        t = EmotionTrajectory()
        for _ in range(2):
            t.add(_er(EmotionType.HAPPY))
        assert t.get_trend() == "insufficient"
        assert t.is_persistent_negative() is False

    def test_window_size_caps_history(self) -> None:
        t = EmotionTrajectory(window_size=3)
        for _ in range(10):
            t.add(_er(EmotionType.HAPPY))
        # maxlen=3 → 只有 3 条，get_dominant 仍是 happy
        assert t.get_dominant_emotion() is EmotionType.HAPPY

    def test_dominant_emotion(self) -> None:
        t = EmotionTrajectory()
        t.add(_er(EmotionType.SAD))
        t.add(_er(EmotionType.SAD))
        t.add(_er(EmotionType.HAPPY))
        assert t.get_dominant_emotion() is EmotionType.SAD

    def test_avg_intensity(self) -> None:
        t = EmotionTrajectory()
        t.add(_er(EmotionType.HAPPY, 0.2))
        t.add(_er(EmotionType.HAPPY, 0.4))
        assert t.get_avg_intensity() == pytest.approx(0.3)

    def test_persistent_negative(self) -> None:
        t = EmotionTrajectory()
        for kind in (EmotionType.SAD, EmotionType.ANGRY, EmotionType.ANXIOUS):
            t.add(_er(kind))
        assert t.is_persistent_negative() is True

    def test_persistent_negative_broken_by_positive(self) -> None:
        t = EmotionTrajectory()
        t.add(_er(EmotionType.SAD))
        t.add(_er(EmotionType.ANGRY))
        t.add(_er(EmotionType.HAPPY))
        assert t.is_persistent_negative() is False

    def test_only_last_three_checked(self) -> None:
        """前两条负面 + 后面三条正面 → 只看最近 3 条，不判持续低落。"""
        t = EmotionTrajectory()
        t.add(_er(EmotionType.SAD))
        t.add(_er(EmotionType.SAD))
        for _ in range(3):
            t.add(_er(EmotionType.HAPPY))
        assert t.is_persistent_negative() is False

    @pytest.mark.parametrize("kinds,expected", [
        ([EmotionType.SAD, EmotionType.SAD, EmotionType.HAPPY], "improving"),
        ([EmotionType.HAPPY, EmotionType.HAPPY, EmotionType.SAD], "declining"),
        ([EmotionType.HAPPY, EmotionType.HAPPY, EmotionType.HAPPY], "stable"),
    ])
    def test_trends(self, kinds, expected) -> None:
        t = EmotionTrajectory()
        for kind in kinds:
            t.add(_er(kind, 1.0))
        assert t.get_trend() == expected

    def test_only_last_five_used(self) -> None:
        """更早的极端值不该影响当前趋势：前五条全负面、后五条全正面。

        只看最近 5 条 → 全是 happy → stable。若把 10 条全算进去，
        前半负面后半正面就会判成 improving。
        """
        t = EmotionTrajectory(window_size=10)
        for _ in range(5):
            t.add(_er(EmotionType.SAD, 1.0))
        for _ in range(5):
            t.add(_er(EmotionType.HAPPY, 1.0))
        assert t.get_trend() == "stable"

    def test_clear(self) -> None:
        t = EmotionTrajectory()
        t.add(_er(EmotionType.HAPPY))
        t.clear()
        assert t.get_dominant_emotion() is None
        assert t.get_trend() == "insufficient"


# --------------------------------------------------------------------------- #
# parse_affection_llm_output
# --------------------------------------------------------------------------- #


class TestParseAffection:
    def test_string_with_valid_json(self) -> None:
        result = LLMEmotionAnalyzer.parse_affection_llm_output(ENRICHED_JSON)
        assert result["affection_impact"]["direction"] is AffectionDirection.POSITIVE
        assert result["affection_impact"]["level"] is AffectionLevel.HIGH
        assert result["affection_impact"]["delta"] > 0

    def test_plain_text_falls_back_to_keywords(self) -> None:
        result = LLMEmotionAnalyzer.parse_affection_llm_output("我今天特别开心")
        assert result["emotion"] is EmotionType.HAPPY
        assert result["affection_impact"]["direction"] is AffectionDirection.NEUTRAL
        assert result["affection_impact"]["delta"] == 0.0

    def test_fallback_shift_has_four_dims(self) -> None:
        result = LLMEmotionAnalyzer.parse_affection_llm_output("随便说说")
        shift = result["personality_shift"]
        assert shift == {
            "trust": "no_change", "dependence": "no_change",
            "openness": "no_change", "jealousy": "no_change",
        }

    def test_dict_input(self) -> None:
        result = LLMEmotionAnalyzer.parse_affection_llm_output(json.loads(ENRICHED_JSON))
        assert result["emotional_needs"] == ["被理解", "休息"]

    def test_missing_fields_get_defaults(self) -> None:
        result = LLMEmotionAnalyzer.parse_affection_llm_output({})
        assert result["emotion_understanding"] == ""
        assert result["emotional_needs"] == []
        assert result["affection_impact"]["direction"] is AffectionDirection.NEUTRAL

    def test_shift_keeps_given_dims(self) -> None:
        result = LLMEmotionAnalyzer.parse_affection_llm_output(
            {"personality_shift": {"trust": "up"}}
        )
        shift = result["personality_shift"]
        assert shift["trust"] == "up"
        assert shift["jealousy"] == "no_change"

    def test_shift_non_dict_falls_back(self) -> None:
        result = LLMEmotionAnalyzer.parse_affection_llm_output(
            {"personality_shift": "up"}
        )
        assert result["personality_shift"]["trust"] == "no_change"

    def test_guidance_non_dict_falls_back(self) -> None:
        result = LLMEmotionAnalyzer.parse_affection_llm_output(
            {"response_guidance": "温柔"}
        )
        assert result["response_guidance"] == {
            "tone": "", "key_points": [], "avoid": [],
        }

    def test_invalid_direction_string(self) -> None:
        result = LLMEmotionAnalyzer.parse_affection_llm_output(
            {"affection_impact": {"direction": "tornado", "level": "high"}}
        )
        # 未知方向被 parse 成 NEUTRAL，delta 为 0 或默认档
        assert isinstance(result["affection_impact"]["direction"], AffectionDirection)

    def test_negative_impact_has_negative_delta(self) -> None:
        result = LLMEmotionAnalyzer.parse_affection_llm_output({
            "affection_impact": {"direction": "strong_negative", "level": "high"},
        })
        assert result["affection_impact"]["delta"] < 0

    def test_affection_impact_non_dict_falls_back(self) -> None:
        """模型偶尔把 `affection_impact` 直接给成字符串而不是对象。"""
        result = LLMEmotionAnalyzer.parse_affection_llm_output(
            {"affection_impact": "positive"}
        )
        assert result["affection_impact"]["direction"] is AffectionDirection.NEUTRAL
        assert result["affection_impact"]["level"] is AffectionLevel.LOW
        assert result["affection_impact"]["reason"] == ""


# --------------------------------------------------------------------------- #
# LLMEmotionAnalyzer.analyze
# --------------------------------------------------------------------------- #


class TestAnalyze:
    async def test_empty_text_skips_llm(self) -> None:
        llm = FakeLLM(ENRICHED_JSON)
        analyzer = LLMEmotionAnalyzer(llm)
        result, enriched = await analyzer.analyze("")
        assert result.emotion is EmotionType.NEUTRAL
        assert result.intensity == 0.0
        assert enriched == _default_enriched()
        assert llm.calls == []

    async def test_empty_text_still_records_trajectory(self) -> None:
        analyzer = LLMEmotionAnalyzer()
        await analyzer.analyze("")
        assert analyzer.trajectory.get_dominant_emotion() is EmotionType.NEUTRAL

    async def test_no_llm_uses_keywords(self) -> None:
        analyzer = LLMEmotionAnalyzer()
        result, enriched = await analyzer.analyze("我今天特别开心")
        assert result.emotion is EmotionType.HAPPY
        assert enriched == _default_enriched()

    async def test_llm_success_new_format(self) -> None:
        analyzer = LLMEmotionAnalyzer(FakeLLM(ENRICHED_JSON))
        result, enriched = await analyzer.analyze("今天升职了")
        assert result.intensity == 0.5
        assert "LLM:他主动分享了好消息" in result.keywords
        assert enriched["affection_impact"]["direction"] == "positive"

    async def test_llm_new_format_emotion_from_understanding(self) -> None:
        analyzer = LLMEmotionAnalyzer(FakeLLM(ENRICHED_JSON))
        result, _ = await analyzer.analyze("今天升职了")
        assert result.emotion is EmotionType.HAPPY

    async def test_llm_success_resets_failures(self) -> None:
        analyzer = LLMEmotionAnalyzer(FakeLLM(ENRICHED_JSON))
        analyzer._failure_count = 2
        await analyzer.analyze("嗯")
        assert analyzer._failure_count == 0

    async def test_old_format_response(self) -> None:
        raw = json.dumps({"emotion": "难过", "intensity": 1.5, "reason": "失恋"})
        analyzer = LLMEmotionAnalyzer(FakeLLM(raw))
        result, enriched = await analyzer.analyze("唉")
        assert result.emotion is EmotionType.SAD
        assert result.intensity == 1.0  # clamp
        assert enriched["_old_emotion"] == "难过"

    async def test_old_format_unknown_emotion_falls_to_neutral(self) -> None:
        raw = json.dumps({"emotion": "困惑", "intensity": 0.5})
        analyzer = LLMEmotionAnalyzer(FakeLLM(raw))
        result, _ = await analyzer.analyze("嗯")
        assert result.emotion is EmotionType.NEUTRAL

    async def test_old_format_no_reason_gives_no_keywords(self) -> None:
        raw = json.dumps({"emotion": "开心", "intensity": 0.5})
        analyzer = LLMEmotionAnalyzer(FakeLLM(raw))
        result, _ = await analyzer.analyze("嗯")
        assert result.keywords == []

    async def test_llm_failure_falls_back_to_keywords(self) -> None:
        analyzer = LLMEmotionAnalyzer(FakeLLM("", error=RuntimeError("boom")))
        result, enriched = await analyzer.analyze("我好难过")
        assert result.emotion is EmotionType.SAD
        assert enriched == _default_enriched()

    async def test_three_failures_sets_degraded(self) -> None:
        analyzer = LLMEmotionAnalyzer(FakeLLM("", error=RuntimeError("boom")))
        for _ in range(3):
            await analyzer.analyze("嗯")
        assert analyzer._degraded is True

    async def test_degraded_still_tries_llm(self) -> None:
        """降级只是标记位，下一次仍会试 —— 为了能自动恢复。"""
        llm = FakeLLM("", error=RuntimeError("boom"))
        analyzer = LLMEmotionAnalyzer(llm)
        for _ in range(3):
            await analyzer.analyze("嗯")
        before = len(llm.calls)
        await analyzer.analyze("嗯")
        assert len(llm.calls) > before

    async def test_success_after_failures_clears_degraded(self) -> None:
        class Flaky:
            def __init__(self):
                self.n = 0

            async def chat(self, messages, system_prompt=None, **kwargs):
                self.n += 1
                if self.n <= 3:
                    raise RuntimeError("boom")
                return LLMResponse(content=ENRICHED_JSON, model="fake")

        analyzer = LLMEmotionAnalyzer(Flaky())
        for _ in range(4):
            await analyzer.analyze("嗯")
        assert analyzer._degraded is False

    async def test_invalid_json_response_falls_back(self) -> None:
        """LLM 回了但没有可用字段 → `_llm_enriched_analyze` 抛 ValueError。"""
        analyzer = LLMEmotionAnalyzer(FakeLLM("哈哈哈"))
        result, enriched = await analyzer.analyze("我好开心")
        assert result.emotion is EmotionType.HAPPY
        assert enriched == _default_enriched()

    async def test_trajectory_grows(self) -> None:
        analyzer = LLMEmotionAnalyzer()
        for _ in range(3):
            await analyzer.analyze("难过")
        assert analyzer.trajectory.get_trend() in {"stable", "declining", "insufficient"}
        assert analyzer.trajectory.get_dominant_emotion() is EmotionType.SAD


# --------------------------------------------------------------------------- #
# _map_emotion
# --------------------------------------------------------------------------- #


class TestMapEmotion:
    @pytest.mark.parametrize("text,expected", [
        ("他很开心", EmotionType.HAPPY),
        ("有点难过", EmotionType.SAD),
        ("很生气", EmotionType.ANGRY),
        ("中性", EmotionType.NEUTRAL),
        ("兴奋", EmotionType.EXCITED),
        ("孤独", EmotionType.LONELY),
        ("焦虑", EmotionType.ANXIOUS),
        ("爱意", EmotionType.LOVE),
    ])
    def test_chinese(self, text, expected) -> None:
        assert LLMEmotionAnalyzer()._map_emotion(text) is expected

    @pytest.mark.parametrize("text,expected", [
        ("he is happy", EmotionType.HAPPY),
        ("feeling sad today", EmotionType.SAD),
        ("very angry", EmotionType.ANGRY),
        ("excited!", EmotionType.EXCITED),
        ("he feels lonely", EmotionType.LONELY),
        ("anxious about tomorrow", EmotionType.ANXIOUS),
        ("full of love", EmotionType.LOVE),
    ])
    def test_english(self, text, expected) -> None:
        assert LLMEmotionAnalyzer()._map_emotion(text) is expected

    def test_case_insensitive(self) -> None:
        assert LLMEmotionAnalyzer()._map_emotion("HAPPY") is EmotionType.HAPPY

    def test_unknown(self) -> None:
        assert LLMEmotionAnalyzer()._map_emotion("说不清") is EmotionType.NEUTRAL

    @pytest.mark.parametrize("text", ["", None])
    def test_empty(self, text) -> None:
        assert LLMEmotionAnalyzer()._map_emotion(text) is EmotionType.NEUTRAL  # type: ignore[arg-type]

    def test_chinese_wins_over_english(self) -> None:
        """同时含「开心」与「sad」→ 中文优先。"""
        assert LLMEmotionAnalyzer()._map_emotion("开心 but sad") is EmotionType.HAPPY


# --------------------------------------------------------------------------- #
# 内部：_llm_enriched_analyze
# --------------------------------------------------------------------------- #


class TestLlmEnrichedAnalyze:
    async def test_no_llm_raises(self) -> None:
        with pytest.raises(RuntimeError):
            await LLMEmotionAnalyzer()._llm_enriched_analyze("hi")

    async def test_prompt_without_history(self) -> None:
        llm = FakeLLM(ENRICHED_JSON)
        await LLMEmotionAnalyzer(llm)._llm_enriched_analyze("今天升职了")
        system = llm.calls[0]["system_prompt"]
        assert "（无历史上下文）" in system
        assert "今天升职了" in system

    async def test_prompt_with_history(self) -> None:
        llm = FakeLLM(ENRICHED_JSON)
        history = [
            {"role": "user", "content": "我今天面试完了"},
            {"role": "assistant", "content": "怎么样"},
        ]
        await LLMEmotionAnalyzer(llm)._llm_enriched_analyze("过了", history)
        system = llm.calls[0]["system_prompt"]
        assert "用户: 我今天面试完了" in system
        assert "助手: 怎么样" in system

    async def test_history_truncated_to_six(self) -> None:
        llm = FakeLLM(ENRICHED_JSON)
        history = [{"role": "user", "content": f"第{i}条"} for i in range(20)]
        await LLMEmotionAnalyzer(llm)._llm_enriched_analyze("x", history)
        system = llm.calls[0]["system_prompt"]
        assert "第0条" not in system
        assert "第19条" in system

    async def test_content_truncated_to_80(self) -> None:
        llm = FakeLLM(ENRICHED_JSON)
        history = [{"role": "user", "content": "长" * 200}]
        await LLMEmotionAnalyzer(llm)._llm_enriched_analyze("x", history)
        assert "长" * 81 not in llm.calls[0]["system_prompt"]

    async def test_unknown_role_treated_as_assistant(self) -> None:
        llm = FakeLLM(ENRICHED_JSON)
        history = [{"role": "system", "content": "系统消息"}]
        await LLMEmotionAnalyzer(llm)._llm_enriched_analyze("x", history)
        assert "助手: 系统消息" in llm.calls[0]["system_prompt"]

    async def test_llm_params(self) -> None:
        llm = FakeLLM(ENRICHED_JSON)
        await LLMEmotionAnalyzer(llm)._llm_enriched_analyze("x")
        call = llm.calls[0]
        assert call["max_tokens"] == 300
        assert call["temperature"] == 0.1
        assert call["messages"] == [{"role": "user", "content": "x"}]

    async def test_empty_understanding_raises(self) -> None:
        llm = FakeLLM(json.dumps({}))
        with pytest.raises(ValueError):
            await LLMEmotionAnalyzer(llm)._llm_enriched_analyze("x")

    async def test_old_format_accepted(self) -> None:
        raw = json.dumps({"emotion": "开心", "intensity": 0.5})
        result = await LLMEmotionAnalyzer(FakeLLM(raw))._llm_enriched_analyze("x")
        assert result["_old_emotion"] == "开心"

    async def test_reason_alone_is_enough(self) -> None:
        """只有 affection_impact.reason 也算有数据（不必有 understanding）。"""
        raw = json.dumps({"affection_impact": {"reason": "他分享了好消息"}})
        result = await LLMEmotionAnalyzer(FakeLLM(raw))._llm_enriched_analyze("x")
        assert result["affection_impact"]["reason"] == "他分享了好消息"


# --------------------------------------------------------------------------- #
# set_llm / trajectory property
# --------------------------------------------------------------------------- #


class TestAccessors:
    def test_set_llm_late_binding(self) -> None:
        analyzer = LLMEmotionAnalyzer()
        assert analyzer._llm is None
        analyzer.set_llm(FakeLLM(ENRICHED_JSON))
        assert analyzer._llm is not None

    def test_trajectory_property_identity(self) -> None:
        analyzer = LLMEmotionAnalyzer()
        assert analyzer.trajectory is analyzer._trajectory

    def test_max_failures_default(self) -> None:
        assert LLMEmotionAnalyzer()._max_failures == 3


# --------------------------------------------------------------------------- #
# 结构化 emotion / intensity —— 让情绪终于能"动"
# --------------------------------------------------------------------------- #


class TestParseEmotionLabel:
    """模型直接给枚举，代替「8 个中文词去子串匹配自由文本」。

    历史缺陷的实测数据：8 条真实风格的 emotion_understanding 里只有 2 条
    命中非 neutral（"用户有点委屈"、"被工作压得喘不过气" 全被判成 neutral），
    而 neutral 的坐标正好是 (0.0, 0.0)，所以每次误判都在把她清零。
    """

    @pytest.mark.parametrize("raw,expected", [
        ("难过", EmotionType.SAD),
        ("焦虑", EmotionType.ANXIOUS),
        ("爱意", EmotionType.LOVE),
        ("sad", EmotionType.SAD),
        ("ANXIOUS", EmotionType.ANXIOUS),
        ("  开心。 ", EmotionType.HAPPY),
        ("「孤独」", EmotionType.LONELY),
    ])
    def test_accepts_both_label_forms(self, raw, expected) -> None:
        assert LLMEmotionAnalyzer.parse_emotion_label(raw) is expected

    @pytest.mark.parametrize("raw", [None, "", "  ", "有点说不上来", 42, ["sad"]])
    def test_rejects_unknown(self, raw) -> None:
        assert LLMEmotionAnalyzer.parse_emotion_label(raw) is None


class TestParseEmotionIntensity:
    @pytest.mark.parametrize("raw,expected", [
        (0.82, 0.82),
        ("0.4", 0.4),
        (2, 1.0),
        (-1, 0.0),
        (None, 0.5),
        ("很强", 0.5),
        (True, 0.5),
    ])
    def test_clamps_and_falls_back(self, raw, expected) -> None:
        assert LLMEmotionAnalyzer.parse_emotion_intensity(raw) == expected


class TestStructuredEmotionWins:
    """analyze() 必须优先采信结构化 emotion 字段。"""

    async def test_uses_structured_emotion_over_free_text(self) -> None:
        llm = FakeLLM(json.dumps({
            "emotion": "难过",
            "intensity": 0.8,
            # 自由描述里一个情感词都不出现 —— 旧实现会判成 neutral
            "emotion_understanding": "用户在说一件已经过去的事，语气很平",
            "affection_impact": {"direction": "neutral", "level": "low", "reason": ""},
        }, ensure_ascii=False))
        analyzer = LLMEmotionAnalyzer(llm)

        result, _ = await analyzer.analyze("算了，都过去了")

        assert result.emotion is EmotionType.SAD
        assert result.intensity == 0.8

    async def test_falls_back_to_substring_when_field_missing(self) -> None:
        """模型没给 emotion 字段时，仍要能用旧的子串匹配兜住。"""
        llm = FakeLLM(json.dumps({
            "emotion_understanding": "用户很开心",
            "affection_impact": {"direction": "positive", "level": "low", "reason": ""},
        }, ensure_ascii=False))
        analyzer = LLMEmotionAnalyzer(llm)

        result, _ = await analyzer.analyze("今天真好")

        assert result.emotion is EmotionType.HAPPY
        assert result.intensity == 0.5  # 无从得知强度时用中性默认

    async def test_prompt_asks_for_enum_and_intensity(self) -> None:
        """提示词本身必须索要这两个字段 —— 否则解析器写得再好也拿不到数据。"""
        prompt = LLMEmotionAnalyzer.ENRICHED_ANALYZE_PROMPT
        assert '"emotion"' in prompt
        assert '"intensity"' in prompt
        assert "开心" in prompt and "焦虑" in prompt
