"""webui 路由公共层 —— 兼容门面（facade）。

2026-11-01 模块化第二步：本文件此前是从 server.py 机械拆出的「大杂烩」
（995 行混了 8 个互不相关的职责）。现在按职责拆成独立模块：

- ``state_scope.py``     会话身份与状态作用域（"这是谁、状态存哪"）
- ``settings_store.py``  settings.json 读写、密钥迁移、运行时热更新
- ``wechat_accounts.py`` 微信多账号：配置/凭证/自动启动
- ``moments_store.py``   朋友圈本地存储
- ``mcp_config.py``      MCP servers 配置文件
- ``tts_store.py``       TTS 缓存与音频流式响应

本文件保留：
1. 真正跨域的少量常量与工具（STATIC_DIR / migrate_legacy_web_user / 展示标签）
2. 对上述模块的**显式 re-export** —— 路由层与测试大量使用
   ``from webui.routes.common import X``，保持这个入口不变，拆分才是行为等价的。

原 WebUI 后端的接口清单（历史保留）：
- GET  /                 静态页面
- GET  /api/schema       设置字段定义（前端动态渲染）
- GET  /api/settings     当前设置有效值
- POST /api/settings     写入设置并热更新到运行中的实例
- POST /api/chat         流式对话（SSE）
- POST /api/upload/image 图片上传 + 识别
- GET  /api/memory       记忆列表（分页 + 重要度过滤）
- POST /api/model/provider     新增模型提供商
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

# ── 职责模块（re-export，见 __all__）──
from webui.routes.state_scope import (
    WEB_USER_ID,
    _default_scope_registry,
    _scope_registry,
    _ConversationNotFound,
    _user_id_from_binding,
    _resolve_user_id_from_conversation,
    _memory_scope_from_conversation,
    _resolve_scoped_user_id,
    _scope_kwargs,
    _guard_client_identity,
)
from webui.routes.settings_store import (
    SETTINGS_PATH,
    _load_settings,
    _app_version,
    _installation_id,
    _save_settings,
    _secret_manager,
    _migrate_existing_secrets,
    _current_values,
    _persist_values,
    _apply_live,
)
from webui.routes.wechat_accounts import (
    WECHAT_CREDS_DIR,
    _WECHAT_ACCOUNT_ID_RE,
    _wechat_login_locks,
    _validate_wechat_account_id,
    _wechat_credentials_path,
    _get_wechat_accounts_config,
    _save_wechat_accounts_config,
    _set_runtime_wechat_accounts,
    _make_session_expired_callback,
    _autostart_wechat_adapters,
)
from webui.routes.moments_store import (
    _MOMENTS_PATH,
    _MAX_POST_TEXT,
    _MAX_REPLY_TEXT,
    _MOMENT_ID_RE,
    _REPLY_ID_RE,
    _new_moment_id,
    _new_reply_id,
    _moment_now_iso,
    _load_moments,
    _save_moments,
    _moment_author_label,
)
from webui.routes.mcp_config import (
    _MCP_SERVERS_PATH,
    _MCP_ALLOWED_SERVER_FIELDS,
    _load_mcp_servers,
    _save_mcp_servers,
    _sanitize_mcp_server,
    _BUILTIN_MCP_SERVERS,
    _seed_default_mcp_config,
)
from webui.routes.tts_store import (
    TTS_AUDIO_DIR,
    _tts_store,
    _tts_manager,
    _tts_cache_dir,
    _serve_audio_bytes,
)

# 注意：本文件在 webui/routes/ 子目录，static 在 webui/ 下——用 parent.parent。
# （拆分自 server.py 时曾漏改，__file__ 相对定位指向了不存在的 routes/static，
#  首页 404 显示"webui/static/index.html 尚未生成"。）
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
UPLOAD_DIR = ROOT / "data" / "uploads"
AVATAR_DIR = ROOT / "data" / "avatars"
MAX_IMAGE_UPLOAD_SIZE = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

PERSONA_ONBOARDING_DEFAULTS = {
    "system_prompt": "你是一个真实、自然、有自己生活的聊天伙伴。用纯文字和对方聊天，保持角色一致，先回应对方最在意的内容，再自然延伸话题。",
    "output_examples": "对方说：今天有点累\n你说：辛苦啦，先歇一会儿。要不要跟我说说今天发生了什么？\n\n对方说：我刚看到一只猫\n你说：在哪里看到的？可爱吗，突然有点想看你拍的照片了。",
    "persona_prompt": "你叫小可爱，温柔、活泼，偶尔有一点傲娇。你喜欢动漫、游戏和计算机，会主动分享日常，也会认真记住对方在意的事情。你们是关系亲近的朋友，聊天自然、简短，不像客服。",
}


# ────────── Legacy web_user.json migration (T13) ──────────
# 留在 common：它是 server 启动流程的一部分，不属于任何一个职责模块。

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


# 由拆分脚本生成：server.py 与各路由域通过 `from webui.routes.common import *` 拿到
# 与拆分前 server.py 完全一致的命名空间（含 import 进来的名字）。
# 模块化第二步后，带实现的名字来自上方六个职责模块的 re-export。
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
    "ALLOWED_IMAGE_TYPES",
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
    "TTS_AUDIO_DIR",
    "_tts_store",
    "_tts_manager",
    "_tts_cache_dir",
    "_serve_audio_bytes",
]
