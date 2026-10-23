"""core/persona/prompt_builder.py 的单元测试。

PromptBuilder 是喂给模型的 system prompt 的唯一出口，所以这里的断言偏「契约」：
性别中立、指令层级、动态段与稳定段的分工、字段为空时不拼空壳。

约定：全部用真 `Persona`（它字段都有默认值），不联网、不碰 data/。
"""

from __future__ import annotations

import types

import pytest

from core.persona.models import Persona
from core.persona.prompt_builder import (
    PromptBuilder,
    _build_critical_rules,
    _build_examples,
    _build_identity,
    _build_relationship,
)


def P(**kw) -> Persona:
    kw.setdefault("id", "p1")
    kw.setdefault("name", "慕")
    return Persona(**kw)


def Duck(**kw):
    """鸭子类型替身，用来演练真 Persona 的类型约束挡不住的防御分支。

    真 `Persona` 把 `hobbies` 钉成 `list[dict[str,str]]`、`speaking_style` 钉成
    `dict`（字符串会被 before-validator 搬去 `legacy_speaking_style`），所以
    「字段类型不对」这几条 `getattr` 兜底只能用替身覆盖。
    """
    base = {
        "id": "p1",
        "name": "慕",
        "age": 20,
        "gender": "",
        "birthday": "",
        "hometown": "",
        "occupation": "",
        "daily_routine": "",
        "appearance": "",
        "personality": [],
        "mbti": "",
        "hobbies": [],
        "music_taste": "",
        "food_preferences": "",
        "catchphrases": [],
        "nickname_for_user": "",
        "speaking_style": {},
        "emotional_patterns": {},
        "relationship_behavior": {},
        "how_we_met": "",
        "first_impression": "",
        "pet_names": [],
        "relationship_level": 50,
        "example_dialogs": [],
        "hard_rules": [],
        "taboos": [],
        "core_memories": [],
        "persona_prompt": "",
        "system_prompt": "",
        "output_examples": "",
    }
    base.update(kw)
    return types.SimpleNamespace(**base)


# ------------------------------------------------------ 1. build_stable


class TestBuildStable:
    def test_always_starts_with_critical_rules(self):
        out = PromptBuilder.build_stable(P())
        assert out.startswith("你发的每条消息都是纯文字")

    def test_contains_identity_block(self):
        out = PromptBuilder.build_stable(P(name="慕"))
        assert "你就是慕本人" in out
        assert "你是慕" in out

    def test_persona_prompt_appended_with_heading(self):
        out = PromptBuilder.build_stable(P(persona_prompt="她喜欢在雨天听歌。"))
        assert "你的人设与生活背景：\n她喜欢在雨天听歌。" in out

    def test_persona_prompt_whitespace_stripped(self):
        out = PromptBuilder.build_stable(P(persona_prompt="   内容   "))
        assert "你的人设与生活背景：\n内容" in out

    def test_empty_persona_prompt_omits_heading(self):
        out = PromptBuilder.build_stable(P(persona_prompt="   "))
        assert "你的人设与生活背景" not in out

    def test_output_examples_section(self):
        out = PromptBuilder.build_stable(P(output_examples="「好累啊」"))
        assert "请参考这些说话示例" in out
        assert "「好累啊」" in out

    def test_core_memories_joined_and_limited(self):
        p = P(core_memories=["一起看过海", "养了团子", "在成都", "爱吃辣", "会游泳", "第六条不该出现"])
        out = PromptBuilder.build_stable(p)
        assert "关于你们的共同记忆：一起看过海、养了团子、在成都、爱吃辣、会游泳。" in out
        assert "第六条不该出现" not in out

    def test_no_core_memories_omits_line(self):
        out = PromptBuilder.build_stable(P(core_memories=[]))
        assert "关于你们的共同记忆" not in out

    def test_system_prompt_appended_verbatim(self):
        out = PromptBuilder.build_stable(P(system_prompt="【额外设定】保持简短。"))
        assert "【额外设定】保持简短。" in out

    def test_sections_separated_by_blank_line(self):
        out = PromptBuilder.build_stable(P(persona_prompt="x", system_prompt="y"))
        assert "\n\n" in out

    def test_example_dialogs_block_included(self):
        out = PromptBuilder.build_stable(
            P(example_dialogs=[{"scenario": "他晚归", "reply": ["怎么才回来"]}])
        )
        assert "你平时说话就是这样的：" in out
        assert "· 他晚归 → 怎么才回来" in out


# --------------------------------------------------- 2. build_dynamic_context


