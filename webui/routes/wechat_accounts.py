"""微信多账号：配置读写、凭证路径、运行时联动与自动启动。

从 common.py 拆出（2026-11-01 模块化第二步）。
依赖 settings_store 的 settings 读写 —— 这是本目录里唯一一块模块间依赖。
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from loguru import logger

from core.config import ROOT, normalize_wechat_accounts
from webui.routes.settings_store import _load_settings, _save_settings

WECHAT_CREDS_DIR = ROOT / "data" / "credentials"

# WeChat account_id validation (matches adapters/wechat.py _ACCOUNT_ID_PATTERN).
# "default" is exempt from the length requirement (backward compat).
_WECHAT_ACCOUNT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")

# Per-account SSE login locks — keyed by account_id. Concurrent login to the
# same account returns 409. Module-level so locks survive across requests.
_wechat_login_locks: dict[str, asyncio.Lock] = {}


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
