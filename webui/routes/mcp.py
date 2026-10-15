"""MCP 扩展路由域（模块化拆分，行为等价搬移）。"""

from __future__ import annotations

import asyncio  # noqa: F401
import io  # noqa: F401
import inspect  # noqa: F401
import json  # noqa: F401
import os  # noqa: F401
import re  # noqa: F401
import secrets  # noqa: F401
import tempfile  # noqa: F401
import threading  # noqa: F401
import uuid  # noqa: F401
import zipfile  # noqa: F401
from pathlib import Path  # noqa: F401
from loguru import logger  # noqa: F401
from aiohttp import web

from webui.routes.common import *  # noqa: F401,F403


def register(routes, app_components):

    async def _mcp_status_overlay() -> dict:
        """best-effort：从 mcp_manager 拿实时连接状态；失败返回空。"""
        mcp = getattr(app_components, "mcp_manager", None)
        if mcp is None:
            return {}
        try:
            return mcp.get_status()
        except Exception:
            return {}

    @routes.get("/api/mcp/servers")
    async def list_mcp_servers(_request):
        servers = _load_mcp_servers()
        status = await _mcp_status_overlay()
        for s in servers:
            name = s.get("name", "")
            st = status.get(name) or {}
            s["_state"] = st.get("state", "disconnected")
            s["_connected"] = bool(st.get("connected", False))
            s["_tools"] = int(st.get("tools", 0) or 0)
        return web.json_response({"servers": servers})

    @routes.post("/api/mcp/servers")
    async def add_mcp_server(request):
        body = await request.json()
        name = str(body.get("name") or "").strip()
        command = str(body.get("command") or "").strip()
        if not name:
            return web.json_response({"error": "服务名不能为空"}, status=400)
        if not command:
            return web.json_response({"error": "启动命令不能为空"}, status=400)
        servers = _load_mcp_servers()
        if any(s.get("name") == name for s in servers):
            return web.json_response({"error": f"已存在同名服务: {name}"}, status=409)
        entry = _sanitize_mcp_server(body)
        entry["name"] = name
        entry["command"] = command
        servers.append(entry)
        _save_mcp_servers(servers)
        return web.json_response({"ok": True, "server": entry}, status=201)

    @routes.put("/api/mcp/servers/{name}")
    async def update_mcp_server(request):
        name = request.match_info["name"]
        body = await request.json()
        servers = _load_mcp_servers()
        idx = next((i for i, s in enumerate(servers) if s.get("name") == name), None)
        if idx is None:
            return web.json_response({"error": "server not found"}, status=404)
        entry = _sanitize_mcp_server(body)
        entry["name"] = name
        servers[idx] = entry
        _save_mcp_servers(servers)
        return web.json_response({"ok": True, "server": entry})

    @routes.delete("/api/mcp/servers/{name}")
    async def delete_mcp_server(request):
        name = request.match_info["name"]
        servers = _load_mcp_servers()
        nxt = [s for s in servers if s.get("name") != name]
        if len(nxt) == len(servers):
            return web.json_response({"error": "server not found"}, status=404)
        _save_mcp_servers(nxt)
        return web.json_response({"ok": True})

    @routes.post("/api/mcp/connect")
    async def connect_mcp_servers(_request):
        mcp = getattr(app_components, "mcp_manager", None)
        if mcp is None:
            return web.json_response({"error": "MCP manager 不可用"}, status=503)
        try:
            connected = await mcp.load_and_connect(CONFIG_DIR)
        except Exception as exc:
            logger.warning(f"MCP connect failed: {exc}")
            return web.json_response({"error": str(exc)}, status=500)
        return web.json_response({"ok": True, "connected": connected})

    # ---- MCP per-server 控制 ----

    def _mcp_mgr_or_503():
        mcp = getattr(app_components, "mcp_manager", None)
        if mcp is None:
            return None, web.json_response({"error": "MCP manager 不可用"}, status=503)
        return mcp, None

    def _find_mcp_server(name: str):
        for s in _load_mcp_servers():
            if s.get("name") == name:
                return s
        return None

    @routes.post("/api/mcp/servers/{name}/test")
    async def test_mcp_server(request):
        name = request.match_info["name"]
        srv = _find_mcp_server(name)
        if srv is None:
            return web.json_response({"error": "server not found"}, status=404)
        mcp, err = _mcp_mgr_or_503()
        if err:
            return err
        try:
            result = await mcp.test_server(srv)
        except Exception as exc:
            logger.warning(f"MCP test {name} failed: {exc}")
            return web.json_response({"ok": False, "error": str(exc)})
        return web.json_response(result)

    @routes.post("/api/mcp/servers/{name}/connect")
    async def connect_mcp_server(request):
        name = request.match_info["name"]
        srv = _find_mcp_server(name)
        if srv is None:
            return web.json_response({"error": "server not found"}, status=404)
        mcp, err = _mcp_mgr_or_503()
        if err:
            return err
        try:
            ok = await mcp.connect_server(srv)
        except Exception as exc:
            logger.warning(f"MCP connect {name} failed: {exc}")
            return web.json_response({"error": str(exc)}, status=500)
        return web.json_response({"ok": True, "connected": ok})

    @routes.post("/api/mcp/servers/{name}/disconnect")
    async def disconnect_mcp_server(request):
        name = request.match_info["name"]
        srv = _find_mcp_server(name)
        if srv is None:
            return web.json_response({"error": "server not found"}, status=404)
        mcp, err = _mcp_mgr_or_503()
        if err:
            return err
        try:
            await mcp.disconnect_server(srv)
        except Exception as exc:
            logger.warning(f"MCP disconnect {name} failed: {exc}")
        return web.json_response({"ok": True})

    @routes.post("/api/mcp/servers/{name}/refresh")
    async def refresh_mcp_server(request):
        name = request.match_info["name"]
        srv = _find_mcp_server(name)
        if srv is None:
            return web.json_response({"error": "server not found"}, status=404)
        mcp, err = _mcp_mgr_or_503()
        if err:
            return err
        try:
            count = await mcp.refresh_server(srv)
        except Exception as exc:
            logger.warning(f"MCP refresh {name} failed: {exc}")
            return web.json_response({"error": str(exc)}, status=500)
        return web.json_response({"ok": True, "tools": count})

    @routes.get("/api/mcp/servers/{name}/tools")
    async def mcp_server_tools(request):
        name = request.match_info["name"]
        mcp, err = _mcp_mgr_or_503()
        if err:
            return err
        tools = mcp.get_server_tools(name)
        return web.json_response({
            "tools": [{"name": t.name, "description": t.description} for t in tools],
        })

