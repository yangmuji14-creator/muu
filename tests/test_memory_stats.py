"""聊天统计与 ASCII 图表测试

覆盖 `core/memory/stats.py`：`ChatStats` 的各项统计、三个图表绘制工具、
`format_dashboard` 的整体输出。

这一层是纯函数（输入 dict 列表、输出数字/字符串），不碰数据库、不联网。
时间相关的用例都用「相对今天」构造时间戳，避免固定日期过几天就变红。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.memory.stats import (
    EMOTION_LABELS,
    ChatStats,
    _bar_horizontal,
    _bar_vertical,
    _sparkline,
    format_dashboard,
)


def _msg(role: str = "user", content: str = "你好", *, hours_ago: float | None = 0,
         emotion: str | None = None, intensity: float | None = None) -> dict:
    """构造一条消息。`hours_ago=None` 表示没有 timestamp 字段。"""
    msg: dict = {"role": role, "content": content}
    if hours_ago is not None:
        msg["timestamp"] = (datetime.now() - timedelta(hours=hours_ago)).isoformat()
    if emotion is not None:
        msg["emotion"] = emotion
    if intensity is not None:
        msg["emotion_intensity"] = intensity
    return msg


class TestEmotionLabels:
    def test_covers_exactly_the_eight_core_emotions(self):
        # 键必须是这 8 个：core/emotion/analyzer.py 的 EmotionType 枚举
        assert set(EMOTION_LABELS) == {
            "happy", "sad", "angry", "neutral",
            "excited", "lonely", "anxious", "love",
        }

    def test_every_label_is_non_empty_chinese(self):
        for key, label in EMOTION_LABELS.items():
            assert isinstance(label, str) and label.strip(), key
            assert not label.isascii(), f"{key} 的标签应该翻成中文"

    def test_label_text_differs_from_analyzer_on_purpose(self):
        # 统计页用「中性/孤独」这种书面词，情绪分析器用「平静/孤单」更口语。
        # 两处文案不同是有意的 —— 这条断言是提醒：别为了「统一」去改其中一边，
        # 它们服务的是不同界面。
        assert EMOTION_LABELS["neutral"] == "中性"
        assert EMOTION_LABELS["lonely"] == "孤独"


class TestParseMessages:
    def test_empty_input(self):
        assert ChatStats([])._parsed == []

    def test_keeps_known_fields_and_drops_others(self):
        stats = ChatStats([{"role": "user", "content": "hi", "image": "x.png"}])
        parsed = stats._parsed[0]
        assert parsed["role"] == "user"
        assert parsed["content"] == "hi"
        assert "image" not in parsed

    def test_missing_role_and_content_default_to_empty(self):
        parsed = ChatStats([{}])._parsed[0]
        assert parsed["role"] == ""
        assert parsed["content"] == ""
        assert parsed["timestamp"] is None

    @pytest.mark.parametrize("bad", ["", "不是时间", "2026-13-45T99:99:99"])
    def test_bad_timestamp_degrades_to_none(self, bad):
        parsed = ChatStats([{"role": "user", "content": "x", "timestamp": bad}])._parsed[0]
        assert parsed["timestamp"] is None

    def test_good_timestamp_parsed(self):
        ts = "2026-10-22T20:38:18"
        parsed = ChatStats([{"role": "user", "content": "x", "timestamp": ts}])._parsed[0]
        assert parsed["timestamp"] == datetime.fromisoformat(ts)


class TestCounts:
    def test_empty_stats_do_not_divide_by_zero(self):
        stats = ChatStats([])
        assert stats.total_messages() == 0
        assert stats.user_messages() == 0
        assert stats.assistant_messages() == 0
        assert stats.avg_message_length() == 0

    def test_counts_by_role(self):
        stats = ChatStats([
            _msg("user", "abc"),
            _msg("assistant", "de"),
            _msg("user", "fghi"),
            _msg("system", "被忽略在 user/assistant 之外"),
        ])
        assert stats.total_messages() == 4
        assert stats.user_messages() == 2
        assert stats.assistant_messages() == 1

    def test_avg_length_counts_all_roles(self):
        # 平均长度算的是全部消息，不分 role。3 + 2 + 4 + 6 = 15 → 3.75
        stats = ChatStats([
            _msg("user", "abc"),
            _msg("assistant", "de"),
            _msg("user", "fghi"),
            _msg("system", "系统提示词呀"),
        ])
        assert stats.avg_message_length() == pytest.approx(3.75)

    def test_avg_length_is_zero_for_all_empty_content(self):
        stats = ChatStats([_msg("user", ""), _msg("user", "")])
        assert stats.avg_message_length() == 0


class TestHourlyDistribution:
    def test_always_returns_all_24_keys(self):
        dist = ChatStats([]).hourly_distribution()
        assert len(dist) == 24
        assert set(dist) == set(range(24))
        assert all(v == 0 for v in dist.values())

    def test_messages_without_timestamp_are_skipped(self):
        dist = ChatStats([_msg(hours_ago=None)]).hourly_distribution()
        assert sum(dist.values()) == 0

    def test_counts_land_in_the_right_hour(self):
        stamp = datetime(2026, 1, 1, 9, 30, 0).isoformat()
        msgs = [{"role": "user", "content": "x", "timestamp": stamp}] * 3
        dist = ChatStats(msgs).hourly_distribution()
        assert dist[9] == 3
        assert sum(dist.values()) == 3


class TestEmotionDistribution:
    def test_empty(self):
        assert ChatStats([]).emotion_distribution() == {}

    def test_messages_without_emotion_are_skipped(self):
        stats = ChatStats([_msg(emotion=None), _msg(emotion="happy")])
        assert stats.emotion_distribution() == {"happy": 1}

    def test_sorted_descending_by_count(self):
        stats = ChatStats([
            _msg(emotion="sad"),
            _msg(emotion="happy"), _msg(emotion="happy"), _msg(emotion="happy"),
            _msg(emotion="sad"), _msg(emotion="sad"),
            _msg(emotion="angry"), _msg(emotion="angry"),
        ])
        # sad 与 happy 同为 3 条，Counter.most_common() 对同分项按*插入顺序*给，
        # sad 先出现所以排前面。这条断言同时锁住「同分不重排」的契约。
        assert list(stats.emotion_distribution().items()) == [
            ("sad", 3), ("happy", 3), ("angry", 2),
        ]

    def test_ties_keep_first_appearance_order(self):
        # Counter.most_common() 对同分项按插入顺序给，不保证别的次序 ——
        # 这条锁住「同分不重排」，前端柱状图的顺序才不会每次刷新都跳。
        stats = ChatStats([_msg(emotion="sad"), _msg(emotion="happy")])
        assert [k for k, _ in stats.emotion_distribution().items()] == ["sad", "happy"]


class TestDailyMessageCounts:
    def test_default_is_seven_days(self):
        counts = ChatStats([]).daily_message_counts()
        assert len(counts) == 7

    def test_keys_are_month_day_and_last_key_is_today(self):
        counts = ChatStats([]).daily_message_counts(3)
        assert list(counts) == [
            (datetime.now() - timedelta(days=d)).strftime("%m/%d") for d in (2, 1, 0)
        ]

    def test_custom_day_count(self):
        assert len(ChatStats([]).daily_message_counts(1)) == 1
        assert len(ChatStats([]).daily_message_counts(30)) == 30

    def test_today_message_lands_in_last_bucket(self):
        counts = ChatStats([_msg(hours_ago=0)]).daily_message_counts(7)
        assert list(counts.values())[-1] == 1

    def test_message_outside_window_is_dropped(self):
        counts = ChatStats([_msg(hours_ago=24 * 30)]).daily_message_counts(7)
        assert sum(counts.values()) == 0


class TestMostActiveHour:
    def test_no_timestamps_falls_back_to_zero_zero(self):
        # 注意：空 dict 也有 24 个 key，所以 max() 会挑出一个 0 —— 这里断言的是
        # 「没有消息时结果是 0 点 0 条」这个对外行为。
        assert ChatStats([]).most_active_hour() == (0, 0)

    def test_picks_the_busiest_hour(self):
        stamp = datetime(2026, 1, 1, 14, 0, 0).isoformat()
        quiet = datetime(2026, 1, 1, 3, 0, 0).isoformat()
        msgs = [{"role": "user", "content": "x", "timestamp": stamp}] * 5
        msgs.append({"role": "user", "content": "x", "timestamp": quiet})
        assert ChatStats(msgs).most_active_hour() == (14, 5)


class TestPeakToTroughRatio:
    def test_zero_messages_returns_one(self):
        # 一个值都没有 → 提前 return 1.0，不是除以 0
        assert ChatStats([]).peak_to_trough_ratio() == 1.0

    def test_single_active_hour_returns_one(self):
        stamp = datetime(2026, 1, 1, 9, 0, 0).isoformat()
        msgs = [{"role": "user", "content": "x", "timestamp": stamp}] * 4
        # 只有一个非零值 → 也走 1.0 分支
        assert ChatStats(msgs).peak_to_trough_ratio() == 1.0

    def test_ratio_between_busiest_and_quietest_nonzero_hour(self):
        busy = datetime(2026, 1, 1, 9, 0, 0).isoformat()
        quiet = datetime(2026, 1, 1, 21, 0, 0).isoformat()
        msgs = [{"role": "user", "content": "x", "timestamp": busy}] * 6
        msgs += [{"role": "user", "content": "x", "timestamp": quiet}] * 2
        assert ChatStats(msgs).peak_to_trough_ratio() == pytest.approx(3.0)

    def test_zero_hours_are_excluded_from_the_trough(self):
        # 22 个小时是 0，只有 2 个小时有值。若把 0 算进谷值，比值会炸成 inf。
        busy = datetime(2026, 1, 1, 9, 0, 0).isoformat()
        quiet = datetime(2026, 1, 1, 21, 0, 0).isoformat()
        msgs = [{"role": "user", "content": "x", "timestamp": busy}] * 10
        msgs += [{"role": "user", "content": "x", "timestamp": quiet}] * 5
        ratio = ChatStats(msgs).peak_to_trough_ratio()
        assert ratio == pytest.approx(2.0)
        assert ratio != float("inf")


class TestBarHorizontal:
    def test_zero_max_draws_no_bar(self):
        out = _bar_horizontal("开心", 0, 0)
        assert "█" not in out
        assert out.endswith(" 0")

    def test_full_value_fills_the_width(self):
        out = _bar_horizontal("开心", 4, 4, width=20)
        assert out.count("█") == 20

    def test_half_value_fills_half_the_width(self):
        out = _bar_horizontal("开心", 5, 10, width=20)
        assert out.count("█") == 10

    def test_width_is_respected(self):
        assert _bar_horizontal("a", 3, 3, width=6).count("█") == 6
        assert _bar_horizontal("a", 3, 3, width=30).count("█") == 30

    def test_value_is_printed_at_the_end(self):
        assert _bar_horizontal("开心", 7, 10).endswith(" 7")


class TestBarVertical:
    def test_empty_values_says_no_data(self):
        assert _bar_vertical([], []) == "  (无数据)"

    def test_all_zero_says_no_data(self):
        assert _bar_vertical([0, 0, 0], ["a", "b", "c"]) == "  (无数据)"

    def test_draws_height_rows_plus_one_label_line(self):
        out = _bar_vertical([1, 2, 3], ["a", "b", "c"], height=8)
        assert len(out.split("\n")) == 8 + 1

    def test_last_line_is_the_x_axis_labels(self):
        out = _bar_vertical([1, 2, 3], ["a", "b", "c"], height=8)
        assert out.split("\n")[-1] == "   a  b  c"

    def test_contains_bars(self):
        out = _bar_vertical([3, 1], ["x", "y"], height=4)
        assert "█" in out


class TestSparkline:
    def test_empty_input(self):
        assert _sparkline([]) == ""

    def test_length_matches_input(self):
        assert len(_sparkline([1, 2, 3, 4, 5])) == 5

    def test_all_zero_uses_lowest_glyph(self):
        assert _sparkline([0, 0, 0]) == "▁▁▁"

    def test_max_value_uses_highest_glyph(self):
        assert _sparkline([0, 9])[-1] == "█"

    def test_only_uses_the_eight_spark_glyphs(self):
        out = _sparkline(list(range(20)))
        assert set(out) <= set("▁▂▃▄▅▆▇█")


class TestFormatDashboard:
    def test_contains_title(self):
        assert "聊天数据仪表盘" in format_dashboard(ChatStats([]))

    def test_returns_newline_joined_text(self):
        assert "\n" in format_dashboard(ChatStats([]))

    def test_reports_zero_counts_for_empty_input(self):
        out = format_dashboard(ChatStats([]))
        assert "消息总数：0" in out
        assert "你：0 条 | AI：0 条" in out

    def test_skips_sections_without_data(self):
        out = format_dashboard(ChatStats([]))
        assert "情感分布" not in out
        assert "最近 7 天趋势" not in out
        assert "消息时间分布" not in out

    def test_shows_emotion_section_when_emotions_exist(self):
        stats = ChatStats([_msg(emotion="happy"), _msg(emotion="happy"), _msg(emotion="sad")])
        out = format_dashboard(stats)
        assert "情感分布" in out
        assert "开心" in out      # EMOTION_LABELS["happy"]
        assert "难过" in out      # EMOTION_LABELS["sad"]

    def test_shows_daily_trend_when_messages_exist(self):
        out = format_dashboard(ChatStats([_msg(hours_ago=0)]))
        assert "最近 7 天趋势" in out

    def test_shows_hourly_section_when_messages_exist(self):
        out = format_dashboard(ChatStats([_msg(hours_ago=0)]))
        assert "消息时间分布" in out

    def test_many_active_hours_are_grouped_by_three(self):
        stamps = []
        for hour in range(24):
            stamps.append({"role": "user", "content": "x",
                           "timestamp": datetime(2026, 1, 1, hour, 0, 0).isoformat()})
        out = format_dashboard(ChatStats(stamps))
        # >12 个活跃时段会按 3 小时分组，标签变成 "00h" "03h" ...
        assert "00h" in out
        assert "21h" in out

    def test_avg_length_is_rounded_to_integer(self):
        out = format_dashboard(ChatStats([_msg("user", "abc"), _msg("user", "abcd")]))
        # 3.5 → f"{x:.0f}" → "4"
        assert "平均长度：4 字符" in out

    def test_output_ends_with_a_rule_line(self):
        out = format_dashboard(ChatStats([]))
        assert out.rstrip().endswith("─" * 44)
