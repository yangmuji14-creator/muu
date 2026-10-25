"""记忆管理器 — 核心 CRUD + 智能评分 + 向量检索 + 冲突检测

集成双层评分（规则 + LLM）、结构化分类、语义向量搜索、记忆冲突检测。
嵌入器不可用时自动降级为关键词排序。
"""

import re
import threading
import time
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
    """记忆管理器

    同时管理 JSON 存储（元数据/重要度/CRUD/分类/冲突）和
    向量存储（语义嵌入/Top-K 搜索），对外提供统一接口。
    """

    MIN_SEMANTIC_SIMILARITY = 0.35
    """绝对下限：低于这个相似度且没有关键词重叠的候选直接丢弃。

    这个值不能单独当闸门用 —— 实测（`tools/probe_gate_noise.py`）在
    23 条日常记忆 × 10 个闲聊查询下，0.35 的过闸率是 **53%、平均每条
    查询放进 12.2 条记忆**，等于没有闸门：bge-small-zh 把「今天下雨了」
    和「我小时候在南方长大」算到 0.60。真正的闸门见
    ``RELATIVE_SIMILARITY_RATIO``。
    """

    RELATIVE_SIMILARITY_RATIO = 0.9
    """相对闸门：候选相似度还要达到「最佳候选 × 0.9」才保留。

    为什么需要相对闸门（`tools/calibrate_relative_gate.py` 实测）：
    闲聊查询与相关查询的相似度分布是重叠的（闲聊 p99=0.541，相关 p10=0.378），
    任何单一绝对阈值都只能在「漏掉弱相关」和「灌入闲聊噪声」之间二选一：

    ==========  ==========  ============  ============
    闸门         召回率      闲聊噪声       陪跑噪声
    ==========  ==========  ============  ============
    绝对 0.35    100%        7.60 条       5.20 条
    绝对 0.45     90%        2.10 条       1.80 条
    相对 0.90     90%        1.90 条       0.30 条
    ==========  ==========  ============  ============

    相对闸门在同等召回率下把「有强匹配时还拖进多少无关记忆」（陪跑噪声）
    从 1.80 条降到 0.30 条。原理：记忆检索的典型形态是「一条明显最相关
    + 若干勉强沾边」，绝对阈值分不清「勉强沾边」和「闲聊噪声」，而
    「离最佳候选多远」能分清。
    """

    DECAY_FLUSH_INTERVAL = 300.0
    """衰减值写回数据库的最小间隔（秒）。

    `get_memories` 每轮对话都会调，衰减值一天才变一点点；每次请求都
    重写全部记忆行既浪费 IO 又会无谓地刷新 `updated_at`。这里按用户节流，
    5 分钟最多落一次盘。`apply_decay()` 是显式调用，不受节流限制。
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

        # 遗忘衰减的落库节流：user_id -> 上次把 forget_score 写回 DB 的
        # monotonic 时间。`get_memories` 每轮对话都会调（记忆上下文、
        # 触发器、主动消息），衰减值一天只变一点点，没必要每次都写库。
        self._decay_flushed_at: dict[str, float] = {}
        self._decay_lock = threading.Lock()

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

        # 只落库真正变化的那几行，不再全量重写。
        #
        # 原来这里是 `self._storage.save(user_id, memories)` —— 一次
        # DELETE 整表 + 重新插入所有记忆。500 条记忆时每加一条要写 501 行，
        # 而实际只有 1 条新增 + 至多几条被取代 + 至多几条被裁剪/归档。
        # 更糟的是 `save` 的 DELETE 会把 `access_count`、`forget_score`
        # 这类「别处刚写进去的」列一起冲掉（全量重写依赖内存对象是全的）。
        #
        # 现在拆成四个精确动作：新增一条、更新被取代的、更新被清理改过的、
        # 删除被裁剪的。
        self._storage.add(user_id, memory)

        if len(memories) > self._max_memories:
            # 必须把 user_id 传进去：裁剪掉的记忆若不同步删向量，就会在
            # memory_vectors 里留下孤儿 —— 语义检索仍能召回「已经不存在的
            # 记忆」，而 get_memories 看不到它，属于用户可感知的错乱。
            #
            # 清理会就地改 forget_score / archived，所以要先拍快照，
            # 之后只把真正变了的那几条写回（而不是整个 kept 列表）。
            snapshot = {m.id: (m.forget_score, m.archived) for m in memories}
            kept = self._cleanup_old_memories(memories, user_id=user_id)
            kept_ids = {m.id for m in kept}
            dropped = [m for m in memories if m.id not in kept_ids]
            dirty = [
                m for m in kept
                if (m.forget_score, m.archived) != snapshot.get(m.id)
            ]
            if dirty:
                self._storage.update_many(user_id, dirty)
            for m in dropped:
                self._storage.delete(user_id, m.id)
            logger.debug(
                f"Trimmed {len(dropped)} memories, {len(dirty)} archived"
            )

        # 冲突标记落库：被取代的那条必须马上写，否则重启后
        # superseded_by 丢失，两条矛盾记忆会同时被召回。
        for conflict in conflicts:
            self._storage.update(user_id, conflict)

        # 向量索引
        self._index_memory(user_id, memory)

        logger.info(
            f"Added memory [{memory.id}] level={level} cat={category}: "
            f"{content[:30]}..."
        )
        return memory


    def _index_memory(self, user_id: str, memory: Memory):
        """生成嵌入并写入向量库（同步，sentence-transformers 是同步库）

        失败必须让运维看得见：早先这里是 `logger.debug`，而 debug 默认不
        输出，于是「向量索引一直失败」这件事在日志里完全不存在 ——
        `memory_vectors` 悄悄空着，语义检索退化成重要度排序，没人知道。

        但也不能每失败一次就刷一条 warning：批量导入 500 条记忆会刷 500 行。
        所以每个进程只完整告警一次（`self._index_warned`），后续降到 debug。
        """
        if not self._embedder or not self._vector_store:
            return
        if not self._embedder.available:
            if not getattr(self, "_index_warned", False):
                self._index_warned = True
                logger.warning(
                    "Vector indexing disabled: embedder unavailable — "
                    "semantic recall will fall back to importance ordering"
                )
            return
        try:
            vec = self._embedder.embed(memory.content)
            if vec:
                self._vector_store.add(
                    user_id, memory.id, memory.content, vec, memory.created_at
                )
                logger.debug(f"Indexed vector for [{memory.id}]")
        except Exception as e:
            if not getattr(self, "_index_warned", False):
                self._index_warned = True
                logger.warning(
                    f"Vector indexing failed for [{memory.id}]: {e} — "
                    "memory will not be semantically searchable "
                    "(further failures logged at debug level)"
                )
            else:
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

        # 应用衰减更新（检查是否需要衰减），并把结果落库。
        #
        # 之前这里只改内存里的对象、不写回数据库：`get_memories` 拿到的
        # `forget_score` 永远是上一次 `apply_decay()` 或创建时的旧值，
        # 「记忆在慢慢遗忘」这件事在持久层完全不可见——管理界面看到的
        # 遗忘分、`should_archive` 依赖的阈值判断都建立在陈旧数据上。
        self._decay_system.apply_forget_decay(user_id, memories)
        self._flush_decay(user_id, memories)

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

    def _flush_decay(
        self, user_id: str, memories: list[Memory], force: bool = False
    ) -> int:
        """把衰减后的 `forget_score` 写回数据库（按用户节流）

        Args:
            user_id: 用户 ID
            memories: 已经过 `apply_forget_decay` 原地更新的记忆列表
            force: 忽略节流，立即写库（显式 `apply_decay()` 用）

        Returns:
            实际写库的记忆条数（被节流跳过时为 0）
        """
        now = time.monotonic()
        with self._decay_lock:
            last = self._decay_flushed_at.get(user_id)
            if not force and last is not None and now - last < self.DECAY_FLUSH_INTERVAL:
                return 0
            self._decay_flushed_at[user_id] = now

        changed = [m for m in memories if not m.archived and not m.is_superseded]
        if not changed:
            return 0
        try:
            written = self._storage.update_many(user_id, changed)
        except Exception as e:
            # 衰减落库失败不该让整轮对话挂掉：内存里的值仍然是对的，
            # 下一轮会再试一次。
            logger.warning(f"Failed to persist forget_score for {user_id}: {e}")
            return 0
        logger.debug(f"Persisted forget_score for {written} memories of {user_id}")
        return written

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
        # 显式调用不受节流限制：调用方要的就是「立刻落盘」。
        self._flush_decay(user_id, memories, force=True)
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
        """语义搜索记忆（向量 Top-K）

        结果会过滤掉**已被取代**和**已归档**的记忆 —— `memory_vectors` 表里
        没有这两个状态列，只按向量相似度返回会把「我不喜欢喝咖啡了」和它
        取代掉的「我喜欢喝咖啡」一起交给调用方，用户看到的是自相矛盾的记忆。

        历史问题：这里以前直接返回 `vector_store.search()` 的原始结果，
        `/api/memory/search` 因此能把已删除/已作废的内容召回。过滤需要
        多取一些候选，否则 top_k 会被过滤后不足数。
        """
        if not self._embedder or not self._vector_store or not self._embedder.available:
            return []
        try:
            vec = self._embedder.embed(query)
            if not vec:
                return []
            # 多取候选：过滤后仍要凑够 top_k。上限 4 倍够用 —— 作废记忆
            # 通常只占少数，真占多数时给不满 top_k 也比返回作废内容正确。
            raw = self._vector_store.search(user_id, vec, top_k=max(top_k * 4, 20))
        except Exception as e:
            logger.debug(f"Semantic search failed: {e}")
            return []
        return self._filter_searchable(user_id, raw, top_k)

    def _filter_searchable(
        self, user_id: str, hits: list[dict], top_k: int,
    ) -> list[dict]:
        """按 ``memories`` 表的作废/归档状态过滤向量检索结果。

        向量表存的是写入那一刻的快照，状态变更（冲突取代、归档、删除）
        只反映在 ``memories`` 表里，所以过滤必须回查主表。
        主表里已经不存在的 id 也一并丢掉 —— 那是孤儿向量，不该被召回。
        """
        if not hits:
            return []
        try:
            alive = {
                m.id: m for m in self._storage.load(user_id)
            }
        except Exception as e:
            # 查不到状态时宁可不返回：返回作废记忆比返回空更糟。
            logger.warning(f"semantic_search state lookup failed for {user_id}: {e}")
            return []
        out: list[dict] = []
        for hit in hits:
            mem = alive.get(hit["memory_id"])
            if mem is None or mem.is_superseded or mem.archived:
                continue
            out.append(hit)
            if len(out) >= top_k:
                break
        return out

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

        ``missing`` / ``orphaned`` 是两个**不同**的错误方向，必须分开报：

        * ``missing``  —— 有记忆但没向量。语义检索会漏掉这些记忆。
        * ``orphaned`` —— 有向量但记忆已不存在。语义检索会召回死内容。

        历史问题：这里以前只有一句 ``status["missing"] += max(0, total - indexed)``，
        孤儿向量让 ``indexed > total`` 时差值被 ``max(0, …)`` 吃掉，于是
        「3 条记忆 8 条向量」被报成 ``missing=0``，覆盖率看起来永远是 100%，
        ``core/runtime/diagnostics.py`` 的健康检查因此从不告警。
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
            "orphaned": 0,
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
                if indexed < total:
                    status["missing"] += total - indexed
                elif indexed > total:
                    status["orphaned"] += indexed - total
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
            {"users": n, "indexed": n, "skipped": n, "failed": n, "pruned": n}

        ``pruned`` 是本次清掉的孤儿向量数（向量存在但对应记忆已不存在）。
        ``force=False`` 时也会 prune —— 孤儿是「错误状态」，不是「待补的索引」，
        没有理由等一次强制重建才收拾。早先这里只管补索引不管清孤儿，于是
        ``memory_vectors`` 一旦长出孤儿行（记忆被裁掉/清空但向量没删）就永久留着，
        语义检索会持续召回已经不存在的记忆。
        """
        result = {"users": 0, "indexed": 0, "skipped": 0, "failed": 0, "pruned": 0}
        if not self._embedder or not self._vector_store:
            return result
        if not self._embedder.available:
            # 这条以前是 debug：整个向量库建不起来，日志里却一个字都没有，
            # 只有翻 `embedding_status()` 才看得出 missing 等于全部。
            logger.warning(
                "Reindex skipped: embedder unavailable — "
                "semantic recall is degraded to importance ordering"
            )
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
            # 孤儿清理：向量 id 不在当前记忆集合里 → 删掉
            if existing:
                alive_ids = {m.id for m in memories}
                orphans = existing - alive_ids
                for orphan_id in orphans:
                    try:
                        if self._vector_store.delete(uid, orphan_id):
                            result["pruned"] += 1
                    except Exception as e:
                        logger.warning(f"Orphan vector delete failed for [{orphan_id}]: {e}")
                existing = existing & alive_ids

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
                    logger.warning(f"Reindex insert failed for [{mem.id}]: {e}")
                    result["failed"] += 1

        if result["indexed"] or result["pruned"]:
            logger.info(
                f"Vector reindex: {result['indexed']} indexed, "
                f"{result['skipped']} skipped, {result['failed']} failed, "
                f"{result['pruned']} orphans pruned"
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

    def clear_memories(self, user_id: str) -> int:
        """清空一个用户的全部记忆（SQLite + 向量），返回清掉的记忆条数。

        存在的唯一理由：`/memories clear` 曾经自己 new 一个 `MemoryStorage`
        直接 `delete_all()`，既绕过 `MemoryManager`、也不碰 `memory_vectors` ——
        用户主动清空记忆之后，`semantic_search` 仍能把那些「已删除」的内容
        召回进 prompt。所有「整用户级」的删除都必须走这里。
        """
        removed = self._storage.count(user_id)
        self._storage.delete_all(user_id)
        if self._vector_store:
            try:
                self._vector_store.delete_all(user_id)
            except Exception as e:
                # 向量清空失败要让调用方知道，否则又是「删了但还能召回」
                logger.warning(f"Vector clear failed for {user_id}: {e}")
        logger.info(f"Cleared {removed} memories for {user_id}")
        return removed

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

        向量来源优先级（第四批修复）：

        1. **先查 ``memory_vectors`` 表** —— 写入时已经算好并归一化的向量，
           一次 embed(query) + 一次全表点积，200 条记忆约 9ms。
        2. 向量表里缺这条记忆（老数据没回填、索引失败）时才回退到
           「现算候选向量」的老路径。

        历史问题：这里以前只有第 2 条路径，每轮对话把 30 条候选记忆全部
        重新 embed 一遍（200 条记忆规模下 147ms，其中 140ms 是纯浪费），
        ``memory_vectors`` 表只有管理界面的 ``semantic_search`` 在读 ——
        用户写入的向量索引在主对话里从未被使用过。
        """
        candidates = self.get_memories(
            user_id, level_min=2, limit=30, include_archived=False
        )
        if not candidates:
            return ""

        if query and self._embedder and self._embedder.available:
            # 路径 1：读已建好的向量索引
            indexed = self._rank_from_vector_store(user_id, candidates, query, limit)
            if indexed is not None:
                return indexed

            # 路径 2：向量表没覆盖到，退回现算
            try:
                query_vec = self._embedder.embed(query)
                if query_vec is not None:
                    candidate_texts = [m.content for m in candidates]
                    cand_vecs = self._embedder.embed_batch(candidate_texts)
                    if cand_vecs and len(cand_vecs) == len(candidates):
                        return self._hybrid_rank_prompt(
                            candidates, cand_vecs, query_vec, limit, query,
                            user_id=user_id,
                        )
            except Exception as e:
                # 降级到重要度排序意味着「这轮记忆召回与话题无关」，
                # 是用户能感觉到的体验下降，值得一条 warning。
                logger.warning(
                    f"Hybrid ranking failed, falling back to importance "
                    f"ordering: {e}"
                )

        # 降级路径：按重要度排列
        candidates.sort(key=lambda m: (m.level, m.last_accessed), reverse=True)
        return self._format_memory_prompt(candidates[:limit])

    def _rank_from_vector_store(
        self, user_id: str, candidates: list[Memory], query: str, limit: int,
    ) -> str | None:
        """用 ``memory_vectors`` 里已存的向量给候选记忆打分并排序。

        Returns:
            排好序的 prompt 文本；**向量表覆盖不全时返回 None**，
            让调用方回退到现算路径（宁可慢，也不能漏掉没索引的记忆）。

        覆盖率要求 100%：只要有一条候选记忆没有向量，就走回退路径。
        原因是一旦混用「索引向量」和「现算向量」两套来源，排序结果会
        取决于索引新旧，排查起来极其困难。缺索引本身是 ``reindex_all``
        该修的状态，不该由召回路径偷偷兜住。
        """
        if not self._vector_store:
            return None
        try:
            indexed = self._vector_store.list_all(user_id)
        except Exception as e:
            logger.debug(f"vector list_all failed, fallback to live embed: {e}")
            return None
        if not indexed:
            return None

        cand_ids = {m.id for m in candidates}
        vec_by_id = {row["memory_id"]: row for row in indexed}
        if not cand_ids <= set(vec_by_id):
            # 索引不全 = 语义召回退化 + 每轮多付一次重 embed 的成本。
            # 这是可自愈的状态（reindex_all 会补），所以不报 warning，
            # 但一个进程里至少要说一次，否则「为什么这么慢」无从查起。
            if not getattr(self, "_incomplete_index_warned", False):
                self._incomplete_index_warned = True
                logger.info(
                    "Vector index incomplete for %s (%d/%d candidates indexed) — "
                    "falling back to live embedding; run reindex_all() to fix",
                    user_id, len(cand_ids & set(vec_by_id)), len(cand_ids),
                )
            else:
                logger.debug(
                    "Vector index incomplete for %s (%d/%d candidates indexed), "
                    "falling back to live embedding",
                    user_id, len(cand_ids & set(vec_by_id)), len(cand_ids),
                )
            return None

        try:
            query_vec = self._embedder.embed(query)
        except Exception as e:
            logger.debug(f"query embed failed: {e}")
            return None
        if not query_vec:
            return None

        # 从表里取回每个候选的向量，顺序与 candidates 对齐
        try:
            stored = self._vector_store.get_embeddings(user_id, list(cand_ids))
        except Exception as e:
            logger.debug(f"vector get_embeddings failed, fallback to live embed: {e}")
            return None
        if not stored or not cand_ids <= set(stored):
            return None

        ordered_vecs = [stored[m.id] for m in candidates]
        return self._hybrid_rank_prompt(
            candidates, ordered_vecs, query_vec, limit, query, user_id=user_id,
        )

    def _hybrid_rank_prompt(
        self, candidates: list[Memory], cand_vecs: list[list[float]],
        query_vec: list[float], limit: int, query: str,
        user_id: str | None = None,
    ) -> str:
        """混合评分排序 + 去重，返回格式化 prompt

        ``user_id`` 只用于把「真正进了 prompt 的记忆」的访问计数落库；
        不传则跳过计数（测试直接调这个方法时不必关心存储层）。
        """
        now = datetime.now()
        query_np = np.array(query_vec, dtype=np.float32).reshape(1, -1)
        scored: list[tuple[float, float, Memory]] = []

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
            scored.append((final, sim, mem))

        selected = self._select_by_gate(scored, limit, query)
        if user_id:
            self._touch_selected(user_id, selected)
        return self._format_memory_prompt(selected)

    def _select_by_gate(
        self, scored: list[tuple[float, float, Memory]], limit: int, query: str,
    ) -> list[Memory]:
        """相对闸门 + 内容去重，选出最终注入 prompt 的记忆。

        ``scored`` 的每项是 ``(混合分, 语义相似度, 记忆)``。

        闸门分两步（顺序不能反）：

        1. **绝对下限** ``MIN_SEMANTIC_SIMILARITY``：纯噪声直接丢。
        2. **相对闸门** ``RELATIVE_SIMILARITY_RATIO``：语义相似度低于
           「最佳候选的相似度 × 0.9」的丢掉。这一步才是真正压噪声的 ——
           有强匹配时，勉强沾边的候选会被挡在门外。

        闸门比的是**相似度**而不是混合分。混合分里含重要度（权重 0.3）
        和时效（权重 0.2），拿它做相对比较会让一条 level=5 的旧记忆
        仅凭重要度就挤进 prompt —— 那正是噪声。重要度只该影响
        「在已经通过语义闸门的候选里排第几」，不该影响「能不能进来」。

        关键词重叠的候选不受相对闸门约束：字面命中说明用户明确提到了这件事，
        哪怕语义分不高也该保留。
        """
        if not scored:
            return []
        scored = sorted(scored, key=lambda x: x[0], reverse=True)
        top_sim = max(sim for _, sim, _ in scored)
        relative_cut = top_sim * self.RELATIVE_SIMILARITY_RATIO
        query_tokens = _keyword_tokens(query)

        selected: list[Memory] = []
        seen_contents: set[str] = set()
        for _final, sim, mem in scored:
            if sim < relative_cut and not (query_tokens & _keyword_tokens(mem.content)):
                continue
            # 内容指纹：取前 10 个字做去重
            fingerprint = mem.content[:10]
            if fingerprint in seen_contents:
                continue
            seen_contents.add(fingerprint)
            selected.append(mem)
            if len(selected) >= limit:
                break
        return selected

    def _touch_selected(self, user_id: str, memories: list[Memory]) -> None:
        """给真正被注入 prompt 的记忆记一次访问。

        历史缺陷：`touch()` 只在 `search()`（关键词搜索）里被调用，语义召回
        从不计数，于是 `access_count` 恒为 0 —— 衰减公式里
        「高访问频率衰减慢」（``access_count * 0.005``）和
        ``get_retrieval_weight`` 的 24h 新鲜项永远拿不到数据。

        只记真正进了 prompt 的，不记候选池：候选池每轮 30 条全算访问，
        等于把「被想起」和「被扫过一眼」混为一谈。
        """
        if not memories:
            return
        for mem in memories:
            mem.touch()
        try:
            self._storage.update_many(user_id, memories)
        except Exception as e:
            # 计数失败不该让整轮对话挂掉
            logger.warning(f"Failed to persist access_count for {user_id}: {e}")

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

    def _cleanup_old_memories(
        self, memories: list[Memory], user_id: str | None = None,
    ) -> list[Memory]:
        """清理旧记忆：先归档「该忘的」，再按重要度 + 遗忘评分裁剪到上限

        两件事一起做，是因为它们都需要同一个 `forget_score`：

        1. **归档**：`MemoryDecaySystem.should_archive` 判定 —— forget_score 过阈值
           且 level < 3 的标记 `archived = True`。这个标记真正落到 `archived` 列，
           归档后不再参与 `get_context_prompt` 的召回（`include_archived=False`）。
        2. **裁剪**：超过 `max_memories` 时按 `(level, 1-forget_score, last_accessed)`
           排序保留头部。已归档、已取代的另外归堆，不占「活跃」名额。

        `user_id` 非空时，被裁剪掉的记忆会同步删除 `memory_vectors` 里的向量。
        早先这里不删向量，于是 `memory_vectors` 比 `memories` 长出一截孤儿行，
        `semantic_search` 能把「已经被裁掉、管理界面也看不到」的记忆召回进 prompt。

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
        dropped = candidates[target:]
        self._prune_orphan_vectors(user_id, dropped)
        removed = len(dropped)
        logger.info(f"Cleaned up {removed} old memories (archived {len(archived)})")
        return kept + superseded + archived

    def _prune_orphan_vectors(
        self, user_id: str | None, dropped: list[Memory],
    ) -> int:
        """删除被裁剪记忆对应的向量，返回成功删除的条数。

        `dropped` 为空时直接返回，不做任何 IO。
        """
        if not user_id or not dropped or not self._vector_store:
            return 0
        deleted = 0
        for m in dropped:
            try:
                if self._vector_store.delete(user_id, m.id):
                    deleted += 1
            except Exception as e:
                # 单条失败不能影响其余清理：孤儿向量由 reindex 的 prune 兜底
                logger.warning(f"Vector delete failed for dropped [{m.id}]: {e}")
        if deleted:
            logger.debug(f"Pruned {deleted} orphan vectors for {user_id}")
        return deleted
