"""Cross-platform application paths.

The source checkout keeps its historical ``config/``, ``data/`` and ``logs/``
layout for backwards compatibility. Packaged builds set ``MU_PORTABLE=1`` and
store writable state in a sibling ``userdata/`` directory instead. A future
desktop installer can set ``MU_HOME`` without changing any business module.

环境变量：新前缀 ``MU_``（如 ``MU_HOME`` / ``MU_PORTABLE`` / ``MU_PACKAGED``），
旧前缀 ``CC_`` 在过渡期仍被兼容读取（见 ``_legacy_env``）。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


APP_NAME = "Muu"
# 旧版（更名前）的应用目录名：打包模式下若旧数据目录存在而新目录不存在，
# 继续沿用旧目录，避免用户已产生的数据被"改名"孤立。
LEGACY_APP_NAME = "CyberCompanion"


def _legacy_env(env: dict[str, str], new_key: str, legacy_key: str) -> str:
    """读取环境变量：优先新前缀 MU_，兼容旧前缀 CC_（过渡期）。"""
    value = env.get(new_key)
    if value is None:
        value = env.get(legacy_key, "")
    return value


@dataclass(frozen=True)
class RuntimePaths:
    """Read-only resources and writable user state for one application run."""

    resource_dir: Path
    home_dir: Path
    data_dir: Path
    config_dir: Path
    logs_dir: Path
    cache_dir: Path
    portable: bool = False


def _source_dir() -> Path:
    # core/runtime/paths.py -> project root
    return Path(__file__).resolve().parents[2]


def _platform_home(
    *,
    environ: dict[str, str] | None = None,
    platform_name: str | None = None,
    user_home: str | Path | None = None,
) -> Path:
    """Return a platform default using injectable inputs for release tests."""
    env = os.environ if environ is None else environ
    current_platform = platform_name or sys.platform
    home = Path(user_home).expanduser() if user_home is not None else Path.home()
    override = _legacy_env(env, "MU_HOME", "CC_HOME").strip()
    if override:
        return Path(override).expanduser()

    def _app_dir(base: Path) -> Path:
        """新目录名优先；旧目录已存在（有历史数据）时沿用旧目录。"""
        candidate = base / APP_NAME
        if not candidate.exists():
            legacy = base / LEGACY_APP_NAME
            if legacy.exists():
                return legacy
        return candidate

    if current_platform == "win32":
        base = env.get("APPDATA") or env.get("LOCALAPPDATA")
        if base:
            return _app_dir(Path(base))
        return _app_dir(home / "AppData" / "Roaming")
    if current_platform == "darwin":
        return _app_dir(home / "Library" / "Application Support")

    base = env.get("XDG_DATA_HOME", "").strip()
    return _app_dir(Path(base).expanduser() if base else home / ".local" / "share")


def resolve_runtime_paths(
    *,
    resource_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
    platform_name: str | None = None,
    user_home: str | Path | None = None,
) -> RuntimePaths:
    """Resolve paths without creating files.

    ``environ`` is injectable so path behavior can be tested without mutating
    process-global environment variables.
    """
    env = os.environ if environ is None else environ
    resources = Path(
        resource_dir
        or _legacy_env(env, "MU_RESOURCE_DIR", "CC_RESOURCE_DIR")
        or _source_dir()
    ).expanduser().resolve()
    portable = _legacy_env(env, "MU_PORTABLE", "CC_PORTABLE").lower() in {"1", "true", "yes", "on"}

    if portable:
        portable_root = Path(
            _legacy_env(env, "MU_PORTABLE_ROOT", "CC_PORTABLE_ROOT") or resources.parent
        ).expanduser().resolve()
        home = Path(
            _legacy_env(env, "MU_HOME", "CC_HOME") or portable_root / "userdata"
        ).expanduser().resolve()
    elif _legacy_env(env, "MU_HOME", "CC_HOME"):
        home = Path(_legacy_env(env, "MU_HOME", "CC_HOME")).expanduser().resolve()
    elif _legacy_env(env, "MU_PACKAGED", "CC_PACKAGED").lower() in {"1", "true", "yes", "on"}:
        home = _platform_home(
            environ=env,
            platform_name=platform_name,
            user_home=user_home,
        ).resolve()
    else:
        # Source checkout compatibility: existing user data stays untouched.
        home = resources

    return RuntimePaths(
        resource_dir=resources,
        home_dir=home,
        data_dir=home / "data",
        config_dir=home / "config",
        logs_dir=home / "logs",
        cache_dir=home / "cache",
        portable=portable,
    )


def ensure_user_directories(paths: RuntimePaths) -> None:
    """Create writable directories at the application boundary."""
    for directory in (paths.home_dir, paths.data_dir, paths.config_dir, paths.logs_dir, paths.cache_dir):
        directory.mkdir(parents=True, exist_ok=True)


def bootstrap_example_config(paths: RuntimePaths) -> None:
    """Copy packaged examples into a portable user's config on first launch."""
    if not paths.portable:
        return
    ensure_user_directories(paths)
    examples = {
        "settings.example.json": "settings.json",
        "personas.example.json": "personas.json",
        "mcp_servers.example.json": "mcp_servers.json",
    }
    for source_name, target_name in examples.items():
        source = paths.resource_dir / "config" / source_name
        target = paths.config_dir / target_name
        if source.exists() and not target.exists():
            target.write_bytes(source.read_bytes())
