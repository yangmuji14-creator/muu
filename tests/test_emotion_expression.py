"""`core/emotion/expression.py` 的测试

三块互不依赖的能力：
1. `MessageSegmenter` —— 长回复切成多条短消息（真人打字感）
2. `EmotionEnhancer` —— 按情绪给回复尾巴挂个 emoji + 模拟打字延迟
3. `MoodExpressionEngine` —— 把 `MoodState` 翻成注入 system prompt 的风格指令

⚠️ 关键契约（改之前先读）：
- `segment()` 在 `len(text) <= max_segment_length` 时**原样返回**（连 strip 都不做），
  只有超长才走断句逻辑。
- `segment("")` 返回 `SegmentedMessage(segments=[""], total_segments=1)` —— 空串也在列表里。
- `_force_split` 的标点断点计算是 `cut_pos = i + 1`，所以带标点的那段会**超出
  max_length 一个字符**（`'abcde，'` 长度 6 而 max 是 5）。这是既有行为，改成
  `cut_pos = i` 会把标点推到下一段开头，聊天断句观感变差 —— 先按现状钉住。
- `enhance_reply` 的 mood 路径与 emotion 路径**判重方式不同**：mood 先看
  `intensity < 0.2` 早退，再 `>= 0.3` 才挂；emotion 路径先查 emoji 池再看 intensity。
- `get_energy_bar` 不 clamp 负数：`energy=-0.2` 会得到 12 个 `░`，不是 10 个。
"""

from __future__ import annotations

import random

import pytest

from core.emotion.analyzer import EmotionResult, EmotionType
from core.emotion.expression import (
    EMOTION_EMOJI_MAP,
    EmotionEnhancer,
    MessageSegmenter,
    MoodExpressionEngine,
)
from core.emotion.mood import MOOD_BEHAVIOR, MoodState, MoodType


def _result(kind: EmotionType, intensity: float = 0.8) -> EmotionResult:
    return EmotionResult(emotion=kind, intensity=intensity, keywords=[])


@pytest.fixture()
def fixed_choice(monkeypatch):
    """固定随机源，让 emoji 断言可复现：
    `choice` 取第一个，`random()` 恒 0.0（因此总是通过装饰概率闸）。"""
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])
    monkeypatch.setattr(random, "random", lambda: 0.0)


# --------------------------------------------------------------------------- #
# MessageSegmenter
# --------------------------------------------------------------------------- #


class TestSegmentShort:
    def test_empty_text_kept_as_single_empty_segment(self) -> None:
        result = MessageSegmenter.segment("")
        assert result.segments == [""]
        assert result.total_segments == 1

    def test_short_text_returned_verbatim(self) -> None:
        """短消息不做 strip —— 原文什么样就什么样。"""
        result = MessageSegmenter.segment("  你好  ")
        assert result.segments == ["  你好  "]

    def test_exactly_at_limit_is_not_split(self) -> None:
        text = "一" * 50
        assert MessageSegmenter.segment(text, 50).segments == [text]

    def test_none_like_empty(self) -> None:
        assert MessageSegmenter.segment(None).segments == [None]  # type: ignore[arg-type]

    def test_total_segments_matches_len(self) -> None:
        result = MessageSegmenter.segment("短")
        assert result.total_segments == len(result.segments)


