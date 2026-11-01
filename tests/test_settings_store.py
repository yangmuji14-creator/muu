"""settings_store：settings.json 读写与 schema 值往返。

注意 patch 的是实现模块 `settings_store` 的路径常量，不是 common 门面
（HANDOFF「不要改回去」第 36 条）。
"""

from __future__ import annotations

import json

import pytest

from webui.routes import settings_store as ss


@pytest.fixture()
def settings_path(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(ss, "SETTINGS_PATH", path)
    return path


class TestLoadSave:
    def test_missing_returns_empty(self, settings_path) -> None:
        assert ss._load_settings() == {}

    def test_broken_json_returns_empty(self, settings_path) -> None:
        settings_path.write_text("{oops", encoding="utf-8")
        assert ss._load_settings() == {}

    def test_roundtrip(self, settings_path) -> None:
        ss._save_settings({"models": {"deepseek": {"temperature": 0.9}}})
        loaded = ss._load_settings()
        assert loaded["models"]["deepseek"]["temperature"] == 0.9

    def test_save_creates_parent_dir(self, tmp_path, monkeypatch) -> None:
        nested = tmp_path / "a" / "b" / "settings.json"
        monkeypatch.setattr(ss, "SETTINGS_PATH", nested)
        ss._save_settings({})
        assert nested.exists()

    def test_bom_tolerated(self, settings_path) -> None:
        """旧文件可能带 BOM——读的时候 utf-8-sig 兼容。"""
        settings_path.write_text(
            json.dumps({"ok": 1}), encoding="utf-8-sig",
        )
        assert ss._load_settings() == {"ok": 1}


class TestInstallationId:
    def test_idempotent(self, tmp_path, monkeypatch) -> None:
        from core.config import DATA_DIR
        monkeypatch.setattr(ss, "DATA_DIR", tmp_path)
        first = ss._installation_id()
        second = ss._installation_id()
        assert first and first == second

    def test_invalid_dir_returns_empty(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(ss, "DATA_DIR", tmp_path / "not" / "a" / "file")
        # 目标路径的父级存在但本身是文件时写入失败 → 返回空串不抛
        (tmp_path / "not").write_text("x", encoding="utf-8")
        monkeypatch.setattr(ss, "DATA_DIR", tmp_path / "not" / "id")
        assert ss._installation_id() == ""


class TestValuesRoundtrip:
    def test_persist_then_read(self, settings_path) -> None:
        """schema 值写进 advanced/models 的正确位置再读回。"""
        values = {f["key"]: f["default"] for f in ss.SETTINGS_SCHEMA
                  if f.get("target") in ("advanced", "model")}
        ss._persist_values(values)
        read_back = ss._current_values()
        for key, value in values.items():
            assert read_back[key] == value, key
