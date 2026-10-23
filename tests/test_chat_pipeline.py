"""对话管线纯函数测试。

覆盖:
- _worth_extracting：语气词/纯数字/空文本不该触发 LLM 记忆提取，
  但短而高情感的消息（"我爱你"）必须能通过
- format_multi_message：单行直通、多行加 [消息N] 前缀
- inject_image_descriptions：注入 image_desc 且剥掉 UI 字段，不修改入参
- _strip_error_mark：错误哨兵的剥离与幂等
"""

import pytest

from core.chat.pipeline import (
    ERROR_REPLY_MARK,
    _strip_error_mark,
    _worth_extracting,
    format_multi_message,
    inject_image_descriptions,
)


class TestWorthExtracting:
    @pytest.mark.parametrize(
        "content",
        ["", "嗯", "哦", "好", "好的", "哈哈", "在吗", "?", "？", "...", "。。。", "ok", "OK"],
    )
    def test_trivial_rejected(self, content):
        assert _worth_extracting(content) is False

    @pytest.mark.parametrize("content", ["  ", "\n", None])
    def test_blank_rejected(self, content):
        assert _worth_extracting(content) is False

    @pytest.mark.parametrize("content", ["123", "2026", "007"])
    def test_pure_digits_rejected(self, content):
        assert _worth_extracting(content) is False

    @pytest.mark.parametrize(
        "content",
        ["我爱你", "想你", "我明天要面试了", "他养了一只猫叫团子", "今天加班到十一点"],
    )
    def test_meaningful_accepted(self, content):
        """短但高情感 / 有信息量的消息必须通过 —— 这是旧 len>10 门槛的回归点。"""
        assert _worth_extracting(content) is True

    def test_trivial_with_whitespace_still_rejected(self):
        assert _worth_extracting("  嗯  ") is False


class TestFormatMultiMessage:
    def test_single_line_passthrough(self):
        assert format_multi_message("你好") == ("你好", 1)

    def test_empty_lines_ignored(self):
        assert format_multi_message("a\n\n\nb") == ("[消息1] a\n[消息2] b", 2)

    def test_multiline_numbering(self):
        formatted, count = format_multi_message("第一行\n第二行\n第三行")
        assert count == 3
        assert formatted == "[消息1] 第一行\n[消息2] 第二行\n[消息3] 第三行"

    def test_whitespace_only_lines_ignored(self):
        formatted, count = format_multi_message("a\n   \nb")
        assert count == 2
        assert "消息3" not in formatted

    def test_line_content_is_stripped(self):
        formatted, _ = format_multi_message("  a  \n  b  ")
        assert formatted == "[消息1] a\n[消息2] b"


class TestInjectImageDescriptions:
    def test_injects_description_for_user_message(self):
        messages = [{"role": "user", "content": "看我拍的", "image_desc": "一只橘猫趴窗台"}]
        out = inject_image_descriptions(messages)
        assert "一只橘猫趴窗台" in out[0]["content"]
        assert out[0]["content"].startswith("看我拍的")

    def test_empty_caption_uses_placeholder(self):
        messages = [{"role": "user", "content": "", "image_desc": "一只橘猫"}]
        out = inject_image_descriptions(messages)
        assert out[0]["content"].startswith("[图片]")

    def test_ui_fields_stripped(self):
        messages = [{"role": "user", "content": "x", "image": "/a.png", "image_desc": "d"}]
        out = inject_image_descriptions(messages)
        assert "image" not in out[0]
        assert "image_desc" not in out[0]

    def test_assistant_message_not_injected(self):
        messages = [{"role": "assistant", "content": "好看", "image_desc": "不该用"}]
        out = inject_image_descriptions(messages)
        assert out[0]["content"] == "好看"

    def test_input_not_mutated(self):
        messages = [{"role": "user", "content": "x", "image_desc": "d"}]
        inject_image_descriptions(messages)
        assert messages[0] == {"role": "user", "content": "x", "image_desc": "d"}

    def test_message_without_image_fields_untouched(self):
        messages = [{"role": "user", "content": "普通消息"}]
        out = inject_image_descriptions(messages)
        assert out[0] == {"role": "user", "content": "普通消息"}

    def test_plain_message_without_image_not_stripped(self):
        """没有 image 字段的消息不该被凭空改内容。"""
        messages = [{"role": "user", "content": "普通消息", "sticker": "x"}]
        out = inject_image_descriptions(messages)
        assert out[0]["content"] == "普通消息"


class TestStripErrorMark:
    def test_marked_reply_is_stripped(self):
        assert _strip_error_mark(ERROR_REPLY_MARK + "服务暂时不可用") == "服务暂时不可用"

    def test_normal_reply_unchanged(self):
        assert _strip_error_mark("哎呀，今天好累") == "哎呀，今天好累"

    def test_idempotent(self):
        once = _strip_error_mark(ERROR_REPLY_MARK + "x")
        assert _strip_error_mark(once) == once

    def test_empty_string(self):
        assert _strip_error_mark("") == ""

    def test_mark_only(self):
        assert _strip_error_mark(ERROR_REPLY_MARK) == ""
