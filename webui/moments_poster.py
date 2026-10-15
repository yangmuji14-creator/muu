"""朋友圈自动发布器（AI 自动发朋友圈）

按配置在活跃时间段内定时，为指定人设生成并发布一条朋友圈动态。
文案**必须由 LLM 实时生成**（注入 generate_fn）；生成失败或返回空时**跳过本次发布**
（不写库、不推进 _last_posted_at），绝不发布模板化假内容。

时间逻辑（与 core.proactive 对齐）：
- 单一活跃时间段（如 8:00 ~ 22:00），可配
- 在活跃窗口内按固定间隔触发（如每 180 分钟一次）
- 不在活跃时间或未启用则不触发

配置存放于 settings.json → advanced.moments_auto_poster：
{
  "enabled": false,
  "interval_minutes": 180,
  "persona_id": "",
  "active_start": 8,
  "active_end": 22
}
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from loguru import logger

DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "interval_minutes": 180,
    "persona_id": "",
    "active_start": 8,
    "active_end": 22,
}


def load_poster_config(settings: dict) -> dict:
    """从 settings 读取 moments_auto_poster 配置，缺省回退默认值。"""
    adv = settings.get("advanced", {}) or {}
    cfg = dict(DEFAULTS)
    cfg.update(adv.get("moments_auto_poster", {}) or {})
    try:
        cfg["interval_minutes"] = max(5, int(cfg["interval_minutes"]))
    except (TypeError, ValueError):
        cfg["interval_minutes"] = DEFAULTS["interval_minutes"]
    for key in ("active_start", "active_end"):
        try:
            cfg[key] = max(0, min(23, int(cfg[key])))
        except (TypeError, ValueError):
            cfg[key] = DEFAULTS[key]
    cfg["enabled"] = bool(cfg["enabled"])
    cfg["persona_id"] = str(cfg.get("persona_id") or "").strip()
    return cfg


class MomentsAutoPoster:
    """朋友圈自动发布器

    saver(moment: dict) -> dict：把一条动态写入 moments 存储并返回序列化结果
    generate_fn(system_prompt, user_prompt) -> str：LLM 文案生成回调（可 None）
    """

    def __init__(
        self,
        *,
        saver: Callable[[dict], dict],
        get_settings: Callable[[], dict],
        generate_fn: Callable[..., Awaitable[str]] | None = None,
        persona_name_fn: Callable[[str], str] | None = None,
    ):
        self._saver = saver
        self._get_settings = get_settings
        self._generate_fn = generate_fn
        self._persona_name_fn = persona_name_fn
        self._last_posted_at: datetime | None = None
        self._stop = False

    # ── 状态 ──

    def _in_active_window(self, now: datetime, cfg: dict) -> bool:
        return cfg["active_start"] <= now.hour < cfg["active_end"]

    def _interval_elapsed(self, now: datetime, cfg: dict) -> bool:
        if self._last_posted_at is None:
            return True
        return now - self._last_posted_at >= timedelta(minutes=cfg["interval_minutes"])

    # ── 文案生成 ──

    async def _compose_text(self, persona_name: str, cfg: dict) -> str | None:
        """生成一条朋友圈文案。生成失败/为空返回 None（调用方跳过发布）。"""
        if self._generate_fn is None:
            logger.warning("moments poster: 无 LLM 生成回调，跳过本次发布")
            return None
        try:
            now = datetime.now()
            system_prompt = (
                f"你是{persona_name}，一个有血有肉的真人。"
                f"请以{persona_name}的身份发布一条微信朋友圈动态文案。\n"
                f"现在是{now.strftime('%Y年%m月%d日 %H:%M')}。\n"
                f"要求：\n"
                f"1. 像真人随手发的朋友圈，自然、有生活气息，不要 AI 味\n"
                f"2. 只输出文案正文，不加引号、标题或前缀\n"
                f"3. 40 字以内\n"
                f"4. 可以适当用 emoji（别太多）\n"
            )
            text = await self._generate_fn(
                system_prompt=system_prompt,
                user_prompt=(f"请以{persona_name}的身份发一条朋友圈动态。直接输出内容。"),
                max_tokens=400,
                temperature=0.95,
            )
            text = (text or "").strip().strip('"').strip("'")
            if text:
                return text
            logger.warning("moments poster: LLM 返回空文案，跳过本次发布")
        except Exception as e:
            logger.warning(f"moments poster LLM generation failed: {e}")
        return None

    # ── 发布 ──

    async def publish_once(self, force: bool = False) -> bool:
        """按当前配置判断是否该发；是则生成一条并入库。返回是否发布。

        force=True 时无视活跃窗口与间隔（用户显式手动触发时使用），
        但仍要求 启用 + 指定人设。
        """
        cfg = load_poster_config(self._get_settings())
        if not cfg["enabled"] or not cfg["persona_id"]:
            return False
        now = datetime.now()
        if not force and not self._in_active_window(now, cfg):
            return False
        if not force and not self._interval_elapsed(now, cfg):
            return False

        persona_name = ""
        if self._persona_name_fn is not None:
            try:
                persona_name = self._persona_name_fn(cfg["persona_id"]) or ""
            except Exception as e:
                logger.warning(f"moments poster persona resolve failed: {e}")

        text = await self._compose_text(persona_name, cfg)
        if not text:
            # 生成失败：跳过本次，不写库、不推进间隔计时（下轮再试）
            return False
        self._saver({
            "author": cfg["persona_id"],
            "text": text,
            "auto": True,
        })
        self._last_posted_at = now
        logger.info(f"MomentsAutoPoster: posted auto moment for {cfg['persona_id']}")
        return True

    # ── 后台循环 ──

    async def run(self, poll_seconds: int = 60) -> None:
        """后台循环：每 poll_seconds 检查一次是否该发布（直到 stop）。"""
        self._stop = False
        try:
            while not self._stop:
                try:
                    await self.publish_once()
                except Exception as e:
                    logger.warning(f"MomentsAutoPoster loop error: {e}")
                await asyncio.sleep(poll_seconds)
        finally:
            logger.info("MomentsAutoPoster: stopped")

    def stop(self) -> None:
        self._stop = True
