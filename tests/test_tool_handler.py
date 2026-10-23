"""工具调用解析测试。

覆盖 parse_tool_call 的三套语法与其优先级:
1. ```tool {"name": ..., "arguments": {...}} ``` 结构化块
2. _TOOL_CALL_PATTERN（tool_name(key="value") 形式）
3. /call name(key="value") 旧 CLI 兼容形式
"""

import pytest

from core.chat.tool_handler import parse_tool_call


class TestStructuredForm:
    def test_structured_block_parsed(self):
        text = '```tool\n{"name": "get_weather", "arguments": {"city": "成都"}}\n```'
        assert parse_tool_call(text) == [("get_weather", {"city": "成都"})]

    def test_multiple_structured_blocks(self):
        text = (
            '```tool\n{"name": "a", "arguments": {"x": "1"}}\n```\n'
            '```tool\n{"name": "b", "arguments": {"y": "2"}}\n```'
        )
        assert parse_tool_call(text) == [("a", {"x": "1"}), ("b", {"y": "2"})]

    def test_missing_arguments_defaults_empty(self):
        text = '```tool\n{"name": "clock"}\n```'
        assert parse_tool_call(text) == [("clock", {})]

    def test_invalid_json_ignored(self):
        text = '```tool\n{not json}\n```'
        assert parse_tool_call(text) == []

    def test_name_not_string_rejected(self):
        text = '```tool\n{"name": 123, "arguments": {}}\n```'
        assert parse_tool_call(text) == []


class TestLegacyCallForm:
    def test_call_without_params(self):
        assert parse_tool_call("/call clock") == [("clock", {})]

    def test_call_with_params(self):
        out = parse_tool_call('/call weather(city="成都")')
        assert out == [("weather", {"city": "成都"})]

    def test_call_with_multiple_params(self):
        out = parse_tool_call('/call f(a="1", b="2")')
        assert out == [("f", {"a": "1", "b": "2"})]

    def test_single_quoted_params(self):
        out = parse_tool_call("/call f(a='1')")
        assert out == [("f", {"a": "1"})]


class TestNoToolCall:
    @pytest.mark.parametrize("text", ["", "就是普通回复", "```python\nprint(1)\n```"])
    def test_plain_text_returns_empty(self, text):
        assert parse_tool_call(text) == []


class TestPriority:
    def test_structured_wins_over_legacy(self):
        text = (
            '```tool\n{"name": "structured", "arguments": {}}\n```\n'
            '/call legacy'
        )
        assert parse_tool_call(text) == [("structured", {})]
