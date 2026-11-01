"""会话身份与状态作用域解析（所有路由共用的"这是谁"层）。

从 common.py 拆出（2026-11-01 模块化第二步）。

这一层回答两个问题：
1. 这个请求对应哪个身份（user_id）？—— 由 conversation binding 决定，
   客户端传值只能核对、不能指定（防伪造，见 ``_guard_client_identity``）。
2. 这个身份的状态存哪里（scope）？—— 2026-11-01 起网页端按「角色」
   而不是「会话」隔离，``user_id`` 本身就是作用域。
"""

from __future__ import annotations

import inspect

from loguru import logger

from core.chat.scope_registry import ScopeExecutionRegistry
from core.config import (
    build_api_uid,
    build_cli_uid,
    build_web_uid,
    build_wechat_uid,
)

# DEPRECATED (T9): 所有 user_id 解析应走 _resolve_user_id_from_conversation。
# 此常量仅作为 helper 内部 "无 conversation_id 且无 persona_id" 时的兜底。
WEB_USER_ID = "web_user"

# S6.2: per-scope execution serialization + request idempotency. Module-level
# so it survives across requests; AppComponents may override with its own.
_default_scope_registry = ScopeExecutionRegistry()


def _scope_registry(app_components) -> ScopeExecutionRegistry:
    """Resolve the scope registry beside app components (testable override)."""
    custom = getattr(app_components, "scope_registry", None)
    return custom if custom is not None else _default_scope_registry


class _ConversationNotFound(Exception):
    """conversation_id 提供但 store 中找不到对应 binding。
    调用方应返回 404。"""


def _user_id_from_binding(binding) -> str:
    """从 ConversationBinding 推导 user_id（按 platform 分发）。"""
    platform = binding.platform
    if platform == "wechat":
        return build_wechat_uid(binding.account_id, binding.contact_id)
    if platform == "web":
        return build_web_uid(binding.persona_id)
    if platform == "cli":
        return build_cli_uid()
    if platform == "api":
        return build_api_uid(binding.contact_id)
    # 未知 platform：兜底走 web uid，避免崩溃
    logger.warning(f"WebUI: unknown platform {platform!r}, falling back to web uid")
    return build_web_uid(binding.persona_id)


def _resolve_user_id_from_conversation(
    conversation_id: str | None,
    app_components,
    fallback_persona_id: str | None = None,
) -> tuple[str, str | None, str | None]:
    """把 conversation_id 解析为 user_id。

    - conversation_id 为空/None → 走 legacy fallback：
        * 有 fallback_persona_id → build_web_uid(persona_id)
        * 无 → WEB_USER_ID（最坏情况兜底）
    - conversation_id 非空 → conversation_store.get(id) →
        * 找不到 → raise _ConversationNotFound
        * 找到 → 按 binding platform 推导 user_id

    返回 (user_id, conversation_id_or_None, persona_id_or_None)。
    - conversation_id_or_None：None 表示走 legacy 路径
    - persona_id_or_None：binding 的 persona_id（仅 conversation_id 命中时非 None）；
      POST /api/chat 应优先用这个 persona_id 喂给 pipeline
    """
    if not conversation_id:
        if fallback_persona_id:
            return build_web_uid(fallback_persona_id), None, None
        return WEB_USER_ID, None, None

    store = getattr(app_components, "conversation_store", None)
    if store is None:
        raise _ConversationNotFound("conversation_store unavailable")
    binding = store.get(conversation_id)
    if binding is None:
        raise _ConversationNotFound(conversation_id)

    # T13 legacy redirect: web:default binding 是从 legacy web_user.json 迁移来的。
    # user_id 必须用 "web_user"（走 T5 legacy 路径加载 web_user.json），而非
    # build_web_uid(persona_id)（那会指向 data/chat_history/web/{persona_id}.json，
    # legacy 历史不在那里）。此分支仅匹配 T13 migrate_legacy_web_user 创建的 binding。
    if (binding.platform == "web"
            and binding.account_id == ""
            and binding.contact_id == "default"):
        return WEB_USER_ID, conversation_id, binding.persona_id

    return _user_id_from_binding(binding), conversation_id, binding.persona_id


def _memory_scope_from_conversation(
    conversation_id: str | None,
    app_components,
    user_id: str,
    persona_id: str | None,
) -> str | None:
    """返回状态隔离键 —— 网页端按「角色」而不是「会话」。

    设计变更（2026-11-01，用户明确要求）：这里原本对每个网页会话返回
    ``scope_<hash(user, persona, conversation)>``，于是**新建一个会话就等于
    换了一个人**：记忆、情绪、人格、亲密度四个 store 全部从零开始。
    实测库里因此躺着 8 套互不相通的状态，其中主力那套（95 亲密度 / 182 条历史）
    仅因为换了会话就整块失踪。

    ``user_id`` 本身已经包含隔离所需的全部信息，不需要再叠一层：
      - web    → ``web::<persona_id>``           同一个角色就是同一个人
      - wechat → ``wechat::<account>::<wxid>``   不同联系人必须是不同的人
      - api    → ``api::<user_id>``              按调用方隔离

    ``conversation_id`` 从此只作 UI 分组与导出用，不参与记忆分区。
    返回 None 让调用方回落到 ``user_id``。
    """
    return None


def _resolve_scoped_user_id(
    conversation_id: str | None,
    app_components,
    fallback_persona_id: str | None = None,
) -> tuple[str, str | None, str | None]:
    """Resolve a binding and return the user-facing storage scope."""
    user_id, resolved_conversation, persona_id = _resolve_user_id_from_conversation(
        conversation_id, app_components, fallback_persona_id=fallback_persona_id,
    )
    scoped = _memory_scope_from_conversation(
        resolved_conversation, app_components, user_id, persona_id,
    )
    return scoped or user_id, resolved_conversation, persona_id


def _scope_kwargs(pipeline, scope_id: str | None) -> dict:
    """Pass scope_id only to pipeline implementations that support it."""
    if not scope_id:
        return {}
    try:
        parameters = inspect.signature(pipeline.process).parameters
    # AttributeError：pipeline 可能是个鸭子类型的替身（测试桩、适配器包装），
    # 连 .process 都没有。这里做的是「能带就带」，不该因为签名探测失败就 500。
    except (AttributeError, TypeError, ValueError):
        return {}
    return {"scope_id": scope_id} if "scope_id" in parameters else {}


def _guard_client_identity(client_user_id, resolved, *, where):
    """Reject a client-supplied user_id that tries to override the resolved identity.

    Identity is authoritative (S6.1): it is derived from the conversation binding or
    the system-controlled fallback. A browser must not be able to redirect memory to
    another user by sending an arbitrary user_id. When the client supplies a user_id
    that does not match the resolved one it is a forge attempt and rejected with 403;
    an equal (or absent) value is harmless.
    """
    if isinstance(client_user_id, str):
        client_user_id = client_user_id.strip()
    if client_user_id is not None and client_user_id != "" and client_user_id != resolved:
        from aiohttp import web
        logger.warning(f"{where}: rejecting forged user_id={client_user_id!r} (resolved={resolved!r})")
        return web.json_response(
            {"error": f"{where}: user_id does not match the bound conversation identity"},
            status=403,
        )
    return None
