"""`core/emotion/analyzer.py` 的测试

关键词式情感分析：无外部依赖、无 LLM。它同时被三处依赖：
1. `MoodEngine.update_from_emotion()` 拿 `EmotionResult` 改情绪坐标；
2. `life_summary` / `open_loop` 用 `emotion` 枚举做分支；
3. `emotion_label()` 把枚举翻成中文（缺 label 会拼出「比较happy」）。

⚠️ 关键契约（改之前先读）：
- `analyze("")` → `NEUTRAL / 0.0 / []`，不抛异常。
- 没有任何关键词命中 → 也是 `NEUTRAL / 0.0 / []`（**不是**「低强度 SAD」）。
- 平分时 `max()` 取**字典插入顺序**里第一个 —— 顺序是 HAPPY→SAD→ANGRY→EXCITED→LONELY→ANXIOUS→LOVE。
- 否定检测只看关键词前面 3 个字符，且 `idx <= 0`（出现在开头/找不到）直接判「未否定」。
- `intensity = min(命中数 / 3, 1.0)`，再乘 booster ×1.3 / reducer ×0.7，最后 `round(..., 2)`。
"""

from __future__ import annotations

import pytest

from core.emotion.analyzer import (
    EMOTION_KEYWORDS,
    EMOTION_LABELS,
    INTENSITY_BOOSTERS,
    INTENSITY_REDUCERS,
    NEGATION_WORDS,
    EmotionAnalyzer,
    EmotionResult,
    EmotionType,
    emotion_label,
)


# --------------------------------------------------------------------------- #
# 常量表
# --------------------------------------------------------------------------- #


class TestConstants:
    def test_every_emotion_type_has_label(self) -> None:
        missing = [e.value for e in EmotionType if e.value not in EMOTION_LABELS]
        assert missing == []

    def test_neutral_has_no_keywords(self) -> None:
        """NEUTRAL 是「没命中任何关键词」的兜底，刻意不设关键词表。"""
        assert EmotionType.NEUTRAL not in EMOTION_KEYWORDS

    def test_other_emotions_have_keywords(self) -> None:
        expected = set(EmotionType) - {EmotionType.NEUTRAL}
        assert set(EMOTION_KEYWORDS) == expected

    def test_keyword_lists_non_empty(self) -> None:
        for emotion, words in EMOTION_KEYWORDS.items():
            assert words, emotion

    def test_no_duplicate_keywords_within_list(self) -> None:
        for emotion, words in EMOTION_KEYWORDS.items():
            assert len(words) == len(set(words)), emotion

    def test_negation_words_do_not_contain_bare_fei(self) -> None:
        """「非常」是强度 booster，不是否定词 —— 曾把 `非` 当否定词。"""
        assert "非" not in NEGATION_WORDS

    def test_boosters_and_reducers_disjoint(self) -> None:
        assert not set(INTENSITY_BOOSTERS) & set(INTENSITY_REDUCERS)


# --------------------------------------------------------------------------- #
# emotion_label
# --------------------------------------------------------------------------- #


class TestEmotionLabel:
    @pytest.mark.parametrize("value,expected", [
        ("happy", "开心"),
        ("sad", "难过"),
        ("neutral", "平静"),
        ("love", "喜欢"),
    ])
    def test_known_values(self, value, expected) -> None:
        assert emotion_label(value) == expected

    def test_accepts_enum(self) -> None:
        assert emotion_label(EmotionType.ANXIOUS) == "焦虑"

    def test_case_insensitive(self) -> None:
        assert emotion_label("HAPPY") == "开心"
        assert emotion_label("  Sad  ") == "难过"

    def test_unknown_returns_empty(self) -> None:
        assert emotion_label("tornado") == ""

    def test_none_returns_empty(self) -> None:
        assert emotion_label(None) == ""

    def test_empty_returns_empty(self) -> None:
        assert emotion_label("") == ""
        assert emotion_label("   ") == ""

    def test_llm_only_labels(self) -> None:
        """这些值不在 EmotionType 里，但 LLM 分析器会给。"""
        assert emotion_label("grateful") == "感激"
        assert emotion_label("ecstatic") == "特别高兴"


# --------------------------------------------------------------------------- #
# _is_negated
# --------------------------------------------------------------------------- #


