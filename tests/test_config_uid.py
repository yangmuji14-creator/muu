"""用户 ID / 记忆作用域工具测试。

覆盖:
- build_wechat_uid / build_web_uid / build_cli_uid / build_api_uid 的格式
- build_memory_scope_uid 的稳定性与区分度（换 persona/conversation 必须换 key）
- parse_uid 对合法与畸形输入的行为（畸形必须返回 platform="unknown" 而不是抛异常）
"""

import pytest

from core.config import (
    SEP,
    build_api_uid,
    build_cli_uid,
    build_memory_scope_uid,
    build_web_uid,
    build_wechat_uid,
    parse_uid,
)


class TestBuildUid:
    def test_wechat_uid_shape(self):
        assert build_wechat_uid("default", "wxid_abc") == "wechat::default::wxid_abc"

    def test_web_uid_shape(self):
        assert build_web_uid("girlfriend_001") == "web::girlfriend_001"

    def test_cli_uid_shape(self):
        assert build_cli_uid() == "cli::local"

    def test_api_uid_shape(self):
        assert build_api_uid("u1") == "api::u1"

    def test_sep_is_double_colon(self):
        assert SEP == "::"


class TestMemoryScopeUid:
    def test_stable_for_same_inputs(self):
        a = build_memory_scope_uid("web::p", "p1", "conv_1")
        b = build_memory_scope_uid("web::p", "p1", "conv_1")
        assert a == b

    def test_prefix_and_length(self):
        uid = build_memory_scope_uid("web::p", "p1", "conv_1")
        assert uid.startswith("scope_")
        assert len(uid) == len("scope_") + 32

    def test_different_conversation_differs(self):
        a = build_memory_scope_uid("web::p", "p1", "conv_1")
        b = build_memory_scope_uid("web::p", "p1", "conv_2")
        assert a != b

    def test_different_persona_differs(self):
        a = build_memory_scope_uid("web::p", "p1", "conv_1")
        b = build_memory_scope_uid("web::p", "p2", "conv_1")
        assert a != b

    def test_different_user_differs(self):
        a = build_memory_scope_uid("web::p1", "p", "conv_1")
        b = build_memory_scope_uid("web::p2", "p", "conv_1")
        assert a != b

    def test_missing_conversation_is_allowed(self):
        uid = build_memory_scope_uid("web::p", "p1")
        assert uid.startswith("scope_")

    def test_field_boundary_not_ambiguous(self):
        """拼接字段必须无歧义：('ab', 'c') 与 ('a', 'bc') 不能撞。"""
        a = build_memory_scope_uid("ab", "c", "")
        b = build_memory_scope_uid("a", "bc", "")
        assert a != b


class TestParseUid:
    def test_parse_wechat(self):
        got = parse_uid("wechat::default::wxid_abc")
        assert got["platform"] == "wechat"
        assert got["account_id"] == "default"
        assert got["raw_id"] == "wxid_abc"

    def test_parse_web(self):
        got = parse_uid("web::girlfriend_001")
        assert got["platform"] == "web"
        assert got["persona_id"] == "girlfriend_001"
        assert got["raw_id"] == "girlfriend_001"

    def test_parse_cli(self):
        got = parse_uid("cli::local")
        assert got["platform"] == "cli"
        assert got["raw_id"] == "local"

    def test_parse_api(self):
        got = parse_uid("api::u1")
        assert got["platform"] == "api"
        assert got["raw_id"] == "u1"

    @pytest.mark.parametrize("bad", ["", "legacy_user", "scope_abc", "web", "::"])
    def test_malformed_returns_unknown_without_raising(self, bad):
        got = parse_uid(bad)
        assert got["platform"] == "unknown"
        assert got["raw_id"] == bad
