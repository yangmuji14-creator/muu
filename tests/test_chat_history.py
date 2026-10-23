"""core/memory/chat_history.py 的单元测试

重点两块：
    - 路径分派与路径穿越防护（wechat / web / cli / api / legacy 五条分支）
    - 落盘语义：全量保留、损坏文件改名保留、``delete_last_messages`` 的
      ``count<=0`` 陷阱

全部 ``tmp_path`` 隔离，不碰真实 ``data/``。
"""

from __future__ import annotations

import json

import pytest

from core.config import build_api_uid, build_cli_uid, build_web_uid, build_wechat_uid
from core.memory.chat_history import ChatHistoryStorage


@pytest.fixture()
def store(tmp_path):
    return ChatHistoryStorage(tmp_path)


# --------------------------------------------------------------------------- #
# 路径分派
# --------------------------------------------------------------------------- #


class TestUserFilePath:
    def test_wechat_subdir(self, store, tmp_path) -> None:
        path = store._get_user_file(build_wechat_uid("default", "abc@im.wechat"))
        assert path == (tmp_path / "chat_history" / "wechat" / "default" / "abc@im.wechat.json").resolve()

    def test_web_subdir(self, store, tmp_path) -> None:
        path = store._get_user_file(build_web_uid("girlfriend_001"))
        assert path == (tmp_path / "chat_history" / "web" / "girlfriend_001.json").resolve()

    def test_cli_subdir(self, store, tmp_path) -> None:
        path = store._get_user_file(build_cli_uid())
        assert path == (tmp_path / "chat_history" / "cli" / "local.json").resolve()

    def test_api_subdir(self, store, tmp_path) -> None:
        path = store._get_user_file(build_api_uid("alice"))
        assert path == (tmp_path / "chat_history" / "api" / "alice.json").resolve()

    def test_legacy_flat_file(self, store, tmp_path) -> None:
        """无 ``::`` 的旧 user_id 落在 chat_history 根下。"""
        path = store._get_user_file("web_user")
        assert path == (tmp_path / "chat_history" / "web_user.json").resolve()

    def test_scope_uid_is_legacy_shape(self, store, tmp_path) -> None:
        """``scope_xxx`` 没有 ``::``，因此走 legacy 扁平路径。

        这是 ``scope_*.json`` 与 ``web/*.json`` 两代路径并存的原因 ——
        不是重复写同一份数据。
        """
        path = store._get_user_file("scope_abc123")
        assert path.parent == (tmp_path / "chat_history").resolve()

    def test_subdirs_created_on_demand(self, store, tmp_path) -> None:
        store._get_user_file(build_wechat_uid("acc", "wx1"))
        assert (tmp_path / "chat_history" / "wechat" / "acc").is_dir()


class TestPathTraversal:
    @pytest.mark.parametrize("bad", ["../evil", "a/b", "a\\b", "..", "a b"])
    def test_persona_id_rejected(self, store, bad: str) -> None:
        with pytest.raises(ValueError):
            store._get_user_file(build_web_uid(bad))

    @pytest.mark.parametrize("bad", ["../x", "a/b"])
    def test_wxid_rejected(self, store, bad: str) -> None:
        with pytest.raises(ValueError):
            store._get_user_file(build_wechat_uid("default", bad))

    def test_account_id_rejected(self, store) -> None:
        with pytest.raises(ValueError):
            store._get_user_file(build_wechat_uid("../up", "wx1"))

    @pytest.mark.parametrize("bad", ["../x", "a/b"])
    def test_api_user_rejected(self, store, bad: str) -> None:
        with pytest.raises(ValueError):
            store._get_user_file(build_api_uid(bad))

    def test_dotted_ok(self, store) -> None:
        """``a.b`` 是合法文件名，不该被拒。"""
        assert store._get_user_file(build_api_uid("a.b")).name == "a.b.json"

    def test_dotdot_inside_rejected(self, store) -> None:
        with pytest.raises(ValueError):
            store._get_user_file(build_api_uid("a..b"))

    def test_legacy_sanitizes_instead_of_raising(self, store, tmp_path) -> None:
        """legacy 分支是 sanitize 而不是抛错：旧数据里有脏 id 也必须能读。"""
        path = store._get_user_file("weird id!@#")
        assert path.parent == (tmp_path / "chat_history").resolve()
        assert " " not in path.name

    def test_legacy_dotdot_stays_inside(self, store, tmp_path) -> None:
        """``../x`` 里的 ``/`` 被换成 ``_``，所以不会越出数据目录。"""
        path = store._get_user_file("../x")
        assert path.parent == (tmp_path / "chat_history").resolve()


