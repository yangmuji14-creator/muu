"""`webui/routes/common.py` 纯辅助函数测试。

这个文件 993 行、原本 0% 覆盖，是 WebUI 与核心之间的唯一适配层：
身份解析、作用域命名、朋友圈存储、MCP 配置清洗都在这里。
挑出来的都是**不依赖 aiohttp 请求对象**的纯函数，能离线跑。

重点守卫（对应 docs/HANDOFF.md 第 3 节 / 第 6 节）：
- 身份由 conversation binding 决定，客户端传的 user_id 不能覆盖它（S6.1 防伪造）。
- `web:default` 这个 T13 迁移 binding 必须继续走 legacy `web_user` 命名空间，
  不能改成 `build_web_uid(persona_id)`，否则老用户的历史会话直接看不见。
"""

import json
from types import SimpleNamespace

import pytest

from core.config import build_memory_scope_uid, build_web_uid, build_wechat_uid
from webui.routes import common
from webui.routes import moments_store


class TestIdGeneration:
    def test_moment_id_shape(self):
        mid = common._new_moment_id()
        assert mid.startswith("mom_")
        assert len(mid) == len("mom_") + 12
        assert common._MOMENT_ID_RE.match(mid)

    def test_reply_id_shape(self):
        rid = common._new_reply_id()
        assert rid.startswith("rep_")
        assert len(rid) == len("rep_") + 12
        assert common._REPLY_ID_RE.match(rid)

    def test_ids_are_unique(self):
        ids = {common._new_moment_id() for _ in range(200)}
        assert len(ids) == 200

    def test_moment_id_is_hex(self):
        tail = common._new_moment_id().split("_", 1)[1]
        int(tail, 16)  # 非十六进制会抛 ValueError


class TestMomentTimestamp:
    def test_iso_with_timezone(self):
        ts = common._moment_now_iso()
        assert "T" in ts
        # 本机时区偏移必须带上（astimezone 的产物）
        assert ts[-6] in "+-" or ts.endswith("Z")

    def test_seconds_precision(self):
        ts = common._moment_now_iso()
        assert len(ts) >= 19


class TestAffectionStage:
    @pytest.mark.parametrize(
        "level,expected",
        [
            (100, "深度关系"),
            (80, "深度关系"),
            (79.9, "亲近"),
            (50, "亲近"),
            (49.9, "熟悉"),
            (20, "熟悉"),
            (19.9, "刚认识"),
            (0, "刚认识"),
            (-5, "刚认识"),
        ],
    )
    def test_thresholds(self, level, expected):
        assert common._affection_stage(level) == expected


class TestSanitizeMcpServer:
    def test_keeps_allowed_fields(self):
        raw = {
            "name": "weather",
            "command": "python",
            "args": ["-u", "mcp_servers/weather.py"],
            "enabled": True,
            "auto_reconnect": True,
            "startup_timeout": 30,
        }
        assert common._sanitize_mcp_server(raw) == raw

    def test_drops_unknown_fields(self):
        raw = {"name": "x", "command": "python", "evil": "payload", "shell": "rm -rf /"}
        assert set(common._sanitize_mcp_server(raw)) == {"name", "command"}

    def test_comment_is_dropped(self):
        # _BUILTIN_MCP_SERVERS 里带 comment 做说明，但清洗时不留
        assert "comment" not in common._sanitize_mcp_server(
            {"name": "system", "comment": "系统工具"}
        )

    def test_empty_input(self):
        assert common._sanitize_mcp_server({}) == {}

    def test_does_not_mutate_input(self):
        raw = {"name": "x", "evil": 1}
        common._sanitize_mcp_server(raw)
        assert raw == {"name": "x", "evil": 1}


class TestValidateWechatAccountId:
    @pytest.mark.parametrize("ok", ["default", "acc", "abc_123", "A" * 32, "my-account"])
    def test_valid(self, ok):
        assert common._validate_wechat_account_id(ok) is True

    @pytest.mark.parametrize(
        "bad",
        ["", "ab", "A" * 33, "has space", "有中文", "dot.dot", "../etc", "a/b"],
    )
    def test_invalid(self, bad):
        assert common._validate_wechat_account_id(bad) is False

    def test_default_exempt_from_length(self):
        # "default" 走的是显式豁免分支（先于正则判断），
        # 它本身也恰好满足 3~32 位规则，所以这里只锁「被独立放行」
        assert common._validate_wechat_account_id("default") is True


class TestWechatCredentialsPath:
    def test_default_uses_plain_name(self):
        assert common._wechat_credentials_path("default").name == "wechat.json"

    def test_named_uses_suffix(self):
        assert common._wechat_credentials_path("acc1").name == "wechat_acc1.json"

    def test_stays_in_creds_dir(self):
        path = common._wechat_credentials_path("acc1")
        assert path.parent == common.WECHAT_CREDS_DIR


