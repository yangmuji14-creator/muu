"""MCP servers 配置读写（CONFIG_DIR/mcp_servers.json）。

从 common.py 拆出（2026-11-01 模块化第二步）。
MCPManager 本体在 core.tools；这里只负责配置文件的持久化与白名单过滤。
"""

from __future__ import annotations

import json
import os

from loguru import logger

from core.config import CONFIG_DIR

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
