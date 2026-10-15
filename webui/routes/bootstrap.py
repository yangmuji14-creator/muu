"""首次引导路由域（模块化拆分，行为等价搬移）。"""

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
    @routes.get("/api/bootstrap/status")
    async def get_bootstrap_status(_request):
        """Return the minimum state needed by the first-run Web onboarding."""
        registry = getattr(app_components, "registry", None)
        available = list(getattr(registry, "available_models", []))
        default_model = getattr(registry, "default_model", None)
        settings = _load_settings()
        persona = getattr(getattr(app_components, "persona_loader", None), "get", lambda _id: None)(DEFAULT_PERSONA_ID)
        persona_defaults = dict(PERSONA_ONBOARDING_DEFAULTS)
        for key in persona_defaults:
            value = getattr(persona, key, "") if persona is not None else ""
            if isinstance(value, str) and value.strip():
                persona_defaults[key] = value
        return web.json_response({
            "needs_setup": not bool(available and default_model),
            "needs_persona_setup": not bool(settings.get("advanced", {}).get("persona_onboarding_completed")),
            "models": available,
            "default_model": default_model,
            "persona_defaults": persona_defaults,
            "portable": bool(os.getenv("MU_PORTABLE") or os.getenv("CC_PORTABLE")),
        })

    @routes.get("/api/bootstrap/providers")
    async def get_bootstrap_providers(_request):
        return web.json_response({"providers": public_provider_catalog()})

    @routes.post("/api/bootstrap/test")
    async def post_bootstrap_test(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "code": "invalid_json", "message": "请求格式不正确"}, status=400)
        provider = str(body.get("provider") or "").strip()
        spec = get_provider_spec(provider)
        if spec is None:
            return web.json_response({"ok": False, "code": "provider", "message": "暂不支持这个服务商"}, status=400)
        result = await test_provider_connection(
            base_url=str(body.get("base_url") or spec.base_url),
            api_key=str(body.get("api_key") or ""),
            model_name=str(body.get("model_name") or spec.default_model),
        )
        return web.json_response(result, status=200 if result.get("ok") else 400)

    @routes.post("/api/bootstrap/models")
    async def post_bootstrap_models(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "code": "invalid_json", "message": "请求格式不正确"}, status=400)
        result = await discover_models(
            base_url=str(body.get("base_url") or ""),
            api_key=str(body.get("api_key") or ""),
        )
        return web.json_response(result, status=200 if result.get("ok") else 400)

    @routes.post("/api/bootstrap/complete")
    async def post_bootstrap_complete(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "请求格式不正确"}, status=400)
        provider = str(body.get("provider") or "").strip()
        spec = get_provider_spec(provider)
        if spec is None:
            return web.json_response({"error": "暂不支持这个服务商"}, status=400)
        api_key = str(body.get("api_key") or "").strip()
        model_name = str(body.get("model_name") or spec.default_model).strip()
        base_url = str(body.get("base_url") or spec.base_url).strip().rstrip("/")
        if not api_key or not model_name or len(api_key) > 512 or len(model_name) > 200:
            return web.json_response({"error": "请填写有效的 API 密钥和模型名称"}, status=400)
        settings = _load_settings()
        model_config = {
            "provider": spec.provider,
            "model_name": model_name,
            "base_url": base_url,
            "api_key": api_key,
            "max_tokens": 4096,
            "temperature": 1.0,
            "presence_penalty": 0.3,
            "frequency_penalty": 0.3,
        }
        model_config, _protected = protect_config_secret(
            model_config, model_secret_ref(provider), manager=_secret_manager()
        )
        settings.setdefault("models", {})[provider] = model_config
        settings["default_model"] = provider
        settings.setdefault("advanced", {})
        _save_settings(settings)

        registry = getattr(app_components, "registry", None)
        if registry is not None and hasattr(registry, "load_config"):
            try:
                registry.load_config(SETTINGS_PATH)
                handler = getattr(app_components, "handler", None)
                if handler is not None and hasattr(handler, "activate_default_model"):
                    handler.activate_default_model()
                vision = getattr(app_components, "vision_manager", None)
                if vision is not None and hasattr(vision, "update_main_model"):
                    vision.update_main_model(registry.get())
            except Exception as e:
                logger.warning(f"WebUI bootstrap registry reload failed: {e}")
                return web.json_response({"ok": True, "restart_required": True, "model": provider})
        return web.json_response({"ok": True, "restart_required": False, "model": provider})

    @routes.post("/api/bootstrap/persona")
    async def post_bootstrap_persona(request):
        """Save the three beginner-friendly persona fields and finish onboarding."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "请求格式不正确"}, status=400)
        fields = {}
        for key in ("system_prompt", "output_examples", "persona_prompt"):
            value = body.get(key, "")
            if value is None:
                value = ""
            if not isinstance(value, str):
                return web.json_response({"error": f"{key} 必须是文本"}, status=400)
            value = value.strip()
            if len(value) > 20000:
                return web.json_response({"error": "人设文本过长，请控制在 20000 字以内"}, status=400)
            fields[key] = value
        loader = getattr(app_components, "persona_loader", None)
        persona = loader.get(DEFAULT_PERSONA_ID) if loader is not None else None
        if persona is None:
            return web.json_response({"error": "默认人设不存在，请先创建一个人设"}, status=409)
        updated = loader.update(DEFAULT_PERSONA_ID, **fields)
        if updated is None:
            return web.json_response({"error": "保存人设失败"}, status=500)
        settings = _load_settings()
        settings.setdefault("advanced", {})["persona_onboarding_completed"] = True
        _save_settings(settings)
        return web.json_response({"ok": True, "persona": {"id": updated.id, "name": updated.name}})

