"""插件与贴纸路由域（模块化拆分，行为等价搬移）。"""

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
    # 由 _make_app 统一创建并挂到 app_components 上（见 server.py）
    sticker_service = app_components.sticker_service

    @routes.get("/api/plugins")
    async def list_plugins(_request):
        from core.tools.base import ToolRegistry
        from core.tools.builtin import register_all

        registry = ToolRegistry()
        try:
            data_dir = str(DATA_DIR)
            register_all(registry, data_dir=data_dir)
        except Exception as e:
            logger.warning(f"plugins builtin register failed: {e}")

        builtin = []
        for tool in registry.list_tools():
            builtin.append({
                "source": "builtin",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            })

        mcp_tools = []
        mcp = getattr(app_components, "mcp_manager", None)
        if mcp is not None:
            try:
                for t in mcp.get_all_tools():
                    mcp_tools.append({
                        "source": "mcp",
                        "name": getattr(t, "name", ""),
                        "description": getattr(t, "description", ""),
                        "server": getattr(t, "server_name", "")
                        or getattr(t, "server", "") or "",
                    })
            except Exception as e:
                logger.warning(f"plugins mcp tools failed: {e}")

        return web.json_response({
            "plugins": builtin + mcp_tools,
            "builtin_count": len(builtin),
            "mcp_count": len(mcp_tools),
            "mcp_status": mcp.get_status() if mcp is not None else None,
        })

    # ---- TTS 语音回复（服务商 CRUD + 合成）----

    @routes.get("/api/stickers")
    async def list_stickers(_request):
        return web.json_response({"stickers": sticker_service.list_stickers()})

    @routes.get("/api/stickers/file/{pack}/{emotion}/{filename}")
    async def sticker_file(request):
        try:
            path = sticker_service.resolve(
                request.match_info["pack"], request.match_info["emotion"],
                request.match_info["filename"],
            )
        except (ValueError, FileNotFoundError):
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    @routes.post("/api/stickers/import")
    async def import_stickers(request):
        reader = await request.multipart()
        upload = None
        pack = ""
        temp_path = DATA_DIR / f"tmp-sticker-import-{uuid.uuid4().hex}.zip"
        try:
            async for part in reader:
                if part.name == "pack":
                    pack = (await part.text()).strip()
                elif part.name in {"file", "stickers"}:
                    temp_path.parent.mkdir(parents=True, exist_ok=True)
                    with temp_path.open("wb") as output:
                        while chunk := await part.read_chunk():
                            output.write(chunk)
                    upload = temp_path
            if not upload or not pack:
                return web.json_response({"error": "pack and file are required"}, status=400)
            return web.json_response({"ok": True, **sticker_service.import_zip(upload, pack)})
        except (ValueError, zipfile.BadZipFile) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        finally:
            temp_path.unlink(missing_ok=True)

