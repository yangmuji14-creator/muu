"""未完成事件（open loops）引擎测试。

覆盖:
- detect()：从中/英消息识别未来事件，去重，分类
- 单轨存储：只落 data/open_loops.json（SQLite 半区已删）
- _check_resolved：用户说「考完了」等词时事件关闭
- get_pending / get_context / get_follow_up / update_status / expire_old
- OpenLoop 的属性：is_active / is_closed / is_expired / days_until_expected
"""

from datetime import datetime, timedelta

import pytest

from core.memory.open_loop import (
    OpenLoop,
    OpenLoopCategory,
    OpenLoopEngine,
    OpenLoopStatus,
)


@pytest.fixture()
def engine(tmp_path):
    return OpenLoopEngine(tmp_path)


class TestDetect:
    def test_tomorrow_event(self, engine):
        created = engine.detect("u1", "我明天要面试了")
        assert len(created) == 1
        assert created[0].title == "要面试了"
        assert created[0].category == OpenLoopCategory.INTERVIEW

    def test_next_week_event(self, engine):
        created = engine.detect("u1", "下周要去成都出差")
        assert len(created) == 1
        assert created[0].expected_date is not None

    def test_travel_classification(self, engine):
        created = engine.detect("u1", "下个月去旅行")
        assert created[0].category == OpenLoopCategory.TRAVEL

    def test_health_classification(self, engine):
        created = engine.detect("u1", "最近感冒了")
        assert created[0].category == OpenLoopCategory.HEALTH

    def test_plain_message_creates_nothing(self, engine):
        assert engine.detect("u1", "今天天气不错") == []

    def test_duplicate_not_created_twice(self, engine):
        engine.detect("u1", "我明天要面试了")
        second = engine.detect("u1", "我明天还是要面试了")
        assert second == []
        assert len(engine.get_pending("u1")) == 1

    def test_users_are_isolated(self, engine):
        engine.detect("u1", "我明天要面试了")
        assert engine.get_pending("u2") == []
        assert len(engine.get_pending("u1")) == 1


class TestPersistence:
    def test_writes_json_only(self, engine, tmp_path):
        engine.detect("u1", "我明天要面试了")
        assert (tmp_path / "open_loops.json").exists()
        # 单轨：不再有 sqlite 文件
        assert not (tmp_path / "open_loops.db").exists()

    def test_survives_reload(self, tmp_path):
        e1 = OpenLoopEngine(tmp_path)
        e1.detect("u1", "我明天要面试了")
        e2 = OpenLoopEngine(tmp_path)
        assert len(e2.get_pending("u1")) == 1

    def test_corrupt_json_does_not_raise(self, tmp_path):
        (tmp_path / "open_loops.json").write_text("{not json", encoding="utf-8")
        e = OpenLoopEngine(tmp_path)  # 不应抛异常
        assert e.get_pending("u1") == []


class TestResolve:
    def test_resolve_keyword_closes_loop(self, engine):
        engine.detect("u1", "我明天要面试了")
        engine.detect("u1", "面试通过了")
        pending = engine.get_pending("u1")
        assert all(l.status != "pending" for l in pending) or pending == []

    def test_unrelated_message_keeps_pending(self, engine):
        engine.detect("u1", "我明天要面试了")
        engine.detect("u1", "今天吃了火锅")
        assert len(engine.get_pending("u1")) == 1


class TestQuery:
    def test_get_context_format(self, engine):
        engine.detect("u1", "我明天要面试了")
        ctx = engine.get_context("u1")
        assert ctx.startswith("【用户正在经历的事情】")
        assert "要面试了" in ctx

    def test_get_context_empty_when_nothing_pending(self, engine):
        assert engine.get_context("u1") == ""

    def test_get_pending_returns_open_loops(self, engine):
        engine.detect("u1", "我明天要面试了")
        pending = engine.get_pending("u1")
        assert all(isinstance(l, OpenLoop) for l in pending)

    def test_update_status(self, engine):
        loop = engine.detect("u1", "我明天要面试了")[0]
        assert engine.update_status("u1", loop.id, "resolved") is True
        assert engine.get_pending("u1") == []

    def test_update_status_missing_id_returns_false(self, engine):
        assert engine.update_status("u1", "loop_nope", "resolved") is False


