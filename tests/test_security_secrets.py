"""`core/security/secrets.py` 的测试

覆盖：三个平台后端（DPAPI 真跑、Keychain / Secret Service 用假 subprocess）、
`SecretManager` 的失败吞掉约定、后端选择、以及密钥解析/保护的优先级契约。

⚠️ 这里最重要的契约是 ``resolve_config_secret`` 的优先级：
**显式保存的密钥（api_key_ref → 后端，其次明文 api_key）必须压过环境变量**。
env 无条件优先是老 bug —— `.env` 里的占位符 `sk-xxx` 会让设置页保存的真 key
全链路 401。
"""

from __future__ import annotations

import json
import subprocess
import sys
import types

import pytest

from core.security import secrets as sec


class FakeBackend:
    """可注入失败的后端替身。"""

    name = "fake"
    available = True

    def __init__(self, store=None, fail=()):
        self.store = dict(store or {})
        self.fail = set(fail)
        self.calls: list[tuple[str, str]] = []

    def get(self, reference: str) -> str:
        self.calls.append(("get", reference))
        if "get" in self.fail:
            raise RuntimeError("get boom")
        return self.store.get(reference, "")

    def set(self, reference: str, value: str) -> None:
        self.calls.append(("set", reference))
        if "set" in self.fail:
            raise RuntimeError("set boom")
        self.store[reference] = value

    def delete(self, reference: str) -> None:
        self.calls.append(("delete", reference))
        if "delete" in self.fail:
            raise RuntimeError("delete boom")
        self.store.pop(reference, None)


class SilentBackend(FakeBackend):
    """set 不报错但也不真写 —— 用来演练「写成功但读不回」的校验分支。"""

    def set(self, reference: str, value: str) -> None:
        self.calls.append(("set", reference))


@pytest.fixture(autouse=True)
def _isolate_manager_cache():
    """`_managers` 是模块级缓存，别让测试互相污染。"""
    snapshot = dict(sec._managers)
    yield
    sec._managers.clear()
    sec._managers.update(snapshot)


@pytest.fixture()
def manager():
    backend = FakeBackend()
    return sec.SecretManager(backend)


# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #


class TestConstants:
    def test_service_name(self) -> None:
        assert sec.SERVICE_NAME == "MuCompanion"

    def test_legacy_service_name(self) -> None:
        """旧名必须保留：更名前写进 Keychain 的条目还要能读到。"""
        assert sec.LEGACY_SERVICE_NAME == "CyberCompanion"

    def test_dpapi_entropy_frozen(self) -> None:
        """熵值改动会让用户已保存的密钥全部解不开，改它必须是有意为之。"""
        assert sec._DPAPI_ENTROPY == "CyberCompanion"


# --------------------------------------------------------------------------- #
# UnavailableBackend
# --------------------------------------------------------------------------- #


class TestUnavailableBackend:
    def test_not_available(self) -> None:
        assert sec.UnavailableBackend.available is False

    def test_get_returns_empty(self) -> None:
        assert sec.UnavailableBackend().get("model/x") == ""

    def test_set_raises(self) -> None:
        with pytest.raises(RuntimeError):
            sec.UnavailableBackend().set("model/x", "v")

    def test_delete_is_noop(self) -> None:
        assert sec.UnavailableBackend().delete("model/x") is None


# --------------------------------------------------------------------------- #
# Windows DPAPI（真跑，不 mock）
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(sys.platform != "win32", reason="只在 Windows 上有 DPAPI")
class TestWindowsDpapi:
    def test_roundtrip_encrypt_decrypt(self) -> None:
        payload = b'{"model/deepseek": "sk-test"}'
        encrypted = sec._windows_dpapi(payload, decrypt=False)
        assert encrypted != payload
        assert sec._windows_dpapi(encrypted, decrypt=True) == payload

    def test_decrypt_garbage_raises(self) -> None:
        with pytest.raises(OSError):
            sec._windows_dpapi(b"not-encrypted", decrypt=True)


