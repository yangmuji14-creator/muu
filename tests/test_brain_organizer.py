"""ThoughtOrganizer：人格念头文案与合并规则的单元测试。

这是 core/brain 的第一个测试文件（此前整个包零覆盖）。重点锁 2026-11-01
改过的两类契约：

1. 人格念头的**宾语视角**——五句全是「我很信任他」式的主语他指，
   已改成「我现在愿意跟他说真话」式的自我视角后果。
2. **合并规则**——五个维度合并成一条 personality 念头。
"""

from __future__ import annotations

from core.brain.models import BrainInput
from core.brain.organizer import ThoughtOrganizer


def _organizer() -> ThoughtOrganizer:
    return ThoughtOrganizer(max_tokens=1000)


def _personality_thoughts(bi: BrainInput):
    return [
        t for t in _organizer().organize(bi)
        if t.source == "personality"
    ]


class TestDispositionCopy:
    """人格念头必须从「她的视角说后果」，不是给「他」贴态度标签。"""

    def test_high_trust_uses_self_perspective(self) -> None:
        thoughts = _personality_thoughts(BrainInput(personality_trust=0.8))
        assert len(thoughts) == 1
        assert "愿意跟他说真话" in thoughts[0].content
        assert "我很信任他" not in thoughts[0].content

    def test_high_jealousy_mentions_the_reaction_not_label(self) -> None:
        thoughts = _personality_thoughts(BrainInput(personality_jealousy=0.8))
        assert "不想说话" in thoughts[0].content

    def test_low_dimensions_produce_no_personality_thought(self) -> None:
        """0.6 以下全部静默——人格不该在什么都没发生时也要说两句。"""
        thoughts = _personality_thoughts(BrainInput(
            personality_trust=0.3, personality_jealousy=0.2,
            personality_dependence=0.1, personality_openness=0.4,
            personality_affection=0.5,
        ))
        assert thoughts == []

    def test_five_dimensions_merge_into_one_thought(self) -> None:
        thoughts = _personality_thoughts(BrainInput(
            personality_trust=0.9, personality_jealousy=0.7,
            personality_dependence=0.8, personality_openness=0.9,
            personality_affection=0.9,
        ))
        assert len(thoughts) == 1
        assert thoughts[0].priority == 0.4
        assert thoughts[0].category == "concern"
        # 五句全在：顿号分隔
        for fragment in ("真话", "不想说话", "离不开", "第一个想告诉", "松弛"):
            assert fragment in thoughts[0].content


class TestAffectionThought:
    def test_high_level_closer(self) -> None:
        thoughts = [
            t for t in _organizer().organize(BrainInput(affection_level=80))
            if t.source == "affection"
        ]
        assert len(thoughts) == 1
        assert "越来越亲近" in thoughts[0].content

    def test_low_level_not_familiar(self) -> None:
        thoughts = [
            t for t in _organizer().organize(BrainInput(affection_level=10))
            if t.source == "affection"
        ]
        assert "不太熟" in thoughts[0].content


class TestOrganizeBaseline:
    def test_empty_input_still_has_default_thought(self) -> None:
        """全空输入至少有一条默认念头——独白不能没内容。"""
        thoughts = _organizer().organize(BrainInput())
        assert thoughts

    def test_mood_high_valence_low_arousal(self) -> None:
        thoughts = [
            t for t in _organizer().organize(
                BrainInput(mood_valence=0.8, mood_arousal=0.2)
            )
            if t.source == "mood"
        ]
        assert any("放松" in t.content for t in thoughts)
