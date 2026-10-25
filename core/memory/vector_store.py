"""VectorStore — SQLite 向量存储 + 余弦相似度 Top-K 搜索

结构：
  memory_vectors(user_id, memory_id, content, embedding_blob, created_at)

embedding 以 numpy float32 数组的二进制形式存入 SQLite，
检索时全量加载后用 numpy 矩阵运算算余弦相似度（500 条以内约 1-2ms）。
"""

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

import numpy as np
from loguru import logger


class VectorStore:
    """基于 SQLite 的向量存储引擎"""

    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    # ---- 连接管理 ----

    @property
    def _conn(self) -> sqlite3.Connection:
        """线程级连接"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            from core.storage.db import open_db
            self._local.conn = open_db(self._db_path)
        return self._local.conn

    def _init_db(self):
        """建表（线程安全）"""
        from core.storage.db import open_db
        with open_db(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_vectors (
                    user_id    TEXT NOT NULL,
                    memory_id  TEXT NOT NULL,
                    content    TEXT NOT NULL,
                    embedding  BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, memory_id)
                )
            """)
            conn.commit()

    # ---- 核心操作 ----

    def add(self, user_id: str, memory_id: str, content: str,
            embedding: list[float], created_at: str | None = None) -> None:
        """存入一条向量记忆"""
        blob = np.array(embedding, dtype=np.float32).tobytes()
        if created_at is None:
            created_at = datetime.now().isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO memory_vectors (user_id, memory_id, content, embedding, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, memory_id, content, blob, created_at),
        )
        self._conn.commit()

    def delete(self, user_id: str, memory_id: str) -> bool:
        """删除一条向量记忆"""
        cur = self._conn.execute(
            "DELETE FROM memory_vectors WHERE user_id=? AND memory_id=?",
            (user_id, memory_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def delete_all(self, user_id: str) -> int:
        """清空用户的所有向量记忆"""
        cur = self._conn.execute(
            "DELETE FROM memory_vectors WHERE user_id=?", (user_id,)
        )
        self._conn.commit()
        return cur.rowcount

    def count(self, user_id: str) -> int:
        """用户记忆数量"""
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM memory_vectors WHERE user_id=?", (user_id,)
        )
        return cur.fetchone()[0]

    def search(self, user_id: str, query_embedding: list[float],
               top_k: int = 5) -> list[dict]:
        """Top-K 语义搜索：余弦相似度

        Returns:
            [{memory_id, content, score, created_at}, ...]  按相似度降序
        """
        cur = self._conn.execute(
            "SELECT memory_id, content, embedding, created_at "
            "FROM memory_vectors WHERE user_id=?", (user_id,)
        )
        rows = cur.fetchall()
        if not rows:
            return []

        query_vec = np.array(query_embedding, dtype=np.float32).ravel()

        # 一次矩阵乘法算完所有相似度，而不是 Python 里逐行 np.dot。
        #
        # 原来每行都 frombuffer + reshape + dot，500 条记忆 = 500 次
        # numpy 小数组运算，每次几十微秒的固定开销全浪费在 Python 循环上。
        # 拼成一个 (n, dim) 矩阵后 `mat @ query_vec` 走 BLAS，快一个量级。
        #
        # 维度和长度不一致的历史数据（换过 embedding 模型）会让
        # reshape 抛异常，所以整段包在 try 里，失败退回逐行算法 ——
        # 慢一点但不会因为一条脏数据让检索整个挂掉。
        try:
            blobs = [row[2] for row in rows]
            mat = np.frombuffer(b"".join(blobs), dtype=np.float32)
            mat = mat.reshape(len(blobs), -1)
            if mat.shape[1] != query_vec.shape[0]:
                raise ValueError(
                    f"dim mismatch: stored {mat.shape[1]} vs query {query_vec.shape[0]}"
                )
            scores = mat @ query_vec
        except Exception as e:
            logger.warning(f"Batch cosine failed, falling back to per-row: {e}")
            scores = None

        results = []
        for i, (memory_id, content, emb_blob, created_at) in enumerate(rows):
            if scores is not None:
                score = float(scores[i])
            else:
                # 逐行回退：维度对不上的行直接跳过。
                # 换过 embedding 模型后，库里会同时存在旧维度（比如 768）
                # 和新维度（512）的向量，它们之间没有可比性 —— 强行
                # 点积只会抛异常或者算出无意义的数。跳过等于「这条暂时
                # 检索不到」，比让整个 search 崩掉或返回垃圾分数都好。
                mem_vec = np.frombuffer(emb_blob, dtype=np.float32)
                if mem_vec.shape[0] != query_vec.shape[0]:
                    logger.debug(
                        f"Skip vector [{memory_id}]: dim {mem_vec.shape[0]} "
                        f"!= query {query_vec.shape[0]}"
                    )
                    continue
                score = float(np.dot(query_vec, mem_vec))
            results.append({
                "memory_id": memory_id,
                "content": content,
                "score": round(score, 4),
                "created_at": created_at,
            })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    def close(self):
        """关闭数据库连接，清理 WAL 文件"""
        if hasattr(self._local, "conn") and self._local.conn:
            try:
                self._local.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            self._local.conn.close()
            self._local.conn = None

    def list_all(self, user_id: str) -> list[dict]:
        """列出用户的所有向量记忆（不含 embedding 数据）"""
        cur = self._conn.execute(
            "SELECT memory_id, content, created_at FROM memory_vectors WHERE user_id=? "
            "ORDER BY created_at DESC",
            (user_id,),
        )
        return [
            {"memory_id": row[0], "content": row[1], "created_at": row[2]}
            for row in cur.fetchall()
        ]

    def get_embeddings(
        self, user_id: str, memory_ids: list[str] | None = None,
    ) -> dict[str, list[float]]:
        """一次取回若干条记忆的向量（``memory_id -> list[float]``）。

        存在的原因：主对话的召回路径要用**已建好的**向量打分，而不是每轮
        把候选记忆重新 embed 一遍。``search()`` 只回内容不回想量，拿不到
        逐条打分的原始向量；这里补一个按 id 取回向量的入口。

        Args:
            user_id: 用户分区
            memory_ids: 只取这些 id；None 表示该用户全部

        Returns:
            存在的 ``memory_id`` 到向量的映射（不存在的 id 不会出现在结果里）
        """
        if memory_ids is not None and not memory_ids:
            return {}
        if memory_ids is None:
            cur = self._conn.execute(
                "SELECT memory_id, embedding FROM memory_vectors WHERE user_id=?",
                (user_id,),
            )
        else:
            placeholders = ",".join("?" * len(memory_ids))
            cur = self._conn.execute(
                f"SELECT memory_id, embedding FROM memory_vectors "
                f"WHERE user_id=? AND memory_id IN ({placeholders})",
                (user_id, *memory_ids),
            )
        out: dict[str, list[float]] = {}
        for memory_id, blob in cur.fetchall():
            vec = np.frombuffer(blob, dtype=np.float32)
            out[memory_id] = vec.tolist()
        return out
