"""WebUI 服务器：HTTP 应用组装与启动。

模块化改造中：常量与模块级辅助已迁至 webui/routes/common.py，
路由域将逐步拆到 webui/routes/*.py（每域一个 register(routes, app_components)）。
"""

# noqa: 拆分过渡期，_make_app/run_web 直接引用公共层的大量名字
from webui.routes.common import *  # noqa: F401,F403
from webui.routes.common import __all__ as _COMMON_ALL  # noqa: F401

# 拆分过渡期：_make_app/run_web 体内直接用到这些模块，import * 不会转发 import 本身
import asyncio  # noqa: F401
import io  # noqa: F401
import inspect  # noqa: F401
import hmac
import ipaddress
import json  # noqa: F401
import os  # noqa: F401
import re  # noqa: F401
import tempfile  # noqa: F401
import threading  # noqa: F401
import uuid  # noqa: F401
from pathlib import Path  # noqa: F401
from loguru import logger  # noqa: F401


def _web_auth_config(host: str) -> tuple[str, str] | None:
    """Require credentials whenever the server binds beyond loopback."""
    normalized_host = host.strip("[]").lower()
    try:
        is_loopback = ipaddress.ip_address(normalized_host).is_loopback
    except ValueError:
        is_loopback = normalized_host == "localhost"
    if is_loopback:
        return None

    username = os.getenv("MU_WEB_AUTH_USER", "")
    password = os.getenv("MU_WEB_AUTH_PASSWORD", "")
    if not username or not password:
        raise RuntimeError(
            "WebUI non-loopback binding requires MU_WEB_AUTH_USER and "
            "MU_WEB_AUTH_PASSWORD"
        )
    if len(password) < 16:
        raise RuntimeError(
            "MU_WEB_AUTH_PASSWORD must contain at least 16 characters "
            "for non-loopback WebUI binding"
        )
    return username, password


def _web_auth_middleware(host: str):
    credentials = _web_auth_config(host)
    if credentials is None:
        return None

    from aiohttp import BasicAuth, web

    @web.middleware
    async def auth_middleware(request, handler):
        try:
            supplied = BasicAuth.decode(
                request.headers.get("Authorization", ""), encoding="utf-8"
            )
        except (ValueError, UnicodeDecodeError):
            supplied = None
        valid = supplied is not None and hmac.compare_digest(
            supplied.login.encode("utf-8"), credentials[0].encode("utf-8")
        ) and hmac.compare_digest(
            supplied.password.encode("utf-8"), credentials[1].encode("utf-8")
        )
        if not valid:
            return web.Response(
                status=401,
                text="Authentication required",
                headers={
                    "WWW-Authenticate": 'Basic realm="Cyber Companion", charset="UTF-8"'
                },
            )
        return await handler(request)

    return auth_middleware


def _make_app(app_components, host: str | None = None):
    from aiohttp import web

    try:
        _migrate_existing_secrets()
    except Exception as exc:
        # A secure-store failure must never prevent the application from using
        # its existing environment variable or legacy plaintext credential.
        logger.warning("Secret migration skipped: {}", exc)

    routes = web.RouteTableDef()
    sticker_service = getattr(app_components, "sticker_service", None)
    if sticker_service is None:
        sticker_service = StickerService(
            DATA_DIR, STATIC_DIR / "stickers" / "pawzochat-default",
        )
        app_components.sticker_service = sticker_service
    try:
        app_components.handler.pipeline._sticker_service = sticker_service
    except AttributeError:
        pass

    from webui.routes.system import register as _register_system
    _register_system(routes, app_components)
    from webui.routes.model import register as _register_model
    _register_model(routes, app_components)
    from webui.routes.memory import register as _register_memory
    _register_memory(routes, app_components)
    from webui.routes.chat import register as _register_chat
    _register_chat(routes, app_components)
    from webui.routes.persona import register as _register_persona
    _register_persona(routes, app_components)
    from webui.routes.wechat import register as _register_wechat
    _register_wechat(routes, app_components)