class TestBuildDynamicContext:
    def test_relationship_first(self):
        out = PromptBuilder.build_dynamic_context(P())
        assert out.startswith("你和对方的关系：")

    def test_memory_context_appended(self):
        out = PromptBuilder.build_dynamic_context(P(), memory_context="【记忆】他爱猫")
        assert "【记忆】他爱猫" in out
        assert out.index("你和对方的关系：") < out.index("【记忆】他爱猫")

    def test_extra_instructions_last(self):
        out = PromptBuilder.build_dynamic_context(
            P(), memory_context="M", extra_instructions="E"
        )
        assert out.index("M") < out.index("E")

    def test_empty_inputs_only_relationship(self):
        out = PromptBuilder.build_dynamic_context(P())
        assert out.count("\n\n") == 0

    def test_relationship_level_override(self):
        p = P(relationship_level=10)
        low = PromptBuilder.build_dynamic_context(p, relationship_level=10)
        high = PromptBuilder.build_dynamic_context(p, relationship_level=90)
        assert "刚认识不久" in low
        assert "在一起很久了" in high

    def test_extra_instructions_only(self):
        out = PromptBuilder.build_dynamic_context(P(), extra_instructions="只回一句")
        assert "只回一句" in out
        assert out.startswith("你和对方的关系：")


# ------------------------------------------------------------- 3. build()


class TestBuild:
    def test_joins_stable_and_dynamic(self):
        out = PromptBuilder.build(P(), memory_context="记忆")
        assert "你发的每条消息都是纯文字" in out
        assert "你和对方的关系：" in out
        assert "记忆" in out

    def test_stable_before_dynamic(self):
        out = PromptBuilder.build(P(), extra_instructions="指令")
        assert out.index("你发的每条消息都是纯文字") < out.index("指令")

    def test_skips_empty_parts(self):
        out = PromptBuilder.build(P())
        assert not out.endswith("\n\n")

    def test_level_forwarded(self):
        out = PromptBuilder.build(P(), relationship_level=5)
        assert "刚认识不久" in out


# ---------------------------------------------------- 4. _build_critical_rules


class TestCriticalRules:
    def test_uses_persona_name(self):
        out = _build_critical_rules(P(name="小林"))
        assert "你就是小林本人" in out

    def test_falls_back_to_default_name(self):
        p = P(name="")
        out = _build_critical_rules(p)
        assert "你就是小可爱本人" in out

    def test_hard_rules_merged(self):
        out = _build_critical_rules(P(hard_rules=["不主动提分手", "不说教"]))
        assert "此外：不主动提分手；不说教" in out

    def test_no_hard_rules_omits_line(self):
        out = _build_critical_rules(P(hard_rules=[]))
        assert "此外：" not in out

    def test_taboos_rendered(self):
        out = _build_critical_rules(P(taboos=["政治", "宗教"]))
        assert "绝对不要触碰的话题：政治、宗教。" in out

    def test_no_taboos_omits_line(self):
        out = _build_critical_rules(P(taboos=[]))
        assert "绝对不要触碰的话题" not in out

    def test_positive_framing_present(self):
        """设计原则第 4 条：说「要做什么」而不是堆负面禁令。"""
        out = _build_critical_rules(P())
        assert "像真人聊微信一样" in out
        assert "你不是客服" in out
        assert "不要用「作为AI」" in out


# -------------------------------------------------------- 5. _build_identity


