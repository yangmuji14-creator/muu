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


def register(routes, app_components):
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
            sanitized = [
                {
                    "role": m.get("role"),
                    "content": m.get("content"),
                    "timestamp": m.get("timestamp"),
                    **({"sticker": m["sticker"]} if m.get("sticker") else {}),
                }
                for m in msgs
            ]
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

    @routes.post("/api/chat")
    async def chat(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON"}, status=400)

        content = (body.get("content") or "").strip()
        if not content:
            return web.json_response({"error": "content is required"}, status=400)
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

        reader = await request.multipart()
        image_path = None
        caption = ""
        conversation_id = ""
        user_id_override = ""
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        async for part in reader:
            if part.name == "image":
                content_type = (part.headers.get("Content-Type") or "").split(";", 1)[0].lower()
                if content_type not in ALLOWED_IMAGE_TYPES:
                    return web.json_response({"error": "unsupported image type"}, status=415)
                ext = Path(part.filename or "img.png").suffix or ".png"
                image_path = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
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

        try:
            vision_prompt = (
                "请客观描述这张图片的内容：画面里有什么、是什么场景、"
                "有什么值得注意的细节。只描述事实，不要加表情、语气和评价。"
            )
            if caption:
                vision_prompt += f"\n用户补充说明：{caption}\n请结合这句话理解图片并直接回复用户。"
            vision_result = await vision.process(str(image_path), vision_prompt)
            if vision.main_is_multimodal:
                reply = vision_result
                history = getattr(app_components, "chat_history", None)
                if history is not None:
                    user_content = "[用户发送了一张图片]" + (f" {caption}" if caption else "")
                    history.add_message(
                        history_user_id, "user", user_content, platform="web",
                        persona_id=persona_id,
                    )
                    history.add_message(
                        history_user_id, "assistant", reply, platform="web",
                        persona_id=persona_id,
                    )
            else:
                enhanced = vision.build_enhanced_message(vision_result, caption)
                reply, _ = await pipeline.process(
                    user_id, enhanced, persona_id,
                    **_scope_kwargs(pipeline, scope_id),
                )
            return web.json_response({"reply": reply})
        except Exception as e:
            logger.error(f"WebUI image error: {e}")
            return web.json_response({"error": str(e)}, status=500)
        finally:
            image_path.unlink(missing_ok=True)

    @routes.post("/api/upload/voice")
    async def upload_voice(request):
        """语音上传：若配置了 ASR 则转写为文本再走对话，否则优雅降级。"""
        pipeline = app_components.handler.pipeline
        reader = await request.multipart()
        audio_path = None
        conversation_id = ""
        user_id_override = ""
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        async for part in reader:
            if part.name == "audio":
                content_type = (part.headers.get("Content-Type") or "").split(";", 1)[0].lower()
                if content_type not in ALLOWED_AUDIO_TYPES:
                    return web.json_response({"error": "unsupported audio type"}, status=415)
                ext = Path(part.filename or "voice.webm").suffix or ".webm"
                audio_path = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
                size = 0
                with open(audio_path, "wb") as f:
                    while True:
                        chunk = await part.read_chunk()
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_AUDIO_UPLOAD_SIZE:
                            f.close()
                            audio_path.unlink(missing_ok=True)
                            return web.json_response({"error": "audio too large"}, status=413)
                        f.write(chunk)
            elif part.name == "conversation_id":
                conversation_id = (await part.text()).strip()
            elif part.name == "user_id":
                user_id_override = (await part.text()).strip()

        if audio_path is None:
            return web.json_response({"error": "no audio"}, status=400)

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

        # S8.3: faster-whisper load + transcribe are blocking — run them off
        # the event loop so chat/SSE/wechat stay responsive while ASR works.
        text = await asyncio.to_thread(_try_transcribe, audio_path)
        if not text:
            return web.json_response(
                {"error": "语音转写未配置", "need_asr": True}, status=400
            )
        try:
            reply, _ = await pipeline.process(
                user_id, text, persona_id,
                **_scope_kwargs(pipeline, scope_id),
            )
            return web.json_response({"transcript": text, "reply": reply})
        except Exception as e:
            logger.error(f"WebUI voice error: {e}")
            return web.json_response({"error": str(e)}, status=500)

