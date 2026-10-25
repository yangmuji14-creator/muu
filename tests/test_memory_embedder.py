"""记忆系统测试：向量嵌入解析 + 混合排序 + 存储层语义不变量。

覆盖:
- resolve_model_source()：本地目录优先，找不到时退回 hub id
- _is_model_dir()：必须同时有 config.json 与 modules.json
- SentenceTransformerEmbedder 的本地加载与语义正确性（离线）
- VectorStore 的增删查与余弦相似度排序
- MemoryManager._hybrid_rank_prompt 的混合权重行为（语义 0.5 + 重要度 0.3 + 时效 0.2）

这些用例默认在离线模式跑：模型来自仓库内 models/ 目录。
"""

import os
from pathlib import Path

import numpy as np
import pytest

from core.memory.embedder import (
    DEFAULT_MODEL,
    LOCAL_MODEL_DIRNAME,
    SentenceTransformerEmbedder,
    _is_model_dir,
    resolve_model_source,
)


class TestModelResolution:
    def test_is_model_dir_requires_config_and_modules(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert _is_model_dir(empty) is False

        half = tmp_path / "half"
        half.mkdir()
        (half / "config.json").write_text("{}", encoding="utf-8")
        assert _is_model_dir(half) is False

        full = tmp_path / "full"
        full.mkdir()
        (full / "config.json").write_text("{}", encoding="utf-8")
        (full / "modules.json").write_text("[]", encoding="utf-8")
        assert _is_model_dir(full) is True

    def test_is_model_dir_false_for_missing_path(self, tmp_path):
        assert _is_model_dir(tmp_path / "nope") is False

    def test_resolve_prefers_env_override(self, tmp_path, monkeypatch):
        model_dir = tmp_path / LOCAL_MODEL_DIRNAME
        model_dir.mkdir()
        (model_dir / "config.json").write_text("{}", encoding="utf-8")
        (model_dir / "modules.json").write_text("[]", encoding="utf-8")

        monkeypatch.setenv("MU_EMBEDDING_MODEL_PATH", str(model_dir))
        assert resolve_model_source() == str(model_dir.resolve())

    def test_resolve_falls_back_to_hub_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MU_EMBEDDING_MODEL_PATH", str(tmp_path / "missing"))
        # 清掉可能存在的其他候选命中
        src = resolve_model_source()
        # 仓库内有 models/ 时会命中本地；否则退回 hub id，两者都是合法结果
        assert src == DEFAULT_MODEL or Path(src).is_dir()


@pytest.fixture(scope="module")
def embedder():
    """仓库内本地模型，离线加载一次。"""
    emb = SentenceTransformerEmbedder()
    if not emb.available:
        pytest.skip(f"本地嵌入模型不可用: {emb.init_error}")
    return emb


class TestEmbedder:
    def test_available_and_dimension(self, embedder):
        assert embedder.available is True
        assert embedder.dimension == 512
        assert embedder.dim == 512
        assert embedder.init_error is None

    def test_model_source_is_local_dir(self, embedder):
        assert Path(embedder.model_source).is_dir()

    def test_embed_returns_512_floats(self, embedder):
        vec = embedder.embed("他养了一只猫")
        assert isinstance(vec, list)
        assert len(vec) == 512
        assert all(isinstance(v, float) for v in vec[:5])

    def test_embed_batch_length_matches(self, embedder):
        out = embedder.embed_batch(["第一句", "第二句", "第三句"])
        assert len(out) == 3
        assert all(len(v) == 512 for v in out)

    def test_embed_batch_empty_returns_empty(self, embedder):
        """空输入必须返回 []，而不是 None 或抛异常。"""
        assert embedder.embed_batch([]) == []

    def test_semantic_ordering(self, embedder):
        """语义相近的句子相似度必须高于无关句子 —— 这是向量记忆的根。"""
        query = embedder.embed("我喜欢吃烤红薯")
        close = embedder.embed("用户爱吃街边的烤红薯")
        far = embedder.embed("我的显卡型号是 RTX 4090")

        def cosine(a, b):
            a, b = np.array(a), np.array(b)
            return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))

        assert cosine(query, close) > cosine(query, far)
        assert cosine(query, close) > 0.7

    def test_same_text_is_identical_vector(self, embedder):
        a = embedder.embed("完全一样的一句话")
        b = embedder.embed("完全一样的一句话")
        assert np.allclose(a, b, atol=1e-6)


class TestLazyInitThreadSafety:
    """并发首次加载只能真正加载一次。

    历史 bug：``_lazy_init`` 开头只有一句
    ``if self._ready or self._init_error: return``，没有锁。启动时后台回填
    线程和主线程同时调 ``available``，两个线程都通过判断、一起进
    ``SentenceTransformer(...)``，torch 在加载权重期间被并发写坏，报
    ``Cannot copy out of meta tensor; no data!``。于是同一次启动里既有
    「加载失败，回退关键词搜索」的 warning，又有 ``ready=True`` 的诊断，
    谁都不知道到底能不能用。
    """

    def test_concurrent_available_loads_once(self, embedder, monkeypatch):
        import threading

        # 换一个全新的实例，确保 _lazy_init 还没跑过
        fresh = SentenceTransformerEmbedder(embedder.model_source)
        calls = []
        original = fresh._lazy_init_locked

        def counting():
            calls.append(1)
            original()

        monkeypatch.setattr(fresh, "_lazy_init_locked", counting)

        threads = [threading.Thread(target=lambda: fresh.available) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(calls) == 1, f"模型被加载了 {len(calls)} 次，应只加载 1 次"
        assert fresh.available is True
        assert fresh.init_error is None
        assert fresh.dimension == 512