class TestBuildIdentity:
    def test_gender_and_age_rendered(self):
        out = _build_identity(P(name="慕", age=23, gender="女"))
        assert "你是慕，23岁，女生。" in out

    def test_gender_only(self):
        # age 有默认值 20，所以「只填性别」也会带年龄；用替身去掉 age 才是真的只有性别
        out = _build_identity(Duck(name="慕", gender="男", age=""))
        assert out == "你是慕，男生。"

    def test_age_zero_omitted(self):
        """`getattr(p, "age", "") or ""` 把 0 当空 —— 钉住现状（0 岁无意义）。"""
        out = _build_identity(P(name="慕", age=0, gender="女"))
        assert out == "你是慕，女生。"
        assert "0岁" not in out

    def test_hobbies_empty_name_dropped(self):
        """回归点：空 name 原样 join 会拼出「你喜欢跑步、画画、、游泳。」。"""
        out = _build_identity(
            Duck(hobbies=[{"name": "跑步"}, {"name": ""}, {"name": "游泳"}])
        )
        assert "你喜欢跑步、游泳。" in out
        assert "、、" not in out

    def test_hobbies_all_empty_name_omits_line(self):
        out = _build_identity(Duck(hobbies=[{"name": ""}, {"other": "x"}]))
        assert "你喜欢" not in out

    def test_no_gender_declares_neutrality(self):
        """性别中立化（2026-10-18）：字段为空时不能回落「女」。"""
        out = _build_identity(P(name="慕", gender=""))
        assert "性别、年龄和与对方的具体关系没有预设" in out
        assert "女生" not in out
        assert "男生" not in out

    def test_gender_whitespace_treated_as_empty(self):
        out = _build_identity(P(gender="   "))
        assert "没有预设" in out

    def test_occupation_and_hometown(self):
        out = _build_identity(P(occupation="是程序员", hometown="成都"))
        assert "你是程序员。" in out
        assert "你是成都人。" in out

    def test_mbti_and_birthday(self):
        out = _build_identity(P(mbti="INFP", birthday="3月5日"))
        assert "你是INFP。" in out
        assert "生日是3月5日。" in out

    def test_personality_limited_to_four(self):
        out = _build_identity(P(personality=["真诚", "自然", "有分寸", "安静", "第五个"]))
        assert "性格上，你真诚、自然、有分寸、安静。" in out
        assert "第五个" not in out

    def test_appearance(self):
        out = _build_identity(P(appearance="个子不高，说话慢"))
        assert "你个子不高，说话慢。" in out

    def test_hobbies_dict_and_str_mixed(self):
        """真 Persona 只收 dict，但 `_build_identity` 对裸字符串也兼容 —— 用替身演练。"""
        out = _build_identity(
            Duck(hobbies=[{"name": "跑步"}, "画画", "游泳"])
        )
        assert "你喜欢跑步、画画、游泳。" in out

    def test_hobbies_dicts_from_real_persona(self):
        out = _build_identity(P(hobbies=[{"name": "跑步"}, {"name": "画画"}]))
        assert "你喜欢跑步、画画。" in out

    def test_music_and_food(self):
        out = _build_identity(P(music_taste="民谣", food_preferences="嗜辣"))
        assert "听歌偏爱民谣。" in out
        assert "口味上嗜辣。" in out

    def test_daily_routine(self):
        out = _build_identity(P(daily_routine="朝九晚五"))
        assert "日常：朝九晚五。" in out

    def test_speaking_style_dict_uses_base_key(self):
        out = _build_identity(P(speaking_style={"基础风格": "简洁"}))
        assert "你说话简洁。" in out

    def test_speaking_style_dict_without_base_joins_values(self):
        out = _build_identity(P(speaking_style={"语气": "轻", "节奏": "慢"}))
        assert "你说话轻、慢。" in out

    def test_speaking_style_empty_dict_omits(self):
        out = _build_identity(P(speaking_style={}))
        assert "你说话" not in out

    def test_speaking_style_string(self):
        """真 Persona 会把字符串搬去 `legacy_speaking_style`，这里用替身覆盖兜底分支。"""
        out = _build_identity(Duck(speaking_style="很软"))
        assert "你说话很软。" in out

    def test_legacy_speaking_style_not_rendered(self):
        """字符串走 before-validator 变成 legacy 字段后，不再参与 identity。"""
        out = _build_identity(P(speaking_style="很软"))
        assert "你说话" not in out

    def test_catchphrases_limited_to_three(self):
        out = _build_identity(P(catchphrases=["嗯嗯", "好呀", "哈", "第四个"]))
        assert "常说的口头禅：嗯嗯、好呀、哈。" in out
        assert "第四个" not in out

    def test_nickname(self):
        out = _build_identity(P(nickname_for_user="宝"))
        assert "你叫对方「宝」。" in out

    def test_emotional_patterns_all_three(self):
        out = _build_identity(
            P(
                emotional_patterns={
                    "依恋类型": "安全型",
                    "压力反应": "沉默一会儿",
                    "爱的语言": "陪伴",
                }
            )
        )
        assert "情感上，依恋类型是安全型，压力大时会沉默一会儿，表达爱的方式是陪伴。" in out

    def test_emotional_patterns_partial(self):
        out = _build_identity(P(emotional_patterns={"依恋类型": "回避型"}))
        assert "情感上，依恋类型是回避型。" in out
        assert "压力大时" not in out

    def test_emotional_patterns_only_pressure(self):
        out = _build_identity(P(emotional_patterns={"压力反应": "沉默"}))
        assert "情感上，压力大时会沉默。" in out
        assert "依恋类型" not in out

    def test_emotional_patterns_only_love_language(self):
        out = _build_identity(P(emotional_patterns={"爱的语言": "陪伴"}))
        assert "情感上，表达爱的方式是陪伴。" in out

    def test_emotional_patterns_unknown_keys_omitted(self):
        out = _build_identity(P(emotional_patterns={"无关字段": "x"}))
        assert "情感上" not in out

    def test_catchphrases_empty_list_omits(self):
        out = _build_identity(P(catchphrases=[]))
        assert "口头禅" not in out

    def test_emotional_patterns_non_dict_ignored(self):
        out = _build_identity(Duck(emotional_patterns="随便"))
        assert "情感上" not in out

    def test_all_empty_gives_minimal_output(self):
        out = _build_identity(P(name="慕", gender=""))
        assert "你是慕。" in out
        assert out.count("\n") == 0  # 每个句子之间不加换行


