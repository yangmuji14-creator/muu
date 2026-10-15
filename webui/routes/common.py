"""webui 路由公共层：常量、配置/密钥/作用域/微信/朋友圈/MCP 等模块级辅助。

由 server.py 拆分而来（模块化第一步，行为等价搬移）。
原 WebUI 后端的接口清单见下方保留的原始说明。

在同进程内复用已初始化的 AppComponents（pipeline / vision / registry），
提供：
- GET  /                 静态页面
- GET  /api/schema       设置字段定义（前端动态渲染）
- GET  /api/settings     当前设置有效值
- POST /api/settings     写入设置并热更新到运行中的实例
- POST /api/chat         流式对话（SSE）
- POST /api/upload/image 图片上传 + 识别
- POST /api/upload/voice 语音上传（可选 ASR，未配置则优雅降级）
- GET  /api/memory             记忆列表（分页 + 重要度过滤）
- GET  /api/memory/{id}        单条记忆详情
- GET  /api/life_summary       人生摘要列表
- GET  /api/life_summary/latest 最新一条人生摘要
- POST /api/model/provider     新增模型提供商
- DELETE /api/model/{key}      删除模型提供商

不修改核心业务逻辑，仅作为一层适配。
"""

from __future__ import annotations

import asyncio
import io
import inspect
import json
import os
import re
import tempfile
import threading
import uuid
import zipfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from loguru import logger

from core.config import (
    ROOT,
    CONFIG_DIR,
    DATA_DIR,
    DEFAULT_PERSONA_ID,
    build_web_uid,
    build_wechat_uid,
    build_memory_scope_uid,
    build_cli_uid,
    build_api_uid,
    load_advanced,
    normalize_wechat_accounts,
    load_image_mode,
)
from core.persona.models import Persona
from core.runtime import run_diagnostics, sanitize_settings
from core.multimodal.stickers import StickerService
from core.llm.catalog import get_provider_spec, public_provider_catalog
from core.llm.diagnostics import discover_models, test_provider_connection
from core.llm.base import set_llm_request_id, reset_llm_request_id
from core.chat.scope_registry import ScopeExecutionRegistry
from core.security import (
    get_secret_manager,
    migrate_settings_secrets,
    model_secret_ref,
    protect_config_secret,
    resolve_config_secret,
    vision_secret_ref,
)
from core.storage.backup import (
    BACKUP_FORMAT_VERSION,
    BackupValidationError,
    create_backup,
    inspect_backup,
    pending_restore_status,
    schedule_restore,
)
from webui.schema import SETTINGS_SCHEMA, coerce_value
from webui.moments_poster import MomentsAutoPoster, load_poster_config
from webui.tts import TTSManager, TTSProvider, TTSStore, parse_voice_markers

# 注意：本文件在 webui/routes/ 子目录，static 在 webui/ 下——用 parent.parent。
# （拆分自 server.py 时曾漏改，__file__ 相对定位指向了不存在的 routes/static，
#  首页 404 显示"webui/static/index.html 尚未生成"。）
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
UPLOAD_DIR = ROOT / "data" / "uploads"
AVATAR_DIR = ROOT / "data" / "avatars"
SETTINGS_PATH = CONFIG_DIR / "settings.json"
WECHAT_CREDS_DIR = ROOT / "data" / "credentials"
MAX_IMAGE_UPLOAD_SIZE = 10 * 1024 * 1024
MAX_AUDIO_UPLOAD_SIZE = 16 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/wav", "audio/mpeg", "audio/mp4"}

PERSONA_ONBOARDING_DEFAULTS = {
    "system_prompt": "你是一个真实、自然、有自己生活的聊天伙伴。用纯文字和对方聊天，保持角色一致，先回应对方最在意的内容，再自然延伸话题。",
    "output_examples": "对方说：今天有点累\n你说：辛苦啦，先歇一会儿。要不要跟我说说今天发生了什么？\n\n对方说：我刚看到一只猫\n你说：在哪里看到的？可爱吗，突然有点想看你拍的照片了。",
    "persona_prompt": "你叫小可爱，温柔、活泼，偶尔有一点傲娇。你喜欢动漫、游戏和计算机，会主动分享日常，也会认真记住对方在意的事情。你们是关系亲近的朋友，聊天自然、简短，不像客服。",
}

