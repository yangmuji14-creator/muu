"""Prompt 上下文装配测试

覆盖 `core/chat/context_builder.py` 的 `PromptContextAssembler.build` 与
`PromptContext` 数据形状。`trim_messages_to_budget` / `insert_dynamic_context`
的基础行为在 `tests/test_context_builder.py` 已测过，这里只补装配层。

装配层不碰数据库、不发请求，但它的输入里有一堆服务对象 —— 全部用最小替身，
只实现 `build` 实际会调的那几个方法。**不要 mock 被测对象本身**：
`PromptContextAssembler` 要真跑一遍，测的才是它自己的分支。
"""

from __future__ import annotations

import pytest

from core.chat.context_builder import (
    DEFAULT_CONTEXT_CHAR_BUDGET,
    PromptContext,
    PromptContextAssembler,
    get_time_context,
    insert_dynamic_context,
    trim_messages_to_budget,
)


# ---------------- 最小替身 ----------------

class FakePersona:
    """`PromptBuilder.build_stable` 会 getattr 一堆字段，漏一个就 AttributeError。
    这里直接用真的 `Persona` 模型（它所有字段都有默认值），比手写替身稳。"""


def _persona():
    from core.persona.models import Persona
    return Persona(
        id="girlfriend_001",
        name="慕",
        personality=["真诚", "自然"],
        background="一个真实存在、有自己生活的陪伴者。",
        nickname_for_user="你",
        relationship_level=30,
    )


class FakeMemoryManager:
    def __init__(self, context: str = "", fallback: list[str] | None = None):
        self._context = context
        self._fallback = fallback or []
        self.context_calls: list[dict] = []

    def get_context_prompt(self, user_id, limit=8, query=""):
        self.context_calls.append({"user_id": user_id, "limit": limit, "query": query})
        return self._context


class FakeMoodEngine:
    def __init__(self, mood=None):
        from core.emotion.mood import MoodState
        self._mood = mood or MoodState()

    def get_mood(self, user_id):
        return self._mood


class FakeTopicTracker:
    def __init__(self, context: str = ""):
        self._context = context

    def get_topic_context(self):
        return self._context


class FakeTool:
    def __init__(self, name: str, description: str, parameters: dict | None = None):
        self.name = name
        self.description = description
        self.parameters = parameters or {"type": "object", "properties": {}}


class FakeToolRegistry:
    """`build_tools_prompt` 真正读的是 `available` + `list_tools()`，不是
    `get_prompt_block()` —— 后者在 `core/chat/tool_handler.py` 里根本不存在，
    照着它写替身会 `AttributeError`。"""

    def __init__(self, tools: list[FakeTool] | None = None):
        self._tools = tools or []
        self.available = bool(self._tools)

    def list_tools(self):
        return list(self._tools)

    def get_prompt_block(self):
        return ""


class FakeMcpManager:
    def __init__(self, tools_count: int = 0, prompt: str = ""):
        self.tools_count = tools_count
        self._prompt = prompt

    def get_tools_prompt(self):
        return self._prompt


class FakeBrain:
    def __init__(self, runtime_context=None, monologue="", raises=False):
        self._runtime_context = runtime_context
        self._monologue = monologue
        self._raises = raises
        self.calls = 0

    async def run(self, user_id, persona_id, user_message=""):
        self.calls += 1
        if self._raises:
            raise RuntimeError("brain 挂了")

        class Output:
            pass

        out = Output()
        out.runtime_context = self._runtime_context
        out.monologue = self._monologue
        return out


async def _no_fallback(user_id: str, content: str) -> list[str]:
    return []


def _assembler(**overrides) -> PromptContextAssembler:
    kwargs = {
        "memory_manager": FakeMemoryManager(),
        "mood_engine": None,
        "topic_tracker": None,
        "tool_registry": FakeToolRegistry(),
        "brain": None,
        "config": {},
    }
    kwargs.update(overrides)
    return PromptContextAssembler(**kwargs)