@pytest.mark.skipif(sys.platform != "win32", reason="只在 Windows 上有 DPAPI")
class TestWindowsDpapiBackend:
    def test_missing_file_reads_empty(self, tmp_path) -> None:
        backend = sec.WindowsDpapiBackend(tmp_path)
        assert backend.get("model/x") == ""

    def test_set_get_delete(self, tmp_path) -> None:
        backend = sec.WindowsDpapiBackend(tmp_path)
        backend.set("model/x", "sk-abc")
        assert backend.get("model/x") == "sk-abc"
        assert (tmp_path / "secrets.dpapi").exists()
        backend.delete("model/x")
        assert backend.get("model/x") == ""

    def test_delete_missing_is_noop(self, tmp_path) -> None:
        backend = sec.WindowsDpapiBackend(tmp_path)
        backend.set("model/x", "sk-abc")
        backend.delete("model/nope")
        assert backend.get("model/x") == "sk-abc"

    def test_file_is_encrypted_not_plaintext(self, tmp_path) -> None:
        backend = sec.WindowsDpapiBackend(tmp_path)
        backend.set("model/x", "sk-secret-value")
        raw = (tmp_path / "secrets.dpapi").read_bytes()
        assert b"sk-secret-value" not in raw

    def test_non_dict_payload_reads_empty(self, tmp_path) -> None:
        payload = json.dumps(["a", "b"]).encode("utf-8")
        (tmp_path / "secrets.dpapi").write_bytes(
            __import__("base64").b64encode(sec._windows_dpapi(payload, decrypt=False))
        )
        backend = sec.WindowsDpapiBackend(tmp_path)
        assert backend.get("model/x") == ""

    def test_available_on_windows(self) -> None:
        assert sec.WindowsDpapiBackend.available is True


# --------------------------------------------------------------------------- #
# macOS Keychain（假 subprocess）
# --------------------------------------------------------------------------- #


def _completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


class TestMacOSKeychain:
    def test_get_from_current_service(self, monkeypatch) -> None:
        monkeypatch.setattr(sec.subprocess, "run", lambda *a, **k: _completed("sk-abc\n"))
        assert sec.MacOSKeychainBackend().get("model/x") == "sk-abc"

    def test_get_falls_back_to_legacy_service(self, monkeypatch) -> None:
        seen: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            seen.append(cmd)
            if sec.LEGACY_SERVICE_NAME in cmd:
                return _completed("sk-legacy\n")
            return _completed("", returncode=1)

        monkeypatch.setattr(sec.subprocess, "run", fake_run)
        assert sec.MacOSKeychainBackend().get("model/x") == "sk-legacy"
        assert any(sec.LEGACY_SERVICE_NAME in c for c in seen)

    def test_get_returns_empty_when_both_miss(self, monkeypatch) -> None:
        monkeypatch.setattr(sec.subprocess, "run", lambda *a, **k: _completed("", returncode=1))
        assert sec.MacOSKeychainBackend().get("model/x") == ""

    def test_set_success(self, monkeypatch) -> None:
        seen: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            seen.append(cmd)
            return _completed()

        monkeypatch.setattr(sec.subprocess, "run", fake_run)
        sec.MacOSKeychainBackend().set("model/x", "sk-abc")
        assert any("add-generic-password" in c for c in seen)

    def test_set_failure_raises_with_stderr(self, monkeypatch) -> None:
        monkeypatch.setattr(sec.subprocess, "run",
                            lambda *a, **k: _completed("", returncode=1, stderr="denied"))
        with pytest.raises(RuntimeError, match="denied"):
            sec.MacOSKeychainBackend().set("model/x", "sk-abc")

    def test_set_failure_without_stderr_uses_default(self, monkeypatch) -> None:
        monkeypatch.setattr(sec.subprocess, "run", lambda *a, **k: _completed("", returncode=1))
        with pytest.raises(RuntimeError, match="Keychain write failed"):
            sec.MacOSKeychainBackend().set("model/x", "sk-abc")

    def test_delete(self, monkeypatch) -> None:
        seen: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            seen.append(cmd)
            return _completed()

        monkeypatch.setattr(sec.subprocess, "run", fake_run)
        sec.MacOSKeychainBackend().delete("model/x")
        assert any("delete-generic-password" in c for c in seen)


# --------------------------------------------------------------------------- #
# Linux Secret Service（假 subprocess）
# --------------------------------------------------------------------------- #