# DEPRECATED (T9): 所有 user_id 解析应走 _resolve_user_id_from_conversation。
# 此常量仅作为 helper 内部 "无 conversation_id 且无 persona_id" 时的兜底。
WEB_USER_ID = "web_user"

# WeChat account_id validation (matches adapters/wechat.py _ACCOUNT_ID_PATTERN).
# "default" is exempt from the length requirement (backward compat).
_WECHAT_ACCOUNT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")

# Per-account SSE login locks — keyed by account_id. Concurrent login to the
# same account returns 409. Module-level so locks survive across requests.
_wechat_login_locks: dict[str, asyncio.Lock] = {}

# S6.2: per-scope execution serialization + request idempotency. Module-level
# so it survives across requests; AppComponents may override with its own.
_default_scope_registry = ScopeExecutionRegistry()


# ---- 发现（朋友圈 moments）数据存储 ----
# 纯本地 JSON 存储，遵循 DATA_DIR 约定；不依赖任何模型服务。
_MOMENTS_PATH = DATA_DIR / "moments.json"
_MAX_POST_TEXT = 2000
_MAX_REPLY_TEXT = 500
_MOMENT_ID_RE = re.compile(r"^mom_[0-9a-f]{12}$")
_REPLY_ID_RE = re.compile(r"^rep_[0-9a-f]{12}$")


def _new_moment_id() -> str:
    return f"mom_{uuid.uuid4().hex[:12]}"


def _new_reply_id() -> str:
    return f"rep_{uuid.uuid4().hex[:12]}"