async def _build(assembler, **overrides):
    kwargs = {
        "user_id": "u1",
        "persona_id": "girlfriend_001",
        "persona": _persona(),
        "content": "我明天要面试了",
        "messages": [{"role": "user", "content": "我明天要面试了"}],
        "relationship_level": 30,
        "message_count": 1,
        "thought": None,
        "retrieve_fallback": _no_fallback,
    }
    kwargs.update(overrides)
    return await assembler.build(**kwargs)


# ---------------- 基础形状 ----------------

class TestPromptContextShape:
    async def test_returns_prompt_context(self):
        assert isinstance(await _build(_assembler()), PromptContext)

    async def test_stable_prompt_is_non_empty(self):
        ctx = await _build(_assembler())
        assert isinstance(ctx.stable_prompt, str) and ctx.stable_prompt.strip()

    async def test_dynamic_context_is_non_empty(self):
        ctx = await _build(_assembler())
        assert isinstance(ctx.dynamic_context, str) and ctx.dynamic_context.strip()

    async def test_request_messages_end_with_the_user_turn(self):
        ctx = await _build(_assembler())
        assert ctx.request_messages[-1]["role"] == "user"
        assert ctx.request_messages[-1]["content"] == "我明天要面试了"

    async def test_brain_active_defaults_to_false(self):
        assert (await _build(_assembler())).brain_active is False


class TestBrainGating:
    async def test_brain_disabled_by_config_is_not_called(self):
        brain = FakeBrain(runtime_context="内心独白")
        ctx = await _build(
            _assembler(brain=brain, config={"brain_enabled": False}),
        )
        assert brain.calls == 0
        assert ctx.brain_active is False

    async def test_brain_without_runtime_context_is_inactive(self):
        brain = FakeBrain(runtime_context=None)
        ctx = await _build(_assembler(brain=brain))
        assert brain.calls == 1
        assert ctx.brain_active is False

    async def test_brain_runtime_context_activates_it(self):
        brain = FakeBrain(runtime_context="我在想他今天怎么这么安静")
        ctx = await _build(_assembler(brain=brain))
        assert ctx.brain_active is True
        assert "我在想他今天怎么这么安静" in ctx.dynamic_context

    async def test_legacy_monologue_is_used_as_fallback(self):
        # 第三方 brain 实现只返回 monologue 时也要能当 runtime_context 用
        brain = FakeBrain(runtime_context=None, monologue="老接口的独白")
        ctx = await _build(_assembler(brain=brain))
        assert ctx.brain_active is True
        assert "老接口的独白" in ctx.dynamic_context

    async def test_brain_exception_does_not_break_build(self):
        ctx = await _build(_assembler(brain=FakeBrain(raises=True)))
        assert ctx.brain_active is False
        assert ctx.request_messages

    async def test_empty_runtime_context_string_is_inactive(self):
        brain = FakeBrain(runtime_context="")
        assert (await _build(_assembler(brain=brain))).brain_active is False


