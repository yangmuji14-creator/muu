"""core/llm/base.py 的单元测试。

覆盖三层：
1. 纯函数：``_field`` / ``_normalize_tool_call`` / ``_is_retryable`` / ``_litellm_kwargs``
2. 重试与密钥解析：``_retry`` / ``_resolve_api_key``
3. 三个调用接口：``chat`` / ``chat_stream`` / ``chat_stream_events``（litellm 全替身）

约定：不联网、不读真实 config/ 与 data/。litellm.acompletion 一律换成假函数。
"""

from __future__ import annotations

import types

import pytest

import core.llm.base as base_mod
from core.llm.base import (
    BaseLLM,
    LLMResponse,
    LLMStreamEvent,
    _field,
    _normalize_tool_call,
    reset_llm_request_id,
    set_llm_request_id,
)


class DummyLLM(BaseLLM):
    """最小可实例化子类，只补上抽象方法。"""

    def _build_model_id(self) -> str:
        return f"dummy/{self.model_name}"


# ---------------------------------------------------------------- 构造替身


def make_llm(**overrides) -> DummyLLM:
    kwargs = {
        "model_name": "m1",
        "api_key": "sk-test",
        "base_url": "https://example.invalid/v1",
        "max_tokens": 128,
        "temperature": 0.7,
        "max_retries": 0,
    }
    kwargs.update(overrides)
    return DummyLLM(**kwargs)


def make_usage(
    prompt: int = 3,
    completion: int = 4,
    total: int = 7,
    cache_read: int | None = None,
    cache_creation: int | None = None,
    cached_tokens: int | None = None,
):
    usage = types.SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
    )
    if cache_read is not None:
        usage.cache_read_input_tokens = cache_read
    if cache_creation is not None:
        usage.cache_creation_input_tokens = cache_creation
    if cached_tokens is not None:
        usage.prompt_tokens_details = types.SimpleNamespace(cached_tokens=cached_tokens)
    return usage


def make_response(
    content: str = "hi",
    finish_reason: str = "stop",
    usage=None,
    tool_calls=None,
):
    message = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = types.SimpleNamespace(message=message, finish_reason=finish_reason)
    return types.SimpleNamespace(choices=[choice], usage=usage)


def make_chunk(content=None, reasoning=None, tool_calls=None, usage=None, no_choices=False):
    if no_choices:
        return types.SimpleNamespace(choices=[], usage=usage)
    delta = types.SimpleNamespace(
        content=content,
        reasoning_content=reasoning,
        tool_calls=tool_calls,
    )
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(delta=delta)],
        usage=usage,
    )


async def stream_of(chunks):
    for chunk in chunks:
        yield chunk


def patch_acompletion(monkeypatch, handler):
    """把 litellm.acompletion 换成 handler(kwargs) -> 响应/异步生成器。"""

    async def fake(**kwargs):
        return handler(kwargs)

    monkeypatch.setattr(base_mod.litellm, "acompletion", fake)


# ---------------------------------------------------------------- 1. _field


class TestField:
    def test_dict_hit(self):
        assert _field({"a": 1}, "a") == 1

    def test_dict_miss_returns_default(self):
        assert _field({"a": 1}, "b") is None
        assert _field({"a": 1}, "b", "fallback") == "fallback"

    def test_object_attribute(self):
        assert _field(types.SimpleNamespace(a=2), "a") == 2

    def test_object_missing_returns_default(self):
        assert _field(types.SimpleNamespace(a=2), "b", 0) == 0

    def test_none_input_returns_default(self):
        assert _field(None, "a", "x") == "x"


# ------------------------------------------------ 2. _normalize_tool_call