def _moment_now_iso() -> str:
    """朋友圈动态时间戳（本机时区 ISO）。"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _load_moments() -> list[dict]:
    if not _MOMENTS_PATH.exists():
        return []
    try:
        return json.loads(_MOMENTS_PATH.read_text(encoding="utf-8")).get("moments") or []
    except Exception as exc:
        logger.warning(f"moments load failed: {exc}")
        return []


def _save_moments(moments: list[dict]) -> None:
    _MOMENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _MOMENTS_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"moments": moments}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(_MOMENTS_PATH)


def _moment_author_label(app_components, author: str) -> str:
    if author == "user":
        return "我"
    if not author:
        return ""
    try:
        loader = getattr(app_components, "persona_loader", None)
        if loader is not None:
            for p in loader.list_all():
                if p.id == author:
                    return p.name or author
    except Exception:
        pass
    return author


# ---- MCP 扩展（servers 配置）----
# 配置在 CONFIG_DIR/mcp_servers.json；MCPManager 已由 core.tools 提供连接/工具。
_MCP_SERVERS_PATH = CONFIG_DIR / "mcp_servers.json"
_MCP_ALLOWED_SERVER_FIELDS = (
    "name", "command", "args", "env", "cwd", "enabled",
    "auto_reconnect", "max_reconnect_attempts", "reconnect_base_delay",
    "reconnect_max_delay", "reconnect_backoff", "startup_timeout", "operation_timeout",
)


def _load_mcp_servers() -> list[dict]:
    if not _MCP_SERVERS_PATH.exists():
        return []
    try:
        return json.loads(_MCP_SERVERS_PATH.read_text(encoding="utf-8")).get("servers") or []
    except Exception as exc:
        logger.warning(f"MCP servers load failed: {exc}")
        return []


def _save_mcp_servers(servers: list[dict]) -> None:
    _MCP_SERVERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _MCP_SERVERS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"servers": servers}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_MCP_SERVERS_PATH)


def _sanitize_mcp_server(raw: dict) -> dict:
    """只保留 MCP 允许的字段，杜绝未知字段写回。"""
    out = {}
    for key in _MCP_ALLOWED_SERVER_FIELDS:
        if key in raw:
            out[key] = raw[key]
    return out


_BUILTIN_MCP_SERVERS = [
    {
        "name": "system", "command": "python",
        "args": ["-u", "mcp_servers/system_tools.py"],
        "enabled": True, "comment": "系统工具：时间/字数/随机数/读文本",
    },
    {
        "name": "web", "command": "python",
        "args": ["-u", "mcp_servers/web_fetch.py"],
        "enabled": True, "comment": "网页能力：抓取网页 + Bing 搜索",
    },
    {
        "name": "weather", "command": "python",
        "args": ["-u", "mcp_servers/weather.py"],
        "enabled": True, "comment": "天气能力：实时天气 + 预报 (wttr.in)",
    },
]


def _seed_default_mcp_config() -> None:
    """打包模式(EXE)首次启动时写入内置 MCP 服务器, 让 MCP 开箱即用。

    仅当 MU_PACKAGED=1（兼容旧名 CC_PACKAGED）且 config 里尚无 mcp_servers.json 时写入,
    不覆盖用户已有的配置。源码模式已有自带配置, 天然跳过。
    """
    if (os.environ.get("MU_PACKAGED") or os.environ.get("CC_PACKAGED", "")).lower() not in {"1", "true", "yes", "on"}:
        return
    if _MCP_SERVERS_PATH.exists():
        return
    try:
        _save_mcp_servers([dict(s) for s in _BUILTIN_MCP_SERVERS])
        logger.info(f"WebUI: seeded built-in MCP servers -> {_MCP_SERVERS_PATH}")
    except Exception as e:
        logger.warning(f"WebUI: seed MCP servers failed: {e}")


def _scope_registry(app_components) -> ScopeExecutionRegistry:
    """Resolve the scope registry beside app components (testable override)."""
    custom = getattr(app_components, "scope_registry", None)
    return custom if custom is not None else _default_scope_registry


# ────────── 会话 → user_id 解析 (T9) ──────────

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
    """Return the isolated state namespace for a real binding.

    The migrated ``web:default`` binding deliberately keeps using the legacy
    ``web_user.json`` namespace. New bindings use a stable conversation/persona
    scope, so rebinding a contact cannot expose the previous role's memory.
    """
    if not conversation_id or not persona_id:
        return None
    store = getattr(app_components, "conversation_store", None)
    binding = store.get(conversation_id) if store is not None else None
    if (
        binding is None
        or (
            binding.platform == "web"
            and binding.account_id == ""
            and binding.contact_id == "default"
        )
    ):
        return None
    return build_memory_scope_uid(user_id, persona_id, conversation_id)


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
    except (TypeError, ValueError):
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


# ────────── 设置读写 ──────────

def _load_settings() -> dict:
    """读取 settings.json，缺失返回空 dict。"""
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"WebUI: failed to read settings.json: {e}")
    return {}


def _app_version() -> str:
    for distribution in ("muu",):
        try:
            return version(distribution)
        except PackageNotFoundError:
            continue
    return "4.3.0"


def _installation_id() -> str:
    """本机安装实例标识：首次生成后持久化，用于诊断定位与授权管理。

    不含任何个人信息（随机 UUID），也不上传——仅在 /api/about 与启动日志中出现。
    """
    path = DATA_DIR / "installation_id"
    try:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        value = uuid.uuid4().hex
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return value
    except Exception:
        return ""


def _save_settings(settings: dict) -> None:
    """原子写入 settings.json。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    tmp.replace(SETTINGS_PATH)


def _secret_manager():
    """Resolve the secret store beside the active settings file (testable)."""
    return get_secret_manager(SETTINGS_PATH.parent)


def _migrate_existing_secrets() -> dict:
    """Move legacy plaintext keys when possible without risking availability."""
    settings = _load_settings()
    if not settings:
        status = _secret_manager().status
        return {"changed": False, "backend": status.backend, "available": status.available,
                "protected": 0, "plaintext": 0}
    migrated, report = migrate_settings_secrets(settings, manager=_secret_manager())
    if report["changed"]:
        _save_settings(migrated)
        logger.info(
            "Protected {} credential(s) with {}",
            report["protected"], report["backend"],
        )
    return report


