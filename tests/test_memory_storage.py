"""core/memory/storage.py 的单元测试

覆盖 SQLite 存储层：建表/补列/回填、JSON 迁移、CRUD、行转换兼容、
WAL 检点、连接生命周期。

全部 ``tmp_path`` 隔离。
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from core.memory.models import Memory
from core.memory.storage import MemoryStorage


def _mem(mem_id="m1", content="内容", level=3, **kwargs) -> Memory:
    return Memory(id=mem_id, content=content, level=level, **kwargs)


@pytest.fixture()
def store(tmp_path):
    return MemoryStorage(tmp_path)


# --------------------------------------------------------------------------- #
# 建表与补列
# --------------------------------------------------------------------------- #


class TestSchema:
    def test_creates_db_file(self, tmp_path) -> None:
        MemoryStorage(tmp_path)
        assert (tmp_path / "companion.db").exists()

    def test_creates_data_dir(self, tmp_path) -> None:
        MemoryStorage(tmp_path / "nested" / "deep")
        assert (tmp_path / "nested" / "deep").is_dir()

    def test_full_column_set(self, store) -> None:
        with sqlite3.connect(str(store._db_path)) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(memories)")]
        assert cols == [
            "user_id", "id", "content", "level", "category", "created_at",
            "last_accessed", "access_count", "tags", "source", "related_ids",
            "superseded_by", "confidence", "forget_score", "archived",
        ]

    def test_indexes_created(self, store) -> None:
        with sqlite3.connect(str(store._db_path)) as conn:
            # PRAGMA index_list 的行是 (seq, name, unique, origin, partial)
            names = {r[1] for r in conn.execute("PRAGMA index_list(memories)")}
        assert "idx_memories_user" in names
        assert "idx_memories_level" in names

    def test_idempotent_reopen(self, tmp_path) -> None:
        store = MemoryStorage(tmp_path)
        store.add("u", _mem())
        store.close()
        assert MemoryStorage(tmp_path).count("u") == 1


class TestEnsureColumns:
    def _legacy_db(self, tmp_path) -> None:
        """造一个只有 12 列的老库（v4 之前）。"""
        with sqlite3.connect(str(tmp_path / "companion.db")) as conn:
            conn.execute("""
                CREATE TABLE memories (
                    user_id TEXT NOT NULL, id TEXT NOT NULL, content TEXT NOT NULL,
                    level INTEGER NOT NULL DEFAULT 1,
                    category TEXT NOT NULL DEFAULT 'other',
                    created_at TEXT NOT NULL, last_accessed TEXT NOT NULL,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    tags TEXT NOT NULL DEFAULT '[]',
                    source TEXT NOT NULL DEFAULT 'auto',
                    related_ids TEXT NOT NULL DEFAULT '[]',
                    superseded_by TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (user_id, id)
                )
            """)

    def test_adds_three_columns(self, tmp_path) -> None:
        self._legacy_db(tmp_path)
        store = MemoryStorage(tmp_path)
        with sqlite3.connect(str(store._db_path)) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(memories)")}
        assert {"confidence", "forget_score", "archived"} <= cols

    def test_backfills_confidence(self, tmp_path) -> None:
        self._legacy_db(tmp_path)
        with sqlite3.connect(str(tmp_path / "companion.db")) as conn:
            conn.execute(
                "INSERT INTO memories (user_id, id, content, level, category,"
                " created_at, last_accessed) VALUES (?,?,?,?,?,?,?)",
                ("u", "old", "我的名字叫小林", 3, "personal", "2026-01-01", "2026-01-01"),
            )
        store = MemoryStorage(tmp_path)
        loaded = store.get("u", "old")
        assert loaded is not None
        assert loaded.confidence == 0.9  # 自称句式 → 高置信

    def test_backfill_skips_when_no_rows(self, tmp_path) -> None:
        self._legacy_db(tmp_path)
        MemoryStorage(tmp_path)  # 不该抛异常

    def test_already_present_column_untouched(self, tmp_path) -> None:
        self._legacy_db(tmp_path)
        with sqlite3.connect(str(tmp_path / "companion.db")) as conn:
            conn.execute("ALTER TABLE memories ADD COLUMN confidence REAL NOT NULL DEFAULT 0.42")
        store = MemoryStorage(tmp_path)
        with sqlite3.connect(str(store._db_path)) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM pragma_table_info('memories') WHERE name='confidence'"
            ).fetchone()
        assert row[0] == 1

    def test_backfill_tolerates_bad_content(self, tmp_path, monkeypatch) -> None:
        """单条内容分类炸了要跳过，不能整表迁移失败。"""
        self._legacy_db(tmp_path)
        with sqlite3.connect(str(tmp_path / "companion.db")) as conn:
            conn.execute(
                "INSERT INTO memories (user_id, id, content, level, category,"
                " created_at, last_accessed) VALUES (?,?,?,?,?,?,?)",
                ("u", "bad", "内容", 3, "other", "2026-01-01", "2026-01-01"),
            )

        def boom(text):
            raise RuntimeError("classify failed")

        monkeypatch.setattr(Memory, "classify_confidence", staticmethod(boom))
        store = MemoryStorage(tmp_path)
        assert store.count("u") == 1


class TestMigrateFromJson:
    def test_skips_without_dir(self, store, tmp_path) -> None:
        assert not (tmp_path / "memories").exists()

    def test_skips_empty_dir(self, tmp_path) -> None:
        (tmp_path / "memories").mkdir()
        MemoryStorage(tmp_path)

    def test_migrates_and_renames(self, tmp_path) -> None:
        json_dir = tmp_path / "memories"
        json_dir.mkdir()
        (json_dir / "u.json").write_text(
            json.dumps({"memories": [{"id": "m1", "content": "旧记忆", "level": 4}]},
                       ensure_ascii=False),
            encoding="utf-8",
        )
        store = MemoryStorage(tmp_path)
        assert store.count("u") == 1
        assert (json_dir / "u.json.migrated").exists()
        assert not (json_dir / "u.json").exists()

    def test_skips_when_sqlite_nonempty(self, tmp_path) -> None:
        store = MemoryStorage(tmp_path)
        store.add("u", _mem())
        store.close()

        json_dir = tmp_path / "memories"
        json_dir.mkdir()
        (json_dir / "u2.json").write_text(
            json.dumps({"memories": [{"id": "x", "content": "不该进来"}]}),
            encoding="utf-8",
        )
        reopened = MemoryStorage(tmp_path)
        assert reopened.count("u2") == 0
        assert (json_dir / "u2.json").exists()

    def test_bad_json_does_not_abort(self, tmp_path) -> None:
        json_dir = tmp_path / "memories"
        json_dir.mkdir()
        (json_dir / "broken.json").write_text("{ not json", encoding="utf-8")
        store = MemoryStorage(tmp_path)
        assert store.count("broken") == 0
        assert (json_dir / "broken.json").exists()


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #


class TestCrud:
    def test_add_and_get(self, store) -> None:
        store.add("u", _mem("m1", "你好"))
        loaded = store.get("u", "m1")
        assert loaded is not None
        assert loaded.content == "你好"

    def test_get_missing(self, store) -> None:
        assert store.get("u", "nope") is None

    def test_load_ordered_desc(self, store) -> None:
        store.add("u", _mem("a", created_at="2026-01-01T00:00:00"))
        store.add("u", _mem("b", created_at="2026-03-01T00:00:00"))
        assert [m.id for m in store.load("u")] == ["b", "a"]

    def test_load_empty(self, store) -> None:
        assert store.load("nobody") == []

    def test_save_replaces_all(self, store) -> None:
        store.add("u", _mem("old"))
        store.save("u", [_mem("new1"), _mem("new2")])
        ids = {m.id for m in store.load("u")}
        assert ids == {"new1", "new2"}

    def test_save_empty_clears(self, store) -> None:
        store.add("u", _mem())
        store.save("u", [])
        assert store.count("u") == 0

    def test_save_rollback_on_error(self, store, monkeypatch) -> None:
        store.add("u", _mem("keep"))
        original = MemoryStorage._insert

        def boom(self, memory, user_id=None):
            raise RuntimeError("insert failed")

        monkeypatch.setattr(MemoryStorage, "_insert", boom)
        with pytest.raises(RuntimeError):
            store.save("u", [_mem("new")])
        monkeypatch.setattr(MemoryStorage, "_insert", original)
        assert [m.id for m in store.load("u")] == ["keep"]

    def test_update(self, store) -> None:
        store.add("u", _mem("m1", "旧"))
        store.update("u", _mem("m1", "新"))
        updated = store.get("u", "m1")
        assert updated is not None
        assert updated.content == "新"

    def test_delete(self, store) -> None:
        store.add("u", _mem("m1"))
        assert store.delete("u", "m1") is True
        assert store.delete("u", "m1") is False

    def test_delete_all(self, store) -> None:
        store.add("u", _mem("m1"))
        store.add("u", _mem("m2"))
        assert store.delete_all("u") is True
        assert store.count("u") == 0

    def test_delete_all_missing(self, store) -> None:
        assert store.delete_all("nobody") is False

    def test_delete_all_scoped(self, store) -> None:
        store.add("a", _mem())
        store.add("b", _mem())
        store.delete_all("a")
        assert store.count("b") == 1

    def test_count(self, store) -> None:
        for i in range(3):
            store.add("u", _mem(f"m{i}"))
        assert store.count("u") == 3

    def test_list_users(self, store) -> None:
        store.add("a", _mem())
        store.add("b", _mem())
        assert set(store.list_users()) == {"a", "b"}

    def test_users_isolated(self, store) -> None:
        store.add("a", _mem("m1"))
        assert store.get("b", "m1") is None


class TestUpdateMany:
    """批量 / 按列更新。

    按列更新存在的原因：``_insert`` 是 ``INSERT OR REPLACE`` 整行覆盖，
    调用方手里的 ``Memory`` 可能是几十毫秒前 ``load()`` 出来的快照，
    整行覆盖会把别的线程刚写进去的 ``superseded_by`` / ``access_count``
    悄悄回滚（lost update）。
    """

    def test_returns_count(self, store) -> None:
        store.add("u", _mem("m1"))
        store.add("u", _mem("m2"))
        mems = store.load("u")
        assert store.update_many("u", mems) == 2

    def test_empty_list_noop(self, store) -> None:
        assert store.update_many("u", []) == 0

    def test_full_row_upsert_when_columns_none(self, store) -> None:
        store.add("u", _mem("m1", "旧"))
        store.update_many("u", [_mem("m1", "新")])
        got = store.get("u", "m1")
        assert got is not None and got.content == "新"

    def test_columns_only_updates_listed(self, store) -> None:
        store.add("u", _mem("m1", "原文"))
        stale = store.get("u", "m1")
        assert stale is not None

        # 别的线程在这之后写了 content / access_count
        fresh = store.get("u", "m1")
        assert fresh is not None
        fresh.content = "别人刚写的内容"
        fresh.access_count = 7
        store.update("u", fresh)

        # 手里这条陈旧快照只改 forget_score 并落库
        stale.forget_score = 0.75
        store.update_many("u", [stale], columns=("forget_score",))

        after = store.get("u", "m1")
        assert after is not None
        assert after.forget_score == pytest.approx(0.75)
        assert after.content == "别人刚写的内容", "未被列出的列不能被回滚"
        assert after.access_count == 7, "未被列出的列不能被回滚"

    def test_columns_json_and_bool_roundtrip(self, store) -> None:
        store.add("u", _mem("m1"))
        mem = store.get("u", "m1")
        assert mem is not None
        mem.tags = ["标签甲", "b"]
        mem.related_memory_ids = ["x1"]
        mem.archived = True
        store.update_many("u", [mem], columns=("tags", "related_ids", "archived"))

        after = store.get("u", "m1")
        assert after is not None
        assert after.tags == ["标签甲", "b"]
        assert after.related_memory_ids == ["x1"]
        assert after.archived is True

    def test_rollback_on_error(self, store, monkeypatch) -> None:
        store.add("u", _mem("m1", "原文"))
        mem = store.get("u", "m1")
        assert mem is not None
        mem.content = "改了一半"

        calls = {"n": 0}
        real = store._update_columns

        def boom(*args, **kwargs):
            calls["n"] += 1
            raise RuntimeError("db gone")

        monkeypatch.setattr(store, "_update_columns", boom)
        with pytest.raises(RuntimeError):
            store.update_many("u", [mem], columns=("content",))
        assert calls["n"] == 1
        after = store.get("u", "m1")
        assert after is not None and after.content == "原文"


class TestQueries:
    def test_search_like(self, store) -> None:
        store.add("u", _mem("m1", "我喜欢跑步"))
        store.add("u", _mem("m2", "喜欢吃面"))
        results = store.search("u", "跑步")
        assert [m.id for m in results] == ["m1"]

    def test_search_ordered_by_level(self, store) -> None:
        store.add("u", _mem("low", "跑步 低", level=2))
        store.add("u", _mem("high", "跑步 高", level=5))
        assert [m.id for m in store.search("u", "跑步")] == ["high", "low"]

    def test_search_limit(self, store) -> None:
        for i in range(5):
            store.add("u", _mem(f"m{i}", "跑步", level=i + 1))
        assert len(store.search("u", "跑步", limit=2)) == 2

    def test_search_no_match(self, store) -> None:
        store.add("u", _mem("m1", "跑步"))
        assert store.search("u", "游泳") == []

    def test_high_importance(self, store) -> None:
        store.add("u", _mem("low", level=2))
        store.add("u", _mem("high", level=5))
        assert [m.id for m in store.get_high_importance("u", min_level=3)] == ["high"]

    def test_high_importance_limit(self, store) -> None:
        for i in range(4):
            store.add("u", _mem(f"m{i}", level=5))
        assert len(store.get_high_importance("u", limit=2)) == 2

    def test_recent(self, store) -> None:
        store.add("u", _mem("a", created_at="2026-01-01T00:00:00"))
        store.add("u", _mem("b", created_at="2026-05-01T00:00:00"))
        assert [m.id for m in store.get_recent("u", limit=1)] == ["b"]


# --------------------------------------------------------------------------- #
# 行转换兼容
# --------------------------------------------------------------------------- #


class TestRowToMemory:
    def test_full_roundtrip(self, store) -> None:
        memory = Memory(
            id="m1", content="内容", level=4, category="personal",
            tags=["a", "b"], source="manual", related_memory_ids=["x"],
            superseded_by="m9", confidence=0.9, forget_score=0.25, archived=True,
        )
        store.add("u", memory)
        loaded = store.get("u", "m1")
        assert loaded is not None
        assert loaded.tags == ["a", "b"]
        assert loaded.related_memory_ids == ["x"]
        assert loaded.superseded_by == "m9"
        assert loaded.confidence == 0.9
        assert loaded.forget_score == 0.25
        assert loaded.archived is True

    def test_missing_optional_columns_use_defaults(self) -> None:
        """12 列老库的 Row 没有 confidence/forget_score/archived —— 走默认值。"""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE memories (
                user_id TEXT, id TEXT, content TEXT, level INT, category TEXT,
                created_at TEXT, last_accessed TEXT, access_count INT,
                tags TEXT, source TEXT, related_ids TEXT, superseded_by TEXT
            )
        """)
        conn.execute(
            "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("u", "m1", "内容", 3, "other", "2026-01-01", "2026-01-01", 0, "[]", "auto", "[]", ""),
        )
        row = conn.execute("SELECT * FROM memories").fetchone()
        memory = MemoryStorage._row_to_memory(row)
        assert memory.confidence == 0.5
        assert memory.forget_score == 0.0
        assert memory.archived is False

    def test_null_confidence_falls_back(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE memories (
                user_id TEXT, id TEXT, content TEXT, level INT, category TEXT,
                created_at TEXT, last_accessed TEXT, access_count INT,
                tags TEXT, source TEXT, related_ids TEXT, superseded_by TEXT,
                confidence REAL, forget_score REAL, archived INT
            )
        """)
        conn.execute(
            "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("u", "m1", "内容", 3, "other", "2026-01-01", "2026-01-01", 0,
             "[]", "auto", "[]", "", None, None, None),
        )
        memory = MemoryStorage._row_to_memory(conn.execute("SELECT * FROM memories").fetchone())
        assert memory.confidence == 0.5
        assert memory.forget_score == 0.0
        assert memory.archived is False

    def test_tags_already_list(self) -> None:
        """tags 列万一被写成非 str（某些驱动会原样返回 list），不要 json.loads。"""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE memories (
                user_id TEXT, id TEXT, content TEXT, level INT, category TEXT,
                created_at TEXT, last_accessed TEXT, access_count INT,
                tags BLOB, source TEXT, related_ids TEXT, superseded_by TEXT
            )
        """)
        conn.execute(
            "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("u", "m1", "内容", 3, "other", "2026-01-01", "2026-01-01", 0,
             json.dumps(["a"]), "auto", json.dumps(["b"]), ""),
        )
        row = conn.execute("SELECT * FROM memories").fetchone()
        assert MemoryStorage._row_to_memory(row).tags == ["a"]