class TestUserIdsFromBinding:
    def _binding(self, platform, account_id="", contact_id="", persona_id="p1"):
        return SimpleNamespace(
            platform=platform, account_id=account_id, contact_id=contact_id,
            persona_id=persona_id,
        )

    def test_wechat(self):
        b = self._binding("wechat", account_id="default", contact_id="wxid_abc")
        assert common._user_id_from_binding(b) == build_wechat_uid("default", "wxid_abc")

    def test_web(self):
        assert common._user_id_from_binding(self._binding("web")) == build_web_uid("p1")

    def test_cli(self):
        assert common._user_id_from_binding(self._binding("cli")) == "cli::local"

    def test_api(self):
        assert common._user_id_from_binding(self._binding("api", contact_id="c9")) == "api::c9"

    def test_unknown_platform_falls_back_to_web(self):
        # 未知 platform 不能崩，兜底走 web uid
        assert common._user_id_from_binding(self._binding("telegram")) == build_web_uid("p1")


class _FakeStore:
    def __init__(self, bindings: dict):
        self._bindings = bindings

    def get(self, conversation_id):
        return self._bindings.get(conversation_id)


class TestResolveUserIdFromConversation:
    def test_no_conversation_no_persona_uses_legacy(self):
        uid, conv, persona = common._resolve_user_id_from_conversation(None, None)
        assert uid == common.WEB_USER_ID
        assert conv is None
        assert persona is None

    def test_no_conversation_with_persona(self):
        uid, conv, persona = common._resolve_user_id_from_conversation(None, None, "p1")
        assert uid == build_web_uid("p1")
        assert conv is None
        assert persona is None

    def test_missing_store_raises(self):
        with pytest.raises(common._ConversationNotFound):
            common._resolve_user_id_from_conversation("conv_1", SimpleNamespace(conversation_store=None))

    def test_unknown_conversation_raises(self):
        comps = SimpleNamespace(conversation_store=_FakeStore({}))
        with pytest.raises(common._ConversationNotFound):
            common._resolve_user_id_from_conversation("conv_404", comps)

    def test_web_binding(self):
        binding = SimpleNamespace(platform="web", account_id="web", contact_id="c", persona_id="p1")
        comps = SimpleNamespace(conversation_store=_FakeStore({"conv_6": binding}))
        uid, conv, persona = common._resolve_user_id_from_conversation("conv_6", comps)
        assert uid == build_web_uid("p1")
        assert conv == "conv_6"
        assert persona == "p1"

    def test_wechat_binding(self):
        binding = SimpleNamespace(
            platform="wechat", account_id="default",
            contact_id="wxid@im.wechat", persona_id="1_988fe8",
        )
        comps = SimpleNamespace(conversation_store=_FakeStore({"conv_7": binding}))
        uid, _, persona = common._resolve_user_id_from_conversation("conv_7", comps)
        assert uid == build_wechat_uid("default", "wxid@im.wechat")
        assert persona == "1_988fe8"

    def test_t13_legacy_binding_keeps_web_user_namespace(self):
        # 这是 T13 迁移来的 web:default binding，必须继续走 legacy web_user.json，
        # 改成 build_web_uid(persona_id) 会让老用户的历史会话直接消失。
        binding = SimpleNamespace(platform="web", account_id="", contact_id="default", persona_id="p1")
        comps = SimpleNamespace(conversation_store=_FakeStore({"conv_1": binding}))
        uid, conv, persona = common._resolve_user_id_from_conversation("conv_1", comps)
        assert uid == common.WEB_USER_ID
        assert uid != build_web_uid("p1")
        assert conv == "conv_1"
        assert persona == "p1"