def _current_values() -> dict:
    """按 schema 汇总当前有效值：settings.json > load_advanced 默认 > schema 默认。"""
    settings = _load_settings()
    advanced = settings.get("advanced", {})
    models = settings.get("models", {})
    default_model = settings.get("default_model")
    model_cfg = models.get(default_model, {}) if default_model else {}
    # 任取一个模型兜底（default 未设时）
    if not model_cfg and models:
        model_cfg = next(iter(models.values()))

    fallback_advanced = load_advanced()
    values: dict = {}
    for field in SETTINGS_SCHEMA:
        key = field["key"]
        target = field["target"]
        default = field["default"]
        if target == "model":
            values[key] = model_cfg.get(key, default)
        elif target == "model_repetition":
            # presence/frequency 合并展示，取 presence 为准
            values[key] = model_cfg.get("presence_penalty", default)
        else:  # advanced
            values[key] = advanced.get(key, fallback_advanced.get(key, default))
        values[key] = coerce_value(field, values[key])
    return values


def _persist_values(values: dict) -> None:
    """把 schema 值写回 settings.json 的正确位置。"""
    settings = _load_settings()
    advanced = settings.setdefault("advanced", {})
    models = settings.setdefault("models", {})
    default_model = settings.get("default_model")
    targets = [models[default_model]] if default_model and default_model in models else list(models.values())

    for field in SETTINGS_SCHEMA:
        key = field["key"]
        target = field["target"]
        val = values.get(key)
        if val is None:
            continue
        if target == "model":
            for m in targets:
                m[key] = val
        elif target == "model_repetition":
            for m in targets:
                m["presence_penalty"] = val
                m["frequency_penalty"] = val
        else:
            advanced[key] = val
    _save_settings(settings)


def _apply_live(app, values: dict) -> None:
    """热更新到运行中的实例，避免重启。"""
    # 1. 模型参数 → 直接改 LLM 实例属性
    try:
        llm = app.registry.get() if app.registry.available_models else None
    except Exception:
        llm = None
    if llm is not None:
        if "temperature" in values:
            llm.temperature = values["temperature"]
        if "max_tokens" in values:
            llm.max_tokens = values["max_tokens"]
        if "max_retries" in values:
            llm.max_retries = values["max_retries"]
        if "repetition_penalty" in values:
            llm.presence_penalty = values["repetition_penalty"]
            llm.frequency_penalty = values["repetition_penalty"]

    # 2. advanced 参数 → 更新共享 config dict
    cfg = getattr(app, "advanced_config", None)
    if isinstance(cfg, dict):
        for key in ("segment_max_length", "debounce_seconds", "summarize_threshold",
                    "proactive_enabled", "proactive_active_start", "proactive_active_end",
                    "proactive_interval_min", "proactive_interval_max", "auto_extract_memory"):
            if key in values:
                cfg[key] = values[key]

    # 3. 主动消息开关热更新
    if hasattr(app, "proactive") and app.proactive is not None:
        if "proactive_enabled" in values:
            app.proactive.enabled = values["proactive_enabled"]

    # 3.5 去抖延迟热更新（review P2-10）：此前只改 config dict，而 DebounceManager
    # 及其每个 state 在构造时复制了值，运行中改设置实际不生效、重启才生效。
    dm = getattr(app, "debounce_manager", None)
    if dm is not None and "debounce_seconds" in values:
        try:
            dm.timeout = float(values["debounce_seconds"])
            for state in getattr(dm, "_states", {}).values():
                state.timeout = dm.timeout  # 已挂起的定时器保持旧值，新定时器生效
        except (TypeError, ValueError, AttributeError):
            pass


# ────────── WeChat account helpers ──────────

def _validate_wechat_account_id(account_id: str) -> bool:
    """Return True if account_id is 'default' or matches ^[a-zA-Z0-9_-]{3,32}$."""
    if account_id == "default":
        return True
    return bool(_WECHAT_ACCOUNT_ID_RE.match(account_id))


