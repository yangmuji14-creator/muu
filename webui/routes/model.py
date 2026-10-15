"""模型与视觉路由域（模块化拆分，行为等价搬移）。"""

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
    @routes.get("/api/model")
    async def get_model(_request):
        """返回当前模型 + 可用模型列表（含各自的多模态声明）。"""
        try:
            settings = _load_settings()
            models = settings.get("models", {})
            if not isinstance(models, dict):
                models = {}
            details = {
                key: {
                    "model_name": str(cfg.get("model_name") or cfg.get("model") or ""),
                    # auto / yes / no；缺省视为 auto（走启发式检测）
                    "multimodal": str(cfg.get("multimodal") or "auto").strip().lower(),
                }
                for key, cfg in models.items()
                if isinstance(cfg, dict)
            }
            return web.json_response({
                "current": settings.get("default_model"),
                "available": list(models.keys()),
                "models": details,
            })
        except Exception as e:
            logger.error(f"WebUI get_model error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.post("/api/model/multimodal")
    async def post_model_multimodal(request):
        """设置某个模型的多模态声明（auto / yes / no）。

        启发式检测覆盖不了所有厂商，猜错的代价是多发一次无意义的图片请求，
        所以让用户显式声明，声明优先于模型名匹配。
        """
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON"}, status=400)
        try:
            model = str(body.get("model") or "").strip()
            value = str(body.get("multimodal") or "auto").strip().lower()
            if not model:
                return web.json_response({"error": "model required"}, status=400)
            if value in ("true", "1", "on"):
                value = "yes"
            if value in ("false", "0", "off"):
                value = "no"
            if value not in ("auto", "yes", "no"):
                return web.json_response(
                    {"error": "multimodal 只支持 auto / yes / no"}, status=400
                )
            settings = _load_settings()
            models = settings.get("models")
            if not isinstance(models, dict) or model not in models or not isinstance(models[model], dict):
                return web.json_response({"error": f"model not found: {model}"}, status=404)
            if value == "auto":
                models[model].pop("multimodal", None)
            else:
                models[model]["multimodal"] = value
            _save_settings(settings)
            logger.info(f"WebUI model {model} multimodal -> {value}")

            # 若改的是当前模型, 立即更新声明（只改判定依据, 不用重启注册表）
            vision = getattr(app_components, "vision_manager", None)
            if vision is not None and model == settings.get("default_model"):
                if hasattr(vision, "set_multimodal_declared"):
                    vision.set_multimodal_declared(value)
            return web.json_response({
                "ok": True,
                "model": model,
                "multimodal": value,
                "image_chain": str(getattr(vision, "image_chain", "") or ""),
            })
        except Exception as e:
            logger.error(f"WebUI post_model_multimodal error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.post("/api/model")
    async def post_model(request):
        """切换默认模型（写 settings.json，下次启动生效，不热切换）。"""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON"}, status=400)
        try:
            model = body.get("model")
            if not model:
                return web.json_response({"error": "model required"}, status=400)
            settings = _load_settings()
            available = list(settings.get("models", {}).keys())
            if model not in available:
                return web.json_response(
                    {"error": f"model not found: {model}", "available": available},
                    status=400,
                )
            settings["default_model"] = model
            _save_settings(settings)
            logger.info(f"WebUI model switched to {model} (effective on next restart)")
            return web.json_response({
                "ok": True,
                "message": "模型已切换，下次启动生效",
                "current": model,
            })
        except Exception as e:
            logger.error(f"WebUI post_model error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.post("/api/model/provider")
    async def add_model_provider(request):
        """添加一个新的模型提供商配置到 settings.json。

        统一字段名（与 core/llm/registry.py._register_from_config 对齐）：
        provider / model_name / base_url / api_key /
        temperature / max_tokens / presence_penalty / frequency_penalty
        """
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON"}, status=400)
        try:
            key = (body.get("key") or "").strip()
            provider = (body.get("provider") or "").strip()
            model_name = (body.get("model_name") or "").strip()
            base_url = (body.get("base_url") or "").strip()
            api_key = (body.get("api_key") or "").strip()
            if not key:
                return web.json_response({"error": "key required"}, status=400)
            if not provider:
                return web.json_response({"error": "provider required"}, status=400)
            if not model_name:
                return web.json_response({"error": "model_name required"}, status=400)
            if not base_url:
                return web.json_response({"error": "base_url required"}, status=400)
            if not api_key:
                return web.json_response({"error": "api_key required"}, status=400)
            temperature = body.get("temperature", 1.0)
            try:
                temperature = float(temperature)
            except (TypeError, ValueError):
                return web.json_response(
                    {"error": "temperature must be numeric"}, status=400
                )
            max_tokens = body.get("max_tokens", 2048)
            try:
                max_tokens = int(max_tokens)
            except (TypeError, ValueError):
                return web.json_response(
                    {"error": "max_tokens must be integer"}, status=400
                )
            presence_penalty = body.get("presence_penalty", 0.3)
            frequency_penalty = body.get("frequency_penalty", 0.3)
            try:
                presence_penalty = float(presence_penalty)
                frequency_penalty = float(frequency_penalty)
            except (TypeError, ValueError):
                return web.json_response(
                    {"error": "presence_penalty/frequency_penalty must be numeric"},
                    status=400,
                )
            settings = _load_settings()
            models = settings.setdefault("models", {})
            if key in models:
                return web.json_response(
                    {"error": "model key already exists"}, status=400
                )
            model_config = {
                "provider": provider,
                "model_name": model_name,
                "base_url": base_url,
                "api_key": api_key,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "presence_penalty": presence_penalty,
                "frequency_penalty": frequency_penalty,
            }
            # 新增时即可声明多模态能力（auto / yes / no），声明优先于模型名启发式匹配
            mm = str(body.get("multimodal") or "auto").strip().lower()
            if mm in ("true", "1", "on"):
                mm = "yes"
            elif mm in ("false", "0", "off"):
                mm = "no"
            if mm in ("yes", "no"):
                model_config["multimodal"] = mm
            model_config, _protected = protect_config_secret(
                model_config, model_secret_ref(key), manager=_secret_manager()
            )
            models[key] = model_config
            _save_settings(settings)
            logger.info(
                f"WebUI model provider added: key={key} provider={provider} "
                f"model_name={model_name}"
            )
            return web.json_response({"ok": True, "key": key})
        except Exception as e:
            logger.error(f"WebUI add_model_provider error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.get("/api/vision/config")
    async def get_vision_config(_request):
        settings = _load_settings()
        config = settings.get("advanced", {}).get("vision_model", {})
        if not isinstance(config, dict):
            config = {}
        registry = getattr(app_components, "registry", None)
        main_model = ""
        if registry is not None and getattr(registry, "available_models", None):
            try:
                main_model = str(getattr(registry.get(), "model_name", "") or "")
            except Exception:
                pass
        vision = getattr(app_components, "vision_manager", None)
        # 用户在当前模型上的多模态声明 ("auto"/"yes"/"no")
        declared = ""
        if registry is not None and getattr(registry, "available_models", None):
            try:
                declared = str(getattr(registry.get(), "multimodal_declared", "") or "")
            except Exception:
                declared = ""
        declared = declared.strip().lower() or "auto"
        return web.json_response({
            "provider": str(config.get("provider") or "openai"),
            "model_name": str(config.get("model_name") or ""),
            "base_url": str(config.get("base_url") or ""),
            "has_api_key": bool(resolve_config_secret(
                config,
                env_value=os.getenv("OPENAI_API_KEY", ""),
                manager=_secret_manager(),
            )),
            "main_model": main_model,
            # 用户声明值 (auto/yes/no) 与最终判定结果分开暴露, 前端好展示"来源"
            "main_multimodal_declared": declared,
            "main_is_multimodal": bool(getattr(vision, "main_is_multimodal", False)),
            "image_mode": str(getattr(vision, "image_mode", None) or load_image_mode()),
            "image_chain": str(getattr(vision, "image_chain", "") or ""),
        })

    @routes.post("/api/vision/config")
    async def post_vision_config(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "请求格式不正确"}, status=400)
        values = {}
        for key in ("provider", "model_name", "base_url", "api_key"):
            value = body.get(key, "")
            if not isinstance(value, str):
                return web.json_response({"error": f"{key} 必须是文本"}, status=400)
            values[key] = value.strip()
        if any(len(value) > 512 for value in values.values()):
            return web.json_response({"error": "视觉模型配置过长"}, status=400)
        if values["base_url"] and not re.match(r"^https?://", values["base_url"], re.I):
            return web.json_response({"error": "请填写有效的视觉模型 API 地址"}, status=400)

        settings = _load_settings()
        advanced = settings.setdefault("advanced", {})
        existing = advanced.get("vision_model", {})
        if not isinstance(existing, dict):
            existing = {}
        # 空字段回退既有值（review P2-14）：客户端只想改 image_mode 而没带
        # model_name/base_url 时，空串会把视觉链路静默禁用（update_config 后
        # _vision_enabled=bool(model_name) 为 False）。
        if not values["model_name"] and isinstance(existing.get("model_name"), str):
            values["model_name"] = existing.get("model_name", "")
        if not values["base_url"] and isinstance(existing.get("base_url"), str):
            values["base_url"] = existing.get("base_url", "")
        api_key = values["api_key"] or resolve_config_secret(
            existing,
            env_value=os.getenv("OPENAI_API_KEY", ""),
            manager=_secret_manager(),
        )
        if values["model_name"] and not api_key and not os.getenv("OPENAI_API_KEY"):
            return web.json_response({"error": "请填写视觉模型 API 密钥"}, status=400)
        runtime_config = {
            "provider": values["provider"] or "openai",
            "model_name": values["model_name"],
            "base_url": values["base_url"].rstrip("/"),
            "api_key": api_key,
        }
        stored_config, _protected = protect_config_secret(
            runtime_config,
            vision_secret_ref(),
            manager=_secret_manager(),
        )
        advanced["vision_model"] = stored_config
        # 图片处理方式: auto / direct / vision
        image_mode = str(body.get("image_mode") or "auto").strip().lower()
        if image_mode not in ("auto", "direct", "vision"):
            image_mode = "auto"
        advanced["image_mode"] = image_mode
        # 主模型的多模态声明: 对当前默认模型生效
        declared = str(body.get("multimodal") or "").strip().lower()
        if declared in ("auto", "yes", "no", "true", "false", ""):
            declared = {"true": "yes", "false": "no", "": "auto"}.get(declared, declared)
            default_model = settings.get("default_model")
            if default_model and isinstance(settings.get("models"), dict):
                models = settings["models"]
                if default_model in models and isinstance(models[default_model], dict):
                    if declared == "auto":
                        models[default_model].pop("multimodal", None)
                    else:
                        models[default_model]["multimodal"] = declared
        _save_settings(settings)
        if isinstance(getattr(app_components, "advanced_config", None), dict):
            app_components.advanced_config["vision_model"] = dict(runtime_config)
            app_components.advanced_config["image_mode"] = image_mode
        vision = getattr(app_components, "vision_manager", None)
        if vision is not None and hasattr(vision, "update_config"):
            vision.update_config(
                runtime_config,
                image_mode=image_mode,
                multimodal_declared=declared or "auto",
            )
        return web.json_response({
            "ok": True,
            "provider": runtime_config["provider"],
            "model_name": runtime_config["model_name"],
            "base_url": runtime_config["base_url"],
            "has_api_key": bool(api_key),
            "image_mode": image_mode,
            "multimodal": declared or "auto",
            "image_chain": str(getattr(vision, "image_chain", "") or ""),
        })

    @routes.post("/api/model/discover")
    async def discover_model_provider(request):
        """Discover models for the settings page without browser-side API calls.

        传 model_key 时用该提供商已保存的密钥与地址（用于"拉取可用模型"，
        用户无需重新粘贴 key）。
        """
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "message": "请求格式不正确"}, status=400)
        base_url = str(body.get("base_url") or "").strip()
        api_key = str(body.get("api_key") or "").strip()
        model_key = str(body.get("model_key") or "").strip()
        if model_key and (not base_url or not api_key):
            settings = _load_settings()
            models = settings.get("models")
            cfg = models.get(model_key) if isinstance(models, dict) else None
            if not isinstance(cfg, dict):
                return web.json_response(
                    {"ok": False, "message": f"模型配置不存在：{model_key}"}, status=404
                )
            base_url = base_url or str(cfg.get("base_url") or "")
            api_key = api_key or resolve_config_secret(
                cfg,
                env_value=os.getenv(f"{model_key.upper()}_API_KEY", ""),
                manager=_secret_manager(),
            )
        result = await discover_models(base_url=base_url, api_key=api_key)
        return web.json_response(result, status=200 if result.get("ok") else 400)

    @routes.get("/api/model/roles")
    async def get_model_roles(_request):
        """返回三个角色的当前分配与模型池。

        chat   = 语言模型（主对话，models.<default_model>）
        vision = 图片识别模型（advanced.vision_model）
        video  = 视频识别模型（advanced.video_model，暂未接入识别链路）
        """
        try:
            settings = _load_settings()
            models = settings.get("models")
            models = models if isinstance(models, dict) else {}
            current = settings.get("default_model")
            adv = settings.get("advanced")
            adv = adv if isinstance(adv, dict) else {}

            def _brief(cfg):
                if not isinstance(cfg, dict) or not cfg:
                    return None
                return {
                    "provider": str(cfg.get("provider") or ""),
                    "model_name": str(cfg.get("model_name") or ""),
                    "base_url": str(cfg.get("base_url") or ""),
                }

            chat_cfg = models.get(current) if isinstance(models.get(current), dict) else {}
            tts_active = None
            try:
                tp = _tts_store().active_provider()
                if tp is not None:
                    tts_active = {
                        "provider": "openai",
                        "model_name": str(tp.model or ""),
                        "base_url": str(tp.base_url or ""),
                        "name": str(tp.name or ""),
                        "voice": str(tp.voice or ""),
                    }
            except Exception as e:
                logger.warning(f"/api/model/roles tts failed: {e}")
            return web.json_response({
                "chat": {
                    "key": current,
                    "model_name": str(chat_cfg.get("model_name") or ""),
                    "base_url": str(chat_cfg.get("base_url") or ""),
                },
                "vision": _brief(adv.get("vision_model")),
                "video": _brief(adv.get("video_model")),
                "tts": tts_active,
                "pool": [
                    {
                        "key": key,
                        "model_name": str(cfg.get("model_name") or ""),
                        "base_url": str(cfg.get("base_url") or ""),
                        "is_current": key == current,
                    }
                    for key, cfg in models.items()
                    if isinstance(cfg, dict)
                ],
            })
        except Exception as e:
            logger.error(f"WebUI get_model_roles error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.post("/api/model/role")
    async def set_model_role(request):
        """把某个模型分配给角色：chat / vision / video。

        - chat：改写当前提供商条目的 model_name（同厂商内切换，保住密钥映射）。
          模型名不会被改动到别的 base_url；跨厂商请走"新增提供商"。
        - vision：写 advanced.vision_model 并热更新视觉管理器。
        - video：写 advanced.video_model（预留，识别链路尚未接入）。
        """
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON"}, status=400)
        role = str(body.get("role") or "").strip().lower()
        model_name = str(body.get("model_name") or "").strip()
        if role not in ("chat", "vision", "video", "tts"):
            return web.json_response({"error": "role 只支持 chat / vision / video / tts"}, status=400)
        if not model_name:
            return web.json_response({"error": "model_name required"}, status=400)
        try:
            settings = _load_settings()
            models = settings.get("models")
            if not isinstance(models, dict) or not models:
                return web.json_response({"error": "还没有配置任何提供商"}, status=400)
            default_model = settings.get("default_model")
            template = models.get(default_model) if isinstance(models.get(default_model), dict) else None
            if template is None:
                template = next((v for v in models.values() if isinstance(v, dict)), {})
            current_key = default_model if isinstance(models.get(default_model), dict) else next(iter(models))

            if role == "chat":
                models[current_key]["model_name"] = model_name
                _save_settings(settings)
                # 热切换：同一个 LLM 实例改 model_name 即可生效（_build_model_id 每次请求现算）。
                # 同一 provider 内换模型（如 Flash ↔ Pro）不需要重启服务。
                hot = False
                try:
                    registry = getattr(app_components, "registry", None)
                    llm = registry.get() if registry is not None else None
                    if llm is not None and hasattr(llm, "model_name"):
                        llm.model_name = model_name
                        hot = True
                        vision = getattr(app_components, "vision_manager", None)
                        if vision is not None and hasattr(vision, "update_main_model"):
                            vision.update_main_model(llm)
                except Exception as e:
                    logger.warning(f"hot switch main model failed: {e}")
                logger.info(f"WebUI 语言模型 -> {model_name}（{current_key}，{'已热切换' if hot else '重启后生效'}）")
                return web.json_response({
                    "ok": True,
                    "role": "chat",
                    "key": current_key,
                    "model_name": model_name,
                    "hot_switched": hot,
                    "message": f"语言模型已切换为 {model_name}" + ("，立即生效" if hot else "（重启后生效）"),
                })

            if role == "tts":
                # 语音模型落在 TTS 服务商配置里（config/tts_providers.json）。
                # 取「第一个 enabled」为当前，所以插入到列表首位即成为生效项。
                base_url = str(body.get("base_url") or template.get("base_url") or "").rstrip("/")
                api_key = resolve_config_secret(
                    template,
                    env_value=os.getenv(f"{current_key.upper()}_API_KEY", ""),
                    manager=_secret_manager(),
                )
                store = _tts_store()
                providers = store.load_providers()
                found = next((p for p in providers if p.name == model_name), None)
                voice = found.voice if found else ""
                entry = TTSProvider(
                    name=model_name,
                    type="openai",
                    api_key=api_key,
                    base_url=base_url or "https://api.openai.com",
                    model=model_name,
                    # voice 为空串会在合成请求里带出非法值，回退默认音色
                    voice=voice or "alloy",
                    enabled=True,
                )
                providers = [p for p in providers if p.name != model_name]
                providers.insert(0, entry)
                store.save_providers(providers)
                logger.info(f"WebUI 语音模型 -> {model_name}（已置为当前语音服务商）")
                return web.json_response({
                    "ok": True,
                    "role": "tts",
                    "model_name": model_name,
                    "base_url": entry.base_url,
                    "message": f"语音模型已设为 {model_name}（已置为当前语音服务商）"
                               "｜注意：这里必须选语音合成模型（如 tts-1 / gpt-4o-mini-tts），"
                               "普通聊天模型无法合成语音",
                })

            provider = str(template.get("provider") or "openai")
            base_url = str(body.get("base_url") or template.get("base_url") or "").rstrip("/")
            entry = {
                "provider": provider,
                "model_name": model_name,
                "base_url": base_url,
            }
            # 保留密钥引用（能力范围内复用同一个密钥）
            ref = str(template.get("api_key_ref") or "").strip()
            if ref:
                entry["api_key_ref"] = ref
            elif template.get("api_key"):
                entry["api_key"] = template.get("api_key")

            adv = settings.setdefault("advanced", {})
            field = "vision_model" if role == "vision" else "video_model"
            existing = adv.get(field)
            if isinstance(existing, dict):
                # 保留原有 provider 标签与密钥信息（用户可能单独给视觉模型配过 key）
                if existing.get("provider"):
                    provider = str(existing.get("provider"))
                if existing.get("api_key_ref") and not entry.get("api_key_ref"):
                    entry["api_key_ref"] = str(existing.get("api_key_ref"))
                elif existing.get("api_key") and not entry.get("api_key"):
                    entry["api_key"] = str(existing.get("api_key"))
            entry["provider"] = provider
            adv[field] = entry
            _save_settings(settings)

            if role == "vision":
                if isinstance(getattr(app_components, "advanced_config", None), dict):
                    app_components.advanced_config["vision_model"] = dict(entry)
                vision = getattr(app_components, "vision_manager", None)
                if vision is not None and hasattr(vision, "update_config"):
                    # VisionManager 只读明文 api_key、不解析 api_key_ref：
                    # 直接把 ref 形式的 entry 热更进去，密钥走 secret store 的用户
                    # 会在热切换后视觉 401（重启才会经 load_vision_config 解析恢复）。
                    runtime_entry = dict(entry)
                    resolved_key = resolve_config_secret(
                        entry,
                        env_value=os.getenv(f"{current_key.upper()}_API_KEY", ""),
                        manager=_secret_manager(),
                    )
                    if resolved_key:
                        runtime_entry["api_key"] = resolved_key
                        runtime_entry.pop("api_key_ref", None)
                    vision.update_config(runtime_entry)
            else:
                logger.info(f"WebUI 视频识别模型 -> {model_name}（暂未接入识别链路）")
            return web.json_response({
                "ok": True,
                "role": role,
                "model_name": model_name,
                "base_url": base_url,
                "message": "视频识别模型已保存（识别链路尚未接入）" if role == "video" else "图片识别模型已保存",
            })
        except Exception as e:
            logger.error(f"WebUI set_model_role error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    @routes.delete("/api/model/{model_key}")
    async def delete_model_provider(request):
        """删除一个模型提供商配置。"""
        model_key = request.match_info["model_key"]
        try:
            settings = _load_settings()
            models = settings.get("models", {})
            if model_key not in models:
                return web.json_response(
                    {"error": "model key not found"}, status=404
                )
            if len(models) == 1:
                return web.json_response(
                    {"error": "cannot delete last model"}, status=400
                )
            removed = models[model_key]
            reference = str(removed.get("api_key_ref") or "") if isinstance(removed, dict) else ""
            del models[model_key]
            if settings.get("default_model") == model_key:
                settings["default_model"] = next(iter(models))
            _save_settings(settings)
            if reference:
                _secret_manager().delete(reference)
            logger.info(f"WebUI model provider deleted: key={model_key}")
            return web.json_response({
                "ok": True,
                "current": settings.get("default_model"),
            })
        except Exception as e:
            logger.error(f"WebUI delete_model_provider error: {e}")
            return web.json_response({"error": str(e)}, status=500)