class TestJsonColumns:
    def test_tags_written_as_json(self, store) -> None:
        store.add("u", _mem(tags=["甲", "乙"]))
        with sqlite3.connect(str(store._db_path)) as conn:
            raw = conn.execute("SELECT tags, related_ids FROM memories").fetchone()
        assert json.loads(raw[0]) == ["甲", "乙"]

    def test_unicode_not_escaped(self, store) -> None:
        store.add("u", _mem(tags=["中文"]))
        with sqlite3.connect(str(store._db_path)) as conn:
            raw = conn.execute("SELECT tags FROM memories").fetchone()[0]
        assert "中文" in raw

    def test_archived_stored_as_int(self, store) -> None:
        store.add("u", _mem(archived=True))
        with sqlite3.connect(str(store._db_path)) as conn:
            raw = conn.execute("SELECT archived FROM memories").fetchone()[0]
        assert raw == 1


# --------------------------------------------------------------------------- #
# 维护操作
# --------------------------------------------------------------------------- #


class TestCheckpoint:
    def test_counter_increments(self, store) -> None:
        store._maybe_checkpoint()
        store._maybe_checkpoint()
        assert store._write_counter == 2

    def test_checkpoint_at_hundred(self, store, monkeypatch) -> None:
        """每 100 次写入触发一次 WAL 检点。"""
        conn = store._conn
        seen: list[str] = []

        class Spy:
            def execute(self, sql, *args, **kwargs):
                seen.append(str(sql))
                return conn.execute(sql, *args, **kwargs)

        monkeypatch.setattr(MemoryStorage, "_conn", property(lambda self: Spy()))
        store._write_counter = 99
        store._maybe_checkpoint()
        assert sum("wal_checkpoint" in s for s in seen) == 1
        store._maybe_checkpoint()
        assert sum("wal_checkpoint" in s for s in seen) == 1  # 101 不触发

    def test_checkpoint_failure_swallowed(self, store, monkeypatch) -> None:
        conn = store._conn

        class Boom:
            def execute(self, sql, *args, **kwargs):
                if "wal_checkpoint" in str(sql):
                    raise RuntimeError("no checkpoint")
                return conn.execute(sql, *args, **kwargs)

        monkeypatch.setattr(MemoryStorage, "_conn", property(lambda self: Boom()))
        store._write_counter = 99
        store._maybe_checkpoint()  # 不该抛


