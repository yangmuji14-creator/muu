"""wechat_accounts：多账号校验、凭证路径、配置读写与自动启动降级。

patch 的 settings 路径在 `settings_store`（实现模块），不是 common 门面
（HANDOFF「不要改回去」第 36 条）。
"""

from __future__ import annotations

import json
import sys

import pytest

from webui.routes import settings_store as ss
from webui.routes import wechat_accounts as wa


@pytest.fixture()
def settings_path(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(ss, "SETTINGS_PATH", path)
    return path


class TestValidateAccountId:
    @pytest.mark.parametrize("account_id", ["default", "abc", "main-1", "a" * 32])
    def test_valid(self, account_id) -> None:
        assert wa._validate_wechat_account_id(account_id) is True

    @pytest.mark.parametrize("account_id", ["", "ab", "a" * 33, "含中文", "bad id"])
    def test_invalid(self, account_id) -> None:
        assert wa._validate_wechat_account_id(account_id) is False


class TestCredentialsPath:
    def test_default_is_wechat_json(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(wa, "WECHAT_CREDS_DIR", tmp_path)
        assert wa._wechat_credentials_path("default") == tmp_path / "wechat.json"

    def test_named_account_gets_own_file(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(wa, "WECHAT_CREDS_DIR", tmp_path)
        assert wa._wechat_credentials_path("main") == tmp_path / "wechat_main.json"


class TestAccountsConfig:
    def test_missing_settings_returns_empty(self, settings_path) -> None:
        assert wa._get_wechat_accounts_config() == []

    def test_new_array_format(self, settings_path) -> None:
        settings_path.write_text(json.dumps({
            "advanced": {"adapters": {"wechat": {"accounts": [
                {"id": "default", "persona_id": "girlfriend_001", "enabled": True},
            ]}}}
        }, ensure_ascii=False), encoding="utf-8")
        accounts = wa._get_wechat_accounts_config()
        assert len(accounts) == 1
        assert accounts[0]["persona_id"] == "girlfriend_001"

    def test_save_preserves_other_keys(self, settings_path) -> None:
        settings_path.write_text(json.dumps({
            "default_model": "deepseek",
            "models": {"deepseek": {}},
        }, ensure_ascii=False), encoding="utf-8")
        wa._save_wechat_accounts_config(
            [{"id": "default", "persona_id": "girlfriend_001"}],
        )
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        assert data["default_model"] == "deepseek"  # 其他键没被冲掉
        assert data["advanced"]["adapters"]["wechat"]["accounts"][0][
            "persona_id"
        ] == "girlfriend_001"


class TestRuntimeSync:
    def test_runtime_config_updated_from_webui(self) -> None:
        advanced: dict = {}
        wa._set_runtime_wechat_accounts(
            type("C", (), {"advanced_config": advanced})(),
            [{"id": "default"}],
        )
        assert advanced["adapters"]["wechat"]["accounts"] == [{"id": "default"}]

    def test_runtime_update_skips_non_dict(self) -> None:
        wa._set_runtime_wechat_accounts(
            type("C", (), {"advanced_config": None})(), [{}],
        )


class TestSessionCallback:
    def test_callback_is_callable_and_silent(self) -> None:
        cb = wa._make_session_expired_callback("default")
        cb("default")  # 不抛出即通过


class TestAutostartDegradation:
    async def test_no_adapter_manager_returns(self) -> None:
        await wa._autostart_wechat_adapters(type("C", (), {})())

    async def test_sdk_missing_skips_all(self, monkeypatch) -> None:
        """SDK 未安装时整体跳过，不留 registered-but-not-running 占位。"""
        monkeypatch.setitem(sys.modules, "weixin_ilink", None)  # import 即 ImportError
        registered: list = []

        class Manager:
            def get(self, *a, **k):
                return None

            def register(self, *a, **k):
                registered.append(a)  # pragma: no cover - 不应被调用

        components = type("C", (), {"adapter_manager": Manager(), "registry": None})()
        await wa._autostart_wechat_adapters(components)
        assert registered == []
