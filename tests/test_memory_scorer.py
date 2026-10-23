"""记忆重要度规则评分测试

覆盖 `core/memory/scorer.py` 的 `MemoryScorer`（规则层）与 `LLMMemoryScorer`
（只测「没有 LLM 时安全返回 None」与「坏 JSON 不抛」这两条边界，真调模型的
部分不在单测里跑）。

这个文件的用例大多是从**真实翻车现场**反推的：规则评分器曾经给
「你是不是在演我啊」打 2 分、给「我养了一只猫叫团子」「我今年24岁」打 1 分，
逻辑正好是反的 —— 结果规则兜底只会往记忆库里塞用户的原话问句。
下面的 `TestIdentity` / `TestPreference` 就是这个回归点。
"""

from __future__ import annotations

import pytest

from core.memory.scorer import (
    HIGH_IMPORTANCE_PATTERNS,
    KEYWORD_WEIGHTS,
    LOW_IMPORTANCE_PATTERNS,
    SCORE_TO_LEVEL,
    LLMMemoryScorer,
    MemoryScorer,
)


class TestPatternIntegrity:
    """防止正则表被改坏 —— 这类错误不会抛异常，只会静默不匹配。"""

    def test_all_high_patterns_compile(self):
        for pattern, weight in HIGH_IMPORTANCE_PATTERNS:
            import re
            re.compile(pattern)  # 编不过会直接抛 re.error
            assert isinstance(weight, int) and weight > 0, pattern

    def test_all_low_patterns_compile(self):
        import re
        for pattern in LOW_IMPORTANCE_PATTERNS:
            re.compile(pattern)

    def test_no_double_escaped_classes(self):
        # 曾经把 r"\s" 写成 "\\s"，在正则里表示「一个字面反斜杠 + 字母 s」，
        # 永远匹配不上，而且不报错。这条守着别复发。
        for pattern, _ in HIGH_IMPORTANCE_PATTERNS:
            assert "\\\\" not in pattern, f"{pattern} 里有双重转义"

    def test_score_to_level_is_descending_and_covers_5(self):
        thresholds = [t for t, _ in SCORE_TO_LEVEL]
        assert thresholds == sorted(thresholds, reverse=True)
        assert SCORE_TO_LEVEL[0][1] == 5
        # 最后的兜底是 level 1（score 达不到任何阈值时）
        assert SCORE_TO_LEVEL[-1][0] <= 2


class TestTrivialInput:
    @pytest.mark.parametrize("text", ["", "   ", "嗯", "ab", "a", " 哦 "])
    def test_too_short_is_level_1_with_high_confidence(self, text):
        level, conf = MemoryScorer.score(text)
        assert level == 1
        assert conf == 0.9

    @pytest.mark.parametrize("text", [
        "嗯", "哦", "好的", "好吧", "哈哈", "嘻嘻", "嘿嘿", "呵呵",
        "hi", "hello", "嗨", "早", "晚安", "拜拜", "再见",
    ])
    def test_greetings_are_level_1(self, text):
        assert MemoryScorer.score(text)[0] == 1

    @pytest.mark.parametrize("text", ["是的", "不是", "对", "对的", "没错", "嗯嗯", "行", "可以"])
    def test_fillers_are_level_1(self, text):
        assert MemoryScorer.score(text)[0] == 1

    @pytest.mark.parametrize("text", ["谢谢", "感谢", "不客气", "没事", "没关系"])
    def test_politeness_is_level_1(self, text):
        assert MemoryScorer.score(text)[0] == 1

    def test_greeting_match_is_case_insensitive(self):
        assert MemoryScorer.score("HELLO")[0] == 1


class TestIdentity:
    """「我叫张三」「我今年24岁」这类必须是高等级 —— 原来它们都是 level 1。"""

    @pytest.mark.parametrize("text", ["我叫张三", "我叫张三。", "我是程序员", "我是李雷！"])
    def test_name_and_role_score_5(self, text):
        assert MemoryScorer.score(text)[0] == 5

    def test_birthday_scores_5(self):
        assert MemoryScorer.score("我的生日是3月5日")[0] == 5

    def test_combined_identity_sentence_scores_5(self):
        level, conf = MemoryScorer.score("我叫李雷，今年24岁，住在成都")
        assert level == 5
        assert conf >= 0.7

    @pytest.mark.parametrize("text", ["我今年24岁", "我住在成都", "我养了一只猫叫团子"])
    def test_important_facts_score_at_least_4(self, text):
        assert MemoryScorer.score(text)[0] == 4

    def test_pet_is_not_mistaken_for_identity(self):
        # 「我养了一只猫叫团子」里有「猫叫团子」，旧的非锚定正则会把它
        # 当成「我叫xxx」抬到 level 5 —— 宠物是重要信息，但最高只该到 4。
        assert MemoryScorer.score("我养了一只猫叫团子")[0] == 4

    @pytest.mark.parametrize("text", ["我是真的难过", "我是很累", "我是不是该走了"])
    def test_emotional_sentences_are_not_identity(self, text):
        # 「我是 + 情绪」不是身份声明，负向断言要挡住。
        assert MemoryScorer.score(text)[0] < 5


