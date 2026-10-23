"""内置工具与注册中心测试 —— `core/tools/base.py` + `core/tools/builtin.py`。

工具在 prompt 里是以「函数签名」形式暴露给模型的，一个不小心就会变成
「模型以为能查天气、其实工具注册失败」的静默故障。这里锁三件事：
1. `to_function_spec()` 输出的形状必须符合 OpenAI function calling；
2. 每个内置工具的 `name` 唯一、`parameters` 是合法 JSON Schema；
3. 文件类工具（reminder / note）真的写到指定 data_dir，不乱丢到 cwd。
"""

import json

import pytest

from core.tools.base import BaseTool, ToolCall, ToolRegistry, ToolResult
from core.tools.builtin import (
    ClockTool,
    DateCalcTool,
    NoteTool,
    ReminderTool,
    TimerTool,
    TranslateTool,
    register_all,
)


class _DummyTool(BaseTool):
    name = "dummy"
    description = "测试用工具"

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(True, "ok")


class TestToolResult:
    def test_defaults(self):
        r = ToolResult(True, "out")
        assert r.success is True
        assert r.output == "out"
        assert r.error is None
        assert r.data == {}

    def test_data_not_shared_between_instances(self):
        a, b = ToolResult(True, "a"), ToolResult(True, "b")
        a.data["x"] = 1
        assert b.data == {}


class TestBaseTool:
    def test_default_parameters_schema(self):
        tool = _DummyTool()
        params = tool.parameters
        assert params["type"] == "object"
        assert params["properties"] == {}
        assert params["required"] == []

    def test_function_spec_shape(self):
        spec = _DummyTool().to_function_spec()
        assert spec["type"] == "function"
        assert spec["function"]["name"] == "dummy"
        assert spec["function"]["description"] == "测试用工具"
        assert spec["function"]["parameters"]["type"] == "object"

    def test_abstract_name_required(self):
        class Incomplete(BaseTool):
            description = "x"

            async def execute(self, **kwargs):
                return ToolResult(True, "")

        with pytest.raises(TypeError):
            Incomplete()

    def test_abstract_execute_required(self):
        class Incomplete(BaseTool):
            name = "x"
            description = "x"

        with pytest.raises(TypeError):
            Incomplete()


class TestToolRegistry:
    def test_empty_registry(self):
        reg = ToolRegistry()
        assert reg.available is False
        assert reg.tool_names == []
        assert reg.list_tools() == []
        assert reg.get_function_specs() == []

    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = _DummyTool()
        reg.register(tool)
        assert reg.get("dummy") is tool
        assert reg.available is True
        assert reg.tool_names == ["dummy"]

    def test_get_missing_returns_none(self):
        assert ToolRegistry().get("nope") is None

    def test_register_replaces_same_name(self):
        reg = ToolRegistry()
        first, second = _DummyTool(), _DummyTool()
        reg.register(first)
        reg.register(second)
        assert reg.get("dummy") is second
        assert len(reg.list_tools()) == 1

    def test_get_function_specs(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())
        specs = reg.get_function_specs()
        assert len(specs) == 1
        assert specs[0]["function"]["name"] == "dummy"

    def test_get_prompt_block_empty(self):
        assert ToolRegistry().get_prompt_block() == ""

    def test_get_prompt_block_lists_tools(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())
        block = reg.get_prompt_block()
        assert block.startswith("可用工具：")
        assert "- dummy: 测试用工具" in block


class TestRegistryParseCalls:
    def _registry(self):
        reg = ToolRegistry()
        reg.register(ClockTool())
        reg.register(DateCalcTool())
        return reg

    def test_no_call(self):
        assert self._registry().parse_calls("今天天气不错") == []

    def test_bare_name(self):
        calls = self._registry().parse_calls("/call clock")
        assert len(calls) == 1
        assert calls[0].name == "clock"
        assert calls[0].params == {}

    def test_with_params(self):
        calls = self._registry().parse_calls('/call date_calc(date1="2026-01-01", date2="2026-02-01")')
        assert calls[0].params == {"date1": "2026-01-01", "date2": "2026-02-01"}

    def test_unknown_tool_skipped(self):
        assert self._registry().parse_calls("/call weather(city='成都')") == []

    def test_raw_text_kept(self):
        calls = self._registry().parse_calls("/call clock")
        assert calls[0].raw_text == "/call clock"

    def test_single_quotes_accepted(self):
        calls = self._registry().parse_calls("/call date_calc(date1='2026-01-01')")
        assert calls[0].params == {"date1": "2026-01-01"}

    def test_multiple_calls(self):
        calls = self._registry().parse_calls("/call clock 然后 /call date_calc(date1=\"2026-01-01\")")
        assert [c.name for c in calls] == ["clock", "date_calc"]


