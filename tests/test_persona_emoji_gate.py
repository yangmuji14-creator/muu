"""人设是否允许后处理追加表情（pipeline._persona_allows_emoji）。

背景：girlfriend_001 的 speaking_style 明确写着「说话自然简短，不用颜文字」
和「不用颜文字和撒娇腔」，但 `EmotionEnhancer.enhance_reply` 是无条件执行的
后处理 —— 只要她不是 neutral，每条回复末尾都会多一个颜文字。
人设与输出在这一处直接打架，而且打架的那一方是硬编码的。
"""

from __future__ import annotations

import pytest

from core.chat.pipeline import _persona_allows_emoji


class _Persona:
    def __init__(self, **kwargs):
        self.speaking_style = kwargs.pop("speaking_style", {})
        self.emoji_habits = kwargs.pop("emoji_habits", "")
        for key, value in kwargs.items():
            setattr(self, key, value)


class TestExplicitField:
    """显式字段优先，这是用户可声明的开关。"""

    def test_false_disables(self) -> None:
        assert _persona_allows_emoji(_Persona(emoji_enabled=False)) is False

    def test_true_enables_even_with_forbidding_text(self) -> None:
        """显式允许压过文本推断 —— 不让启发式赢过用户的明确选择。"""
        persona = _Persona(
            emoji_enabled=True,
            speaking_style={"基础风格": "不用颜文字"},
        )
        assert _persona_allows_emoji(persona) is True

    def test_none_falls_back_to_text(self) -> None:
        persona = _Persona(
            emoji_enabled=None,
            speaking_style={"基础风格": "说话自然简短，不用颜文字"},
        )
        assert _persona_allows_emoji(persona) is False


class TestTextFallback:
    """旧配置兼容：读用户亲手写下的人设约束。"""

    @pytest.mark.parametrize("style_text", [
        "说话自然简短，不用颜文字，不刻意卖萌",
        "不用 emoji",
        "不加表情",
        "不用表情包以外的表情",
    ])
    def test_forbidding_text_disables(self, style_text) -> None:
        assert _persona_allows_emoji(
            _Persona(speaking_style={"基础风格": style_text}),
        ) is False

    def test_emoji_habits_field_is_also_read(self) -> None:
        assert _persona_allows_emoji(
            _Persona(emoji_habits="偶尔发表情，不用颜文字"),
        ) is False

    def test_legacy_string_speaking_style(self) -> None:
        assert _persona_allows_emoji(
            _Persona(speaking_style="简短自然，不用颜文字"),
        ) is False

    def test_neutral_text_allows(self) -> None:
        assert _persona_allows_emoji(
            _Persona(speaking_style={"基础风格": "简短自然，喜欢用表情"}),
        ) is True

    def test_empty_persona_allows(self) -> None:
        assert _persona_allows_emoji(_Persona()) is True

    def test_none_persona_allows(self) -> None:
        """没有 persona 时不能把回复弄崩，也不能凭空禁用表情。"""
        assert _persona_allows_emoji(None) is True