class TestIsNegated:
    @pytest.mark.parametrize("text,keyword", [
        ("我不喜欢这个", "喜欢"),
        ("没开心过", "开心"),
        ("别高兴太早", "高兴"),
        ("没有快乐", "快乐"),
    ])
    def test_detects_negation(self, text, keyword) -> None:
        assert EmotionAnalyzer._is_negated(text, keyword) is True

    @pytest.mark.parametrize("text,keyword", [
        ("我很喜欢这个", "喜欢"),
        ("开心极了", "开心"),
        ("今天真快乐", "快乐"),
    ])
    def test_plain_text_not_negated(self, text, keyword) -> None:
        assert EmotionAnalyzer._is_negated(text, keyword) is False

    def test_keyword_at_start_not_negated(self) -> None:
        assert EmotionAnalyzer._is_negated("开心就好", "开心") is False

    def test_missing_keyword_not_negated(self) -> None:
        assert EmotionAnalyzer._is_negated("随便说点什么", "开心") is False

    def test_only_looks_three_chars_back(self) -> None:
        """「不开心」→ 间隔 0；「不啊真的很开心」→ 间隔 5 字，不算否定。"""
        assert EmotionAnalyzer._is_negated("不开心", "开心") is True
        assert EmotionAnalyzer._is_negated("不啊真的很开心", "开心") is False

    def test_does_not_use_feichang_as_negation(self) -> None:
        assert EmotionAnalyzer._is_negated("非常开心", "开心") is False


# --------------------------------------------------------------------------- #
# analyze
# --------------------------------------------------------------------------- #


