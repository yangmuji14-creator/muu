"""记忆冲突解析测试 —— `core/memory/conflict_resolver.py`。

它决定「用户改口之后，旧记忆还算不算数」。判错两个方向都伤：
- 漏判：旧的「喜欢猫」和新的「讨厌猫」同时进 prompt，模型自相矛盾；
- 误判：「我喜欢吃烤红薯」和「我不喜欢吃香菜」被当成冲突，正常的偏好被互删。
所以既要有正例也要有反例。
"""

import pytest

from core.memory.conflict_resolver import MemoryConflictResolver
from core.memory.models import Memory


def _mem(mem_id: str, content: str, *, category: str = "preference", level: int = 3,
         superseded_by: str = "", archived: bool = False) -> Memory:
    return Memory(
        id=mem_id, content=content, level=level, category=category,
        superseded_by=superseded_by, archived=archived,
    )


class TestAntonymConflict:
    @pytest.mark.parametrize(
        "a,b,expected",
        [
            ("我特别喜欢猫", "我讨厌猫", "preference"),
            ("我爱吃烤红薯", "我恨烤红薯", "preference"),
            ("我想学吉他", "我不想学吉他", "preference"),
            ("我有工作", "我没有工作", "state"),
            ("我在成都", "我不在成都", "state"),
            ("我养了一只猫", "我不养猫", "preference"),
        ],
    )
    def test_detects_opposites(self, a, b, expected):
        assert MemoryConflictResolver._check_antonym_conflict(a, b) == expected

    def test_order_does_not_matter(self):
        assert MemoryConflictResolver._check_antonym_conflict("我讨厌猫", "我喜欢猫") == "preference"

    def test_no_conflict_when_same_polarity(self):
        assert MemoryConflictResolver._check_antonym_conflict("我喜欢猫", "我也喜欢狗") is None

    def test_double_negation_skipped(self):
        # 「不是不喜欢」= 喜欢，不能算冲突
        assert MemoryConflictResolver._check_antonym_conflict("我不是不喜欢猫", "我喜欢猫") is None

    def test_unrelated_contents(self):
        assert MemoryConflictResolver._check_antonym_conflict("今天下雨", "明天晴") is None

    def test_empty_strings(self):
        assert MemoryConflictResolver._check_antonym_conflict("", "") is None
        assert MemoryConflictResolver._check_antonym_conflict("喜欢猫", "") is None


class TestIdentityConflict:
    @pytest.mark.parametrize(
        "a,b",
        [
            ("我今年 20岁", "我今年 21岁"),
            ("我上大一", "我上大二"),
            ("我 2024年 毕业", "我 2025年 毕业"),
        ],
    )
    def test_numeric_change_detected(self, a, b):
        assert MemoryConflictResolver._check_identity_conflict(a, b) == "identity"

    def test_same_number_no_conflict(self):
        assert MemoryConflictResolver._check_identity_conflict("我 20岁", "我 20岁") is None

    def test_different_units_no_conflict(self):
        # 20岁 vs 20斤：单位不同，不是同一件事
        assert MemoryConflictResolver._check_identity_conflict("我 20岁", "我 20斤") is None

    @pytest.mark.parametrize("unit", ["cm", "kg", "分", "名", "月", "日"])
    def test_only_year_grade_age_counted(self, unit):
        # 只有 岁/年级/年 参与冲突判定，体重身高变化不该标记身份冲突
        assert MemoryConflictResolver._check_identity_conflict(f"我 10{unit}", f"我 20{unit}") is None

    def test_no_numbers(self):
        assert MemoryConflictResolver._check_identity_conflict("我叫小明", "我叫小红") is None


class TestStateConflict:
    @pytest.mark.parametrize(
        "a,b",
        [
            ("我现在单身", "我现在恋爱中"),
            ("我辞职了", "我还在职"),
            ("在读研究生", "已经毕业"),
            ("我们在一起了", "我们已经分手"),
        ],
    )
    def test_detects_state_flip(self, a, b):
        assert MemoryConflictResolver._check_state_conflict(a, b) == "state"

    def test_order_independent(self):
        assert MemoryConflictResolver._check_state_conflict("恋爱中", "单身") == "state"

    def test_same_state_no_conflict(self):
        assert MemoryConflictResolver._check_state_conflict("我单身", "他也单身") is None

    def test_unrelated(self):
        assert MemoryConflictResolver._check_state_conflict("今天天气好", "明天可能有雨") is None


class TestSemanticConflict:
    def test_high_overlap_opposite_words(self):
        result = MemoryConflictResolver._check_semantic_conflict(
            "这家店的烤红薯很好吃", "这家店的烤红薯很难吃",
        )
        assert result == "preference"

    def test_high_overlap_same_polarity(self):
        assert MemoryConflictResolver._check_semantic_conflict(
            "这家店的烤红薯很好吃", "这家店的烤红薯也很好吃",
        ) is None

    def test_low_overlap(self):
        assert MemoryConflictResolver._check_semantic_conflict("烤红薯", "显卡型号") is None

    def test_empty(self):
        assert MemoryConflictResolver._check_semantic_conflict("", "") is None
        assert MemoryConflictResolver._check_semantic_conflict("喜欢", "") is None