class TestMemoryContext:
    async def test_memory_context_is_injected(self):
        mgr = FakeMemoryManager(context="【关于对方的记忆】\n- 他有一只猫叫团子")
        ctx = await _build(_assembler(memory_manager=mgr))
        assert "团子" in ctx.dynamic_context

    async def test_memory_query_includes_thought_topic(self):
        mgr = FakeMemoryManager()
        await _build(_assembler(memory_manager=mgr),
                     thought={"topic": "面试", "intent": ""})
        assert "面试" in mgr.context_calls[0]["query"]

    async def test_memory_query_is_content_without_thought(self):
        mgr = FakeMemoryManager()
        await _build(_assembler(memory_manager=mgr), content="我明天要面试了")
        assert mgr.context_calls[0]["query"] == "我明天要面试了"

    async def test_memory_limit_is_8(self):
        mgr = FakeMemoryManager()
        await _build(_assembler(memory_manager=mgr))
        assert mgr.context_calls[0]["limit"] == 8

    async def test_fallback_retrieval_runs_only_when_memory_is_empty(self):
        calls: list[str] = []

        async def fallback(user_id, content):
            calls.append(content)
            return ["旧总结里的一条"]

        ctx = await _build(_assembler(memory_manager=FakeMemoryManager(context="")),
                           retrieve_fallback=fallback)
        assert calls == ["我明天要面试了"]
        assert "旧总结里的一条" in ctx.dynamic_context

    async def test_fallback_retrieval_skipped_when_memory_exists(self):
        calls: list[str] = []

        async def fallback(user_id, content):
            calls.append(content)
            return ["不该出现"]

        ctx = await _build(
            _assembler(memory_manager=FakeMemoryManager(context="【记忆】\n- 有猫")),
            retrieve_fallback=fallback,
        )
        assert calls == []
        assert "不该出现" not in ctx.dynamic_context

    async def test_empty_fallback_result_adds_nothing(self):
        ctx = await _build(_assembler(memory_manager=FakeMemoryManager(context="")))
        assert "与当前话题相关的记忆" not in ctx.dynamic_context


class TestMoodAndTopic:
    async def test_mood_style_is_appended_when_no_brain(self):
        from core.emotion.mood import MoodState, MoodType
        mood = FakeMoodEngine(MoodState(mood=MoodType.HAPPY, intensity=0.9,
                                        valence=0.8, arousal=0.6, energy=0.7))
        ctx = await _build(_assembler(mood_engine=mood))
        assert "【当前情绪指导】" in ctx.dynamic_context

    async def test_mood_style_also_applies_when_brain_active(self):
        """runtime 块与情绪风格指导是互补的，不是互斥的。

        历史缺陷：这里是 `elif`，只要 brain 返回非空 runtime（深夜 / 有未闭合事件 /
        非中性情绪都会返回），17 条情绪表达规则整块被跳过。
        """
        from core.emotion.mood import MoodState, MoodType
        mood = FakeMoodEngine(MoodState(mood=MoodType.HAPPY, intensity=0.9))
        brain = FakeBrain(runtime_context="独白")
        ctx = await _build(_assembler(mood_engine=mood, brain=brain))
        assert "独白" in ctx.dynamic_context
        assert "【当前情绪指导】" in ctx.dynamic_context

    async def test_topic_context_is_appended(self):
        ctx = await _build(_assembler(topic_tracker=FakeTopicTracker("【话题】在聊面试")))
        assert "【话题】在聊面试" in ctx.dynamic_context

    async def test_topic_context_is_skipped_when_brain_active(self):
        brain = FakeBrain(runtime_context="独白")
        ctx = await _build(_assembler(brain=brain,
                                      topic_tracker=FakeTopicTracker("【话题】不该出现")))
        assert "不该出现" not in ctx.dynamic_context

    async def test_empty_topic_context_adds_nothing(self):
        ctx = await _build(_assembler(topic_tracker=FakeTopicTracker("")))
        assert ctx.dynamic_context


class TestThoughtHint:
    @pytest.mark.parametrize("intent", ["撒娇", "抱怨", "倾诉", "表白"])
    async def test_emotional_intents_add_a_hint(self, intent):
        ctx = await _build(_assembler(), thought={"intent": intent, "topic": ""})
        assert f"对方似乎在{intent}" in ctx.dynamic_context

    async def test_ordinary_intent_adds_no_hint(self):
        ctx = await _build(_assembler(), thought={"intent": "陈述", "topic": ""})
        assert "对方似乎在" not in ctx.dynamic_context

    async def test_hint_is_skipped_when_brain_active(self):
        brain = FakeBrain(runtime_context="独白")
        ctx = await _build(_assembler(brain=brain),
                           thought={"intent": "撒娇", "topic": ""})
        assert "对方似乎在" not in ctx.dynamic_context