class TestLinuxSecretService:
    def test_get_from_current_service(self, monkeypatch) -> None:
        monkeypatch.setattr(sec.subprocess, "run", lambda *a, **k: _completed("sk-abc\n"))
        assert sec.LinuxSecretServiceBackend().get("model/x") == "sk-abc"

    def test_get_falls_back_to_legacy_service(self, monkeypatch) -> None:
        def fake_run(cmd, **kwargs):
            if sec.LEGACY_SERVICE_NAME in cmd:
                return _completed("sk-legacy\n")
            return _completed("", returncode=1)

        monkeypatch.setattr(sec.subprocess, "run", fake_run)
        assert sec.LinuxSecretServiceBackend().get("model/x") == "sk-legacy"

    def test_empty_stdout_treated_as_miss(self, monkeypatch) -> None:
        monkeypatch.setattr(sec.subprocess, "run", lambda *a, **k: _completed("  \n"))
        assert sec.LinuxSecretServiceBackend().get("model/x") == ""

    def test_set_pipes_value_on_stdin(self, monkeypatch) -> None:
        captured: dict[str, str | None] = {}

        def fake_run(cmd, **kwargs):
            captured["input"] = kwargs.get("input")
            return _completed()

        monkeypatch.setattr(sec.subprocess, "run", fake_run)
        sec.LinuxSecretServiceBackend().set("model/x", "sk-abc")
        assert captured["input"] == "sk-abc"

    def test_set_failure_raises(self, monkeypatch) -> None:
        monkeypatch.setattr(sec.subprocess, "run",
                            lambda *a, **k: _completed("", returncode=1, stderr="nope"))
        with pytest.raises(RuntimeError, match="nope"):
            sec.LinuxSecretServiceBackend().set("model/x", "sk-abc")

    def test_set_failure_default_message(self, monkeypatch) -> None:
        monkeypatch.setattr(sec.subprocess, "run", lambda *a, **k: _completed("", returncode=1))
        with pytest.raises(RuntimeError, match="Secret Service write failed"):
            sec.LinuxSecretServiceBackend().set("model/x", "sk-abc")

    def test_delete(self, monkeypatch) -> None:
        seen: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            seen.append(cmd)
            return _completed()

        monkeypatch.setattr(sec.subprocess, "run", fake_run)
        sec.LinuxSecretServiceBackend().delete("model/x")
        assert seen and "clear" in seen[0]


# --------------------------------------------------------------------------- #
# SecretManager 门面
# --------------------------------------------------------------------------- #


class TestSecretManager:
    def test_status(self) -> None:
        status = sec.SecretManager(FakeBackend()).status
        assert status.backend == "fake"
        assert status.available is True

    def test_get(self, manager) -> None:
        manager.set("model/x", "sk-abc")
        assert manager.get("model/x") == "sk-abc"

    def test_get_tolerates_backend_error(self) -> None:
        manager = sec.SecretManager(FakeBackend(fail=["get"]))
        assert manager.get("model/x") == ""

    def test_get_empty_reference_short_circuits(self, manager) -> None:
        assert manager.get("") == ""
        assert manager.backend.calls == []

    def test_get_unavailable_backend(self) -> None:
        backend = FakeBackend()
        backend.available = False
        manager = sec.SecretManager(backend)
        assert manager.get("model/x") == ""
        assert backend.calls == []

    def test_set(self, manager) -> None:
        assert manager.set("model/x", "sk-abc") is True
        assert manager.backend.store["model/x"] == "sk-abc"

    def test_set_verifies_readback(self) -> None:
        """写进去读不回来就当失败 —— 别让用户以为存住了。"""
        assert sec.SecretManager(SilentBackend()).set("model/x", "sk-abc") is False

    def test_set_empty_value_returns_false(self, manager) -> None:
        assert manager.set("model/x", "") is False
        assert manager.set("", "sk-abc") is False

    def test_set_tolerates_backend_error(self) -> None:
        assert sec.SecretManager(FakeBackend(fail=["set"])).set("model/x", "sk-abc") is False

    def test_set_unavailable_backend(self) -> None:
        backend = FakeBackend()
        backend.available = False
        assert sec.SecretManager(backend).set("model/x", "sk-abc") is False

    def test_delete(self, manager) -> None:
        manager.set("model/x", "sk-abc")
        assert manager.delete("model/x") is True
        assert manager.get("model/x") == ""

    def test_delete_empty_reference(self, manager) -> None:
        assert manager.delete("") is False

    def test_delete_tolerates_backend_error(self) -> None:
        assert sec.SecretManager(FakeBackend(fail=["delete"])).delete("model/x") is False

    def test_delete_unavailable_backend(self) -> None:
        backend = FakeBackend()
        backend.available = False
        assert sec.SecretManager(backend).delete("model/x") is False


# --------------------------------------------------------------------------- #
# 后端选择
# --------------------------------------------------------------------------- #