class TestSegmentLong:
    def test_splits_on_period(self) -> None:
        text = "第一句。" * 20
        result = MessageSegmenter.segment(text, 20)
        assert result.total_segments > 1
        assert all("第一句" in s for s in result.segments)

    def test_no_segment_exceeds_limit_unless_punctuation(self) -> None:
        text = "今天天气很好我们出去走走吧顺便买点菜回来做饭" * 3
        result = MessageSegmenter.segment(text, 20)
        for seg in result.segments:
            assert len(seg) <= 21  # +1 是标点跟着上一段走的既有偏差

    def test_strips_segments(self) -> None:
        text = "  第一句。   第二句。"
        result = MessageSegmenter.segment(text * 10, 15)
        for seg in result.segments:
            assert seg == seg.strip()

    def test_empty_segments_dropped(self) -> None:
        result = MessageSegmenter.segment("A。" * 40, 10)
        assert all(s for s in result.segments)

    @pytest.mark.parametrize("punct", ["。", "！", "？", "…", "\n", ".", "!", "?"])
    def test_all_punctuation_splits(self, punct) -> None:
        text = f"内容{punct}" * 30
        assert MessageSegmenter.segment(text, 20).total_segments > 1

    def test_merges_short_segments(self) -> None:
        """「好。」这种两字短句要攒起来，不能一句一条消息。"""
        text = "好。" * 30
        result = MessageSegmenter.segment(text, 20)
        assert result.total_segments < 30

    def test_buffer_does_not_exceed_limit(self) -> None:
        text = "短。" * 40
        result = MessageSegmenter.segment(text, 10)
        for seg in result.segments:
            assert len(seg) <= 10

    def test_long_run_without_punctuation_force_split(self) -> None:
        text = "一" * 100
        result = MessageSegmenter.segment(text, 20)
        assert result.total_segments == 5
        assert all(len(s) == 20 for s in result.segments)

    def test_force_split_flushes_pending_buffer(self) -> None:
        """短 buffer 后面紧跟超长段落时，buffer 要先收口，不能把长段挤成一坨。"""
        text = "短句。" + "一" * 60
        result = MessageSegmenter.segment(text, 20)
        assert result.segments[0] == "短句。"
        assert all(len(s) <= 20 for s in result.segments[1:])


class TestForceSplit:
    def test_no_split_when_short(self) -> None:
        assert MessageSegmenter._force_split("abc", 10) == ["abc"]

    def test_chunks_evenly_without_punctuation(self) -> None:
        assert MessageSegmenter._force_split("一" * 25, 10) == ["一" * 10, "一" * 10, "一" * 5]

    def test_prefers_punctuation_break(self) -> None:
        chunks = MessageSegmenter._force_split("abcdefg，hijklmnop", 10)
        assert chunks[0].endswith("，")

    def test_punctuation_break_overflows_by_one(self) -> None:
        """既有偏差：`cut_pos = i + 1` 让标点跟着上一段走，段长 +1。"""
        chunks = MessageSegmenter._force_split("abcde，fghij", 5)
        assert chunks[0] == "abcde，"
        assert len(chunks[0]) == 6

    def test_strips_chunks(self) -> None:
        chunks = MessageSegmenter._force_split("一" * 10 + "    " + "二" * 10, 10)
        for chunk in chunks:
            assert chunk == chunk.strip()

    def test_empty_input(self) -> None:
        assert MessageSegmenter._force_split("", 10) == []


# --------------------------------------------------------------------------- #
# EmotionEnhancer.enhance_reply —— EmotionResult 路径
# --------------------------------------------------------------------------- #