class TestMultiMessageHint:
    async def test_single_message_adds_no_hint(self):
        ctx = await _build(_assembler(), message_count=1)
        assert "一口气发了" not in ctx.dynamic_context

    async def test_multiple_messages_add_hint(self):
        ctx = await _build(_assembler(), message_count=3)
        assert "一口气发了 3 条消息" in ctx.dynamic_context


class TestToolsPrompt:
    async def test_tools_prompt_is_appended(self):
        registry = FakeToolRegistry([
            FakeTool("clock", "报时", {"type": "object", "properties": {}}),
        ])
        ctx = await _build(_assembler(tool_registry=registry))
        assert "可用工具" in ctx.dynamic_context
        assert "clock" in ctx.dynamic_context

    async def test_tool_parameter_descriptions_are_rendered(self):
        registry = FakeToolRegistry([
            FakeTool("weather", "查天气", {
                "type": "object",
                "properties": {"city": {"description": "城市名"}},
                "required": ["city"],
            }),
        ])
        ctx = await _build(_assembler(tool_registry=registry))
        assert "city: 城市名 （必填）" in ctx.dynamic_context

    async def test_empty_registry_adds_nothing(self):
        ctx = await _build(_assembler(tool_registry=FakeToolRegistry([])))
        assert "可用工具" not in ctx.dynamic_context

    async def test_none_registry_adds_nothing(self):
        ctx = await _build(_assembler(tool_registry=None))
        assert "可用工具" not in ctx.dynamic_context


class TestMessageGates:
    async def test_max_messages_trims_history_head(self):
        history = [{"role": "user", "content": f"第{i}句"} for i in range(1, 11)]
        ctx = await _build(_assembler(config={"max_messages": 3}), messages=history)
        assert len(ctx.request_messages) <= 3 + 1  # +1 是插入的 system 块
        assert ctx.request_messages[-1]["content"] == "第10句"

    async def test_max_messages_zero_means_no_limit(self):
        history = [{"role": "user", "content": f"第{i}句"} for i in range(1, 11)]
        ctx = await _build(_assembler(config={"max_messages": 0}), messages=history)
        user_msgs = [m for m in ctx.request_messages if m["role"] == "user"]
        assert len(user_msgs) == 10

    async def test_bad_max_messages_value_is_ignored(self):
        history = [{"role": "user", "content": f"第{i}句"} for i in range(1, 6)]
        ctx = await _build(_assembler(config={"max_messages": "不是数字"}), messages=history)
        assert len([m for m in ctx.request_messages if m["role"] == "user"]) == 5

    async def test_char_budget_shrinks_history(self):
        history = [
            {"role": "user", "content": "长" * 5000},
            {"role": "assistant", "content": "回" * 5000},
            {"role": "user", "content": "最新一句"},
        ]
        ctx = await _build(_assembler(config={"context_char_budget": 4000}),
                           messages=history)
        assert ctx.request_messages[-1]["content"] == "最新一句"
        assert len(ctx.request_messages) < len(history) + 1

    async def test_budget_floor_is_4000(self):
        # 配一个荒唐的小预算，也不该把当前请求裁掉
        ctx = await _build(_assembler(config={"context_char_budget": 10}),
                           messages=[{"role": "user", "content": "最新一句"}])
        assert any(m["content"] == "最新一句" for m in ctx.request_messages)

    async def test_default_budget_constant(self):
        assert DEFAULT_CONTEXT_CHAR_BUDGET == 24_000

    async def test_ui_fields_are_stripped_from_request_messages(self):
        history = [{"role": "user", "content": "嗨", "sticker": "paw", "emotion": "happy"}]
        ctx = await _build(_assembler(), messages=history)
        last = ctx.request_messages[-1]
        assert "sticker" not in last
        assert "emotion" not in last