# --------------------------------------------------------------------------- #
# 读写与缓存
# --------------------------------------------------------------------------- #


class TestLoadSave:
    def test_missing_returns_empty(self, store) -> None:
        assert store.load(build_web_uid("p1")) == {"messages": [], "short_memories": []}

    def test_add_then_read(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "你好")
        assert store.get_messages(uid)[0]["content"] == "你好"

    def test_timestamp_added(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "hi")
        assert "T" in store.get_messages(uid)[0]["timestamp"]

    def test_persisted_to_disk(self, tmp_path) -> None:
        uid = build_web_uid("p1")
        ChatHistoryStorage(tmp_path).add_message(uid, "user", "落盘")
        raw = json.loads(
            (tmp_path / "chat_history" / "web" / "p1.json").read_text(encoding="utf-8")
        )
        assert raw["messages"][0]["content"] == "落盘"

    def test_file_is_utf8(self, store, tmp_path) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "中文内容")
        text = (tmp_path / "chat_history" / "web" / "p1.json").read_text(encoding="utf-8")
        assert "中文内容" in text

    def test_cache_returns_same_object(self, store) -> None:
        uid = build_web_uid("p1")
        assert store.load(uid) is store.load(uid)

    def test_two_instances_share_file(self, tmp_path) -> None:
        uid = build_web_uid("p1")
        ChatHistoryStorage(tmp_path).add_message(uid, "user", "第一条")
        assert ChatHistoryStorage(tmp_path).get_messages(uid)[0]["content"] == "第一条"

    def test_save_without_cache_is_noop(self, store) -> None:
        store.save(build_web_uid("never_loaded"))  # 不该抛异常

    def test_users_isolated(self, store) -> None:
        store.add_message(build_web_uid("a"), "user", "A")
        store.add_message(build_web_uid("b"), "user", "B")
        assert store.get_messages(build_web_uid("a"))[0]["content"] == "A"


class TestCorruptFile:
    def test_backed_up_not_overwritten(self, store, tmp_path) -> None:
        uid = build_web_uid("p1")
        path = tmp_path / "chat_history" / "web" / "p1.json"
        path.parent.mkdir(parents=True)
        path.write_text("{ not json", encoding="utf-8")

        assert store.get_messages(uid) == []
        corrupt = path.with_suffix(".json.corrupt")
        assert corrupt.exists()
        assert corrupt.read_text(encoding="utf-8") == "{ not json"
        assert not path.exists()

    def test_second_load_survives(self, store, tmp_path) -> None:
        uid = build_web_uid("p1")
        path = tmp_path / "chat_history" / "web" / "p1.json"
        path.parent.mkdir(parents=True)
        path.write_text("garbage", encoding="utf-8")
        store.get_messages(uid)
        assert store.get_messages(uid) == []

    def test_existing_corrupt_kept(self, store, tmp_path) -> None:
        """已有 .corrupt 时不覆盖 —— 保留第一份真实数据。"""
        uid = build_web_uid("p1")
        path = tmp_path / "chat_history" / "web" / "p1.json"
        path.parent.mkdir(parents=True)
        path.write_text("second corruption", encoding="utf-8")
        corrupt = path.with_suffix(".json.corrupt")
        corrupt.write_text("first corruption", encoding="utf-8")

        store.get_messages(uid)
        assert corrupt.read_text(encoding="utf-8") == "first corruption"

    def test_rename_failure_is_swallowed(self, store, tmp_path, monkeypatch) -> None:
        """改名失败也要继续返回空数据，不能让读历史把主链路搞崩。"""
        uid = build_web_uid("p1")
        path = tmp_path / "chat_history" / "web" / "p1.json"
        path.parent.mkdir(parents=True)
        path.write_text("{ broken", encoding="utf-8")

        def boom(self, target):
            raise OSError("locked")

        monkeypatch.setattr(type(path), "rename", boom, raising=True)
        assert store.get_messages(uid) == []


