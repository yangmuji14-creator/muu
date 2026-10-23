"""core/memory/identity.py 的单元测试

覆盖两块：
    - ``IdentityProfile`` 的序列化 / 合并 / prompt 生成
    - ``IdentityLayer`` 的加载、保存、更新、规则提取

以及模块级 ``_extract_school``（它修过两个真 bug，见各用例注释）。

全部走 ``tmp_path``，不碰真实 ``data/identities/``。
"""

from __future__ import annotations

import json

import pytest

from core.memory.identity import (
    IdentityLayer,
    IdentityProfile,
    _extract_school,
)


# --------------------------------------------------------------------------- #
# 校名提取
# --------------------------------------------------------------------------- #


class TestExtractSchool:
    """`_extract_school` 的行为契约

    它替换掉的是旧版「`group(1) + "大学"` 拼后缀 + 要求后缀后紧跟标点」的正则，
    那两个毛病各有一个用例钉住。
    """

    @pytest.mark.parametrize(
        "message, expected",
        [
            ("我在清华大学。", "清华大学"),
            ("我在清华大学读书", "清华大学"),
            ("我是北京大学的学生", "北京大学"),
            ("我本科在北京大学", "北京大学"),
            ("他在浙江大学。", "浙江大学"),
            ("我在中国人民大学。", "中国人民大学"),
            ("上海交通大学", "上海交通大学"),
            ("我在上海大学读书", "上海大学"),
        ],
    )
    def test_extracts_full_name_with_suffix(self, message: str, expected: str) -> None:
        assert _extract_school(message) == expected

    @pytest.mark.parametrize(
        "message, expected",
        [
            ("我在清华学院。", "清华学院"),
            ("我在清华学校。", "清华学校"),
        ],
    )
    def test_keeps_original_suffix(self, message: str, expected: str) -> None:
        """后缀原样保留 —— 旧实现把「清华学院」改写成「清华大学」。"""
        assert _extract_school(message) == expected

    @pytest.mark.parametrize(
        "message",
        ["", "这所大学不错", "我在学校", "在上大学", "我上大学", "没提学校的事"],
    )
    def test_rejects_non_school_names(self, message: str) -> None:
        """专名部分不足两字、或以主语/指示词开头的，都不是校名。"""
        assert _extract_school(message) == ""

    @pytest.mark.parametrize(
        "message, expected",
        [
            ("我毕业于上海交通大学", "上海交通大学"),
            ("我来自复旦大学", "复旦大学"),
            ("我考上了北京大学。", "北京大学"),
            ("我考上了北京大学的研究生", "北京大学"),
        ],
    )
    def test_strips_leading_verbs(self, message: str, expected: str) -> None:
        """「毕业于」「来自」这类动词不能算进校名。"""
        assert _extract_school(message) == expected

    def test_shanghai_is_not_cut_by_stop_char(self) -> None:
        """「上」不是停止字 —— 否则「上海交通大学」会被截成「海交通大学」。"""
        assert _extract_school("上海交通大学") == "上海交通大学"
        assert _extract_school("我在上海大学") == "上海大学"

    def test_first_suffix_match_wins(self) -> None:
        """先找到哪个后缀就从哪个后缀起算。"""
        assert _extract_school("我在清华大学") == "清华大学"

    def test_empty_message(self) -> None:
        assert _extract_school("") == ""


# --------------------------------------------------------------------------- #
# IdentityProfile
# --------------------------------------------------------------------------- #


class TestProfileBasics:
    def test_defaults(self) -> None:
        profile = IdentityProfile(user_id="u1")
        assert profile.user_id == "u1"
        assert profile.education == ""
        assert profile.interests == []
        assert profile.preferences == {}
        assert profile.version == 1
        assert profile.created_at and profile.updated_at

    def test_list_fields_are_independent(self) -> None:
        """`field(default_factory=list)` 不能写成 `[]`，否则实例间共享同一个列表。"""
        a = IdentityProfile(user_id="a")
        b = IdentityProfile(user_id="b")
        a.interests.append("跑步")
        assert b.interests == []