# ---------------------------------------------------- 6. _build_relationship


class TestBuildRelationship:
    @pytest.mark.parametrize(
        "level,needle",
        [
            (100, "在一起很久了"),
            (85, "在一起很久了"),
            (84, "关系很亲密"),
            (65, "关系很亲密"),
            (64, "是好朋友"),
            (40, "是好朋友"),
            (39, "认识的朋友"),
            (20, "认识的朋友"),
            (19, "刚认识不久"),
            (0, "刚认识不久"),
        ],
    )
    def test_level_buckets(self, level, needle):
        out = _build_relationship(P(), level)
        assert needle in out

    def test_default_level_from_persona(self):
        out = _build_relationship(P(relationship_level=50))
        assert "是好朋友" in out

    def test_explicit_level_beats_persona(self):
        out = _build_relationship(P(relationship_level=90), 10)
        assert "刚认识不久" in out

    def test_how_we_met(self):
        out = _build_relationship(P(how_we_met="在图书馆认识"))
        assert "你们在图书馆认识。" in out

    def test_first_impression(self):
        out = _build_relationship(P(first_impression="话不多但很认真"))
        assert "你对对方的第一印象：话不多但很认真。" in out

    def test_relationship_behavior(self):
        out = _build_relationship(
            P(relationship_behavior={"冲突模式": "先冷静", "边界需求": "独处时间"})
        )
        assert "有矛盾时你会先冷静" in out
        assert "你需要独处时间" in out

    def test_relationship_behavior_partial(self):
        out = _build_relationship(P(relationship_behavior={"冲突模式": "直接说"}))
        assert "有矛盾时你会直接说" in out
        assert "你需要" not in out

    def test_relationship_behavior_only_boundary(self):
        out = _build_relationship(P(relationship_behavior={"边界需求": "独处"}))
        assert "你需要独处" in out
        assert "有矛盾时" not in out

    def test_relationship_behavior_unknown_keys_omitted(self):
        out = _build_relationship(P(relationship_behavior={"无关": "x"}))
        assert "有矛盾时" not in out
        assert "你需要" not in out

    def test_no_pet_names_omits_line(self):
        out = _build_relationship(P(pet_names=[]))
        assert "昵称" not in out

    def test_relationship_behavior_non_dict_ignored(self):
        out = _build_relationship(Duck(relationship_behavior="x"))
        assert "有矛盾时" not in out

    def test_pet_names(self):
        out = _build_relationship(P(pet_names=["小狗", "笨蛋"]))
        assert "你私下给对方起的昵称是小狗、笨蛋。" in out

    def test_prefix_always_present(self):
        assert _build_relationship(P()).startswith("你和对方的关系：")


# ------------------------------------------------------- 7. _build_examples


class TestBuildExamples:
    def test_empty_returns_empty_string(self):
        assert _build_examples(P(example_dialogs=[])) == ""

    def test_none_returns_empty_string(self):
        # 真 Persona 的 example_dialogs 不允许 None（validate_assignment 会拒），
        # 用替身覆盖 `getattr(...) or []` 之外的 None 分支
        assert _build_examples(Duck(example_dialogs=None)) == ""

    def test_renders_scenario_and_replies(self):
        out = _build_examples(
            P(example_dialogs=[{"scenario": "他晚归", "reply": ["怎么才回来", "我等你很久了"]}])
        )
        assert out.startswith("你平时说话就是这样的：")
        assert "· 他晚归 → 怎么才回来 / 我等你很久了" in out

    def test_replies_limited_to_three(self):
        out = _build_examples(
            P(example_dialogs=[{"scenario": "s", "reply": ["a", "b", "c", "d"]}])
        )
        assert "a / b / c" in out
        assert "d" not in out

    def test_dialogs_limited_to_three(self):
        out = _build_examples(
            P(
                example_dialogs=[
                    {"scenario": "s1", "reply": ["r1"]},
                    {"scenario": "s2", "reply": ["r2"]},
                    {"scenario": "s3", "reply": ["r3"]},
                    {"scenario": "s4", "reply": ["r4"]},
                ]
            )
        )
        assert "s3" in out
        assert "s4" not in out

    def test_missing_scenario_skipped(self):
        out = _build_examples(P(example_dialogs=[{"reply": ["r"]}]))
        assert out == "你平时说话就是这样的："

    def test_missing_reply_skipped(self):
        out = _build_examples(P(example_dialogs=[{"scenario": "s", "reply": []}]))
        assert out == "你平时说话就是这样的："
