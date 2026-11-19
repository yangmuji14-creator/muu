"""记忆生命周期管理 — 归档与遗忘候选

与 ``MemoryDecaySystem`` 共用同一套遗忘评分：本模块不再自建阈值，
``compute_forget_score`` 直接委托给生产用的 decay 公式，避免两套
公式对同一批记忆给出互相矛盾的归档结论。

输入是「dict 形态的记忆」（``Memory.to_dict()`` 的输出），
时间字段一律是 ISO 字符串 —— 这里统一解析，绝不把字符串当 datetime 相减。
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from loguru import logger

from .decay import MemoryDecaySystem
from .models import Memory, parse_datetime


@dataclass
class MemorySummary:
    """记忆摘要"""

    original_ids: list[str]
    summary_content: str
    created_at: datetime
    importance_score: float
    emotion_tags: list[str]
    topic: str


class MemoryLifecycleManager:
    """记忆生命周期管理器

    - 遗忘评分：委托 ``MemoryDecaySystem``（阈值与生产归档完全一致）
    - 归档候选：>ARCHIVE_AGE_DAYS 天、访问次数 <3、情感强度 ≤0.7
    - 报告：与归档候选使用同一条规则
    """

    ARCHIVE_AGE_DAYS = 90
    LOW_ACCESS_THRESHOLD = 3
    HIGH_EMOTION_INTENSITY = 0.7
    # 与 MemoryDecaySystem 的默认 forget_threshold 保持一致
    FORGET_SCORE_THRESHOLD = 1.0

    def __init__(self, decay: MemoryDecaySystem | None = None):
        self._decay = decay or MemoryDecaySystem()
        # 跟随注入实例的阈值，避免「报表按 1.0 判、归档按 0.8 判」。
        self._forget_threshold = float(
            getattr(self._decay, "_forget_threshold", self.FORGET_SCORE_THRESHOLD)
        )
        self._forget_scores: dict[str, float] = {}

    # ────────── 遗忘评分 ──────────

    def compute_forget_score(
        self,
        memory_id: str,
        memory: dict,
        current_time: datetime | None = None,
    ) -> float:
        """计算遗忘评分（委托生产用的 decay 公式）

        ``current_time`` 仅为兼容旧调用保留；decay 公式内部使用当前时间。
        """
        try:
            payload = dict(memory)
            payload.setdefault("id", memory_id)
            # decay 用 fromisoformat 解析时间：datetime 实例会让它抛
            # TypeError 并把时间重置为 now（分数静默变 0）；带时区的字符串
            # 则会产出 aware datetime，与 naive now 相减时崩溃。统一归一化。
            for key in ("created_at", "last_accessed"):
                normalized = parse_datetime(payload.get(key))
                if normalized is not None:
                    payload[key] = normalized.isoformat()
            mem = Memory.from_dict(payload)
        except (KeyError, TypeError, ValueError) as exc:
            logger.debug(f"compute_forget_score: 无法转换记忆 {memory_id}: {exc}")
            return 0.0
        return self._decay.calculate_forget_score(mem)

    def mark_for_forgetting(
        self, memory_ids: list[str], memories: dict[str, dict]
    ) -> list[str]:
        """标记应该遗忘的记忆（评分 ≥ FORGET_SCORE_THRESHOLD）"""
        marked: list[str] = []
        now = datetime.now()

        for mem_id in memory_ids:
            memory = memories.get(mem_id)
            if memory is None:
                continue

            score = self.compute_forget_score(mem_id, memory, now)
            self._forget_scores[mem_id] = score

            if score >= self._forget_threshold:
                marked.append(mem_id)
                logger.info(f"Memory marked for forgetting: {mem_id} (score={score:.2f})")

        return marked

    # ────────── 归档 ──────────

    def _age_days(self, memory: dict, now: datetime) -> int | None:
        created = parse_datetime(memory.get("created_at"))
        if created is None:
            return None
        return (now - created).days

    @staticmethod
    def _emotion_intensity(memory: dict) -> float:
        emotion = memory.get("emotion") or {}
        return float(emotion.get("intensity", 0.5)) if emotion else 0.5

    @staticmethod
    def _level_of(memory: dict) -> int:
        try:
            return int(memory.get("level", 1))
        except (TypeError, ValueError):
            return 1

    def is_archive_candidate(self, memory: dict, now: datetime) -> bool:
        """归档候选（报告与归档共用）。"""
        return self._archive_candidate(
            memory,
            self._age_days(memory, now),
            self._emotion_intensity(memory),
        )

    def _archive_candidate(
        self,
        memory: dict,
        age_days: int | None,
        emotion_intensity: float,
    ) -> bool:
        """归档候选的三条规则 + 生产 decay 的重要度守卫。

        level>=3、已归档的记忆永不进入摘要归档 —— 与
        ``MemoryDecaySystem.should_archive`` 的 level<3 守卫保持一致。
        """
        if age_days is None or age_days <= self.ARCHIVE_AGE_DAYS:
            return False
        if self._level_of(memory) >= 3 or memory.get("archived"):
            return False
        if memory.get("access_count", 0) >= self.LOW_ACCESS_THRESHOLD:
            return False
        return emotion_intensity <= self.HIGH_EMOTION_INTENSITY

    def archive_old_memories(self, memories: dict[str, dict]) -> list[MemorySummary]:
        """将归档候选聚类并生成摘要"""
        summaries: list[MemorySummary] = []
        now = datetime.now()

        candidates = [
            (mem_id, mem)
            for mem_id, mem in memories.items()
            if self.is_archive_candidate(mem, now)
        ]
        if not candidates:
            return summaries

        for topic, cluster_ids in self._cluster_memories(candidates).items():
            cluster_memories = [memories[mid] for mid in cluster_ids if mid in memories]
            if not cluster_memories:
                continue

            avg_importance = sum(
                m.get("importance", 0.5) for m in cluster_memories
            ) / len(cluster_memories)

            summaries.append(
                MemorySummary(
                    original_ids=cluster_ids,
                    summary_content=self._simple_summary(cluster_memories),
                    created_at=now,
                    importance_score=avg_importance,
                    emotion_tags=[
                        m.get("emotion", {}).get("type")
                        for m in cluster_memories
                        if m.get("emotion")
                    ],
                    topic=topic,
                )
            )

        return summaries

    def _cluster_memories(
        self, memories: list[tuple[str, dict]]
    ) -> dict[str, list[str]]:
        clusters: dict[str, list[str]] = defaultdict(list)
        for mem_id, mem in memories:
            tags = mem.get("tags") or []
            emotion = mem.get("emotion") or {}
            topic = tags[0] if tags else emotion.get("type", "neutral")
            clusters[topic].append(mem_id)
        return dict(clusters)

    def _simple_summary(self, memories: list[dict]) -> str:
        if not memories:
            return ""

        def _sort_key(m: dict) -> datetime:
            return parse_datetime(m.get("created_at")) or datetime.min

        parts = []
        for mem in sorted(memories, key=_sort_key)[:3]:
            content = str(mem.get("content", ""))
            if len(content) > 100:
                content = content[:100] + "..."
            parts.append(content)
        return " | ".join(parts)

    # ────────── 报告 ──────────

    def get_lifecycle_report(self, memories: dict[str, dict]) -> dict:
        """生命周期报告 —— 分桶规则与 archive_old_memories 完全一致"""
        now = datetime.now()
        report = {
            "total": len(memories),
            "active": 0,
            "aging": 0,
            "archived_candidate": 0,
            "high_emotion": 0,
            "forget_candidates": 0,
        }

        for mem_id, mem in memories.items():
            age_days = self._age_days(mem, now)
            if age_days is None:
                continue

            intensity = self._emotion_intensity(mem)
            if intensity > self.HIGH_EMOTION_INTENSITY:
                report["high_emotion"] += 1

            # 复用已算出的年龄/情感强度，避免重复解析 ISO 时间
            if self._archive_candidate(mem, age_days, intensity):
                report["archived_candidate"] += 1
            elif age_days <= self.ARCHIVE_AGE_DAYS:
                report["active"] += 1
            else:
                report["aging"] += 1

            if self._forget_scores.get(mem_id, 0.0) >= self._forget_threshold:
                report["forget_candidates"] += 1

        return report
