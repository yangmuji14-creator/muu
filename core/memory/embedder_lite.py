"""轻量化向量嵌入器 — CPU / 低资源环境

直接继承 ``SentenceTransformerEmbedder``：模型解析、离线开关、
懒加载锁与诊断属性（model_source / init_error / dim）全部复用，
本类只负责在这之上增加：

  1. 查询结果 LRU 缓存（命中刷新顺序；带命中率统计）
  2. 流式批量嵌入（按批处理，限制内存峰值；命中缓存的不重算）
  3. 批大小：psutil 可用时按可用内存估算，否则用保守默认值

注意：本模块不做任何量化。需要更小内存请换更小的模型。
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict

from loguru import logger

from .embedder import SentenceTransformerEmbedder

_DEFAULT_BATCH = 32
_MAX_BATCH = 64


class LiteEmbedder(SentenceTransformerEmbedder):
    """轻量嵌入器：LRU 缓存 + 流式批量 + 自适应批大小"""

    def __init__(
        self,
        model_name: str | None = None,
        cache_size: int = 1024,
        batch_size: int | None = None,
    ):
        super().__init__(model_name)

        self._cache_size = max(0, cache_size)
        self._query_cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._cache_hits = 0
        self._cache_misses = 0

        self._batch_size = max(1, batch_size or self._default_batch_size())

    # ────────── 批大小 ──────────

    @staticmethod
    def _default_batch_size() -> int:
        """psutil 可用时按可用内存估算，否则用保守默认值。"""
        try:
            import psutil  # 可选依赖，不在 requirements 里

            available_mb = int(psutil.virtual_memory().available / 1024 / 1024)
            return max(8, min(_MAX_BATCH, available_mb // 128))
        except Exception:
            return _DEFAULT_BATCH

    # ────────── 缓存 ──────────

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()

    def _cache_get(self, key: str) -> list[float] | None:
        with self._cache_lock:
            vec = self._query_cache.get(key)
            if vec is not None:
                self._query_cache.move_to_end(key)  # 真正的 LRU：命中刷新顺序
                self._cache_hits += 1
                return vec
            self._cache_misses += 1
            return None

    def _cache_put(self, key: str, vec: list[float]) -> None:
        if self._cache_size <= 0:
            return
        with self._cache_lock:
            self._query_cache[key] = vec
            self._query_cache.move_to_end(key)
            while len(self._query_cache) > self._cache_size:
                self._query_cache.popitem(last=False)  # 淘汰最久未使用

    def clear_cache(self):
        with self._cache_lock:
            self._query_cache.clear()
        logger.info("LiteEmbedder query cache cleared")

    def cache_stats(self) -> dict:
        with self._cache_lock:
            total = self._cache_hits + self._cache_misses
            return {
                "size": len(self._query_cache),
                "max_size": self._cache_size,
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "hit_rate": round(self._cache_hits / total, 3) if total else 0.0,
            }

    # ────────── 嵌入 ──────────

    def embed(self, text: str) -> list[float] | None:
        if not text:
            return None

        key = self._key(text)
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        vec = super().embed(text)
        if vec is None:
            return None
        self._cache_put(key, vec)
        return vec

    def embed_batch(self, texts: list[str]) -> list[list[float]] | None:
        """批量嵌入：命中缓存的直接复用，只对未命中的文本分批发编码。"""
        if not texts:
            return []

        self._lazy_init()
        if not self._ready or self._model is None:
            return None

        results: list[list[float] | None] = [None] * len(texts)
        pending: list[tuple[int, str, str]] = []  # (index, text, cache_key)
        for idx, text in enumerate(texts):
            if not text:
                continue
            key = self._key(text)
            cached = self._cache_get(key)
            if cached is not None:
                results[idx] = cached
            else:
                pending.append((idx, text, key))

        try:
            for start in range(0, len(pending), self._batch_size):
                chunk = pending[start : start + self._batch_size]
                vecs = self._model.encode(
                    [text for _, text, _ in chunk], normalize_embeddings=True
                )
                if len(vecs) != len(chunk):
                    # 静默截断会让缺失项变成零向量，这些记忆将永远不可召回
                    logger.error(
                        f"Batch embedding returned {len(vecs)} rows for {len(chunk)} inputs"
                    )
                    return None
                for (idx, _text, key), vec in zip(chunk, vecs):
                    value = vec.tolist()
                    results[idx] = value
                    self._cache_put(key, value)
        except Exception as exc:
            logger.error(f"Batch embedding failed: {exc}")
            return None

        # 空字符串不产生向量，用零向量占位以保持与输入等长
        return [vec if vec is not None else [0.0] * self._dim for vec in results]
