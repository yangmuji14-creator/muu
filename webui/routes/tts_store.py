"""TTS 语音存储与音频流式响应。

从 common.py 拆出（2026-11-01 模块化第二步）。
TTS 生成/合成逻辑在 webui.tts；这里只管缓存目录与 HTTP Range 播放。
"""

from __future__ import annotations

from pathlib import Path

from core.config import CONFIG_DIR, DATA_DIR
from webui.tts import TTSManager, TTSStore

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
