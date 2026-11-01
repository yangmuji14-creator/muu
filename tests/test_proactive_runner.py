"""ProactiveRunner：主动消息的调度层。

这一层存在的唯一理由：`ProactiveMessenger` 的触发逻辑写得很全，但此前只有
CLI 的输入超时分支在调它 —— 网页端和微信上 `proactive_enabled: true` 等于
没配。调度层补上「遍历会话 → 触发 → 生成 → 投递」这条链。

这里全部用替身，不联网、不碰真实 data/。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.conversation.binding import ConversationBinding
from core.proactive_runner import ProactiveRunner, ProactiveTarget


# ── 替身 ────────────────────────────────────────────────────────


class FakeStore:
    def __init__(self, bindings=None):
        self._bindings = bindings or []

    def list(self):
        return list(self._bindings)


class FakeChatHistory:
    def __init__(self, messages_by_user=None):
        self._messages = messages_by_user or {}
        self.added: list[dict] = []

    def get_messages(self, user_id):
        return self._messages.get(user_id, [])

    def add_message(self, user_id, role, content, **kwargs):
        self.added.append(
            {"user_id": user_id, "role": role, "content": content, **kwargs}
        )


class FakeProactive:
    def __init__(self, trigger=None, text="嗯，在干嘛", enabled=True, raises=False):
        self.enabled = enabled
        self._trigger = trigger
        self._text = text
        self._raises = raises
        self.checked: list[dict] = []
        self.generated: list[dict] = []

    def check_proactive_messages(self, user_id, persona_id, scope_id=None):
        if self._raises:
            raise RuntimeError("check boom")
        self.checked.append(
            {"user_id": user_id, "persona_id": persona_id, "scope_id": scope_id}
        )
        return self._trigger

    async def generate_message(self, trigger, user_id, persona_id, scope_id=None):
        self.generated.append(
            {"trigger": trigger, "user_id": user_id, "scope_id": scope_id}
        )
        return self._text


def _binding(conversation_id="conv_6", platform="web", account_id="",
             contact_id="girlfriend_001", persona_id="girlfriend_001"):
    return ConversationBinding(
        conversation_id=conversation_id,
        platform=platform,
        account_id=account_id,
        contact_id=contact_id,
        persona_id=persona_id,
        updated_at=datetime.now().isoformat(),
    )


def _runner(deliver_ok: bool = True, **overrides):
    delivered: list[tuple] = []

    async def deliver(target, text):
        delivered.append((target, text))
        return deliver_ok

    kwargs = {
        "proactive": FakeProactive(),
        "conversation_store": FakeStore(),
        "chat_history": FakeChatHistory(),
        "deliver": deliver,
        "tick_seconds": 60,
        "quiet_minutes": 15,
    }
    kwargs.update(overrides)
    return ProactiveRunner(**kwargs), delivered


# ── 目标枚举 ────────────────────────────────────────────────────


class TestIterTargets:
    def test_web_binding_uses_role_uid_and_no_scope(self) -> None:
        runner, _ = _runner(conversation_store=FakeStore([_binding()]))
        targets = runner.iter_targets()
        assert len(targets) == 1
        assert targets[0].user_id == "web::girlfriend_001"
        # 网页端作用域就是 user_id，不再叠一层 scope_<hash>
        assert targets[0].scope_id is None

    def test_wechat_binding_gets_contact_scoped_uid(self) -> None:
        runner, _ = _runner(conversation_store=FakeStore([
            _binding("conv_7", "wechat", "default", "wxid_abc"),
        ]))
        targets = runner.iter_targets()
        assert targets[0].user_id == "wechat::default::wxid_abc"
        assert targets[0].scope_id is None or targets[0].scope_id.startswith("scope_")

    def test_same_role_in_two_conversations_collapses(self) -> None:
        """同一角色挂两个网页会话时只处理一次，否则一轮发两条。"""
        runner, _ = _runner(conversation_store=FakeStore([
            _binding("conv_6"), _binding("conv_8"),
        ]))
        assert len(runner.iter_targets()) == 1

    def test_cli_bindings_are_ignored(self) -> None:
        runner, _ = _runner(conversation_store=FakeStore([
            _binding("conv_cli", "cli", "", "local"),
        ]))
        assert runner.iter_targets() == []

    def test_binding_without_persona_is_skipped(self) -> None:
        runner, _ = _runner(conversation_store=FakeStore([
            _binding(persona_id=""),
        ]))
        assert runner.iter_targets() == []

    def test_store_failure_returns_empty(self) -> None:
        class Broken:
            def list(self):
                raise RuntimeError("boom")

        runner, _ = _runner(conversation_store=Broken())
        assert runner.iter_targets() == []


# ── 冷静期 ──────────────────────────────────────────────────────


class TestQuietWindow:
    def _messages(self, minutes_ago: float):
        stamp = (datetime.now() - timedelta(minutes=minutes_ago)).isoformat()
        return [{"role": "user", "content": "在吗", "timestamp": stamp}]

    def test_recent_activity_blocks(self) -> None:
        history = FakeChatHistory({"web::girlfriend_001": self._messages(3)})
        proactive = FakeProactive(trigger="scheduled")
        runner, delivered = _runner(
            conversation_store=FakeStore([_binding()]),
            chat_history=history,
            proactive=proactive,
        )
        import asyncio
        asyncio.run(runner.tick())

        assert proactive.checked == []           # 连检查都不做
        assert delivered == []

    def test_idle_conversation_is_eligible(self) -> None:
        history = FakeChatHistory({"web::girlfriend_001": self._messages(120)})
        proactive = FakeProactive(trigger="scheduled")
        runner, delivered = _runner(
            conversation_store=FakeStore([_binding()]),
            chat_history=history,
            proactive=proactive,
        )
        import asyncio
        asyncio.run(runner.tick())

        assert len(delivered) == 1

    def test_no_history_is_not_treated_as_quiet(self) -> None:
        """没聊过的新会话交给亲密度门槛去挡，不该在调度层被永久挡住。"""
        proactive = FakeProactive(trigger="scheduled")
        runner, delivered = _runner(
            conversation_store=FakeStore([_binding()]),
            proactive=proactive,
        )
        import asyncio
        asyncio.run(runner.tick())
        assert len(proactive.checked) == 1


# ── 单轮行为 ────────────────────────────────────────────────────


class TestTick:
    def test_disabled_does_nothing(self) -> None:
        proactive = FakeProactive(trigger="scheduled", enabled=False)
        runner, delivered = _runner(
            conversation_store=FakeStore([_binding()]), proactive=proactive,
        )
        import asyncio
        asyncio.run(runner.tick())
        assert proactive.checked == []

    def test_no_trigger_does_not_generate(self) -> None:
        proactive = FakeProactive(trigger=None)
        runner, delivered = _runner(
            conversation_store=FakeStore([_binding()]), proactive=proactive,
        )
        import asyncio
        asyncio.run(runner.tick())
        assert proactive.generated == []
        assert delivered == []

    def test_empty_generation_is_skipped(self) -> None:
        proactive = FakeProactive(trigger="scheduled", text="   ")
        runner, delivered = _runner(
            conversation_store=FakeStore([_binding()]), proactive=proactive,
        )
        import asyncio
        asyncio.run(runner.tick())
        assert delivered == []

    def test_successful_delivery_recorded(self) -> None:
        runner, delivered = _runner(
            conversation_store=FakeStore([_binding()]),
            proactive=FakeProactive(trigger="scheduled", text="我有点想你了"),
        )
        import asyncio
        sent = asyncio.run(runner.tick())

        assert len(delivered) == 1
        target, text = delivered[0]
        assert isinstance(target, ProactiveTarget)
        assert text == "我有点想你了"
        assert sent == ["web::girlfriend_001"]

    def test_check_exception_does_not_break_other_targets(self) -> None:
        proactive = FakeProactive(trigger="scheduled", raises=True)
        runner, delivered = _runner(
            conversation_store=FakeStore([_binding()]), proactive=proactive,
        )
        import asyncio
        # 不抛出去就算通过
        assert asyncio.run(runner.tick()) == []
