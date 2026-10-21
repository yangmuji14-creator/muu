"""对话与上传路由域（模块化拆分，行为等价搬移）。"""

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
from webui.routes.common import _scope_registry
from core.multimodal.vision import VisionManager


def _vision_failed(vision_result: str) -> bool:
    """视觉结果是否属于失败/未配置（不应喂给主模型，否则会诱发幻觉）。"""
    s = str(vision_result or "").strip()
    return (
        not s
        or s.startswith("[图片识别失败")
        or s.startswith("[图片识别未配置")
    )


def _message_blocks(m: dict) -> list[dict]:
    """把存储层消息组装为 PawzoChat 式 content blocks（API 输出层）。

    存储层保持「content 字符串 + image/sticker 附件字段」不变（零迁移），
    块化只发生在 API 输出：前端按 blocks 渲染，每类内容独立气泡。
    """
    blocks: list[dict] = []
    if m.get("image"):
        blocks.append({"type": "image", "url": m["image"]})
    st = m.get("sticker")
    if st:
        blocks.append({
            "type": "emoji",
            **{k: st[k] for k in ("pack", "emotion", "filename", "url") if st.get(k)},
        })
    text = str(m.get("content") or "")
    # 占位文本不进块：图片消息的 "[图片]"、表情消息的 "[表情]"、语音消息的 "[语音]"
    placeholder = (
        (m.get("image") and text.strip() == "[图片]")
        or (st and text.strip() in ("[表情]", ""))
        or (m.get("voice") and text.strip() == "[语音]")
    )
    if text.strip() and not placeholder:
        blocks.append({"type": "text", "text": text})
    if m.get("voice_url") or m.get("voice"):
        blocks.append({"type": "voice", "url": m.get("voice_url") or m.get("voice")})
    if not blocks and text:
        blocks.append({"type": "text", "text": text})
    return blocks


