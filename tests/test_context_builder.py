"""上下文预算裁剪测试。

覆盖:
- trim_messages_to_budget：空输入、当前请求必须保留、新轮次优先、system 前缀跟随
- _llm_message：剥掉 UI 字段，只留 provider 需要的键
- get_time_context：返回非空中文时段描述
"""

from core.chat.context_builder import (
    DEFAULT_CONTEXT_CHAR_BUDGET,
    _llm_message,
    get_time_context,
    trim_messages_to_budget,
)


class TestLlmMessage:
    def test_only_llm_keys_kept(self):
        raw = {
            "role": "user",
            "content": "hi",
            "sticker": "s1",
            "timestamp": "12:00",
            "emotion": "happy",
        }
        assert _llm_message(raw) == {"role": "user", "content": "hi"}

    def test_name_and_tool_fields_kept(self):
        raw = {"role": "tool", "content": "x", "name": "clock", "tool_call_id": "t1"}
        out = _llm_message(raw)
        assert set(out) == {"role", "content", "name", "tool_call_id"}

    def test_tool_calls_kept(self):
        raw = {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]}
        assert _llm_message(raw)["tool_calls"] == [{"id": "1"}]


class TestTrimMessagesToBudget:
    def test_empty_returns_empty(self):
        assert trim_messages_to_budget([], max_chars=100) == []

    def test_current_request_always_kept(self):
        """即使当前请求本身超预算，也必须保留（否则模型无话可说）。"""
        messages = [
            {"role": "user", "content": "a" * 500},
            {"role": "assistant", "content": "b" * 500},
            {"role": "user", "content": "c" * 500},
        ]
        out = trim_messages_to_budget(messages, max_chars=10)
        assert out[-1]["content"] == "c" * 500

    def test_newest_turns_kept_first(self):
        messages = [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old-reply"},
            {"role": "user", "content": "new"},
        ]
        out = trim_messages_to_budget(messages, max_chars=200)
        assert [m["content"] for m in out] == ["old", "old-reply", "new"]

    def test_budget_drops_oldest_turn(self):
        messages = [
            {"role": "user", "content": "x" * 100},
            {"role": "assistant", "content": "y" * 100},
            {"role": "user", "content": "z" * 100},
        ]
        out = trim_messages_to_budget(messages, max_chars=150)
        # 最新一轮 100 字符保留，旧一轮 200 字符超预算被丢
        assert [m["content"] for m in out] == ["z" * 100]

    def test_whole_turn_kept_or_dropped_together(self):
        """user/assistant 必须成对出现，不能只留半轮。"""
        messages = [
            {"role": "user", "content": "u" * 80},
            {"role": "assistant", "content": "a" * 80},
            {"role": "user", "content": "latest"},
        ]
        out = trim_messages_to_budget(messages, max_chars=100)
        roles = [m["role"] for m in out]
        # 要么 u+a 都在，要么都不在
        assert not (("user" in roles[:-1]) != ("assistant" in roles))

    def test_system_prefix_follows_current_request(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "latest"},
        ]
        out = trim_messages_to_budget(messages, max_chars=1000)
        assert out[0]["role"] == "system"
        assert out[-1]["content"] == "latest"

    def test_reserved_chars_reduces_available(self):
        messages = [
            {"role": "user", "content": "x" * 100},
            {"role": "assistant", "content": "y" * 100},
            {"role": "user", "content": "z" * 100},
        ]
        loose = trim_messages_to_budget(messages, max_chars=350)
        tight = trim_messages_to_budget(messages, max_chars=350, reserved_chars=300)
        assert len(tight) <= len(loose)

    def test_ui_fields_stripped_in_output(self):
        messages = [{"role": "user", "content": "hi", "sticker": "s", "timestamp": "t"}]
        out = trim_messages_to_budget(messages, max_chars=100)
        assert "sticker" not in out[0]

    def test_negative_reserved_clamped(self):
        messages = [{"role": "user", "content": "hi"}]
        out = trim_messages_to_budget(messages, max_chars=100, reserved_chars=-500)
        assert out[0]["content"] == "hi"

    def test_default_budget_value(self):
        assert DEFAULT_CONTEXT_CHAR_BUDGET == 24_000


class TestTimeContext:
    def test_returns_non_empty_string(self):
        out = get_time_context()
        assert isinstance(out, str)
        assert out.strip()