class TestNormalizeToolCall:
    def test_dict_arguments_kept(self):
        call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "clock", "arguments": {"tz": "UTC"}},
        }
        out = _normalize_tool_call(call)
        assert out == {
            "id": "call_1",
            "type": "function",
            "name": "clock",
            "arguments": {"tz": "UTC"},
        }

    def test_string_arguments_parsed(self):
        call = {"function": {"name": "clock", "arguments": '{"tz": "UTC"}'}}
        assert _normalize_tool_call(call)["arguments"] == {"tz": "UTC"}

    def test_broken_json_arguments_become_empty_dict(self):
        call = {"function": {"name": "clock", "arguments": "{not json"}}
        assert _normalize_tool_call(call)["arguments"] == {}

    def test_none_arguments_becomes_empty_dict(self):
        call = {"function": {"name": "clock", "arguments": None}}
        assert _normalize_tool_call(call)["arguments"] == {}

    def test_missing_id_uses_fallback_index(self):
        call = {"function": {"name": "clock", "arguments": "{}"}}
        assert _normalize_tool_call(call, 3)["id"] == "call_3"

    def test_default_type_is_function(self):
        out = _normalize_tool_call({"function": {"name": "x"}})
        assert out["type"] == "function"

    def test_missing_function_yields_empty_name(self):
        out = _normalize_tool_call({})
        assert out["name"] == ""
        assert out["arguments"] == {}

    def test_object_input_supported(self):
        call = types.SimpleNamespace(
            id="call_9",
            type="function",
            function=types.SimpleNamespace(name="note", arguments='{"text": "hi"}'),
        )
        out = _normalize_tool_call(call)
        assert out["id"] == "call_9"
        assert out["name"] == "note"
        assert out["arguments"] == {"text": "hi"}


# ------------------------------------------------------------ 3. 数据模型


class TestDataclasses:
    def test_llm_response_defaults(self):
        r = LLMResponse(content="a", model="m")
        assert r.usage == {}
        assert r.metadata == {}

    def test_llm_response_usage_not_shared(self):
        a = LLMResponse(content="a", model="m")
        b = LLMResponse(content="b", model="m")
        a.usage["x"] = 1
        assert b.usage == {}

    def test_stream_event_defaults(self):
        e = LLMStreamEvent(kind="content")
        assert e.content == ""
        assert e.tool_call is None
        assert e.reasoning == ""
        assert e.usage == {}


# ---------------------------------------------------------- 4. _is_retryable


class TestIsRetryable:
    @pytest.mark.parametrize(
        "message",
        [
            "Connection timed out",
            "rate limit exceeded",
            "server error 502",
            "Error 429",
            "connection reset by peer",
            "The server is overloaded",
            "EOF occurred in violation of protocol",
            "please try again later",
            "HTTP 503",
        ],
    )
    def test_retryable(self, message):
        assert BaseLLM._is_retryable(RuntimeError(message)) is True

    @pytest.mark.parametrize(
        "message",
        [
            "AuthenticationError: invalid api_key",
            "HTTP 401 unauthorized",
            "HTTP 403 forbidden",
            "invalid_request_error: bad param",
            "insufficient_quota",
        ],
    )
    def test_non_retryable_wins(self, message):
        assert BaseLLM._is_retryable(RuntimeError(message)) is False

    def test_non_retryable_keyword_beats_retryable_one(self):
        # 同时含 "timeout"（可重试）与 "auth"（不可重试）→ 判不可重试
        assert BaseLLM._is_retryable(RuntimeError("auth timeout")) is False

    def test_unknown_error_not_retryable(self):
        assert BaseLLM._is_retryable(ValueError("something odd")) is False

    def test_case_insensitive(self):
        assert BaseLLM._is_retryable(RuntimeError("TIMEOUT")) is True


# --------------------------------------------------------------- 5. _retry