class TestSelectBackend:
    def test_windows_uses_dpapi(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(sec.sys, "platform", "win32")
        assert isinstance(sec._select_backend(tmp_path), sec.WindowsDpapiBackend)

    def test_darwin_with_security_binary(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(sec.sys, "platform", "darwin")
        monkeypatch.setattr(sec.MacOSKeychainBackend, "available", True)
        assert isinstance(sec._select_backend(tmp_path), sec.MacOSKeychainBackend)

    def test_darwin_without_security_binary(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(sec.sys, "platform", "darwin")
        monkeypatch.setattr(sec.MacOSKeychainBackend, "available", False)
        monkeypatch.setattr(sec.LinuxSecretServiceBackend, "available", False)
        assert isinstance(sec._select_backend(tmp_path), sec.UnavailableBackend)

    def test_linux_with_secret_tool(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(sec.sys, "platform", "linux")
        monkeypatch.setattr(sec.LinuxSecretServiceBackend, "available", True)
        backend = sec._select_backend(tmp_path)
        assert isinstance(backend, sec.LinuxSecretServiceBackend)

    def test_linux_without_secret_tool(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(sec.sys, "platform", "linux")
        monkeypatch.setattr(sec.LinuxSecretServiceBackend, "available", False)
        assert isinstance(sec._select_backend(tmp_path), sec.UnavailableBackend)


class TestGetSecretManager:
    def test_caches_per_directory(self, tmp_path) -> None:
        first = sec.get_secret_manager(tmp_path)
        second = sec.get_secret_manager(tmp_path)
        assert first is second

    def test_distinct_directories_distinct_managers(self, tmp_path) -> None:
        a = sec.get_secret_manager(tmp_path / "a")
        b = sec.get_secret_manager(tmp_path / "b")
        assert a is not b

    def test_accepts_string_path(self, tmp_path) -> None:
        manager = sec.get_secret_manager(str(tmp_path))
        assert sec.get_secret_manager(tmp_path) is manager

    def test_defaults_to_runtime_config_dir(self, tmp_path, monkeypatch) -> None:
        fake_paths = types.SimpleNamespace(config_dir=tmp_path)
        monkeypatch.setattr(sec, "resolve_runtime_paths", lambda: fake_paths)
        manager = sec.get_secret_manager()
        assert manager is sec.get_secret_manager(tmp_path)


# --------------------------------------------------------------------------- #
# 引用命名
# --------------------------------------------------------------------------- #


class TestSecretRefs:
    def test_model_secret_ref(self) -> None:
        assert sec.model_secret_ref("deepseek") == "model/deepseek"

    def test_model_secret_ref_strips(self) -> None:
        assert sec.model_secret_ref("  mimo  ") == "model/mimo"

    def test_vision_secret_ref(self) -> None:
        assert sec.vision_secret_ref() == "vision/default"


# --------------------------------------------------------------------------- #
# resolve_config_secret —— 优先级契约
# --------------------------------------------------------------------------- #


class TestResolveConfigSecret:
    def test_backend_wins_over_plaintext_and_env(self, manager) -> None:
        manager.set("model/x", "sk-backend")
        got = sec.resolve_config_secret(
            {"api_key_ref": "model/x", "api_key": "sk-plaintext"},
            env_value="sk-env",
            manager=manager,
        )
        assert got == "sk-backend"

    def test_plaintext_wins_over_env(self) -> None:
        got = sec.resolve_config_secret(
            {"api_key": "sk-plaintext"}, env_value="sk-env", manager=sec.SecretManager(FakeBackend())
        )
        assert got == "sk-plaintext"

    def test_env_used_only_when_nothing_saved(self) -> None:
        got = sec.resolve_config_secret({}, env_value="sk-env",
                                        manager=sec.SecretManager(FakeBackend()))
        assert got == "sk-env"

    def test_missing_reference_falls_through(self) -> None:
        got = sec.resolve_config_secret(
            {"api_key_ref": "model/missing"}, env_value="sk-env",
            manager=sec.SecretManager(FakeBackend()),
        )
        assert got == "sk-env"

    def test_empty_config_returns_empty(self) -> None:
        assert sec.resolve_config_secret(None, manager=sec.SecretManager(FakeBackend())) == ""

    def test_non_dict_config_ignored(self) -> None:
        assert sec.resolve_config_secret(["nope"], env_value="sk-env",
                                         manager=sec.SecretManager(FakeBackend())) == "sk-env"

    def test_none_values_become_empty(self) -> None:
        got = sec.resolve_config_secret(
            {"api_key_ref": None, "api_key": None},
            env_value="", manager=sec.SecretManager(FakeBackend()),
        )
        assert got == ""


# --------------------------------------------------------------------------- #
# protect_config_secret
# --------------------------------------------------------------------------- #


class TestProtectConfigSecret:
    def test_moves_plaintext_to_backend(self, manager) -> None:
        result, secure = sec.protect_config_secret(
            {"api_key": "sk-abc"}, "model/x", manager=manager
        )
        assert secure is True
        assert result["api_key"] == ""
        assert result["api_key_ref"] == "model/x"
        assert manager.get("model/x") == "sk-abc"

    def test_explicit_value_wins_over_config(self, manager) -> None:
        result, secure = sec.protect_config_secret(
            {"api_key": "sk-old"}, "model/x", value="sk-new", manager=manager
        )
        assert secure is True
        assert manager.get("model/x") == "sk-new"

    def test_falls_back_to_plaintext_when_backend_fails(self) -> None:
        """后端写不进去时绝不能把能用的密钥丢掉。"""
        result, secure = sec.protect_config_secret(
            {"api_key": "sk-abc"}, "model/x",
            manager=sec.SecretManager(FakeBackend(fail=["set"])),
        )
        assert secure is False
        assert result["api_key"] == "sk-abc"
        assert "api_key_ref" not in result

    def test_does_not_mutate_input(self, manager) -> None:
        config = {"api_key": "sk-abc"}
        sec.protect_config_secret(config, "model/x", manager=manager)
        assert config == {"api_key": "sk-abc"}

    def test_empty_candidate_with_live_ref_clears_plaintext(self, manager) -> None:
        manager.set("model/x", "sk-abc")
        result, secure = sec.protect_config_secret(
            {"api_key_ref": "model/x", "api_key": "sk-stale"}, "model/x",
            manager=manager,
        )
        assert secure is True
        assert result["api_key"] == ""

    def test_no_candidate_reports_secure_when_ref_alive(self, manager) -> None:
        """候选密钥为空但 ref 仍活着：只需把残留明文清掉，算成功。"""
        manager.set("model/x", "sk-abc")
        result, secure = sec.protect_config_secret(
            {"api_key_ref": "model/x", "api_key": ""}, "model/x", manager=manager
        )
        assert secure is True
        assert result["api_key"] == ""
        assert result["api_key_ref"] == "model/x"

    def test_empty_candidate_with_dead_ref(self) -> None:
        result, secure = sec.protect_config_secret(
            {"api_key_ref": "model/x"}, "model/x",
            manager=sec.SecretManager(FakeBackend()),
        )
        assert secure is False
        assert result["api_key_ref"] == "model/x"

    def test_empty_everything(self) -> None:
        result, secure = sec.protect_config_secret(
            {}, "model/x", manager=sec.SecretManager(FakeBackend())
        )
        assert secure is False
        assert result == {}

    def test_readback_mismatch_keeps_plaintext(self) -> None:
        result, secure = sec.protect_config_secret(
            {"api_key": "sk-abc"}, "model/x", manager=sec.SecretManager(SilentBackend())
        )
        assert secure is False
        assert result["api_key"] == "sk-abc"


# --------------------------------------------------------------------------- #
# migrate_settings_secrets
# --------------------------------------------------------------------------- #


class TestMigrateSettingsSecrets:
    def test_migrates_model_plaintext(self, manager) -> None:
        settings = {"models": {"deepseek": {"api_key": "sk-abc"}}}
        result, stats = sec.migrate_settings_secrets(settings, manager=manager)
        assert stats["changed"] is True
        assert stats["protected"] == 1
        assert stats["plaintext"] == 0
        assert result["models"]["deepseek"]["api_key"] == ""
        assert manager.get("model/deepseek") == "sk-abc"

    def test_reports_plaintext_when_backend_fails(self) -> None:
        settings = {"models": {"deepseek": {"api_key": "sk-abc"}}}
        result, stats = sec.migrate_settings_secrets(
            settings, manager=sec.SecretManager(FakeBackend(fail=["set"]))
        )
        assert stats["changed"] is False
        assert stats["protected"] == 0
        assert stats["plaintext"] == 1
        assert result["models"]["deepseek"]["api_key"] == "sk-abc"

    def test_counts_existing_live_ref(self, manager) -> None:
        manager.set("model/deepseek", "sk-abc")
        settings = {"models": {"deepseek": {"api_key_ref": "model/deepseek"}}}
        _, stats = sec.migrate_settings_secrets(settings, manager=manager)
        assert stats["protected"] == 1
        assert stats["changed"] is False

    def test_dead_ref_not_counted(self) -> None:
        settings = {"models": {"deepseek": {"api_key_ref": "model/deepseek"}}}
        _, stats = sec.migrate_settings_secrets(
            settings, manager=sec.SecretManager(FakeBackend())
        )
        assert stats["protected"] == 0

    def test_skips_non_dict_model_config(self, manager) -> None:
        settings = {"models": {"broken": "not-a-dict", "ok": {"api_key": "sk-abc"}}}
        result, stats = sec.migrate_settings_secrets(settings, manager=manager)
        assert stats["protected"] == 1
        assert result["models"]["broken"] == "not-a-dict"

    def test_model_config_without_credentials(self, manager) -> None:
        """既没有明文也没有 ref 的模型条目（纯配置）不该被计数。"""
        settings = {"models": {"deepseek": {"model_name": "deepseek-chat"}}}
        _, stats = sec.migrate_settings_secrets(settings, manager=manager)
        assert stats["protected"] == 0
        assert stats["plaintext"] == 0
        assert stats["changed"] is False

    def test_vision_config_without_credentials(self, manager) -> None:
        settings = {"advanced": {"vision_model": {"provider": "deepseek"}}}
        _, stats = sec.migrate_settings_secrets(settings, manager=manager)
        assert stats["protected"] == 0
        assert stats["plaintext"] == 0

    def test_vision_not_a_dict(self, manager) -> None:
        settings = {"advanced": {"vision_model": "deepseek-flash"}}
        result, stats = sec.migrate_settings_secrets(settings, manager=manager)
        assert stats["protected"] == 0
        assert result["advanced"]["vision_model"] == "deepseek-flash"

    def test_missing_models_section(self, manager) -> None:
        result, stats = sec.migrate_settings_secrets({}, manager=manager)
        assert stats["protected"] == 0
        assert result == {}

    def test_models_not_dict(self, manager) -> None:
        _, stats = sec.migrate_settings_secrets({"models": []}, manager=manager)
        assert stats["protected"] == 0

    def test_migrates_vision_plaintext(self, manager) -> None:
        settings = {"advanced": {"vision_model": {"api_key": "sk-vision"}}}
        result, stats = sec.migrate_settings_secrets(settings, manager=manager)
        assert stats["protected"] == 1
        assert stats["changed"] is True
        assert result["advanced"]["vision_model"]["api_key"] == ""
        assert result["advanced"]["vision_model"]["api_key_ref"] == "vision/default"
        assert manager.get("vision/default") == "sk-vision"

    def test_vision_plaintext_when_backend_fails(self) -> None:
        settings = {"advanced": {"vision_model": {"api_key": "sk-vision"}}}
        result, stats = sec.migrate_settings_secrets(
            settings, manager=sec.SecretManager(FakeBackend(fail=["set"]))
        )
        assert stats["plaintext"] == 1
        assert result["advanced"]["vision_model"]["api_key"] == "sk-vision"

    def test_vision_existing_live_ref(self, manager) -> None:
        manager.set("vision/default", "sk-vision")
        settings = {"advanced": {"vision_model": {"api_key_ref": "vision/default"}}}
        _, stats = sec.migrate_settings_secrets(settings, manager=manager)
        assert stats["protected"] == 1
        assert stats["changed"] is False

    def test_vision_dead_ref(self) -> None:
        settings = {"advanced": {"vision_model": {"api_key_ref": "vision/default"}}}
        _, stats = sec.migrate_settings_secrets(
            settings, manager=sec.SecretManager(FakeBackend())
        )
        assert stats["protected"] == 0

    def test_history_untouched_on_copy(self, manager) -> None:
        """migrate 必须深拷贝：设置对象在别处还有引用，别被就地改掉。"""
        settings = {"models": {"deepseek": {"api_key": "sk-abc"}}}
        sec.migrate_settings_secrets(settings, manager=manager)
        assert settings["models"]["deepseek"]["api_key"] == "sk-abc"

    def test_stats_shape(self, manager) -> None:
        _, stats = sec.migrate_settings_secrets({}, manager=manager)
        assert set(stats) == {"changed", "backend", "available", "protected", "plaintext"}
        assert stats["backend"] == "fake"
        assert stats["available"] is True
