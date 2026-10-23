"""记忆管理器 — 核心 CRUD + 智能评分 + 向量检索 + 冲突检测

集成双层评分（规则 + LLM）、结构化分类、语义向量搜索、记忆冲突检测。
嵌入器不可用时自动降级为关键词排序。
"""

import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from loguru import logger

from .models import Memory, MemoryCategory
from .scorer import MemoryScorer, LLMMemoryScorer
from .storage import MemoryStorage
from .conflict_resolver import MemoryConflictResolver
from .decay import MemoryDecaySystem

if TYPE_CHECKING:
    from .embedder import BaseEmbedder
    from .vector_store import VectorStore

# Extract meaningful tokens: 2+ char Chinese phrases, 2+ letter English words, numbers
TOKEN_RE = re.compile(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{2,}|\d+', re.UNICODE)

# 中文没有空格分词，TOKEN_RE 抓到的是「最长连续汉字串」——整句往往是一个 token，
# 于是 "查询" 与 "查询这件事的细节" 之间判定为「没有关键词重叠」，短查询的记忆
# 会被相似度阈值整条丢掉。这里对中文串再切 2-gram，让子串重叠能被识别。
_CJK_RE = re.compile(r'[\u4e00-\u9fff]+', re.UNICODE)


def _keyword_tokens(text: str) -> set[str]:
    """抽取用于「关键词重叠」判定的 token（中文补 2-gram）。"""
    tokens: set[str] = set(TOKEN_RE.findall(text or ""))
    for chunk in _CJK_RE.findall(text or ""):
        if len(chunk) < 2:
            continue
        tokens.update(chunk[i:i + 2] for i in range(len(chunk) - 1))
    return tokens


class MemoryManager:
    MIN_SEMANTIC_SIMILARITY = 0.35
    """记忆管理器

    同时管理 JSON 存储（元数据/重要度/CRUD/分类/冲突）和
    向量存储（语义嵌入/Top-K 搜索），对外提供统一接口。
    """

    def __init__(
        self,
        data_dir: str | Path,
        max_memories: int = 500,
        llm=None,
        embedder: "BaseEmbedder | None" = None,
        vector_store: "VectorStore | None" = None,
    ):
        self._storage = MemoryStorage(data_dir)
        self._scorer = MemoryScorer()
        self._llm_scorer = LLMMemoryScorer(llm)
        self._max_memories = max_memories
        self._embedder = embedder
        self._vector_store = vector_store
        self._conflict_resolver = MemoryConflictResolver()
        self._decay_system = MemoryDecaySystem()

    @property
    def data_dir(self) -> Path:
        """公开数据目录路径"""
        return self._storage.data_dir

    # ---- 增 ----

    def set_llm(self, llm) -> None:
        """延迟设置 LLM（用于首次对话时初始化）"""
        self._llm_scorer._llm = llm

    async def add_memory(
        self,
        user_id: str,
        content: str,
        level: int | None = None,
        tags: list[str] | None = None,
        category: str | None = None,
        source: str = "auto",
    ) -> Memory | None:
        """添加一条记忆（LLM 评分 + 自动分类 + 向量索引）

        Args:
            user_id: 用户 ID
            content: 记忆内容
            level: 重要度（1-5），不指定则自动评分
            tags: 标签列表
            category: 记忆分类，不指定则自动分类
            source: 来源标识

        Returns:
            创建的 Memory 对象，如果评分太低则返回 None
        """
        if level is None:
            level, _ = self._scorer.score(content)
            if self._scorer.needs_llm_evaluation(content) and self._llm_scorer._llm:
                llm_result = await self._llm_scorer.evaluate(content)
                if llm_result:
                    llm_level, llm_category = llm_result
                    level = llm_level
                    if category is None:
                        category = llm_category

        return self._add_memory_impl(user_id, content, level, category, tags, source)

    def add_memory_sync(
        self,
        user_id: str,
        content: str,
        level: int | None = None,
        tags: list[str] | None = None,
        category: str | None = None,
        source: str = "auto",
    ) -> Memory | None:
        """同步版本 add_memory（仅规则评分，不调 LLM）"""
        if level is None:
            level, _ = self._scorer.score(content)
        return self._add_memory_impl(user_id, content, level, category, tags, source)

    def _add_memory_impl(
        self,
        user_id: str,
        content: str,
        level: int,
        category: str | None,
        tags: list[str] | None,
        source: str,
    ) -> Memory | None:
        """记忆添加核心实现（同步）

        处理评分过滤、创建、冲突检测、持久化、向量索引。
        """
        if level < 2:
            logger.debug(f"Skipping low-importance memory: {content[:30]}...")
            return None

        if category is None:
            category = Memory.classify(content)

        # 置信度 = 这条记忆「有多可信」，与「有多重要」是两件事。
        #
        # 原来这里写的是 memory.confidence = level / 5.0，等于把置信度做成
        # 了重要度的镜像：level 3 永远 0.6、level 4 永远 0.8，界面上每条
        # 都显示同一个数字，信息量归零。现在直接采信内容的陈述方式
        # （明确自述 0.9 / 含糊其辞 0.4 / 普通陈述 0.7），level 由 level
        # 列自己表达，不再混进来。
        memory = Memory(
            id=f"mem_{uuid.uuid4().hex[:8]}",
            content=content,
            level=level,
            category=category,
            tags=tags or [],
            source=source,
            confidence=Memory.classify_confidence(content),
        )

        memories = self._storage.load(user_id)

        # 冲突检测（使用 MemoryConflictResolver）
        conflicts = self._conflict_resolver.detect(memory, memories)
        for conflict in conflicts:
            conflict.superseded_by = memory.id
            memory.related_memory_ids.append(conflict.id)
            logger.info(
                f"Memory conflict: '{conflict.content[:30]}' "
                f"superseded by '{memory.content[:30]}'"
            )

        memories.append(memory)

        if len(memories) > self._max_memories:
            memories = self._cleanup_old_memories(memories)
        self._storage.save(user_id, memories)

        # 向量索引
        self._index_memory(user_id, memory)

        logger.info(
            f"Added memory [{memory.id}] level={level} cat={category}: "
            f"{content[:30]}..."
        )
        return memory


    def _index_memory(self, user_id: str, memory: Memory):
        """生成嵌入并写入向量库（同步，sentence-transformers 是同步库）"""
        if not self._embedder or not self._vector_store or not self._embedder.available:
            return
        try:
            vec = self._embedder.embed(memory.content)
            if vec:
                self._vector_store.add(
                    user_id, memory.id, memory.content, vec, memory.created_at
                )
                logger.debug(f"Indexed vector for [{memory.id}]")
        except Exception as e:
            logger.debug(f"Vector indexing skipped for [{memory.id}]: {e}")

    # ---- 查 ----

    def get_memories(
        self,
        user_id: str,
        level_min: int = 1,
        level_max: int = 5,
        limit: int = 20,
        category: str | None = None,
        include_superseded: bool = False,
        min_confidence: float = 0.0,
        include_archived: bool = True,
    ) -> list[Memory]:
        """获取用户记忆，按重要度和最近访问排序

        Args:
            user_id: 用户 ID
            level_min: 最低重要度
            level_max: 最高重要度
            limit: 最大返回数
            category: 分类过滤
            include_superseded: 是否包含已被取代的
            min_confidence: 最低置信度（v1.2 新增，过滤低置信度记忆）
            include_archived: 是否包含已归档的。管理界面（`/api/memory`）要能看到
                全部，所以默认 True；**喂给模型的上下文必须传 False**
                （见 `get_context_prompt`），否则「已经忘掉的事」还会被注入 prompt。
        """
        memories = self._storage.load(user_id)

        # 应用衰减更新（检查是否需要衰减）
        self._decay_system.apply_forget_decay(user_id, memories)

        filtered = []
        for m in memories:
            if not include_superseded and m.is_superseded:
                continue
            if not include_archived and m.archived:
                continue
            if not (level_min <= m.level <= level_max):
                continue
            if category and m.category != category:
                continue
            if m.confidence < min_confidence:
                continue
            filtered.append(m)
        filtered.sort(key=lambda m: (m.level, m.last_accessed), reverse=True)
        return filtered[:limit]

    def apply_decay(self, user_id: str) -> int:
        """显式触发记忆衰减，返回被衰减影响的记忆数

        注意这里**不做归档**：归档统一由 `_cleanup_old_memories` 在记忆数
        超过上限时执行。早先这里还额外数了一遍 `is_superseded and
        forget_score >= 0.8` 的条数，但那个局部变量从来没被返回或使用，
        而 docstring 却写着「返回被归档/清理的记忆数」—— 名实不符，
        已一并删掉。
        """
        memories = self._storage.load(user_id)
        result = self._decay_system.apply_forget_decay(user_id, memories)
        # 持久化更新后的 forget_score
        for m in memories:
            self._storage.update(user_id, m)
        logger.info(f"Decay applied for {user_id}: {result} affected")
        return result

    def list_all_memories(
        self, user_id: str, offset: int = 0, limit: int = 10
    ) -> tuple[list[Memory], int]:
        """分页获取全部记忆（不含已被取代的）"""
        memories = self._storage.load(user_id)
        active = [m for m in memories if not m.is_superseded]
        active.sort(key=lambda m: (m.level, m.last_accessed), reverse=True)
        total = len(active)
        page = active[offset: offset + limit]
        return page, total

    def search_memories(
        self, user_id: str, keyword: str, limit: int = 10
    ) -> list[Memory]:
        """关键词搜索记忆（SQLite LIKE，排除已被取代的）"""
        results = self._storage.search(user_id, keyword, limit=limit)
        for m in results:
            m.touch()
            self._storage.update(user_id, m)
        return results

    def semantic_search(self, user_id: str, query: str, top_k: int = 5) -> list[dict]:
        """语义搜索记忆（向量 Top-K）"""
        if not self._embedder or not self._vector_store or not self._embedder.available:
            return []
        try:
            vec = self._embedder.embed(query)
            if not vec:
                return []
            return self._vector_store.search(user_id, vec, top_k=top_k)
        except Exception as e:
            logger.debug(f"Semantic search failed: {e}")
            return []

    def get_memory(self, user_id: str, memory_id: str) -> Memory | None:
        """获取单条记忆"""
        return self._storage.get(user_id, memory_id)

    def memory_detail(self, user_id: str, memory_id: str) -> Memory | None:
        """获取单条记忆的完整信息（遗忘分数按当前时间实时算）。

        存在的原因：`forget_score` 原本只在 `_cleanup_old_memories` 里落库，
        而那段逻辑要等记忆总数超过上限才会跑一次 —— 平时详情页读到的
        永远是初始值 0.0，看起来像「这条记忆永远不会被忘」。这里按当前
        时间重算一遍再返回，读接口不做任何写入。
        """
        memory = self._storage.get(user_id, memory_id)
        if memory is None:
            return None
        try:
            memory.forget_score = self._decay_system.calculate_forget_score(memory)
        except Exception as e:
            logger.debug(f"forget_score calc skipped for [{memory_id}]: {e}")
        return memory

    # ---- 向量维护 ----

    def embedding_status(self) -> dict:
        """嵌入器与向量库的当前状态（供诊断接口使用）。

        这是记忆系统健康度的唯一可信来源：``ready=False`` 时语义检索
        会静默降级成关键词排序，功能不崩但记忆召回质量会明显变差。
        """
        embedder = self._embedder
        ready = bool(embedder and embedder.available)
        status = {
            "ready": ready,
            "dimension": getattr(embedder, "dimension", 0) if embedder else 0,
            "model_source": getattr(embedder, "model_source", "") if embedder else "",
            "error": getattr(embedder, "init_error", None) if embedder else None,
            "indexed_by_user": {},
            "missing": 0,
        }
        if not self._vector_store:
            return status
        try:
            for user_id in self._storage.list_users():
                total = self._storage.count(user_id)
                indexed = self._vector_store.count(user_id)
                status["indexed_by_user"][user_id] = {
                    "memories": total,
                    "indexed": indexed,
                }
                status["missing"] += max(0, total - indexed)
        except Exception as e:  # 诊断接口绝不能自己抛错
            logger.debug(f"embedding_status failed: {e}")
        return status

    def reindex_all(self, user_id: str | None = None, force: bool = False) -> dict:
        """为已有记忆补建向量索引。

        历史原因：向量库上线前写入的记忆没有 embedding，旧版本的
        embedder 在无网环境下又必然加载失败，于是 ``memory_vectors``
        长期是空表，语义检索全程空转。这个方法是幂等的修复入口，
        启动时可安全调用（已索引的会跳过，除非 ``force``）。

        Args:
            user_id: 只重建某个用户；None 表示全部用户
            force:  True 时删除并重建已有向量

        Returns:
            {"users": n, "indexed": n, "skipped": n, "failed": n}
        """
        result = {"users": 0, "indexed": 0, "skipped": 0, "failed": 0}
        if not self._embedder or not self._vector_store:
            return result
        if not self._embedder.available:
            logger.debug("Reindex skipped: embedder unavailable")
            return result

        users = [user_id] if user_id else self._storage.list_users()
        for uid in users:
            if not uid:
                continue
            result["users"] += 1
            try:
                memories = self._storage.load(uid)
            except Exception as e:
                logger.warning(f"Reindex skipped for {uid}: {e}")
                result["failed"] += 1
                continue

            if force and self._vector_store:
                self._vector_store.delete_all(uid)

            existing = set() if force else self._existing_vector_ids(uid)
            pending = [m for m in memories if m.id not in existing]
            result["skipped"] += len(memories) - len(pending)
            if not pending:
                continue

            texts = [m.content for m in pending]
            vecs = self._embedder.embed_batch(texts)
            if not vecs or len(vecs) != len(pending):
                logger.warning(f"Reindex failed for {uid}: embedding batch mismatch")
                result["failed"] += len(pending)
                continue

            for mem, vec in zip(pending, vecs):
                try:
                    self._vector_store.add(uid, mem.id, mem.content, vec, mem.created_at)
                    result["indexed"] += 1
                except Exception as e:
                    logger.debug(f"Reindex insert failed for [{mem.id}]: {e}")
                    result["failed"] += 1

        if result["indexed"]:
            logger.info(
                f"Vector reindex: {result['indexed']} indexed, "
                f"{result['skipped']} skipped, {result['failed']} failed"
            )
        return result

    def _existing_vector_ids(self, user_id: str) -> set[str]:
        """一次查出已建索引的 memory_id 集合（避免逐条查询）。"""
        if not self._vector_store:
            return set()
        try:
            return {r["memory_id"] for r in self._vector_store.list_all(user_id)}
        except Exception as e:
            logger.debug(f"list_all vectors failed: {e}")
            return set()

    # ---- 删 ----

    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        """删除一条记忆（SQLite + 向量）"""
        deleted = self._storage.delete(user_id, memory_id)
        if deleted and self._vector_store:
            self._vector_store.delete(user_id, memory_id)
        if deleted:
            logger.info(f"Deleted memory {memory_id}")
        return deleted

    # ---- 改 ----

    def update_memory(
        self, user_id: str, memory_id: str, content: str | None = None,
        level: int | None = None, category: str | None = None,
    ) -> Memory | None:
        """更新一条记忆（内容变更时重新生成嵌入）"""
        memory = self._storage.get(user_id, memory_id)
        if not memory:
            return None
        if content is not None:
            memory.content = content
        if level is not None:
            memory.level = level
        if category is not None:
            memory.category = category
        memory.last_accessed = datetime.now().isoformat()
        self._storage.update(user_id, memory)
        if content is not None and self._embedder and self._vector_store:
            self._index_memory(user_id, memory)
        logger.info(f"Updated memory {memory_id}")
        return memory

    # ---- 上下文 ----

    CATEGORY_NAMES = {
        "personal": "个人信息",
        "emotion": "情感",
        "event": "事件",
        "preference": "偏好",
        "relationship": "关系",
        "opinion": "观点",
    }

    def get_context_prompt(self, user_id: str, limit: int = 8,
                           query: str | None = None) -> str:
        """生成记忆上下文 prompt

        混合评分：语义相似度 × 0.5 + 重要度 × 0.3 + 时效 × 0.2
        嵌入器不可用时降级为纯重要度排序。
        """
        candidates = self.get_memories(
            user_id, level_min=2, limit=30, include_archived=False
        )
        if not candidates:
            return ""

        if query and self._embedder and self._embedder.available:
            try:
                query_vec = self._embedder.embed(query)
                if query_vec is not None:
                    # 批量生成候选记忆的嵌入
                    candidate_texts = [m.content for m in candidates]
                    cand_vecs = self._embedder.embed_batch(candidate_texts)
                    if cand_vecs and len(cand_vecs) == len(candidates):
                        return self._hybrid_rank_prompt(
                            candidates, cand_vecs, query_vec, limit, query
                        )
            except Exception as e:
                logger.debug(f"Hybrid ranking failed, fallback to importance: {e}")

        # 降级路径：按重要度排列
        candidates.sort(key=lambda m: (m.level, m.last_accessed), reverse=True)
        return self._format_memory_prompt(candidates[:limit])

    def _hybrid_rank_prompt(
        self, candidates: list[Memory], cand_vecs: list[list[float]],
        query_vec: list[float], limit: int, query: str,
    ) -> str:
        """混合评分排序 + 去重，返回格式化 prompt"""
        now = datetime.now()
        query_np = np.array(query_vec, dtype=np.float32).reshape(1, -1)
        scored: list[tuple[float, Memory]] = []

        for mem, vec in zip(candidates, cand_vecs):
            mem_np = np.array(vec, dtype=np.float32).reshape(1, -1)
            sim = float(np.dot(query_np, mem_np.T)[0, 0])
            keyword_overlap = bool(_keyword_tokens(query) & _keyword_tokens(mem.content))
            if sim < self.MIN_SEMANTIC_SIMILARITY and not keyword_overlap:
                continue

            # 重要度归一化
            imp_norm = (mem.level - 1) / 4.0

            # 时效因子：30 天内满权重，之后逐渐衰减
            try:
                days_old = (now - datetime.fromisoformat(mem.created_at)).total_seconds() / 86400
            except (ValueError, TypeError):
                days_old = 0
            recency = max(0.2, 1.0 - days_old * 0.02)

            # 混合评分
            final = sim * 0.5 + imp_norm * 0.3 + recency * 0.2
            scored.append((final, mem))

        scored.sort(key=lambda x: x[0], reverse=True)

        # 内容级去重：跳过内容相似度过高的
        selected: list[Memory] = []
        seen_contents: set[str] = set()
        for _, mem in scored:
            # 内容指纹：取前 10 个字做去重
            fingerprint = mem.content[:10]
            if fingerprint not in seen_contents:
                seen_contents.add(fingerprint)
                selected.append(mem)
            if len(selected) >= limit:
                break

        return self._format_memory_prompt(selected)

    def _format_memory_prompt(self, memories: list[Memory]) -> str:
        """格式化记忆列表为 prompt 文本"""
        if not memories:
            return ""
        lines = ["【与当前话题相关的记忆】"]
        for m in memories:
            stars = "⭐" * m.level
            cat = self.CATEGORY_NAMES.get(m.category, "")
            cat_tag = f"[{cat}]" if cat else ""
            lines.append(f"- {stars} {cat_tag} {m.content}")
        return "\n".join(lines)

    def get_memories_by_category(
        self, user_id: str, category: str
    ) -> list[Memory]:
        """按分类获取记忆"""
        return self.get_memories(
            user_id, category=category, include_superseded=False
        )

    # ---- 导入导出 ----

    def import_memories(self, user_id: str, memories_data: list[dict]) -> int:
        """批量导入记忆（含向量索引）"""
        existing = self._storage.load(user_id)
        new_memories = [Memory.from_dict(d) for d in memories_data]
        existing.extend(new_memories)
        self._storage.save(user_id, existing)
        for m in new_memories:
            self._index_memory(user_id, m)
        logger.info(f"Imported {len(new_memories)} memories for user {user_id}")
        return len(new_memories)

    def export_memories(self, user_id: str) -> list[Memory]:
        """导出所有记忆（不含已被取代的）"""
        memories = self._storage.load(user_id)
        return [m for m in memories if not m.is_superseded]

    # ---- 内部 ----

    def _cleanup_old_memories(self, memories: list[Memory]) -> list[Memory]:
        """清理旧记忆：先归档「该忘的」，再按重要度 + 遗忘评分裁剪到上限

        两件事一起做，是因为它们都需要同一个 `forget_score`：

        1. **归档**：`MemoryDecaySystem.should_archive` 判定 —— forget_score 过阈值
           且 level < 3 的标记 `archived = True`。这个标记真正落到 `archived` 列，
           归档后不再参与 `get_context_prompt` 的召回（`include_archived=False`）。
        2. **裁剪**：超过 `max_memories` 时按 `(level, 1-forget_score, last_accessed)`
           排序保留头部。已归档、已取代的另外归堆，不占「活跃」名额。

        遗忘评分统一由 `MemoryDecaySystem.calculate_forget_score` 计算。
        这里曾经有一套**独立的** `_update_decay`
        （`days*0.01*importance_factor*recency - access/50`），与 `decay.py` 的
        （`days*base*level_mult*cat_mod - access*0.005 - 近期访问奖励`）不一致，
        结果是「详情页看到的遗忘指数」和「清理时真正用的分数」是两个不同的数，
        而且归档判定用的是 0.8 硬编码阈值、归档结果从不写进 `archived` 列。
        现在只留一套公式、一个阈值来源。
        """
        for m in memories:
            m.forget_score = self._decay_system.calculate_forget_score(m)
            # 已取代的记忆有单独的清理路径，不在这里归档
            if not m.is_superseded and self._decay_system.should_archive(m):
                self._decay_system.archive_memory(m)

        archived = [m for m in memories if m.archived]
        active = [m for m in memories if not m.archived]

        # 已取代的优先清理
        superseded = [m for m in active if m.is_superseded]
        candidates = [m for m in active if not m.is_superseded]

        target = self._max_memories
        if len(candidates) <= target:
            return candidates + superseded + archived

        # 按综合评分排序：(level, 1-forget_score, last_accessed)
        candidates.sort(
            key=lambda m: (m.level, 1.0 - m.forget_score, m.last_accessed),
            reverse=True,
        )
        kept = candidates[:target]
        removed = len(candidates) - len(kept)
        logger.info(f"Cleaned up {removed} old memories (archived {len(archived)})")
        return kept + superseded + archived