class TestMemoryScopeFromConversation:
    """网页端状态按「角色」隔离，不按「会话」隔离。

    历史行为：每个新会话一套独立的记忆/情绪/人格/亲密度，等于换一个人。
    实测库里因此有 8 套互不相通的状态，主力那套（95 亲密度 / 182 条历史）
    仅因为换了会话就整块失踪。这个类锁住「不再分片」这条契约。
    """

    def test_no_conversation(self):
        assert common._memory_scope_from_conversation(None, None, "u1", "p1") is None

    def test_no_persona(self):
        assert common._memory_scope_from_conversation("conv_1", None, "u1", None) is None

    def test_t13_legacy_binding_has_no_scope(self):
        # legacy web_user.json 命名空间与 scope 命名空间互相隔离，不能混用
        binding = SimpleNamespace(platform="web", account_id="", contact_id="default", persona_id="p1")
        comps = SimpleNamespace(conversation_store=_FakeStore({"conv_1": binding}))
        assert common._memory_scope_from_conversation("conv_1", comps, "web_user", "p1") is None

    def test_real_binding_has_no_extra_scope(self):
        """状态键回落到 user_id（web::<persona>），不再叠 scope_<hash>。"""
        binding = SimpleNamespace(platform="web", account_id="web", contact_id="c", persona_id="p1")
        comps = SimpleNamespace(conversation_store=_FakeStore({"conv_6": binding}))
        assert common._memory_scope_from_conversation("conv_6", comps, "web::p1", "p1") is None

    def test_missing_binding_has_no_scope(self):
        comps = SimpleNamespace(conversation_store=_FakeStore({}))
        assert common._memory_scope_from_conversation("conv_x", comps, "u1", "p1") is None

    def test_scopes_do_not_differ_per_conversation(self):
        """同一角色开两个会话，必须是同一个人。"""
        binding = SimpleNamespace(platform="web", account_id="web", contact_id="c", persona_id="p1")
        comps = SimpleNamespace(conversation_store=_FakeStore({"conv_6": binding, "conv_7": binding}))
        a = common._memory_scope_from_conversation("conv_6", comps, "web::p1", "p1")
        b = common._memory_scope_from_conversation("conv_7", comps, "web::p1", "p1")
        assert a == b is None


class TestResolveScopedUserId:
    def test_returns_role_uid_for_real_binding(self):
        binding = SimpleNamespace(platform="web", account_id="web", contact_id="c", persona_id="p1")
        comps = SimpleNamespace(conversation_store=_FakeStore({"conv_6": binding}))
        uid, conv, persona = common._resolve_scoped_user_id("conv_6", comps)
        assert uid == build_web_uid("p1")
        assert conv == "conv_6"
        assert persona == "p1"

    def test_two_conversations_share_one_identity(self):
        """这是本次改动的核心：换会话不换人。"""
        binding = SimpleNamespace(platform="web", account_id="web", contact_id="c", persona_id="p1")
        comps = SimpleNamespace(
            conversation_store=_FakeStore({"conv_6": binding, "conv_7": binding}),
        )
        first, _, _ = common._resolve_scoped_user_id("conv_6", comps)
        second, _, _ = common._resolve_scoped_user_id("conv_7", comps)
        assert first == second == build_web_uid("p1")

    def test_returns_plain_uid_for_legacy(self):
        binding = SimpleNamespace(platform="web", account_id="", contact_id="default", persona_id="p1")
        comps = SimpleNamespace(conversation_store=_FakeStore({"conv_1": binding}))
        uid, _, _ = common._resolve_scoped_user_id("conv_1", comps)
        assert uid == common.WEB_USER_ID

    def test_no_conversation_with_persona(self):
        uid, conv, _ = common._resolve_scoped_user_id(None, None, "p1")
        assert uid == build_web_uid("p1")
        assert conv is None


class TestScopeKwargs:
    def test_empty_scope_returns_empty(self):
        assert common._scope_kwargs(object(), None) == {}
        assert common._scope_kwargs(object(), "") == {}

    def test_pipeline_with_scope_id(self):
        class P:
            def process(self, *, scope_id=None):
                ...

        assert common._scope_kwargs(P(), "scope_x") == {"scope_id": "scope_x"}

    def test_pipeline_without_scope_id(self):
        class P:
            def process(self, content):
                ...

        assert common._scope_kwargs(P(), "scope_x") == {}

    def test_uninspectable_callable(self):
        # inspect.signature 失败时不能抛，直接不带 scope_id
        assert common._scope_kwargs(len, "scope_x") == {}


class TestGuardClientIdentity:
    def test_none_allowed(self):
        assert common._guard_client_identity(None, "u1", where="t") is None

    def test_empty_allowed(self):
        assert common._guard_client_identity("", "u1", where="t") is None

    def test_matching_allowed(self):
        assert common._guard_client_identity("u1", "u1", where="t") is None

    def test_matching_after_strip(self):
        assert common._guard_client_identity("  u1  ", "u1", where="t") is None

    def test_mismatch_rejected_with_403(self):
        resp = common._guard_client_identity("attacker", "u1", where="GET /api/memory")
        assert resp is not None
        assert resp.status == 403
        body = json.loads(resp.text)
        assert "does not match" in body["error"]

    def test_non_string_also_rejected(self):
        # 严格模式：非字符串（数字/对象）既不等于 resolved 也不为空，
        # 一律当伪造处理。宽松放行才是危险的默认。
        resp = common._guard_client_identity(123, "u1", where="t")
        assert resp is not None
        assert resp.status == 403


