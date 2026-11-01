"""settings.json 读写、密钥迁移与运行时热更新。

从 common.py 拆出（2026-11-01 模块化第二步）。
settings.json 是真实用户配置（.gitignore），这里的写入全部走原子替换。
"""

from __future__ import annotations

import json
import uuid

from loguru import logger

from core.config import CONFIG_DIR, DATA_DIR, load_advanced
from core.security import get_secret_manager, migrate_settings_secrets
from webui.schema import SETTINGS_SCHEMA, coerce_value

SETTINGS_PATH = CONFIG_DIR / "settings.json"


def _load_settings() -> dict:
    """读取 settings.json，缺失返回空 dict。"""
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"WebUI: failed to read settings.json: {e}")
    return {}


def _app_version() -> str:
    """单一来源：core/config.APP_VERSION（与 pyproject.toml 同步维护）。"""
    from core.config import APP_VERSION
    return APP_VERSION


def _installation_id() -> str:
    """本机安装实例标识：首次生成后持久化，用于诊断定位与授权管理。

    不含任何个人信息（随机 UUID），也不上传——仅在 /api/about 与启动日志中出现。
    """
    path = DATA_DIR / "installation_id"
    try:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        value = uuid.uuid4().hex
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return value
    except Exception:
        return ""


def _save_settings(settings: dict) -> None:
    """原子写入 settings.json。

    mkdir 的必须是目标文件的父目录而不是 CONFIG_DIR —— 两者在源码模式
    相同，但测试/打包场景替换 SETTINGS_PATH 后前者创建的目录是错的。
    """
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    tmp.replace(SETTINGS_PATH)


def _secret_manager():
    """Resolve the secret store beside the active settings file (testable)."""
    return get_secret_manager(SETTINGS_PATH.parent)


def _migrate_existing_secrets() -> dict:
    """Move legacy plaintext keys when possible without risking availability."""
    settings = _load_settings()
    if not settings:
        status = _secret_manager().status
        return {"changed": False, "backend": status.backend, "available": status.available,
                "protected": 0, "plaintext": 0}
    migrated, report = migrate_settings_secrets(settings, manager=_secret_manager())
    if report["changed"]:
        _save_settings(migrated)
        logger.info(
            "Protected {} credential(s) with {}",
            report["protected"], report["backend"],
        )
    return report


def _current_values() -> dict:
    """按 schema 汇总当前有效值：settings.json > load_advanced 默认 > schema 默认。"""
    settings = _load_settings()
    advanced = settings.get("advanced", {})
    models = settings.get("models", {})
    default_model = settings.get("default_model")
    model_cfg = models.get(default_model, {}) if default_model else {}
    # 任取一个模型兜底（default 未设时）
    if not model_cfg and models:
        model_cfg = next(iter(models.values()))

    fallback_advanced = load_advanced()
    values: dict = {}
    for field in SETTINGS_SCHEMA:
        key = field["key"]
        target = field["target"]
        default = field["default"]
        if target == "model":
            values[key] = model_cfg.get(key, default)
        elif target == "model_repetition":
            # presence/frequency 合并展示，取 presence 为准
            values[key] = model_cfg.get("presence_penalty", default)
        else:  # advanced
            values[key] = advanced.get(key, fallback_advanced.get(key, default))
        values[key] = coerce_value(field, values[key])
    return values


def _persist_values(values: dict) -> None:
    """把 schema 值写回 settings.json 的正确位置。"""
    settings = _load_settings()
    advanced = settings.setdefault("advanced", {})
    models = settings.setdefault("models", {})
    default_model = settings.get("default_model")
    targets = [models[default_model]] if default_model and default_model in models else list(models.values())

    for field in SETTINGS_SCHEMA:
        key = field["key"]
        target = field["target"]
        val = values.get(key)
        if val is None:
            continue
        if target == "model":
            for m in targets:
                m[key] = val
        elif target == "model_repetition":
            for m in targets:
                m["presence_penalty"] = val
                m["frequency_penalty"] = val
        else:
            advanced[key] = val
    _save_settings(settings)


def _apply_live(app, values: dict) -> None:
    """热更新到运行中的实例，避免重启。"""
    # 1. 模型参数 → 直接改 LLM 实例属性
    try:
        llm = app.registry.get() if app.registry.available_models else None
    except Exception:
        llm = None
    if llm is not None:
        if "temperature" in values:
            llm.temperature = values["temperature"]
        if "max_tokens" in values:
            llm.max_tokens = values["max_tokens"]
        if "max_retries" in values:
            llm.max_retries = values["max_retries"]
        if "repetition_penalty" in values:
            llm.presence_penalty = values["repetition_penalty"]
            llm.frequency_penalty = values["repetition_penalty"]

    # 2. advanced 参数 → 更新共享 config dict
    cfg = getattr(app, "advanced_config", None)
    if isinstance(cfg, dict):
        for key in ("segment_max_length", "debounce_seconds", "summarize_threshold",
                    "proactive_enabled", "proactive_active_start", "proactive_active_end",
                    "proactive_interval_min", "proactive_interval_max", "auto_extract_memory"):
            if key in values:
                cfg[key] = values[key]

    # 3. 主动消息开关热更新
    if hasattr(app, "proactive") and app.proactive is not None:
        if "proactive_enabled" in values:
            app.proactive.enabled = values["proactive_enabled"]

    # 3.5 去抖延迟热更新（review P2-10）：此前只改 config dict，而 DebounceManager
    # 及其每个 state 在构造时复制了值，运行中改设置实际不生效、重启才生效。
    dm = getattr(app, "debounce_manager", None)
    if dm is not None and "debounce_seconds" in values:
        try:
            dm.timeout = float(values["debounce_seconds"])
            for state in getattr(dm, "_states", {}).values():
                state.timeout = dm.timeout  # 已挂起的定时器保持旧值，新定时器生效
        except (TypeError, ValueError, AttributeError):
            pass
