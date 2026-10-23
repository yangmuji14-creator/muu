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
        """返回人设列表。

        除 id/name/avatar 外附带几条**只读摘要**（age/gender/occupation/
        personality/relationship_level/background），供通讯录名单渲染副标题。
        这些字段本来就在 USER_FIELDS 里、`/api/persona/{id}` 也会全量返回，
        这里只是提前给列表用，不引入新的敏感数据。

        为什么加：名单页原来每行只有一个名字，两个人设的通讯录看起来像
        一张空表 —— 有摘要才能在这一行里把「她是谁」说清楚，也才有信息
        判断该点哪一条。
        """
        try:
            personas = app_components.persona_loader.list_all()
            items = []
            for p in personas:
                summary = ""
                bg = (getattr(p, "background", "") or "").strip()
                if bg:
                    summary = bg.splitlines()[0][:60]
                items.append({
                    "id": p.id,
                    "name": p.name,
                    "avatar": getattr(p, "avatar", "") or "",
                    "age": getattr(p, "age", None),
                    "gender": getattr(p, "gender", "") or "",
                    "occupation": getattr(p, "occupation", "") or "",
                    "personality": list(getattr(p, "personality", []) or []),
                    "relationship_level": getattr(p, "relationship_level", None),
                    "summary": summary,
                })
            return web.json_response(items)
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
        """返回性格标签选择器所需的全部元数据。

        数据源 config/persona_tags.json —— 与 CLI setup_wizard 共用同一份。

        返回：
          tags          标签名列表（保持文件顺序，前端 chip 的排列顺序）
          specs         每个标签的三句草稿 + 硬规则，供「点选 → 预览」用
          max_tags      多选上限（后端与前端读同一个数字，不各写一份）
          mutex_groups  互斥对，前端据此自动取消勾选
          version       schema 版本；1 表示标签只有字段没有草稿，前端应隐藏预览区

        为什么一次给全：标签选择器需要「名字 + 说明 + 上限 + 互斥」四样东西
        才能把「点一下就知道会发生什么」做出来。分成四个接口只会让前端在
        打开弹窗时打四次请求，且中途失败会留下半截状态。
        """
        try:
            from core.persona.tags import (
                is_v2,
                max_tags,
                mutex_groups,
                tag_names,
                tag_specs,
            )

            return web.json_response(
                {
                    "version": 2 if is_v2() else 1,
                    "tags": tag_names(),
                    "specs": tag_specs(),
                    "max_tags": max_tags(),
                    "mutex_groups": mutex_groups(),
                }
            )
        except Exception as e:
            logger.error(f"WebUI get_persona_tags error: {e}")
            return web.json_response(
                {"version": 1, "tags": [], "specs": [], "max_tags": 3, "mutex_groups": []}
            )

    @routes.post("/api/persona/tags/preview")
    async def preview_persona_tags(request):
        """把选中的标签翻译成三组可编辑草稿，**不落库**。

        body: {"tags": ["温柔", "细心"]}

        返回 speaking / emotion / relationship 三段完整的中文句子，加
        hard_rules、命中的互斥组 conflicts、不认识的标签 unknown、超上限
        被截掉的 truncated。

        交互契约：前端拿这三段填进 textarea，用户可以改；提交建人时把改过的
        文本随 body 一起发回来，由 `drafts` 字段直接写入，**不再走标签翻译**。
        这样「标签」只是降低填写门槛的草稿生成器，最终落库的永远是用户看见
        并确认过的那句话。
        """
        try:
            from core.persona.tags import preview_persona_tags

            body = await request.json()
            tags = body.get("tags") or []
            if not isinstance(tags, list):
                tags = [tags]
            tags = [str(t).strip() for t in tags if str(t).strip()]
            return web.json_response(preview_persona_tags(tags))
        except Exception as e:
            logger.error(f"WebUI preview_persona_tags error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.post("/api/persona")
    async def create_persona(request):
        """新建人设。

        body: {"id"?, "name", "description"?, "personality"?, "drafts"?}

        - `id` 可省略：缺省时由 name 生成（中文取拼音不可靠，退化为
          "persona_" + 短哈希），避免让用户去想技术 ID
        - `personality` 是性格标签列表（见 GET /api/persona/tags），
          会被翻译成具体行为规则合入人设
        - `drafts` 可选，{"speaking"?, "emotion"?, "relationship"?} ——
          用户在「点选标签 → 预览草稿」之后**改过的那三段文本**。带了这个
          就直接写，不再用标签重新翻译一遍：用户改过的东西不能被标签覆盖。
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
                # 纯数字/纯中文的 name 会退化成 "1_988fe8" 这种没意义的前缀，
                # 也会让磁盘文件名难以辨认。以字母开头才用作前缀。
                if not (base.isascii() and base[0].isalpha()):
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

            drafts = body.get("drafts")
            if not isinstance(drafts, dict):
                drafts = {}

            persona = Persona(id=persona_id, name=name, personality=personality)
            if description:
                persona.background = description
            if personality or drafts:
                # 性格标签 → 具体行为规则（与 CLI setup_wizard 同一份翻译表）
                from core.persona.tags import apply_drafts, apply_persona_tags

                merged = apply_persona_tags(persona.model_dump(), personality)
                # 用户改过的草稿优先：在标签翻译**之后**再覆盖一次。
                # 顺序不能反 —— 反了就等于「标签覆盖用户」，那预览就没有意义了。
                apply_drafts(merged, drafts)
                persona = Persona(**merged)
            loader.add(persona)
            logger.info(
                f"WebUI persona created: {persona_id} "
                f"(tags={personality}, drafts={sorted(drafts)})"
            )
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

