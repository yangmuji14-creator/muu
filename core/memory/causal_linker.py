"""因果链识别 — 识别相关记忆中的因果关系

当用户说「感冒了」，不仅加载「感冒相关的」记忆，
还要加载「昨天下雨了 → 今天感冒」这样的因果链。

实现思路：
  1. 候选记忆中查找时间/事件关联
  2. 识别"前因"和"后果"
  3. 因果链作为一个单元加载到上下文
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from loguru import logger

from .models import parse_datetime


@dataclass
class CausalLink:
    """因果链条"""
    cause_memory_id: str
    effect_memory_id: str
    cause_content: str
    effect_content: str
    time_gap_hours: float
    confidence: float  # 0-1，因果确信度


class CausalLinker:
    """因果链识别系统"""

    def __init__(self):
        # 关键词配对：(前因关键词, 后果关键词) -> 可能的因果关系
        self._causal_keywords = {
            ("下雨", "感冒"): 0.7,
            ("熬夜", "疲劳"): 0.8,
            ("加班", "头疼"): 0.7,
            ("吵架", "心情不好"): 0.8,
            ("高兴的事", "开心"): 0.75,
            ("失败", "沮丧"): 0.8,
            ("成功", "自信"): 0.75,
        }

        # 时间窗口：多少小时内的事件可能有因果关系
        self.CAUSAL_TIME_WINDOW = timedelta(hours=48)

    def find_causal_chains(
        self,
        query_memory_id: str,
        query_content: str,
        candidate_memories: list[dict],
    ) -> list[CausalLink]:
        """
        在候选记忆中寻找与查询相关的因果链

        Args:
            query_memory_id: 查询的记忆 ID
            query_content: 查询的记忆内容
            candidate_memories: 候选记忆列表 [{"id": str, "content": str, "timestamp": datetime}, ...]

        Returns:
            因果链列表
        """
        chains = []

        for candidate in candidate_memories:
            candidate_id = candidate.get("id", "")
            candidate_content = candidate.get("content", "")
            # 两种字段名都接受：内部调用多用 timestamp，Memory.to_dict 用 created_at
            candidate_time = parse_datetime(
                candidate.get("timestamp") or candidate.get("created_at")
            )

            base_confidence = self._compute_causal_confidence(
                cause=candidate_content,
                effect=query_content,
                forward=True,
            )
            if base_confidence <= 0.5:
                continue

            gap_hours = 0.0
            confidence = base_confidence
            if candidate_time is not None:
                gap = datetime.now() - candidate_time
                gap_hours = gap.total_seconds() / 3600.0
                # 时间戳明确晚于查询时，不可能是「前因」
                if gap_hours < 0:
                    continue
                # 超出因果窗口只降权，不丢链 —— 0.7×0.6=0.42 若再按 0.5 过滤
                # 会把「降权」变成「硬切断」，与窗口语义相反。
                if gap.total_seconds() > self.CAUSAL_TIME_WINDOW.total_seconds():
                    confidence *= 0.6

            chains.append(CausalLink(
                cause_memory_id=candidate_id,
                effect_memory_id=query_memory_id,
                cause_content=candidate_content,
                effect_content=query_content,
                time_gap_hours=gap_hours,
                confidence=confidence,
            ))

        return sorted(chains, key=lambda x: x.confidence, reverse=True)

    def _compute_causal_confidence(
        self,
        cause: str,
        effect: str,
        forward: bool = True,
    ) -> float:
        """计算两条记忆之间的因果确信度"""
        confidence = 0.0

        # 1. 关键词配对匹配
        for (cause_kw, effect_kw), base_conf in self._causal_keywords.items():
            if forward:
                if cause_kw in cause and effect_kw in effect:
                    confidence = max(confidence, base_conf)
            else:
                if effect_kw in cause and cause_kw in effect:
                    confidence = max(confidence, base_conf * 0.8)

        # 2. 情感语境匹配（简单启发式）
        if "因为" in cause or "导致" in effect or "所以" in effect:
            confidence = max(confidence, 0.6)

        if "不过" in effect or "但是" in effect:
            confidence *= 0.7  # 转折减弱因果

        return min(confidence, 1.0)

    def rank_with_causal_boost(
        self,
        candidate_memories: list[dict],
        query_memory_id: str,
        query_content: str,
        original_scores: dict[str, float],  # memory_id -> similarity_score
    ) -> dict[str, float]:
        """
        基于因果链增强排序得分

        Args:
            candidate_memories: 候选记忆
            query_memory_id: 查询记忆 ID
            query_content: 查询内容
            original_scores: 原始相似度得分

        Returns:
            增强后的得分 (memory_id -> 新得分)
        """
        chains = self.find_causal_chains(query_memory_id, query_content, candidate_memories)

        boosted_scores = original_scores.copy()

        # 因果链中的记忆获得加成
        for chain in chains:
            if chain.cause_memory_id in boosted_scores:
                # 加成：confidence × 0.2（最多增加 20% 的分数）
                boost = chain.confidence * 0.2
                boosted_scores[chain.cause_memory_id] = min(
                    1.0,
                    boosted_scores[chain.cause_memory_id] + boost
                )
                logger.debug(
                    f"Causal boost: {chain.cause_memory_id} "
                    f"(+{boost:.3f}, confidence={chain.confidence:.2f})"
                )

        return boosted_scores
