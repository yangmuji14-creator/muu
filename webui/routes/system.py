"""系统与设置（健康/诊断/备份/设置）路由域（模块化拆分，行为等价搬移）。"""

from __future__ import annotations

import asyncio  # noqa: F401
import base64  # noqa: F401
import html  # noqa: F401
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

    def _diagnostic_report() -> dict:
        return run_diagnostics(
            app_components,
            data_dir=DATA_DIR,
            config_dir=SETTINGS_PATH.parent,
            settings=_load_settings(),
            secret_manager=_secret_manager(),
        )

    @routes.get("/")
    async def index(_request):
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            # index.html 里引用的是带内容哈希的资源名 (index-XXXX.js/css)。
            # 若被浏览器启发式缓存, 前端重新构建后它会指向已被删除的旧资源,
            # 结果就是白屏 / 卡在"引导中…"。这里强制每次重新校验:
            # 文件没变时服务端返回 304, 依然很快。
            return web.FileResponse(
                index_file,
                headers={"Cache-Control": "no-cache, must-revalidate"},
            )
        return web.Response(
            text="webui/static/index.html 尚未生成", status=404
        )

    @routes.get("/api/schema")
    async def get_schema(_request):
        return web.json_response({"schema": SETTINGS_SCHEMA})

    @routes.get("/api/health")
    async def get_health(_request):
        from core.runtime import runtime_metrics
        registry = getattr(app_components, "registry", None)
        mcp = getattr(app_components, "mcp_manager", None)
        return web.json_response({
            "ok": True,
            "models": len(getattr(registry, "available_models", [])),
            "mcp_servers": getattr(mcp, "connected_count", 0),
            "runtime": runtime_metrics.snapshot(),
        })

    # ---- 发现（朋友圈）routes ----

    from webui.routes.moments import register as _register_moments
    _register_moments(routes, app_components)
    from webui.routes.plugins import register as _register_plugins
    _register_plugins(routes, app_components)
    from webui.routes.voice import register as _register_voice
    _register_voice(routes, app_components)
    from webui.routes.mcp import register as _register_mcp
    _register_mcp(routes, app_components)
    @routes.get("/api/diagnostics")
    async def get_diagnostics(_request):
        """Run local checks without contacting model providers or exposing data."""
        return web.json_response(_diagnostic_report())

    @routes.get("/api/diagnostics/export")
    async def export_diagnostics(_request):
        """Export a sanitized support bundle without logs, messages or secrets."""
        report = _diagnostic_report()
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "diagnostics.json",
                json.dumps(report, ensure_ascii=False, indent=2),
            )
            archive.writestr(
                "settings.sanitized.json",
                json.dumps(sanitize_settings(_load_settings()), ensure_ascii=False, indent=2),
            )
        return web.Response(
            body=output.getvalue(),
            content_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="mu-diagnostics.zip"',
                "Cache-Control": "no-store",
            },
        )

    from webui.routes.bootstrap import register as _register_bootstrap
    _register_bootstrap(routes, app_components)
    @routes.get("/api/settings")
    async def get_settings(_request):
        return web.json_response({"values": _current_values()})

    @routes.get("/api/about")
    async def get_about(_request):
        return web.json_response({
            "name": "慕",
            "version": _app_version(),
            "license": "AGPL-3.0",
            "author": "yangmuji14-creator",
            "installation_id": _installation_id(),
            "storage": str(DATA_DIR.resolve()),
            "backup_format_version": BACKUP_FORMAT_VERSION,
            "privacy": "对话与人设默认只保存在本机。模型服务仅在发送消息时接收必要的对话内容。",
            "tagline": "慕，只是你夜航时偶遇的浮灯，它能温柔你回望的旧岸，却无法替你横渡真实的黎明。",
        })

    @routes.post("/api/backup")
    async def post_backup(_request):
        try:
            archive = create_backup(DATA_DIR, CONFIG_DIR)
            return web.FileResponse(
                archive,
                headers={
                    "Content-Disposition": f'attachment; filename="{archive.name}"',
                    "Cache-Control": "no-store",
                },
            )
        except Exception as e:
            logger.exception(f"WebUI backup failed: {e}")
            return web.json_response({"error": "backup creation failed"}, status=500)

    @routes.post("/api/backup/inspect")
    async def inspect_uploaded_backup(request):
        """Validate a selected backup before offering an offline restore."""
        try:
            reader = await request.multipart()
            part = await reader.next()
            if part is None or part.name != "backup":
                return web.json_response({"error": "backup file required"}, status=400)
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as temp:
                temp_path = Path(temp.name)
                size = 0
                while chunk := await part.read_chunk():
                    size += len(chunk)
                    if size > 512 * 1024 * 1024:
                        temp_path.unlink(missing_ok=True)
                        return web.json_response({"error": "backup too large"}, status=413)
                    temp.write(chunk)
            try:
                manifest = inspect_backup(temp_path)
                return web.json_response({"ok": True, "manifest": manifest})
            finally:
                temp_path.unlink(missing_ok=True)
        except BackupValidationError as e:
            return web.json_response({"error": str(e)}, status=400)
        except Exception as e:
            logger.error(f"WebUI backup inspection failed: {e}")
            return web.json_response({"error": "backup inspection failed"}, status=500)

    @routes.get("/api/restore/status")
    async def get_restore_status(_request):
        pending = pending_restore_status(DATA_DIR)
        return web.json_response({"pending": bool(pending), "restore": pending})

    @routes.post("/api/restore")
    async def schedule_uploaded_restore(request):
        """Validate and queue a restore; never replace open SQLite files here."""
        temp_path = None
        try:
            reader = await request.multipart()
            part = await reader.next()
            if part is None or part.name != "backup":
                return web.json_response({"error": "backup file required"}, status=400)
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as temp:
                temp_path = Path(temp.name)
                size = 0
                while chunk := await part.read_chunk():
                    size += len(chunk)
                    if size > 512 * 1024 * 1024:
                        return web.json_response({"error": "backup too large"}, status=413)
                    temp.write(chunk)
            queued = schedule_restore(temp_path, DATA_DIR)
            return web.json_response({
                "ok": True,
                "restart_required": True,
                "restore": queued,
            })
        except BackupValidationError as e:
            return web.json_response({"error": str(e)}, status=400)
        except Exception as e:
            logger.exception(f"WebUI restore scheduling failed: {e}")
            return web.json_response({"error": "restore scheduling failed"}, status=500)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    @routes.post("/api/settings")
    async def post_settings(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON"}, status=400)

        incoming = body.get("values", body) or {}
        clean: dict = {}
        for field in SETTINGS_SCHEMA:
            key = field["key"]
            if key in incoming:
                clean[key] = coerce_value(field, incoming[key])

        if not clean:
            return web.json_response({"error": "no valid fields"}, status=400)

        try:
            _persist_values(clean)
            _apply_live(app_components, clean)
        except Exception as e:
            logger.error(f"WebUI: apply settings failed: {e}")
            return web.json_response({"error": str(e)}, status=500)

        return web.json_response({"ok": True, "values": _current_values()})

