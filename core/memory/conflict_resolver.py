"""记忆冲突解析器 — 检测并解决记忆间的矛盾

支持三种冲突类型：
1. 偏好冲突：如「喜欢猫」vs「喜欢狗」、「喜欢红色」vs「喜欢蓝色」
2. 身份信息冲突：如「大一」vs「大二」、「20岁」vs「21岁」
3. 状态信息冲突：如「单身」vs「恋爱中」、「有工作」vs「辞职了」

策略：默认保留最新记忆，旧记忆标记为 superseded，不参与检索。
"""

import re
from loguru import logger

from .models import Memory


class MemoryConflictResolver:
    """记忆冲突解析器

    职责：
    - 检测新记忆与已有记忆之间的冲突
    - 解决冲突（旧记忆标记 superseded）
    - 保留冲突历史用于审计
    """

    # 反义词对（用于检测偏好/观点冲突）
    ANTONYM_PAIRS: list[tuple[str, str, str]] = [
        ("喜欢", "讨厌", "preference"),
        ("爱", "恨", "preference"),
        ("爱吃", "不爱吃", "preference"),
        ("喜欢", "不喜欢", "preference"),
        ("想", "不想", "preference"),
        ("要", "不要", "preference"),
        ("会", "不会", "preference"),
        ("去", "不去", "preference"),
        ("有", "没有", "state"),
        ("是", "不是", "identity"),
        ("在", "不在", "state"),
        ("养", "不养", "preference"),
        ("吃", "不吃", "preference"),
    ]

    # 数字信息关键词（用于身份信息冲突检测）
    IDENTITY_NUMERIC_KEYWORDS = [
        "岁", "年级", "年", "月", "日", "斤", "kg", "cm", "分", "名",
    ]

    # 状态关键词（用于状态冲突检测）
    STATE_KEYWORDS = {
        "单身": "恋爱中",
        "恋爱中": "单身",
        "有工作": "没工作",
        "没工作": "有工作",
        "辞职": "在职",
        "在职": "辞职",
        "在读": "毕业",
        "毕业": "在读",
        "在一起": "分手",
        "分手": "在一起",
        "住": "不住",
    }

    def __init__(self, enable_llm_fallback: bool = False, llm=None):
        """
        Args:
            enable_llm_fallback: 是否启用 LLM 辅助解决复杂冲突
            llm: LLM 实例（仅当 enable_llm_fallback=True 时需要）
        """
        self._enable_llm = enable_llm_fallback
        self._llm = llm

    def detect(self, new_memory: Memory, existing: list[Memory]) -> list[Memory]:
        """检测新记忆与已有记忆之间的所有冲突

        返回所有冲突的旧记忆列表（与 manager.py 集成用）
        """
        conflicts = []
        for old_mem in existing:
            if old_mem.is_superseded or old_mem.archived:
                continue
            conflict = self._check_pair(new_memory, old_mem)
            if conflict:
                logger.debug(
                    f"Conflict detected: '{old_mem.content[:30]}' "
                    f"vs '{new_memory.content[:30]}' ({conflict})"
                )
                conflicts.append(old_mem)
        return conflicts

    def detect_conflict(self, new_memory: Memory, existing: list[Memory]) -> Memory | None:
        """检测新记忆与已有记忆之间的冲突

        Args:
            new_memory: 新添加的记忆
            existing: 已有的全部记忆（仅 active 状态）

        Returns:
            有冲突时返回冲突的旧记忆，无冲突返回 None
        """
        for old_mem in existing:
            if old_mem.is_superseded or old_mem.archived:
                continue

            conflict = self._check_pair(new_memory, old_mem)
            if conflict:
                logger.debug(
                    f"Conflict detected: '{old_mem.content[:30]}' "
                    f"vs '{new_memory.content[:30]}' ({conflict})"
                )
                return old_mem
        return None

    def _check_pair(self, new_mem: Memory, old_mem: Memory) -> str | None:
        """检测两条记忆之间是否存在冲突

        Returns:
            冲突类型字符串，无冲突返回 None
        """
        # 1. 偏好冲突（反义词检测）
        result = self._check_antonym_conflict(new_mem.content, old_mem.content)
        if result:
            return result

        # 2. 身份信息冲突（数字信息变化）
        if new_mem.category in ("personal", "identity") and \
           old_mem.category in ("personal", "identity"):
            result = self._check_identity_conflict(new_mem.content, old_mem.content)
            if result:
                return result

        # 3. 状态冲突（直接对立的状态描述）
        result = self._check_state_conflict(new_mem.content, old_mem.content)
        if result:
            return result

        # 4. 同一分类且内容高度重叠但对立的语义冲突
        if new_mem.category == old_mem.category and \
           new_mem.category in ("preference", "opinion"):
            result = self._check_semantic_conflict(new_mem.content, old_mem.content)
            if result:
                return result

        return None

    @staticmethod
    def _is_double_negated(text: str, negated_form: str) -> bool:
        """判断否定式本身是否又被否定（「不是不喜欢」「并不讨厌」）。

        取否定式每一次出现位置往前 3 个字符，只要出现 不/没/别 就算双重否定。
        窗口取 3 而不是 1，是因为「不**是**不喜欢」中间隔着「是」。
        """
        start = 0
        while True:
            idx = text.find(negated_form, start)
            if idx < 0:
                return False
            if any(mark in text[max(0, idx - 3):idx] for mark in ("不", "没", "别")):
                return True
            start = idx + 1

    # 语境核验的虚词表：只算实词汉字的交集，避免「我」「的」「上」这类
    # 几乎每句都出现的字撑起假共性。
    _STOP_CHARS = set(
        "我你他她它我们你们他们这那的了吗呢啊吧呀把被和与就不没很也"
        "都还在是个有还又也上下里外中前后来去出说过点能让会比之"
    )

    @staticmethod
    def _context_windows(text: str, word: str, pad: int = 6) -> list[str]:
        """冲突词在文本中每次出现位置的前后窗口"""
        windows: list[str] = []
        start = 0
        while True:
            idx = text.find(word, start)
            if idx < 0:
                break
            windows.append(text[max(0, idx - pad): idx + len(word) + pad])
            start = idx + 1
        return windows

    @staticmethod
    def _windows_overlap(content_a: str, word_a: str,
                         content_b: str, word_b: str,
                         min_shared: int = 1) -> bool:
        """两边冲突词的窗口文本（各自剔除冲突词本身）去掉虚词与标点后，
        实词汉字交集是否 ≥ min_shared。

        同一件事的翻供会复述宾语（「我喜欢吃辣」/「我不喜欢吃辣」→
        交集含 {吃,辣}；「我喜欢猫」/「我讨厌猫」→ 共享宾语「猫」）；
        语境无关的巧合（「会主动问起」/「不会马上吹干」）剔除冲突词后
        连一个共同实词都没有。阈值取 1 的前提是反义词对已命中 + 窗口
        仅 6 字 —— 无关句子在这个窗口里共享实词的概率极低。
        """
        windows_a = MemoryConflictResolver._context_windows(content_a, word_a)
        windows_b = MemoryConflictResolver._context_windows(content_b, word_b)
        stop = MemoryConflictResolver._STOP_CHARS

        def _content_chars(text: str, remove: str) -> set[str]:
            cleaned = text.replace(remove, "")
            return {
                ch for ch in cleaned
                if "\u4e00" <= ch <= "\u9fff" and ch not in stop
            }

        for wa in windows_a:
            chars_a = _content_chars(wa, word_a)
            if not chars_a:
                continue
            for wb in windows_b:
                chars_b = _content_chars(wb, word_b)
                if len(chars_a & chars_b) >= min_shared:
                    return True
        return False

    @staticmethod
    def _check_antonym_conflict(content_a: str, content_b: str) -> str | None:
        """检测反义词冲突（偏好/观点对立）

        .. note::
           双重否定豁免只查「否定式又被否定」，**不能**再查 `"不" + 正向词`。
           ANTONYM_PAIRS 里有 10 组本身就把否定写成「不 + 正向词」
           （想/不想、在/不在、养/不养、喜欢/不喜欢、会/不会、去/不去、
           是/不是、吃/不吃、要/不要、爱吃/不爱吃），再拿 `"不" + pos`
           去豁免，那 10 组会 100% 命中豁免、永远判不出冲突 ——
           用户说「我不喜欢猫」，旧记忆「我喜欢猫」就永远不会被取代。
        """
        for pos, neg, conflict_type in MemoryConflictResolver.ANTONYM_PAIRS:
            if (pos in content_a and neg in content_b) or \
               (neg in content_a and pos in content_b):
                if MemoryConflictResolver._is_double_negated(content_a, neg):
                    continue
                if MemoryConflictResolver._is_double_negated(content_b, neg):
                    continue
                # 语境核验：词对命中只说明两句话里出现了这对反义字，
                # 不说明说的是同一件事。实测误判——「我关心团子，会主动
                # 问起」vs「头发不会马上吹干」因「会/不会」被判偏好翻供，
                # 一条与团子有关的记忆被静默顶掉。要求两边冲突词的
                # 上下文窗口有 ≥2 字公共子串（同一件事的翻供通常复述
                # 宾语），否则跳过这组词对。
                word_a = pos if pos in content_a else neg
                word_b = neg if word_a == pos else pos
                if not MemoryConflictResolver._windows_overlap(
                    content_a, word_a, content_b, word_b,
                ):
                    continue
                return conflict_type
        return None

    # 汉字年级（「大一 / 大二」不写阿拉伯数字，数字正则抓不到）
    GRADE_CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8}

    @staticmethod
    def _extract_grade(content: str) -> int | None:
        match = re.search(r"大([一二三四五六七八])", content or "")
        return MemoryConflictResolver.GRADE_CN.get(match.group(1)) if match else None

    @staticmethod
    def _check_identity_conflict(content_a: str, content_b: str) -> str | None:
        """检测身份信息冲突（数字变化如 20岁→21岁、大一→大二）"""
        # 提取所有数字+单位组合
        pattern = re.compile(r'(\d+)([岁年级年月日斤kgcm分名])')
        matches_a = pattern.findall(content_a)
        matches_b = pattern.findall(content_b)

        for num_a, unit_a in matches_a:
            for num_b, unit_b in matches_b:
                if unit_a == unit_b and num_a != num_b:
                    # 同一单位但数值不同 — 身份冲突
                    if unit_a in ('岁', '年级', '年'):
                        return "identity"

        # 年级常写成「大一 / 大二」，没有阿拉伯数字，单独比一次
        grade_a = MemoryConflictResolver._extract_grade(content_a)
        grade_b = MemoryConflictResolver._extract_grade(content_b)
        if grade_a is not None and grade_b is not None and grade_a != grade_b:
            return "identity"

        return None

    @staticmethod
    def _check_state_conflict(content_a: str, content_b: str) -> str | None:
        """检测状态冲突（单身 vs 恋爱中）"""
        for state_a, opposite_b in MemoryConflictResolver.STATE_KEYWORDS.items():
            if state_a in content_a and opposite_b in content_b:
                return "state"
            if state_a in content_b and opposite_b in content_a:
                return "state"
        return None

    @staticmethod
    def _check_semantic_conflict(content_a: str, content_b: str) -> str | None:
        """检测同一分类下的语义冲突（高重叠但观点对立）"""
        # 计算字符级重叠
        set_a = set(content_a)
        set_b = set(content_b)
        overlap = len(set_a & set_b)
        min_len = min(len(set_a), len(set_b))
        if min_len == 0:
            return None
        overlap_ratio = overlap / min_len

        # 高度重叠（>60%字符相同）可能表达相反观点
        if overlap_ratio > 0.6:
            # 检查是否包含对立情感词
            positive_words = {"喜欢", "爱", "好", "棒", "香", "好吃", "好看", "好听"}
            negative_words = {"讨厌", "恨", "差", "烂", "臭", "难吃", "难看", "难听"}
            pos_in_a = any(w in content_a for w in positive_words)
            neg_in_a = any(w in content_b for w in negative_words)
            pos_in_b = any(w in content_b for w in positive_words)
            neg_in_b = any(w in content_a for w in negative_words)
            if (pos_in_a and neg_in_a) or (pos_in_b and neg_in_b):
                return "preference"
        return None

    @staticmethod
    def resolve_conflict(new_memory: Memory, old_memory: Memory) -> tuple[Memory, Memory]:
        """解决冲突：保留新记忆，旧记忆标记 superseded

        Args:
            new_memory: 新记忆（保留）
            old_memory: 旧记忆（标记 superseded）

        Returns:
            (更新后的新记忆, 更新后的旧记忆)
        """
        old_memory.superseded_by = new_memory.id
        new_memory.related_memory_ids = list(set(
            new_memory.related_memory_ids + [old_memory.id]
        ))

        # 新记忆继承旧记忆的访问计数（如果更高的话）
        new_memory.access_count = max(new_memory.access_count, old_memory.access_count)

        logger.info(
            f"Conflict resolved: '{old_memory.content[:30]}' → "
            f"'{new_memory.content[:30]}' "
            f"(type: {old_memory.category})"
        )
        return new_memory, old_memory
