"""人设与会话路由域（模块化拆分，行为等价搬移）。"""

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
    @routes.get("/api/persona")
    async def list_personas(_request):
        """返回人设列表（只 id+name+avatar，不含完整字段）。"""
        try:
            personas = app_components.persona_loader.list_all()
            return web.json_response([
                {"id": p.id, "name": p.name, "avatar": getattr(p, "avatar", "") or ""}
                for p in personas
            ])
        except Exception as e:
            logger.error(f"WebUI list_personas error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.get("/api/persona/{persona_id}")
    async def get_persona(request):
        """返回单个人设的 USER_FIELDS（脱敏，不含 ADVANCED_FIELDS）。"""
        persona_id = request.match_info["persona_id"]
        try:
            persona = app_components.persona_loader.get(persona_id)
            if not persona:
                return web.json_response({"error": "persona not found"}, status=404)
            data = {f: getattr(persona, f, None) for f in app_components.persona_loader.USER_FIELDS}
            data["id"] = persona.id
            return web.json_response(data)
        except Exception as e:
            logger.error(f"WebUI get_persona error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.get("/api/persona/{persona_id}/advanced")
    async def get_persona_advanced(request):
        """返回单个人设的 ADVANCED_FIELDS（高级折叠区用）。"""
        persona_id = request.match_info["persona_id"]
        try:
            persona = app_components.persona_loader.get(persona_id)
            if not persona:
                return web.json_response({"error": "persona not found"}, status=404)
            data = {f: getattr(persona, f, None) for f in app_components.persona_loader.ADVANCED_FIELDS}
            return web.json_response(data)
        except Exception as e:
            logger.error(f"WebUI get_persona_advanced error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.post("/api/persona/{persona_id}")
    async def update_persona(request):
        """更新人设字段。body: {"fields": {field: value, ...}}。
        fields 的 key 必须在 USER_FIELDS ∪ ADVANCED_FIELDS 内。
        """
        persona_id = request.match_info["persona_id"]
        try:
            persona = app_components.persona_loader.get(persona_id)
            if not persona:
                return web.json_response({"error": "persona not found"}, status=404)
            body = await request.json()
            fields = body.get("fields", {})
            loader = app_components.persona_loader
            allowed = loader.USER_FIELDS | loader.ADVANCED_FIELDS
            invalid = set(fields.keys()) - allowed
            if invalid:
                return web.json_response(
                    {"error": f"invalid fields: {invalid}"}, status=400
                )
            updated = loader.update(persona_id, **fields)
            return web.json_response({"ok": True, "persona": {"id": updated.id, "name": updated.name}})
        except Exception as e:
            logger.error(f"WebUI update_persona error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.get("/api/persona/tags")
    async def get_persona_tags(_request):
        """返回全部可选性格标签（建人时的"选项"）。

        数据源 config/persona_tags.json —— 与 CLI setup_wizard 共用同一份，
        标签会被翻译成 speaking_style / emotional_patterns / relationship_behavior
        等具体行为规则。
        """
        try:
            from core.persona.tags import tag_names

            return web.json_response({"tags": tag_names()})
        except Exception as e:
            logger.error(f"WebUI get_persona_tags error: {e}")
            return web.json_response({"tags": []})

    @routes.post("/api/persona")
    async def create_persona(request):
        """新建人设。

        body: {"id"?, "name", "description"?, "personality"?}

        - `id` 可省略：缺省时由 name 生成（中文取拼音不可靠，退化为
          "persona_" + 短哈希），避免让用户去想技术 ID
        - `personality` 是性格标签列表（见 GET /api/persona/tags），
          会被翻译成具体行为规则合入人设
        - `description` 可选，写入 background 字段
        """
        try:
            body = await request.json()
            persona_id = str(body.get("id") or "").strip()
            name = str(body.get("name") or "").strip()
            if not name:
                return web.json_response({"error": "name required"}, status=400)

            # id 缺省时自动生成（用户只该关心名字，不该去想技术 ID）
            generated = False
            if not persona_id:
                base = "".join(c for c in name.lower() if c.isalnum()) or "persona"
                if not base.isascii():
                    base = "persona"
                persona_id = f"{base}_{uuid.uuid4().hex[:6]}"
                generated = True

            loader = app_components.persona_loader
            if loader.get(persona_id):
                return web.json_response(
                    {"error": "persona id already exists"}, status=409
                )

            description = str(body.get("description") or "").strip()
            personality = body.get("personality") or []
            if not isinstance(personality, list):
                personality = [personality] if personality else []
            personality = [str(t).strip() for t in personality if str(t).strip()]

            persona = Persona(id=persona_id, name=name, personality=personality)
            if description:
                persona.background = description
            if personality:
                # 性格标签 → 具体行为规则（与 CLI setup_wizard 同一份翻译表）
                from core.persona.tags import apply_persona_tags

                merged = apply_persona_tags(persona.model_dump(), personality)
                persona = Persona(**merged)
            loader.add(persona)
            logger.info(f"WebUI persona created: {persona_id} (tags={personality})")
            return web.json_response(
                {
                    "ok": True,
                    "generated_id": generated,
                    "persona": {"id": persona.id, "name": persona.name},
                }
            )
        except Exception as e:
            logger.error(f"WebUI create_persona error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.delete("/api/persona/{persona_id}")
    async def delete_persona(request):
        """删除人设。不允许删除 DEFAULT_PERSONA_ID 或最后一个人设。
        T13: PersonaLoader.delete 自动清理 avatar 孤儿文件。
        """
        persona_id = request.match_info["persona_id"]
        loader = app_components.persona_loader
        if not loader.get(persona_id):
            return web.json_response({"error": "persona not found"}, status=404)
        if persona_id == DEFAULT_PERSONA_ID:
            return web.json_response(
                {"error": "不能删除默认人设"}, status=409
            )
        if len(loader.list_all()) <= 1:
            return web.json_response(
                {"error": "至少保留一个人设"}, status=409
            )
        assigned_accounts = [
            account["id"] for account in _get_wechat_accounts_config()
            if account.get("persona_id") == persona_id
        ]
        if assigned_accounts:
            return web.json_response(
                {"error": "这个角色仍被微信账号使用，请先为账号选择其他角色"},
                status=409,
            )
        store = getattr(app_components, "conversation_store", None)
        if store is not None and any(
            binding.persona_id == persona_id for binding in store.list()
        ):
            return web.json_response(
                {"error": "这个角色仍有对话记录，请先删除对应对话"},
                status=409,
            )
        deleted = loader.delete(persona_id)
        if not deleted:
            return web.json_response({"error": "delete failed"}, status=500)
        logger.info(f"WebUI persona deleted: {persona_id}")
        return web.json_response({"ok": True})

    # ────────── 人设头像 ──────────

    AVATAR_CONTENT_TYPE_EXT = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
    }
    AVATAR_MAX_SIZE = 2 * 1024 * 1024  # 2MB

    @routes.post("/api/persona/{persona_id}/avatar")
    async def upload_persona_avatar(request):
        """上传人设头像。multipart/form-data, field 'file', <2MB, png/jpg/webp。
        保存为 data/avatars/{persona_id}.{ext}，更新 personas.json 的 avatar 字段。
        """
        persona_id = request.match_info["persona_id"]
        loader = app_components.persona_loader
        if not loader.get(persona_id):
            return web.json_response({"error": "persona not found"}, status=404)

        reader = await request.multipart()
        file_part = None
        async for part in reader:
            if part.name == "file":
                file_part = part
                break
        if file_part is None:
            return web.json_response({"error": "no file field"}, status=400)

        content_type = file_part.headers.get("Content-Type", "")
        ext = AVATAR_CONTENT_TYPE_EXT.get(content_type)
        if ext is None:
            return web.json_response(
                {"error": f"unsupported content type: {content_type}"}, status=415
            )

        AVATAR_DIR.mkdir(parents=True, exist_ok=True)
        # 清理旧文件（扩展名变更时防止残留）
        for old in AVATAR_DIR.glob(f"{persona_id}.*"):
            old.unlink(missing_ok=True)

        avatar_path = AVATAR_DIR / f"{persona_id}.{ext}"
        size = 0
        too_large = False
        with open(avatar_path, "wb") as f:
            while True:
                chunk = await file_part.read_chunk()
                if not chunk:
                    break
                size += len(chunk)
                if size > AVATAR_MAX_SIZE:
                    too_large = True
                    break
                f.write(chunk)

        if too_large:
            avatar_path.unlink(missing_ok=True)
            return web.json_response(
                {"error": "file too large (max 2MB)"}, status=413
            )

        avatar_url = f"/avatars/{persona_id}.{ext}"
        loader.update(persona_id, avatar=avatar_url)
        logger.info(f"WebUI avatar uploaded for {persona_id}: {avatar_url}")
        return web.json_response({"ok": True, "avatar_url": avatar_url})

    @routes.delete("/api/persona/{persona_id}/avatar")
    async def delete_persona_avatar(request):
        """删除人设头像文件 + 清空 avatar 字段。
        persona 不存在 → 404；但仍执行孤儿文件清理。
        """
        persona_id = request.match_info["persona_id"]
        loader = app_components.persona_loader
        persona = loader.get(persona_id)

        # 孤儿清理：即使 persona 已删，也尝试删文件（双重保险，T13 也做）
        AVATAR_DIR.mkdir(parents=True, exist_ok=True)
        for old in AVATAR_DIR.glob(f"{persona_id}.*"):
            old.unlink(missing_ok=True)

        if not persona:
            return web.json_response({"error": "persona not found"}, status=404)

        loader.update(persona_id, avatar="")
        logger.info(f"WebUI avatar deleted for {persona_id}")
        return web.json_response({"ok": True})

    # ────────── 会话绑定 (Conversation Binding) ──────────

    @routes.get("/api/conversations")
    async def list_conversations(_request):
        """返回所有会话绑定，每条附带 persona name。"""
        try:
            store = app_components.conversation_store
            persona_loader = app_components.persona_loader
            bindings = store.list()
            result = []
            for b in bindings:
                d = b.to_dict()
                persona = persona_loader.get(b.persona_id) if persona_loader else None
                d["persona_name"] = getattr(persona, "name", "") if persona else ""
                result.append(d)
            return web.json_response(result)
        except Exception as e:
            logger.error(f"WebUI list_conversations error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.get("/api/conversations/{conversation_id}")
    async def get_conversation(request):
        """返回单个会话绑定详情。"""
        conversation_id = request.match_info["conversation_id"]
        try:
            store = app_components.conversation_store
            b = store.get(conversation_id)
            if not b:
                return web.json_response(
                    {"error": "conversation not found"}, status=404
                )
            d = b.to_dict()
            persona_loader = app_components.persona_loader
            persona = persona_loader.get(b.persona_id) if persona_loader else None
            d["persona_name"] = getattr(persona, "name", "") if persona else ""
            return web.json_response(d)
        except Exception as e:
            logger.error(f"WebUI get_conversation error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.post("/api/conversations")
    async def create_conversation(request):
        """创建会话绑定。body: {platform, account_id, contact_id, persona_id}。
        三元组重复 → 409。
        """
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON"}, status=400)

        platform = str(body.get("platform", "")).strip()
        account_id = str(body.get("account_id", "")).strip()
        contact_id = str(body.get("contact_id", "")).strip()
        persona_id = str(body.get("persona_id", "")).strip()
        if not (platform and persona_id):
            return web.json_response(
                {"error": "platform and persona_id are required"}, status=400
            )

        # Web conversations are persona-scoped, so exposing contact_id in the
        # UI adds no value. Keep the stored triple stable without user input.
        if platform == "web" and not contact_id:
            contact_id = persona_id
        elif not contact_id:
            return web.json_response(
                {"error": "contact_id is required for WeChat conversations"},
                status=400,
            )

        try:
            store = app_components.conversation_store
            binding = store.create(platform, account_id, contact_id, persona_id)
            return web.json_response(binding.to_dict())
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=409)
        except Exception as e:
            logger.error(f"WebUI create_conversation error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.patch("/api/conversations/{conversation_id}")
    async def update_conversation(request):
        """更新会话绑定。body: {persona_id?, title?}，至少传一个。不存在 → 404。

        - persona_id：切换人设（非空串才生效）
        - title：用户自定义备注名（可传空串清除，回退显示 persona name）
        """
        conversation_id = request.match_info["conversation_id"]
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON"}, status=400)

        persona_id = body.get("persona_id")
        title = body.get("title")

        # 至少一个可操作字段：persona_id 非空串，或 title 显式提供（含空串清除）
        if not persona_id and title is None:
            return web.json_response(
                {"error": "persona_id or title is required"}, status=400
            )

        try:
            store = app_components.conversation_store
            binding = None
            if persona_id:
                binding = store.update_persona(conversation_id, persona_id)
                if not binding:
                    return web.json_response(
                        {"error": "conversation not found"}, status=404
                    )
            if title is not None:
                binding = store.rename(conversation_id, title)
                if not binding:
                    return web.json_response(
                        {"error": "conversation not found"}, status=404
                    )
            return web.json_response(binding.to_dict())
        except Exception as e:
            logger.error(f"WebUI update_conversation error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.delete("/api/conversations/{conversation_id}")
    async def delete_conversation(request):
        """删除会话绑定。不存在 → 404。

        同时清空该对话关联的 chat_history（按 binding platform 推导 user_id，
        调 chat_history.delete_user）。chat_history 清理失败不阻塞删除，
        仅记 warning。
        """
        conversation_id = request.match_info["conversation_id"]
        try:
            store = app_components.conversation_store
            # 先拿 binding（需要 platform/account_id/contact_id/persona_id 推导 user_id）
            binding = store.get(conversation_id)
            if not binding:
                return web.json_response(
                    {"error": "conversation not found"}, status=404
                )
            ok = store.delete(conversation_id)
            if not ok:
                # 极少见：get 命中但 delete 失败（并发删除）
                return web.json_response(
                    {"error": "conversation not found"}, status=404
                )

            # 清 chat_history（按 binding 推导 user_id）
            chat_history = getattr(app_components, "chat_history", None)
            if chat_history is not None:
                try:
                    uid = _user_id_from_binding(binding)
                    scope_uid = _memory_scope_from_conversation(
                        conversation_id, app_components, uid, binding.persona_id,
                    )
                    chat_history.delete_user(scope_uid or uid)
                except Exception as e:
                    logger.warning(
                        f"WebUI: clean chat_history for conv {conversation_id} failed: {e}"
                    )
            return web.json_response({"ok": True})
        except Exception as e:
            logger.error(f"WebUI delete_conversation error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    # ────────── WeChat 账号管理 + SSE 二维码登录 (T8) ──────────