class TestMomentsStorage:
    @pytest.fixture
    def moments_path(self, tmp_path, monkeypatch):
        """patch 实现模块而不是 common 门面。

        `_MOMENTS_PATH` 的实现搬进 `moments_store` 后，`common._MOMENTS_PATH`
        只是 re-export 的副本 —— patch 门面影响不了 `_load_moments()` 实际读的
        模块级变量，这是拆 facade 时最容易踩的坑。
        """
        path = tmp_path / "moments.json"
        monkeypatch.setattr(moments_store, "_MOMENTS_PATH", path)
        return path

    def test_load_missing_returns_empty(self, moments_path):
        assert common._load_moments() == []

    def test_save_then_load(self, moments_path):
        data = [{"id": "mom_aaaaaaaaaaaa", "text": "今天下雨", "likes": [], "replies": []}]
        common._save_moments(data)
        assert common._load_moments() == data

    def test_saved_file_is_wrapped_in_object(self, moments_path):
        common._save_moments([{"id": "x"}])
        raw = json.loads(moments_path.read_text(encoding="utf-8"))
        assert list(raw) == ["moments"]

    def test_bare_list_file_returns_empty(self, moments_path):
        # 顶层是数组时 .get("moments") 会 AttributeError，被兜住返回 []
        moments_path.write_text('[{"id": "x"}]', encoding="utf-8")
        assert common._load_moments() == []

    def test_broken_json_returns_empty(self, moments_path):
        moments_path.write_text("{oops", encoding="utf-8")
        assert common._load_moments() == []

    def test_null_moments_returns_empty(self, moments_path):
        moments_path.write_text('{"moments": null}', encoding="utf-8")
        assert common._load_moments() == []

    def test_save_creates_parent_dir(self, tmp_path, monkeypatch):
        path = tmp_path / "nested" / "moments.json"
        monkeypatch.setattr(moments_store, "_MOMENTS_PATH", path)
        common._save_moments([{"id": "x"}])
        assert path.exists()

    def test_save_leaves_no_tmp_file(self, moments_path):
        common._save_moments([{"id": "x"}])
        assert [p.name for p in moments_path.parent.iterdir()] == ["moments.json"]

    def test_chinese_not_escaped(self, moments_path):
        common._save_moments([{"text": "降温了"}])
        assert "降温了" in moments_path.read_text(encoding="utf-8")


class TestMomentAuthorLabel:
    def test_user_is_me(self):
        assert common._moment_author_label(None, "user") == "我"

    def test_empty_author(self):
        assert common._moment_author_label(None, "") == ""

    def test_known_persona_uses_name(self):
        loader = SimpleNamespace(list_all=lambda: [
            SimpleNamespace(id="girlfriend_001", name="慕"),
        ])
        comps = SimpleNamespace(persona_loader=loader)
        assert common._moment_author_label(comps, "girlfriend_001") == "慕"

    def test_unknown_persona_returns_id(self):
        loader = SimpleNamespace(list_all=lambda: [SimpleNamespace(id="a", name="A")])
        comps = SimpleNamespace(persona_loader=loader)
        assert common._moment_author_label(comps, "b") == "b"

    def test_missing_loader_returns_id(self):
        assert common._moment_author_label(SimpleNamespace(persona_loader=None), "pfx") == "pfx"

    def test_loader_raises_returns_id(self):
        def boom():
            raise RuntimeError("loader broken")

        comps = SimpleNamespace(persona_loader=SimpleNamespace(list_all=boom))
        assert common._moment_author_label(comps, "pfx") == "pfx"

    def test_persona_without_name_falls_back_to_id(self):
        loader = SimpleNamespace(list_all=lambda: [SimpleNamespace(id="px", name="")])
        comps = SimpleNamespace(persona_loader=loader)
        assert common._moment_author_label(comps, "px") == "px"


class TestConstants:
    def test_text_length_limits(self):
        assert common._MAX_POST_TEXT == 2000
        assert common._MAX_REPLY_TEXT == 500

    def test_image_upload_limits(self):
        assert common.MAX_IMAGE_UPLOAD_SIZE == 10 * 1024 * 1024
        assert common.ALLOWED_IMAGE_TYPES == {"image/jpeg", "image/png", "image/webp", "image/gif"}

    def test_static_dir_points_at_webui_static(self):
        # 这个目录曾经错指向 webui/routes/static，导致首页 404
        assert common.STATIC_DIR.name == "static"
        assert common.STATIC_DIR.parent.name == "webui"

    def test_builtin_mcp_servers_shape(self):
        assert {s["name"] for s in common._BUILTIN_MCP_SERVERS} == {"system", "web", "weather"}
        for server in common._BUILTIN_MCP_SERVERS:
            assert server["command"] == "python"
            assert server["args"][0] == "-u"
            assert server["args"][1].endswith(".py")
