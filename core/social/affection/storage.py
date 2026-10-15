"""UnifiedAffectionStorage — 线程安全的 SQLite 亲密度存储后端

实现 AffectionStorage 协议中定义的所有方法。支持：
- 文件模式：data/companion.db（默认）
- 内存模式：:memory:（用于测试）
- 直接传入 sqlite3.Connection（测试注入）
"""

from __future__ import annotations

import json
import sqlite3
import threading
from core.storage.db import open_db
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Union

from loguru import logger

from core.social.affection.schema import (
    AffectionRecord,
    AffectionStats,
    CREATE_TABLE_SQL,
)
from core.social.affection.constants import (
    AffectionDirection,
    AffectionLevel,
    DIRECTION_LEVEL_MAP,
    BASE_BONUS,
    AFFECTION_PEAK_DELTA,
    MIN_AFFECTION,
    MAX_AFFECTION,
)
from core.social.affection.mapper import AffectionMapper


class UnifiedAffectionStorage:
    """线程安全的 SQLite 亲密度存储后端。

    可通过三种方式初始化:
    1. unified = UnifiedAffectionStorage("data")            # 文件模式
    2. unified = UnifiedAffectionStorage(":memory:")        # 内存模式
    3. unified = UnifiedAffectionStorage(existing_conn)     # 测试注入
    """

    def __init__(
        self, data_dir_or_conn: str | Path | sqlite3.Connection = "data"
    ) -> None:
        # RLock：update/apply_decay 的异常兜底路径可能再次取锁读值，
        # 用可重入锁避免 except 分支自锁死锁（曾评审发现的挂死隐患）。
        self._lock = threading.RLock()

        if isinstance(data_dir_or_conn, sqlite3.Connection):
            # 测试注入 — 使用已存在的连接（fixture 已创建表）
            self._conn: sqlite3.Connection = data_dir_or_conn
            self._owns_conn = False
        else:
            self._owns_conn = True
            if isinstance(data_dir_or_conn, str) and data_dir_or_conn == ":memory:":
                db_path = ":memory:"
            else:
                data_dir = Path(data_dir_or_conn)
                data_dir.mkdir(parents=True, exist_ok=True)
                from core.storage.db import get_db_path
                db_path = str(get_db_path(data_dir))

            self._conn = open_db(db_path)
            self._conn.execute(CREATE_TABLE_SQL)
            self._conn.commit()

    # ── 内部辅助 ─────────────────────────────────────────────

    def _ensure_record(self, user_id: str, persona_id: str = "default") -> None:
        """如果 (user_id, persona_id) 记录不存在则创建默认记录。"""
        now = datetime.now().isoformat()
        cur = self._conn.execute(
            """INSERT OR IGNORE INTO affection
               (user_id, persona_id, level, message_count,
                positive_count, negative_count, last_interaction, created_at)
               VALUES (?, ?, 50.0, 0, 0, 0, ?, ?)""",
            (user_id, persona_id, now, now),
        )
        # 必须结束隐式事务（review 后实测踩坑）：python sqlite3 会在 INSERT 前
        # 自动 BEGIN，若 no-op（行已存在）时不收尾，连接会一直攥着写事务不放手，
        # 其它连接全部 "database is locked"——曾因此把整轮对话卡死。
        #   rowcount>0 → commit（真插入了）；no-op → rollback（无事可提交但必须关事务）
        if cur.rowcount > 0:
            self._conn.commit()
        else:
            self._conn.rollback()

    @staticmethod
    def _is_positive(direction: AffectionDirection) -> bool:
        return direction in (
            AffectionDirection.STRONG_POSITIVE,
            AffectionDirection.POSITIVE,
            AffectionDirection.SLIGHT_POSITIVE,
        )

    @staticmethod
    def _is_negative(direction: AffectionDirection) -> bool:
        return direction in (
            AffectionDirection.STRONG_NEGATIVE,
            AffectionDirection.NEGATIVE,
            AffectionDirection.SLIGHT_NEGATIVE,
        )

    @staticmethod
    def _normalize_direction_value(value: Any) -> AffectionDirection:
        """将任意输入规范化为 AffectionDirection（用于计数判定）。"""
        if isinstance(value, AffectionDirection):
            return value
        direction = AffectionMapper._parse_direction(value)
        return direction

    # ── 公开方法 (AffectionStorage 协议) ─────────────────────

    def get_level(self, user_id: str, persona_id: str = "default") -> float:
        """获取当前亲密度数值。"""
        try:
            with self._lock:
                self._ensure_record(user_id, persona_id)
                cursor = self._conn.execute(
                    "SELECT level FROM affection WHERE user_id = ? AND persona_id = ?",
                    (user_id, persona_id),
                )
                row = cursor.fetchone()
                return float(row[0]) if row else 50.0
        except Exception:
            logger.warning(f"Failed to get_level for {user_id}/{persona_id}")
            return 50.0

    def update(
        self,
        user_id: str,
        direction: str | AffectionDirection,
        level: str | AffectionLevel,
        persona_id: str = "default",
    ) -> float:
        """更新亲密度并返回新值。

        映射方向+等级 → delta，叠加 BASE_BONUS，
        更新正/负计数，裁剪到 [MIN_AFFECTION, MAX_AFFECTION]。
        """
        with self._lock:
            current_level = 50.0
            try:
                self._ensure_record(user_id, persona_id)

                # 当前亲密度：钟形曲线需要它来决定本次幅度
                cursor = self._conn.execute(
                    "SELECT level FROM affection WHERE user_id = ? AND persona_id = ?",
                    (user_id, persona_id),
                )
                row = cursor.fetchone()
                current_level = float(row[0]) if row else 50.0

                # 增量 = 峰值 × 钟形(当前亲密度) × 强度权重 × 抖动。
                # 两端限速（涨/跌对称）由钟形曲线负责，不再叠加线性边际递减。
                delta = AffectionMapper.sample_delta(direction, level, current_level)
                # BASE_BONUS 只在正向叠加（review P2-1）：
                #   - neutral（delta=0）严格保持 0 —— 否则每条中性消息稳定 +0.02 漂向 100；
                #   - 负向保持符号 —— 否则 |delta| < BASE_BONUS 时负面互动被归零，
                #     亲密度两端（<10 或 >90）将无法通过负面互动降好感。
                if delta > 0:
                    effective_delta = min(delta + BASE_BONUS, AFFECTION_PEAK_DELTA)
                else:
                    effective_delta = delta

                # 判定方向类型用于计数
                dir_enum = self._normalize_direction_value(direction)
                pos_inc = 1 if self._is_positive(dir_enum) else 0
                neg_inc = 1 if self._is_negative(dir_enum) else 0

                now = datetime.now().isoformat()

                self._conn.execute(
                    """UPDATE affection
                       SET level = MAX(MIN(level + ?, ?), ?),
                           message_count = message_count + 1,
                           positive_count = positive_count + ?,
                           negative_count = negative_count + ?,
                           last_interaction = ?
                       WHERE user_id = ? AND persona_id = ?""",
                    (effective_delta, MAX_AFFECTION, MIN_AFFECTION,
                     pos_inc, neg_inc, now, user_id, persona_id),
                )
                self._conn.commit()

                cursor = self._conn.execute(
                    "SELECT level FROM affection WHERE user_id = ? AND persona_id = ?",
                    (user_id, persona_id),
                )
                row = cursor.fetchone()
                return float(row[0]) if row else 50.0
            except Exception:
                logger.warning(f"Failed to update affection for {user_id}/{persona_id}")
                # 不再调 get_level()：它在锁内再取锁（不可重入时会死锁），
                # 直接返回本次已读到的 current_level。
                return current_level

    def get_stats(self, user_id: str, persona_id: str = "default") -> AffectionStats:
        """获取亲密度统计概览。"""
        try:
            with self._lock:
                self._ensure_record(user_id, persona_id)
                cursor = self._conn.execute(
                    """SELECT level, message_count, positive_count, negative_count, created_at
                       FROM affection WHERE user_id = ? AND persona_id = ?""",
                    (user_id, persona_id),
                )
                row = cursor.fetchone()
                if row:
                    level, msg_count, pos_count, neg_count, created_at_str = row
                    created_at = datetime.fromisoformat(created_at_str)
                    days_known = (datetime.now() - created_at).days
                    return AffectionStats(
                        level=float(level),
                        message_count=int(msg_count),
                        positive_count=int(pos_count),
                        negative_count=int(neg_count),
                        days_known=days_known,
                    )
                return AffectionStats(
                    level=50.0, message_count=0,
                    positive_count=0, negative_count=0, days_known=0,
                )
        except Exception:
            logger.warning(f"Failed to get_stats for {user_id}/{persona_id}")
            return AffectionStats(
                level=50.0, message_count=0,
                positive_count=0, negative_count=0, days_known=0,
            )

    def get_last_interaction(
        self, user_id: str, persona_id: str = "default"
    ) -> str | None:
        """获取最近一次交互时间戳（isoformat 字符串）。"""
        try:
            with self._lock:
                self._ensure_record(user_id, persona_id)
                cursor = self._conn.execute(
                    "SELECT last_interaction FROM affection WHERE user_id = ? AND persona_id = ?",
                    (user_id, persona_id),
                )
                row = cursor.fetchone()
                return str(row[0]) if row else None
        except Exception:
            logger.warning(
                f"Failed to get_last_interaction for {user_id}/{persona_id}"
            )
            return None

    def apply_decay(self, user_id: str, persona_id: str = "default") -> float:
        """应用自然衰减并返回新值。

        如果 last_interaction 超过 3 天，
        level 减少 (days_idle - 3) × 0.05，至少裁剪到 MIN_AFFECTION。
        """
        with self._lock:
            last_known: float | None = None
            try:
                self._ensure_record(user_id, persona_id)
                cursor = self._conn.execute(
                    "SELECT level, last_interaction FROM affection "
                    "WHERE user_id = ? AND persona_id = ?",
                    (user_id, persona_id),
                )
                row = cursor.fetchone()
                if not row:
                    return 50.0

                level, last_interaction_str = row
                last_known = float(level)
                last_interaction = datetime.fromisoformat(last_interaction_str)
                days_idle = (datetime.now() - last_interaction).days

                if days_idle > 3:
                    decay = (days_idle - 3) * 0.05
                    new_level = max(float(level) - decay, float(MIN_AFFECTION))
                    self._conn.execute(
                        "UPDATE affection SET level = ? "
                        "WHERE user_id = ? AND persona_id = ?",
                        (new_level, user_id, persona_id),
                    )
                    self._conn.commit()
                    return new_level

                return float(level)
            except Exception:
                logger.warning(
                    f"Failed to apply_decay for {user_id}/{persona_id}"
                )
                # 不再调 get_level()：锁内再取锁有死锁风险，返回已读值或默认值。
                return last_known if last_known is not None else 50.0

    def migrate_from_json(self, json_path: str) -> bool:
        """从 JSON 文件迁移数据。

        支持两种格式:
        - 嵌套: {user_id: {persona_id: {fields...}}}
        - 扁平: {user_id__persona_id: {fields...}} 或 {user_id: {fields...}}
        """
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)

            for key, value in data.items():
                if isinstance(value, dict):
                    # 检查是否有 level 字段 → 扁平格式
                    if "level" in value:
                        self._migrate_flat_record(key, value)
                    else:
                        # 嵌套格式: key=user_id, value={persona_id: {fields...}}
                        for persona_id, record in value.items():
                            if isinstance(record, dict):
                                self._migrate_flat_record(
                                    f"{key}__{persona_id}", record
                                )
            return True
        except Exception as e:
            logger.warning(f"Failed to migrate from JSON: {e}")
            return False

    def _migrate_flat_record(self, key: str, record: dict[str, Any]) -> None:
        """处理扁平键格式的迁移记录。

        键格式:
        - "user_id__persona_id" → 拆分 user_id 和 persona_id
        - "user_id"            → persona_id 默认为 "default"
        """
        if "__" in key:
            user_id, persona_id = key.split("__", 1)
        else:
            user_id = key
            persona_id = "default"

        now = datetime.now().isoformat()
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO affection
                   (user_id, persona_id, level, message_count,
                    positive_count, negative_count, last_interaction, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    persona_id,
                    record.get("level", 50.0),
                    record.get("message_count", 0),
                    record.get("positive_count", 0),
                    record.get("negative_count", 0),
                    record.get("last_interaction", now),
                    record.get("created_at", now),
                ),
            )
            self._conn.commit()