class TestBuiltinMetadata:
    ALL = [ClockTool, DateCalcTool, ReminderTool, NoteTool, TimerTool, TranslateTool]

    def test_names_unique(self):
        names = [cls.name for cls in self.ALL]
        assert len(names) == len(set(names))

    def test_description_non_empty(self):
        for cls in self.ALL:
            assert cls.description.strip(), f"{cls.__name__} 缺少描述"

    @pytest.mark.parametrize("cls", ALL)
    def test_parameters_is_valid_schema(self, cls, tmp_path):
        params = cls(data_dir=str(tmp_path)).parameters if cls in (ReminderTool, NoteTool) else cls().parameters
        assert params["type"] == "object"
        assert isinstance(params["properties"], dict)
        assert isinstance(params["required"], list)
        # required 里的字段必须真的在 properties 里声明
        for key in params["required"]:
            assert key in params["properties"], f"{cls.__name__}.required 引用了未声明字段 {key}"
        # 必须能 JSON 序列化（会直接塞进请求体）
        json.dumps(params, ensure_ascii=False)

    def test_register_all(self, tmp_path):
        reg = ToolRegistry()
        register_all(reg, data_dir=str(tmp_path))
        assert set(reg.tool_names) == {"clock", "date_calc", "reminder", "note", "timer", "translate"}
        assert len(reg.get_function_specs()) == 6


class TestClockTool:
    async def test_returns_time_string(self):
        result = await ClockTool().execute()
        assert result.success is True
        assert "当前时间：" in result.output
        assert "星期" in result.output

    async def test_ignores_extra_params(self):
        result = await ClockTool().execute(unexpected="x")
        assert result.success is True


class TestDateCalcTool:
    async def test_two_dates(self):
        result = await DateCalcTool().execute(date1="2026-01-01", date2="2026-01-31")
        assert result.success is True
        assert "30 天" in result.output

    async def test_absolute_difference(self):
        # 传反了也要给正数
        result = await DateCalcTool().execute(date1="2026-01-31", date2="2026-01-01")
        assert "30 天" in result.output

    async def test_missing_date2_uses_today(self):
        result = await DateCalcTool().execute(date1="2020-01-01")
        assert result.success is True
        assert "共" in result.output

    @pytest.mark.parametrize("bad", ["2026/01/01", "not-a-date", "2026-13-01"])
    async def test_bad_format(self, bad):
        result = await DateCalcTool().execute(date1=bad)
        assert result.success is False
        assert "日期格式错误" in result.error


class TestReminderTool:
    async def test_writes_json(self, tmp_path):
        tool = ReminderTool(data_dir=str(tmp_path))
        result = await tool.execute(content="明天带伞")
        assert result.success is True
        assert "已记住" in result.output
        files = list((tmp_path / "reminders").glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text(encoding="utf-8"))
        assert data[0]["content"] == "明天带伞"
        assert "created_at" in data[0]

    async def test_appends_to_same_month_file(self, tmp_path):
        tool = ReminderTool(data_dir=str(tmp_path))
        await tool.execute(content="第一件")
        await tool.execute(content="第二件")
        files = list((tmp_path / "reminders").glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text(encoding="utf-8"))
        assert [d["content"] for d in data] == ["第一件", "第二件"]

    @pytest.mark.parametrize("content", ["", None])
    async def test_empty_content_rejected(self, content, tmp_path):
        tool = ReminderTool(data_dir=str(tmp_path))
        result = await tool.execute(content=content or "")
        assert result.success is False
        assert "需要记住什么" in result.error

    def test_does_not_touch_cwd_when_data_dir_given(self, tmp_path):
        ReminderTool(data_dir=str(tmp_path))
        assert (tmp_path / "reminders").is_dir()


