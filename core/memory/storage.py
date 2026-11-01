"""记忆存储层 - SQLite 存储（替代 JSON）

线程安全（WAL 模式 + 连接隔离），支持并发读写。
自动从旧 JSON 文件迁移数据。

Schema:
  memories(
    user_id TEXT, id TEXT, content TEXT, level INT, category TEXT,
    created_at TEXT, last_accessed TEXT, access_count INT,
    tags TEXT, source TEXT, related_ids TEXT, superseded_by TEXT,
    confidence REAL, forget_score REAL, archived INT,
    PRIMARY KEY(user_id, id)
  )

confidence / forget_score / archived 三列是 v4 补的（第二十八批）：
在此之前这三项只活在 Memory 对象的默认值里，落到表里没有列，
于是「置信度」永远读回 0.5、「遗忘分数」每次算完就丢。
"""

import json
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Iterable

from loguru import logger

from .models import Memory


class MemoryStorage:
    """SQLite 存储层

    每个数据库文件存储所有用户的记忆，按 user_id 分区。
    使用 WAL 模式 + 线程级连接隔离，支持并发读写。
    """

    def __init__(self, data_dir: str | Path):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        from core.storage.db import get_db_path
        self._db_path = get_db_path(self._data_dir)
        self._local = threading.local()
        self._write_counter = 0
        self._init_db()
        self._migrate_from_json()
        self._verify_integrity()

    # ---- 连接管理 ----

    @property
    def _conn(self) -> sqlite3.Connection:
        """线程级 SQLite 连接"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            from core.storage.db import open_db
            self._local.conn = open_db(self._db_path)
        return self._local.conn

    def _init_db(self):
        """建表（线程安全）"""
        from core.storage.db import open_db
        with open_db(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    user_id        TEXT NOT NULL,
                    id             TEXT NOT NULL,
                    content        TEXT NOT NULL,
                    level          INTEGER NOT NULL DEFAULT 1,
                    category       TEXT NOT NULL DEFAULT 'other',
                    created_at     TEXT NOT NULL,
                    last_accessed  TEXT NOT NULL,
                    access_count   INTEGER NOT NULL DEFAULT 0,
                    tags           TEXT NOT NULL DEFAULT '[]',
                    source         TEXT NOT NULL DEFAULT 'auto',
                    related_ids    TEXT NOT NULL DEFAULT '[]',
                    superseded_by  TEXT NOT NULL DEFAULT '',
                    confidence     REAL NOT NULL DEFAULT 0.5,
                    forget_score   REAL NOT NULL DEFAULT 0.0,
                    archived       INTEGER NOT NULL DEFAULT 0,
                    subject        TEXT NOT NULL DEFAULT 'user',
                    PRIMARY KEY (user_id, id)
                )
            """)
            self._ensure_columns(conn)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_user
                ON memories(user_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_level
                ON memories(user_id, level DESC)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_json_migrations (
                    filename TEXT PRIMARY KEY,
                    migrated_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def _ensure_columns(self, conn: sqlite3.Connection) -> None:
        """给老库补 confidence / forget_score / archived 三列

        CREATE TABLE IF NOT EXISTS 对已存在的库是空操作，旧版本的 12 列表
        不会自己长出这三列，所以必须显式 ALTER TABLE。
        新加 confidence 列时顺带回填一遍历史行 —— 否则所有老记忆会停在
        ALTER 的默认值 0.5，界面上仍是「每条都一样」。
        """
        existing = {
            row[1] for row in conn.execute("PRAGMA table_info(memories)")
        }
        additions = (
            ("confidence", "REAL NOT NULL DEFAULT 0.5"),
            ("forget_score", "REAL NOT NULL DEFAULT 0.0"),
            ("archived", "INTEGER NOT NULL DEFAULT 0"),
            # subject：这条记忆说的是「谁」。存量全部是提取通道写的「关于他」，
            # 默认 'user' 即完成回填，无需单独脚本。
            ("subject", "TEXT NOT NULL DEFAULT 'user'"),
        )
        added: list[str] = []
        for name, decl in additions:
            if name in existing:
                continue
            try:
                conn.execute(f"ALTER TABLE memories ADD COLUMN {name} {decl}")
                added.append(name)
                logger.info(f"memories 表补列: {name}")
            except sqlite3.OperationalError as e:  # pragma: no cover - 并发建列
                logger.warning(f"补列 {name} 失败: {e}")
        if "confidence" in added:
            self._backfill_confidence(conn)

    def _backfill_confidence(self, conn: sqlite3.Connection) -> None:
        """给历史记忆回填置信度（按内容陈述方式，不含重要度）"""
        rows = list(conn.execute("SELECT id, content FROM memories"))
        if not rows:
            return
        filled = 0
        for mem_id, content in rows:
            try:
                score = Memory.classify_confidence(content or "")
            except Exception:
                continue
            conn.execute(
                "UPDATE memories SET confidence=? WHERE id=?", (round(score, 4), mem_id)
            )
            filled += 1
        logger.info(f"memories 回填置信度: {filled} 条")

    # ---- JSON 迁移 ----

    def _migrate_from_json(self):
        """从旧的 JSON 文件迁移数据（仅首次运行）"""
        json_dir = self._data_dir / "memories"
        if not json_dir.exists():
            return
        # 检查是否有任何 JSON 文件需要迁移
        json_files = list(json_dir.glob("*.json"))
        if not json_files:
            return
        conn = self._conn
        # Resume file-by-file migrations interrupted after earlier files committed.
        markers = conn.execute(
            "SELECT COUNT(*) FROM memory_json_migrations"
        ).fetchone()[0]
        cur = conn.execute("SELECT COUNT(*) FROM memories")
        if cur.fetchone()[0] > 0 and markers == 0:
            logger.info("SQLite 已有数据，跳过 JSON 迁移")
            return
        migrated = 0
        for json_file in json_files:
            user_id = json_file.stem
            marker = conn.execute(
                "SELECT 1 FROM memory_json_migrations WHERE filename=?",
                (json_file.name,),
            ).fetchone()
            if marker:
                self._rename_migrated_json(json_file)
                continue
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                memories = data.get("memories", [])
                conn.execute("BEGIN IMMEDIATE")
                for mem in memories:
                    self._insert(Memory.from_dict(mem), user_id)
                conn.execute(
                    "INSERT INTO memory_json_migrations (filename, migrated_at) "
                    "VALUES (?, ?)",
                    (json_file.name, datetime.now().isoformat()),
                )
                conn.commit()
                migrated += len(memories)
                self._rename_migrated_json(json_file)
            except Exception as e:
                conn.rollback()
                logger.warning(f"迁移 {json_file.name} 失败: {e}")
        if migrated:
            logger.info(f"从 JSON 迁移了 {migrated} 条记忆到 SQLite")

    @staticmethod
    def _rename_migrated_json(json_file: Path) -> None:
        migrated_file = json_file.with_suffix(".json.migrated")
        if json_file.exists() and not migrated_file.exists():
            try:
                json_file.rename(migrated_file)
            except OSError as e:
                logger.warning(f"迁移数据已提交，但无法重命名 {json_file.name}: {e}")

    def _insert(self, memory: Memory, user_id: str | None = None):
        """插入一条记忆到数据库"""
        uid = user_id or "default"
        self._conn.execute(
            """INSERT OR REPLACE INTO memories
               (user_id, id, content, level, category, created_at,
                last_accessed, access_count, tags, source, related_ids, superseded_by,
                confidence, forget_score, archived, subject)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                uid, memory.id, memory.content, memory.level,
                memory.category, memory.created_at, memory.last_accessed,
                memory.access_count, json.dumps(memory.tags, ensure_ascii=False),
                memory.source, json.dumps(memory.related_memory_ids),
                memory.superseded_by,
                float(memory.confidence), float(memory.forget_score),
                1 if memory.archived else 0,
                getattr(memory, "subject", "user") or "user",
            ),
        )

    # ---- CRUD ----

    def load(self, user_id: str) -> list[Memory]:
        """加载用户的所有记忆"""
        cur = self._conn.execute(
            "SELECT * FROM memories WHERE user_id=? ORDER BY created_at DESC",
            (user_id,),
        )
        return [self._row_to_memory(row) for row in cur.fetchall()]

    def save(self, user_id: str, memories: list[Memory]) -> None:
        """保存用户的所有记忆（全量替换，事务内原子执行）"""
        conn = self._conn
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM memories WHERE user_id=?", (user_id,))
            for mem in memories:
                self._insert(mem, user_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def add(self, user_id: str, memory: Memory) -> None:
        """添加单条记忆"""
        self._insert(memory, user_id)
        self._conn.commit()
        self._maybe_checkpoint()

    def _maybe_checkpoint(self):
        """每 100 次写入触发一次 WAL 检点，防止 WAL 文件无限增长"""
        self._write_counter += 1
        if self._write_counter % 100 == 0:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except Exception:
                pass

    def _verify_integrity(self):
        """数据库完整性检查（启动时运行）"""
        try:
            result = self._conn.execute("PRAGMA integrity_check").fetchone()
            if result and result[0] != "ok":
                logger.warning(f"DB integrity check: {result[0]}")
        except Exception as e:
            logger.warning(f"DB integrity check failed: {e}")

    def update(self, user_id: str, memory: Memory) -> None:
        """更新单条记忆"""
        self._insert(memory, user_id)
        self._conn.commit()

    def update_many(
        self, user_id: str, memories: list[Memory],
        columns: Iterable[str] | None = None,
    ) -> int:
        """批量更新记忆（单事务）。

        存在的原因：遗忘衰减需要把一批记忆的新 `forget_score` 一起写回，
        逐条 `update()` 会做 N 次 commit；500 条记忆在 WAL 模式下等于 500 次
        落盘。这里合到一个事务里，返回实际写入的条数。

        Args:
            columns: 只更新这些列（``None`` 表示整行 upsert）。

        为什么要能限定列：``_insert`` 是 ``INSERT OR REPLACE`` 整行覆盖，
        而调用方拿到的 ``Memory`` 对象可能来自几十毫秒前的 ``load()``。
        这期间别的线程可能刚把 ``superseded_by`` / ``archived`` / ``access_count``
        写进库，整行覆盖会把这些更新悄悄回滚（lost update）——
        典型症状是「刚被取代的记忆又冒出来」「访问计数归零」。
        读路径（``get_memories`` 落衰减）和清理路径都必须只写自己改过的列。
        """
        if not memories:
            return 0
        conn = self._conn
        try:
            conn.execute("BEGIN IMMEDIATE")
            for mem in memories:
                if columns is None:
                    self._insert(mem, user_id)
                else:
                    self._update_columns(mem, user_id, columns)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return len(memories)

    def _update_columns(
        self, memory: Memory, user_id: str, columns: Iterable[str],
    ) -> None:
        """按列部分更新（列名由调用方以常量给出，不来自外部输入）"""
        assignments: list[str] = []
        values: list = []
        for column in columns:
            assignments.append(f"{column}=?")
            if column == "tags":
                values.append(json.dumps(memory.tags, ensure_ascii=False))
            elif column == "related_ids":
                values.append(json.dumps(memory.related_memory_ids))
            elif column == "archived":
                values.append(1 if memory.archived else 0)
            elif column in ("confidence", "forget_score"):
                values.append(float(getattr(memory, column)))
            else:
                values.append(getattr(memory, column))
        values.extend([user_id, memory.id])
        self._conn.execute(
            f"UPDATE memories SET {', '.join(assignments)} WHERE user_id=? AND id=?",
            values,
        )

    def delete(self, user_id: str, memory_id: str) -> bool:
        """删除一条记忆"""
        cur = self._conn.execute(
            "DELETE FROM memories WHERE user_id=? AND id=?",
            (user_id, memory_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get(self, user_id: str, memory_id: str) -> Memory | None:
        """获取单条记忆"""
        cur = self._conn.execute(
            "SELECT * FROM memories WHERE user_id=? AND id=?",
            (user_id, memory_id),
        )
        row = cur.fetchone()
        return self._row_to_memory(row) if row else None

    def search(self, user_id: str, keyword: str, limit: int = 20) -> list[Memory]:
        """关键词搜索记忆（LIKE 模糊匹配）"""
        cur = self._conn.execute(
            "SELECT * FROM memories WHERE user_id=? AND content LIKE ? "
            "ORDER BY level DESC, last_accessed DESC LIMIT ?",
            (user_id, f"%{keyword}%", limit),
        )
        return [self._row_to_memory(row) for row in cur.fetchall()]

    def delete_all(self, user_id: str) -> bool:
        """删除用户所有记忆"""
        cur = self._conn.execute(
            "DELETE FROM memories WHERE user_id=?", (user_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def count(self, user_id: str) -> int:
        """用户记忆数量"""
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM memories WHERE user_id=?", (user_id,)
        )
        return cur.fetchone()[0]

    def list_users(self) -> list[str]:
        """列出所有有记忆的用户"""
        cur = self._conn.execute(
            "SELECT DISTINCT user_id FROM memories"
        )
        return [row[0] for row in cur.fetchall()]

    def get_high_importance(self, user_id: str, min_level: int = 3, limit: int = 30) -> list[Memory]:
        """获取高重要度记忆"""
        cur = self._conn.execute(
            "SELECT * FROM memories WHERE user_id=? AND level>=? "
            "ORDER BY level DESC, last_accessed DESC LIMIT ?",
            (user_id, min_level, limit),
        )
        return [self._row_to_memory(row) for row in cur.fetchall()]

    def get_recent(self, user_id: str, limit: int = 20) -> list[Memory]:
        """获取最近记忆"""
        cur = self._conn.execute(
            "SELECT * FROM memories WHERE user_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        )
        return [self._row_to_memory(row) for row in cur.fetchall()]

    # ---- 工具方法 ----

    @staticmethod
    def _row_to_memory(row: sqlite3.Row) -> Memory:
        """将 SQLite 行转换为 Memory 对象"""
        keys = row.keys()

        def _opt(name, default):
            return row[name] if name in keys else default

        return Memory(
            id=row["id"],
            content=row["content"],
            level=row["level"],
            category=row["category"],
            created_at=row["created_at"],
            last_accessed=row["last_accessed"],
            access_count=row["access_count"],
            tags=json.loads(row["tags"]) if isinstance(row["tags"], str) else row["tags"] or [],
            source=row["source"],
            related_memory_ids=json.loads(row["related_ids"]) if isinstance(row["related_ids"], str) else [],
            superseded_by=row["superseded_by"] or "",
            confidence=float(_opt("confidence", 0.5) or 0.5),
            forget_score=float(_opt("forget_score", 0.0) or 0.0),
            archived=bool(_opt("archived", 0)),
            subject=str(_opt("subject", "user") or "user"),
        )

    def close(self):
        """关闭数据库连接，清理 WAL 文件"""
        if hasattr(self._local, "conn") and self._local.conn:
            try:
                self._local.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            try:
                self._local.conn.close()
            except Exception:
                pass
            self._local.conn = None

    @property
    def data_dir(self) -> Path:
        """Directory containing the consolidated application database."""
        return self._data_dir

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
