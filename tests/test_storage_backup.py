"""备份与恢复（core/storage/backup.py）。

这个模块是「用户数据唯一的逃生通道」，测试重点全在**失败时的行为**：

1. 备份要能用在跑的库 —— SQLite 走 `backup()` API 而不是 `copyfile`，
   否则 WAL 里最新那批写入会丢；
2. 归档必须先 `inspect_backup` 校验再动磁盘 —— 缺 manifest、格式版本不对、
   路径穿越（`../`、绝对路径）、data//config/ 之外的条目，全部拒；
3. 恢复前必须先造安全备份（`safety_backup` 字段），否则一次错恢复就永久丢档；
4. v1（只有 legacy 域库）与 v2（有 companion.db）两条路径对旧文件的处理相反：
   v1 要删掉 companion.db 让下次启动重新导入，v2 要删掉遗留 legacy 文件防止重复导入。

全部在 tmp_path 里跑，不碰真实 data/。
"""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from core.storage import backup as backup_mod
from core.storage.backup import (
    BACKUP_FORMAT_VERSION,
    MAX_BACKUPS,
    BackupValidationError,
    apply_pending_restore,
    create_backup,
    inspect_backup,
    pending_restore_status,
    restore_backup,
    schedule_restore,
)
from core.storage.constants import CONSOLIDATED_DB_NAME, LEGACY_DB_NAMES


@pytest.fixture()
def dirs(tmp_path):
    data = tmp_path / "data"
    config = tmp_path / "config"
    data.mkdir()
    config.mkdir()
    return data, config


def _make_db(path, table="t", value="x"):
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (v TEXT)")
    conn.execute(f"INSERT INTO {table} VALUES (?)", (value,))
    conn.commit()
    conn.close()
    return path


def _write_zip(path, entries: dict[str, str], manifest=None):
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
        if manifest is not None:
            archive.writestr(
                "manifest.json",
                manifest if isinstance(manifest, str) else json.dumps(manifest),
            )
    return path