def _wechat_credentials_path(account_id: str) -> Path:
    """Return the credentials file path for a wechat account_id.

    Mirrors adapters/wechat.py _credential_paths_for logic:
    - "default" → wechat.json (backward compat)
    - other     → wechat_{account_id}.json
    """
    if account_id == "default":
        return WECHAT_CREDS_DIR / "wechat.json"
    return WECHAT_CREDS_DIR / f"wechat_{account_id}.json"


def _get_wechat_accounts_config() -> list[dict]:
    """Read wechat accounts from settings.json.

    Normalizes both new array format and legacy single-object format:
    - New: advanced.adapters.wechat.accounts = [{id, persona_id, enabled, auto_start}, ...]
    - Legacy: advanced.adapters.wechat = {enabled, auto_start} (no accounts key)
    """
    settings = _load_settings()
    wechat_cfg = settings.get("advanced", {}).get("adapters", {}).get("wechat", {})
    return normalize_wechat_accounts(wechat_cfg)


def _save_wechat_accounts_config(accounts: list[dict]) -> None:
    """Write wechat accounts array to settings.json (preserves other keys)."""
    settings = _load_settings()
    settings.setdefault("advanced", {}).setdefault("adapters", {}).setdefault("wechat", {})["accounts"] = accounts
    _save_settings(settings)


def _set_runtime_wechat_accounts(app_components, accounts: list[dict]) -> None:
    """Keep live message routing aligned with account changes from the WebUI."""
    advanced = getattr(app_components, "advanced_config", None)
    if not isinstance(advanced, dict):
        return
    advanced.setdefault("adapters", {}).setdefault("wechat", {})["accounts"] = [
        dict(account) for account in accounts
    ]


def _make_session_expired_callback(account_id: str):
    """构造 session_expired 回调，注入到 WeChatAdapter.on_session_expired。

    回调由 WeChatAdapter._poll_messages 的 watchdog 在检测到 session 过期时调用
    （参数是 account_id）。回调本身只记日志 —— 前端通过 GET /api/wechat/accounts
    的 session_expired 字段轮询发现，自动弹出 QR 重登模态框。
    """
    def _on_session_expired(acc_id: str) -> None:
        logger.warning(
            f"WeChat[{acc_id}] session expired, flag set; WebUI will poll session_expired=true"
        )
    return _on_session_expired


async def _autostart_wechat_adapters(app_components) -> None:
    """服务器启动时：为 auto_start=True 且已有凭证的微信账号注册并启动 WeChatAdapter。

    遍历 settings.json 的微信账号配置，对每个 auto_start=True 且凭证文件存在的账号：
    1. 构造 WeChatAdapter(account_id=acc_id)
    2. 注册到 app_components.adapter_manager
    3. 调用 adapter.start()（复用已有凭证，不会触发二维码登录）

    无凭证的账号跳过（避免在无用户交互的服务器启动场景触发终端二维码）。
    SDK 未安装时整体跳过（避免注册一批无法启动的 adapter 占位）。
    任何单账号启动失败只 log warning，不影响其他账号或服务器启动。
    """
    adapter_manager = getattr(app_components, "adapter_manager", None)
    if adapter_manager is None:
        return

    # SDK 未安装 → 整体跳过（WeChatAdapter.start() 会静默返回，导致 registered-but-not-running 占位）
    try:
        import weixin_ilink  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        logger.info("WeChat autostart: SDK not installed, skipping all accounts")
        return

    from adapters.wechat import WeChatAdapter

    accounts = _get_wechat_accounts_config()
    if not accounts:
        logger.info("WeChat autostart: no accounts configured in settings.json")
    for acc in accounts:
        acc_id = acc.get("id", "default")
        auto_start = acc.get("auto_start", True)
        if not auto_start:
            logger.info(f"WeChat autostart: skip {acc_id} (auto_start=false)")
            continue
        creds_path = _wechat_credentials_path(acc_id)
        if not creds_path.exists():
            logger.info(f"WeChat autostart: skip {acc_id} (no credentials)")
            continue
        # 已注册则跳过（幂等，避免重复注册）
        try:
            existing = adapter_manager.get("wechat", acc_id)
            if existing is not None:
                continue
        except Exception:
            pass
        try:
            adapter = WeChatAdapter(account_id=acc_id)
            registry = getattr(app_components, "registry", None)
            if registry is not None and getattr(registry, "available_models", None):
                try:
                    adapter._main_model = registry.get()
                except Exception:
                    pass
            # 注入 session_expired 回调（watchdog 触发后通知 WebUI）
            adapter.on_session_expired = _make_session_expired_callback(acc_id)
            adapter_manager.register(adapter, account_id=acc_id)
            await adapter.start()
            logger.info(f"WeChat autostart: started {acc_id}")
        except Exception as e:
            logger.warning(f"WeChat autostart: failed for {acc_id}: {e}")
            # 启动失败则从 manager 移除，避免残留一个未运行的 adapter 占位
            try:
                adapter_manager.unregister("wechat", acc_id)
            except Exception:
                pass