class TestProfileSerialization:
    def test_to_dict_roundtrip(self) -> None:
        profile = IdentityProfile(
            user_id="u1",
            education="本科",
            major="计算机",
            school="清华大学",
            interests=["跑步", "摄影"],
            preferences={"city": "成都"},
        )
        restored = IdentityProfile.from_dict(profile.to_dict())
        assert restored == profile

    def test_from_dict_fills_missing_fields(self) -> None:
        restored = IdentityProfile.from_dict({"user_id": "u1"})
        assert restored.user_id == "u1"
        assert restored.education == ""
        assert restored.interests == []
        assert restored.version == 1

    def test_from_dict_generates_timestamps(self) -> None:
        restored = IdentityProfile.from_dict({})
        assert restored.created_at
        assert restored.updated_at

    def test_to_dict_covers_every_field(self) -> None:
        data = IdentityProfile(user_id="u1").to_dict()
        for key in (
            "user_id", "education", "major", "school", "grade", "career",
            "location", "interests", "personality_traits", "skills",
            "communication_style", "goals", "values", "life_events",
            "important_life_events", "preferences",
            "created_at", "updated_at", "version",
        ):
            assert key in data


class TestProfileMerge:
    def test_scalar_other_wins(self) -> None:
        mine = IdentityProfile(user_id="u1", major="数学", career="学生")
        other = IdentityProfile(user_id="u1", major="计算机")
        merged = mine.merge(other)
        assert merged.major == "计算机"
        # other 为空则保留自己的
        assert merged.career == "学生"

    def test_list_fields_union(self) -> None:
        mine = IdentityProfile(user_id="u1", interests=["跑步"])
        other = IdentityProfile(user_id="u1", interests=["摄影"])
        merged = mine.merge(other)
        assert set(merged.interests) == {"跑步", "摄影"}

    def test_list_fields_deduped(self) -> None:
        mine = IdentityProfile(user_id="u1", interests=["跑步"])
        other = IdentityProfile(user_id="u1", interests=["跑步"])
        merged = mine.merge(other)
        assert merged.interests == ["跑步"]

    def test_preferences_shallow_merge(self) -> None:
        mine = IdentityProfile(user_id="u1", preferences={"a": 1, "b": 2})
        other = IdentityProfile(user_id="u1", preferences={"b": 3, "c": 4})
        merged = mine.merge(other)
        assert merged.preferences == {"a": 1, "b": 3, "c": 4}

    def test_keeps_created_at_from_self(self) -> None:
        mine = IdentityProfile(user_id="u1", created_at="2026-01-01T00:00:00")
        other = IdentityProfile(user_id="u1", created_at="2026-02-02T00:00:00")
        merged = mine.merge(other)
        assert merged.created_at == "2026-01-01T00:00:00"

    def test_refreshes_updated_at(self) -> None:
        mine = IdentityProfile(user_id="u1", updated_at="2026-01-01T00:00:00")
        merged = mine.merge(IdentityProfile(user_id="u1"))
        assert merged.updated_at != "2026-01-01T00:00:00"

    def test_does_not_mutate_inputs(self) -> None:
        mine = IdentityProfile(user_id="u1", interests=["跑步"])
        other = IdentityProfile(user_id="u1", interests=["摄影"])
        mine.merge(other)
        assert mine.interests == ["跑步"]
        assert other.interests == ["摄影"]


class TestProfilePrompt:
    def test_always_has_header(self) -> None:
        assert IdentityProfile(user_id="u1").to_prompt() == "【用户身份档案】"

    def test_empty_profile_has_no_extra_lines(self) -> None:
        assert "\n" not in IdentityProfile(user_id="u1").to_prompt()

    def test_education_line_combines_school_major(self) -> None:
        profile = IdentityProfile(
            user_id="u1", school="清华大学", education="本科", major="计算机",
        )
        assert "教育背景：" in profile.to_prompt()
        assert "清华大学" in profile.to_prompt()
        assert "计算机" in profile.to_prompt()

    def test_education_line_triggered_by_major_alone(self) -> None:
        """只有 major 也要出行 —— 「教育背景」这一行的条件三者取或。"""
        line = IdentityProfile(user_id="u1", major="计算机").to_prompt()
        assert "教育背景：" in line
        assert "计算机" in line

    @pytest.mark.parametrize(
        "field_name, label",
        [
            ("career", "职业："),
            ("location", "所在地："),
            ("interests", "兴趣爱好："),
            ("personality_traits", "性格特征："),
            ("skills", "技能："),
            ("goals", "目标："),
            ("values", "价值观："),
            ("life_events", "重要经历："),
            ("important_life_events", "重要人生事件："),
        ],
    )
    def test_each_field_has_own_line(self, field_name: str, label: str) -> None:
        value = ["项"] if field_name.endswith("s") or field_name in {
            "interests", "personality_traits", "skills", "goals", "values",
            "life_events", "important_life_events",
        } else "值"
        prompt = IdentityProfile(user_id="u1", **{field_name: value}).to_prompt()
        assert label in prompt

    def test_to_prompt_section_is_alias(self) -> None:
        profile = IdentityProfile(user_id="u1", career="程序员")
        assert profile.to_prompt_section() == profile.to_prompt()


