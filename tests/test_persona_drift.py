"""人格漂移监测器（core/persona/drift_monitor.py）。

纯规则模块，没有 LLM、没有 IO，唯一的外部依赖是 loguru。测试盯四件事：

1. 三个维度（语言风格 / 性格表达 / 价值观）各自的判据与扣分；
2. `consistency_score` 是三者的**算术平均**，`drift_score = 1 - 它`；
3. `passed` 的阈值是 0.95（含等号）；
4. 空回复列表必须给满分而不是崩（新会话第一轮就是空）。

注意 `_check_language_style` 的 emoji 检查要 >5 条回复才启动，
`_check_personality_expression` 的长度检查却是任何非空列表都跑 ——
两个口径不一样，测试里分开断言。
"""

from __future__ import annotations

import pytest

from core.persona.drift_monitor import PersonaDriftMonitor, PersonaDriftReport


@pytest.fixture()
def monitor():
    return PersonaDriftMonitor()


class TestReportModel:
    def test_passed_at_threshold(self):
        r = PersonaDriftReport("u", "p", 1, consistency_score=0.95, drift_score=0.05)
        assert r.passed is True

    def test_failed_below_threshold(self):
        r = PersonaDriftReport("u", "p", 1, consistency_score=0.9499, drift_score=0.05)
        assert r.passed is False

    def test_defaults(self):
        r = PersonaDriftReport("u", "p", 1, 1.0, 0.0)
        assert r.suggestions == []
        assert r.details == {}
        assert r.created_at

    def test_created_at_is_isoformat(self):
        from datetime import datetime

        r = PersonaDriftReport("u", "p", 1, 1.0, 0.0)
        datetime.fromisoformat(r.created_at)


class TestShouldCheck:
    def test_interval_is_100(self, monitor):
        assert monitor.CHECK_INTERVAL == 100

    def test_exactly_at_interval(self, monitor):
        assert monitor.should_check(100, 0) is True

    def test_below_interval(self, monitor):
        assert monitor.should_check(99, 0) is False

    def test_relative_to_last_check(self, monitor):
        assert monitor.should_check(150, 50) is True
        assert monitor.should_check(140, 50) is False

    def test_negative_delta_not_triggered(self, monitor):
        """对话数被重置（比如换了人设）时不能误触发。"""
        assert monitor.should_check(10, 500) is False


class TestEmptyInput:
    def test_empty_replies_gives_perfect_score(self, monitor):
        report = monitor.analyze("u1", "girlfriend_001", 0, [])
        assert report.consistency_score == 1.0
        assert report.drift_score == 0.0
        assert report.passed is True
        assert report.suggestions == []

    def test_empty_replies_keeps_ids(self, monitor):
        report = monitor.analyze("u1", "p1", 42, [])
        assert report.user_id == "u1"
        assert report.persona_id == "p1"
        assert report.conversation_count == 42


class TestLanguageStyle:
    def test_stable_lengths_no_issue(self, monitor):
        score, issues = monitor._check_language_style("你好呀", ["你好呀", "在的哦", "怎么啦"])
        assert issues == []
        assert score == 1.0

    def test_abrupt_length_jump_flagged(self, monitor):
        """相邻两条回复长度差 5 倍以上就报「波动过大」。"""
        _, issues = monitor._check_language_style(" ".join(["嗨"] * 1), ["嗨", "哈" * 20])
        assert any("波动过大" in i for i in issues)

    def test_ratio_of_exactly_five_not_flagged(self, monitor):
        """判据是 `ratio > 5`，正好 5 倍不报。"""
        _, issues = monitor._check_language_style("", ["a" * 5, "b" * 25])
        assert issues == []

    def test_zero_length_reply_skipped_in_ratio(self, monitor):
        """空回复不参与比值计算，否则除零。"""
        _, issues = monitor._check_language_style("", ["", "x"])
        assert issues == []

    def test_only_first_length_issue_reported(self, monitor):
        """长度波动只报一次（break），不然一个走样的会话能刷满建议。"""
        replies = ["a", "b" * 30, "c", "d" * 40]
        _, issues = monitor._check_language_style(" ".join(replies), replies)
        assert sum("波动过大" in i for i in issues) == 1

    def test_no_emoji_needs_more_than_five_replies(self, monitor):
        """6 条以内不查 emoji（样本太少），6 条以上才判。"""
        five = ["今天过得还行吧"] * 5
        _, issues5 = monitor._check_language_style(" ".join(five), five)
        assert not any("emoji" in i for i in issues5)

        six = ["今天过得还行吧"] * 6
        _, issues6 = monitor._check_language_style(" ".join(six), six)
        assert any("缺少情感表达" in i for i in issues6)

    def test_negative_emoji_dominance_flagged(self, monitor):
        text = " ".join(["难过 😢😭😤"] * 6)
        _, issues = monitor._check_language_style(text, [text] * 6)
        assert any("负面 emoji" in i for i in issues)

    def test_positive_emoji_suppresses_noise_issue(self, monitor):
        text = " ".join(["开心 😊"] * 6)
        _, issues = monitor._check_language_style(text, [text] * 6)
        assert not any("emoji" in i for i in issues)

    def test_score_deducts_ten_percent_per_issue(self, monitor):
        """一个 issue 扣 0.1。只两条回复 → emoji 检查不启动，只剩长度问题。"""
        score_one, issues_one = monitor._check_language_style("", ["a", "b" * 100])
        assert len(issues_one) == 1
        assert score_one == pytest.approx(0.9)

    def test_score_never_negative(self, monitor):
        """issue 多到爆也要夹在 0，不能出负分（下游会拿去算百分比）。"""
        bad = ["a", "b" * 200] + ["😢😭"] * 7
        score, issues = monitor._check_language_style(" ".join(bad), bad)
        assert len(issues) >= 2
        assert 0.0 <= score <= 1.0