# ---- 应用组装（原 _make_app 尾部）----
    @web.middleware
    async def friendly_error_middleware(request, handler):
        """Keep technical exception details in logs and out of user responses."""
        try:
            response = await handler(request)
        except web.HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Unhandled WebUI error on {request.method} {request.path}: {e}")
            return web.json_response(
                {"error": "服务暂时无法完成操作，请稍后重试"}, status=500,
            )
        if response.status >= 500 and response.content_type == "application/json":
            message = "功能暂时不可用，请稍后重试" if response.status == 503 else "服务暂时无法完成操作，请稍后重试"
            return web.json_response({"error": message}, status=response.status)
        return response

    host = host or os.getenv("MU_WEB_HOST") or os.getenv("CC_WEB_HOST", "127.0.0.1")
    auth_middleware = _web_auth_middleware(host)
    middlewares = [friendly_error_middleware]
    if auth_middleware is not None:
        middlewares.append(auth_middleware)

    aio_app = web.Application(
        client_max_size=512 * 1024 * 1024,
        middlewares=middlewares,
    )
    aio_app.add_routes(routes)
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    aio_app.router.add_static("/avatars", AVATAR_DIR, name="avatars")
    # 聊天图片附件（web 上传 / 微信接收）：历史消息的 image 字段指向这里
    ATTACHMENTS_DIR = DATA_DIR / "attachments"
    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    aio_app.router.add_static("/attachments", ATTACHMENTS_DIR, name="attachments")
    if STATIC_DIR.exists():
        aio_app.router.add_static("/static/", STATIC_DIR, name="static")

    # T13: best-effort legacy web_user.json → web:default binding migration.
    # 失败不阻塞 server 启动（log warning + 继续）。
    try:
        migrate_legacy_web_user(
            getattr(app_components, "conversation_store", None), DATA_DIR
        )
    except Exception as e:
        logger.warning(f"T13 legacy migration failed: {e}")

    return aio_app