class TestEnhanceFromEmotion:
    def test_none_returns_reply(self, fixed_choice) -> None:
        assert EmotionEnhancer.enhance_reply("你好") == "你好"

    def test_neutral_returns_reply(self, fixed_choice) -> None:
        assert EmotionEnhancer.enhance_reply("你好", _result(EmotionType.NEUTRAL)) == "你好"

    def test_low_intensity_returns_reply(self, fixed_choice) -> None:
        assert EmotionEnhancer.enhance_reply("你好", _result(EmotionType.HAPPY, 0.2)) == "你好"

    def test_appends_emoji(self, fixed_choice) -> None:
        out = EmotionEnhancer.enhance_reply("你好", _result(EmotionType.HAPPY, 0.8))
        assert out == f"你好 {EMOTION_EMOJI_MAP[EmotionType.HAPPY][0]}"

    def test_skips_if_any_pool_emoji_present(self, fixed_choice) -> None:
        """池子里任一 emoji 已在正文里就不再挂 —— 否则尾巴会出现两个。"""
        emoji = EMOTION_EMOJI_MAP[EmotionType.HAPPY][3]
        reply = f"你好{emoji}"
        assert EmotionEnhancer.enhance_reply(reply, _result(EmotionType.HAPPY, 0.8)) == reply

    def test_exactly_at_threshold_appends(self, fixed_choice) -> None:
        out = EmotionEnhancer.enhance_reply("你好", _result(EmotionType.HAPPY, 0.3))
        assert out.startswith("你好 ")

    @pytest.mark.parametrize("kind", [
        EmotionType.HAPPY, EmotionType.SAD, EmotionType.ANGRY,
        EmotionType.EXCITED, EmotionType.LONELY, EmotionType.ANXIOUS,
        EmotionType.LOVE,
    ])
    def test_every_emotion_has_pool(self, fixed_choice, kind) -> None:
        assert EmotionEnhancer.enhance_reply("嗯", _result(kind, 1.0)) != "嗯"

    def test_emotion_without_pool_returns_reply(self, fixed_choice) -> None:
        """池子为空的兜底。正常路径进不来（NEUTRAL 早退、其余七种都有池子），
        但 `EMOTION_EMOJI_MAP.get(...)` 用的是 `.get`，将来加新的
        EmotionType 却忘了配 emoji 时会走到这里 —— 返回原文而不是 KeyError。"""
        class Weird(str):
            pass

        weird = EmotionResult(emotion=Weird("weird"), intensity=0.9, keywords=[])
        assert EmotionEnhancer.enhance_reply("嗯", weird) == "嗯"


# --------------------------------------------------------------------------- #
# EmotionEnhancer.enhance_reply —— MoodState 路径
# --------------------------------------------------------------------------- #


class TestEnhanceFromMood:
    def test_mood_takes_priority_over_emotion(self, fixed_choice) -> None:
        """mood 是 AI 自己的情绪，比单轮检测稳定 —— 两者都给时用 mood。"""
        mood = MoodState(mood=MoodType.LOVE, valence=0.9, arousal=0.5, intensity=0.9)
        out = EmotionEnhancer.enhance_reply(
            "你好", _result(EmotionType.SAD, 0.9), mood,
        )
        assert EMOTION_EMOJI_MAP[EmotionType.LOVE][0] in out

    def test_low_mood_intensity_returns_reply(self, fixed_choice) -> None:
        mood = MoodState(mood=MoodType.HAPPY, intensity=0.1)
        assert EmotionEnhancer.enhance_reply("你好", mood_state=mood) == "你好"

    def test_between_thresholds_returns_reply(self, fixed_choice) -> None:
        """`0.2 <= intensity < 0.3` 是空档：过了早退但不够挂 emoji。"""
        mood = MoodState(mood=MoodType.HAPPY, intensity=0.25)
        assert EmotionEnhancer.enhance_reply("你好", mood_state=mood) == "你好"

    def test_mood_appends_emoji(self, fixed_choice) -> None:
        mood = MoodState(mood=MoodType.HAPPY, intensity=0.5)
        out = EmotionEnhancer.enhance_reply("你好", mood_state=mood)
        assert out == f"你好 {EMOTION_EMOJI_MAP[EmotionType.HAPPY][0]}"

    def test_neutral_mood_pool_empty_returns_reply(self, fixed_choice) -> None:
        """NEUTRAL 映射到 EmotionType.NEUTRAL，池子是空的 → 原样返回。"""
        mood = MoodState(mood=MoodType.NEUTRAL, intensity=0.9)
        assert EmotionEnhancer.enhance_reply("你好", mood_state=mood) == "你好"

    @pytest.mark.parametrize("mood_type,expected_emotion", [
        (MoodType.ECSTATIC, EmotionType.HAPPY),
        (MoodType.TIRED, EmotionType.SAD),
        (MoodType.DEPRESSED, EmotionType.SAD),
        (MoodType.FRUSTRATED, EmotionType.ANGRY),
        (MoodType.GRATEFUL, EmotionType.HAPPY),
        (MoodType.EXCITED, EmotionType.EXCITED),
    ])
    def test_mood_to_emotion_mapping(self, fixed_choice, mood_type, expected_emotion) -> None:
        mood = MoodState(mood=mood_type, intensity=0.9)
        out = EmotionEnhancer.enhance_reply("嗯", mood_state=mood)
        assert out == f"嗯 {EMOTION_EMOJI_MAP[expected_emotion][0]}"

    def test_skips_if_pool_emoji_present(self, fixed_choice) -> None:
        emoji = EMOTION_EMOJI_MAP[EmotionType.LOVE][1]
        mood = MoodState(mood=MoodType.LOVE, intensity=0.9)
        reply = f"想你{emoji}"
        assert EmotionEnhancer.enhance_reply(reply, mood_state=mood) == reply


