"""通用工具函数测试 —— `core/utils.py` 与诊断脱敏。

`parse_json_response` 是记忆提取、情绪分析、Brain 各处的公共入口：
LLM 只要多写一句客套话或漏一个反引号，整次解析就白费。
这里的用例锁定「能兜到就兜到，兜不到返回 None 而不是抛异常」这一契约。
"""

import json

import pytest

from core.runtime.diagnostics import sanitize_settings
from core.utils import atomic_write_json, parse_json_response, read_json


class TestParseJsonResponse:
    def test_plain_json(self):
        assert parse_json_response('{"a": 1}') == {"a": 1}

    def test_plain_json_with_whitespace(self):
        assert parse_json_response('\n   {"a": 1}  \n') == {"a": 1}

    def test_markdown_json_block(self):
        text = '好的，这是结果：\n```json\n{"emotion": "happy"}\n```\n希望有帮助'
        assert parse_json_response(text) == {"emotion": "happy"}

    def test_markdown_block_without_language_tag(self):
        text = "```\n{\"a\": 1}\n```"
        assert parse_json_response(text) == {"a": 1}

    def test_first_block_wins(self):
        text = '```json\n{"a": 1}\n```\n```json\n{"b": 2}\n```'
        assert parse_json_response(text) == {"a": 1}

    @pytest.mark.parametrize("text", ["", "   ", "\n\n"])
    def test_empty_returns_none(self, text):
        assert parse_json_response(text) is None

    def test_non_json_returns_none(self):
        assert parse_json_response("今天天气不错") is None

    def test_broken_json_returns_none(self):
        assert parse_json_response('{"a": 1,,}') is None

    def test_json_array_returns_none(self):
        # 契约是 dict；数组要由调用方自己处理
        assert parse_json_response("[1, 2, 3]") is None

    def test_json_scalar_returns_none(self):
        assert parse_json_response('"just a string"') is None
        assert parse_json_response("42") is None
        assert parse_json_response("null") is None

    def test_json_in_inline_code_span_not_extracted(self):
        # 只认三反引号块，单反引号不处理
        assert parse_json_response('`{"a": 1}`') is None

    def test_nested_structure(self):
        payload = {"memories": [{"content": "他喜欢烤红薯", "level": 4}]}
        assert parse_json_response(json.dumps(payload, ensure_ascii=False)) == payload


class TestAtomicWriteJson:
    def test_writes_and_reads_back(self, tmp_path):
        target = tmp_path / "nested" / "data.json"
        atomic_write_json(target, {"name": "慕", "level": 3})
        assert json.loads(target.read_text(encoding="utf-8")) == {"name": "慕", "level": 3}

    def test_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "a" / "b" / "c" / "x.json"
        atomic_write_json(target, {"ok": True})
        assert target.exists()

    def test_overwrites_existing(self, tmp_path):
        target = tmp_path / "x.json"
        atomic_write_json(target, {"v": 1})
        atomic_write_json(target, {"v": 2})
        assert json.loads(target.read_text(encoding="utf-8")) == {"v": 2}

    def test_no_temp_file_left_behind(self, tmp_path):
        target = tmp_path / "x.json"
        atomic_write_json(target, {"v": 1})
        assert [p.name for p in tmp_path.iterdir()] == ["x.json"]

    def test_chinese_not_escaped(self, tmp_path):
        target = tmp_path / "x.json"
        atomic_write_json(target, {"name": "慕"})
        raw = target.read_text(encoding="utf-8")
        assert "慕" in raw
        assert "\\u" not in raw

    def test_custom_indent(self, tmp_path):
        target = tmp_path / "x.json"
        atomic_write_json(target, {"a": 1}, indent=4)
        assert target.read_text(encoding="utf-8") == '{\n    "a": 1\n}'

    def test_accepts_str_path(self, tmp_path):
        target = tmp_path / "x.json"
        atomic_write_json(str(target), {"v": 1})
        assert target.exists()

    def test_serialization_error_does_not_leave_temp(self, tmp_path):
        target = tmp_path / "x.json"
        with pytest.raises(TypeError):
            atomic_write_json(target, {"bad": object()})
        assert list(tmp_path.iterdir()) == []


class TestReadJson:
    def test_reads_existing(self, tmp_path):
        target = tmp_path / "x.json"
        target.write_text('{"a": 1}', encoding="utf-8")
        assert read_json(target) == {"a": 1}

    def test_missing_returns_default(self, tmp_path):
        assert read_json(tmp_path / "nope.json") is None
        assert read_json(tmp_path / "nope.json", default={}) == {}

    def test_broken_returns_default(self, tmp_path):
        target = tmp_path / "x.json"
        target.write_text("{oops", encoding="utf-8")
        assert read_json(target, default=[]) == []

    def test_non_utf8_returns_default(self, tmp_path):
        target = tmp_path / "x.json"
        target.write_bytes(b"\xff\xfe\x00")
        assert read_json(target, default="fallback") == "fallback"

    def test_roundtrip_with_atomic_write(self, tmp_path):
        target = tmp_path / "x.json"
        payload = {"persona": "慕", "tags": ["真诚", "自然"]}
        atomic_write_json(target, payload)
        assert read_json(target) == payload


class TestSanitizeSettings:
    def test_api_key_redacted(self):
        assert sanitize_settings({"api_key": "sk-abcdef123456"}) == {"api_key": "[已配置]"}

    def test_empty_secret_stays_empty(self):
        assert sanitize_settings({"api_key": ""}) == {"api_key": ""}

    def test_api_key_ref_not_redacted(self):
        # *_ref 是引用名，不是密钥本身，必须原样保留
        data = {"api_key_ref": "model/deepseek"}
        assert sanitize_settings(data) == {"api_key_ref": "model/deepseek"}

    @pytest.mark.parametrize(
        "key",
        ["password", "secret", "token", "credential", "authorization", "API_KEY"],
    )
    def test_sensitive_key_parts(self, key):
        assert sanitize_settings({key: "value"}) == {key: "[已配置]"}

    def test_nested_dict(self):
        data = {"models": {"deepseek": {"api_key": "sk-real", "model_name": "deepseek-chat"}}}
        result = sanitize_settings(data)
        assert result["models"]["deepseek"]["api_key"] == "[已配置]"
        assert result["models"]["deepseek"]["model_name"] == "deepseek-chat"

    def test_list_of_dicts(self):
        data = {"providers": [{"api_key": "sk-1", "name": "a"}, {"api_key": "sk-2", "name": "b"}]}
        result = sanitize_settings(data)
        assert [p["api_key"] for p in result["providers"]] == ["[已配置]", "[已配置]"]
        assert [p["name"] for p in result["providers"]] == ["a", "b"]

    def test_plain_value_passthrough(self):
        assert sanitize_settings("hello") == "hello"
        assert sanitize_settings(42) == 42
        assert sanitize_settings(None) is None
        assert sanitize_settings(True) is True

    def test_does_not_mutate_input(self):
        data = {"models": {"x": {"api_key": "sk-real"}}}
        sanitize_settings(data)
        assert data["models"]["x"]["api_key"] == "sk-real"