# ────────── Legacy web_user.json migration (T13) ──────────

# T13: Legacy web_user.json → web:default conversation binding migration.
# 在 _make_app 中 best-effort 调用，失败不阻塞 server 启动。
_WEB_DEFAULT_PLATFORM = "web"
_WEB_DEFAULT_ACCOUNT_ID = ""
_WEB_DEFAULT_CONTACT_ID = "default"
_MIGRATION_MARKER = ".web_user_migrated"


def migrate_legacy_web_user(conversation_store, data_dir) -> None:
    """T13: 迁移 legacy web_user.json → web:default conversation binding.

    检测条件（全部满足才创建 binding）:
    1. ``{data_dir}/.web_user_migrated`` marker 文件不存在（未迁移过）
    2. ``{data_dir}/chat_history/web_user.json`` 存在（有 legacy 历史）
    3. ``ConversationStore.find("web", "", "default")`` 返回 None（未手动创建过）

    迁移成功或判定无需迁移后写入 marker 文件（``Path.touch()``），保证幂等。
    任何异常都捕获并 log warning——迁移失败不阻塞 server 启动。

    Args:
        conversation_store: ConversationStore 实例；为 None 时直接返回。
        data_dir: 数据目录路径（str | Path）。
    """
    data_dir = Path(data_dir)
    marker = data_dir / _MIGRATION_MARKER

    if marker.exists():
        return  # 已迁移，幂等返回

    if conversation_store is None:
        return  # 无 store（测试环境 FakeAppComponents 默认 None）— 不写 marker，下次再试

    legacy_file = data_dir / "chat_history" / "web_user.json"

    # 检查 binding 是否已存在（手动创建或 race condition）— self-heal marker
    try:
        existing = conversation_store.find(
            _WEB_DEFAULT_PLATFORM, _WEB_DEFAULT_ACCOUNT_ID, _WEB_DEFAULT_CONTACT_ID
        )
    except Exception as e:
        logger.warning(f"T13 migration: find() failed: {e}")
        return

    if existing is None:
        # 无 binding — 只有 legacy 文件存在才创建
        if not legacy_file.exists():
            # 无 legacy 文件 + 无 binding — 写 marker 跳过未来检查
            try:
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.touch()
            except Exception as e:
                logger.warning(f"T13 migration: failed to write marker: {e}")
            return
        # 有 legacy 文件 + 无 binding → 创建 binding
        try:
            conversation_store.create(
                platform=_WEB_DEFAULT_PLATFORM,
                account_id=_WEB_DEFAULT_ACCOUNT_ID,
                contact_id=_WEB_DEFAULT_CONTACT_ID,
                persona_id=DEFAULT_PERSONA_ID,
            )
            logger.info("Legacy web_user.json migrated to web:default conversation")
        except ValueError as e:
            # Race condition: binding 在 find() 与 create() 之间被创建 — self-heal marker
            logger.warning(f"T13 migration: binding already exists (race): {e}")
        except Exception as e:
            # 真实失败（IO / 权限等）— 不写 marker，下次启动重试
            logger.warning(f"T13 migration: create() failed: {e}")
            return

    # 写 marker（covers: 刚创建 binding / binding 已存在 self-heal / race resolved）
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except Exception as e:
        logger.warning(f"T13 migration: failed to write marker: {e}")