class TestPersonalityExpression:
    def test_warm_reply_clean(self, monitor):
        score, issues = monitor._check_personality_expression("我好担心你，要乖", ["我好担心你，要乖"])
        assert issues == []
        assert score == 1.0

    def test_cold_dominance_flagged(self, monitor):
        text = "哦 嗯 知道了 随便 行吧"
        _, issues = monitor._check_personality_expression(text, [text])
        assert any("冷淡" in i for i in issues)

    def test_no_expression_keywords_no_issue(self, monitor):
        """一句普通回复里没有任何情绪词 → 不判冷淡（避免误伤）。"""
        _, issues = monitor._check_personality_expression("明天八点开会", ["明天八点开会"])
        assert not any("冷淡" in i for i in issues)

    def test_long_reply_flagged(self, monitor):
        long_reply = "这是一段很长的回复。" * 40
        _, issues = monitor._check_personality_expression(long_reply, [long_reply])
        assert any("篇幅过长" in i for i in issues)

    def test_short_reply_flagged(self, monitor):
        _, issues = monitor._check_personality_expression("嗯", ["嗯"])
        assert any("过于简短" in i for i in issues)

    def test_boundary_200_not_flagged(self, monitor):
        """判据是 `> 200`，正好 200 字不报。"""
        reply = "字" * 200
        _, issues = monitor._check_personality_expression(reply, [reply])
        assert not any("篇幅过长" in i for i in issues)

    def test_boundary_5_not_flagged(self, monitor):
        """判据是 `< 5`，正好 5 字不报。"""
        _, issues = monitor._check_personality_expression("五个字的回复", ["五个字的回复"])
        assert not any("过于简短" in i for i in issues)

    def test_average_length_used_not_each(self, monitor):
        """长度判据看的是平均值：一条短一条长平均下来正常就不报。"""
        replies = ["嗯", "字" * 100]
        _, issues = monitor._check_personality_expression(" ".join(replies), replies)
        assert not any("过于简短" in i for i in issues)
        assert not any("篇幅过长" in i for i in issues)

    def test_score_deducts_fifteen_percent_per_issue(self, monitor):
        """「冷淡 + 超短」两条独立 issue，扣 2×0.15。"""
        _, issues = monitor._check_personality_expression("嗯", ["嗯"])
        score, _ = monitor._check_personality_expression("嗯", ["嗯"])
        assert len(issues) == 2
        assert score == pytest.approx(0.7)

    def test_score_deducts_fifteen_percent_for_single_issue(self, monitor):
        """只有长度问题（带温暖词所以不触发冷淡判据）时扣一笔 0.15。"""
        reply = "我很关心你呀，" + "字" * 200
        _, issues = monitor._check_personality_expression(reply, [reply])
        assert len(issues) == 1
        score, _ = monitor._check_personality_expression(reply, [reply])
        assert score == pytest.approx(0.85)

    def test_empty_replies_no_length_issue(self, monitor):
        _, issues = monitor._check_personality_expression("", [])
        assert not any("简短" in i for i in issues)


class TestValueConsistency:
    def test_positive_only_clean(self, monitor):
        score, issues = monitor._check_value_consistency("你一定能行，加油")
        assert issues == []
        assert score == 1.0

    def test_negative_dominance_flagged(self, monitor):
        _, issues = monitor._check_value_consistency("没救 算了 放弃 无聊")
        assert any("负面" in i for i in issues)

    def test_ratio_exactly_half_not_flagged(self, monitor):
        """判据是 `> 0.5`，正好一半不报。"""
        _, issues = monitor._check_value_consistency("好 算了")
        assert issues == []

    def test_no_value_words_no_issue(self, monitor):
        _, issues = monitor._check_value_consistency("今天吃了面条")
        assert issues == []

    def test_score_deducts_twenty_percent(self, monitor):
        score, issues = monitor._check_value_consistency("没救 算了 放弃")
        assert len(issues) == 1
        assert score == pytest.approx(0.8)


