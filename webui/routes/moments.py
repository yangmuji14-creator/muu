"""朋友圈（moments）路由域（模块化拆分，行为等价搬移）。"""

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

    def _serialize_moment(m: dict) -> dict:
        replies_raw = list(m.get("replies", []) or [])
        reply_authors = {r.get("id"): r.get("author", "") for r in replies_raw}
        replies = []
        for r in replies_raw:
            rt = r.get("reply_to") or None
            rt_author = reply_authors.get(rt) if rt else None
            replies.append({
                "id": r.get("id", ""),
                "author": r.get("author", ""),
                "author_label": _moment_author_label(app_components, r.get("author", "")),
                "timestamp": r.get("timestamp", ""),
                "text": r.get("text", ""),
                "reply_to": rt,
                "reply_to_label": _moment_author_label(app_components, rt_author) if rt_author else None,
            })
        likes = [
            {"author": w, "author_label": _moment_author_label(app_components, w)}
            for w in (m.get("likes", []) or [])
        ]
        return {
            "id": m.get("id", ""),
            "author": m.get("author", ""),
            "author_label": _moment_author_label(app_components, m.get("author", "")),
            "timestamp": m.get("timestamp", ""),
            "text": m.get("text", ""),
            "likes": likes,
            "replies": replies,
        }

    def _now_iso() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    @routes.get("/api/moments")
    async def list_moments(request):
        moments = _load_moments()
        try:
            limit = max(1, min(int(request.query.get("limit", 20)), 50))
        except ValueError:
            limit = 20
        has_more = len(moments) > limit
        return web.json_response({
            "moments": [_serialize_moment(m) for m in moments[:limit]],
            "has_more": has_more,
        })

    @routes.get("/api/moments/personas")
    async def list_moment_authors(_request):
        loader = getattr(app_components, "persona_loader", None)
        personas = []
        try:
            if loader is not None:
                personas = [{"id": p.id, "name": p.name} for p in loader.list_all()]
        except Exception as exc:
            logger.warning(f"moments personas failed: {exc}")
        return web.json_response({"personas": personas})

    @routes.post("/api/moments")
    async def publish_moment(request):
        body = await request.json()
        text = (body.get("text") or "").strip()
        author = (body.get("author") or "").strip() or "user"
        if not text:
            return web.json_response({"error": "文案不能为空"}, status=400)
        if len(text) > _MAX_POST_TEXT:
            return web.json_response({"error": "文案过长"}, status=400)
        moments = _load_moments()
        moments.insert(0, {
            "id": _new_moment_id(),
            "author": author,
            "timestamp": _now_iso(),
            "text": text,
            "likes": [],
            "replies": [],
        })
        _save_moments(moments)
        return web.json_response({"ok": True, "moment": _serialize_moment(moments[0])}, status=201)

    @routes.delete("/api/moments/{moment_id}")
    async def delete_moment(request):
        mid = request.match_info["moment_id"]
        if not _MOMENT_ID_RE.match(mid):
            return web.json_response({"error": "invalid id"}, status=400)
        moments = _load_moments()
        nxt = [m for m in moments if m.get("id") != mid]
        if len(nxt) == len(moments):
            return web.json_response({"error": "not found"}, status=404)
        _save_moments(nxt)
        return web.json_response({"ok": True})

    @routes.post("/api/moments/{moment_id}/like")
    async def like_moment(request):
        mid = request.match_info["moment_id"]
        moments = _load_moments()
        m = next((x for x in moments if x.get("id") == mid), None)
        if m is None:
            return web.json_response({"error": "not found"}, status=404)
        likes = m.setdefault("likes", [])
        if "user" not in likes:
            likes.append("user")
        _save_moments(moments)
        return web.json_response({"ok": True, "added": True})

    @routes.delete("/api/moments/{moment_id}/like")
    async def unlike_moment(request):
        mid = request.match_info["moment_id"]
        moments = _load_moments()
        m = next((x for x in moments if x.get("id") == mid), None)
        if m is None:
            return web.json_response({"error": "not found"}, status=404)
        likes = m.setdefault("likes", [])
        added = "user" in likes
        m["likes"] = [w for w in likes if w != "user"]
        _save_moments(moments)
        return web.json_response({"ok": True, "removed": added})

    @routes.post("/api/moments/{moment_id}/replies")
    async def post_reply(request):
        mid = request.match_info["moment_id"]
        body = await request.json()
        text = (body.get("text") or "").strip()
        reply_to = body.get("reply_to") or None
        if not text:
            return web.json_response({"error": "评论不能为空"}, status=400)
        if len(text) > _MAX_REPLY_TEXT:
            return web.json_response({"error": "评论过长"}, status=400)
        if reply_to is not None and not _REPLY_ID_RE.match(reply_to):
            return web.json_response({"error": "invalid reply_to"}, status=400)
        moments = _load_moments()
        m = next((x for x in moments if x.get("id") == mid), None)
        if m is None:
            return web.json_response({"error": "not found"}, status=404)
        now = _now_iso()
        r = {
            "id": _new_reply_id(),
            "author": "user",
            "timestamp": now,
            "text": text,
            "reply_to": reply_to,
        }
        m.setdefault("replies", []).append(r)
        _save_moments(moments)
        return web.json_response({"ok": True, "reply": _serialize_moment(m)["replies"][-1]}, status=201)

    @routes.delete("/api/moments/{moment_id}/replies/{reply_id}")
    async def delete_reply(request):
        mid = request.match_info["moment_id"]
        rid = request.match_info["reply_id"]
        if not _MOMENT_ID_RE.match(mid) or not _REPLY_ID_RE.match(rid):
            return web.json_response({"error": "invalid id"}, status=400)
        moments = _load_moments()
        m = next((x for x in moments if x.get("id") == mid), None)
        if m is None:
            return web.json_response({"error": "not found"}, status=404)
        before = len(m.get("replies", []))
        m["replies"] = [r for r in m.get("replies", []) if r.get("id") != rid]
        if len(m["replies"]) == before:
            return web.json_response({"error": "reply not found"}, status=404)
        _save_moments(moments)
        return web.json_response({"ok": True})

    # ---- 朋友圈自动发布（AI 自动发朋友圈）----

    def _poster_config() -> dict:
        return load_poster_config(_load_settings())

    @routes.get("/api/moments/auto/config")
    async def get_auto_config(_request):
        cfg = _poster_config()
        loader = getattr(app_components, "persona_loader", None)
        personas = []
        try:
            if loader is not None:
                personas = [{"id": p.id, "name": p.name} for p in loader.list_all()]
        except Exception as exc:
            logger.warning(f"moments auto personas failed: {exc}")
        return web.json_response({"config": cfg, "personas": personas})

    @routes.put("/api/moments/auto/config")
    async def put_auto_config(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "请求格式不正确"}, status=400)
        cfg = _poster_config()
        for key in ("enabled", "interval_minutes", "persona_id", "active_start", "active_end"):
            if key in body:
                cfg[key] = body[key]
        normalized = load_poster_config({"advanced": {"moments_auto_poster": cfg}})
        settings = _load_settings()
        settings.setdefault("advanced", {})["moments_auto_poster"] = normalized
        _save_settings(settings)
        return web.json_response({"ok": True, "config": normalized})

    @routes.post("/api/moments/auto/publish")
    async def post_auto_publish(_request):
        """手动触发一次自动发布（无视时间窗口与间隔，但仍要求启用 + 指定人设）。"""
        poster = getattr(app_components, "moments_poster", None)
        if poster is None:
            return web.json_response({"error": "自动发布器未启动"}, status=503)
        poster._last_posted_at = None  # 重置间隔，强制本次发布
        published = await poster.publish_once(force=True)
        if not published:
            return web.json_response(
                {"ok": False, "error": "未发布：请在设置中启用并指定人设"},
                status=400,
            )
        return web.json_response({"ok": True})

    # ---- 插件管理（内置工具 + MCP 工具目录，只读）----