class TestTimeContextHelper:
    """顺手补两条 `get_time_context` 的行为契约。"""

    def test_format(self):
        out = get_time_context()
        assert out.startswith("现在是")
        assert "：" in out or ":" in out

    def test_period_word_is_one_of_the_seven(self):
        out = get_time_context()
        assert any(p in out for p in ("深夜", "早上", "上午", "中午", "下午", "晚上"))


class TestInsertDynamicContextHelper:
    def test_inserts_before_last_user_turn(self):
        messages = [
            {"role": "user", "content": "旧"},
            {"role": "assistant", "content": "回"},
            {"role": "user", "content": "新"},
        ]
        out = insert_dynamic_context(messages, "动态块")
        assert out[-2] == {"role": "system", "content": "动态块"}
        assert out[-1]["content"] == "新"

    def test_appends_when_no_user_turn(self):
        out = insert_dynamic_context([{"role": "assistant", "content": "只有回复"}], "动态块")
        assert out[-1] == {"role": "system", "content": "动态块"}

    def test_empty_context_returns_copy(self):
        messages = [{"role": "user", "content": "嗨"}]
        out = insert_dynamic_context(messages, "")
        assert out == [{"role": "user", "content": "嗨"}]
        assert out is not messages

    def test_does_not_mutate_input(self):
        messages = [{"role": "user", "content": "嗨"}]
        insert_dynamic_context(messages, "动态块")
        assert messages == [{"role": "user", "content": "嗨"}]


class TestTrimHelperRegression:
    """`trim_messages_to_budget` 的边界补充（原有测试已覆盖主路径）。"""

    def test_current_request_survives_a_near_zero_budget(self):
        messages = [{"role": "user", "content": "最新一句"}]
        assert trim_messages_to_budget(messages, max_chars=1)[-1]["content"] == "最新一句"

    def test_empty_messages(self):
        assert trim_messages_to_budget([], max_chars=100) == []


# ---------------- 上下文窗口（max_messages）----------------


class TestMaxMessages:
    """`max_messages` 决定模型能看到多少条历史。

    这条配置长期是死的（赋值后无读者），修复后它才真正生效 —— 于是
    默认值直接决定「她记不记得刚才说过什么」。这里锁住三条契约：
    0/缺省=不截断、超限时保留最近、截断后仍以当前这条用户消息结尾。
    """

    @staticmethod
    def _history(turns: int) -> list[dict]:
        messages = []
        for i in range(turns):
            messages.append({"role": "user", "content": f"第{i}句用户消息"})
            messages.append({"role": "assistant", "content": f"第{i}句回复"})
        return messages

    async def test_zero_means_no_truncation(self) -> None:
        messages = self._history(40)  # 80 条
        ctx = await _build(
            _assembler(config={"max_messages": 0}), messages=messages,
        )
        # 80 条历史 + 1 条插入的 system 上下文
        assert len(ctx.request_messages) >= 80

    async def test_keeps_newest_turns(self) -> None:
        messages = self._history(40)
        ctx = await _build(
            _assembler(config={"max_messages": 20}), messages=messages,
        )
        contents = [m.get("content", "") for m in ctx.request_messages]
        assert any("第39句用户消息" in c for c in contents)
        assert not any("第0句用户消息" in c for c in contents)

    async def test_ends_with_current_user_message(self) -> None:
        messages = self._history(30)
        ctx = await _build(
            _assembler(config={"max_messages": 10}), messages=messages,
        )
        non_system = [m for m in ctx.request_messages if m.get("role") != "system"]
        assert non_system[-1]["role"] == "assistant"

    async def test_invalid_value_does_not_crash(self) -> None:
        messages = self._history(5)
        for bad in ("abc", None, 2.7):
            ctx = await _build(
                _assembler(config={"max_messages": bad}), messages=messages,
            )
            assert ctx.request_messages