class TestSaveFailure:
    def test_cache_dropped_on_write_error(self, store, monkeypatch) -> None:
        """写盘失败时把缓存丢掉：下次读会重新从磁盘来，不会一直以为是新数据。"""
        uid = build_web_uid("p1")
        store.load(uid)  # 先建缓存

        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr("core.memory.chat_history.atomic_write_json", boom)
        store.save(uid)
        assert uid not in store._cache


class TestMaxStored:
    def test_default_is_unlimited(self, store) -> None:
        assert store._max_stored is None

    def test_zero_means_unlimited(self, tmp_path) -> None:
        assert ChatHistoryStorage(tmp_path, max_stored=0)._max_stored is None

    def test_none_means_unlimited(self, tmp_path) -> None:
        assert ChatHistoryStorage(tmp_path, max_stored=None)._max_stored is None

    def test_bad_value_means_unlimited(self, tmp_path) -> None:
        assert ChatHistoryStorage(tmp_path, max_stored="abc")._max_stored is None

    def test_trims_to_cap(self, tmp_path) -> None:
        store = ChatHistoryStorage(tmp_path, max_stored=3)
        uid = build_web_uid("p1")
        for i in range(6):
            store.add_message(uid, "user", f"m{i}")
        contents = [m["content"] for m in store.get_messages(uid)]
        assert contents == ["m3", "m4", "m5"]

    def test_no_trim_at_exact_cap(self, tmp_path) -> None:
        store = ChatHistoryStorage(tmp_path, max_stored=3)
        uid = build_web_uid("p1")
        for i in range(3):
            store.add_message(uid, "user", f"m{i}")
        assert len(store.get_messages(uid)) == 3


# --------------------------------------------------------------------------- #
# 消息字段
# --------------------------------------------------------------------------- #