# ────────── 运行时状态聚合 (/api/state 用) ──────────

# MoodType 英文枚举 → 中文标签
_MOOD_LABELS = {
    "ecstatic": "欣喜",
    "happy": "开心",
    "content": "满足",
    "calm": "平和",
    "neutral": "平静",
    "tired": "疲惫",
    "sad": "难过",
    "depressed": "低落",
    "lonely": "孤单",
    "anxious": "不安",
    "angry": "生气",
    "frustrated": "烦躁",
    "excited": "兴奋",
    "love": "心动",
    "grateful": "感激",
}


def _affection_stage(level: float) -> str:
    """亲密度 → 关系阶段标签（与 RelationshipEvolution 分档一致）。"""
    if level >= 80:
        return "深度关系"
    if level >= 50:
        return "亲近"
    if level >= 20:
        return "熟悉"
    return "刚认识"


# ────────── HTTP handlers ──────────



# ── TTS / Whisper 语音合成辅助（原 server.py 尾部，被 voice 与 upload/voice 共用）──
_whisper_model = None
_whisper_model_lock = threading.Lock()

def _get_whisper_model():
    """Load the optional local ASR model once per process.

    Loading Whisper for every voice request made the WebUI appear frozen for
    several seconds and repeatedly consumed memory. The model remains an
    optional fallback because browser speech recognition is the zero-install
    path for portable builds.
    """
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception:
        return None
    with _whisper_model_lock:
        if _whisper_model is None:
            model_name = os.getenv("MU_WHISPER_MODEL") or os.getenv("CC_WHISPER_MODEL", "base")
            _whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
    return _whisper_model


def _try_transcribe(audio_path: Path) -> str | None:
    """Try optional faster-whisper transcription; return None when unavailable."""
    try:
        model = _get_whisper_model()
        if model is None:
            return None
        segments, _info = model.transcribe(str(audio_path), language="zh")
        return "".join(seg.text for seg in segments).strip() or None
    except Exception as e:
        logger.warning(f"WebUI ASR failed: {e}")
        return None


# ===== TTS 语音回复 =====

TTS_AUDIO_DIR = DATA_DIR / "tts_audio"


def _tts_store() -> TTSStore:
    return TTSStore(CONFIG_DIR)


def _tts_manager() -> TTSManager:
    return TTSManager(_tts_store())


def _tts_cache_dir() -> Path:
    p = TTS_AUDIO_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def _serve_audio_bytes(request, data: bytes, content_type: str = "audio/mpeg"):
    """支持 HTTP Range 的音频响应（浏览器可拖动播放）。"""
    from aiohttp import web
    size = len(data)
    rng = request.headers.get("Range")
    if rng:
        try:
            start_s = rng.replace("bytes=", "").split("-")[0].strip()
            start = int(start_s) if start_s else 0
            end = size - 1
        except (ValueError, AttributeError):
            start, end = 0, size - 1
        if start >= size:
            return web.Response(status=416)
        body = data[start:end + 1]
        return web.Response(
            status=206,
            body=body,
            headers={
                "Content-Type": content_type,
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(body)),
                "Cache-Control": "private, max-age=3600",
            },
        )
    return web.Response(
        body=data,
        headers={
            "Content-Type": content_type,
            "Accept-Ranges": "bytes",
            "Content-Length": str(size),
            "Cache-Control": "private, max-age=3600",
        },
    )