# --------------------------------------------------------------------------- #
# IdentityLayer
# --------------------------------------------------------------------------- #


@pytest.fixture()
def layer(tmp_path):
    return IdentityLayer(tmp_path)


class TestLayerIO:
    def test_creates_identities_dir(self, tmp_path) -> None:
        IdentityLayer(tmp_path)
        assert (tmp_path / "identities").is_dir()

    def test_load_missing_returns_empty_profile(self, layer) -> None:
        profile = layer.load("nobody")
        assert profile.user_id == "nobody"
        assert profile.career == ""

    def test_save_then_load(self, layer) -> None:
        layer.save(IdentityProfile(user_id="u1", major="计算机"))
        assert layer.load("u1").major == "计算机"

    def test_save_writes_utf8_json(self, layer, tmp_path) -> None:
        layer.save(IdentityProfile(user_id="u1", major="计算机"))
        raw = (tmp_path / "identities" / "u1.json").read_text(encoding="utf-8")
        assert "计算机" in raw
        assert json.loads(raw)["major"] == "计算机"

    def test_save_refreshes_updated_at(self, layer) -> None:
        profile = IdentityProfile(user_id="u1", updated_at="2026-01-01T00:00:00")
        layer.save(profile)
        assert profile.updated_at != "2026-01-01T00:00:00"

    def test_load_corrupt_json_returns_empty(self, layer, tmp_path) -> None:
        path = tmp_path / "identities" / "u1.json"
        path.write_text("{ not json", encoding="utf-8")
        profile = layer.load("u1")
        assert profile.user_id == "u1"
        assert profile.major == ""

    def test_users_are_isolated(self, layer) -> None:
        layer.save(IdentityProfile(user_id="a", major="数学"))
        layer.save(IdentityProfile(user_id="b", major="物理"))
        assert layer.load("a").major == "数学"
        assert layer.load("b").major == "物理"


class TestLayerUpdate:
    def test_sets_known_fields(self, layer) -> None:
        profile = layer.update("u1", career="程序员")
        assert profile.career == "程序员"
        assert layer.load("u1").career == "程序员"

    def test_ignores_unknown_fields(self, layer) -> None:
        profile = layer.update("u1", nonexistent_field="x")
        assert not hasattr(profile, "nonexistent_field")

    def test_bumps_version(self, layer) -> None:
        assert layer.update("u1", career="a").version == 2
        assert layer.update("u1", career="b").version == 3

    def test_accepts_user_id_kwarg(self, layer) -> None:
        """`user_id` 是 positional-only —— 展开整条记录传进来不能炸。

        旧签名是 `def update(self, user_id: str, **kwargs)`，
        `update(uid, **row)` 会在入口就抛
        `TypeError: got multiple values for argument 'user_id'`。
        """
        profile = layer.update("u1", user_id="u1", career="程序员")
        assert profile.user_id == "u1"
        assert profile.career == "程序员"

    def test_preserves_other_fields(self, layer) -> None:
        layer.update("u1", major="计算机")
        profile = layer.update("u1", career="程序员")
        assert profile.major == "计算机"


class TestExtractMajor:
    @pytest.mark.parametrize(
        "message, expected",
        [
            ("我是学计算机的", "计算机"),
            ("我学数学的", "数学"),
            ("专业是物理", "物理"),
            ("读金融专业", "金融"),
        ],
    )
    def test_extracts_major(self, layer, message: str, expected: str) -> None:
        assert layer.extract_from_message("u1", message).major == expected

    def test_does_not_duplicate_work(self, layer) -> None:
        layer.extract_from_message("u1", "我是学计算机的")
        profile = layer.extract_from_message("u1", "我是学计算机的")
        assert profile.major == "计算机"