class TestAddMessageFields:
    def test_optional_fields_absent_by_default(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "hi")
        msg = store.get_messages(uid)[0]
        assert set(msg) == {"role", "content", "timestamp"}

    def test_emotion_fields(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(
            uid, "user", "hi",
            emotion="happy", emotion_intensity=0.7777, emotion_understanding="很开心",
        )
        msg = store.get_messages(uid)[0]
        assert msg["emotion"] == "happy"
        assert msg["emotion_intensity"] == 0.778  # round 到 3 位
        assert msg["emotion_understanding"] == "很开心"

    def test_platform_fields(self, store) -> None:
        uid = build_wechat_uid("acc", "wx1")
        store.add_message(uid, "user", "hi", platform="wechat", persona_id="p1", account_id="acc")
        msg = store.get_messages(uid)[0]
        assert msg["platform"] == "wechat"
        assert msg["persona_id"] == "p1"
        assert msg["account_id"] == "acc"

    def test_sticker_only_metadata_keys(self, store) -> None:
        """贴纸只留元数据，多余的键丢掉 —— 不然历史文件会塞满没用的东西。"""
        uid = build_web_uid("p1")
        store.add_message(uid, "assistant", "[贴纸]", sticker={
            "pack": "pawzochat-default", "emotion": "loved",
            "filename": "1.png", "url": "/static/x.png", "junk": "drop me",
        })
        assert store.get_messages(uid)[0]["sticker"] == {
            "pack": "pawzochat-default", "emotion": "loved",
            "filename": "1.png", "url": "/static/x.png",
        }

    def test_empty_sticker_dict_skipped(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "assistant", "x", sticker={})
        assert "sticker" not in store.get_messages(uid)[0]

    def test_image_and_desc(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "", image="/attachments/a.png", image_desc="一只猫")
        msg = store.get_messages(uid)[0]
        assert msg["image"] == "/attachments/a.png"
        assert msg["image_desc"] == "一只猫"

    def test_voice(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "assistant", "", voice="/attachments/a.mp3")
        assert store.get_messages(uid)[0]["voice"] == "/attachments/a.mp3"

    def test_empty_platform_not_stored(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "x", platform="", persona_id="", account_id="")
        assert "platform" not in store.get_messages(uid)[0]


class TestUpdateImageDesc:
    def test_updates_matching_message(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "", image="/a.png")
        assert store.update_image_desc(uid, "/a.png", " 一只猫 ") is True
        assert store.get_messages(uid)[0]["image_desc"] == "一只猫"

    def test_skips_already_described(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "", image="/a.png", image_desc="旧描述")
        assert store.update_image_desc(uid, "/a.png", "新描述") is False

    def test_missing_image(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "", image="/a.png")
        assert store.update_image_desc(uid, "/b.png", "描述") is False

    def test_empty_args(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "", image="/a.png")
        assert store.update_image_desc(uid, "", "描述") is False
        assert store.update_image_desc(uid, "/a.png", "   ") is False

    def test_updates_latest_only(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "", image="/a.png")
        store.add_message(uid, "user", "", image="/a.png")
        store.update_image_desc(uid, "/a.png", "第二张的描述")
        messages = store.get_messages(uid)
        assert "image_desc" not in messages[0]
        assert messages[1]["image_desc"] == "第二张的描述"

    def test_ignores_assistant_message(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "assistant", "", image="/a.png")
        assert store.update_image_desc(uid, "/a.png", "描述") is False


# --------------------------------------------------------------------------- #
# 短期记忆
# --------------------------------------------------------------------------- #


class TestShortMemories:
    def test_add(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_short_memory(uid, "你好", "嗯")
        assert store.get_short_memories(uid) == [{"user": "你好", "assistant": "嗯"}]

    def test_clear(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_short_memory(uid, "a", "b")
        store.clear_short_memories(uid)
        assert store.get_short_memories(uid) == []

    def test_clear_persisted(self, tmp_path) -> None:
        uid = build_web_uid("p1")
        ChatHistoryStorage(tmp_path).add_short_memory(uid, "a", "b")
        ChatHistoryStorage(tmp_path).clear_short_memories(uid)
        assert ChatHistoryStorage(tmp_path).get_short_memories(uid) == []


# --------------------------------------------------------------------------- #
# 删除
# --------------------------------------------------------------------------- #


class TestDeleteLastMessages:
    def test_deletes_and_returns(self, store) -> None:
        uid = build_web_uid("p1")
        for i in range(4):
            store.add_message(uid, "user", f"m{i}")
        deleted = store.delete_last_messages(uid, 2)
        assert [m["content"] for m in deleted] == ["m2", "m3"]
        assert [m["content"] for m in store.get_messages(uid)] == ["m0", "m1"]

    def test_zero_deletes_nothing(self, store) -> None:
        """``messages[:-0]`` 是空列表 —— 不特判会把全部历史删光。"""
        uid = build_web_uid("p1")
        for i in range(3):
            store.add_message(uid, "user", f"m{i}")
        assert store.delete_last_messages(uid, 0) == []
        assert len(store.get_messages(uid)) == 3

    def test_negative_deletes_nothing(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "m0")
        assert store.delete_last_messages(uid, -5) == []
        assert len(store.get_messages(uid)) == 1

    def test_none_deletes_nothing(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "m0")
        assert store.delete_last_messages(uid, None) == []
        assert len(store.get_messages(uid)) == 1

    def test_count_clamped_to_length(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "m0")
        assert len(store.delete_last_messages(uid, 99)) == 1
        assert store.get_messages(uid) == []

    def test_empty_history(self, store) -> None:
        assert store.delete_last_messages(build_web_uid("p1"), 2) == []


class TestDeleteUser:
    def test_removes_file(self, store, tmp_path) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "x")
        assert store.delete_user(uid) is True
        assert not (tmp_path / "chat_history" / "web" / "p1.json").exists()

    def test_missing_returns_false(self, store) -> None:
        assert store.delete_user(build_web_uid("nobody")) is False

    def test_cache_invalidated(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "x")
        store.delete_user(uid)
        assert store.get_messages(uid) == []


# --------------------------------------------------------------------------- #
# 搜索
# --------------------------------------------------------------------------- #


class TestSearchMessages:
    def test_finds_exact(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "我喜欢跑步")
        store.add_message(uid, "assistant", "那很好")
        results = store.search_messages(uid, "跑步")
        assert len(results) == 1
        assert results[0]["index"] == 0

    def test_case_insensitive(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "Hello Python")
        assert store.search_messages(uid, "python")

    def test_context_before_after(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "第一句")
        store.add_message(uid, "assistant", "命中这句")
        store.add_message(uid, "user", "第三句")
        hit = store.search_messages(uid, "命中")[0]
        assert hit["before"]["content"] == "第一句"
        assert hit["after"]["content"] == "第三句"

    def test_first_has_no_before(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "只有这句")
        assert store.search_messages(uid, "只有")[0]["before"] is None

    def test_last_has_no_after(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "只有这句")
        assert store.search_messages(uid, "只有")[0]["after"] is None

    def test_limit(self, store) -> None:
        uid = build_web_uid("p1")
        for _ in range(5):
            store.add_message(uid, "user", "重复")
        assert len(store.search_messages(uid, "重复", limit=2)) == 2

    def test_empty_keyword(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "x")
        assert store.search_messages(uid, "") == []

    def test_empty_history(self, store) -> None:
        assert store.search_messages(build_web_uid("p1"), "x") == []


# --------------------------------------------------------------------------- #
# 导出 Markdown
# --------------------------------------------------------------------------- #


class TestExportMarkdown:
    def test_empty_history(self, store) -> None:
        assert store.export_markdown(build_web_uid("p1")) == ""

    def test_header_fields(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "你好")
        md = store.export_markdown(uid, "慕")
        assert md.startswith("# 💬 聊天记录")
        assert "角色：慕" in md
        assert "消息数：1" in md

    def test_roles_rendered(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "你好")
        store.add_message(uid, "assistant", "嗯")
        md = store.export_markdown(uid, "慕")
        assert "🧑 你" in md
        assert "💕 慕" in md

    def test_other_role_raw(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "system", "提示")
        assert "system" in store.export_markdown(uid)

    def test_timestamp_rendered(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "hi")
        assert "`" in store.export_markdown(uid)

    def test_bad_timestamp_tolerated(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "hi")
        store.get_messages(uid)[0]["timestamp"] = "not-a-date"
        md = store.export_markdown(uid)
        assert "hi" in md

    def test_missing_timestamp_tolerated(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "hi")
        del store.get_messages(uid)[0]["timestamp"]
        assert "hi" in store.export_markdown(uid)

    def test_content_included(self, store) -> None:
        uid = build_web_uid("p1")
        store.add_message(uid, "user", "独特内容ABCD")
        assert "独特内容ABCD" in store.export_markdown(uid)


class TestDataDir:
    def test_property(self, store, tmp_path) -> None:
        assert store.data_dir == tmp_path / "chat_history"

    def test_created(self, tmp_path) -> None:
        ChatHistoryStorage(tmp_path)
        assert (tmp_path / "chat_history").is_dir()
