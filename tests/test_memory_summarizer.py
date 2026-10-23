"""`core/memory/summarizer.py` 测试 — 三个纯解析函数 + 四个 LLM 方法。

替身思路：`FakeLLM` 只实现 `chat`，返回预先排好的 `LLMResponse`（或抛异常）。
这一层最容易出错的地方是「模型输出不是干净 JSON」，所以解析用例比方法用例多。
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from core.llm.base import LLMResponse
from core.memory.models import Memory
from core.memory.summarizer import (
    MemorySummarizer,
    _clean_memory_content,
    _parse_memory_items,
    _parse_memory_json,
)


class FakeLLM:
    """最小 LLM 替身：按序吐 response，用完循环最后一个。"""

    def __init__(self, *responses, raises: Exception | None = None):
        self._responses = list(responses) or [""]
        self._raises = raises
        self.calls: list[dict] = []

    async def chat(self, messages, system_prompt=None, **kwargs):
        self.calls.append(
            {"messages": messages, "system_prompt": system_prompt, **kwargs}
        )
        if self._raises:
            raise self._raises
        text = self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        return LLMResponse(content=text, model="fake")


# ── _parse_memory_json ───────────────────────────────────


class TestParseMemoryJson:
    def test_plain_object(self):
        assert _parse_memory_json('{"content": "他喜欢火锅"}') == {
            "content": "他喜欢火锅"
        }

    def test_code_fence(self):
        text = '```json\n{"content": "他喜欢火锅"}\n```'
        assert _parse_memory_json(text) == {"content": "他喜欢火锅"}

    def test_fence_without_language(self):
        assert _parse_memory_json('```\n{"content": "x"}\n```') == {"content": "x"}

    def test_extra_prose_around_object(self):
        assert _parse_memory_json('好的，结果是：{"content": "x"} 完毕') == {"content": "x"}

    def test_array_takes_first_dict(self):
        text = '[{"content": "第一条"}, {"content": "第二条"}]'
        assert _parse_memory_json(text) == {"content": "第一条"}

    def test_array_without_dict_returns_none(self):
        assert _parse_memory_json('[1, 2, 3]') is None

    def test_scalar_returns_none(self):
        """契约是只接受 dict —— 标量/数组都要 None，调用方据此丢弃。"""
        assert _parse_memory_json('"just a string"') is None
        assert _parse_memory_json("42") is None

    def test_empty_returns_none(self):
        assert _parse_memory_json("") is None
        assert _parse_memory_json("   ") is None
        assert _parse_memory_json(None) is None

    def test_garbage_returns_none(self):
        assert _parse_memory_json("完全不是 JSON") is None

    def test_broken_json_returns_none(self):
        assert _parse_memory_json('{"content": ') is None

    def test_nested_object(self):
        text = '{"content": "x", "extra": {"a": 1}}'
        assert _parse_memory_json(text)["content"] == "x"


# ── _clean_memory_content ────────────────────────────────


class TestCleanMemoryContent:
    def test_plain_text_passthrough(self):
        assert _clean_memory_content("他养了一只猫") == "他养了一只猫"

    def test_strips_whitespace(self):
        assert _clean_memory_content("  他养了一只猫  ") == "他养了一只猫"

    def test_none_and_empty(self):
        assert _clean_memory_content(None) == ""
        assert _clean_memory_content("") == ""
        assert _clean_memory_content("   ") == ""

    def test_object_unwraps_content(self):
        assert _clean_memory_content('{"content": "他养了一只猫"}') == "他养了一只猫"

    def test_object_without_content_returns_empty(self):
        assert _clean_memory_content('{"foo": "bar"}') == ""

    def test_array_takes_first_dict(self):
        text = '[{"content": "第一条"}, {"content": "第二条"}]'
        assert _clean_memory_content(text) == "第一条"

    def test_array_of_numbers_returns_empty(self):
        """`[1,2,3]` 不是记忆内容 —— 宁可不记也不存垃圾。"""
        assert _clean_memory_content("[1, 2, 3]") == ""

    def test_array_of_short_strings_returns_empty(self):
        assert _clean_memory_content('["a", "b"]') == ""

    def test_array_of_long_strings_takes_first(self):
        assert _clean_memory_content('[', ) == ""  # 半个括号 → 解析失败
        assert _clean_memory_content('["这是一条足够长的记忆"]') == "这是一条足够长的记忆"

    def test_broken_json_returns_empty(self):
        assert _clean_memory_content('{"content": "x"') == ""

    def test_too_long_returns_empty(self):
        """超过 200 字说明模型把整段对话塞回来了，不该当成一条记忆。"""
        assert _clean_memory_content("长" * 201) == ""
        assert _clean_memory_content("长" * 200) == "长" * 200

    def test_double_wrapped_json_returns_empty(self):
        """嵌套 JSON 解一层后仍是 JSON → 丢弃。"""
        inner = json.dumps({"content": {"nested": "x"}}, ensure_ascii=False)
        assert _clean_memory_content(inner) == ""

    def test_non_string_input_is_stringified(self):
        assert _clean_memory_content(123) == "123"


# ── _parse_memory_items ──────────────────────────────────


class TestParseMemoryItems:
    def test_array_of_objects(self):
        text = '[{"content": "他喜欢火锅"}, {"content": "他养了猫"}]'
        assert _parse_memory_items(text) == ["他喜欢火锅", "他养了猫"]

    def test_single_object(self):
        assert _parse_memory_items('{"content": "他喜欢火锅"}') == ["他喜欢火锅"]

    def test_code_fence(self):
        text = '```json\n[{"content": "a"}, {"content": "b"}]\n```'
        assert _parse_memory_items(text) == ["a", "b"]

    def test_empty_array(self):
        """「没有值得记的」明确输出 [] —— 返回空列表，不是 None。"""
        assert _parse_memory_items("[]") == []

    def test_empty_input(self):
        assert _parse_memory_items("") == []
        assert _parse_memory_items(None) == []

    def test_garbage(self):
        assert _parse_memory_items("完全不是 JSON") == []

    def test_scalar_returns_empty(self):
        assert _parse_memory_items('"scalar"') == []

    def test_array_of_strings(self):
        assert _parse_memory_items('["他喜欢火锅", "他养了猫"]') == ["他喜欢火锅", "他养了猫"]

    def test_skips_uncleanable_entries(self):
        text = '[{"content": "好的一条"}, {"content": ""}, {"content": "[1,2]"}]'
        assert _parse_memory_items(text) == ["好的一条"]

    def test_prose_wrapped_array(self):
        assert _parse_memory_items('结果如下：[{"content": "x"}] 完毕') == ["x"]


# ── summarize ────────────────────────────────────────────


class TestSummarize:
    @pytest.mark.asyncio
    async def test_too_few_conversations_returns_none(self):
        llm = FakeLLM('["x"]')
        assert await MemorySummarizer(llm).summarize([]) is None
        assert await MemorySummarizer(llm).summarize(
            [{"user": "a", "assistant": "b"}]
        ) is None
        assert llm.calls == []

    @pytest.mark.asyncio
    async def test_joins_entries_with_blank_line(self):
        llm = FakeLLM('[{"content": "第一条"}, {"content": "第二条"}]')
        convs = [{"user": f"u{i}", "assistant": f"a{i}"} for i in range(3)]
        result = await MemorySummarizer(llm).summarize(convs)
        assert result == "第一条\n\n第二条"

    @pytest.mark.asyncio
    async def test_empty_array_returns_none(self):
        llm = FakeLLM("[]")
        convs = [{"user": "u", "assistant": "a"}] * 3
        assert await MemorySummarizer(llm).summarize(convs) is None

    @pytest.mark.asyncio
    async def test_falls_back_to_plain_text(self):
        """模型没照格式来、吐了一句人话 —— 该保留而不是丢掉。"""
        llm = FakeLLM("他今天说他下个月要去成都出差。")
        convs = [{"user": "u", "assistant": "a"}] * 3
        assert await MemorySummarizer(llm).summarize(convs) == "他今天说他下个月要去成都出差。"

    @pytest.mark.asyncio
    async def test_json_fallback_is_not_stored_raw(self):
        """纯 JSON 但取不出 content —— 不能把整段 JSON 当记忆存下去。"""
        llm = FakeLLM('[{"foo": "bar"}, {"baz": "qux"}]')
        convs = [{"user": "u", "assistant": "a"}] * 3
        assert await MemorySummarizer(llm).summarize(convs) is None

    @pytest.mark.asyncio
    async def test_short_response_returns_none(self):
        llm = FakeLLM("短")
        convs = [{"user": "u", "assistant": "a"}] * 3
        assert await MemorySummarizer(llm).summarize(convs) is None

    @pytest.mark.asyncio
    async def test_llm_exception_returns_none(self):
        llm = FakeLLM(raises=RuntimeError("boom"))
        convs = [{"user": "u", "assistant": "a"}] * 3
        assert await MemorySummarizer(llm).summarize(convs) is None

    @pytest.mark.asyncio
    async def test_prompt_carries_transcript_and_date(self):
        """对话正文走 messages，写作要求走 system_prompt —— 两者别搞混。"""
        llm = FakeLLM("[]")
        convs = [{"user": "我想吃火锅", "assistant": "好呀"}] * 3
        await MemorySummarizer(llm).summarize(convs)
        call = llm.calls[0]
        transcript = call["messages"][0]["content"]
        assert "用户: 我想吃火锅" in transcript
        assert "助手: 好呀" in transcript
        prompt = call["system_prompt"]
        assert "只输出 JSON 数组" in prompt
        assert "以第一人称写日记" in prompt
        # 当前日期必须进 prompt，模型据此把「明天」推算成绝对日期
        assert datetime.now().strftime("%Y年") in prompt

    @pytest.mark.asyncio
    async def test_missing_keys_do_not_crash(self):
        llm = FakeLLM("[]")
        convs = [{}, {}, {}]
        assert await MemorySummarizer(llm).summarize(convs) is None


# ── extract_memory ───────────────────────────────────────


class TestExtractMemory:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        llm = FakeLLM('{"content": "他养了一只猫叫团子", "importance": 4, "category": "personal"}')
        result = await MemorySummarizer(llm).extract_memory("我养了只猫", "叫啥")
        assert result == {
            "content": "他养了一只猫叫团子",
            "importance": 4,
            "category": "personal",
        }

    @pytest.mark.asyncio
    async def test_null_returns_none(self):
        llm = FakeLLM("null")
        assert await MemorySummarizer(llm).extract_memory("嗯", "嗯嗯") is None

    @pytest.mark.asyncio
    async def test_empty_returns_none(self):
        llm = FakeLLM("   ")
        assert await MemorySummarizer(llm).extract_memory("u", "a") is None

    @pytest.mark.asyncio
    async def test_broken_json_returns_none(self):
        llm = FakeLLM('{"content": ')
        assert await MemorySummarizer(llm).extract_memory("u", "a") is None

    @pytest.mark.asyncio
    async def test_uncleanable_content_returns_none(self):
        """模型把一坨 JSON 塞进 content —— 清洗后为空就丢掉。"""
        llm = FakeLLM('{"content": "[1,2,3]", "importance": 4}')
        assert await MemorySummarizer(llm).extract_memory("u", "a") is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [('"4"', 4), ("100", 5), ("0", 1), ("-3", 1), ('"abc"', 3), ("null", 3)],
    )
    async def test_importance_is_clamped_int(self, raw, expected):
        """模型会给字符串或越界值 —— 不钳制会在 pipeline 里 `"4" >= 2` 抛 TypeError。"""
        payload = f'{{"content": "他喜欢火锅", "importance": {raw}}}'
        result = await MemorySummarizer(FakeLLM(payload)).extract_memory("u", "a")
        assert result["importance"] == expected
        assert isinstance(result["importance"], int)

    @pytest.mark.asyncio
    async def test_missing_importance_defaults_to_3(self):
        result = await MemorySummarizer(FakeLLM('{"content": "他喜欢火锅"}')).extract_memory("u", "a")
        assert result["importance"] == 3

    @pytest.mark.asyncio
    async def test_missing_category_defaults_to_other(self):
        result = await MemorySummarizer(FakeLLM('{"content": "他喜欢火锅"}')).extract_memory("u", "a")
        assert result["category"] == "other"

    @pytest.mark.asyncio
    async def test_null_category_defaults_to_other(self):
        payload = '{"content": "他喜欢火锅", "category": null}'
        result = await MemorySummarizer(FakeLLM(payload)).extract_memory("u", "a")
        assert result["category"] == "other"

    @pytest.mark.asyncio
    async def test_llm_exception_propagates(self):
        """这里必须抛 —— 调用方靠「抛异常 vs 返回 None」区分调用失败与「不值得记」。"""
        llm = FakeLLM(raises=RuntimeError("api down"))
        with pytest.raises(RuntimeError):
            await MemorySummarizer(llm).extract_memory("u", "a")

    @pytest.mark.asyncio
    async def test_prompt_includes_both_turns(self):
        llm = FakeLLM("null")
        await MemorySummarizer(llm).extract_memory("我明天面试", "加油")
        prompt = llm.calls[0]["system_prompt"]
        assert "他: 我明天面试" in prompt
        assert "你: 加油" in prompt


# ── retrieve_relevant ────────────────────────────────────


class TestRetrieveRelevant:
    @pytest.mark.asyncio
    async def test_no_memories_returns_empty(self):
        llm = FakeLLM("1")
        assert await MemorySummarizer(llm).retrieve_relevant("q", []) == []
        assert llm.calls == []

    @pytest.mark.asyncio
    async def test_few_candidates_skip_rerank(self):
        """召回数不超过 limit 就没必要再烧一次 LLM。"""
        llm = FakeLLM("1")
        result = await MemorySummarizer(llm).retrieve_relevant(
            "火锅", ["他喜欢吃火锅"], limit=5
        )
        assert result == ["他喜欢吃火锅"]
        assert llm.calls == []

    @pytest.mark.asyncio
    async def test_accepts_memory_objects(self):
        llm = FakeLLM("1")
        memories = [Memory(id="m1", content="他喜欢吃火锅", level=5)]
        assert await MemorySummarizer(llm).retrieve_relevant("火锅", memories) == [
            "他喜欢吃火锅"
        ]

    @pytest.mark.asyncio
    async def test_llm_rerank_used_when_enough_candidates(self):
        llm = FakeLLM("1")
        memories = ["他喜欢吃火锅", "楼下新开了火锅店", "他养了猫"]
        result = await MemorySummarizer(llm).retrieve_relevant("火锅", memories, limit=1)
        assert result == ["他喜欢吃火锅"]
        assert len(llm.calls) == 1

    @pytest.mark.asyncio
    async def test_llm_says_none_returns_empty(self):
        """模型明确回「无」= 判定都不相关，不能拿规则结果再塞回 prompt。"""
        llm = FakeLLM("无")
        memories = ["他喜欢吃火锅", "楼下新开了火锅店", "他还想再吃火锅"]
        assert await MemorySummarizer(llm).retrieve_relevant("火锅", memories, limit=1) == []

    @pytest.mark.asyncio
    async def test_llm_garbage_falls_back_to_level_sort(self):
        llm = FakeLLM("我不知道")
        memories = [
            Memory(id="m1", content="低分记忆", level=1),
            Memory(id="m2", content="高分记忆", level=5),
        ]
        memories += [Memory(id=f"m{i}", content=f"填充{i}", level=2) for i in range(20)]
        result = await MemorySummarizer(llm).retrieve_relevant("q", memories, limit=1)
        assert result == ["高分记忆"]

    @pytest.mark.asyncio
    async def test_llm_exception_falls_back_to_level_sort(self):
        llm = FakeLLM(raises=RuntimeError("boom"))
        memories = [Memory(id=f"m{i}", content=f"记忆{i}", level=i + 1) for i in range(10)]
        result = await MemorySummarizer(llm).retrieve_relevant("q", memories, limit=1)
        # 只有 level>=4 的进热度召回（记忆3..记忆9），按 level 降序取第一即 level 10
        assert result == ["记忆9"]

    @pytest.mark.asyncio
    async def test_no_llm_uses_level_sort(self):
        memories = [Memory(id=f"m{i}", content=f"记忆{i}", level=i + 1) for i in range(10)]
        assert await MemorySummarizer(None).retrieve_relevant("q", memories, limit=1) == [
            "记忆9"
        ]


# ── _multi_path_recall ───────────────────────────────────


class TestMultiPathRecall:
    def _summarizer(self):
        return MemorySummarizer(FakeLLM("1"))

    def _items(self, *contents, level=1, category="other", access_count=0):
        return [
            {"content": c, "level": level, "category": category, "access_count": access_count}
            for c in contents
        ]

    def test_keyword_hit_needs_two_chars(self):
        """至少 2 个字重合才算关键词命中 —— 1 个字全是噪声。"""
        s = self._summarizer()
        assert s._multi_path_recall("火锅", self._items("他喜欢吃火锅"))[0]["match_type"] == "keyword"
        assert s._multi_path_recall("锅", self._items("他喜欢吃火锅")) == []

    def test_keyword_ignores_punctuation_and_spaces(self):
        s = self._summarizer()
        hit = s._multi_path_recall("火 锅？", self._items("他喜欢吃火锅"))
        assert hit and hit[0]["match_type"] == "keyword"

    def test_category_hint(self):
        """分类召回独立于关键词 —— 记忆里不含查询原词也要能被分类带出来。"""
        s = self._summarizer()
        items = self._items("他在腾讯做后端", category="personal")
        hit = s._multi_path_recall("他生日是几号", items)
        assert hit and hit[0]["match_type"] == "category"

    def test_category_hint_ignored_for_other_category(self):
        s = self._summarizer()
        items = self._items("他在腾讯做后端", category="event")
        assert s._multi_path_recall("他生日是几号", items) == []

    def test_hot_recall_by_level(self):
        s = self._summarizer()
        hit = s._multi_path_recall("完全无关的问句", self._items("他喜欢吃火锅", level=5))
        assert hit and hit[0]["match_type"] == "hot"

    def test_hot_recall_by_access_count(self):
        s = self._summarizer()
        hit = s._multi_path_recall(
            "完全无关的问句", self._items("他喜欢吃火锅", access_count=3)
        )
        assert hit and hit[0]["match_type"] == "hot"

    def test_cold_memory_is_not_recalled(self):
        s = self._summarizer()
        assert s._multi_path_recall("完全无关的问句", self._items("他喜欢吃火锅")) == []

    def test_dedupes_by_content(self):
        s = self._summarizer()
        items = self._items("他喜欢吃火锅", level=5)
        hit = s._multi_path_recall("火锅", items)
        assert len(hit) == 1
        assert hit[0]["match_type"] == "keyword"  # 先到的路径赢

    def test_respects_recall_limit(self):
        s = self._summarizer()
        items = self._items(*[f"记忆{i}" for i in range(40)], level=5)
        assert len(s._multi_path_recall("x", items, recall_limit=15)) <= 15

    def test_does_not_mutate_input(self):
        s = self._summarizer()
        items = self._items("他喜欢吃火锅", level=5)
        s._multi_path_recall("火锅", items)
        assert "match_type" not in items[0]

    def test_empty(self):
        assert self._summarizer()._multi_path_recall("q", []) == []


# ── _llm_rerank ─────────────────────────────────────────


class TestLlmRerank:
    @pytest.mark.asyncio
    async def test_parses_numbers_in_order(self):
        llm = FakeLLM("3,1,2")
        candidates = [{"content": f"c{i}"} for i in range(1, 4)]
        assert await MemorySummarizer(llm)._llm_rerank("q", candidates, 3) == [
            "c3", "c1", "c2"
        ]

    @pytest.mark.asyncio
    async def test_respects_limit(self):
        llm = FakeLLM("1,2,3")
        candidates = [{"content": f"c{i}"} for i in range(1, 4)]
        assert await MemorySummarizer(llm)._llm_rerank("q", candidates, 2) == ["c1", "c2"]

    @pytest.mark.asyncio
    async def test_ignores_out_of_range_numbers(self):
        llm = FakeLLM("1,99,2")
        candidates = [{"content": "c1"}, {"content": "c2"}]
        assert await MemorySummarizer(llm)._llm_rerank("q", candidates, 5) == ["c1", "c2"]

    @pytest.mark.asyncio
    async def test_none_means_failure(self):
        """返回 None 表示调用失败（走规则回退），与「明确无相关」的空列表不同。"""
        llm = FakeLLM("不知道")
        assert await MemorySummarizer(llm)._llm_rerank("q", [{"content": "c"}], 1) is None

    @pytest.mark.asyncio
    async def test_all_out_of_range_returns_none(self):
        llm = FakeLLM("99,100")
        assert await MemorySummarizer(llm)._llm_rerank("q", [{"content": "c"}], 1) is None

    @pytest.mark.asyncio
    async def test_explicit_none_returns_empty_list(self):
        llm = FakeLLM("无")
        assert await MemorySummarizer(llm)._llm_rerank("q", [{"content": "c"}], 1) == []

    @pytest.mark.asyncio
    async def test_exception_returns_none(self):
        llm = FakeLLM(raises=RuntimeError("boom"))
        assert await MemorySummarizer(llm)._llm_rerank("q", [{"content": "c"}], 1) is None

    @pytest.mark.asyncio
    async def test_prompt_lists_candidates(self):
        llm = FakeLLM("1")
        await MemorySummarizer(llm)._llm_rerank("火锅", [{"content": "他喜欢吃火锅"}], 1)
        assert "1. 他喜欢吃火锅" in llm.calls[0]["system_prompt"]
        assert "用户问题：火锅" in llm.calls[0]["system_prompt"]