class TestCheckPair:
    def test_antonym_checked_first(self):
        new = _mem("n", "我讨厌猫")
        old = _mem("o", "我喜欢猫")
        assert MemoryConflictResolver()._check_pair(new, old) == "preference"

    def test_identity_only_for_personal_category(self):
        new = _mem("n", "我今年 21岁", category="personal")
        old = _mem("o", "我今年 20岁", category="personal")
        assert MemoryConflictResolver()._check_pair(new, old) == "identity"

    def test_identity_skipped_for_other_categories(self):
        new = _mem("n", "我今年 21岁", category="event")
        old = _mem("o", "我今年 20岁", category="event")
        assert MemoryConflictResolver()._check_pair(new, old) is None

    def test_no_conflict(self):
        assert MemoryConflictResolver()._check_pair(
            _mem("n", "他有一只猫叫团子"), _mem("o", "他下个月去成都"),
        ) is None


class TestDetect:
    def test_returns_all_conflicts(self):
        new = _mem("n", "我喜欢猫")
        existing = [
            _mem("o1", "我讨厌猫"),
            _mem("o2", "他喜欢狗"),
            _mem("o3", "我不喜欢猫"),
        ]
        conflicts = MemoryConflictResolver().detect(new, existing)
        assert {m.id for m in conflicts} == {"o1", "o3"}

    def test_skips_superseded(self):
        new = _mem("n", "我喜欢猫")
        existing = [_mem("o1", "我讨厌猫", superseded_by="o9")]
        assert MemoryConflictResolver().detect(new, existing) == []

    def test_skips_archived(self):
        new = _mem("n", "我喜欢猫")
        existing = [_mem("o1", "我讨厌猫", archived=True)]
        assert MemoryConflictResolver().detect(new, existing) == []

    def test_empty_existing(self):
        assert MemoryConflictResolver().detect(_mem("n", "x"), []) == []

    def test_no_conflicts(self):
        new = _mem("n", "他喜欢烤红薯")
        existing = [_mem("o1", "他有一只猫"), _mem("o2", "他在学游泳")]
        assert MemoryConflictResolver().detect(new, existing) == []


class TestDetectConflict:
    def test_returns_first_match(self):
        new = _mem("n", "我喜欢猫")
        existing = [_mem("o1", "我讨厌猫"), _mem("o2", "我不喜欢猫")]
        hit = MemoryConflictResolver().detect_conflict(new, existing)
        assert hit is not None
        assert hit.id == "o1"

    def test_none_when_clean(self):
        assert MemoryConflictResolver().detect_conflict(
            _mem("n", "他喜欢烤红薯"), [_mem("o1", "他有一只猫")],
        ) is None

    def test_skips_inactive(self):
        new = _mem("n", "我喜欢猫")
        existing = [_mem("o1", "我讨厌猫", archived=True)]
        assert MemoryConflictResolver().detect_conflict(new, existing) is None


class TestResolveConflict:
    def test_old_marked_superseded(self):
        new, old = _mem("n", "我喜欢猫"), _mem("o", "我讨厌猫")
        new2, old2 = MemoryConflictResolver.resolve_conflict(new, old)
        assert old2.superseded_by == "n"
        assert old2.is_superseded is True

    def test_new_records_related_id(self):
        new, old = _mem("n", "我喜欢猫"), _mem("o", "我讨厌猫")
        new2, _ = MemoryConflictResolver.resolve_conflict(new, old)
        assert "o" in new2.related_memory_ids

    def test_related_ids_not_duplicated(self):
        new = _mem("n", "我喜欢猫")
        new.related_memory_ids = ["o"]
        MemoryConflictResolver.resolve_conflict(new, _mem("o", "我讨厌猫"))
        assert new.related_memory_ids.count("o") == 1

    def test_inherits_higher_access_count(self):
        new, old = _mem("n", "我喜欢猫"), _mem("o", "我讨厌猫")
        new.access_count = 3
        old.access_count = 17
        new2, _ = MemoryConflictResolver.resolve_conflict(new, old)
        assert new2.access_count == 17

    def test_keeps_new_when_new_is_higher(self):
        new, old = _mem("n", "我喜欢猫"), _mem("o", "我讨厌猫")
        new.access_count = 20
        old.access_count = 5
        new2, _ = MemoryConflictResolver.resolve_conflict(new, old)
        assert new2.access_count == 20

    def test_returns_same_objects(self):
        new, old = _mem("n", "a"), _mem("o", "b")
        r_new, r_old = MemoryConflictResolver.resolve_conflict(new, old)
        assert r_new is new
        assert r_old is old


class TestConstructor:
    def test_defaults(self):
        resolver = MemoryConflictResolver()
        assert resolver._enable_llm is False
        assert resolver._llm is None

    def test_llm_flags_accepted(self):
        resolver = MemoryConflictResolver(enable_llm_fallback=True, llm=object())
        assert resolver._enable_llm is True
        assert resolver._llm is not None
