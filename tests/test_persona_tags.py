"""性格标签翻译表（core/persona/tags.py）。

这个模块是 CLI 向导与 WebUI 建人接口共用的唯一一份翻译逻辑，所以测试重点
不在「能不能读文件」，而在合并语义：
- 用户手填的字段必须优先（setdefault 语义，不覆盖）
- `hard_rules` 是列表，去重要保持顺序
- 三个 DEFAULT_LAYERS 无论有没有标签都要存在（PromptBuilder 会直接读）
- 文件缺失/损坏时降级成空表，不能抛

所有用例都用 monkeypatch 把 CONFIG_DIR 指到 tmp_path，不碰真实 config/。
"""

from __future__ import annotations

import json

import pytest

from core.persona import tags as tags_mod


@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    """把 core.config.CONFIG_DIR 指到临时目录。

    `tags_path()` 是在函数体里 `from core.config import CONFIG_DIR`，
    所以必须 patch 模块属性，而不是 patch 本模块里的某个常量。
    """
    import core.config

    monkeypatch.setattr(core.config, "CONFIG_DIR", tmp_path)
    return tmp_path


def _write_tags(config_dir, data) -> None:
    (config_dir / "persona_tags.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


class TestTagsPath:
    def test_points_into_config_dir(self, config_dir):
        assert tags_mod.tags_path() == config_dir / "persona_tags.json"

    def test_follows_config_dir_change(self, config_dir, tmp_path, monkeypatch):
        import core.config

        other = tmp_path / "other"
        other.mkdir()
        monkeypatch.setattr(core.config, "CONFIG_DIR", other)
        assert tags_mod.tags_path() == other / "persona_tags.json"


class TestLoadPersonaTags:
    def test_missing_file_returns_empty_dict(self, config_dir):
        assert tags_mod.load_persona_tags() == {}

    def test_reads_normal_file(self, config_dir):
        _write_tags(config_dir, {"话痨": {"speaking_style": {"说话量": "话多"}}})
        data = tags_mod.load_persona_tags()
        assert data["话痨"]["speaking_style"]["说话量"] == "话多"

    def test_tolerates_bom(self, config_dir):
        """`utf-8-sig`：Windows 记事本存出来的文件带 BOM，必须能读。"""
        path = config_dir / "persona_tags.json"
        path.write_text(json.dumps({"温柔": {}}, ensure_ascii=False), encoding="utf-8-sig")
        assert "温柔" in tags_mod.load_persona_tags()

    def test_top_level_array_returns_empty_dict(self, config_dir):
        """顶层是数组就当没读到 —— 调用方按 dict 用，不能塞个 list 进去。"""
        (config_dir / "persona_tags.json").write_text("[1, 2]", encoding="utf-8")
        assert tags_mod.load_persona_tags() == {}

    def test_broken_json_returns_empty_dict(self, config_dir):
        (config_dir / "persona_tags.json").write_text("{ not json", encoding="utf-8")
        assert tags_mod.load_persona_tags() == {}

    def test_empty_file_returns_empty_dict(self, config_dir):
        (config_dir / "persona_tags.json").write_text("", encoding="utf-8")
        assert tags_mod.load_persona_tags() == {}

    def test_directory_instead_of_file_is_tolerated(self, config_dir):
        """OSError 分支：同名目录会让 read_text 抛 IsADirectoryError。"""
        (config_dir / "persona_tags.json").mkdir()
        assert tags_mod.load_persona_tags() == {}


class TestTagNames:
    def test_preserves_insertion_order(self, config_dir):
        _write_tags(config_dir, {"b": {}, "a": {}, "c": {}})
        assert tags_mod.tag_names() == ["b", "a", "c"]

    def test_empty_when_file_missing(self, config_dir):
        assert tags_mod.tag_names() == []

    def test_returns_plain_list(self, config_dir):
        _write_tags(config_dir, {"x": {}})
        assert isinstance(tags_mod.tag_names(), list)


class TestApplyPersonaTagsMerge:
    def test_single_tag_creates_layer(self, config_dir):
        _write_tags(config_dir, {"话痨": {"speaking_style": {"说话量": "话多"}}})
        persona = tags_mod.apply_persona_tags({}, ["话痨"])
        assert persona["speaking_style"]["说话量"] == "话多"

    def test_existing_field_wins(self, config_dir):
        """用户在进阶配置里手填过的字段优先，标签不能覆盖。"""
        _write_tags(config_dir, {"话痨": {"speaking_style": {"说话量": "话多"}}})
        persona = {"speaking_style": {"说话量": "惜字如金"}}
        tags_mod.apply_persona_tags(persona, ["话痨"])
        assert persona["speaking_style"]["说话量"] == "惜字如金"

    def test_merge_fills_missing_keys(self, config_dir):
        """已有 layer 时按键合并，不整块替换。"""
        _write_tags(
            config_dir,
            {"温柔": {"speaking_style": {"语气": "轻", "语速": "慢"}}},
        )
        persona = {"speaking_style": {"语气": "我自己写的"}}
        tags_mod.apply_persona_tags(persona, ["温柔"])
        assert persona["speaking_style"]["语气"] == "我自己写的"
        assert persona["speaking_style"]["语速"] == "慢"

    def test_multiple_tags_apply_in_order(self, config_dir):
        _write_tags(
            config_dir,
            {
                "话痨": {"speaking_style": {"说话量": "话多"}},
                "高冷": {"relationship_behavior": {"主动程度": "低"}},
            },
        )
        persona = tags_mod.apply_persona_tags({}, ["话痨", "高冷"])
        assert persona["speaking_style"]["说话量"] == "话多"
        assert persona["relationship_behavior"]["主动程度"] == "低"

    def test_first_tag_wins_on_same_key(self, config_dir):
        """两个标签撞同一个 key 时，先出现的那个生效（setdefault 语义）。"""
        _write_tags(
            config_dir,
            {
                "话痨": {"speaking_style": {"说话量": "话多"}},
                "高冷": {"speaking_style": {"说话量": "话少"}},
            },
        )
        persona = tags_mod.apply_persona_tags({}, ["话痨", "高冷"])
        assert persona["speaking_style"]["说话量"] == "话多"

    def test_unknown_tag_skipped(self, config_dir):
        _write_tags(config_dir, {"话痨": {"speaking_style": {"说话量": "话多"}}})
        persona = tags_mod.apply_persona_tags({}, ["不存在的标签", "话痨"])
        assert persona["speaking_style"]["说话量"] == "话多"

    def test_empty_tags_still_normalizes_layers(self, config_dir):
        _write_tags(config_dir, {})
        persona = tags_mod.apply_persona_tags({}, [])
        for layer in tags_mod.DEFAULT_LAYERS:
            assert persona[layer] == {}
        assert persona["hard_rules"] == []

    def test_none_tags_normalized(self, config_dir):
        """`tags or []` —— 传 None 不能炸。"""
        _write_tags(config_dir, {})
        persona = tags_mod.apply_persona_tags({}, None)
        assert persona["hard_rules"] == []

    def test_non_dict_persona_returned_as_is(self, config_dir):
        _write_tags(config_dir, {"话痨": {"speaking_style": {"说话量": "话多"}}})
        assert tags_mod.apply_persona_tags(None, ["话痨"]) is None
        assert tags_mod.apply_persona_tags("字符串", ["话痨"]) == "字符串"

    def test_returns_same_object(self, config_dir):
        """原地修改并返回同一个对象的契约（方便链式调用）。"""
        _write_tags(config_dir, {"话痨": {"speaking_style": {"说话量": "话多"}}})
        persona = {}
        assert tags_mod.apply_persona_tags(persona, ["话痨"]) is persona


class TestApplyPersonaTagsListLayer:
    def test_hard_rules_appended(self, config_dir):
        _write_tags(config_dir, {"冷暴力": {"hard_rules": ["不许冷暴力"]}})
        persona = tags_mod.apply_persona_tags({}, ["冷暴力"])
        assert persona["hard_rules"] == ["不许冷暴力"]

    def test_hard_rules_dedup_keeps_order(self, config_dir):
        _write_tags(
            config_dir,
            {
                "冷暴力": {"hard_rules": ["不许冷暴力", "不许消失"]},
                "有主见": {"hard_rules": ["不要一味附和"]},
            },
        )
        persona = {"hard_rules": ["不许消失", "用户自填规则"]}
        tags_mod.apply_persona_tags(persona, ["冷暴力", "有主见"])
        assert persona["hard_rules"] == ["不许消失", "用户自填规则", "不许冷暴力", "不要一味附和"]

    def test_hard_rules_repeat_apply_is_idempotent(self, config_dir):
        """同一个标签应用两次，列表不该翻倍。"""
        _write_tags(config_dir, {"冷暴力": {"hard_rules": ["不许冷暴力"]}})
        persona = tags_mod.apply_persona_tags({}, ["冷暴力"])
        tags_mod.apply_persona_tags(persona, ["冷暴力"])
        assert persona["hard_rules"] == ["不许冷暴力"]

    def test_non_list_hard_rules_replaced(self, config_dir):
        """`hard_rules` 被写成了字符串/None 时重置成列表，不能把字符拆开。"""
        _write_tags(config_dir, {"冷暴力": {"hard_rules": ["不许冷暴力"]}})
        persona = {"hard_rules": "不是列表"}
        tags_mod.apply_persona_tags(persona, ["冷暴力"])
        assert persona["hard_rules"] == ["不许冷暴力"]

    def test_hard_rules_field_that_is_not_list_skipped(self, config_dir):
        """标签表里 hard_rules 自己写成字符串 → 跳过该层（不会把字拆成字符列表）。"""
        _write_tags(config_dir, {"坏的": {"hard_rules": "不许冷暴力"}})
        persona = tags_mod.apply_persona_tags({}, ["坏的"])
        assert persona["hard_rules"] == []


class TestApplyPersonaTagsNormalization:
    def test_existing_layer_not_dict_is_replaced(self, config_dir):
        """layer 存在但不是 dict（比如被填成字符串）→ 整块换成标签内容。"""
        _write_tags(config_dir, {"话痨": {"speaking_style": {"说话量": "话多"}}})
        persona = {"speaking_style": "我的错误写法"}
        tags_mod.apply_persona_tags(persona, ["话痨"])
        assert persona["speaking_style"] == {"说话量": "话多"}

    def test_default_layers_repaired_when_wrong_type(self, config_dir):
        _write_tags(config_dir, {})
        persona = {"speaking_style": "x", "emotional_patterns": 1, "relationship_behavior": None}
        tags_mod.apply_persona_tags(persona, [])
        for layer in tags_mod.DEFAULT_LAYERS:
            assert persona[layer] == {}

    def test_extra_layers_preserved(self, config_dir):
        """persona 里其它字段（name/age/background…）不能被这层逻辑动到。"""
        _write_tags(config_dir, {"话痨": {"speaking_style": {"说话量": "话多"}}})
        persona = {"name": "慕", "age": 20, "personality": ["真诚"]}
        tags_mod.apply_persona_tags(persona, ["话痨"])
        assert persona["name"] == "慕"
        assert persona["age"] == 20
        assert persona["personality"] == ["真诚"]

    def test_malformed_translation_skipped(self, config_dir):
        """标签值是字符串或层值不是 dict → 跳过，不炸也不写脏数据。"""
        _write_tags(
            config_dir,
            {
                "坏的": "不是 dict",
                "半坏": {"speaking_style": "也不是 dict", "emotional_patterns": {"a": "b"}},
            },
        )
        persona = tags_mod.apply_persona_tags({}, ["坏的", "半坏"])
        assert persona["speaking_style"] == {}
        assert persona["emotional_patterns"] == {"a": "b"}


class TestShippedTagFile:
    """真实 config/persona_tags.json 的形状约束（这文件是入库的）。

    这个文件已升级到 v2 schema（`{"version": 2, "tags": {...}}`），所以校验
    必须**按 schema 分支**：直接把顶层 key 当标签名遍历，会把 `version` /
    `max_tags` / `mutex_groups` 当成标签，`set(2)` 直接抛
    `TypeError: argument of type 'int' is not iterable`。那类失败不是被测代码
    的问题，而是测试还在按 v1 的形状断言。
    """

    def test_shipped_file_loads(self):
        data = tags_mod.load_persona_tags()
        assert isinstance(data, dict)
        assert len(tags_mod.tag_names()) >= 10, "标签表被清空过？"

    def test_every_layer_key_is_known(self):
        """标签里出现的层必须落在已知层内。

        出现未知层说明有人加了新行为层却没登记 —— 那些字段会被写进 persona
        但没人读，等于静默失效。v2 的字段是 speaking/emotion/relationship/
        hard_rules，v1 的是三个 DEFAULT_LAYERS + hard_rules。
        """
        known_v2 = {"speaking", "emotion", "relationship", "hard_rules"}
        known_v1 = set(tags_mod.DEFAULT_LAYERS) | set(tags_mod.LIST_LAYERS)

        if tags_mod.is_v2():
            for name, spec in tags_mod.load_persona_tags()["tags"].items():
                unknown = set(spec) - known_v2
                assert not unknown, f"标签 {name} 含未登记的字段：{unknown}"
        else:
            for name, translation in tags_mod.load_persona_tags().items():
                unknown = set(translation) - known_v1
                assert not unknown, f"标签 {name} 含未登记的层：{unknown}"

    def test_list_layers_are_lists(self):
        if tags_mod.is_v2():
            for name, spec in tags_mod.load_persona_tags()["tags"].items():
                assert isinstance(spec.get("hard_rules", []), list), f"{name}.hard_rules 应为列表"
        else:
            for name, translation in tags_mod.load_persona_tags().items():
                for layer in tags_mod.LIST_LAYERS:
                    if layer in translation:
                        assert isinstance(translation[layer], list), f"{name}.{layer} 应为列表"

    def test_dict_layers_are_dicts(self):
        if tags_mod.is_v2():
            for name, spec in tags_mod.load_persona_tags()["tags"].items():
                assert isinstance(spec, dict), f"{name} 应为 dict"
                # 三句描述必须是字符串 —— 前端直接塞进 textarea
                for field in ("speaking", "emotion", "relationship"):
                    assert isinstance(spec.get(field, ""), str), f"{name}.{field} 应为字符串"
        else:
            for name, translation in tags_mod.load_persona_tags().items():
                for layer in tags_mod.DEFAULT_LAYERS:
                    if layer in translation:
                        assert isinstance(translation[layer], dict), f"{name}.{layer} 应为 dict"

    def test_applying_all_tags_never_crashes(self):
        """把全部内置标签一起挂上，结果必须是可序列化的干净 persona。"""
        all_tags = tags_mod.tag_names()
        persona = tags_mod.apply_persona_tags({}, all_tags)
        for layer in tags_mod.DEFAULT_LAYERS:
            assert isinstance(persona[layer], dict)
        assert isinstance(persona["hard_rules"], list)
        json.dumps(persona, ensure_ascii=False)  # 不能有不可序列化对象

    def test_shipped_v2_declares_its_version(self):
        """v2 文件必须带 version 字段，否则别处无法判断代际。"""
        if not tags_mod.is_v2():
            pytest.skip("当前是 v1 翻译表")
        assert tags_mod.load_persona_tags().get("version") == 2

    def test_shipped_mutex_groups_reference_real_tags(self):
        """互斥组里不能出现不存在的标签名 —— 前端照着它做自动取消。"""
        names = set(tags_mod.tag_names())
        for group in tags_mod.mutex_groups():
            for name in group:
                assert name in names, f"互斥组引用了不存在的标签：{name}"


# ============================================================
# v2: 「点标签 → 预填草稿 → 用户改 → 落库」这条链路
# ------------------------------------------------------------
# 这三步任何一步错位都会让用户看见的文本和最终落库的文本不一致，
# 而那种 bug 在界面上完全看不出来（人设建好了，行为却是别的）。
# 所以每一环单独钉住。
# ============================================================

V2_FIXTURE = {
    "version": 2,
    "max_tags": 2,
    "mutex_groups": [["话痨", "高冷"]],
    "tags": {
        "温柔": {
            "speaking": "语气温和",
            "emotion": "先安抚",
            "relationship": "主动照顾",
            "hard_rules": [],
        },
        "细心": {
            "speaking": "会提醒加衣",
            "emotion": "能察觉变化",
            "relationship": "记得喜好",
            "hard_rules": ["不敷衍"],
        },
        "话痨": {
            "speaking": "话多",
            "emotion": "情绪外放",
            "relationship": "爱分享",
            "hard_rules": [],
        },
        "高冷": {
            "speaking": "话少",
            "emotion": "不轻易表露",
            "relationship": "慢热",
            "hard_rules": [],
        },
    },
}


@pytest.fixture()
def v2_config(config_dir):
    _write_tags(config_dir, V2_FIXTURE)
    return config_dir


class TestV2Metadata:
    def test_is_v2_detects_block(self, v2_config):
        assert tags_mod.is_v2() is True

    def test_max_tags_read_from_file(self, v2_config):
        assert tags_mod.max_tags() == 2

    def test_max_tags_falls_back_on_garbage(self, config_dir):
        _write_tags(config_dir, {**V2_FIXTURE, "max_tags": "abc"})
        assert tags_mod.max_tags() == tags_mod.DEFAULT_MAX_TAGS

    def test_max_tags_falls_back_on_non_positive(self, config_dir):
        _write_tags(config_dir, {**V2_FIXTURE, "max_tags": 0})
        assert tags_mod.max_tags() == tags_mod.DEFAULT_MAX_TAGS

    def test_mutex_groups_parsed(self, v2_config):
        assert tags_mod.mutex_groups() == [["话痨", "高冷"]]

    def test_mutex_groups_drops_single_element(self, config_dir):
        _write_tags(config_dir, {**V2_FIXTURE, "mutex_groups": [["a"], ["b", "c"]]})
        assert tags_mod.mutex_groups() == [["b", "c"]]

    def test_mutex_groups_tolerates_non_list(self, config_dir):
        _write_tags(config_dir, {**V2_FIXTURE, "mutex_groups": "oops"})
        assert tags_mod.mutex_groups() == []

    def test_tag_specs_shape(self, v2_config):
        specs = {s["name"]: s for s in tags_mod.tag_specs()}
        assert set(specs) == {"温柔", "细心", "话痨", "高冷"}
        assert specs["温柔"]["speaking"] == "语气温和"
        assert specs["细心"]["hard_rules"] == ["不敷衍"]

    def test_tag_specs_v1_yields_empty_drafts(self, config_dir):
        """v1 标签没有三句描述 —— 前端据此隐藏预览区，不能塞空串冒充。"""
        _write_tags(config_dir, {"话痨": {"speaking_style": {"说话量": "话多"}}})
        specs = tags_mod.tag_specs()
        assert len(specs) == 1
        assert specs[0]["speaking"] == ""
        assert specs[0]["emotion"] == ""


class TestPreview:
    def test_merges_same_layer_with_joiner(self, v2_config):
        p = tags_mod.preview_persona_tags(["温柔", "细心"])
        assert p["speaking"] == "语气温和" + tags_mod.CONFLICT_JOINER + "会提醒加衣"

    def test_does_not_touch_persona(self, v2_config):
        persona = {}
        tags_mod.preview_persona_tags(["温柔"])
        assert persona == {}

    def test_truncates_beyond_max(self, v2_config):
        p = tags_mod.preview_persona_tags(["温柔", "细心", "话痨"])
        assert p["truncated"] == ["话痨"]
        assert "话多" not in p["speaking"]

    def test_reports_unknown(self, v2_config):
        p = tags_mod.preview_persona_tags(["温柔", "不存在"])
        assert p["unknown"] == ["不存在"]

    def test_reports_conflicts(self, v2_config):
        p = tags_mod.preview_persona_tags(["话痨", "高冷"])
        assert p["conflicts"] == [["话痨", "高冷"]]

    def test_dedupes_identical_sentences(self, config_dir):
        _write_tags(
            config_dir,
            {
                "version": 2,
                "max_tags": 3,
                "tags": {
                    "a": {"speaking": "同一句", "emotion": "", "relationship": "", "hard_rules": []},
                    "b": {"speaking": "同一句", "emotion": "", "relationship": "", "hard_rules": []},
                },
            },
        )
        p = tags_mod.preview_persona_tags(["a", "b"])
        assert p["speaking"] == "同一句"

    def test_dedupes_repeated_tag_name(self, v2_config):
        p = tags_mod.preview_persona_tags(["温柔", "温柔"])
        assert p["speaking"] == "语气温和"

    def test_empty_selection_is_empty(self, v2_config):
        p = tags_mod.preview_persona_tags([])
        assert p["speaking"] == "" and p["hard_rules"] == []


class TestApplyV2:
    def test_writes_three_contract_keys(self, v2_config):
        persona = tags_mod.apply_persona_tags({}, ["温柔"])
        assert persona["speaking_style"]["基础风格"] == "语气温和"
        assert persona["emotional_patterns"]["情感表达"] == "先安抚"
        assert persona["relationship_behavior"]["相处模式"] == "主动照顾"

    def test_does_not_overwrite_handwritten_field(self, v2_config):
        persona = {"speaking_style": {"基础风格": "我自己写的"}}
        tags_mod.apply_persona_tags(persona, ["温柔"])
        assert persona["speaking_style"]["基础风格"] == "我自己写的"

    def test_keeps_other_fields_in_same_layer(self, v2_config):
        persona = {"speaking_style": {"说话量": "话少"}}
        tags_mod.apply_persona_tags(persona, ["温柔"])
        assert persona["speaking_style"]["说话量"] == "话少"
        assert persona["speaking_style"]["基础风格"] == "语气温和"

    def test_hard_rules_appended_deduped(self, v2_config):
        persona = {"hard_rules": ["不敷衍", "已存在"]}
        tags_mod.apply_persona_tags(persona, ["细心"])
        assert persona["hard_rules"] == ["不敷衍", "已存在"]

    def test_idempotent(self, v2_config):
        persona = tags_mod.apply_persona_tags({}, ["温柔", "细心"])
        again = tags_mod.apply_persona_tags(persona, ["温柔", "细心"])
        assert again == persona


class TestApplyDrafts:
    def test_user_edit_wins_over_tag(self, v2_config):
        persona = tags_mod.apply_persona_tags({}, ["温柔"])
        tags_mod.apply_drafts(persona, {"speaking": "我改过的"})
        assert persona["speaking_style"]["基础风格"] == "我改过的"

    def test_blank_draft_does_not_erase_tag_text(self, v2_config):
        """清空草稿 = 「这次不用建议」，不等于删掉标签写进去的内容。"""
        persona = tags_mod.apply_persona_tags({}, ["温柔"])
        tags_mod.apply_drafts(persona, {"speaking": "   "})
        assert persona["speaking_style"]["基础风格"] == "语气温和"

    def test_unknown_draft_key_ignored(self, v2_config):
        persona = tags_mod.apply_persona_tags({}, ["温柔"])
        before = json.loads(json.dumps(persona, ensure_ascii=False))
        tags_mod.apply_drafts(persona, {"nonsense": "x", "emotion": None})
        assert persona == before

    def test_drafts_only_without_tags(self, v2_config):
        """用户完全手填、一个标签都没选，也必须能写进三个契约 key。"""
        persona = tags_mod.apply_persona_tags({}, [])
        tags_mod.apply_drafts(
            persona,
            {"speaking": "慢慢说", "emotion": "先听完", "relationship": "不追问"},
        )
        assert persona["speaking_style"]["基础风格"] == "慢慢说"
        assert persona["emotional_patterns"]["情感表达"] == "先听完"
        assert persona["relationship_behavior"]["相处模式"] == "不追问"

    def test_drafts_strip_whitespace(self, v2_config):
        persona = {}
        tags_mod.apply_drafts(persona, {"speaking": "  有空格  "})
        assert persona["speaking_style"]["基础风格"] == "有空格"

    def test_non_dict_inputs_tolerated(self, v2_config):
        assert tags_mod.apply_drafts(None, {"speaking": "x"}) is None
        assert tags_mod.apply_drafts({}, "nope") == {}


class TestPromptContract:
    """标签翻译必须落到 PromptBuilder 真正读的那三个 key 上。

    这是整条链路唯一会被「静默」破坏的地方：写错 key 名不会报错，
    只会让标签在 prompt 里消失，用户以为选了性格其实没生效。
    """

    def test_keys_match_prompt_builder(self, v2_config):
        persona = tags_mod.apply_persona_tags({}, ["温柔"])
        # 这三个 (层, key) 组合来自 prompt_builder 的读取点
        assert "基础风格" in persona["speaking_style"]
        assert "情感表达" in persona["emotional_patterns"]
        assert "相处模式" in persona["relationship_behavior"]

    def test_all_shipped_tags_land_on_contract_keys(self):
        """真实配置里每个标签都必须产出三段非空文本。"""
        if not tags_mod.is_v2():
            pytest.skip("当前是 v1 翻译表")
        for name in tags_mod.tag_names():
            p = tags_mod.preview_persona_tags([name])
            assert p["speaking"], f"{name} 缺 speaking"
            assert p["emotion"], f"{name} 缺 emotion"
            assert p["relationship"], f"{name} 缺 relationship"
