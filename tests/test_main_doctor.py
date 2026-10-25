"""main.py 的 doctor 自检：语义记忆那一项必须能区分三种状态。

为什么单测这个
--------------
`_doctor()` 以前只查 5 个核心依赖，完全不看语义记忆。用户装了 92MB 的模型、
也 pip 装了 sentence-transformers，却仍然只能靠「AI 好像记不住意思相近的话」
来猜向量记忆到底有没有生效 —— 这正是 v0.1.9 之前那个「不知道有没有在真正运作」
的盲区。现在 doctor 会分开报：依赖没装 / 模型不在 / 模型加载失败 / 一切正常。

这四种状态的判定逻辑很容易写反（尤其 `resolve_model_source()` 在找不到本地目录时
返回的是 hub id 而不是空串），所以用假模块把每条分支都钉住。
"""

from __future__ import annotations

import sys
import types

import pytest

import main as main_module


def _run_doctor(monkeypatch, *, has_deps: bool, model_source: str, available: bool, dimension: int = 512):
    """跑 _doctor()，返回它打印的文本。外部依赖全部打桩，不碰真实模型。"""
    fake_embedder_mod = types.ModuleType("core.memory.embedder")
    fake_embedder_mod.DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
    fake_embedder_mod.LOCAL_MODEL_DIRNAME = "bge-small-zh-v1.5"
    fake_embedder_mod.resolve_model_source = lambda: model_source

    class FakeEmbedder:
        def __init__(self) -> None:
            self.available = available
            self.dimension = dimension

    fake_embedder_mod.SentenceTransformerEmbedder = FakeEmbedder

    monkeypatch.setitem(sys.modules, "core.memory.embedder", fake_embedder_mod)

    if has_deps:
        fake_st = types.ModuleType("sentence_transformers")
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st)
    else:
        # None 让 `import sentence_transformers` 抛 ImportError
        monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    captured: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: captured.append(" ".join(str(x) for x in a)))
    main_module._doctor()
    return "\n".join(captured)


LOCAL = "C:/proj/models/bge-small-zh-v1.5"
HUB = "BAAI/bge-small-zh-v1.5"


class TestDoctorSemanticMemory:
    def test_reports_enabled_when_everything_works(self, monkeypatch):
        out = _run_doctor(monkeypatch, has_deps=True, model_source=LOCAL, available=True)
        assert "语义记忆已启用" in out
        assert "512 维向量" in out

    def test_warns_when_deps_missing(self, monkeypatch):
        out = _run_doctor(monkeypatch, has_deps=False, model_source=LOCAL, available=False)
        assert "未安装语义记忆依赖" in out
        assert "requirements-vector.txt" in out

    def test_warns_when_model_dir_absent(self, monkeypatch):
        """resolve_model_source() 找不到本地目录时返回 hub id，不是空串 —— 这条最容易写错。"""
        out = _run_doctor(monkeypatch, has_deps=True, model_source=HUB, available=False)
        assert "没有本地向量模型" in out
        assert "fetch_embedding_model" in out

    def test_warns_when_model_fails_to_load(self, monkeypatch):
        out = _run_doctor(monkeypatch, has_deps=True, model_source=LOCAL, available=False)
        assert "向量模型加载失败" in out
        # 不能误报成「没有本地向量模型」—— 目录在，只是加载不出来
        assert "没有本地向量模型" not in out

    def test_doctor_never_raises_on_broken_embedder_module(self, monkeypatch):
        """embedder 模块自身炸掉时，doctor 要给出警告而不是整体崩掉。"""
        monkeypatch.setitem(sys.modules, "core.memory.embedder", None)
        captured: list[str] = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: captured.append(" ".join(str(x) for x in a)))
        assert main_module._doctor() == 0
        assert "语义记忆自检失败" in "\n".join(captured)
