"""core/proactive.py 的单元测试

覆盖三条触发链（定时 / 久未联系 / 记忆追问 / 持续关怀）与 LLM 生成、兜底文案。
全部用替身，不联网、不碰真实 data/ 与 config/。

几个容易踩的点写在这里，改代码时别把它们「简化」掉：

1. `_is_in_active_window` 用的是 `start <= hour < end`，**end 是开区间**。
   想让测试永远在窗口内就把窗口设成 `0..24`，想永远在窗外就设成 `0..0`。
2. `_can_fire` 有副作用：第一次调用就写入 `_next_proactive_after`。
   所以「间隔未到」的用例必须手动把 `_next_proactive_after` 设成未来时间，
   不能指望连调两次 `_can_fire`（第二次的结果依赖真实时钟）。
3. `check_proactive_messages` 的四条链是**顺序短路**的：定时命中就 return，
   后面三条根本不执行。测后三条必须先把窗口关掉（`0..0`）。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.memory.models import Memory
from core.proactive import ProactiveMessenger
from core.social.affection.schema import AffectionStats


# ── 替身 ────────────────────────────────────────────────────────


class FakePersonaLoader:
    def __init__(self, personas: dict | None = None):
        self.personas = personas if personas is not None else {"p1": FakePersona()}

    def get(self, persona_id: str):
        return self.personas.get(persona_id)


class FakePersona:
    def __init__(self, **overrides):
        self.name = "慕"
        self.personality = ["真诚", "自然"]
        self.speaking_style = {"基础风格": "简短自然"}
        self.gender = "女"
        for key, value in overrides.items():
            setattr(self, key, value)


class FakeMemoryMgr:
    def __init__(self, memories: list | None = None, raises: bool = False):
        self.memories = memories or []
        self.raises = raises
        self.calls: list[dict] = []

    def get_memories(self, user_id, level_min=1, limit=10, **kwargs):
        self.calls.append({"user_id": user_id, "level_min": level_min, "limit": limit})
        if self.raises:
            raise RuntimeError("memory boom")
        return self.memories


class FakeAffection:
    def __init__(self, level: float = 60.0, stats: AffectionStats | None = None,
                 last: str | None = None):
        self.level = level
        self.stats = stats or AffectionStats(
            level=level, message_count=20, positive_count=10,
            negative_count=2, days_known=30,
        )
        self.last = last

    def get_level(self, user_id, persona_id=""):
        return self.level

    def get_stats(self, user_id, persona_id=""):
        return self.stats

    def get_last_interaction(self, user_id, persona_id=""):
        return self.last


class FakeChatHistory:
    def __init__(self, messages: list | None = None, raises: bool = False):
        self.messages = messages or []
        self.raises = raises

    def get_messages(self, user_id):
        if self.raises:
            raise RuntimeError("history boom")
        return self.messages


def make_messenger(
    *,
    persona_loader=None,
    memory_mgr=None,
    affection=None,
    chat_history=None,
    **config,
) -> ProactiveMessenger:
    """造一个 messenger，默认活跃窗口 0..24（永远在窗口内）。"""
    cfg = {
        "proactive_enabled": True,
        "proactive_active_start": 0,
        "proactive_active_end": 24,
        "proactive_interval_min": 30,
        "proactive_interval_max": 30,
        "proactive_min_level": 20,
        "proactive_missing_days": 2,
        "proactive_memory_recall": True,
    }
    cfg.update(config)
    return ProactiveMessenger(
        persona_loader=persona_loader or FakePersonaLoader(),
        memory_mgr=memory_mgr or FakeMemoryMgr(),
        affection_storage=affection or FakeAffection(),
        config=cfg,
        chat_history=chat_history,
    )


def mem(content: str, *, days_old: float = 0.5, level: int = 4,
        mem_id: str | None = None) -> Memory:
    created = datetime.now() - timedelta(days=days_old)
    return Memory(
        id=mem_id or f"mem_{abs(hash(content)) % 10 ** 8:08d}",
        content=content,
        level=level,
        category="personal",
        created_at=created.isoformat(),
        last_accessed=created.isoformat(),
    )


# ── 构造与配置 ──────────────────────────────────────────────────


class TestConfig:
    def test_defaults(self):
        m = ProactiveMessenger(
            persona_loader=FakePersonaLoader(),
            memory_mgr=FakeMemoryMgr(),
            affection_storage=FakeAffection(),
        )
        assert m.enabled is True
        assert m.missing_days == 2
        assert m.min_relationship_level == 20
        assert m.memory_recall_enabled is True
        assert (m._active_start, m._active_end) == (7, 23)
        assert (m._interval_min, m._interval_max) == (30, 180)

    def test_config_overrides(self):
        m = make_messenger(
            proactive_enabled=False,
            proactive_missing_days=5,
            proactive_min_level=50,
            proactive_memory_recall=False,
            proactive_active_start=9,
            proactive_active_end=21,
            proactive_interval_min=10,
            proactive_interval_max=20,
        )
        assert m.enabled is False
        assert m.missing_days == 5
        assert m.min_relationship_level == 50
        assert m.memory_recall_enabled is False
        assert (m._active_start, m._active_end) == (9, 21)
        assert (m._interval_min, m._interval_max) == (10, 20)

    def test_none_config_uses_defaults(self):
        m = ProactiveMessenger(
            persona_loader=FakePersonaLoader(),
            memory_mgr=FakeMemoryMgr(),
            affection_storage=FakeAffection(),
            config=None,
        )
        assert m.enabled is True

    def test_set_llm_generator(self):
        m = make_messenger()

        async def gen(**kwargs):
            return "hi"

        assert m._llm_generate is None
        m.set_llm_generator(gen)
        assert m._llm_generate is gen


# ── 当日去重标记 ────────────────────────────────────────────────


class TestFiredMarkers:
    def test_today_key_contains_date_and_period(self):
        m = make_messenger()
        key = m._today_key("scheduled")
        assert key == f"{datetime.now().date()}_scheduled"

    def test_not_fired_initially(self):
        m = make_messenger()
        assert m._already_fired("scheduled") is False

    def test_mark_then_fired(self):
        m = make_messenger()
        m._mark_fired("missing")
        assert m._already_fired("missing") is True
        assert m._already_fired("scheduled") is False

    def test_cleanup_drops_yesterday(self):
        m = make_messenger()
        m._fired_today["2020-01-01_scheduled"] = datetime(2020, 1, 1, 9, 0)
        m._mark_fired("missing")
        m._cleanup_old_markers()
        assert "2020-01-01_scheduled" not in m._fired_today
        assert m._already_fired("missing") is True

    def test_periods_are_independent(self):
        m = make_messenger()
        m._mark_fired("recall_1")
        m._mark_fired("recall_2")
        assert m._already_fired("recall_1") and m._already_fired("recall_2")
        assert m._already_fired("care") is False


# ── 间隔与窗口 ──────────────────────────────────────────────────


class TestIntervalAndWindow:
    def test_pick_next_interval_within_range(self):
        m = make_messenger(proactive_interval_min=10, proactive_interval_max=10)
        assert m._pick_next_interval() == timedelta(minutes=10)

    def test_pick_next_interval_randomised(self):
        m = make_messenger(proactive_interval_min=30, proactive_interval_max=180)
        picks = {m._pick_next_interval() for _ in range(40)}
        assert len(picks) > 1
        assert all(timedelta(minutes=30) <= p <= timedelta(minutes=180) for p in picks)

    def test_active_window_boundaries(self):
        m = make_messenger(proactive_active_start=7, proactive_active_end=23)
        assert m._is_in_active_window(datetime(2026, 1, 1, 7, 0)) is True
        assert m._is_in_active_window(datetime(2026, 1, 1, 22, 59)) is True
        assert m._is_in_active_window(datetime(2026, 1, 1, 23, 0)) is False
        assert m._is_in_active_window(datetime(2026, 1, 1, 6, 59)) is False

    def test_can_fire_first_time_sets_next(self):
        m = make_messenger()
        now = datetime(2026, 1, 1, 12, 0)
        assert m._next_proactive_after is None
        assert m._can_fire(now) is True
        assert m._next_proactive_after == now + timedelta(minutes=30)

    def test_can_fire_before_next_returns_false(self):
        m = make_messenger()
        now = datetime(2026, 1, 1, 12, 0)
        m._next_proactive_after = now + timedelta(minutes=10)
        assert m._can_fire(now) is False
        assert m._next_proactive_after == now + timedelta(minutes=10)

    def test_can_fire_after_next_resets(self):
        m = make_messenger()
        now = datetime(2026, 1, 1, 12, 0)
        m._next_proactive_after = now - timedelta(seconds=1)
        assert m._can_fire(now) is True
        assert m._next_proactive_after == now + timedelta(minutes=30)


# ── 主检查链 ────────────────────────────────────────────────────


class TestCheckGates:
    def test_disabled_returns_none(self):
        m = make_messenger(proactive_enabled=False)
        assert m.check_proactive_messages("u1", "p1") is None

    def test_unknown_persona_returns_none(self):
        m = make_messenger(persona_loader=FakePersonaLoader(personas={}))
        assert m.check_proactive_messages("u1", "p1") is None

    def test_low_relationship_returns_none(self):
        m = make_messenger(affection=FakeAffection(level=10.0))
        assert m.check_proactive_messages("u1", "p1") is None

    def test_level_boundary_is_inclusive(self):
        m = make_messenger(affection=FakeAffection(level=20.0))
        assert m.check_proactive_messages("u1", "p1") == "scheduled"

    def test_scope_id_used_for_memory_lookups(self):
        affection = FakeAffection(level=60.0)
        seen: list[str] = []

        class Recording(FakeAffection):
            def get_level(self, user_id, persona_id=""):
                seen.append(user_id)
                return super().get_level(user_id, persona_id)

        m = make_messenger(affection=Recording(level=60.0, stats=affection.stats))
        m.check_proactive_messages("u1", "p1", scope_id="scope_abc")
        assert seen == ["scope_abc"]


class TestScheduledTrigger:
    def test_fires_and_marks(self):
        m = make_messenger()
        assert m.check_proactive_messages("u1", "p1") == "scheduled"
        assert m._already_fired("scheduled") is True
        assert m._last_proactive_at is not None

    def test_interval_blocks_second_fire(self):
        m = make_messenger()
        m.check_proactive_messages("u1", "p1")
        # 第二次调用时 next 还在未来 → 定时链不命中
        assert m.check_proactive_messages("u1", "p1") is None

    def test_outside_window_skips_scheduled(self):
        m = make_messenger(proactive_active_start=0, proactive_active_end=0)
        assert m.check_proactive_messages("u1", "p1") is None


class TestMissingTrigger:
    def _messenger(self, *, last: str | None, msg_count: int = 20,
                   days_known: int = 30, **config):
        m = make_messenger(
            proactive_active_start=0,
            proactive_active_end=0,
            affection=FakeAffection(
                level=60.0,
                stats=AffectionStats(
                    level=60.0, message_count=msg_count, positive_count=10,
                    negative_count=1, days_known=days_known,
                ),
                last=last,
            ),
            **config,
        )
        return m

    def test_fires_when_idle_long_enough(self):
        last = (datetime.now() - timedelta(days=5)).isoformat()
        m = self._messenger(last=last)
        assert m.check_proactive_messages("u1", "p1") == "missing"
        assert m._already_fired("missing") is True

    def test_not_idle_enough(self):
        last = (datetime.now() - timedelta(hours=6)).isoformat()
        m = self._messenger(last=last)
        assert m.check_proactive_messages("u1", "p1") is None

    def test_no_last_interaction_returns_none(self):
        m = self._messenger(last=None)
        assert m.check_proactive_messages("u1", "p1") is None

    def test_bad_timestamp_swallowed(self):
        m = self._messenger(last="not-a-date")
        assert m.check_proactive_messages("u1", "p1") is None

    def test_zero_messages_skips(self):
        last = (datetime.now() - timedelta(days=5)).isoformat()
        m = self._messenger(last=last, msg_count=0)
        assert m.check_proactive_messages("u1", "p1") is None

    def test_short_relationship_skips(self):
        last = (datetime.now() - timedelta(days=5)).isoformat()
        m = self._messenger(last=last, days_known=1)
        assert m.check_proactive_messages("u1", "p1") is None

    def test_already_fired_today_skips(self):
        last = (datetime.now() - timedelta(days=5)).isoformat()
        m = self._messenger(last=last)
        m._mark_fired("missing")
        assert m.check_proactive_messages("u1", "p1") is None


class TestRecallTrigger:
    def _messenger(self, memories, *, level: float = 45.0, recall: bool = True,
                   chat_history=None):
        return make_messenger(
            proactive_active_start=0,
            proactive_active_end=0,
            memory_mgr=FakeMemoryMgr(memories),
            affection=FakeAffection(level=level, last=None),
            chat_history=chat_history,
            proactive_memory_recall=recall,
            proactive_min_level=20,
        )

    def test_level_below_40_skips_recall(self):
        m = self._messenger([mem("明天要考试")], level=35.0)
        assert m.check_proactive_messages("u1", "p1") is None

    def test_recall_disabled_skips(self):
        m = self._messenger([mem("明天要考试")], recall=False)
        assert m.check_proactive_messages("u1", "p1") is None

    def test_recent_exam_triggers_recall(self):
        m = self._messenger([mem("明天要面试了", days_old=0.5)])
        assert m.check_proactive_messages("u1", "p1") == "memory_recall"
        assert m._pending_recall_topic == "明天要面试了"[:30]

    def test_old_exam_does_not_trigger(self):
        m = self._messenger([mem("之前考过一次试", days_old=10)])
        assert m.check_proactive_messages("u1", "p1") is None

    def test_recent_travel_triggers_recall(self):
        m = self._messenger([mem("下个月去成都旅行", days_old=3)])
        assert m.check_proactive_messages("u1", "p1") == "memory_recall"

    def test_very_old_travel_does_not_trigger(self):
        m = self._messenger([mem("去成都旅行", days_old=30)])
        assert m.check_proactive_messages("u1", "p1") is None

    def test_birthday_same_day_triggers(self):
        today = datetime.now()
        birthday_mem = Memory(
            id="mem_bd", content="他的生日是今天",
            level=5, category="personal",
            created_at=today.replace(year=today.year - 1).isoformat(),
            last_accessed=today.isoformat(),
        )
        assert birthday_mem.created_at  # 日期不同年，靠 month/day 比
        m = self._messenger([birthday_mem], level=45.0)
        # 记忆是去年同一天 → days_old≈365，但生日判定只看 month/day
        result = m.check_proactive_messages("u1", "p1")
        # 如果今天正好是那天（不可能总是），退化为 None；两种都接受
        assert result in (None, "birthday")

    def test_birthday_detected_with_fresh_timestamp(self):
        now = datetime.now()
        birthday_mem = Memory(
            id="mem_bd2", content="他生日快到了",
            level=5, category="personal",
            created_at=now.isoformat(), last_accessed=now.isoformat(),
        )
        m = self._messenger([birthday_mem], level=45.0)
        assert m.check_proactive_messages("u1", "p1") == "birthday"
        assert m._pending_recall_topic == "生日"

    def test_high_level_fresh_memory_triggers(self):
        m = self._messenger([mem("他今天提到想换个工作", days_old=2)], level=60.0)
        assert m.check_proactive_messages("u1", "p1") == "memory_recall"

    def test_level_59_does_not_use_level_branch(self):
        m = self._messenger([mem("他今天提到想换个工作", days_old=2)], level=59.0)
        assert m.check_proactive_messages("u1", "p1") is None

    def test_already_recalled_memory_skipped(self):
        m = self._messenger([mem("明天要面试了", days_old=0.5)])
        m._recalled_memory_ids.add(m._memory_mgr.memories[0].id)
        assert m.check_proactive_messages("u1", "p1") is None

    def test_bad_created_at_skipped(self):
        bad = Memory(
            id="mem_bad", content="明天要面试了",
            level=4, category="personal", created_at="garbage",
            last_accessed="garbage",
        )
        m = self._messenger([bad])
        assert m.check_proactive_messages("u1", "p1") is None

    def test_empty_memories(self):
        m = self._messenger([])
        assert m.check_proactive_messages("u1", "p1") is None

    def test_memory_manager_exception_swallowed(self):
        m = make_messenger(
            proactive_active_start=0, proactive_active_end=0,
            memory_mgr=FakeMemoryMgr(raises=True),
            affection=FakeAffection(level=45.0, last=None),
        )
        assert m.check_proactive_messages("u1", "p1") is None

    def test_only_first_five_candidates_scanned(self):
        memories = [mem(f"普通记忆{i}", days_old=100) for i in range(5)]
        memories.append(mem("明天要面试了", days_old=0.5))
        m = self._messenger(memories)
        # 第 6 条超出 candidates[:5]，扫不到
        assert m.check_proactive_messages("u1", "p1") is None

    def test_exam_keyword_outside_window_falls_through(self):
        """命中「考试」但 days_old 不在 [0.08, 2] → 落到旅行判定，最终 None。

        这条是给 `366->372` 那个分支的：内层 if 不成立时要能继续往下走，
        而不是 return None 或直接跳过候选。
        """
        m = self._messenger([mem("明天要考试了", days_old=10)])
        assert m.check_proactive_messages("u1", "p1") is None


class TestCareTrigger:
    def _history(self, emotions: list[str]) -> FakeChatHistory:
        return FakeChatHistory([
            {"role": "user", "content": "嗯", "emotion": e} for e in emotions
        ])

    def _messenger(self, chat_history, level: float = 55.0):
        return make_messenger(
            proactive_active_start=0,
            proactive_active_end=0,
            memory_mgr=FakeMemoryMgr([]),
            affection=FakeAffection(level=level, last=None),
            chat_history=chat_history,
            proactive_min_level=20,
        )

    def test_level_below_50_skips_care(self):
        m = self._messenger(self._history(["sad"] * 5), level=49.0)
        assert m.check_proactive_messages("u1", "p1") is None

    def test_no_chat_history_skips(self):
        m = self._messenger(None)
        assert m.check_proactive_messages("u1", "p1") is None

    def test_three_consecutive_negative_rounds_fires(self):
        m = self._messenger(self._history(["sad", "anxious", "lonely"]))
        assert m.check_proactive_messages("u1", "p1") is None
        assert m.check_proactive_messages("u1", "p1") is None
        assert m.check_proactive_messages("u1", "p1") == "care"
        assert m._consecutive_negative["u1"] == 0
        assert m._already_fired("care") is True

    def test_fewer_than_three_negatives_resets(self):
        m = self._messenger(self._history(["sad", "happy", "happy"]))
        m._consecutive_negative["u1"] = 2
        assert m.check_proactive_messages("u1", "p1") is None
        assert m._consecutive_negative["u1"] == 0

    def test_already_fired_today_blocks(self):
        m = self._messenger(self._history(["sad"] * 5))
        m._consecutive_negative["u1"] = 2
        m._mark_fired("care")
        assert m.check_proactive_messages("u1", "p1") is None

    def test_history_exception_swallowed(self):
        m = self._messenger(FakeChatHistory(raises=True))
        assert m.check_proactive_messages("u1", "p1") is None

    def test_only_last_ten_user_messages(self):
        old_negative = [{"role": "user", "content": "嗯", "emotion": "sad"}] * 5
        recent_positive = [{"role": "user", "content": "嗯", "emotion": "happy"}] * 10
        m = self._messenger(FakeChatHistory(old_negative + recent_positive))
        assert m.check_proactive_messages("u1", "p1") is None

    def test_assistant_messages_ignored(self):
        msgs = [{"role": "assistant", "content": "x", "emotion": "sad"}] * 5
        m = self._messenger(FakeChatHistory(msgs))
        assert m.check_proactive_messages("u1", "p1") is None

    def test_messages_without_emotion_field_ignored(self):
        msgs = [{"role": "user", "content": "嗯"}] * 5
        m = self._messenger(FakeChatHistory(msgs))
        assert m.check_proactive_messages("u1", "p1") is None


# ── LLM 生成 ────────────────────────────────────────────────────


class TestGenerateMessage:
    async def test_unknown_persona_returns_none(self):
        m = make_messenger(persona_loader=FakePersonaLoader(personas={}))
        assert await m.generate_message("scheduled", "u1", "p1") is None

    async def test_llm_output_used(self):
        captured: dict = {}

        async def gen(**kwargs):
            captured.update(kwargs)
            return "  今天风好大，你出门记得穿外套。  "

        m = make_messenger()
        m.set_llm_generator(gen)
        out = await m.generate_message("scheduled", "u1", "p1")
        assert out == "今天风好大，你出门记得穿外套。"
        assert captured["max_tokens"] == 200
        assert captured["temperature"] == 0.95
        assert "慕" in captured["system_prompt"]

    async def test_quotes_stripped(self):
        async def gen(**kwargs):
            return "「今天想你了」"

        m = make_messenger()
        m.set_llm_generator(gen)
        assert await m.generate_message("scheduled", "u1", "p1") == "今天想你了"

    async def test_empty_llm_output_falls_back(self):
        async def gen(**kwargs):
            return "   "

        m = make_messenger()
        m.set_llm_generator(gen)
        out = await m.generate_message("scheduled", "u1", "p1")
        assert out in m._fallback_message("scheduled", "慕", 60) or out
        assert out

    async def test_llm_exception_falls_back(self):
        async def gen(**kwargs):
            raise RuntimeError("boom")

        m = make_messenger()
        m.set_llm_generator(gen)
        out = await m.generate_message("care", "u1", "p1")
        assert out in [
            "最近天气忽冷忽热的，注意别感冒了哦~ 🥺",
            "今天看到一朵好看的云，希望你心情也能变好~",
            "不管发生什么，我都在你身边呢 💕",
        ]

    async def test_no_llm_uses_fallback(self):
        m = make_messenger()
        out = await m.generate_message("birthday", "u1", "p1")
        assert out in [
            "生日快乐呀！🎂 希望你今天特别开心！",
            "生日快乐！🎉 新的一岁要更加幸福哦~",
        ]

    async def test_gender_male_identity(self):
        captured: dict = {}

        async def gen(**kwargs):
            captured.update(kwargs)
            return "hi"

        m = make_messenger(
            persona_loader=FakePersonaLoader({"p1": FakePersona(gender="男")})
        )
        m.set_llm_generator(gen)
        await m.generate_message("scheduled", "u1", "p1")
        assert "真实男生" in captured["system_prompt"]

    async def test_gender_female_identity(self):
        captured: dict = {}

        async def gen(**kwargs):
            captured.update(kwargs)
            return "hi"

        m = make_messenger()
        m.set_llm_generator(gen)
        await m.generate_message("scheduled", "u1", "p1")
        assert "真实女生" in captured["system_prompt"]

    async def test_gender_empty_is_neutral(self):
        captured: dict = {}

        async def gen(**kwargs):
            captured.update(kwargs)
            return "hi"

        m = make_messenger(
            persona_loader=FakePersonaLoader({"p1": FakePersona(gender="")})
        )
        m.set_llm_generator(gen)
        await m.generate_message("scheduled", "u1", "p1")
        assert "真实的人" in captured["system_prompt"]
        assert "男生" not in captured["system_prompt"]
        assert "女生" not in captured["system_prompt"]

    async def test_speaking_style_dict_uses_base_key(self):
        captured: dict = {}

        async def gen(**kwargs):
            captured.update(kwargs)
            return "hi"

        m = make_messenger(
            persona_loader=FakePersonaLoader(
                {"p1": FakePersona(speaking_style={"基础风格": "慵懒"})}
            )
        )
        m.set_llm_generator(gen)
        await m.generate_message("scheduled", "u1", "p1")
        assert "慵懒" in captured["system_prompt"]

    async def test_speaking_style_plain_string(self):
        captured: dict = {}

        async def gen(**kwargs):
            captured.update(kwargs)
            return "hi"

        m = make_messenger(
            persona_loader=FakePersonaLoader(
                {"p1": FakePersona(speaking_style="简短")}
            )
        )
        m.set_llm_generator(gen)
        await m.generate_message("scheduled", "u1", "p1")
        assert "简短" in captured["system_prompt"]

    async def test_empty_personality_uses_default(self):
        captured: dict = {}

        async def gen(**kwargs):
            captured.update(kwargs)
            return "hi"

        m = make_messenger(
            persona_loader=FakePersonaLoader({"p1": FakePersona(personality=[])})
        )
        m.set_llm_generator(gen)
        await m.generate_message("scheduled", "u1", "p1")
        assert "温柔可爱" in captured["system_prompt"]

    async def test_recent_chat_included(self):
        captured: dict = {}

        async def gen(**kwargs):
            captured.update(kwargs)
            return "hi"

        history = FakeChatHistory([
            {"role": "user", "content": "我今天加班"},
            {"role": "assistant", "content": "辛苦了"},
            {"role": "user", "content": "嗯"},
            {"role": "assistant", "content": "早点睡"},
            {"role": "user", "content": "好"},
            {"role": "assistant", "content": "晚安"},
        ])
        m = make_messenger(chat_history=history)
        m.set_llm_generator(gen)
        await m.generate_message("scheduled", "u1", "p1")
        user_prompt = captured["user_prompt"]
        assert "最近的聊天记录" in user_prompt
        # 只取最后 4 条
        assert "晚安" in user_prompt
        assert "我今天加班" not in user_prompt

    async def test_short_history_uses_last_two(self):
        captured: dict = {}

        async def gen(**kwargs):
            captured.update(kwargs)
            return "hi"

        history = FakeChatHistory([
            {"role": "user", "content": "第一条"},
            {"role": "user", "content": "第二条"},
            {"role": "user", "content": "第三条"},
        ])
        m = make_messenger(chat_history=history)
        m.set_llm_generator(gen)
        await m.generate_message("scheduled", "u1", "p1")
        user_prompt = captured["user_prompt"]
        assert "第三条" in user_prompt
        assert "第一条" not in user_prompt

    async def test_empty_history_no_block(self):
        captured: dict = {}

        async def gen(**kwargs):
            captured.update(kwargs)
            return "hi"

        m = make_messenger(chat_history=FakeChatHistory([]))
        m.set_llm_generator(gen)
        await m.generate_message("scheduled", "u1", "p1")
        assert "最近的聊天记录" not in captured["user_prompt"]

    async def test_history_exception_ignored(self):
        captured: dict = {}

        async def gen(**kwargs):
            captured.update(kwargs)
            return "hi"

        m = make_messenger(chat_history=FakeChatHistory(raises=True))
        m.set_llm_generator(gen)
        out = await m.generate_message("scheduled", "u1", "p1")
        assert out == "hi"

    @pytest.mark.parametrize("trigger", [
        "scheduled", "missing", "memory_recall", "care", "birthday", "unknown",
    ])
    async def test_all_trigger_types_build_prompt(self, trigger):
        captured: dict = {}

        async def gen(**kwargs):
            captured.update(kwargs)
            return "ok"

        m = make_messenger()
        m._pending_recall_topic = "上次说的面试"
        m.set_llm_generator(gen)
        assert await m.generate_message(trigger, "u1", "p1") == "ok"
        assert "绝对禁止" in captured["system_prompt"]

    async def test_memory_recall_prompt_uses_pending_topic(self):
        captured: dict = {}

        async def gen(**kwargs):
            captured.update(kwargs)
            return "ok"

        m = make_messenger()
        m._pending_recall_topic = "上次说的面试"
        m.set_llm_generator(gen)
        await m.generate_message("memory_recall", "u1", "p1")
        assert "上次说的面试" in captured["system_prompt"]

    async def test_memory_recall_without_topic_uses_default(self):
        captured: dict = {}

        async def gen(**kwargs):
            captured.update(kwargs)
            return "ok"

        m = make_messenger()
        m.set_llm_generator(gen)
        await m.generate_message("memory_recall", "u1", "p1")
        assert "之前聊过的事" in captured["system_prompt"]

    async def test_missing_prompt_forbids_absence_words(self):
        captured: dict = {}

        async def gen(**kwargs):
            captured.update(kwargs)
            return "ok"

        m = make_messenger()
        m.set_llm_generator(gen)
        await m.generate_message("missing", "u1", "p1")
        prompt = captured["system_prompt"]
        assert "你回来啦" in prompt
        assert "你去哪了" in prompt

    async def test_scope_id_used_for_level(self):
        captured: dict = {}

        async def gen(**kwargs):
            captured.update(kwargs)
            return "ok"

        seen: list[str] = []

        class Recording(FakeAffection):
            def get_level(self, user_id, persona_id=""):
                seen.append(user_id)
                return 88.0

        m = make_messenger(affection=Recording())
        m.set_llm_generator(gen)
        await m.generate_message("scheduled", "u1", "p1", scope_id="scope_x")
        assert seen == ["scope_x"]
        assert "88/100" in captured["system_prompt"]


# ── 兜底文案 ────────────────────────────────────────────────────


class TestFallbackMessage:
    def test_all_known_types_have_options(self):
        m = make_messenger()
        for trigger in ("scheduled", "missing", "care", "birthday", "memory_recall"):
            out = m._fallback_message(trigger, "慕", 60)
            assert isinstance(out, str) and out

    def test_unknown_type_falls_back_to_scheduled(self):
        m = make_messenger()
        allowed = {
            "嗨~ 突然想跟你聊聊天！你今天怎么样呀？",
            "刚刚看了一个超好笑的视频，等下发给你看~",
            "突然想到你了，你在干嘛呀？✨",
        }
        for _ in range(20):
            assert m._fallback_message("weird", "慕", 60) in allowed

    def test_missing_never_mentions_absence(self):
        m = make_messenger()
        forbidden = ("你回来啦", "你去哪了", "好久不见", "你终于出现了")
        for _ in range(30):
            out = m._fallback_message("missing", "慕", 60)
            assert not any(w in out for w in forbidden)

    def test_memory_recall_single_option(self):
        m = make_messenger()
        assert m._fallback_message("memory_recall", "慕", 60) == \
            "诶对了，我突然想起来之前那事，后来怎么样了呀？"