async def run_web(app_components, host: str = "127.0.0.1", port: int = 8000) -> None:
    """启动网页服务（阻塞直到取消）。"""
    from aiohttp import web

    _web_auth_config(host)

    # 打包模式(EXE)首次启动时自动写入内置 MCP 服务器, 保证开箱即用
    _seed_default_mcp_config()

    # 确保 adapter_manager 存在（Web 模式不经过 run_with_adapters，需在此注入）
    if getattr(app_components, "adapter_manager", None) is None:
        from adapters import AdapterManager
        app_components.adapter_manager = AdapterManager()

    # 注入消息处理回调（Web 模式不经过 run_with_adapters，需在此注入）
    # 否则 adapter._handler 为 None，_on_inbound_message 会静默丢弃所有消息。
    # 依赖：pipeline（app.handler.pipeline）+ DebounceManager + make_message_handler
    adapter_manager = app_components.adapter_manager
    if not getattr(adapter_manager, "_message_handler", None):
        try:
            from adapters.debounce import DebounceManager
            from core.app import make_message_handler
            pipeline = app_components.handler.pipeline
            debounce_seconds = app_components.advanced_config.get("debounce_seconds", 3)
            debounce = DebounceManager(debounce_seconds, pipeline, app_components, adapter_manager)
            # 挂到组件上，供 _apply_live 热更新 debounce_seconds（review P2-10）
            app_components.debounce_manager = debounce
            handler = make_message_handler(app_components, pipeline, debounce)
            adapter_manager.set_message_handler(handler)
            logger.info("WebUI: injected message handler + DebounceManager for adapters")
        except Exception as e:
            logger.warning(f"WebUI: inject message handler failed: {e}")

    aio_app = _make_app(app_components, host=host)
    runner = web.AppRunner(aio_app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    # 连接 MCP 工具（可选）
    mcp = getattr(app_components, "mcp_manager", None)
    if mcp is not None:
        try:
            connected = await mcp.load_and_connect(CONFIG_DIR)
            if connected:
                logger.info(f"WebUI: MCP {connected} server(s) connected")
        except Exception as e:
            logger.warning(f"WebUI: MCP connect failed: {e}")

    # 自动启动已配置且已有凭证的微信账号（auto_start=True）
    # 失败不阻塞 server 启动（best-effort，单账号失败只 log warning）
    try:
        await _autostart_wechat_adapters(app_components)
    except Exception as e:
        logger.warning(f"WebUI: wechat autostart failed: {e}")

    # 朋友圈自动发布器（AI 自动发朋友圈）：按配置定时为指定人设发布动态。
    # 独立后台任务，失败不阻塞 server 启动。配置存 settings.json。
    try:
        if getattr(app_components, "moments_poster", None) is None:
            def _moment_saver(moment: dict) -> dict:
                now = _moment_now_iso()
                record = {
                    "id": _new_moment_id(),
                    "author": moment.get("author", "") or "user",
                    "timestamp": now,
                    "text": (moment.get("text") or "").strip(),
                    "likes": [],
                    "replies": [],
                    "auto": bool(moment.get("auto")),
                }
                moments = _load_moments()
                moments.insert(0, record)
                _save_moments(moments)
                return record

            def _moment_poster_persona_name(persona_id: str) -> str:
                loader = getattr(app_components, "persona_loader", None)
                if loader is None:
                    return ""
                try:
                    p = loader.get(persona_id)
                    return getattr(p, "name", "") or ""
                except Exception:
                    return ""

            _llm = getattr(getattr(app_components, "registry", None), "get", lambda: None)()
            poster_gen = None
            if _llm is not None and hasattr(_llm, "chat"):
                async def _gen(system_prompt: str, user_prompt: str,
                               max_tokens: int = 400, temperature: float = 0.95) -> str:
                    resp = await _llm.chat(
                        messages=[{"role": "user", "content": user_prompt}],
                        system_prompt=system_prompt,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    )
                    return getattr(resp, "content", "") or ""
                # 必须把回调挂上去，否则发布器拿不到 LLM 生成能力
                # （此前漏了这一行，导致永远走兜底文案）
                poster_gen = _gen
            def _moment_state(persona_id: str) -> str:
                """朋友圈生成时附带的「她此刻的状态」。

                只用能稳定拿到的两样：精力与心情。作用域取 ``web::<persona>``
                （回退作用域）——带 conversation_id 的会话作用域是另一套，
                朋友圈没有会话上下文，拿不到那边的主力状态。这一点等
                作用域统一后再补。
                """
                parts: list[str] = []
                mood_engine = getattr(app_components, "mood_manager", None)
                if mood_engine is not None and persona_id:
                    try:
                        mood = mood_engine.get_mood(f"web::{persona_id}")
                    except Exception:
                        mood = None
                    if mood is not None:
                        energy = getattr(mood, "energy", 0.5) or 0.0
                        valence = getattr(mood, "valence", 0.0) or 0.0
                        if energy < 0.35:
                            parts.append("这会儿有点累，提不起劲")
                        elif energy > 0.75:
                            parts.append("精力挺好")
                        if valence <= -0.3:
                            parts.append("心情有点低")
                        elif valence >= 0.3:
                            parts.append("心情不错")
                return "；".join(parts)

            poster = MomentsAutoPoster(
                saver=_moment_saver,
                get_settings=_load_settings,
                generate_fn=poster_gen,
                persona_name_fn=_moment_poster_persona_name,
                state_fn=_moment_state,
            )
            app_components.moments_poster = poster
            asyncio.get_running_loop().create_task(poster.run())
            logger.info("WebUI: moments auto-poster started")
    except Exception as e:
        logger.warning(f"WebUI: moments auto-poster start failed: {e}")

    # ── 主动消息调度 ──
    # 此前 proactive 只有一个调用点：CLI 的输入超时分支。用网页端和微信时
    # `proactive_enabled: true` 是空配置 —— 她一次都不会主动找你。
    # 这里补上调度层，交付动作按平台分流：Web 写库 + SSE，微信走 adapter.send。
    try:
        from core.proactive_runner import ProactiveRunner
        from core.runtime import event_bus

        async def _deliver_proactive(target, text: str) -> bool:
            memory_uid = target.scope_id or target.user_id

            # 微信：先发后落。发送失败就不落库——发都没发出去的消息，
            # 不能让她"记得自己说过"（历史与微信端必须一致）。
            if target.platform == "wechat":
                mgr = getattr(app_components, "adapter_manager", None)
                adapter = mgr.get("wechat", target.account_id) if mgr else None
                if adapter is None:
                    logger.info(
                        f"Proactive: no wechat adapter for {target.account_id!r}, "
                        f"message dropped (not persisted)"
                    )
                    return False
                sent = await adapter.send(target.user_id, text)
                if not sent:
                    logger.warning(
                        f"Proactive: wechat send failed for {target.user_id}, "
                        f"message dropped (not persisted)"
                    )
                    return False
                try:
                    app_components.chat_history.add_message(
                        memory_uid, "assistant", text,
                        platform=target.platform,
                        persona_id=target.persona_id,
                        account_id=target.account_id,
                    )
                except Exception as e:
                    # 已发出去但落库失败：历史缺失比虚假历史好，只记日志
                    logger.warning(f"Proactive: persist-after-send failed: {e}")
                return True

            # Web：先落库再推给订阅了这个作用域的前端（前端收到即刷新聊天列表）
            try:
                app_components.chat_history.add_message(
                    memory_uid, "assistant", text,
                    platform=target.platform,
                    persona_id=target.persona_id,
                    account_id=target.account_id,
                )
            except Exception as e:
                logger.warning(f"Proactive: persist failed for {memory_uid}: {e}")
                return False
            event_bus.publish_history_changed(memory_uid, source="proactive")
            return True

        # 情绪内生源：没有用户输入时她也会变化（未闭合话题压力 / 孤独感）。
        # 纯代码零模型调用，随调度循环每轮施加（自带 10 分钟节流）。
        from core.emotion.internal_source import InternalMoodSource
        from core.runtime.vitality_monitor import VitalityMonitor
        internal_source = InternalMoodSource(
            mood_engine=app_components.mood_manager,
            open_loop=app_components.open_loop,
            chat_history=app_components.chat_history,
        )
        vitality_monitor = VitalityMonitor(
            memory_manager=app_components.memory_mgr,
            chat_history=app_components.chat_history,
        )

        runner = ProactiveRunner(
            proactive=app_components.proactive,
            conversation_store=app_components.conversation_store,
            chat_history=app_components.chat_history,
            advanced_config=getattr(app_components, "advanced_config", {}) or {},
            deliver=_deliver_proactive,
            tick_seconds=int(
                (getattr(app_components, "advanced_config", {}) or {})
                .get("proactive_tick_seconds", 120)
            ),
            quiet_minutes=int(
                (getattr(app_components, "advanced_config", {}) or {})
                .get("proactive_quiet_minutes", 15)
            ),
            internal_source=internal_source,
            vitality_monitor=vitality_monitor,
        )
        app_components.proactive_runner = runner
        runner.start()
    except Exception as e:
        logger.warning(f"WebUI: proactive runner start failed: {e}")

    url = f"http://{host}:{port}"
    print(f"\n  🌐 网页端已启动：{url}")
    print(f"  浏览器打开上面的地址即可对话 + 调参")
    print(f"  按 Ctrl+C 停止\n")
    logger.info(f"WebUI running on {url}")
    logger.info(f"慕 · 浮灯 {_installation_id()} · 夜航中")

    try:
        await asyncio.Event().wait()
    finally:
        # 停止主动消息调度
        runner = getattr(app_components, "proactive_runner", None)
        if runner is not None:
            try:
                await runner.stop()
            except Exception as e:
                logger.warning(f"WebUI: proactive runner stop failed: {e}")
        # 停止所有适配器（微信长轮询等后台任务）
        adapter_manager = getattr(app_components, "adapter_manager", None)
        if adapter_manager is not None:
            try:
                await adapter_manager.stop_all()
            except Exception as e:
                logger.warning(f"WebUI: adapter stop_all failed: {e}")
        try:
            await app_components.handler.pipeline.shutdown()
        except Exception as e:
            logger.warning(f"WebUI: pipeline shutdown failed: {e}")
        await runner.cleanup()