class TestRetry:
    async def test_success_first_attempt(self):
        llm = make_llm(max_retries=2)
        calls = []

        async def factory():
            calls.append(1)
            return "ok"

        assert await llm._retry(factory, "op") == "ok"
        assert len(calls) == 1

    async def test_retries_then_succeeds(self, monkeypatch):
        slept = []

        async def fake_sleep(delay):
            slept.append(delay)

        monkeypatch.setattr(base_mod.asyncio, "sleep", fake_sleep)
        llm = make_llm(max_retries=2)
        attempts = []

        async def factory():
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("timeout")
            return "done"

        assert await llm._retry(factory, "op") == "done"
        assert len(attempts) == 3
        assert len(slept) == 2
        # 指数退避：1.0*2^0 + jitter，1.0*2^1 + jitter
        assert slept[0] >= 1.0
        assert slept[1] >= 2.0

    async def test_exhausts_and_raises_last_error(self, monkeypatch):
        async def fake_sleep(delay):
            return None

        monkeypatch.setattr(base_mod.asyncio, "sleep", fake_sleep)
        llm = make_llm(max_retries=1)
        attempts = []

        async def factory():
            attempts.append(1)
            raise RuntimeError(f"timeout {len(attempts)}")

        with pytest.raises(RuntimeError) as exc:
            await llm._retry(factory, "op")
        assert "timeout 2" in str(exc.value)
        assert len(attempts) == 2

    async def test_non_retryable_raises_immediately(self, monkeypatch):
        async def fake_sleep(delay):
            raise AssertionError("不该 sleep")

        monkeypatch.setattr(base_mod.asyncio, "sleep", fake_sleep)
        llm = make_llm(max_retries=3)
        attempts = []

        async def factory():
            attempts.append(1)
            raise RuntimeError("invalid api_key")

        with pytest.raises(RuntimeError):
            await llm._retry(factory, "op")
        assert len(attempts) == 1

    async def test_zero_retries_single_attempt(self):
        llm = make_llm(max_retries=0)
        attempts = []

        async def factory():
            attempts.append(1)
            raise RuntimeError("timeout")

        with pytest.raises(RuntimeError):
            await llm._retry(factory, "op")
        assert len(attempts) == 1


# ------------------------------------------------------- 6. _resolve_api_key


