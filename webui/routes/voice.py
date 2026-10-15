"""语音服务商与音频路由域（模块化拆分，行为等价搬移）。"""

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

    def _providers_public() -> list[dict]:
        out = []
        for p in _tts_store().load_providers():
            d = p.to_dict()
            d["has_api_key"] = bool(d.pop("api_key", ""))
            out.append(d)
        return out

    @routes.get("/api/voice-providers")
    async def get_voice_providers(_request):
        store = _tts_store()
        active = store.active_provider()
        return web.json_response({
            "providers": _providers_public(),
            "active": active.name if active else None,
        })

    @routes.post("/api/voice-providers")
    async def post_voice_provider(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "请求格式不正确"}, status=400)
        name = str(body.get("name") or "").strip()
        if not name:
            return web.json_response({"error": "服务商名称不能为空"}, status=400)
        store = _tts_store()
        providers = store.load_providers()
        if any(p.name == name for p in providers):
            return web.json_response({"error": "服务商已存在"}, status=409)
        providers.append(TTSProvider.from_dict(body))
        store.save_providers(providers)
        return web.json_response({"ok": True})

    @routes.put("/api/voice-providers/{name}")
    async def put_voice_provider(request):
        name = request.match_info["name"]
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "请求格式不正确"}, status=400)
        store = _tts_store()
        providers = store.load_providers()
        found = next((p for p in providers if p.name == name), None)
        if found is None:
            return web.json_response({"error": "not found"}, status=404)
        updated = TTSProvider.from_dict({**found.to_dict(), **body, "name": name})
        idx = providers.index(found)
        # 未传新 api_key 时保留旧 key（前端 masked，不发回明文）
        if not body.get("api_key") and found.api_key:
            updated.api_key = found.api_key
        providers[idx] = updated
        store.save_providers(providers)
        return web.json_response({"ok": True})

    @routes.delete("/api/voice-providers/{name}")
    async def delete_voice_provider(request):
        name = request.match_info["name"]
        store = _tts_store()
        providers = store.load_providers()
        nxt = [p for p in providers if p.name != name]
        if len(nxt) == len(providers):
            return web.json_response({"error": "not found"}, status=404)
        store.save_providers(nxt)
        return web.json_response({"ok": True})

    @routes.post("/api/voice-providers/{name}/test")
    async def test_voice_provider(request):
        name = request.match_info["name"]
        store = _tts_store()
        prov = next((p for p in store.load_providers() if p.name == name), None)
        if prov is None:
            return web.json_response({"error": "not found"}, status=404)
        try:
            data = await _tts_manager().synthesize("你好，我是慕。", provider=prov)
        except Exception as e:
            logger.warning(f"voice provider {name} test failed: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=400)
        return web.json_response({"ok": True, "bytes": len(data)})

    @routes.get("/api/audio/synthesize")
    async def synthesize_audio(request):
        """按给文字 + 可选音色合成一段语音（供试听 / 前端预合成用）。"""
        text = request.query.get("text", "").strip()
        if not text:
            return web.json_response({"error": "text 不能为空"}, status=400)
        if len(text) > 500:
            return web.json_response({"error": "text 过长"}, status=400)
        voice = request.query.get("voice", "").strip() or None
        try:
            data = await _tts_manager().synthesize(text, voice=voice)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)
        return _serve_audio_bytes(request, data)

    # ---- TTS 语音合成缓存（供聊天回复 voice 渲染）----

    async def _synthesize_for_chat(persona_id: str, text: str) -> str | None:
        """真人设 + 语音服务商可用时合成语音，返回可访问的 /api/audio/... 相对 URL。

        失败 / 未配置服务商时返回 None（前端回退为纯文字）。"""
        try:
            data = await _tts_manager().synthesize(text)
        except Exception as e:
            logger.warning(f"chat TTS synthesis skipped: {e}")
            return None
        fname = f"{persona_id}_{uuid.uuid4().hex}.mp3"
        path = _tts_cache_dir() / fname
        path.write_bytes(data)
        return f"/api/audio/{persona_id}/{fname}"

    @routes.get("/api/audio/{persona_id}/{fname}")
    async def get_audio_file(request):
        pid = request.match_info["persona_id"]
        fname = request.match_info["fname"]
        if (
            not re.fullmatch(r"[A-Za-z0-9_.-]+", fname)
            or ".." in fname
            or fname.startswith(".")
        ):
            # ".." 能过字符白名单：打开目录会 IsADirectoryError -> 500，
            # 连续点号也可能在软链/大小写变体下探出缓存目录
            return web.json_response({"error": "invalid name"}, status=400)
        path = _tts_cache_dir() / fname
        if not path.is_file():
            return web.json_response({"error": "not found"}, status=404)
        return _serve_audio_bytes(request, path.read_bytes())

    # ---- MCP 扩展 ----

