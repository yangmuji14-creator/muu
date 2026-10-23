"""人设加载器（core/persona/loader.py）。

测三件最容易出事的地方：
1. 旧版 personas.json 缺字段要能补默认值读进来（向后兼容）；
2. `update()` 的字段白名单 —— 未知字段丢弃，非法值整笔拒绝且**不能改内存里的副本**；
3. `delete()` 顺带清 avatar 孤儿文件。

`_AVATAR_DIR` 是模块级常量（`core.config.DATA_DIR / "avatars"`），测试里
monkeypatch 到 tmp_path，避免误删真实头像。
"""

from __future__ import annotations

import json

import pytest

from core.persona import loader as loader_mod
from core.persona.loader import PersonaLoader
from core.persona.models import Persona


@pytest.fixture()
def avatar_dir(tmp_path, monkeypatch):
    d = tmp_path / "avatars"
    d.mkdir()
    monkeypatch.setattr(loader_mod, "_AVATAR_DIR", d)
    return d


@pytest.fixture()
def config_path(tmp_path):
    return tmp_path / "personas.json"


@pytest.fixture()
def loader(config_path, avatar_dir):
    return PersonaLoader(config_path)


def _write(path, personas) -> None:
    path.write_text(
        json.dumps({"personas": personas}, ensure_ascii=False), encoding="utf-8"
    )


MINIMAL_PERSONA = {
    "id": "girlfriend_001",
    "name": "慕",
    "personality": ["真诚", "自然"],
    "background": "一个陪伴者",
}


class TestLoad:
    def test_missing_file_logs_and_returns_empty(self, loader):
        assert loader.list_all() == []

    def test_reads_personas(self, config_path, avatar_dir):
        _write(config_path, [MINIMAL_PERSONA])
        loaded = PersonaLoader(config_path)
        assert loaded.get("girlfriend_001").name == "慕"

    def test_broken_json_yields_empty(self, config_path, avatar_dir):
        config_path.write_text("{ not json", encoding="utf-8")
        assert PersonaLoader(config_path).list_all() == []

    def test_missing_personas_key_yields_empty(self, config_path, avatar_dir):
        config_path.write_text("{}", encoding="utf-8")
        assert PersonaLoader(config_path).list_all() == []

    def test_legacy_missing_fields_get_defaults(self, config_path, avatar_dir):
        """旧版文件里没有 hard_rules / speaking_style 等字段，要补默认值。"""
        _write(config_path, [MINIMAL_PERSONA])
        p = PersonaLoader(config_path).get("girlfriend_001")
        assert p.hard_rules == []
        assert p.speaking_style == {}
        assert p.emotional_patterns == {}
        assert p.relationship_behavior == {}
        assert p.sticker_enabled is True
        assert p.sticker_probability == pytest.approx(0.18)
        assert p.sticker_pack == "builtin"

    def test_legacy_defaults_fill_many_fields(self, config_path, avatar_dir):
        _write(config_path, [MINIMAL_PERSONA])
        p = PersonaLoader(config_path).get("girlfriend_001")
        for key, expected in loader_mod._PERSONA_DEFAULTS.items():
            assert getattr(p, key) == expected, f"{key} 默认值不对"

    def test_existing_values_not_overwritten_by_defaults(self, config_path, avatar_dir):
        _write(config_path, [{**MINIMAL_PERSONA, "mbti": "INFP", "sticker_pack": "pawzochat"}])
        p = PersonaLoader(config_path).get("girlfriend_001")
        assert p.mbti == "INFP"
        assert p.sticker_pack == "pawzochat"

    def test_multiple_personas(self, config_path, avatar_dir):
        _write(
            config_path,
            [MINIMAL_PERSONA, {"id": "p2", "name": "第二个人"}],
        )
        loaded = PersonaLoader(config_path)
        assert len(loaded.list_all()) == 2
        assert loaded.get("p2").name == "第二个人"

    def test_list_all_returns_persona_objects(self, config_path, avatar_dir):
        _write(config_path, [MINIMAL_PERSONA])
        items = PersonaLoader(config_path).list_all()
        assert all(isinstance(p, Persona) for p in items)

    def test_get_unknown_returns_none(self, loader):
        assert loader.get("不存在") is None


class TestAdd:
    def test_add_persists(self, config_path, avatar_dir):
        inst = PersonaLoader(config_path)
        inst.add(Persona(id="p2", name="新人"))
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        assert [p["id"] for p in raw["personas"]] == ["p2"]

    def test_add_then_reload_same_data(self, config_path, avatar_dir):
        inst = PersonaLoader(config_path)
        inst.add(Persona(id="p2", name="新人", personality=["温柔"]))
        again = PersonaLoader(config_path).get("p2")
        assert again.name == "新人"
        assert again.personality == ["温柔"]

    def test_add_same_id_replaces(self, config_path, avatar_dir):
        inst = PersonaLoader(config_path)
        inst.add(Persona(id="p2", name="旧"))
        inst.add(Persona(id="p2", name="新"))
        assert inst.get("p2").name == "新"
        assert len(inst.list_all()) == 1