# --------------------------------------------------------------------------- #
# 打字延迟
# --------------------------------------------------------------------------- #


class TestTypingDelay:
    def test_first_segment_longer(self, monkeypatch) -> None:
        monkeypatch.setattr(random, "uniform", lambda a, b: (a + b) / 2)
        first = EmotionEnhancer.get_typing_delay(0, 3)
        assert 1.5 <= first <= 3.0

    def test_last_segment_zero(self) -> None:
        assert EmotionEnhancer.get_typing_delay(2, 3) == 0

    def test_first_segment_wins_over_last(self) -> None:
        """`if segment_index == 0` 在前，所以「只有一段」走的是首段延迟，
        不是末尾的 0 —— 单段消息也要等 1.5~3s 模拟思考。"""
        assert 1.5 <= EmotionEnhancer.get_typing_delay(0, 1) <= 3.0

    def test_middle_segment_range(self, monkeypatch) -> None:
        monkeypatch.setattr(random, "uniform", lambda a, b: b)
        middle = EmotionEnhancer.get_typing_delay(1, 3)
        assert middle == 2.5


# --------------------------------------------------------------------------- #
# MoodExpressionEngine
# --------------------------------------------------------------------------- #


class TestVerbosityRule:
    @pytest.mark.parametrize("energy,expected", [
        (0.1, "1-2 句"),
        (0.3, "2 句"),
        (0.5, "1-3 句"),
        (0.7, "2-4 句"),
        (0.9, "活泼热情"),
    ])
    def test_buckets(self, energy, expected) -> None:
        assert expected in MoodExpressionEngine._verbosity_rule(energy)

    @pytest.mark.parametrize("energy", [0.0, 0.24, 0.25, 0.39, 0.4, 0.59, 0.6, 0.79, 0.8, 1.0])
    def test_boundaries_do_not_crash(self, energy) -> None:
        assert isinstance(MoodExpressionEngine._verbosity_rule(energy), str)


class TestStyleInstructions:
    def test_prefix(self) -> None:
        out = MoodExpressionEngine.get_style_instructions(MoodState())
        assert out.startswith("【当前情绪指导】")

    def test_lines_are_bulleted(self) -> None:
        out = MoodExpressionEngine.get_style_instructions(MoodState())
        body = out.split("\n")[1:]
        assert body and all(line.startswith("- ") for line in body)

    def test_contains_behavior(self) -> None:
        mood = MoodState(mood=MoodType.LOVE, valence=0.9, arousal=0.5, energy=0.5)
        assert MOOD_BEHAVIOR[MoodType.LOVE] in MoodExpressionEngine.get_style_instructions(mood)

    @pytest.mark.parametrize("valence,keyword", [
        (0.5, "温暖积极"),
        (0.0, "自然平和"),
        (-0.5, "偏淡"),
    ])
    def test_valence_branches(self, valence, keyword) -> None:
        out = MoodExpressionEngine.get_style_instructions(MoodState(valence=valence))
        assert keyword in out

    @pytest.mark.parametrize("arousal,keyword", [
        (0.8, "句子活跃"),
        (0.5, "正常节奏"),
        (0.1, "句子偏短"),
    ])
    def test_arousal_branches(self, arousal, keyword) -> None:
        out = MoodExpressionEngine.get_style_instructions(MoodState(arousal=arousal))
        assert keyword in out

    @pytest.mark.parametrize("mood_type", list(MoodType))
    def test_every_mood_produces_instructions(self, mood_type) -> None:
        out = MoodExpressionEngine.get_style_instructions(MoodState(mood=mood_type))
        assert out.count("- ") >= 4

    def test_neutral_has_no_extra_line(self) -> None:
        """NEUTRAL 不在 `mood_specific` 里 → 只有四行基础指令。"""
        out = MoodExpressionEngine.get_style_instructions(MoodState(mood=MoodType.NEUTRAL))
        assert out.count("- ") == 4

    def test_specific_mood_adds_line(self) -> None:
        out = MoodExpressionEngine.get_style_instructions(MoodState(mood=MoodType.ANXIOUS))
        assert out.count("- ") == 5


