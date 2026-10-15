"""微信账号路由域（模块化拆分，行为等价搬移）。"""

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
    @routes.get("/api/wechat/accounts")
    async def list_wechat_accounts(_request):
        """列出所有配置的微信账号 + 状态（has_credentials / adapter_running / session_expired）。"""
        try:
            accounts = _get_wechat_accounts_config()
            adapter_manager = getattr(app_components, "adapter_manager", None)
            result = []
            for acc in accounts:
                acc_id = acc.get("id", "default")
                creds_path = _wechat_credentials_path(acc_id)
                adapter_running = False
                session_expired = False
                if adapter_manager is not None:
                    try:
                        adapter = adapter_manager.get("wechat", acc_id)
                        if adapter is not None:
                            adapter_running = True
                            # WeChatAdapter.session_expired（watchdog 触发后置 True）
                            session_expired = getattr(adapter, "session_expired", False)
                    except Exception:
                        adapter_running = False
                result.append({
                    "id": acc_id,
                    "enabled": acc.get("enabled", True),
                    "auto_start": acc.get("auto_start", False),
                    "persona_id": acc.get("persona_id", DEFAULT_PERSONA_ID),
                    "persona_name": (
                        getattr(
                            app_components.persona_loader.get(
                                acc.get("persona_id", DEFAULT_PERSONA_ID)
                            ),
                            "name",
                            "",
                        )
                        if getattr(app_components, "persona_loader", None) is not None
                        else ""
                    ),
                    "has_credentials": creds_path.exists(),
                    "adapter_running": adapter_running,
                    "session_expired": session_expired,
                })
            return web.json_response(result)
        except Exception as e:
            logger.error(f"WebUI list_wechat_accounts error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.post("/api/wechat/accounts")
    async def create_wechat_account(request):
        """新增微信账号配置。body: {id, persona_id?, enabled?, auto_start?}。

        id 必须匹配 ^[a-zA-Z0-9_-]{3,32}$ 或为 "default"。
        重复 id → 409；非法 id → 400。
        """
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON"}, status=400)
        try:
            acc_id = (body.get("id") or "").strip()
            if not acc_id:
                return web.json_response({"error": "id required"}, status=400)
            if not _validate_wechat_account_id(acc_id):
                return web.json_response(
                    {"error": "id must match ^[a-zA-Z0-9_-]{3,32}$ or be 'default'"},
                    status=400,
                )
            accounts = _get_wechat_accounts_config()
            if any(a.get("id") == acc_id for a in accounts):
                return web.json_response(
                    {"error": f"account already exists: {acc_id}"}, status=409,
                )
            explicit_persona_id = str(body.get("persona_id") or "").strip()
            persona_id = explicit_persona_id or DEFAULT_PERSONA_ID
            loader = getattr(app_components, "persona_loader", None)
            if explicit_persona_id and loader is not None and loader.get(persona_id) is None:
                return web.json_response({"error": "persona not found"}, status=400)
            new_acc = {
                "id": acc_id,
                "enabled": bool(body.get("enabled", True)),
                "auto_start": bool(body.get("auto_start", False)),
                "persona_id": persona_id,
            }
            accounts.append(new_acc)
            _save_wechat_accounts_config(accounts)
            _set_runtime_wechat_accounts(app_components, accounts)
            logger.info(f"WebUI wechat account created: {acc_id}")
            return web.json_response(new_acc)
        except Exception as e:
            logger.error(f"WebUI create_wechat_account error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.patch("/api/wechat/accounts/{account_id}")
    async def update_wechat_account(request):
        """Change the single role assigned to an external WeChat account."""
        account_id = request.match_info["account_id"]
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON"}, status=400)
        persona_id = str(body.get("persona_id") or "").strip()
        if not persona_id:
            return web.json_response({"error": "persona_id required"}, status=400)
        loader = getattr(app_components, "persona_loader", None)
        persona = loader.get(persona_id) if loader is not None else None
        if loader is not None and persona is None:
            return web.json_response({"error": "persona not found"}, status=400)
        try:
            accounts = _get_wechat_accounts_config()
            account = next((item for item in accounts if item.get("id") == account_id), None)
            if account is None:
                return web.json_response(
                    {"error": f"account not found: {account_id}"}, status=404,
                )
            account["persona_id"] = persona_id
            _save_wechat_accounts_config(accounts)
            _set_runtime_wechat_accounts(app_components, accounts)
            synced = 0
            store = getattr(app_components, "conversation_store", None)
            if store is not None:
                synced = store.update_account_persona("wechat", account_id, persona_id)
            return web.json_response({
                "ok": True,
                "id": account_id,
                "persona_id": persona_id,
                "persona_name": getattr(persona, "name", "") if persona else "",
                "bindings_updated": synced,
            })
        except Exception as e:
            logger.error(f"WebUI update_wechat_account error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.delete("/api/wechat/accounts/{account_id}")
    async def delete_wechat_account(request):
        """删除微信账号配置 + 凭证文件 + 停止适配器（若运行中）。不存在 → 404。"""
        account_id = request.match_info["account_id"]
        try:
            accounts = _get_wechat_accounts_config()
            if not any(a.get("id") == account_id for a in accounts):
                return web.json_response(
                    {"error": f"account not found: {account_id}"}, status=404,
                )
            # 先停止 + 注销适配器（避免删除凭证后适配器仍尝试长轮询）
            adapter_manager = getattr(app_components, "adapter_manager", None)
            if adapter_manager is not None:
                try:
                    existing = adapter_manager.get("wechat", account_id)
                    if existing is not None:
                        await existing.stop()
                        adapter_manager.unregister("wechat", account_id)
                except Exception as e:
                    logger.warning(f"WeChat delete: failed to stop adapter for {account_id}: {e}")
            accounts = [a for a in accounts if a.get("id") != account_id]
            _save_wechat_accounts_config(accounts)
            _set_runtime_wechat_accounts(app_components, accounts)
            creds_path = _wechat_credentials_path(account_id)
            if creds_path.exists():
                creds_path.unlink()
            logger.info(f"WebUI wechat account deleted: {account_id}")
            return web.json_response({"ok": True})
        except Exception as e:
            logger.error(f"WebUI delete_wechat_account error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.get("/api/wechat/login/{account_id}/qrcode")
    async def wechat_login_qrcode(request):
        """SSE 二维码登录流。后端在 executor 中调用 weixin_ilink.login()。

        事件:
        - event: qrcode  data: {qr_url, qr_base64?}
        - event: status   data: {status, message}
        - event: done     data: {ok: true} | {ok: false, error: "..."}
        - 心跳: `: ping` 每 5s

        同账号并发登录 → 409。客户端断开 → 取消 executor future + 释放锁。
        """
        account_id = request.match_info["account_id"]
        accounts = _get_wechat_accounts_config()
        if not any(a.get("id") == account_id for a in accounts):
            return web.json_response(
                {"error": f"account not configured: {account_id}"}, status=404,
            )

        lock = _wechat_login_locks.setdefault(account_id, asyncio.Lock())
        if lock.locked():
            return web.json_response(
                {"error": "login already in progress for this account"},
                status=409,
            )

        async with lock:
            resp = web.StreamResponse(
                status=200,
                headers={
                    "Content-Type": "text/event-stream; charset=utf-8",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
            await resp.prepare(request)

            loop = asyncio.get_running_loop()
            events_queue: asyncio.Queue = asyncio.Queue()
            creds_path = _wechat_credentials_path(account_id)
            creds_path.parent.mkdir(parents=True, exist_ok=True)

            # SDK status → user-facing status mapping
            # (SDK typo "scaned" preserved as key)
            status_map = {
                "scaned": ("scanning", "请确认登录"),
                "confirmed": ("confirmed", "登录成功"),
                "expired": ("expired", "二维码过期"),
            }

            def _on_qrcode(url: str) -> None:
                """SDK 回调（executor 线程中执行）→ 推 qrcode 事件。"""
                payload: dict = {"qr_url": url}
                try:
                    import io
                    import base64 as _b64
                    import qrcode  # type: ignore[import-not-found]
                    qr = qrcode.QRCode(border=1)
                    qr.add_data(url)
                    qr.make()
                    img = qr.make_image(fill_color="black", back_color="white")
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    b64 = _b64.b64encode(buf.getvalue()).decode("ascii")
                    payload["qr_base64"] = f"data:image/png;base64,{b64}"
                except Exception:
                    pass  # qrcode lib 未安装 → 前端用 qr_url 自行渲染
                loop.call_soon_threadsafe(
                    events_queue.put_nowait, ("qrcode", payload)
                )

            def _on_status_change(status: str) -> None:
                """SDK 回调 → 推 status 事件。"""
                mapped, message = status_map.get(
                    status, ("failed", f"未知状态: {status}")
                )
                loop.call_soon_threadsafe(
                    events_queue.put_nowait,
                    ("status", {"status": mapped, "message": message}),
                )

            def _do_login():
                """在 executor 线程中执行阻塞 login()。"""
                try:
                    from weixin_ilink import login  # lazy import
                    creds = login(
                        save_to=str(creds_path),
                        on_qrcode=_on_qrcode,
                        on_status_change=_on_status_change,
                    )
                    loop.call_soon_threadsafe(
                        events_queue.put_nowait, ("creds", creds)
                    )
                except Exception as e:
                    loop.call_soon_threadsafe(
                        events_queue.put_nowait, ("error", str(e))
                    )

            executor_future = loop.run_in_executor(None, _do_login)

            async def _send(event: str, data: dict):
                payload = json.dumps(data, ensure_ascii=False)
                await resp.write(
                    f"event: {event}\ndata: {payload}\n\n".encode("utf-8")
                )

            async def _heartbeat():
                """每 2s 发送心跳注释，防止代理超时断开。

                同时检测客户端断开（transport 关闭 / 写入失败），通知主循环
                结束以释放账号锁——否则客户端未等 done 就关闭连接时，
                asyncio.Lock 会永久泄漏，导致该账号后续二维码请求恒 409。
                2s 间隔让"关闭弹窗后立即重开"能快速拿到锁。
                """
                while True:
                    await asyncio.sleep(2)
                    transport = request.transport
                    if transport is None or transport.is_closing():
                        try:
                            events_queue.put_nowait(("disconnect", None))
                        except Exception:
                            pass
                        return
                    try:
                        await resp.write(b": ping\n\n")
                    except Exception:
                        try:
                            events_queue.put_nowait(("disconnect", None))
                        except Exception:
                            pass
                        return

            heartbeat_task = asyncio.create_task(_heartbeat())
            login_succeeded = False
            try:
                while True:
                    event_type, payload = await events_queue.get()
                    if event_type == "qrcode":
                        await _send("qrcode", payload)
                    elif event_type == "status":
                        await _send("status", payload)
                    elif event_type == "creds":
                        await _send("done", {"ok": True})
                        login_succeeded = True
                        break
                    elif event_type == "error":
                        await _send("done", {"ok": False, "error": payload})
                        break
                    elif event_type == "disconnect":
                        # 客户端已断开 → 结束 SSE 处理，finally 释放账号锁
                        break
            except (ConnectionResetError, asyncio.CancelledError):
                pass
            except Exception as e:
                logger.error(f"WeChat SSE login error: {e}")
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
                if not executor_future.done():
                    executor_future.cancel()
                try:
                    await resp.write_eof()
                except Exception:
                    pass
                # 登录成功后自动启动 WeChatAdapter，保持账户在线状态（长轮询维持会话）
                # 仅在 adapter_manager 已注入时执行；失败只 log warning，不影响 SSE 关闭
                if login_succeeded:
                    adapter_manager = getattr(app_components, "adapter_manager", None)
                    if adapter_manager is not None:
                        try:
                            from adapters.wechat import WeChatAdapter
                            # 已注册则先停止+注销旧的，避免重复（例如重复登录场景）
                            try:
                                existing = adapter_manager.get("wechat", account_id)
                                if existing is not None:
                                    await existing.stop()
                                    adapter_manager.unregister("wechat", account_id)
                            except Exception:
                                pass
                            adapter = WeChatAdapter(account_id=account_id)
                            # 注入 session_expired 回调（watchdog 触发后通知 WebUI）
                            adapter.on_session_expired = _make_session_expired_callback(account_id)
                            adapter_manager.register(adapter, account_id=account_id)
                            await adapter.start()
                            logger.info(f"WeChat SSE login: auto-started adapter for {account_id}")
                        except Exception as e:
                            logger.warning(
                                f"WeChat SSE login: auto-start failed for {account_id}: {e}"
                            )
                            try:
                                adapter_manager.unregister("wechat", account_id)
                            except Exception:
                                pass
            return resp

    @routes.post("/api/wechat/logout/{account_id}")
    async def wechat_logout(request):
        """删除凭证文件 + 停止适配器（若运行中）。未配置 → 404。"""
        account_id = request.match_info["account_id"]
        try:
            accounts = _get_wechat_accounts_config()
            if not any(a.get("id") == account_id for a in accounts):
                return web.json_response(
                    {"error": f"account not configured: {account_id}"}, status=404,
                )
            creds_path = _wechat_credentials_path(account_id)
            if creds_path.exists():
                creds_path.unlink()
            adapter_manager = getattr(app_components, "adapter_manager", None)
            if adapter_manager is not None:
                try:
                    adapter = adapter_manager.get("wechat", account_id)
                    if adapter is not None:
                        await adapter.stop()
                except Exception as e:
                    logger.warning(f"WeChat logout: failed to stop adapter: {e}")
            logger.info(f"WebUI wechat logout: {account_id}")
            return web.json_response({"ok": True})
        except Exception as e:
            logger.error(f"WebUI wechat_logout error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.get("/api/wechat/status/{account_id}")
    async def wechat_status(request):
        """返回账号登录状态。未配置 → 404。"""
        account_id = request.match_info["account_id"]
        try:
            accounts = _get_wechat_accounts_config()
            if not any(a.get("id") == account_id for a in accounts):
                return web.json_response(
                    {"error": f"account not configured: {account_id}"}, status=404,
                )
            creds_path = _wechat_credentials_path(account_id)
            adapter_running = False
            adapter_manager = getattr(app_components, "adapter_manager", None)
            if adapter_manager is not None:
                try:
                    adapter = adapter_manager.get("wechat", account_id)
                    adapter_running = adapter is not None
                except Exception:
                    adapter_running = False
            return web.json_response({
                "has_credentials": creds_path.exists(),
                "adapter_running": adapter_running,
            })
        except Exception as e:
            logger.error(f"WebUI wechat_status error: {e}")
            return web.json_response({"error": str(e)}, status=500)