class TestUpdate:
    def test_allowed_field_updated(self, loader):
        loader.add(Persona(id="p1", name="原名"))
        updated = loader.update("p1", name="新名")
        assert updated.name == "新名"
        assert loader.get("p1").name == "新名"

    def test_unknown_persona_returns_none(self, loader):
        assert loader.update("不存在", name="x") is None

    def test_disallowed_field_ignored(self, loader):
        """`id` 不在 ALLOWED_FIELDS 里 —— 改 id 会让所有引用悬空。"""
        loader.add(Persona(id="p1", name="原名"))
        loader.update("p1", id="p_hacked", name="新名")
        assert loader.get("p1") is not None
        assert loader.get("p_hacked") is None

    def test_update_persists(self, config_path, avatar_dir):
        inst = PersonaLoader(config_path)
        inst.add(Persona(id="p1", name="原名"))
        inst.update("p1", name="新名")
        assert PersonaLoader(config_path).get("p1").name == "新名"

    def test_invalid_value_rejected_and_memory_kept(self, loader):
        """`age` 传非数字 → Pydantic 拒绝，内存里的对象必须保持原样。"""
        loader.add(Persona(id="p1", name="原名", age=20))
        assert loader.update("p1", age="不是数字") is None
        assert loader.get("p1").age == 20

    def test_update_returns_updated_object(self, loader):
        loader.add(Persona(id="p1", name="原名"))
        updated = loader.update("p1", nickname_for_user="宝贝")
        assert updated.nickname_for_user == "宝贝"

    def test_partial_update_keeps_other_fields(self, loader):
        loader.add(Persona(id="p1", name="原名", personality=["温柔"], age=22))
        loader.update("p1", nickname_for_user="宝贝")
        p = loader.get("p1")
        assert p.personality == ["温柔"]
        assert p.age == 22


class TestDelete:
    def test_delete_existing(self, loader):
        loader.add(Persona(id="p1", name="x"))
        assert loader.delete("p1") is True
        assert loader.get("p1") is None

    def test_delete_missing_returns_false(self, loader):
        assert loader.delete("不存在") is False

    def test_delete_persists(self, config_path, avatar_dir):
        inst = PersonaLoader(config_path)
        inst.add(Persona(id="p1", name="x"))
        inst.delete("p1")
        assert PersonaLoader(config_path).list_all() == []

    def test_delete_cleans_avatar_files(self, loader, avatar_dir):
        loader.add(Persona(id="p1", name="x"))
        (avatar_dir / "p1.png").write_bytes(b"fake")
        (avatar_dir / "p1.jpg").write_bytes(b"fake")
        loader.delete("p1")
        assert list(avatar_dir.iterdir()) == []

    def test_delete_keeps_other_persona_avatars(self, loader, avatar_dir):
        loader.add(Persona(id="p1", name="x"))
        loader.add(Persona(id="p2", name="y"))
        (avatar_dir / "p1.png").write_bytes(b"fake")
        (avatar_dir / "p2.png").write_bytes(b"fake")
        loader.delete("p1")
        assert [p.name for p in avatar_dir.iterdir()] == ["p2.png"]

    def test_avatar_cleanup_failure_tolerated(self, loader, avatar_dir, monkeypatch):
        """unlink 抛异常时只警告，不能把 delete 整笔弄失败。"""
        loader.add(Persona(id="p1", name="x"))
        (avatar_dir / "p1.png").write_bytes(b"fake")

        import pathlib

        def boom(self):
            raise PermissionError("占用中")

        monkeypatch.setattr(pathlib.Path, "unlink", boom)
        assert loader.delete("p1") is True
        assert loader.get("p1") is None


class TestFieldSets:
    def test_user_and_advanced_are_disjoint(self):
        """用户可编辑字段与高级字段不能重叠，否则前端会渲染两遍。"""
        assert PersonaLoader.USER_FIELDS & PersonaLoader.ADVANCED_FIELDS == set()

    def test_both_subsets_of_allowed(self):
        assert PersonaLoader.USER_FIELDS <= PersonaLoader.ALLOWED_FIELDS
        assert PersonaLoader.ADVANCED_FIELDS <= PersonaLoader.ALLOWED_FIELDS

    def test_every_allowed_field_exists_on_model(self):
        """白名单里写了模型上没有的字段 → update 时会静默丢弃，得提前发现。"""
        model_fields = set(Persona.model_fields)
        assert PersonaLoader.ALLOWED_FIELDS <= model_fields

    def test_id_not_editable(self):
        assert "id" not in PersonaLoader.ALLOWED_FIELDS