class TestFollowUp:
    def test_no_follow_up_when_too_new(self, engine):
        engine.detect("u1", "我明天要面试了")
        assert engine.get_follow_up("u1") is None

    def test_follow_up_after_a_day(self, engine):
        loop = engine.detect("u1", "我明天要面试了")[0]
        loop.created_at = (datetime.now() - timedelta(days=2)).isoformat()
        engine._save()
        msg = engine.get_follow_up("u1")
        assert msg is not None
        assert "要面试了" in msg

    def test_ask_count_increments(self, engine):
        loop = engine.detect("u1", "我明天要面试了")[0]
        loop.created_at = (datetime.now() - timedelta(days=2)).isoformat()
        engine._save()
        engine.get_follow_up("u1")
        assert engine.get_pending("u1")[0].ask_count == 1

    def test_max_two_asks(self, engine):
        loop = engine.detect("u1", "我明天要面试了")[0]
        loop.created_at = (datetime.now() - timedelta(days=10)).isoformat()
        loop.last_asked = (datetime.now() - timedelta(days=10)).isoformat()
        loop.ask_count = 2
        engine._save()
        assert engine.get_follow_up("u1") is None


class TestExpire:
    def test_old_loop_expires(self, engine):
        loop = engine.detect("u1", "我明天要面试了")[0]
        loop.created_at = (datetime.now() - timedelta(days=40)).isoformat()
        engine._save()
        assert engine.expire_old("u1", max_days=30) == 1
        assert engine.get_pending("u1") == []

    def test_fresh_loop_not_expired(self, engine):
        engine.detect("u1", "我明天要面试了")
        assert engine.expire_old("u1", max_days=30) == 0


class TestOpenLoopModel:
    def test_pending_is_active(self):
        loop = OpenLoop(id="l1", title="x", status="pending")
        assert loop.is_active is True
        assert loop.is_closed is False

    @pytest.mark.parametrize("status", ["resolved", "failed", "abandoned"])
    def test_closed_states(self, status):
        loop = OpenLoop(id="l1", title="x", status=status)
        assert loop.is_active is False
        assert loop.is_closed is True

    def test_no_expected_date_never_expires(self):
        loop = OpenLoop(id="l1", title="x")
        assert loop.is_expired is False
        assert loop.days_until_expected is None

    def test_expected_date_in_past_expires_after_grace(self):
        past = (datetime.now() - timedelta(days=5)).isoformat()
        loop = OpenLoop(id="l1", title="x", expected_date=past)
        assert loop.is_expired is True

    def test_expected_date_in_future_not_expired(self):
        future = (datetime.now() + timedelta(days=5)).isoformat()
        loop = OpenLoop(id="l1", title="x", expected_date=future)
        assert loop.is_expired is False

    def test_bad_expected_date_does_not_raise(self):
        loop = OpenLoop(id="l1", title="x", expected_date="not-a-date")
        assert loop.is_expired is False
        assert loop.days_until_expected is None

    def test_roundtrip_dict(self):
        loop = OpenLoop(id="l1", user_id="u1", title="面试", category="interview")
        restored = OpenLoop.from_dict(loop.to_dict())
        assert restored.id == loop.id
        assert restored.title == loop.title
        assert restored.category == loop.category

    def test_status_enum_values(self):
        assert OpenLoopStatus.PENDING.value == "pending"
        assert OpenLoopStatus.RESOLVED.value == "resolved"
        assert OpenLoopStatus.FAILED.value == "failed"
        assert OpenLoopStatus.ABANDONED.value == "abandoned"