class TestAnalyzeAggregation:
    def test_score_is_mean_of_three(self, monitor):
        report = monitor.analyze("u1", "p1", 10, ["嗯"])
        expected = sum(
            v["score"] for v in report.details.values()
        ) / 3
        assert report.consistency_score == pytest.approx(round(expected, 4))

    def test_details_has_three_dimensions(self, monitor):
        report = monitor.analyze("u1", "p1", 10, ["你好呀"])
        assert set(report.details) == {
            "language_style",
            "personality_expression",
            "value_consistency",
        }

    def test_each_detail_has_score_and_issues(self, monitor):
        report = monitor.analyze("u1", "p1", 10, ["你好呀"])
        for dim, payload in report.details.items():
            assert set(payload) == {"score", "issues"}, dim
            assert 0.0 <= payload["score"] <= 1.0

    def test_drift_is_complement(self, monitor):
        report = monitor.analyze("u1", "p1", 10, ["嗯"])
        assert report.drift_score == pytest.approx(round(1.0 - report.consistency_score, 4))

    def test_suggestions_collected_from_all_dimensions(self, monitor):
        report = monitor.analyze("u1", "p1", 10, ["嗯", "没救 算了 放弃 无聊"])
        assert len(report.suggestions) >= 2

    def test_scores_rounded_to_four_places(self, monitor):
        report = monitor.analyze("u1", "p1", 10, ["嗯"])
        assert report.consistency_score == round(report.consistency_score, 4)
        assert report.drift_score == round(report.drift_score, 4)

    def test_bad_replies_fail_check(self, monitor):
        bad = ["嗯", "哦", "随便"] * 4
        report = monitor.analyze("u1", "p1", 10, bad)
        assert report.passed is False

    def test_good_replies_pass_check(self, monitor):
        good = ["我刚泡了杯茶，正好在想你今天过得怎么样呀～"] * 4
        report = monitor.analyze("u1", "p1", 10, good)
        assert report.passed is True

    def test_conversation_count_echoed(self, monitor):
        assert monitor.analyze("u1", "p1", 777, ["你好呀"]).conversation_count == 777


class TestReportSummary:
    def test_contains_all_fields(self, monitor):
        report = monitor.analyze("u1", "p1", 12, ["嗯"])
        summary = monitor.generate_report_summary(report)
        assert "一致性评分" in summary
        assert "漂移评分" in summary
        assert "对话轮数：12" in summary
        assert "建议：" in summary

    def test_status_marker_for_pass(self, monitor):
        report = PersonaDriftReport("u", "p", 1, 1.0, 0.0)
        assert "✅" in monitor.generate_report_summary(report)

    def test_status_marker_for_fail(self, monitor):
        report = PersonaDriftReport("u", "p", 1, 0.5, 0.5, suggestions=["冷"])
        assert "⚠️" in monitor.generate_report_summary(report)

    def test_no_suggestions_renders_none(self, monitor):
        report = PersonaDriftReport("u", "p", 1, 1.0, 0.0)
        assert "建议：无" in monitor.generate_report_summary(report)

    def test_suggestions_joined_with_semicolon(self, monitor):
        report = PersonaDriftReport("u", "p", 1, 0.5, 0.5, suggestions=["甲", "乙"])
        assert "甲；乙" in monitor.generate_report_summary(report)

    def test_uses_real_newlines(self, monitor):
        """回归点：写成 `\\\\n` 会把摘要压成一行。"""
        report = PersonaDriftReport("u", "p", 1, 1.0, 0.0)
        summary = monitor.generate_report_summary(report)
        assert "\\n" not in summary
        assert summary.count("\n") == 4

    def test_percentage_format(self, monitor):
        report = PersonaDriftReport("u", "p", 1, 0.8765, 0.1235)
        assert "87.65%" in monitor.generate_report_summary(report)


class TestKeywordTables:
    def test_three_dimensions_defined(self):
        assert set(PersonaDriftMonitor.DIMENSION_KEYWORDS) == {
            "language",
            "personality",
            "value",
        }

    def test_language_has_four_buckets(self):
        assert set(PersonaDriftMonitor.DIMENSION_KEYWORDS["language"]) == {
            "catchphrases",
            "filler_words",
            "positive_emoji",
            "negative_emoji",
        }

    def test_positive_and_negative_emoji_disjoint(self):
        lang = PersonaDriftMonitor.DIMENSION_KEYWORDS["language"]
        assert not set(lang["positive_emoji"]) & set(lang["negative_emoji"])

    def test_personality_has_three_styles(self):
        assert set(PersonaDriftMonitor.DIMENSION_KEYWORDS["personality"]) == {
            "warm",
            "cold",
            "playful",
        }

    def test_value_has_two_polarities(self):
        assert set(PersonaDriftMonitor.DIMENSION_KEYWORDS["value"]) == {"positive", "negative"}

    def test_all_keyword_lists_non_empty(self):
        for dim, buckets in PersonaDriftMonitor.DIMENSION_KEYWORDS.items():
            for name, words in buckets.items():
                if name == "catchphrases":
                    continue  # 按人设动态填，允许为空
                assert words, f"{dim}.{name} 不能空"
