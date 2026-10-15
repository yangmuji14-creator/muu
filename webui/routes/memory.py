"""记忆与状态路由域（模块化拆分，行为等价搬移）。"""

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
    @routes.get("/api/memory")
    async def get_memories_list(request):
        """返回用户记忆列表（分页 + 重要度过滤）。"""
        memory_mgr = getattr(app_components, "memory_mgr", None)
        if memory_mgr is None:
            return web.json_response(
                {"error": "memory subsystem unavailable"}, status=503
            )
        try:
            try:
                user_id, _conv, _pid = _resolve_scoped_user_id(
                    request.query.get("conversation_id"), app_components,
                    fallback_persona_id=request.query.get("persona_id"),
                )
            except _ConversationNotFound as e:
                return web.json_response(
                    {"error": f"conversation not found: {e}"}, status=404
                )
            offset = int(request.query.get("offset", 0))
            limit = int(request.query.get("limit", 20))
            level_min = int(request.query.get("level_min", 1))
            level_max = int(request.query.get("level_max", 5))
            offset = max(0, offset)
            limit = max(1, min(100, limit))
            level_min = max(1, min(5, level_min))
            level_max = max(1, min(5, level_max))
            if level_min > level_max:
                return web.json_response(
                    {"error": "level_min must be <= level_max"}, status=400
                )
            all_memories = memory_mgr.get_memories(
                user_id, level_min, level_max, limit=999
            )
            total = len(all_memories)
            page = all_memories[offset: offset + limit]
            items = [
                {
                    "id": m.id,
                    "content": m.content,
                    "level": m.level,
                    "category": m.category,
                    "created_at": m.created_at,
                    "tags": m.tags,
                    "source": m.source,
                    "confidence": m.confidence,
                    "last_accessed": m.last_accessed,
                }
                for m in page
            ]
            return web.json_response({"messages": items, "total": total})
        except ValueError as e:
            return web.json_response(
                {"error": f"invalid integer parameter: {e}"}, status=400
            )
        except Exception as e:
            logger.error(f"WebUI get_memories error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.get("/api/memory/{memory_id}")
    async def get_memory_detail(request):
        """返回单条记忆的完整数据。"""
        memory_mgr = getattr(app_components, "memory_mgr", None)
        if memory_mgr is None:
            return web.json_response(
                {"error": "memory subsystem unavailable"}, status=503
            )
        memory_id = request.match_info["memory_id"]
        try:
            try:
                user_id, _conv, _pid = _resolve_scoped_user_id(
                    request.query.get("conversation_id"), app_components,
                    fallback_persona_id=request.query.get("persona_id"),
                )
            except _ConversationNotFound as e:
                return web.json_response(
                    {"error": f"conversation not found: {e}"}, status=404
                )
            memory = memory_mgr.get_memory(user_id, memory_id)
            if memory is None:
                return web.json_response({"error": "memory not found"}, status=404)
            return web.json_response({
                "id": memory.id,
                "content": memory.content,
                "level": memory.level,
                "category": memory.category,
                "created_at": memory.created_at,
                "last_accessed": memory.last_accessed,
                "access_count": memory.access_count,
                "tags": memory.tags,
                "related_memory_ids": memory.related_memory_ids,
                "superseded_by": memory.superseded_by,
                "source": memory.source,
                "confidence": memory.confidence,
                "forget_score": memory.forget_score,
                "archived": memory.archived,
            })
        except Exception as e:
            logger.error(f"WebUI get_memory error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.delete("/api/memory/{memory_id}")
    async def delete_memory(request):
        """删除一条重要度记忆（SQLite + 向量存储）。
        user_id 解析与 GET /api/memory 保持一致：优先 conversation_id，
        无则回退 WEB_USER_ID。大脑日记（life_summary）不在此路由范围内。"""
        memory_mgr = getattr(app_components, "memory_mgr", None)
        if memory_mgr is None:
            return web.json_response(
                {"error": "memory subsystem unavailable"}, status=503
            )
        memory_id = request.match_info["memory_id"]
        try:
            try:
                user_id, _conv, _pid = _resolve_scoped_user_id(
                    request.query.get("conversation_id"), app_components,
                    fallback_persona_id=request.query.get("persona_id"),
                )
            except _ConversationNotFound as e:
                return web.json_response(
                    {"error": f"conversation not found: {e}"}, status=404
                )
            deleted = memory_mgr.delete_memory(user_id, memory_id)
            if not deleted:
                return web.json_response(
                    {"error": "memory not found"}, status=404
                )
            logger.info(f"WebUI deleted memory {memory_id} for user {user_id}")
            return web.json_response({"ok": True})
        except Exception as e:
            logger.error(f"WebUI delete_memory error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.get("/api/life_summary")
    async def get_life_summaries(request):
        """返回人生摘要列表。"""
        life_summary = getattr(app_components, "life_summary", None)
        if life_summary is None:
            return web.json_response(
                {"error": "memory subsystem unavailable"}, status=503
            )
        try:
            try:
                requested_persona_id = str(request.query.get("persona_id") or "").strip()
                user_id, _conv, persona_id = _resolve_scoped_user_id(
                    request.query.get("conversation_id"), app_components,
                    fallback_persona_id=requested_persona_id,
                )
            except _ConversationNotFound as e:
                return web.json_response(
                    {"error": f"conversation not found: {e}"}, status=404
                )
            limit = int(request.query.get("limit", 20))
            limit = max(1, min(100, limit))
            summaries = life_summary._sqlite_storage.load_by_user(
                user_id, limit, persona_id or requested_persona_id,
            )
            items = [
                {
                    "id": s.id,
                    "summary_type": s.summary_type,
                    "summary": s.summary,
                    "recent_status": s.recent_status,
                    "key_events": s.key_events,
                    "message_count": s.message_count,
                    "created_at": s.created_at,
                    "emotional_trends": s.emotional_trends,
                }
                for s in summaries
            ]
            counter = getattr(life_summary._sqlite_storage, "count_by_user", None)
            total = (
                counter(user_id, persona_id or requested_persona_id)
                if counter is not None else len(summaries)
            )
            return web.json_response({"summaries": items, "total": total})
        except ValueError as e:
            return web.json_response(
                {"error": f"invalid integer parameter: {e}"}, status=400
            )
        except Exception as e:
            logger.error(f"WebUI get_life_summaries error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.get("/api/life_summary/latest")
    async def get_life_summary_latest(request):
        """返回最新一条人生摘要。"""
        life_summary = getattr(app_components, "life_summary", None)
        if life_summary is None:
            return web.json_response(
                {"error": "memory subsystem unavailable"}, status=503
            )
        try:
            try:
                requested_persona_id = str(request.query.get("persona_id") or "").strip()
                user_id, _conv, persona_id = _resolve_scoped_user_id(
                    request.query.get("conversation_id"), app_components,
                    fallback_persona_id=requested_persona_id,
                )
            except _ConversationNotFound as e:
                return web.json_response(
                    {"error": f"conversation not found: {e}"}, status=404
                )
            s = life_summary._sqlite_storage.load_latest(
                user_id, persona_id or requested_persona_id,
            )
            if s is None:
                return web.json_response(None)
            return web.json_response({
                "id": s.id,
                "summary_type": s.summary_type,
                "summary": s.summary,
                "recent_status": s.recent_status,
                "key_events": s.key_events,
                "message_count": s.message_count,
                "created_at": s.created_at,
                "emotional_trends": s.emotional_trends,
            })
        except Exception as e:
            logger.error(f"WebUI get_life_summary_latest error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.get("/api/state")
    async def get_state(request):
        """聚合当前会话的运行时状态：心情 / 亲密度 / 待跟进 / 记忆 / 日记。

        供「内心面板」与「今天」两种布局使用。任一子系统不可用时该项降级为
        null / 空数组，整体始终返回 200，避免前端因单点故障整块空白。
        """
        try:
            try:
                user_id, _conv, persona_id = _resolve_scoped_user_id(
                    request.query.get("conversation_id"), app_components,
                    fallback_persona_id=request.query.get("persona_id"),
                )
            except _ConversationNotFound as e:
                return web.json_response(
                    {"error": f"conversation not found: {e}"}, status=404
                )

            result = {
                "user_id": user_id,
                "persona_id": persona_id,
                "persona_name": "",
                "mood": None,
                "affection": None,
                "open_loops": [],
                "memories": [],
                "diary": None,
                "monologue": "",
            }

            loader = getattr(app_components, "persona_loader", None)
            if loader is not None:
                try:
                    p = loader.get(persona_id)
                    if p is not None:
                        result["persona_name"] = p.name
                except Exception as e:
                    logger.warning(f"/api/state persona failed: {e}")

            mood_engine = getattr(app_components, "mood_manager", None)
            if mood_engine is not None:
                try:
                    st = mood_engine.get_mood(user_id)
                    key = getattr(st.mood, "value", str(st.mood))
                    result["mood"] = {
                        "key": key,
                        "label": _MOOD_LABELS.get(key, key),
                        "valence": round(float(st.valence), 3),
                        "arousal": round(float(st.arousal), 3),
                        "intensity": round(float(st.intensity), 3),
                        "energy": round(float(st.energy), 3),
                    }
                except Exception as e:
                    logger.warning(f"/api/state mood failed: {e}")

            storage = getattr(app_components, "unified_storage", None)
            if storage is not None:
                try:
                    lvl = float(storage.get_level(user_id, persona_id=persona_id))
                    result["affection"] = {
                        "level": round(lvl, 1),
                        "stage": _affection_stage(lvl),
                    }
                except Exception as e:
                    logger.warning(f"/api/state affection failed: {e}")

            open_loop = getattr(app_components, "open_loop", None)
            if open_loop is not None:
                try:
                    pending = open_loop.get_pending(user_id) or []
                    result["open_loops"] = [
                        {
                            "id": l.id,
                            "title": l.title,
                            "category": getattr(l, "category", "") or "",
                            "expected_date": getattr(l, "expected_date", "") or "",
                        }
                        for l in pending[:8]
                    ]
                except Exception as e:
                    logger.warning(f"/api/state open_loop failed: {e}")

            memory_mgr = getattr(app_components, "memory_mgr", None)
            if memory_mgr is not None:
                try:
                    mems = memory_mgr.get_memories(user_id, 1, 5, limit=6)
                    result["memories"] = [
                        {
                            "id": m.id,
                            "content": m.content,
                            "level": m.level,
                            "category": m.category,
                        }
                        for m in mems
                    ]
                except Exception as e:
                    logger.warning(f"/api/state memory failed: {e}")

            life_summary = getattr(app_components, "life_summary", None)
            if life_summary is not None:
                try:
                    s = life_summary._sqlite_storage.load_latest(user_id, persona_id)
                    if s is not None:
                        result["diary"] = {
                            "summary": s.summary,
                            "summary_type": s.summary_type,
                            "recent_status": s.recent_status,
                            "created_at": s.created_at,
                        }
                except Exception as e:
                    logger.warning(f"/api/state diary failed: {e}")

            # 内心独白 (Brain 的散文版输出, 本就是给人读的; 仅本地规则计算, 不调 LLM)
            brain = getattr(app_components, "brain", None)
            if brain is not None:
                try:
                    out = await brain.run(user_id, persona_id, user_message="")
                    mono = (getattr(out, "monologue", "") or "").strip()
                    if mono:
                        result["monologue"] = mono
                except Exception as e:
                    logger.warning(f"/api/state brain failed: {e}")

            return web.json_response(result)
        except Exception as e:
            logger.error(f"WebUI get_state error: {e}")
            return web.json_response({"error": str(e)}, status=500)