class TestEnergyBar:
    def test_full(self) -> None:
        assert MoodExpressionEngine.get_energy_bar(1.0) == "█" * 10

    def test_empty(self) -> None:
        assert MoodExpressionEngine.get_energy_bar(0.0) == "░" * 10

    def test_half(self) -> None:
        assert MoodExpressionEngine.get_energy_bar(0.5) == "█" * 5 + "░" * 5

    def test_custom_length(self) -> None:
        assert len(MoodExpressionEngine.get_energy_bar(0.5, 4)) == 4

    def test_negative_overflows(self) -> None:
        """既有行为：不 clamp 负数，`'░' * (10 - (-2))` 变成 12 格。"""
        assert len(MoodExpressionEngine.get_energy_bar(-0.2)) == 12

    def test_over_one_overflows(self) -> None:
        """`'░' * 负` 是空串，所以只有 `█` 那一半溢出。"""
        assert len(MoodExpressionEngine.get_energy_bar(1.5)) == 15


# --------------------------------------------------------------------------- #
# EmotionEnhancer.should_decorate —— 装饰闸门
# --------------------------------------------------------------------------- #


class TestShouldDecorate:
    """表情是唯一可见的情绪出口，所以它的闸门必须可解释、可断言。

    历史行为是「只要不是 neutral 就必挂一个」，难过时也一样 —— 那是最假的地方。
    """

    def test_negative_valence_never_decorates(self, fixed_choice) -> None:
        mood = MoodState(mood=MoodType.SAD, valence=-0.6, arousal=0.2, intensity=0.8)
        assert EmotionEnhancer.should_decorate(mood) is False
        assert EmotionEnhancer.enhance_reply("有点累。", mood_state=mood) == "有点累。"

    def test_positive_valence_may_decorate(self, fixed_choice) -> None:
        mood = MoodState(mood=MoodType.HAPPY, valence=0.7, arousal=0.5, intensity=0.8)
        assert EmotionEnhancer.should_decorate(mood) is True

    def test_low_intensity_never_decorates(self, fixed_choice) -> None:
        mood = MoodState(mood=MoodType.HAPPY, valence=0.7, intensity=0.2)
        assert EmotionEnhancer.should_decorate(mood) is False

    def test_persona_can_disable_entirely(self, fixed_choice) -> None:
        mood = MoodState(mood=MoodType.HAPPY, valence=0.9, intensity=1.0)
        assert EmotionEnhancer.should_decorate(mood, allow_emoji=False) is False
        assert EmotionEnhancer.enhance_reply(
            "你好", mood_state=mood, allow_emoji=False,
        ) == "你好"

    def test_probability_gate_can_skip(self, monkeypatch) -> None:
        """非中性也不该每条都挂：随机闸不过就返回原文。"""
        monkeypatch.setattr(random, "random", lambda: 0.99)
        mood = MoodState(mood=MoodType.HAPPY, valence=0.9, intensity=1.0)
        assert EmotionEnhancer.should_decorate(mood) is False

    def test_none_mood_never_decorates(self) -> None:
        assert EmotionEnhancer.should_decorate(None) is False
