"""Embedder — 文本向量嵌入（同步，可直接在 async 上下文调用）

将文本转为稠密向量，用于语义搜索。

模型解析优先级（**离线优先**）：
  1. 环境变量 ``MU_EMBEDDING_MODEL_PATH`` / ``CC_EMBEDDING_MODEL_PATH`` 指定的目录
  2. 项目内 ``models/bge-small-zh-v1.5``（随仓库/打包分发，无需联网）
  3. HF 缓存里的 ``BAAI/bge-small-zh-v1.5``（若用户已手工下载过）
  4. 允许联网时才回退到 hub id 在线拉取

历史问题：早期实现直接传 hub id + ``local_files_only=True``，
在无法访问 huggingface.co 的机器上必然失败，于是向量记忆全程空转。
现在改为「本地目录优先」，只有显式设置 ``MU_EMBEDDING_ALLOW_DOWNLOAD=1``
才会尝试联网下载。
"""

import os
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from loguru import logger

# 默认嵌入模型（中文优化，33MB 参数即 ~92MB safetensors，输出 512 维）
DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
# 本地目录名（与下载脚本一致）
LOCAL_MODEL_DIRNAME = "bge-small-zh-v1.5"

# 判定一个目录是否是可用的 sentence-transformers 模型目录
_REQUIRED_FILES = ("config.json", "modules.json")


def _env_flag(*names: str) -> bool:
    for name in names:
        value = (os.getenv(name) or "").strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
    return False


def _candidate_local_dirs() -> list[Path]:
    """收集所有可能存放本地模型副本的目录（按优先级）。"""
    candidates: list[Path] = []

    override = (
        os.getenv("MU_EMBEDDING_MODEL_PATH")
        or os.getenv("CC_EMBEDDING_MODEL_PATH")
        or ""
    ).strip()
    if override:
        candidates.append(Path(override).expanduser())

    try:
        from core.config import ROOT  # 延迟导入，避免循环依赖

        candidates.append(Path(ROOT) / "models" / LOCAL_MODEL_DIRNAME)
    except Exception:  # pragma: no cover - 仅在极端导入失败时触发
        pass

    # 源码布局：core/memory/embedder.py -> 项目根
    project_root = Path(__file__).resolve().parents[2]
    candidates.append(project_root / "models" / LOCAL_MODEL_DIRNAME)

    # 打包布局：可执行文件旁边的 models/
    candidates.append(Path.cwd() / "models" / LOCAL_MODEL_DIRNAME)

    return candidates


def _is_model_dir(path: Path) -> bool:
    try:
        if not path.is_dir():
            return False
        return all((path / name).is_file() for name in _REQUIRED_FILES)
    except OSError:
        return False


def resolve_model_source() -> str:
    """返回可用的模型来源字符串：本地目录绝对路径，或 hub id（需要联网）。

    调用方无需关心区别 —— ``SentenceTransformer`` 两者都接受。
    """
    for candidate in _candidate_local_dirs():
        if _is_model_dir(candidate):
            return str(candidate.resolve())
    return DEFAULT_MODEL


class BaseEmbedder(ABC):
    """嵌入器基类（同步接口）"""

    @abstractmethod
    def embed(self, text: str) -> list[float] | None:
        """将单条文本转为向量，失败返回 None"""
        ...

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]] | None:
        """批量嵌入，失败返回 None"""
        ...

    @property
    @abstractmethod
    def available(self) -> bool:
        """是否可用"""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """向量维度"""
        ...


class SentenceTransformerEmbedder(BaseEmbedder):
    """基于 sentence-transformers 的本地嵌入器（同步）

    线程注意：``available`` 是首次调用时才加载模型（约 0.5-2s），
    加载失败会缓存错误，不会每一轮对话重试。
    """

    def __init__(self, model_name: str | None = None):
        # 传 None 时按「本地目录优先」自动解析
        self._explicit_model = model_name
        self._model_name = model_name or ""
        self._resolved_source = ""
        self._model = None
        self._dim = 0
        self._ready = False
        self._init_error = None
        # 保护 _lazy_init 的「一次性加载」语义。
        #
        # 不加锁时 6 个线程会同时通过 `if self._ready or self._init_error`
        # 的判断，一起调 SentenceTransformer()。torch 加载权重期间多个
        # 线程同时往同一批 tensor 里搬数据，会把参数写成 meta tensor，
        # 报「Cannot copy out of meta tensor; no data!」，于是「模型其实
        # 能用」和「加载失败」两种状态在同一次启动里同时出现：
        # 后台回填线程看到失败并写进 _init_error，主线程的实例却成功了。
        # 结果就是日志说「回退关键词搜索」，embedding_status 却说 ready=True。
        self._init_lock = threading.Lock()

    @property
    def model_source(self) -> str:
        """实际使用的模型来源（本地路径或 hub id），供诊断接口展示。"""
        if self._resolved_source:
            return self._resolved_source
        return self._model_name or resolve_model_source()

    @property
    def available(self) -> bool:
        if not self._ready and not self._init_error:
            self._lazy_init()
        return self._ready

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def init_error(self) -> str | None:
        """最近一次初始化失败的原因（成功时为 None）。"""
        return self._init_error

    def _lazy_init(self):
        """首次使用时延迟加载模型（线程安全，只会真正加载一次）"""
        if self._ready or self._init_error:
            return
        with self._init_lock:
            # 双重检查：等锁期间别的线程可能已经把模型加载好了
            if self._ready or self._init_error:
                return
            self._lazy_init_locked()

    def _lazy_init_locked(self):
        """真正加载模型的部分，调用方必须持有 ``self._init_lock``。"""

        source = self._explicit_model or resolve_model_source()
        self._resolved_source = source
        self._model_name = source

        # 本地目录 → 强制离线；hub id → 是否允许联网由环境变量决定
        is_local_dir = Path(source).exists()
        allow_download = _env_flag(
            "MU_EMBEDDING_ALLOW_DOWNLOAD", "CC_EMBEDDING_ALLOW_DOWNLOAD"
        )

        try:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading embedding model: {source} (local_dir={is_local_dir})")
            self._model = SentenceTransformer(
                source,
                local_files_only=is_local_dir or not allow_download,
            )
            self._dim = self._model.get_sentence_embedding_dimension()
            self._ready = True
            logger.info(f"Embedder ready (dim={self._dim}, source={source})")
        except Exception as e:
            self._init_error = str(e)
            self._model = None
            logger.warning(f"Failed to load embedding model '{source}': {e}")
            logger.warning(
                "Falling back to keyword-based memory search. "
                "离线环境请把模型放到 models/"
                f"{LOCAL_MODEL_DIRNAME}/（运行 python -m tools.fetch_embedding_model）"
            )

    def embed(self, text: str) -> list[float] | None:
        self._lazy_init()
        if not self._ready:
            return None
        try:
            vec = self._model.encode(text, normalize_embeddings=True)
            return vec.tolist()
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            return None

    def embed_batch(self, texts: list[str]) -> list[list[float]] | None:
        self._lazy_init()
        if not self._ready:
            return None
        if not texts:
            return []
        try:
            vecs = self._model.encode(texts, normalize_embeddings=True)
            return [v.tolist() for v in vecs]
        except Exception as e:
            logger.error(f"Batch embedding failed: {e}")
            return None