class TestPreference:
    @pytest.mark.parametrize("text", ["我喜欢吃火锅", "我讨厌下雨天", "我明年毕业", "我在腾讯工作"])
    def test_general_preferences_clear_the_threshold(self, text):
        # 关键契约：这些必须 >= 2，否则 `_add_memory_impl` 会直接丢弃。
        # 当时它们全是 level 1，等于规则兜底永远写不进任何一条记忆。
        level, _ = MemoryScorer.score(text)
        assert level >= 2, f"{text} 应该是值得记住的"
        assert MemoryScorer.should_remember(text) is True

    def test_intensified_preference_is_level_3(self):
        assert MemoryScorer.score("我特别喜欢吃冰美式")[0] == 3


class TestNotWorthRemembering:
    @pytest.mark.parametrize("text", [
        "你是不是在演我啊", "今天天气不错", "我最近很焦虑", "随便吧", "在吗",
    ])
    def test_chatter_is_level_1(self, text):
        assert MemoryScorer.score(text)[0] == 1

    def test_chatter_asks_for_llm_second_opinion(self):
        # 低置信度的内容应该被标成「建议 LLM 复核」，而不是直接采信规则。
        assert MemoryScorer.needs_llm_evaluation("今天天气不错") is True


class TestConfidence:
    def test_more_signals_means_higher_confidence(self):
        _, low = MemoryScorer.score("我喜欢吃火锅")
        _, high = MemoryScorer.score("我叫李雷，今年24岁，住在成都")
        assert high > low

    def test_confidence_always_in_range(self):
        for text in ["", "嗯", "我叫张三", "我叫李雷，今年24岁，住在成都，生日是3月5日"]:
            assert 0.0 <= MemoryScorer.score(text)[1] <= 1.0


class TestShouldRemember:
    def test_default_threshold_is_2(self):
        assert MemoryScorer.should_remember("我叫张三") is True
        assert MemoryScorer.should_remember("嗯") is False

    def test_custom_threshold(self):
        # level 2 的内容在 threshold=3 时不该入库
        assert MemoryScorer.should_remember("我喜欢吃火锅", threshold=3) is False
        assert MemoryScorer.should_remember("我叫张三", threshold=3) is True


class TestNeedsLlmEvaluation:
    def test_high_score_high_confidence_skips_llm(self):
        assert MemoryScorer.needs_llm_evaluation("我的生日是3月5日") is False

    def test_low_score_high_confidence_skips_llm(self):
        assert MemoryScorer.needs_llm_evaluation("嗯") is False

    def test_borderline_level_2_asks_for_llm(self):
        assert MemoryScorer.needs_llm_evaluation("我喜欢吃火锅") is True

    def test_result_is_always_bool(self):
        for text in ["", "嗯", "我叫张三", "我喜欢吃火锅", "今天天气不错"]:
            assert isinstance(MemoryScorer.needs_llm_evaluation(text), bool)


class TestKeywordWeights:
    def test_weights_are_positive_ints(self):
        for keyword, weight in KEYWORD_WEIGHTS.items():
            assert isinstance(keyword, str) and keyword
            assert isinstance(weight, int) and weight > 0

    def test_core_personal_info_weighs_the_most(self):
        for key in ("生日", "名字", "年龄", "地址", "电话", "学校", "公司"):
            assert KEYWORD_WEIGHTS[key] == 3


class TestLLMMemoryScorer:
    def test_without_llm_returns_none(self):
        assert LLMMemoryScorer().evaluate  # 存在即可，异步调用在下面

    async def test_evaluate_without_llm_returns_none(self):
        assert await LLMMemoryScorer(None).evaluate("我叫张三") is None

    async def test_evaluate_swallows_llm_exception(self):
        class Boom:
            async def chat(self, **kwargs):
                raise RuntimeError("上游挂了")

        assert await LLMMemoryScorer(Boom()).evaluate("我叫张三") is None

    async def test_evaluate_parses_valid_response(self):
        class Fake:
            async def chat(self, **kwargs):
                class R:
                    content = '{"importance": 4, "category": "personal", "reason": "身份"}'
                return R()

        assert await LLMMemoryScorer(Fake()).evaluate("我叫张三") == (4, "personal")

    async def test_evaluate_clamps_importance_into_range(self):
        class Fake:
            async def chat(self, **kwargs):
                class R:
                    content = '{"importance": 99, "category": "other"}'
                return R()

        result = await LLMMemoryScorer(Fake()).evaluate("随便什么")
        assert result == (5, "other")

    async def test_evaluate_returns_none_on_bad_json(self):
        class Fake:
            async def chat(self, **kwargs):
                class R:
                    content = "我觉得这个挺重要的"
                return R()

        assert await LLMMemoryScorer(Fake()).evaluate("随便什么") is None
