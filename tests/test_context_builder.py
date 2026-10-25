"""上下文预算裁剪测试。

覆盖:
- trim_messages_to_budget：空输入、当前请求必须保留、新轮次优先、system 前缀跟随
- _llm_message：剥掉 UI 字段，只留 provider 需要的键
- get_time_context：返回非空中文时段描述
"""

from core.chat.context_builder import (
    DEFAULT_CONTEXT_CHAR_BUDGET,
    PromptContextAssembler,
    _llm_message,
    get_time_context,
    trim_messages_to_budget,
)


class _FakeTopicTracker:
    def __init__(self, topic: str = "") -> None:
        self._topic = topic
        self.raise_on_get = False

    def get_current_topic(self) -> str:
        if self.raise_on_get:
            raise RuntimeError("tracker broke")
        return self._topic

    def get_topic_context(self) -> str:
        return ""


def _assembler(topic_tracker) -> PromptContextAssembler:
    return PromptContextAssembler(
        memory_manager=None,
        mood_engine=None,
        topic_tracker=topic_tracker,
        tool_registry=None,
        brain=None,
        config={},
    )


class TestBuildMemoryQuery:
    """记忆检索查询串的拼接。

    历史缺陷：这里原来只有 ``thought["topic"]`` 一条分支，而 pipeline 传进来的
    ``thought`` 恒为 None（ENABLE_DIALOGUE_THINKER 关着），整段是死代码。
    """

    def test_uses_topic_tracker_when_thought_missing(self):
        """thought 为 None 时改用 TopicTracker 的话题，而不是只发用户原话。"""
        asm = _assembler(_FakeTopicTracker("养猫"))
        q = asm._build_memory_query("它最近怎么样", None)
        assert "养猫" in q and "它最近怎么样" in q

    def test_thought_topic_wins_over_tracker(self):
        """DialogueThinker 打开时它的 topic 更精确，优先用。"""
        asm = _assembler(_FakeTopicTracker("养猫"))
        q = asm._build_memory_query("它最近怎么样", {"topic": "宠物健康"})
        assert "宠物健康" in q
        assert "养猫" not in q

    def test_empty_topic_falls_back_to_content(self):
        asm = _assembler(_FakeTopicTracker(""))
        assert asm._build_memory_query("随便聊聊", None) == "随便聊聊"

    def test_no_tracker_falls_back_to_content(self):
        asm = _assembler(None)
        assert asm._build_memory_query("随便聊聊", None) == "随便聊聊"

    def test_tracker_failure_falls_back_to_content(self):
        """话题追踪出问题不该让记忆检索挂掉。"""
        tracker = _FakeTopicTracker("养猫")
        tracker.raise_on_get = True
        asm = _assembler(tracker)
        assert asm._build_memory_query("随便聊聊", None) == "随便聊聊"

    def test_topic_already_in_content_not_duplicated(self):
        """话题词已经在原话里时不再重复拼一遍。"""
        asm = _assembler(_FakeTopicTracker("养猫"))
        q = asm._build_memory_query("养猫要注意什么", None)
        assert q == "养猫要注意什么"
        assert q.count("养猫") == 1


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