def register(routes, app_components):
    # ---- PawzoChat/微信式图片聚合（2026-10-17）----
    # 图片先到 → 立即上屏并开始后台视觉识别；文字后到 → /api/chat 认领合并；
    # 8 秒内没有文字 → 看门任务自动按"只发图"处理。
    pending_images = {}  # scope_id -> {url, desc_task, ts, user_id, persona_id, history_uid, scope_id}

    def _patch_desc_later(entry) -> None:
        """后台等描述完成并回填历史（直连路径用：回复不等描述）。"""
        history = getattr(app_components, "chat_history", None)
        if history is None or not hasattr(history, "update_image_desc"):
            return

        async def _patch():
            try:
                vision_result = await entry["desc_task"]
            except Exception as e:
                logger.error(f"Pending image vision task failed: {e}")
                return
            if _vision_failed(vision_result):
                return
            desc = VisionManager.single_line_description(vision_result)
            # 描述任务在上传时就开始跑，可能比 pipeline 落库更早完成 ——
            # 那一刻 update 找不到消息。短重试几次覆盖落库窗口，避免描述丢失
            # （丢了之后旧图在后续轮次里就只剩 [图片] 占位）。
            for delay in (0, 2.0, 5.0):
                if delay:
                    await asyncio.sleep(delay)
                try:
                    if history.update_image_desc(entry["history_uid"], entry["url"], desc):
                        return
                except Exception as e:
                    logger.error(f"Patch image_desc failed: {e}")
                    return
            logger.warning(
                f"image_desc patch missed after retries: {entry['url']}"
            )

        asyncio.create_task(_patch())

    async def _consume_pending_image(entry, text: str = "") -> None:
        """处理一张待聚合图片（看门兜底/多图强制消费）。

        多模态主模型：图片本体进主调用，不等描述；否则等描述再注入 prompt。
        ⚠️ 所有都会话状态写入必须经 per-scope 锁（ScopeExecutionRegistry），
        与 /api/chat 同一把锁 —— 否则看门任务在用户正在生成回复时触发，
        同一会话两轮 pipeline 并发跑，历史/记忆都会打架。
        """
        vision = getattr(app_components, "vision_manager", None)
        history = getattr(app_components, "chat_history", None)
        url = entry["url"]
        persona_id = entry["persona_id"]
        scope_key = entry.get("scope_id") or ""
        pipeline = app_components.handler.pipeline
        try:
            parameters = inspect.signature(pipeline.process).parameters
        except (TypeError, ValueError):
            parameters = {}
        kwargs = {}
        if scope_key and "scope_id" in parameters:
            kwargs["scope_id"] = scope_key

        async def _run_locked(fn):
            """在会话锁内执行一段写入（空 scope 直接执行）。"""
            return await _scope_registry(app_components).submit(
                scope_key, uuid.uuid4().hex, fn, dedup=False,
            )

        # ---- 原生直连（PawzoChat 式）：语言模型勾了「多模态」→ 图片本体
        # 直接进主调用，回复不等描述；描述后台补写历史供之后轮次使用。
        if vision is not None and vision.main_is_multimodal:
            _patch_desc_later(entry)
            kwargs_native = dict(kwargs)
            if "image" in parameters:
                kwargs_native["image"] = url
            if "image_path" in parameters:
                kwargs_native["image_path"] = entry.get("path")
            if "attach_image" in parameters:
                kwargs_native["attach_image"] = True

            async def _run_native():
                await pipeline.process(
                    entry["user_id"], text or "[图片]", persona_id,
                    **kwargs_native,
                )

            try:
                await _run_locked(_run_native)
            except Exception as e:
                logger.error(f"Pending image process failed: {e}")
            return

        try:
            vision_result = await entry["desc_task"]
        except Exception as e:
            logger.error(f"Pending image vision task failed: {e}")
            vision_result = ""
        failed = _vision_failed(vision_result)

        async def _run_fallback():
            if failed:
                # 视觉失败：把失败说明作为回复落库，绝不能拿空/错误描述喂主模型
                if history is not None:
                    history.add_message(
                        entry["history_uid"], "user", text or "[图片]",
                        platform="web", persona_id=persona_id, image=url,
                    )
                    history.add_message(
                        entry["history_uid"], "assistant",
                        "图片识别失败了，稍后再发一次试试~",
                        platform="web", persona_id=persona_id,
                    )
                return
            desc = VisionManager.single_line_description(vision_result)
            await pipeline.process(
                entry["user_id"], text or "[图片]", persona_id,
                image=url, image_desc=desc, **kwargs,
            )

        try:
            await _run_locked(_run_fallback)
        except Exception as e:
            logger.error(f"Pending image process failed: {e}")

    @routes.get("/api/history")
    async def get_history(request):
        """返回当前用户的消息历史（脱敏，不含 emotion 内部元数据）。"""
        try:
            try:
                user_id, _conv, _pid = _resolve_scoped_user_id(
                    request.query.get("conversation_id"), app_components,
                    # legacy (no-conversation) web refresh reads the same
                    # persona scope that legacy chat writes to, not WEB_USER_ID.
                    fallback_persona_id=(
                        request.query.get("persona_id") or DEFAULT_PERSONA_ID
                    ),
                )
            except _ConversationNotFound as e:
                return web.json_response(
                    {"error": f"conversation not found: {e}"}, status=404
                )
            # S6.1: identity is authoritative — reject a query user_id mismatch.
            forged = _guard_client_identity(
                request.query.get("user_id"), user_id, where="/api/history",
            )
            if forged is not None:
                return forged
            msgs = app_components.chat_history.get_messages(user_id)
            sanitized = []
            for m in msgs:
                item = {
                    "role": m.get("role"),
                    "content": m.get("content"),
                    "timestamp": m.get("timestamp"),
                    "blocks": _message_blocks(m),
                    **({"sticker": m["sticker"]} if m.get("sticker") else {}),
                    **({"image": m["image"]} if m.get("image") else {}),
                    **({"voice": m["voice"]} if m.get("voice") else {}),
                    **({"platform": m["platform"]} if m.get("platform") else {}),
                }
                sanitized.append(item)
            return web.json_response({"messages": sanitized})
        except Exception as e:
            logger.error(f"WebUI get_history error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.delete("/api/history/last")
    async def delete_last_message_pair(request):
        """删除最后一对消息（user+assistant），用于前端"重新生成"场景。"""
        try:
            conversation_id = request.query.get("conversation_id")
            resolved_user, _conv, _pid = _resolve_user_id_from_conversation(
                conversation_id, app_components,
                # legacy (no-conversation) regen operates on the same persona
                # scope that legacy chat writes to, not WEB_USER_ID.
                fallback_persona_id=(
                    request.query.get("persona_id") or DEFAULT_PERSONA_ID
                ),
            )
            scope_id = _memory_scope_from_conversation(
                _conv, app_components, resolved_user, _pid,
            )
            user_id = scope_id or resolved_user
            # S6.1: identity is authoritative — reject a query user_id mismatch.
            forged = _guard_client_identity(
                request.query.get("user_id"), user_id, where="/api/history/last",
            )
            if forged is not None:
                return forged
            # S6.2: /regen must take the same scope lock as a normal message so
            # it can never interleave with an in-flight generation.
            registry = _scope_registry(app_components)
            async with registry.run_exclusive(scope_id):
                app_components.chat_history.delete_last_messages(user_id)
                remaining = app_components.chat_history.get_messages(user_id)
            return web.json_response({"ok": True, "remaining": len(remaining)})
        except Exception as e:
            logger.error(f"WebUI delete_last error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.get("/api/events")
    async def sse_events(request):
        """SSE 实时事件流：订阅当前 scope 的 history_changed 事件。

        前端 EventSource 收到后立即刷新聊天列表（替代固定 5s 轮询的主通道，
        轮询保留作兜底）。15s 心跳防代理断连。
        """
        try:
            user_id, _conv, _pid = _resolve_scoped_user_id(
                request.query.get("conversation_id"), app_components,
                fallback_persona_id=(
                    request.query.get("persona_id") or DEFAULT_PERSONA_ID
                ),
            )
        except _ConversationNotFound as e:
            return web.json_response(
                {"error": f"conversation not found: {e}"}, status=404
            )
        # ⚠️ 订阅 key 必须与消息落库的作用域一致：_resolve_scoped_user_id 返回的
        # user_id 本身就是记忆作用域（scope_<sha>，与 /api/history 同一键空间）。
        # 不要再用 _memory_scope_from_conversation 重算——那会得到另一个 key，
        # 导致永远收不到 pipeline 发布的事件（2026-10-18 实测踩坑）。
        scope_id = user_id

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream; charset=utf-8",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(request)
        from core.runtime import event_bus
        queue = event_bus.subscribe(scope_id)
        logger.info(f"SSE subscribed: scope={scope_id!r} user={user_id!r}")
        try:
            await response.write(
                f"data: {json.dumps({'type': 'connected'})}\n\n".encode("utf-8")
            )
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                    await response.write(
                        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
                    )
                except asyncio.TimeoutError:
                    # 心跳：保持连接、探测断连
                    await response.write(b": ping\n\n")
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        except Exception as e:
            logger.debug(f"SSE stream ended: {e}")
        finally:
            event_bus.unsubscribe(scope_id, queue)
            try:
                await response.write_eof()
            except Exception:
                pass
        return response

    @routes.post("/api/chat")
    async def chat(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON"}, status=400)

        content = (body.get("content") or "").strip()
        if not content:
            return web.json_response({"error": "content is required"}, status=400)
        # 顺序指纹：多行（前端去抖合并）时记录收到的行序，用于定位「分段连发乱序」
        # 是前端合并就乱还是后端落库乱。每行只取前 6 字符，避免日志泄全文。
        _mlines = [ln.strip() for ln in content.split("\n") if ln.strip()]
        if len(_mlines) > 1:
            logger.info(
                "WebUI chat multi-line fingerprint: {} 行 | {}",
                len(_mlines), " | ".join(ln[:6] for ln in _mlines),
            )
        body_persona_id = body.get("persona_id") or DEFAULT_PERSONA_ID
        # T9: 优先用 conversation_id 解析 user_id；缺省走 build_web_uid(persona_id)
        try:
            user_id, _conv, binding_persona_id = _resolve_user_id_from_conversation(
                body.get("conversation_id"), app_components,
                fallback_persona_id=body_persona_id,
            )
        except _ConversationNotFound as e:
            return web.json_response(
                {"error": f"conversation not found: {e}"}, status=404
            )
        # conversation_id 命中时优先用 binding 的 persona_id（保证与该会话绑定一致）；
        # 否则用 body 里的 persona_id
        persona_id = binding_persona_id or body_persona_id
        scope_id = _memory_scope_from_conversation(
            _conv, app_components, user_id, persona_id,
        )
        # S6.1: identity is authoritative. A browser-supplied user_id may not
        # override the conversation-bound identity; reject any mismatch.
        forged = _guard_client_identity(body.get("user_id"), user_id, where="/api/chat")
        if forged is not None:
            return forged
        sticker_meta = None
        raw_sticker = body.get("sticker")
        if isinstance(raw_sticker, dict):
            try:
                sticker_service.resolve(
                    str(raw_sticker.get("pack", "")),
                    str(raw_sticker.get("emotion", "")),
                    str(raw_sticker.get("filename", "")),
                )
                sticker_meta = {
                    "pack": str(raw_sticker.get("pack")),
                    "emotion": str(raw_sticker.get("emotion")),
                    "filename": str(raw_sticker.get("filename")),
                    "url": (
                        f"/api/stickers/file/{raw_sticker.get('pack')}/"
                        f"{raw_sticker.get('emotion')}/{raw_sticker.get('filename')}"
                    ),
                }
            except (ValueError, FileNotFoundError):
                return web.json_response({"error": "invalid sticker"}, status=400)

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream; charset=utf-8",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(request)

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def on_token(token: str):
            loop.call_soon_threadsafe(queue.put_nowait, ("token", {"token": token}))

        def on_event(event: str, data: dict):
            # Event payloads are deliberately small and never contain raw tool
            # output; this keeps the activity panel useful without leaking
            # connector data into the browser.
            loop.call_soon_threadsafe(queue.put_nowait, (event, data))

        pipeline = app_components.handler.pipeline
        registry = _scope_registry(app_components)
        # S6.3: request_id enables idempotent retries: re-submitting the same
        # scope + request_id returns the recorded result without re-calling the
        # model. Honours the X-Request-ID header or a body request_id.
        request_id = str(
            body.get("request_id") or request.headers.get("X-Request-ID") or ""
        ).strip()
        dedup = bool(request_id)

        async def _generate():
            # Streaming callbacks are set up lazily so a deduplicated request
            # (which returns a recorded result) never re-streams or re-runs.
            kwargs = {"on_token": on_token}
            try:
                parameters = inspect.signature(pipeline.process).parameters
            except (TypeError, ValueError):
                parameters = {}
            if "on_event" in parameters:
                kwargs["on_event"] = on_event
            if "sticker" in parameters:
                kwargs["sticker"] = sticker_meta
            if scope_id and "scope_id" in parameters:
                kwargs["scope_id"] = scope_id
            # 图片聚合：本 scope 有未处理的上传图片 → 认领，图+文一轮处理。
            entry = pending_images.pop(scope_id, None)
            if entry is not None:
                vision = getattr(app_components, "vision_manager", None)
                if vision is not None and vision.main_is_multimodal:
                    # ---- 原生直连：图片本体进主调用，回复不等描述 ----
                    # 描述任务后台继续跑，完成后回填历史（update_image_desc）。
                    _patch_desc_later(entry)
                    if "image" in parameters:
                        kwargs["image"] = entry["url"]
                    if "image_path" in parameters:
                        kwargs["image_path"] = entry.get("path")
                    if "attach_image" in parameters:
                        kwargs["attach_image"] = True
                    logger.info("WebUI chat aggregated pending image (native vision)")
                else:
                    # ---- 备用路线：等描述 → 描述注入 prompt ----
                    # 视觉任务在上传时就已开跑，此处最多等它完成。
                    try:
                        vision_result = await entry["desc_task"]
                    except Exception as e:
                        logger.error(f"Pending image vision failed: {e}")
                        vision_result = ""
                    if _vision_failed(vision_result):
                        # 视觉失败：附一句说明，别让主模型对着空描述编内容
                        if "image_desc" in parameters:
                            kwargs["image_desc"] = "（图片识别失败，暂时无法看到这张图片的内容）"
                        if "image" in parameters:
                            kwargs["image"] = entry["url"]
                    else:
                        if "image" in parameters:
                            kwargs["image"] = entry["url"]
                        if "image_desc" in parameters:
                            kwargs["image_desc"] = VisionManager.single_line_description(
                                vision_result
                            )
                    logger.info("WebUI chat aggregated pending image for scope")
            # The pipeline already returns friendly user-facing error strings
            # internally; unexpected exceptions propagate to the SSE loop's
            # error handler below.
            # §8.4: bind the request_id so every LLM log line is traceable
            # (desensitized; never logs keys or full prompts).
            _llm_req_token = set_llm_request_id(request_id)
            try:
                return await pipeline.process(
                    user_id, content, persona_id, **kwargs,
                )
            finally:
                reset_llm_request_id(_llm_req_token)

        async def _run():
            try:
                # S6.2/S6.3: submit() takes the per-scope lock (one scope runs
                # one generation at a time; different scopes run concurrently)
                # and dedups repeated (scope, request_id) so a retry never
                # re-invokes the model. A cancellation while waiting leaves the
                # lock cleanly and a disconnected client never blocks forever.
                return await registry.submit(
                    scope_id, request_id or uuid.uuid4().hex,
                    _generate, dedup=dedup and bool(scope_id),
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        task = asyncio.create_task(_run())

        async def _send(event: str, data: dict):
            payload = json.dumps(data, ensure_ascii=False)
            await response.write(
                f"event: {event}\ndata: {payload}\n\n".encode("utf-8")
            )

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event, data = item
                await _send(event, data)
            reply, level = await task
            # TTS 语音回复：若回复带 [语音]/[voice] 标记且配置了语音服务商，
            # 则异步合成语音并附带 voice_url；失败/未配置时仅发纯文字（标记已剥离）。
            display_reply, want_voice = parse_voice_markers(reply)
            voice_url = None
            if want_voice and display_reply:
                try:
                    voice_url = await _synthesize_for_chat(persona_id, display_reply)
                except Exception as e:
                    logger.warning(f"chat TTS hook failed: {e}")
            await _send("done", {
                "reply": display_reply,
                "level": level,
                "voice_url": voice_url,
            })
        except Exception as e:
            logger.error(f"WebUI chat error: {e}")
            try:
                await _send("error", {"error": "暂时无法生成回复，请稍后重试"})
            except Exception:
                pass
        finally:
            if not task.done():
                task.cancel()
            try:
                await response.write_eof()
            except Exception:
                pass
        return response

    @routes.post("/api/upload/image")
    async def upload_image(request):
        vision = getattr(app_components, "vision_manager", None)
        pipeline = app_components.handler.pipeline
        # 图片存到 attachments/web（静态可访问），历史消息带 /attachments URL；
        # 2026-10-17 之前是存 uploads 且识别完即删，导致 Web 端永远看不到图。
        ATTACH_WEB_DIR = DATA_DIR / "attachments" / "web"

        reader = await request.multipart()
        image_path = None
        caption = ""
        conversation_id = ""
        user_id_override = ""
        ATTACH_WEB_DIR.mkdir(parents=True, exist_ok=True)

        async for part in reader:
            if part.name == "image":
                content_type = (part.headers.get("Content-Type") or "").split(";", 1)[0].lower()
                if content_type not in ALLOWED_IMAGE_TYPES:
                    return web.json_response({"error": "unsupported image type"}, status=415)
                ext = Path(part.filename or "img.png").suffix or ".png"
                image_path = ATTACH_WEB_DIR / f"{uuid.uuid4().hex}{ext}"
                size = 0
                with open(image_path, "wb") as f:
                    while True:
                        chunk = await part.read_chunk()
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_IMAGE_UPLOAD_SIZE:
                            f.close()
                            image_path.unlink(missing_ok=True)
                            return web.json_response({"error": "image too large"}, status=413)
                        f.write(chunk)
            elif part.name == "caption":
                caption = (await part.text()).strip()
            elif part.name == "conversation_id":
                conversation_id = (await part.text()).strip()
            elif part.name == "user_id":
                user_id_override = (await part.text()).strip()

        if image_path is None:
            return web.json_response({"error": "no image"}, status=400)

        if vision is None:
            return web.json_response(
                {"error": "视觉识别未配置"}, status=400
            )

        try:
            resolved_user_id, _conv, bound_persona_id = _resolve_user_id_from_conversation(
                conversation_id, app_components,
            )
        except _ConversationNotFound as e:
            return web.json_response(
                {"error": f"conversation not found: {e}"}, status=404
            )
        # S6.1: identity is authoritative — a client-form user_id may not override
        # the conversation-bound identity; reject any mismatch.
        forged = _guard_client_identity(user_id_override, resolved_user_id, where="/api/upload")
        if forged is not None:
            return forged
        user_id = resolved_user_id
        persona_id = bound_persona_id or DEFAULT_PERSONA_ID
        scope_id = _memory_scope_from_conversation(
            _conv, app_components, resolved_user_id, persona_id,
        )
        history_user_id = scope_id or user_id
        image_url = f"/attachments/web/{image_path.name}"

        # ---- PawzoChat/微信式流程：立即返回，后台识别 ----
        # 1) 立刻启动视觉识别（用户打字期间并行跑）
        vision_prompt = (
            "请客观描述这张图片的内容：画面里有什么、是什么场景、"
            "有什么值得注意的细节。只描述事实，不要加表情、语气和评价。"
        )
        desc_task = asyncio.create_task(
            vision.process(str(image_path), vision_prompt)
        )
        entry = {
            "url": image_url,
            "path": str(image_path),
            "desc_task": desc_task,
            "ts": asyncio.get_event_loop().time(),
            "user_id": user_id,
            "persona_id": persona_id,
            "history_uid": history_user_id,
            "scope_id": scope_id,
        }
        # 2) 同 scope 已有未聚合图片 → 立即按"只发图"处理旧的（多图连发各回各的）
        old = pending_images.pop(scope_id, None)
        if old is not None:
            asyncio.create_task(_consume_pending_image(old, text=""))
        pending_images[scope_id] = entry

        # 3) 看门任务：去抖窗口内没有文字来认领 → 自动按"只发图"处理。
        #    窗口与前端去抖对齐（max(8, 去抖延迟+3)）：前端图片已加入去抖
        #    序列，文字可能把窗口推得比 8 秒更久，看门不能抢先。
        _deb = float(
            (getattr(app_components, "advanced_config", {}) or {}).get("debounce_seconds", 3) or 3
        )
        _watchdog_delay = max(8.0, _deb + 3.0)

        async def _watchdog():
            await asyncio.sleep(_watchdog_delay)
            if pending_images.get(scope_id) is entry:
                pending_images.pop(scope_id, None)
                await _consume_pending_image(entry, text="")

        asyncio.create_task(_watchdog())
        logger.info(
            f"WebUI image accepted: {image_url} (watchdog {_watchdog_delay:.0f}s)"
        )
        return web.json_response({"ok": True, "image_url": image_url})