class TestExtractSchool:
    def test_extracts_school(self, layer) -> None:
        profile = layer.extract_from_message("u1", "我在清华大学读书")
        assert profile.school == "清华大学"

    def test_school_and_major_together(self, layer) -> None:
        profile = layer.extract_from_message("u1", "我在清华大学读计算机专业")
        assert profile.school == "清华大学"
        assert profile.major == "计算机"


class TestExtractInterest:
    @pytest.mark.parametrize(
        "message, expected",
        [
            ("我喜欢Python", ["Python"]),
            ("我喜欢跑步和游泳。", ["跑步", "游泳"]),
            ("我喜欢猫，也喜欢狗", ["猫", "狗"]),
            ("我喜欢咖啡、喜欢跑步", ["咖啡", "跑步"]),
            ("我的爱好是摄影", ["摄影"]),
            ("我兴趣是钓鱼", ["钓鱼"]),
        ],
    )
    def test_extracts_interests(self, layer, message: str, expected: list[str]) -> None:
        assert layer.extract_from_message("u1", message).interests == expected

    @pytest.mark.parametrize(
        "message",
        ["我不喜欢下雨", "喜欢和不喜欢", "我爱好"],
    )
    def test_ignores_negations_and_empty(self, layer, message: str) -> None:
        """否定式不是兴趣，空宾语也不记。"""
        assert layer.extract_from_message("u1", message).interests == []

    def test_negation_does_not_swallow_later_clause(self, layer) -> None:
        """「我不喜欢你这样但喜欢猫」—— 转折词后仍要抓到「猫」。

        只用一个贪婪正则会把「喜欢你这样但喜欢猫」整串当成一个兴趣。
        """
        assert layer.extract_from_message("u1", "我不喜欢你这样但喜欢猫").interests == ["猫"]

    def test_accumulates_across_messages(self, layer) -> None:
        layer.extract_from_message("u1", "我喜欢跑步")
        profile = layer.extract_from_message("u1", "我喜欢摄影")
        assert profile.interests == ["跑步", "摄影"]

    def test_dedupes_same_interest(self, layer) -> None:
        layer.extract_from_message("u1", "我喜欢跑步")
        profile = layer.extract_from_message("u1", "我喜欢跑步")
        assert profile.interests == ["跑步"]


class TestExtractGrade:
    @pytest.mark.parametrize(
        "message, expected",
        [
            ("我大二了", "大二"),
            ("我是研究生", "研究生"),
            ("读硕士", "硕士"),
            ("在读博士", "博士"),
        ],
    )
    def test_extracts_grade(self, layer, message: str, expected: str) -> None:
        assert layer.extract_from_message("u1", message).grade == expected


class TestReturnValue:
    def test_returns_profile_even_without_changes(self, layer) -> None:
        profile = layer.extract_from_message("u1", "今天天气不错")
        assert isinstance(profile, IdentityProfile)
        assert profile.user_id == "u1"

    def test_does_not_write_when_nothing_changed(self, layer, tmp_path) -> None:
        layer.extract_from_message("u1", "今天天气不错")
        assert not (tmp_path / "identities" / "u1.json").exists()


class TestGetContext:
    def test_empty_when_nothing_useful(self, layer) -> None:
        assert layer.get_context("nobody") == ""

    def test_empty_when_only_career(self, layer) -> None:
        """只有职业不算 —— `get_context` 只认「教育背景」或「兴趣」。

        这是刻意的收窄：身份块要短，不能因为记住了「他是程序员」
        就每次对话都塞一整块档案进去。
        """
        layer.update("u1", career="程序员")
        assert layer.get_context("u1") == ""

    def test_returns_prompt_when_has_major(self, layer) -> None:
        layer.update("u1", major="计算机")
        context = layer.get_context("u1")
        assert context.startswith("【用户身份档案】")
        assert "计算机" in context

    def test_returns_prompt_when_has_interest(self, layer) -> None:
        layer.update("u1", interests=["跑步"])
        assert "跑步" in layer.get_context("u1")

    def test_returns_prompt_when_has_school(self, layer) -> None:
        layer.update("u1", school="清华大学")
        assert "清华大学" in layer.get_context("u1")

    def test_corrupt_file_yields_empty(self, layer, tmp_path) -> None:
        (tmp_path / "identities").mkdir(exist_ok=True)
        (tmp_path / "identities" / "u1.json").write_text("[[[", encoding="utf-8")
        assert layer.get_context("u1") == ""