class TestIntegrity:
    def test_ok_silent(self, store) -> None:
        store._verify_integrity()

    def test_bad_result_warns(self, store, monkeypatch) -> None:
        conn = store._conn

        class FakeCursor:
            def fetchone(self):
                return ("*** in database main ***",)

        class Fake:
            def execute(self, sql, *args, **kwargs):
                if "integrity_check" in str(sql):
                    return FakeCursor()
                return conn.execute(sql, *args, **kwargs)

        monkeypatch.setattr(MemoryStorage, "_conn", property(lambda self: Fake()))
        store._verify_integrity()

    def test_exception_swallowed(self, store, monkeypatch) -> None:
        class Boom:
            def execute(self, sql, *args, **kwargs):
                raise RuntimeError("broken")

        monkeypatch.setattr(MemoryStorage, "_conn", property(lambda self: Boom()))
        store._verify_integrity()  # 不该抛


class TestLifecycle:
    def test_close_and_reopen(self, tmp_path) -> None:
        store = MemoryStorage(tmp_path)
        store.add("u", _mem())
        store.close()
        assert store._local.conn is None
        assert store.count("u") == 1

    def test_close_without_conn(self, tmp_path) -> None:
        store = MemoryStorage(tmp_path)
        store._local.conn = None
        store.close()  # 不该抛

    def test_close_swallows_errors(self, store) -> None:
        class BadConn:
            def execute(self, *a, **k):
                raise RuntimeError("x")

            def close(self):
                raise RuntimeError("y")

        store._local.conn = BadConn()
        store.close()
        assert store._local.conn is None

    def test_context_manager(self, tmp_path) -> None:
        with MemoryStorage(tmp_path) as store:
            store.add("u", _mem())
        assert store.count("u") == 1

    def test_data_dir_property(self, tmp_path) -> None:
        assert MemoryStorage(tmp_path).data_dir == tmp_path