class TestResolveApiKey:
    def test_instance_key_wins(self, monkeypatch):
        monkeypatch.setenv("DUMMY_API_KEY", "from-env")
        llm = make_llm(api_key="sk-instance")
        assert llm._resolve_api_key("dummy/m1") == "sk-instance"

    def test_env_fallback(self, monkeypatch):
        monkeypatch.setenv("DUMMY_API_KEY", "from-env")
        llm = make_llm(api_key="")
        assert llm._resolve_api_key("dummy/m1") == "from-env"

    def test_env_missing_returns_empty(self, monkeypatch):
        monkeypatch.delenv("DUMMY_API_KEY", raising=False)
        llm = make_llm(api_key="")
        assert llm._resolve_api_key("dummy/m1") == ""

    def test_prefix_upper_cased(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        llm = make_llm(api_key="")
        assert llm._resolve_api_key("deepseek/deepseek-chat") == "sk-ds"


# ------------------------------------------------------ 7. _litellm_kwargs


class TestLitellmKwargs:
    def test_defaults_from_instance(self):
        llm = make_llm(max_tokens=256, temperature=0.3)
        out = llm._litellm_kwargs({})
        assert out["max_tokens"] == 256
        assert out["temperature"] == 0.3
        assert out["presence_penalty"] == 0.3
        assert out["frequency_penalty"] == 0.3
        assert out["timeout"] == 120

    def test_overrides_win(self):
        llm = make_llm()
        out = llm._litellm_kwargs({"max_tokens": 9, "timeout": 5})
        assert out["max_tokens"] == 9
        assert out["timeout"] == 5

    def test_pops_known_keys_from_caller_dict(self):
        """回归点：必须 pop 而不是 get。

        早前用 get() 时，调用方随后 `**kwargs` 展开会把同一个参数传两次，
        litellm 直接报 "got multiple values for keyword argument 'max_tokens'"。
        """
        llm = make_llm()
        caller = {"max_tokens": 64, "temperature": 0.1, "stream": True}
        out = llm._litellm_kwargs(caller)
        assert out["max_tokens"] == 64
        assert "max_tokens" not in caller
        assert "temperature" not in caller
        # 未知参数原样留下，供调用方透传
        assert caller == {"stream": True}

    def test_empty_caller_dict_not_mutated_beyond_pops(self):
        llm = make_llm()
        caller: dict = {}
        llm._litellm_kwargs(caller)
        assert caller == {}


# ------------------------------------------------------------ 8. chat()


class TestChat:
    async def test_basic_content_and_metadata(self, monkeypatch):
        patch_acompletion(monkeypatch, lambda kw: make_response("你好", usage=make_usage()))
        llm = make_llm()
        result = await llm.chat([{"role": "user", "content": "hi"}])
        assert isinstance(result, LLMResponse)
        assert result.content == "你好"
        assert result.model == "dummy/m1"
        assert result.usage == {
            "prompt_tokens": 3,
            "completion_tokens": 4,
            "total_tokens": 7,
        }
        assert result.metadata["finish_reason"] == "stop"
        assert result.metadata["tool_calls"] == []

    async def test_system_prompt_prepended(self, monkeypatch):
        seen = {}

        def handler(kw):
            seen["messages"] = kw["messages"]
            return make_response()

        patch_acompletion(monkeypatch, handler)
        llm = make_llm()
        await llm.chat([{"role": "user", "content": "hi"}], system_prompt="你是慕")
        assert seen["messages"][0] == {"role": "system", "content": "你是慕"}
        assert seen["messages"][1]["content"] == "hi"

    async def test_no_system_prompt_keeps_messages(self, monkeypatch):
        seen = {}

        def handler(kw):
            seen["messages"] = kw["messages"]
            return make_response()

        patch_acompletion(monkeypatch, handler)
        llm = make_llm()
        await llm.chat([{"role": "user", "content": "hi"}])
        assert len(seen["messages"]) == 1

    async def test_model_id_and_base_url_passed(self, monkeypatch):
        seen = {}

        def handler(kw):
            seen.update(kw)
            return make_response()

        patch_acompletion(monkeypatch, handler)
        llm = make_llm()
        await llm.chat([{"role": "user", "content": "hi"}])
        assert seen["model"] == "dummy/m1"
        assert seen["base_url"] == "https://example.invalid/v1"
        assert seen["api_key"] == "sk-test"

    async def test_none_content_becomes_empty_string(self, monkeypatch):
        patch_acompletion(monkeypatch, lambda kw: make_response(content=None))
        llm = make_llm()
        assert (await llm.chat([{"role": "user", "content": "hi"}])).content == ""

    async def test_usage_none_gives_zero_tokens(self, monkeypatch):
        patch_acompletion(monkeypatch, lambda kw: make_response(usage=None))
        llm = make_llm()
        result = await llm.chat([{"role": "user", "content": "hi"}])
        assert result.usage == {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    async def test_cache_fields_recorded(self, monkeypatch):
        usage = make_usage(cache_read=11, cache_creation=12, cached_tokens=13)
        patch_acompletion(monkeypatch, lambda kw: make_response(usage=usage))
        llm = make_llm()
        result = await llm.chat([{"role": "user", "content": "hi"}])
        assert result.usage["cache_read_input_tokens"] == 11
        assert result.usage["cache_creation_input_tokens"] == 12
        assert result.usage["cached_tokens"] == 13

    async def test_tool_calls_normalized(self, monkeypatch):
        raw = [
            types.SimpleNamespace(
                id="call_a",
                type="function",
                function=types.SimpleNamespace(name="clock", arguments='{"tz":"UTC"}'),
            )
        ]
        patch_acompletion(monkeypatch, lambda kw: make_response(tool_calls=raw))
        llm = make_llm()
        result = await llm.chat([{"role": "user", "content": "hi"}])
        assert result.metadata["tool_calls"] == [
            {
                "id": "call_a",
                "type": "function",
                "name": "clock",
                "arguments": {"tz": "UTC"},
            }
        ]

    async def test_error_reraised(self, monkeypatch):
        def handler(kw):
            raise RuntimeError("invalid api_key")

        patch_acompletion(monkeypatch, handler)
        llm = make_llm()
        with pytest.raises(RuntimeError, match="invalid api_key"):
            await llm.chat([{"role": "user", "content": "hi"}])

    async def test_retryable_error_is_retried(self, monkeypatch):
        slept = []

        async def fake_sleep(delay):
            slept.append(delay)

        monkeypatch.setattr(base_mod.asyncio, "sleep", fake_sleep)
        attempts = []

        def handler(kw):
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("rate limit")
            return make_response("ok")

        patch_acompletion(monkeypatch, handler)
        llm = make_llm(max_retries=1)
        result = await llm.chat([{"role": "user", "content": "hi"}])
        assert result.content == "ok"
        assert len(attempts) == 2
        assert len(slept) == 1


# ------------------------------------------------------ 9. chat_stream()


class TestChatStream:
    async def test_yields_tokens(self, monkeypatch):
        chunks = [make_chunk("你"), make_chunk("好")]
        patch_acompletion(monkeypatch, lambda kw: stream_of(chunks))
        llm = make_llm()
        got = [t async for t in llm.chat_stream([{"role": "user", "content": "hi"}])]
        assert got == ["你", "好"]

    async def test_skips_empty_content(self, monkeypatch):
        chunks = [make_chunk(None), make_chunk("a"), make_chunk("")]
        patch_acompletion(monkeypatch, lambda kw: stream_of(chunks))
        llm = make_llm()
        got = [t async for t in llm.chat_stream([{"role": "user", "content": "hi"}])]
        assert got == ["a"]

    async def test_stream_true_passed(self, monkeypatch):
        seen = {}

        def handler(kw):
            seen.update(kw)
            return stream_of([make_chunk("x")])

        patch_acompletion(monkeypatch, handler)
        llm = make_llm()
        [t async for t in llm.chat_stream([{"role": "user", "content": "hi"}])]
        assert seen["stream"] is True

    async def test_system_prompt_prepended(self, monkeypatch):
        seen = {}

        def handler(kw):
            seen["messages"] = kw["messages"]
            return stream_of([make_chunk("x")])

        patch_acompletion(monkeypatch, handler)
        llm = make_llm()
        [t async for t in llm.chat_stream([{"role": "user", "content": "hi"}], system_prompt="S")]
        assert seen["messages"][0]["role"] == "system"

    async def test_error_before_first_token_retried(self, monkeypatch):
        slept = []

        async def fake_sleep(delay):
            slept.append(delay)

        monkeypatch.setattr(base_mod.asyncio, "sleep", fake_sleep)
        attempts = []

        def handler(kw):
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("connection reset")
            return stream_of([make_chunk("ok")])

        patch_acompletion(monkeypatch, handler)
        llm = make_llm(max_retries=1)
        got = [t async for t in llm.chat_stream([{"role": "user", "content": "hi"}])]
        assert got == ["ok"]
        assert len(attempts) == 2

    async def test_error_after_first_token_raised(self, monkeypatch):
        """已经吐出 token 就不能重试，否则会把内容重复给用户。"""

        async def bad_stream():
            yield make_chunk("a")
            raise RuntimeError("timeout")

        patch_acompletion(monkeypatch, lambda kw: bad_stream())
        llm = make_llm(max_retries=3)
        got = []
        with pytest.raises(RuntimeError, match="timeout"):
            async for token in llm.chat_stream([{"role": "user", "content": "hi"}]):
                got.append(token)
        assert got == ["a"]

    async def test_non_retryable_raised_immediately(self, monkeypatch):
        def handler(kw):
            raise RuntimeError("invalid api_key")

        patch_acompletion(monkeypatch, handler)
        llm = make_llm(max_retries=2)
        with pytest.raises(RuntimeError, match="invalid api_key"):
            async for _ in llm.chat_stream([{"role": "user", "content": "hi"}]):
                pass


# ---------------------------------------------- 10. chat_stream_events()


class TestChatStreamEvents:
    async def test_content_events(self, monkeypatch):
        chunks = [make_chunk("你"), make_chunk("好")]
        patch_acompletion(monkeypatch, lambda kw: stream_of(chunks))
        llm = make_llm()
        events = [
            e async for e in llm.chat_stream_events([{"role": "user", "content": "hi"}])
        ]
        assert [e.kind for e in events] == ["content", "content"]
        assert [e.content for e in events] == ["你", "好"]

    async def test_reasoning_events(self, monkeypatch):
        chunks = [make_chunk(reasoning="想一想"), make_chunk("答")]
        patch_acompletion(monkeypatch, lambda kw: stream_of(chunks))
        llm = make_llm()
        events = [
            e async for e in llm.chat_stream_events([{"role": "user", "content": "hi"}])
        ]
        assert events[0].kind == "reasoning"
        assert events[0].reasoning == "想一想"
        assert events[1].kind == "content"

    async def test_tool_call_accumulated_across_chunks(self, monkeypatch):
        def tc(index, cid="", name="", args=""):
            return types.SimpleNamespace(
                index=index,
                id=cid,
                function=types.SimpleNamespace(name=name, arguments=args),
            )

        chunks = [
            make_chunk(tool_calls=[tc(0, cid="call_1", name="clock", args='{"tz"')]),
            make_chunk(tool_calls=[tc(0, args=':"UTC"}')]),
        ]
        patch_acompletion(monkeypatch, lambda kw: stream_of(chunks))
        llm = make_llm()
        events = [
            e async for e in llm.chat_stream_events([{"role": "user", "content": "hi"}])
        ]
        assert len(events) == 1
        assert events[0].kind == "tool_call"
        assert events[0].tool_call["id"] == "call_1"
        assert events[0].tool_call["name"] == "clock"
        assert events[0].tool_call["arguments"] == {"tz": "UTC"}

    async def test_tool_call_dict_argument_chunk_serialized(self, monkeypatch):
        chunk = make_chunk(
            tool_calls=[
                types.SimpleNamespace(
                    index=0,
                    id="c",
                    function=types.SimpleNamespace(name="n", arguments={"k": "v"}),
                )
            ]
        )
        patch_acompletion(monkeypatch, lambda kw: stream_of([chunk]))
        llm = make_llm()
        events = [
            e async for e in llm.chat_stream_events([{"role": "user", "content": "hi"}])
        ]
        assert events[0].tool_call["arguments"] == {"k": "v"}

    async def test_usage_only_chunk_recorded(self, monkeypatch):
        """末位只带 usage、choices 为空的 chunk 不该产出事件，但要记用量。"""

        chunks = [
            make_chunk("x"),
            make_chunk(no_choices=True, usage=make_usage(prompt=10, completion=20, total=30)),
        ]
        patch_acompletion(monkeypatch, lambda kw: stream_of(chunks))
        llm = make_llm()
        events = [
            e async for e in llm.chat_stream_events([{"role": "user", "content": "hi"}])
        ]
        assert len(events) == 1
        assert events[0].content == "x"

    async def test_usage_attached_to_chunk_with_choices(self, monkeypatch):
        chunk = make_chunk("x", usage=make_usage(cache_read=5, cached_tokens=6))
        patch_acompletion(monkeypatch, lambda kw: stream_of([chunk]))
        llm = make_llm()
        events = [
            e async for e in llm.chat_stream_events([{"role": "user", "content": "hi"}])
        ]
        assert len(events) == 1

    async def test_stream_options_added_by_default(self, monkeypatch):
        seen = {}

        def handler(kw):
            seen.update(kw)
            return stream_of([make_chunk("x")])

        patch_acompletion(monkeypatch, handler)
        llm = make_llm()
        [e async for e in llm.chat_stream_events([{"role": "user", "content": "hi"}])]
        assert seen["stream_options"] == {"include_usage": True}

    async def test_stream_options_fallback_on_failure(self, monkeypatch):
        """老式 OpenAI 兼容服务端不认 stream_options → 去掉后重试一次。"""

        seen = []

        def handler(kw):
            seen.append(dict(kw))
            if "stream_options" in kw:
                raise RuntimeError("unsupported parameter: stream_options")
            return stream_of([make_chunk("ok")])

        patch_acompletion(monkeypatch, handler)
        llm = make_llm()
        events = [
            e async for e in llm.chat_stream_events([{"role": "user", "content": "hi"}])
        ]
        assert len(seen) == 2
        assert "stream_options" in seen[0]
        assert "stream_options" not in seen[1]
        assert events[0].content == "ok"

    async def test_caller_supplied_stream_options_not_retried(self, monkeypatch):
        """调用方自己传了 stream_options 时不做降级重试，直接抛。"""

        attempts = []

        def handler(kw):
            attempts.append(1)
            raise RuntimeError("boom")

        patch_acompletion(monkeypatch, handler)
        llm = make_llm()
        with pytest.raises(RuntimeError, match="boom"):
            async for _ in llm.chat_stream_events(
                [{"role": "user", "content": "hi"}],
                stream_options={"include_usage": False},
            ):
                pass
        assert len(attempts) == 1

    async def test_retry_without_stream_options_also_fails(self, monkeypatch):
        attempts = []

        def handler(kw):
            attempts.append(1)
            raise RuntimeError("always down")

        patch_acompletion(monkeypatch, handler)
        llm = make_llm()
        with pytest.raises(RuntimeError, match="always down"):
            async for _ in llm.chat_stream_events([{"role": "user", "content": "hi"}]):
                pass
        assert len(attempts) == 2

    async def test_system_prompt_prepended(self, monkeypatch):
        seen = {}

        def handler(kw):
            seen["messages"] = kw["messages"]
            return stream_of([make_chunk("x")])

        patch_acompletion(monkeypatch, handler)
        llm = make_llm()
        [
            e
            async for e in llm.chat_stream_events(
                [{"role": "user", "content": "hi"}], system_prompt="S"
            )
        ]
        assert seen["messages"][0] == {"role": "system", "content": "S"}

    async def test_multiple_tool_calls_sorted_by_index(self, monkeypatch):
        def tc(index, name):
            return types.SimpleNamespace(
                index=index,
                id=f"call_{index}",
                function=types.SimpleNamespace(name=name, arguments="{}"),
            )

        chunk = make_chunk(tool_calls=[tc(1, "second"), tc(0, "first")])
        patch_acompletion(monkeypatch, lambda kw: stream_of([chunk]))
        llm = make_llm()
        events = [
            e async for e in llm.chat_stream_events([{"role": "user", "content": "hi"}])
        ]
        assert [e.tool_call["name"] for e in events] == ["first", "second"]

    async def test_tool_call_without_id_gets_fallback(self, monkeypatch):
        chunk = make_chunk(
            tool_calls=[
                types.SimpleNamespace(
                    index=0,
                    id="",
                    function=types.SimpleNamespace(name="clock", arguments="{}"),
                )
            ]
        )
        patch_acompletion(monkeypatch, lambda kw: stream_of([chunk]))
        llm = make_llm()
        events = [
            e async for e in llm.chat_stream_events([{"role": "user", "content": "hi"}])
        ]
        assert events[0].tool_call["id"] == "call_0"

    async def test_empty_chunk_without_usage_ignored(self, monkeypatch):
        """choices 为空、usage 也为空的 chunk 既不产出事件也不崩。"""
        chunks = [make_chunk("x"), make_chunk(no_choices=True, usage=None)]
        patch_acompletion(monkeypatch, lambda kw: stream_of(chunks))
        llm = make_llm()
        events = [
            e async for e in llm.chat_stream_events([{"role": "user", "content": "hi"}])
        ]
        assert len(events) == 1

    async def test_usage_only_chunk_records_cached_tokens(self, monkeypatch):
        usage = make_usage(cache_read=1, cached_tokens=2)
        chunks = [make_chunk(no_choices=True, usage=usage)]
        patch_acompletion(monkeypatch, lambda kw: stream_of(chunks))
        llm = make_llm()
        events = [
            e async for e in llm.chat_stream_events([{"role": "user", "content": "hi"}])
        ]
        assert events == []

    async def test_reasoning_after_content_keeps_first_token_ms(self, monkeypatch):
        """先有 content 再出 reasoning，首个 token 时间不能被覆盖。"""
        chunks = [make_chunk("a"), make_chunk(reasoning="想想")]
        patch_acompletion(monkeypatch, lambda kw: stream_of(chunks))
        llm = make_llm()
        events = [
            e async for e in llm.chat_stream_events([{"role": "user", "content": "hi"}])
        ]
        assert [e.kind for e in events] == ["content", "reasoning"]

    async def test_cached_tokens_recorded_on_delta_chunk(self, monkeypatch):
        chunk = make_chunk("x", usage=make_usage(cached_tokens=42))
        patch_acompletion(monkeypatch, lambda kw: stream_of([chunk]))
        llm = make_llm()
        [
            e
            async for e in llm.chat_stream_events([{"role": "user", "content": "hi"}])
        ]

    async def test_usage_without_details_on_delta_chunk(self, monkeypatch):
        """带 choices 的 chunk 只有 prompt/completion/total，没有 prompt_tokens_details。"""
        usage = types.SimpleNamespace(
            prompt_tokens=1, completion_tokens=2, total_tokens=3
        )
        chunk = make_chunk("x", usage=usage)
        patch_acompletion(monkeypatch, lambda kw: stream_of([chunk]))
        llm = make_llm()
        events = [
            e async for e in llm.chat_stream_events([{"role": "user", "content": "hi"}])
        ]
        assert events[0].content == "x"

    async def test_broken_arguments_yield_empty_dict(self, monkeypatch):
        chunk = make_chunk(
            tool_calls=[
                types.SimpleNamespace(
                    index=0,
                    id="c",
                    function=types.SimpleNamespace(name="clock", arguments="{broken"),
                )
            ]
        )
        patch_acompletion(monkeypatch, lambda kw: stream_of([chunk]))
        llm = make_llm()
        events = [
            e async for e in llm.chat_stream_events([{"role": "user", "content": "hi"}])
        ]
        assert events[0].tool_call["arguments"] == {}


# ---------------------------------------------------- 11. request id 上下文


class TestRequestId:
    def test_set_and_reset(self):
        token = set_llm_request_id("req-1")
        try:
            assert base_mod._pending_request_id.get() == "req-1"
        finally:
            reset_llm_request_id(token)
        assert base_mod._pending_request_id.get() == ""

    def test_none_coerced_to_empty(self):
        token = set_llm_request_id(None)
        try:
            assert base_mod._pending_request_id.get() == ""
        finally:
            reset_llm_request_id(token)


# ------------------------------------------------------ 12. 构造与属性


class TestConstructor:
    def test_defaults(self):
        llm = DummyLLM(model_name="m", api_key="k")
        assert llm.base_url is None
        assert llm.max_tokens == 2048
        assert llm.temperature == 1.0
        assert llm.max_retries == 2
        assert llm.presence_penalty == 0.3
        assert llm.frequency_penalty == 0.3

    def test_overrides(self):
        llm = make_llm(presence_penalty=0.0, frequency_penalty=0.0)
        assert llm.presence_penalty == 0.0
        assert llm.frequency_penalty == 0.0

    def test_build_model_id_abstract(self):
        with pytest.raises(TypeError):
            BaseLLM(model_name="m", api_key="k")  # type: ignore[abstract]