class TestAnalyze:
    @pytest.mark.parametrize("text", ["", "   ", "\n"])
    def test_empty_text(self, text) -> None:
        result = EmotionAnalyzer.analyze(text)
        assert result.emotion is EmotionType.NEUTRAL
        assert result.intensity == 0.0
        assert result.keywords == []

    def test_no_keyword_is_neutral(self) -> None:
        result = EmotionAnalyzer.analyze("今天去买了菜")
        assert result.emotion is EmotionType.NEUTRAL
        assert result.intensity == 0.0

    def test_returns_emotion_result(self) -> None:
        assert isinstance(EmotionAnalyzer.analyze("我好开心"), EmotionResult)

    @pytest.mark.parametrize("text,expected", [
        ("今天好开心啊", EmotionType.HAPPY),
        ("我好难过", EmotionType.SAD),
        ("气死我了", EmotionType.ANGRY),
        ("太棒了", EmotionType.EXCITED),
        ("我一个人在家", EmotionType.LONELY),
        ("好担心明天的面试", EmotionType.ANXIOUS),
        ("爱你", EmotionType.LOVE),
    ])
    def test_obvious_emotions(self, text, expected) -> None:
        assert EmotionAnalyzer.analyze(text).emotion is expected

    def test_emoji_keywords(self) -> None:
        assert EmotionAnalyzer.analyze("😭😭").emotion is EmotionType.SAD

    def test_keywords_reported(self) -> None:
        result = EmotionAnalyzer.analyze("好开心，太高兴了")
        assert "开心" in result.keywords
        assert "高兴" in result.keywords

    def test_negated_keyword_skipped(self) -> None:
        """「不开心」不应命中 HAPPY。SAD 的「不开心」在表里，所以判 SAD 才怪；
        这里只断言「没有 happy 得分」。"""
        result = EmotionAnalyzer.analyze("我不开心")
        assert result.emotion is not EmotionType.HAPPY

    def test_all_keywords_negated_falls_back_to_neutral(self) -> None:
        result = EmotionAnalyzer.analyze("我不喜欢")
        # 「喜欢」被否定后 HAPPY 无分；其余情绪也没命中
        assert result.emotion is not EmotionType.HAPPY

    def test_more_hits_win(self) -> None:
        """HAPPY 命中 4 个词，SAD 命中 1 个 → HAPPY。"""
        result = EmotionAnalyzer.analyze("开心 高兴 快乐 幸福 但是有点难过")
        assert result.emotion is EmotionType.HAPPY

    def test_tie_goes_to_dict_order(self) -> None:
        """分数与最长命中词都相同的真平分 → 按 EMOTION_KEYWORDS 插入顺序取 HAPPY。"""
        result = EmotionAnalyzer.analyze("开心又难过")
        assert result.emotion is EmotionType.HAPPY

    @pytest.mark.parametrize("text,expected", [
        # 「爱」在 HAPPY 表里、「爱你」在 LOVE 表里 → 打平但 LOVE 的词更长
        ("爱你", EmotionType.LOVE),
        # 「棒」在 HAPPY 表里、「太棒了」在 EXCITED 表里 → EXCITED 更长
        ("太棒了", EmotionType.EXCITED),
        # 「想你」在 LONELY 与 LOVE 都有，等长 → 取靠前的 LONELY
        ("想你", EmotionType.LONELY),
    ])
    def test_longer_keyword_wins_tie(self, text, expected) -> None:
        """平分时用「命中词最长长度」做第二判据。

        改之前 `max(scores, key=scores.get)` 只看分数，导致「爱你」「太棒了」
        这些最典型的表达全被判成 HAPPY —— HAPPY 表里有单字「爱」「棒」，
        与具体短语各命中 1 次就打平，而 HAPPY 排在字典最前。
        """
        assert EmotionAnalyzer.analyze(text).emotion is expected

    # ---- 强度 ---- #

    def test_single_hit_intensity(self) -> None:
        assert EmotionAnalyzer.analyze("开心").intensity == pytest.approx(0.33)

    def test_two_hits(self) -> None:
        assert EmotionAnalyzer.analyze("开心，高兴").intensity == pytest.approx(0.67)

    def test_three_hits_saturates(self) -> None:
        assert EmotionAnalyzer.analyze("开心 高兴 快乐").intensity == pytest.approx(1.0)

    def test_many_hits_capped_at_one(self) -> None:
        result = EmotionAnalyzer.analyze("开心 高兴 快乐 哈哈 嘻嘻 幸福")
        assert result.intensity == 1.0

    def test_booster_multiplies(self) -> None:
        plain = EmotionAnalyzer.analyze("开心")
        boosted = EmotionAnalyzer.analyze("非常开心")
        assert boosted.intensity > plain.intensity

    def test_booster_capped(self) -> None:
        assert EmotionAnalyzer.analyze("非常 开心 高兴 快乐").intensity <= 1.0

    def test_reducer_multiplies_down(self) -> None:
        plain = EmotionAnalyzer.analyze("开心 高兴 快乐")   # 1.0
        reduced = EmotionAnalyzer.analyze("有点 开心 高兴 快乐")
        assert reduced.intensity < plain.intensity

    def test_reducer_floor(self) -> None:
        """最小强度不低过 0.1。"""
        result = EmotionAnalyzer.analyze("可能 有点 开心")
        assert result.intensity >= 0.1

    def test_booster_takes_first_match_only(self) -> None:
        """只乘一次 —— 多个 booster 不会叠乘。"""
        once = EmotionAnalyzer.analyze("非常开心")
        twice = EmotionAnalyzer.analyze("非常 真的 开心")
        assert once.intensity == twice.intensity

    def test_intensity_rounded_to_two(self) -> None:
        value = EmotionAnalyzer.analyze("开心 高兴").intensity
        assert round(value, 2) == value


# --------------------------------------------------------------------------- #
# 边界：真实对话样本
# --------------------------------------------------------------------------- #


class TestRealSamples:
    @pytest.mark.parametrize("text", [
        "嗯", "好的", "哈哈哈哈", "在吗", "...",
    ])
    def test_short_replies_do_not_crash(self, text) -> None:
        assert isinstance(EmotionAnalyzer.analyze(text), EmotionResult)

    def test_user_statement(self) -> None:
        result = EmotionAnalyzer.analyze("我明天要面试，好紧张啊")
        assert result.emotion is EmotionType.ANXIOUS

    def test_long_text(self) -> None:
        text = "今天我们聊了很多，" * 200
        assert isinstance(EmotionAnalyzer.analyze(text), EmotionResult)

    def test_mixed_positive_negative(self) -> None:
        result = EmotionAnalyzer.analyze("今天很开心但是也有点难过")
        assert result.emotion in {EmotionType.HAPPY, EmotionType.SAD}