class TestCreateBackup:
    def test_creates_zip_in_backups_dir(self, dirs):
        data, config = dirs
        path = create_backup(data, config)
        assert path.exists()
        assert path.parent == data / "backups"
        assert path.name.startswith("mu-")
        assert path.suffix == ".zip"

    def test_manifest_format_version(self, dirs):
        data, config = dirs
        manifest = inspect_backup(create_backup(data, config))
        assert manifest["format_version"] == BACKUP_FORMAT_VERSION

    def test_manifest_has_created_at(self, dirs):
        data, config = dirs
        manifest = inspect_backup(create_backup(data, config))
        assert manifest["created_at"]
        from datetime import datetime

        datetime.fromisoformat(manifest["created_at"])

    def test_manifest_lists_exclusions(self, dirs):
        data, config = dirs
        manifest = inspect_backup(create_backup(data, config))
        excluded = manifest["excluded"]
        assert "data/credentials" in excluded
        assert "data/logs" in excluded
        assert "*.db-wal" in excluded

    def test_empty_dirs_still_produce_valid_archive(self, dirs):
        data, config = dirs
        manifest = inspect_backup(create_backup(data, config))
        assert manifest["included"] == []

    def test_includes_database(self, dirs):
        data, config = dirs
        _make_db(data / "companion.db")
        manifest = inspect_backup(create_backup(data, config))
        assert "data/companion.db" in manifest["included"]

    def test_database_content_preserved(self, dirs, tmp_path):
        data, config = dirs
        _make_db(data / "companion.db", value="hello")
        path = create_backup(data, config)
        with zipfile.ZipFile(path) as archive:
            extracted = tmp_path / "extracted.db"
            extracted.write_bytes(archive.read("data/companion.db"))
        conn = sqlite3.connect(extracted)
        try:
            assert conn.execute("SELECT v FROM t").fetchone()[0] == "hello"
        finally:
            conn.close()

    def test_wal_data_included(self, dirs, tmp_path):
        """回归点：直接 copyfile 会漏掉还在 WAL 里、尚未 checkpoint 的写入。"""
        data, config = dirs
        db = data / "companion.db"
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE t (v TEXT)")
        conn.execute("INSERT INTO t VALUES ('wal-only')")
        conn.commit()
        try:
            path = create_backup(data, config)
            with zipfile.ZipFile(path) as archive:
                out = tmp_path / "out.db"
                out.write_bytes(archive.read("data/companion.db"))
            chk = sqlite3.connect(out)
            try:
                assert chk.execute("SELECT count(*) FROM t").fetchone()[0] == 1
            finally:
                chk.close()
        finally:
            conn.close()

    def test_wal_shm_not_archived(self, dirs):
        data, config = dirs
        _make_db(data / "companion.db")
        path = create_backup(data, config)
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
        assert not any(n.endswith("-wal") or n.endswith("-shm") for n in names)

    def test_snapshot_temp_file_cleaned(self, dirs):
        data, config = dirs
        _make_db(data / "companion.db")
        create_backup(data, config)
        assert list((data / "backups").glob(".*.snapshot")) == []

    def test_legacy_dbs_excluded_when_consolidated_present(self, dirs):
        data, config = dirs
        _make_db(data / "companion.db")
        _make_db(data / "memories.db")
        manifest = inspect_backup(create_backup(data, config))
        assert "data/memories.db" not in manifest["included"]
        assert "data/companion.db" in manifest["included"]

    def test_legacy_dbs_included_without_consolidated(self, dirs):
        data, config = dirs
        _make_db(data / "memories.db")
        manifest = inspect_backup(create_backup(data, config))
        assert "data/memories.db" in manifest["included"]

    def test_conversations_json_included(self, dirs):
        data, config = dirs
        (data / "conversations.json").write_text("{}", encoding="utf-8")
        manifest = inspect_backup(create_backup(data, config))
        assert "data/conversations.json" in manifest["included"]

    @pytest.mark.parametrize(
        "directory", ["chat_history", "identities", "life_summaries", "avatars"]
    )
    def test_user_content_directories_included(self, dirs, directory):
        data, config = dirs
        sub = data / directory / "nested"
        sub.mkdir(parents=True)
        (sub / "file.json").write_text("{}", encoding="utf-8")
        manifest = inspect_backup(create_backup(data, config))
        assert f"data/{directory}/nested/file.json" in manifest["included"]

    @pytest.mark.parametrize("name", ["personas.json", "settings.json", "mcp_servers.json"])
    def test_config_files_included(self, dirs, name):
        data, config = dirs
        (config / name).write_text("{}", encoding="utf-8")
        manifest = inspect_backup(create_backup(data, config))
        assert f"config/{name}" in manifest["included"]

    def test_unknown_config_files_excluded(self, dirs):
        data, config = dirs
        (config / "secrets.dpapi").write_bytes(b"secret")
        manifest = inspect_backup(create_backup(data, config))
        assert "config/secrets.dpapi" not in manifest["included"]

    def test_credentials_dir_excluded(self, dirs):
        data, config = dirs
        (data / "credentials").mkdir()
        (data / "credentials" / "wechat.json").write_text("{}", encoding="utf-8")
        manifest = inspect_backup(create_backup(data, config))
        assert not any("credentials" in item for item in manifest["included"])

    def test_creates_backup_dir_if_missing(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        config = tmp_path / "config"
        config.mkdir()
        assert create_backup(data, config).parent.is_dir()


class TestCorruptDatabase:
    """一个坏掉的 .db 不该让整次备份永远失败 —— 用户就再也导不出数据了。"""

    def test_bad_db_skipped_not_fatal(self, dirs):
        data, config = dirs
        (data / "junk.db").write_bytes(b"not a sqlite file")
        path = create_backup(data, config)
        assert path.exists()
        manifest = inspect_backup(path)
        assert "data/junk.db" in manifest["skipped"]
        assert "data/junk.db" not in manifest["included"]

    def test_good_db_still_included_alongside_bad(self, dirs):
        data, config = dirs
        _make_db(data / "companion.db", value="ok")
        (data / "junk.db").write_bytes(b"garbage")
        manifest = inspect_backup(create_backup(data, config))
        assert "data/companion.db" in manifest["included"]
        assert "data/junk.db" in manifest["skipped"]

    def test_skipped_key_always_present(self, dirs):
        """manifest 的字段形状要稳定，前端/脚本靠它判断。"""
        data, config = dirs
        assert inspect_backup(create_backup(data, config))["skipped"] == []

    def test_corrupt_db_does_not_block_safety_backup(self, dirs, tmp_path):
        """恢复前要造安全备份 —— 坏的 .db 不能连恢复都挡住。"""
        data, config = dirs
        (data / "junk.db").write_bytes(b"garbage")
        archive = _write_zip(
            tmp_path / "b.zip",
            {"config/settings.json": '{"new": true}'},
            {"format_version": 2},
        )
        result = restore_backup(archive, data, config)
        assert Path(result["safety_backup"]).exists()
        assert (config / "settings.json").exists()


class TestPruneOldBackups:
    def test_keeps_at_most_max_backups(self, dirs):
        data, config = dirs
        backup_dir = data / "backups"
        backup_dir.mkdir()
        import os
        import time

        for i in range(MAX_BACKUPS + 5):
            p = backup_dir / f"mu-old-{i}.zip"
            p.write_bytes(b"x")
            # 保证 mtime 严格递增，否则排序不稳
            os.utime(p, (1000 + i, 1000 + i))
        create_backup(data, config)
        assert len(list(backup_dir.glob("mu-*.zip"))) == MAX_BACKUPS

    def test_oldest_removed_first(self, dirs):
        data, config = dirs
        backup_dir = data / "backups"
        backup_dir.mkdir()
        import os

        oldest = backup_dir / "mu-oldest.zip"
        oldest.write_bytes(b"x")
        os.utime(oldest, (1, 1))
        for i in range(MAX_BACKUPS):
            p = backup_dir / f"mu-new-{i}.zip"
            p.write_bytes(b"x")
            os.utime(p, (2000 + i, 2000 + i))
        create_backup(data, config)
        assert not oldest.exists()

    def test_counts_legacy_cyber_companion_zips(self, dirs):
        """老命名 `cyber-companion-*.zip` 也占名额，不能无限堆积。"""
        data, config = dirs
        backup_dir = data / "backups"
        backup_dir.mkdir()
        import os

        for i in range(MAX_BACKUPS + 3):
            p = backup_dir / f"cyber-companion-{i}.zip"
            p.write_bytes(b"x")
            os.utime(p, (500 + i, 500 + i))
        create_backup(data, config)
        total = len(list(backup_dir.glob("mu-*.zip"))) + len(
            list(backup_dir.glob("cyber-companion-*.zip"))
        )
        assert total == MAX_BACKUPS


class TestInspectBackup:
    def test_valid_archive_returns_manifest(self, tmp_path):
        path = _write_zip(
            tmp_path / "b.zip",
            {"data/companion.db": "x"},
            {"format_version": 2, "included": [], "created_at": "2026-01-01"},
        )
        manifest = inspect_backup(path)
        assert manifest["format_version"] == 2

    def test_missing_manifest_rejected(self, tmp_path):
        path = _write_zip(tmp_path / "b.zip", {"data/companion.db": "x"})
        with pytest.raises(BackupValidationError, match="missing manifest"):
            inspect_backup(path)

    def test_v1_accepted(self, tmp_path):
        path = _write_zip(
            tmp_path / "b.zip", {"data/memories.db": "x"}, {"format_version": 1}
        )
        assert inspect_backup(path)["format_version"] == 1

    def test_unknown_format_version_rejected(self, tmp_path):
        path = _write_zip(tmp_path / "b.zip", {}, {"format_version": 99})
        with pytest.raises(BackupValidationError, match="unsupported backup format"):
            inspect_backup(path)

    def test_missing_format_version_rejected(self, tmp_path):
        path = _write_zip(tmp_path / "b.zip", {}, {"created_at": "x"})
        with pytest.raises(BackupValidationError):
            inspect_backup(path)

    def test_bad_zip_rejected(self, tmp_path):
        path = tmp_path / "b.zip"
        path.write_bytes(b"not a zip")
        with pytest.raises(BackupValidationError, match="invalid zip archive"):
            inspect_backup(path)

    def test_broken_manifest_json_rejected(self, tmp_path):
        path = _write_zip(tmp_path / "b.zip", {}, "{ not json")
        with pytest.raises(json.JSONDecodeError):
            inspect_backup(path)

    @pytest.mark.parametrize(
        "name",
        ["data/../../etc/passwd", "config/../../../evil", "../../outside"],
    )
    def test_path_traversal_rejected(self, tmp_path, name):
        path = _write_zip(
            tmp_path / "b.zip", {name: "x"}, {"format_version": 2}
        )
        with pytest.raises(BackupValidationError, match="unsafe archive path"):
            inspect_backup(path)

    def test_absolute_path_rejected(self, tmp_path):
        path = _write_zip(
            tmp_path / "b.zip",
            {"/etc/passwd": "x"},
            {"format_version": 2},
        )
        with pytest.raises(BackupValidationError):
            inspect_backup(path)

    @pytest.mark.parametrize("name", ["secrets.dpapi", "evil.sh", "datax/file"])
    def test_unexpected_prefix_rejected(self, tmp_path, name):
        path = _write_zip(tmp_path / "b.zip", {name: "x"}, {"format_version": 2})
        with pytest.raises(BackupValidationError, match="unexpected archive content"):
            inspect_backup(path)

    def test_empty_dir_entries_allowed(self, tmp_path):
        """zip 里带目录条目（末尾 `/`）是正常写法，不该被拒。"""
        path = tmp_path / "b.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("data/", "")
            archive.writestr("manifest.json", json.dumps({"format_version": 2}))
        assert inspect_backup(path)["format_version"] == 2


class TestPendingRestore:
    def _valid_archive(self, tmp_path):
        return _write_zip(
            tmp_path / "src.zip",
            {"data/companion.db": "x", "config/settings.json": "{}"},
            {"format_version": 2, "included": [], "created_at": "2026-01-01"},
        )

    def test_no_pending_returns_none(self, dirs):
        data, _ = dirs
        assert pending_restore_status(data) is None

    def test_schedule_creates_marker_and_archive(self, dirs, tmp_path):
        data, _ = dirs
        archive = self._valid_archive(tmp_path)
        result = schedule_restore(archive, data)
        pending = data / ".pending_restore"
        assert (pending / "request.json").exists()
        assert (pending / "backup.zip").exists()
        assert result["pending"] is True
        assert result["source_name"] == "src.zip"

    def test_schedule_does_not_leave_tmp_files(self, dirs, tmp_path):
        data, _ = dirs
        schedule_restore(self._valid_archive(tmp_path), data)
        leftover = [p.name for p in (data / ".pending_restore").iterdir() if p.name.startswith(".")]
        assert leftover == []

    def test_schedule_rejects_invalid_archive(self, dirs, tmp_path):
        data, _ = dirs
        bad = tmp_path / "bad.zip"
        bad.write_bytes(b"nope")
        with pytest.raises(BackupValidationError):
            schedule_restore(bad, data)
        assert not (data / ".pending_restore" / "backup.zip").exists()

    def test_status_returns_marker_and_manifest(self, dirs, tmp_path):
        data, _ = dirs
        schedule_restore(self._valid_archive(tmp_path), data)
        status = pending_restore_status(data)
        assert status["pending"] is True
        assert status["manifest"]["format_version"] == 2
        assert status["scheduled_at"]

    def test_status_missing_archive_returns_none(self, dirs, tmp_path):
        data, _ = dirs
        pending = data / ".pending_restore"
        pending.mkdir()
        (pending / "request.json").write_text("{}", encoding="utf-8")
        assert pending_restore_status(data) is None

    def test_status_missing_marker_returns_none(self, dirs, tmp_path):
        data, _ = dirs
        pending = data / ".pending_restore"
        pending.mkdir()
        (pending / "backup.zip").write_bytes(b"x")
        assert pending_restore_status(data) is None

    def test_status_broken_marker_returns_none(self, dirs, tmp_path):
        data, _ = dirs
        schedule_restore(self._valid_archive(tmp_path), data)
        (data / ".pending_restore" / "request.json").write_text("{ broken", encoding="utf-8")
        assert pending_restore_status(data) is None

    def test_status_corrupted_archive_returns_none(self, dirs, tmp_path):
        data, _ = dirs
        schedule_restore(self._valid_archive(tmp_path), data)
        (data / ".pending_restore" / "backup.zip").write_bytes(b"garbage")
        assert pending_restore_status(data) is None

    def test_apply_without_pending_returns_none(self, dirs):
        data, config = dirs
        assert apply_pending_restore(data, config) is None

    def test_apply_restores_and_cleans_up(self, dirs, tmp_path):
        data, config = dirs
        schedule_restore(self._valid_archive(tmp_path), data)
        result = apply_pending_restore(data, config)
        assert "data/companion.db" in result["restored"]
        assert not (data / ".pending_restore").exists()


class TestRestoreBackup:
    def test_restores_data_files(self, dirs, tmp_path):
        data, config = dirs
        (data / "chat_history").mkdir()
        archive = _write_zip(
            tmp_path / "b.zip",
            {"data/chat_history/x.json": '{"messages": []}'},
            {"format_version": 2},
        )
        restore_backup(archive, data, config)
        assert (data / "chat_history" / "x.json").read_text(encoding="utf-8")

    def test_restores_config_files(self, dirs, tmp_path):
        data, config = dirs
        archive = _write_zip(
            tmp_path / "b.zip",
            {"config/settings.json": '{"default_model": "deepseek"}'},
            {"format_version": 2},
        )
        restore_backup(archive, data, config)
        assert "deepseek" in (config / "settings.json").read_text(encoding="utf-8")

    def test_creates_safety_backup_first(self, dirs, tmp_path):
        data, config = dirs
        archive = _write_zip(tmp_path / "b.zip", {}, {"format_version": 2})
        result = restore_backup(archive, data, config)
        assert Path(result["safety_backup"]).exists()

    def test_safety_backup_before_overwrite(self, dirs, tmp_path):
        """安全备份必须含**被覆盖前**的内容。"""
        data, config = dirs
        (config / "settings.json").write_text('{"old": true}', encoding="utf-8")
        archive = _write_zip(
            tmp_path / "b.zip",
            {"config/settings.json": '{"new": true}'},
            {"format_version": 2},
        )
        result = restore_backup(archive, data, config)
        with zipfile.ZipFile(result["safety_backup"]) as zf:
            assert '"old"' in zf.read("config/settings.json").decode("utf-8")

    def test_restored_list_reports_prefixed_paths(self, dirs, tmp_path):
        data, config = dirs
        archive = _write_zip(
            tmp_path / "b.zip",
            {"data/conversations.json": "{}", "config/settings.json": "{}"},
            {"format_version": 2},
        )
        restored = restore_backup(archive, data, config)["restored"]
        assert "data/conversations.json" in restored
        assert "config/settings.json" in restored

    def test_manifest_returned(self, dirs, tmp_path):
        data, config = dirs
        archive = _write_zip(tmp_path / "b.zip", {}, {"format_version": 2, "note": "x"})
        assert restore_backup(archive, data, config)["manifest"]["note"] == "x"

    def test_directory_entries_skipped(self, dirs, tmp_path):
        data, config = dirs
        path = tmp_path / "b.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("data/", "")
            archive.writestr("manifest.json", json.dumps({"format_version": 2}))
        assert restore_backup(path, data, config)["restored"] == []

    def test_v1_removes_consolidated_db(self, dirs, tmp_path):
        """v1 只有 legacy 域库 → 删掉 companion.db 让下次启动重新导入。"""
        data, config = dirs
        _make_db(data / "companion.db")
        archive = _write_zip(
            tmp_path / "b.zip", {"data/memories.db": "x"}, {"format_version": 1}
        )
        restore_backup(archive, data, config)
        assert not (data / "companion.db").exists()

    def test_v1_removes_consolidated_wal_shm(self, dirs, tmp_path):
        data, config = dirs
        (data / f"{CONSOLIDATED_DB_NAME}-wal").write_bytes(b"x")
        (data / f"{CONSOLIDATED_DB_NAME}-shm").write_bytes(b"x")
        archive = _write_zip(
            tmp_path / "b.zip", {"data/memories.db": "x"}, {"format_version": 1}
        )
        restore_backup(archive, data, config)
        assert not (data / f"{CONSOLIDATED_DB_NAME}-wal").exists()
        assert not (data / f"{CONSOLIDATED_DB_NAME}-shm").exists()

    def test_v2_removes_legacy_dbs(self, dirs, tmp_path):
        """v2 是权威 → 删掉遗留 legacy 文件，防止下次启动重复导入盖掉它。"""
        data, config = dirs
        for name in LEGACY_DB_NAMES:
            (data / name).write_bytes(b"x")
        archive = _write_zip(
            tmp_path / "b.zip",
            {"data/companion.db": "x"},
            {"format_version": 2},
        )
        restore_backup(archive, data, config)
        for name in LEGACY_DB_NAMES:
            assert not (data / name).exists(), name

    def test_v2_removes_legacy_wal_shm(self, dirs, tmp_path):
        data, config = dirs
        legacy = LEGACY_DB_NAMES[0]
        (data / f"{legacy}-wal").write_bytes(b"x")
        archive = _write_zip(
            tmp_path / "b.zip", {"data/companion.db": "x"}, {"format_version": 2}
        )
        restore_backup(archive, data, config)
        assert not (data / f"{legacy}-wal").exists()

    def test_v2_without_legacy_files_ok(self, dirs, tmp_path):
        data, config = dirs
        archive = _write_zip(
            tmp_path / "b.zip", {"data/companion.db": "x"}, {"format_version": 2}
        )
        assert restore_backup(archive, data, config)["restored"]

    def test_invalid_archive_rejected_before_touching_disk(self, dirs, tmp_path):
        data, config = dirs
        (config / "settings.json").write_text('{"keep": true}', encoding="utf-8")
        bad = tmp_path / "bad.zip"
        bad.write_bytes(b"nope")
        with pytest.raises(BackupValidationError):
            restore_backup(bad, data, config)
        assert "keep" in (config / "settings.json").read_text(encoding="utf-8")

    def test_staging_dir_cleaned_up(self, dirs, tmp_path):
        data, config = dirs
        archive = _write_zip(tmp_path / "b.zip", {}, {"format_version": 2})
        restore_backup(archive, data, config)
        assert list(data.parent.glob("cc-restore-*")) == []

    def test_roundtrip(self, dirs, tmp_path):
        """建备份 → 改光数据 → 恢复 → 内容回来。"""
        data, config = dirs
        (config / "settings.json").write_text('{"v": 1}', encoding="utf-8")
        (data / "chat_history").mkdir()
        (data / "chat_history" / "a.json").write_text('{"m": 1}', encoding="utf-8")
        snapshot = create_backup(data, config)

        (config / "settings.json").write_text('{"v": 2}', encoding="utf-8")
        (data / "chat_history" / "a.json").unlink()

        restore_backup(snapshot, data, config)
        assert '"v": 1' in (config / "settings.json").read_text(encoding="utf-8")
        assert (data / "chat_history" / "a.json").exists()


class TestConstants:
    def test_max_backups_is_10(self):
        assert MAX_BACKUPS == 10

    def test_format_version_is_2(self):
        assert BACKUP_FORMAT_VERSION == 2
        assert backup_mod.SUPPORTED_BACKUP_FORMAT_VERSIONS == {1, 2}

    def test_restorable_prefixes(self):
        assert backup_mod._RESTORABLE_PREFIXES == ("data/", "config/")

    def test_pending_dir_names(self):
        assert backup_mod.PENDING_RESTORE_DIRNAME == ".pending_restore"
        assert backup_mod.PENDING_RESTORE_ARCHIVE == "backup.zip"
        assert backup_mod.PENDING_RESTORE_MARKER == "request.json"
