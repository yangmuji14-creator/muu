"""朋友圈（发现/moments）本地 JSON 存储。

从 common.py 拆出（2026-11-01 模块化第二步）。纯本地存储，
不依赖任何模型服务；`common` 保留同名 re-export，老引用不用改。
"""

from __future__ import annotations

import json
import re
import uuid

from loguru import logger

from core.config import DATA_DIR

_MOMENTS_PATH = DATA_DIR / "moments.json"
_MAX_POST_TEXT = 2000
_MAX_REPLY_TEXT = 500
_MOMENT_ID_RE = re.compile(r"^mom_[0-9a-f]{12}$")
_REPLY_ID_RE = re.compile(r"^rep_[0-9a-f]{12}$")


def _new_moment_id() -> str:
    return f"mom_{uuid.uuid4().hex[:12]}"


def _new_reply_id() -> str:
    return f"rep_{uuid.uuid4().hex[:12]}"


def _moment_now_iso() -> str:
    """朋友圈动态时间戳（本机时区 ISO）。"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _load_moments() -> list[dict]:
    if not _MOMENTS_PATH.exists():
        return []
    try:
        return json.loads(_MOMENTS_PATH.read_text(encoding="utf-8")).get("moments") or []
    except Exception as exc:
        logger.warning(f"moments load failed: {exc}")
        return []


def _save_moments(moments: list[dict]) -> None:
    _MOMENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _MOMENTS_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"moments": moments}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(_MOMENTS_PATH)


def _moment_author_label(app_components, author: str) -> str:
    if author == "user":
        return "我"
    if not author:
        return ""
    try:
        loader = getattr(app_components, "persona_loader", None)
        if loader is not None:
            for p in loader.list_all():
                if p.id == author:
                    return p.name or author
    except Exception:
        pass
    return author