# 由拆分脚本生成：server.py 与各路由域通过 `from webui.routes.common import *` 拿到
# 与拆分前 server.py 完全一致的命名空间（含 import 进来的名字）
__all__ = [
    "asyncio",
    "io",
    "inspect",
    "json",
    "os",
    "re",
    "tempfile",
    "threading",
    "uuid",
    "zipfile",
    "PackageNotFoundError",
    "version",
    "Path",
    "logger",
    "ROOT",
    "CONFIG_DIR",
    "DATA_DIR",
    "DEFAULT_PERSONA_ID",
    "build_web_uid",
    "build_wechat_uid",
    "build_memory_scope_uid",
    "build_cli_uid",
    "build_api_uid",
    "load_advanced",
    "normalize_wechat_accounts",
    "load_image_mode",
    "Persona",
    "run_diagnostics",
    "sanitize_settings",
    "StickerService",
    "get_provider_spec",
    "public_provider_catalog",
    "discover_models",
    "test_provider_connection",
    "set_llm_request_id",
    "reset_llm_request_id",
    "ScopeExecutionRegistry",
    "get_secret_manager",
    "migrate_settings_secrets",
    "model_secret_ref",
    "protect_config_secret",
    "resolve_config_secret",
    "vision_secret_ref",
    "BACKUP_FORMAT_VERSION",
    "BackupValidationError",
    "create_backup",
    "inspect_backup",
    "pending_restore_status",
    "schedule_restore",
    "SETTINGS_SCHEMA",
    "coerce_value",
    "MomentsAutoPoster",
    "load_poster_config",
    "TTSManager",
    "TTSProvider",
    "TTSStore",
    "parse_voice_markers",
    "STATIC_DIR",
    "UPLOAD_DIR",
    "AVATAR_DIR",
    "SETTINGS_PATH",
    "WECHAT_CREDS_DIR",
    "MAX_IMAGE_UPLOAD_SIZE",
    "MAX_AUDIO_UPLOAD_SIZE",
    "ALLOWED_IMAGE_TYPES",
    "ALLOWED_AUDIO_TYPES",
    "PERSONA_ONBOARDING_DEFAULTS",
    "WEB_USER_ID",
    "_WECHAT_ACCOUNT_ID_RE",
    "_wechat_login_locks",
    "_default_scope_registry",
    "_MOMENTS_PATH",
    "_MAX_POST_TEXT",
    "_MAX_REPLY_TEXT",
    "_MOMENT_ID_RE",
    "_REPLY_ID_RE",
    "_new_moment_id",
    "_new_reply_id",
    "_moment_now_iso",
    "_load_moments",
    "_save_moments",
    "_moment_author_label",
    "_MCP_SERVERS_PATH",
    "_MCP_ALLOWED_SERVER_FIELDS",
    "_load_mcp_servers",
    "_save_mcp_servers",
    "_sanitize_mcp_server",
    "_BUILTIN_MCP_SERVERS",
    "_seed_default_mcp_config",
    "_scope_registry",
    "_ConversationNotFound",
    "_user_id_from_binding",
    "_resolve_user_id_from_conversation",
    "_memory_scope_from_conversation",
    "_resolve_scoped_user_id",
    "_scope_kwargs",
    "_guard_client_identity",
    "_load_settings",
    "_app_version",
    "_installation_id",
    "_save_settings",
    "_secret_manager",
    "_migrate_existing_secrets",
    "_current_values",
    "_persist_values",
    "_apply_live",
    "_validate_wechat_account_id",
    "_wechat_credentials_path",
    "_get_wechat_accounts_config",
    "_save_wechat_accounts_config",
    "_set_runtime_wechat_accounts",
    "_make_session_expired_callback",
    "_autostart_wechat_adapters",
    "_WEB_DEFAULT_PLATFORM",
    "_WEB_DEFAULT_ACCOUNT_ID",
    "_WEB_DEFAULT_CONTACT_ID",
    "_MIGRATION_MARKER",
    "migrate_legacy_web_user",
    "_MOOD_LABELS",
    "_affection_stage",
    "_whisper_model",
    "_whisper_model_lock",
    "_get_whisper_model",
    "_try_transcribe",
    "TTS_AUDIO_DIR",
    "_tts_store",
    "_tts_manager",
    "_tts_cache_dir",
    "_serve_audio_bytes",
]
