"""ProactiveRunner — 让主动消息在 Web / 微信端真的会发生。

背景：`ProactiveMessenger` 的整套触发逻辑（定时 / 久未联系 / 未闭合事件追问 /
记忆追问 / 持续关怀）只有一个调用点 —— `core/chat/handler.py:251`，那是 CLI
的输入超时分支。也就是说用网页端和微信时，`proactive_enabled: true` 这行配置
是空的：她一次都不会主动找你。

这个模块补上那层调度：

    while True:
        for 每个活跃会话:
            触发判断 → LLM 生成 → 交给平台交付

设计约束：

1. **不依赖 webui**。交付动作由调用方注入 ``deliver`` 回调，core 层保持干净，
   Web 与微信各写各的投递方式（写 chat_history + SSE / adapter.send）。
2. **按 user_id 去重**。同一个角色可能挂多个网页会话（conv_6 / conv_8 …），
   它们的 user_id 都是 ``web::<persona>`` —— 不去重就会一轮发好几条。
3. **正在聊的时候不打扰**。最近 ``quiet_minutes`` 内有任何消息就跳过这个会话。
4. **生成失败不消耗状态**。触发判断有副作用（mark_fired），所以只在真正要发
   的时候才调它；生成返回空则记录 warning，不重试（下一轮间隔会重新计算）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from loguru import logger

from core.config import build_memory_scope_uid, build_web_uid, build_wechat_uid


@dataclass
class ProactiveTarget:
    platform: str          # "web" | "wechat"
    user_id: str           # 平台侧身份（web::persona / wechat::account::wxid）
    persona_id: str
    scope_id: str | None   # 记忆作用域；web 走 user_id 时不另设
    conversation_id: str
    account_id: str = ""


class ProactiveRunner:
    """主动消息后台调度器。"""

    def __init__(
        self,
        *,
        proactive,
        conversation_store,
        chat_history,
        advanced_config: dict | None = None,
        deliver: Callable[[ProactiveTarget, str], Awaitable[bool]],
        tick_seconds: int = 120,
        quiet_minutes: int = 15,
        internal_source=None,
    ) -> None:
        self._proactive = proactive
        self._store = conversation_store
        self._chat_history = chat_history
        self._config = advanced_config or {}
        self._deliver = deliver
        self._tick_seconds = max(30, int(tick_seconds))
        self._quiet_minutes = max(0, int(quiet_minutes))
        # 情绪内生源（可选）：每轮对所有目标施加「未闭合话题压力 / 孤独感」
        # 偏移，自带 10 分钟节流。这是「没有用户输入时她也会变化」的那一层。
        self._internal_source = internal_source
        self._stop = False
        self._task: asyncio.Task | None = None

    # ── 生命周期 ──

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop = False
        self._task = asyncio.get_running_loop().create_task(
            self._loop(), name="proactive-runner",
        )
        logger.info(
            f"ProactiveRunner started (tick={self._tick_seconds}s, "
            f"quiet={self._quiet_minutes}min)"
        )

    async def stop(self) -> None:
        self._stop = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass  # 预期路径：cancel 之后 await 一定抛它
            except Exception as e:
                logger.debug(f"ProactiveRunner stop: task ended with {e}")
            self._task = None

    async def _loop(self) -> None:
        # 启动后先等一轮，别和启动流程里的模型加载抢资源
        try:
            await asyncio.sleep(min(30, self._tick_seconds))
            while not self._stop:
                try:
                    await self.tick()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning(f"ProactiveRunner tick failed: {e}")
                await asyncio.sleep(self._tick_seconds)
        except asyncio.CancelledError:
            return

    # ── 目标枚举 ──

    def iter_targets(self) -> list[ProactiveTarget]:
        """列出所有该被考虑主动消息的会话（按 user_id 去重）。"""
        targets: dict[str, ProactiveTarget] = {}
        try:
            bindings = self._store.list()
        except Exception as e:
            logger.debug(f"ProactiveRunner: conversation_store unavailable: {e}")
            return []

        for binding in bindings:
            if binding.platform not in ("web", "wechat"):
                continue
            if not binding.persona_id:
                continue
            if binding.platform == "web":
                # legacy web:default 绑定沿用 web_user 命名空间，其余按角色
                if binding.account_id == "" and binding.contact_id == "default":
                    user_id = "web_user"
                else:
                    user_id = build_web_uid(binding.persona_id)
                scope = None
            else:
                user_id = build_wechat_uid(binding.account_id, binding.contact_id)
                scope = build_memory_scope_uid(
                    user_id, binding.persona_id, binding.conversation_id,
                )

            if user_id in targets:
                # 同一身份挂多个网页会话（conv_6 / conv_8 …）时只处理一次：
                # 它们的 user_id 与 chat_history 都是同一个作用域，
                # 不去重就会在一轮里连发好几条。
                continue
            targets[user_id] = ProactiveTarget(
                platform=binding.platform,
                user_id=user_id,
                persona_id=binding.persona_id,
                scope_id=scope,
                conversation_id=binding.conversation_id,
                account_id=binding.account_id,
            )
        return list(targets.values())

    # ── 冷却判断 ──

    def _minutes_since_last_message(self, target: ProactiveTarget) -> float | None:
        """距该会话最后一条消息多少分钟；拿不到返回 None。"""
        memory_user_id = target.scope_id or target.user_id
        try:
            messages = self._chat_history.get_messages(memory_user_id)
        except Exception:
            return None
        if not messages:
            return None
        stamp = messages[-1].get("timestamp") or ""
        try:
            last = datetime.fromisoformat(stamp)
        except (TypeError, ValueError):
            return None
        return (datetime.now() - last).total_seconds() / 60.0

    def _is_quiet(self, target: ProactiveTarget) -> bool:
        idle = self._minutes_since_last_message(target)
        if idle is None:
            # 没有任何历史 → 交给 check 里的亲密度门槛去挡，不在这里判
            return False
        return idle < self._quiet_minutes

    # ── 单轮 ──

    async def tick(self) -> list[str]:
        """跑一轮，返回本轮成功投递的 user_id 列表。"""
        if not getattr(self._proactive, "enabled", False):
            return []

        targets = self.iter_targets()

        # 情绪内生源先跑：主动消息的触发判断（比如心情低落少开口）
        # 应该读到这里面生源刚更新过的状态，而不是上一轮的。
        if self._internal_source is not None:
            for target in targets:
                try:
                    self._internal_source.tick(target.scope_id or target.user_id)
                except Exception as e:
                    logger.debug(f"Internal mood source failed for {target.user_id}: {e}")

        delivered: list[str] = []
        for target in targets:
            if self._is_quiet(target):
                continue
            try:
                trigger = self._proactive.check_proactive_messages(
                    target.user_id, target.persona_id, scope_id=target.scope_id,
                )
            except Exception as e:
                logger.debug(f"Proactive check failed for {target.user_id}: {e}")
                continue
            if not trigger:
                continue

            try:
                text = await self._proactive.generate_message(
                    trigger, target.user_id, target.persona_id,
                    scope_id=target.scope_id,
                )
            except Exception as e:
                logger.warning(f"Proactive generate failed for {target.user_id}: {e}")
                continue
            if not text or not text.strip():
                logger.info(
                    f"Proactive message empty for {target.user_id} "
                    f"(trigger={trigger}), skipped"
                )
                continue

            try:
                ok = await self._deliver(target, text.strip())
            except Exception as e:
                logger.warning(f"Proactive deliver failed for {target.user_id}: {e}")
                continue
            if ok:
                delivered.append(target.user_id)
                logger.info(
                    f"Proactive message sent: {target.platform} "
                    f"{target.user_id} trigger={trigger}"
                )
        return delivered