class TestNoteTool:
    async def test_writes_markdown(self, tmp_path):
        tool = NoteTool(data_dir=str(tmp_path))
        result = await tool.execute(content="今天修了记忆衰减")
        assert result.success is True
        files = list((tmp_path / "notes").glob("*.md"))
        assert len(files) == 1
        text = files[0].read_text(encoding="utf-8")
        assert "今天修了记忆衰减" in text
        assert text.startswith("\n## ")
        assert text.rstrip().endswith("---")

    async def test_tags_line(self, tmp_path):
        tool = NoteTool(data_dir=str(tmp_path))
        await tool.execute(content="内容", tags="记忆,衰减")
        text = next((tmp_path / "notes").glob("*.md")).read_text(encoding="utf-8")
        assert "tags: 记忆,衰减" in text

    async def test_no_tags_no_line(self, tmp_path):
        tool = NoteTool(data_dir=str(tmp_path))
        await tool.execute(content="内容")
        text = next((tmp_path / "notes").glob("*.md")).read_text(encoding="utf-8")
        assert "tags:" not in text

    async def test_appends_within_same_day(self, tmp_path):
        tool = NoteTool(data_dir=str(tmp_path))
        await tool.execute(content="第一条")
        await tool.execute(content="第二条")
        files = list((tmp_path / "notes").glob("*.md"))
        assert len(files) == 1
        text = files[0].read_text(encoding="utf-8")
        assert "第一条" in text and "第二条" in text

    async def test_empty_rejected(self, tmp_path):
        result = await NoteTool(data_dir=str(tmp_path)).execute(content="")
        assert result.success is False
        assert "不能为空" in result.error


class TestTimerTool:
    def setup_method(self):
        TimerTool._timers.clear()

    def teardown_method(self):
        TimerTool._timers.clear()

    async def test_sets_timer(self):
        result = await TimerTool().execute(minutes=5, note="泡茶")
        assert result.success is True
        assert "5 分钟后" in result.output
        assert "泡茶" in result.output
        assert len(TimerTool._timers) == 1

    async def test_default_note(self):
        result = await TimerTool().execute(minutes=1)
        assert "时间到" in result.output

    @pytest.mark.parametrize("bad", [0, -1, 1441, 99999])
    async def test_out_of_range(self, bad):
        result = await TimerTool().execute(minutes=bad)
        assert result.success is False
        assert "1~1440" in result.error

    @pytest.mark.parametrize("ok", [1, 1440])
    async def test_boundary_accepted(self, ok):
        assert (await TimerTool().execute(minutes=ok)).success is True

    async def test_check_returns_overdue(self):
        TimerTool._timers.append({"note": "过期项", "eta": __import__("datetime").datetime(2000, 1, 1)})
        TimerTool._timers.append({"note": "未来项", "eta": __import__("datetime").datetime(2999, 1, 1)})
        overdue = TimerTool.check()
        assert overdue == ["过期项"]
        # 只移除已过期的
        assert [t["note"] for t in TimerTool._timers] == ["未来项"]

    def test_check_empty(self):
        assert TimerTool.check() == []


class TestTranslateTool:
    @pytest.mark.parametrize(
        "text,expected",
        [("你好", "Hello"), ("谢谢", "Thank you"), ("Hello", "你好"), ("today", "今天")],
    )
    async def test_dict_hit(self, text, expected):
        result = await TranslateTool().execute(text=text)
        assert result.success is True
        assert result.output == expected

    async def test_dict_miss_fallback(self):
        result = await TranslateTool().execute(text="完全没收录的句子")
        assert result.success is True
        assert result.output.startswith("[翻译] ")

    async def test_strips_whitespace(self):
        assert (await TranslateTool().execute(text="  你好  ")).output == "Hello"

    async def test_empty_rejected(self):
        result = await TranslateTool().execute(text="")
        assert result.success is False
        assert "需要翻译" in result.error

    async def test_invalid_target_falls_back_to_zh(self):
        # target 只认 zh/en，其它一律当 zh
        assert (await TranslateTool().execute(text="Hello", target="fr")).output == "你好"

    async def test_target_case_insensitive(self):
        assert (await TranslateTool().execute(text="Hello", target="ZH")).output == "你好"


class TestToolCall:
    def test_defaults(self):
        call = ToolCall(name="clock")
        assert call.params == {}
        assert call.raw_text == ""

    def test_params_independent(self):
        a, b = ToolCall(name="x"), ToolCall(name="y")
        a.params["k"] = "v"
        assert b.params == {}
