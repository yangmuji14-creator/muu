#!/usr/bin/env python
"""下载本地嵌入模型（BAAI/bge-small-zh-v1.5）到 ``models/``。

为什么需要这个脚本
------------------
`huggingface.co` 在国内网络环境下通常不可达，而 `sentence-transformers`
默认会去 hub 拉模型。模型拉不到时，`core/memory/embedder.py` 会优雅降级成
关键词搜索 —— 功能不崩，但「语义记忆」等于全程没启用。

本脚本按以下顺序尝试下载源，任意一个成功即可：

1. ModelScope（国内直连，通常最快）
   https://modelscope.cn/api/v1/models/BAAI/bge-small-zh-v1.5/repo
2. hf-mirror.com（HuggingFace 国内镜像）
3. huggingface.co（直连，可能需要代理）

用法
----
    ./.venv/Scripts/python.exe -m tools.fetch_embedding_model
    ./.venv/Scripts/python.exe -m tools.fetch_embedding_model --force
    ./.venv/Scripts/python.exe -m tools.fetch_embedding_model --source hf-mirror

下载完成后无需改配置，`core/memory/embedder.py` 会自动发现
``models/bge-small-zh-v1.5/`` 并离线加载。
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

MODEL_REPO = "BAAI/bge-small-zh-v1.5"
MODEL_DIRNAME = "bge-small-zh-v1.5"

# 需要下载的文件（sentence-transformers 目录格式）
FILES = [
    "config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "special_tokens_map.json",
    "modules.json",
    "sentence_bert_config.json",
    "1_Pooling/config.json",
]

SOURCES = {
    "modelscope": "https://modelscope.cn/api/v1/models/{repo}/repo?Revision=master&FilePath={file}",
    "hf-mirror": "https://hf-mirror.com/{repo}/resolve/main/{file}",
    "huggingface": "https://huggingface.co/{repo}/resolve/main/{file}",
}

# 关键文件的期望大小下限（字节），用于识别被限流/被劫持的假响应
MIN_SIZES = {
    "model.safetensors": 50_000_000,
    "tokenizer.json": 100_000,
    "vocab.txt": 50_000,
    "config.json": 300,
}

DEFAULT_ORDER = ["modelscope", "hf-mirror", "huggingface"]


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def target_dir() -> Path:
    return project_root() / "models" / MODEL_DIRNAME


def _log(msg: str) -> None:
    print(msg, flush=True)


def _download(url: str, dest: Path, timeout: int = 120) -> tuple[bool, str]:
    """下载单个文件。返回 (成功?, 说明)。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "muu-model-fetcher/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            if status != 200:
                return False, f"HTTP {status}"
            expected = resp.headers.get("Content-Length")
            written = 0
            with open(tmp, "wb") as fh:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
                    written += len(chunk)
            if expected is not None and written != int(expected):
                tmp.unlink(missing_ok=True)
                return False, f"长度不符 ({written}/{expected})"
    except urllib.error.HTTPError as e:
        tmp.unlink(missing_ok=True)
        return False, f"HTTP {e.code}"
    except Exception as e:  # 网络超时、DNS 失败等
        tmp.unlink(missing_ok=True)
        return False, f"{type(e).__name__}: {e}"

    minimum = MIN_SIZES.get(dest.name)
    if minimum is not None and written < minimum:
        tmp.unlink(missing_ok=True)
        return False, f"响应过小 ({written} < {minimum})，可能是错误页"

    tmp.replace(dest)
    return True, f"{written / 1024 / 1024:.1f}MB"


def download_model(source: str, dest: Path, force: bool) -> bool:
    template = SOURCES[source]
    _log(f"[{source}] 目标目录: {dest}")

    ok_count = 0
    for name in FILES:
        file_path = dest / name
        if file_path.exists() and not force and file_path.stat().st_size > 0:
            _log(f"  跳过 {name}（已存在）")
            ok_count += 1
            continue
        url = template.format(repo=MODEL_REPO, file=name)
        ok, detail = _download(url, file_path)
        if ok:
            _log(f"  OK   {name}  {detail}")
            ok_count += 1
        else:
            _log(f"  FAIL {name}  {detail}")
            return False

    if ok_count != len(FILES):
        return False

    # 完整性抽查：模型文件必须能读出行数与摘要
    model_file = dest / "model.safetensors"
    if model_file.exists():
        digest = hashlib.sha256()
        with open(model_file, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                digest.update(block)
        _log(f"  model.safetensors sha256={digest.hexdigest()[:16]}…")
    return True


def verify(dest: Path) -> bool:
    """离线加载一次，确认模型真能用。"""
    _log("\n验证：离线加载模型…")
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np

        model = SentenceTransformer(str(dest), local_files_only=True)
        dim = model.get_sentence_embedding_dimension()
        a, b, c = model.encode(
            ["我喜欢吃烤红薯", "用户爱吃街边的烤红薯", "我的显卡是 RTX 4090"],
            normalize_embeddings=True,
        )
        related = float(np.dot(a, b))
        unrelated = float(np.dot(a, c))
        _log(f"  dim={dim}")
        _log(f"  相似句得分 = {related:.4f}（应 > 0.6）")
        _log(f"  无关句得分 = {unrelated:.4f}（应 < 0.5）")
        if dim != 512:
            _log("  ! 维度不是 512，可能用错了模型")
            return False
        if related <= unrelated:
            _log("  ! 语义排序异常")
            return False
        return True
    except Exception as e:
        _log(f"  验证失败: {type(e).__name__}: {e}")
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="下载 bge-small-zh-v1.5 到 models/ 供记忆系统离线使用"
    )
    parser.add_argument(
        "--source",
        choices=DEFAULT_ORDER + ["auto"],
        default="auto",
        help="下载源，默认 auto（依次尝试 modelscope → hf-mirror → huggingface）",
    )
    parser.add_argument("--force", action="store_true", help="已存在的文件也重新下载")
    parser.add_argument("--verify-only", action="store_true", help="只验证本地模型，不下载")
    args = parser.parse_args(argv)

    dest = target_dir()

    if args.verify_only:
        if not dest.is_dir():
            _log(f"本地没有模型目录: {dest}")
            return 1
        return 0 if verify(dest) else 1

    order = DEFAULT_ORDER if args.source == "auto" else [args.source]

    for source in order:
        _log(f"\n=== 尝试下载源: {source} ===")
        try:
            if download_model(source, dest, args.force):
                _log(f"\n[{source}] 全部文件就绪")
                if verify(dest):
                    _log("\n完成。记忆系统下次启动会自动加载本地模型。")
                    return 0
                _log("\n文件已下载但验证未通过，换下一个源重试。")
        except KeyboardInterrupt:
            _log("\n已中断")
            return 130

    _log("\n所有下载源都失败。可手动下载后放到：")
    _log(f"  {dest}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
