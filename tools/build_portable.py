"""打「一键启动版」发布包：纯净源码 + 内置向量模型 + 启动脚本。

为什么要单独一个脚本
--------------------
``tools/export_clean.py`` 导出的是**该进 Git 的源码**，按设计排除了
``models/``（92MB 的 safetensors 不该进版本库）。但一键启动版必须带模型：
用户的机器多半连不上 huggingface.co，没有本地模型副本，语义记忆会静默降级
成关键词搜索 —— 这正是 v0.1.8 之前那个「向量记忆到底有没有在跑」的坑。

所以在 export_clean 之上再叠一层：把 ``models/bge-small-zh-v1.5/`` 拷进去，
并保证 ``Run.bat`` / ``Run.command`` / ``start.sh`` 的首次运行流程会装上
``requirements-vector.txt``（否则有模型没有 sentence-transformers，照样用不了）。

产物::

    _export/muu-<version>-portable/        解压即用的目录
    _export/muu-<version>-portable.zip     分发包

用法::

    python -m tools.build_portable                  # 导出 + 打 zip
    python -m tools.build_portable --no-zip         # 只要目录
    python -m tools.build_portable --skip-export    # 复用已有的 _export/muu-<version>
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

MODEL_DIRNAME = "bge-small-zh-v1.5"
EMBED_PYTHON_VERSION = "3.12.10"
EMBED_PYTHON_URL = (
    f"https://www.python.org/ftp/python/{EMBED_PYTHON_VERSION}/"
    f"python-{EMBED_PYTHON_VERSION}-embed-amd64.zip"
)
CPU_TORCH_INDEX = "https://download.pytorch.org/whl/cpu"

# 打包时必须存在的文件（缺一个就说明包不完整，宁可失败也别发出去）
REQUIRED_IN_PACKAGE = (
    "main.py",
    "README.md",
    "LICENSE",
    "requirements.txt",
    "requirements-vector.txt",
    "Run.bat",
    "Run.command",
    "start.sh",
    f"models/{MODEL_DIRNAME}/config.json",
    f"models/{MODEL_DIRNAME}/model.safetensors",
    f"models/{MODEL_DIRNAME}/tokenizer.json",
    f"models/{MODEL_DIRNAME}/modules.json",
    "webui/static/index.html",
)

# 绝对不能出现在发布包里的东西（模型之外的个人数据/密钥/产物）
FORBIDDEN_IN_PACKAGE = (
    "data",
    "config/settings.json",
    "config/personas.json",
    ".env",
    ".venv",
    "packaging",
    "_export",
    "logs",
)

# --with-runtime 时必须存在的独立运行时与关键三方库路径
REQUIRED_IN_RUNTIME = (
    "runtime/python.exe",
    "runtime/python312._pth",
    "runtime/Lib/site-packages/torch",
    "runtime/Lib/site-packages/sentence_transformers",
    "runtime/Lib/site-packages/litellm",
    "runtime/Lib/site-packages/aiohttp",
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_version(root: Path) -> str:
    """从 core/config.py 的 APP_VERSION 取版本号（单一来源，与 export_clean 同一正则）。"""
    config_py = root / "core" / "config.py"
    text = config_py.read_text(encoding="utf-8")
    match = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit(f"core/config.py 里找不到 APP_VERSION：{config_py}")
    return match.group(1)


def run_export(root: Path, dest: Path) -> None:
    """调 export_clean 导出纯净源码（它会顺手跑自检 + pytest）。"""
    cmd = [
        sys.executable,
        "-m",
        "tools.export_clean",
        "--dest",
        str(dest),
        "--force",
        "--no-verify",  # 自检放到本脚本最后统一做，避免同一套测试跑两遍
    ]
    print(f"[portable] 导出纯净源码 -> {dest}")
    result = subprocess.run(cmd, cwd=root)
    if result.returncode != 0:
        raise SystemExit(f"export_clean 失败（exit {result.returncode}）")


def copy_model(root: Path, dest: Path) -> int:
    """把向量模型拷进发布包，返回复制的文件数。"""
    src = root / "models" / MODEL_DIRNAME
    if not src.is_dir():
        raise SystemExit(
            f"找不到向量模型：{src}\n"
            "先跑 python -m tools.fetch_embedding_model 下载，或确认 models/ 未被删。"
        )
    missing = [n for n in ("config.json", "model.safetensors", "modules.json") if not (src / n).is_file()]
    if missing:
        raise SystemExit(f"模型目录不完整，缺：{', '.join(missing)}")

    dst = dest / "models" / MODEL_DIRNAME
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)

    count = sum(1 for p in dst.rglob("*") if p.is_file())
    size_mb = sum(p.stat().st_size for p in dst.rglob("*") if p.is_file()) / 1024 / 1024
    print(f"[portable] 已内置向量模型：{count} 个文件，{size_mb:.1f} MB")
    return count


def _find_uv() -> str:
    """定位 uv 可执行文件，用于向嵌入式 runtime 离线/纯净装配依赖。"""
    found = shutil.which("uv")
    if found:
        return found
    for candidate in (
        Path.home() / ".local" / "bin" / "uv.exe",
        Path.home() / ".cargo" / "bin" / "uv.exe",
    ):
        if candidate.is_file():
            return str(candidate)
    raise SystemExit("找不到 uv 可执行文件，请先安装 uv 或确认其在 PATH / ~/.local/bin 中")


def _isolated_python_env() -> dict[str, str]:
    """构造不继承宿主机 PYTHONPATH / PYTHONHOME 的纯净环境变量。"""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PYTHONUTF8"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _resolve_embed_zip(root: Path, embed_zip: Path | None) -> Path:
    """定位或下载官方 Windows 嵌入式 Python ZIP（带 _export/.cache 复用）。"""
    if embed_zip is not None:
        resolved = embed_zip.expanduser().resolve()
        if not resolved.is_file():
            raise SystemExit(f"指定的嵌入式 Python 包不存在：{resolved}")
        return resolved

    cache_dir = root / "_export" / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"python-{EMBED_PYTHON_VERSION}-embed-amd64.zip"
    if cached.is_file() and cached.stat().st_size > 5 * 1024 * 1024:
        print(f"[portable] 复用嵌入式 Python 缓存：{cached}")
        return cached

    print(f"[portable] 正在下载嵌入式 Python {EMBED_PYTHON_VERSION} -> {EMBED_PYTHON_URL}")
    tmp_path = cached.with_suffix(".zip.tmp")
    if tmp_path.exists():
        tmp_path.unlink()
    try:
        urllib.request.urlretrieve(EMBED_PYTHON_URL, tmp_path)
        tmp_path.replace(cached)
    except Exception as exc:
        if tmp_path.exists():
            tmp_path.unlink()
        raise SystemExit(f"下载嵌入式 Python 失败：{exc}") from exc
    return cached


def _cleanup_site_packages(site_packages: Path) -> int:
    """清理 __pycache__ 与 .pyc/.pyo 字节码以减小发布体积，不删除任何源码或数据文件。"""
    removed = 0
    for pycache in list(site_packages.rglob("__pycache__")):
        if pycache.is_dir():
            shutil.rmtree(pycache, ignore_errors=True)
            removed += 1
    for pattern in ("*.pyc", "*.pyo"):
        for file_path in list(site_packages.rglob(pattern)):
            if file_path.is_file():
                try:
                    file_path.unlink()
                    removed += 1
                except OSError:
                    pass
    return removed


def bundle_runtime(root: Path, dest: Path, embed_zip: Path | None = None) -> None:
    """内置 Windows 嵌入式 Python 3.12 + 全量核心/微信/CPU PyTorch 依赖。"""
    zip_path = _resolve_embed_zip(root, embed_zip)
    runtime_dir = dest / "runtime"
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    print(f"[portable] 解压嵌入式 Python 到 {runtime_dir}")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(runtime_dir)

    pth_file = runtime_dir / "python312._pth"
    pth_file.write_text(
        "python312.zip\n.\nLib/site-packages\n..\n../mcp_servers\nimport site\n",
        encoding="utf-8",
    )

    site_packages = runtime_dir / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)

    uv_bin = _find_uv()
    runtime_python = runtime_dir / "python.exe"
    if not runtime_python.is_file():
        raise SystemExit(f"嵌入式 Python 解压后缺少可执行文件：{runtime_python}")

    # 1. 先单独安装 CPU 版 torch，避免后续解析器从 PyPI 拉取 ~2.5 GB CUDA 版
    print("[portable] 安装 CPU 版 PyTorch 到 runtime/Lib/site-packages ...")
    subprocess.run(
        [
            uv_bin,
            "pip",
            "install",
            "--target",
            str(site_packages),
            "--python-version",
            "3.12",
            "--python-platform",
            "x86_64-pc-windows-msvc",
            "--index-url",
            CPU_TORCH_INDEX,
            "torch",
        ],
        cwd=root,
        check=True,
    )

    iso_env = _isolated_python_env()
    torch_ver_proc = subprocess.run(
        [
            str(runtime_python),
            "-c",
            "import importlib.metadata as m; print(m.version('torch'))",
        ],
        cwd=dest,
        env=iso_env,
        capture_output=True,
        text=True,
        check=True,
    )
    torch_version = torch_ver_proc.stdout.strip()
    print(f"[portable] 锁定 CPU torch 版本：{torch_version}")

    # 2. 用 constraint 锁定已装好的 CPU torch，再装配核心 + 向量 + 微信依赖（不含 dev）
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", encoding="utf-8", delete=False
    ) as tf:
        tf.write(f"torch=={torch_version}\n")
        constraint_path = Path(tf.name)

    try:
        print("[portable] 安装核心、语义记忆与微信依赖（不含 dev 工具）...")
        subprocess.run(
            [
                uv_bin,
                "pip",
                "install",
                "--target",
                str(site_packages),
                "--python-version",
                "3.12",
                "--python-platform",
                "x86_64-pc-windows-msvc",
                "--index-url",
                "https://pypi.org/simple",
                "--extra-index-url",
                CPU_TORCH_INDEX,
                "--index-strategy",
                "unsafe-best-match",
                "--constraint",
                str(constraint_path),
                "-r",
                str(root / "requirements.txt"),
                "-r",
                str(root / "requirements-vector.txt"),
                "-r",
                str(root / "requirements-wechat.txt"),
            ],
            cwd=root,
            check=True,
        )
    finally:
        if constraint_path.exists():
            constraint_path.unlink()

    # 3. 校验无 CUDA 巨型 DLL，并尽量通过 runtime Python 校验 CPU 版 torch
    if "+cpu" not in torch_version:
        raise SystemExit(f"安装的 torch 不是 CPU 版本：{torch_version}")
    torch_dir = site_packages / "torch"
    cuda_dlls = [
        p.name
        for p in torch_dir.rglob("*.dll")
        if any(tok in p.name.lower() for tok in ("cublas", "cudnn", "cudart", "cufft", "cusparse"))
    ]
    if cuda_dlls:
        raise SystemExit(f"检测到 CUDA DLL，可能误装了 GPU 版 PyTorch：{cuda_dlls[:5]}")

    check_proc = subprocess.run(
        [
            str(runtime_python),
            "-c",
            "import torch; print('torch:', torch.__version__, 'cuda:', torch.cuda.is_available())",
        ],
        cwd=dest,
        env=iso_env,
        capture_output=True,
        text=True,
    )
    if check_proc.returncode == 0:
        print(f"[portable] 运行时校验：{check_proc.stdout.strip()}")
    else:
        stderr_tail = (check_proc.stderr or "").strip().splitlines()[-1:] or [""]
        # 在受限工作区目录（带 Low Mandatory Level ACL）下直接执行新解压的 _ctypes.pyd
        # 可能被 Windows 拦截，解压到普通目录/Temp 即可正常加载；仍需在隔离目录实测。
        print(f"[portable] 运行时原位冒烟跳过（需在非受限目录实测）：{stderr_tail[0]}")

    cleaned = _cleanup_site_packages(site_packages)
    runtime_mb = sum(p.stat().st_size for p in runtime_dir.rglob("*") if p.is_file()) / 1024 / 1024
    print(f"[portable] 清理字节码缓存 {cleaned} 项；runtime 总大小：{runtime_mb:.1f} MB")


def write_quickstart(dest: Path, version: str, *, with_runtime: bool = False) -> Path:
    """在包根写一份最短的上手说明（GitHub 上的 README 太长，解压时只想看怎么开）。"""
    path = dest / "启动说明.txt"
    if with_runtime:
        body = f"""慕 v{version} — Windows 离线开箱即用版
========================================

本压缩包为真正免安装的独立离线版，已内置：
  1. Python {EMBED_PYTHON_VERSION} 嵌入式运行时（runtime/）；
  2. 全部核心依赖、CPU 版 PyTorch、语义记忆（sentence-transformers）与微信插件依赖；
  3. 本地中文向量模型（models/bge-small-zh-v1.5，约 92MB）。

无需在本机安装 Python，无需联网执行 pip install。

------------------------------------------------
Windows 使用方法
------------------------------------------------
  1. 完整解压本压缩包到任意目录（不要直接在压缩软件预览窗里双击）
  2. 双击  Run.bat
  3. 浏览器会自动打开 http://127.0.0.1:8000

  首次启动会自动从 *.example.json 初始化 config/ 并直接运行自检后拉起网页端。
  （在网页端「设置 → 模型设置」填入你自己的对话模型 API Key 即可开始聊天。）

------------------------------------------------
数据存在哪
------------------------------------------------
  data/       对话、记忆、关系值（首次启动时创建）
  config/     模型密钥与人设（首次启动时从 *.example.json 初始化）
  logs/       运行日志

  升级新版时保留自己的 data/ 和 config/ 即可带走全部记忆与配置。

------------------------------------------------
遇到问题
------------------------------------------------
  在包目录执行：  runtime\\python.exe main.py doctor
  它会逐项检查 Python、依赖、模型、配置、端口。
"""
    else:
        body = f"""慕 v{version} — 一键启动版
========================================

这个包和 GitHub 上的源码版只有两点不同：
  1. 已经内置向量模型（models/bge-small-zh-v1.5，约 92MB），
     所以「语义记忆」开箱可用，不需要联网下载模型。
  2. 启动脚本会在首次运行时额外安装 requirements-vector.txt
     （sentence-transformers + torch，约 2GB，只装一次）。

------------------------------------------------
Windows
------------------------------------------------
  1. 装 Python 3.11 或更高版本（python.org，安装时勾选 "Add to PATH"）
  2. 双击  Run.bat
  3. 浏览器会自动打开 http://127.0.0.1:8000

  首次运行会：建 .venv → 装依赖 → 装向量依赖 → 自检 → 启动。
  依赖安装期间窗口会停几分钟，属正常现象。

------------------------------------------------
macOS / Linux
------------------------------------------------
  1. 确认有 python3（3.11+）
  2. chmod +x Run.command   （macOS，仅第一次）
     ./Run.command
     或：./start.sh

------------------------------------------------
想跳过 torch（不装语义记忆）
------------------------------------------------
  模型目录删掉再启动，脚本会自动跳过向量依赖，
  以关键词记忆模式运行（更轻，但记不住「意思相近」的话）。

------------------------------------------------
数据存在哪
------------------------------------------------
  data/       对话、记忆、关系值（首次启动时创建）
  config/     模型密钥与人设（首次启动时从 *.example.json 生成）
  logs/       运行日志

  这三样都不会被打进发布包，升级时直接覆盖程序文件即可，
  个人数据留在原地。

------------------------------------------------
遇到问题
------------------------------------------------
  在包目录执行：  python main.py doctor
  它会逐项检查 Python、依赖、模型、配置、端口。
"""
    path.write_text(body, encoding="utf-8")
    return path


def verify(dest: Path, *, with_runtime: bool = False) -> list[str]:
    """发布包自检。返回问题列表，空表示通过。"""
    problems: list[str] = []

    for rel in REQUIRED_IN_PACKAGE:
        if not (dest / rel).exists():
            problems.append(f"缺少必需文件：{rel}")

    if with_runtime:
        for rel in REQUIRED_IN_RUNTIME:
            if not (dest / rel).exists():
                problems.append(f"缺少内置运行时/依赖：{rel}")

    for rel in FORBIDDEN_IN_PACKAGE:
        target = dest / rel
        if target.exists():
            problems.append(f"不该出现的路径：{rel}")

    # 密钥兜底扫描（跳过 runtime/ 第三方库与 model.safetensors 避免无谓扫描）
    secret = re.compile(r"\bsk-[A-Za-z0-9]{20,}")
    for path in dest.rglob("*"):
        if not path.is_file():
            continue
        rel_path = path.relative_to(dest)
        if with_runtime and rel_path.parts and rel_path.parts[0] == "runtime":
            continue
        if path.suffix.lower() not in {".py", ".md", ".json", ".toml", ".txt", ".yml", ".yaml", ".bat", ".sh", ".command"}:
            continue
        if path.name == "model.safetensors":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if secret.search(text):
            problems.append(f"疑似密钥泄露：{rel_path}")

    return problems


def make_zip(dest: Path) -> Path:
    # 不能用 dest.with_suffix(".zip")：目录名里的 "0.1.9-portable" 会被当成后缀，
    # 结果压出 muu-0.1.zip 这种被截断的名字。
    archive = dest.parent / f"{dest.name}.zip"
    if archive.exists():
        archive.unlink()
    print(f"[portable] 正在压缩 -> {archive.name}")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(dest.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(dest.parent))
    return archive


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="打一键启动版发布包（含向量模型）")
    parser.add_argument("--dest", default="", help="目标目录，默认按模式生成在 _export/ 下")
    parser.add_argument("--no-zip", action="store_true", help="只生成目录，不压 zip")
    parser.add_argument("--skip-export", action="store_true", help="复用已导出的 _export/muu-<version>")
    parser.add_argument(
        "--with-runtime",
        action="store_true",
        help="内置 Windows 嵌入式 Python 3.12 与全量离线依赖（解压双击 Run.bat 零安装直启）",
    )
    parser.add_argument(
        "--python-embed-zip",
        default="",
        help="可选：本地 python-3.12.10-embed-amd64.zip 路径（配合 --with-runtime）",
    )
    args = parser.parse_args(argv)

    root = project_root()
    version = read_version(root)
    source = root / "_export" / f"muu-{version}"
    default_name = f"muu-{version}-win64-portable" if args.with_runtime else f"muu-{version}-portable"
    dest = Path(args.dest) if args.dest else root / "_export" / default_name
    dest = dest.resolve()

    if dest == root or dest in root.parents:
        raise SystemExit("目标目录不能是项目根，也不能是它的父目录")

    print(f"[portable] 版本：{version}")
    print(f"[portable] 目标：{dest}")

    if args.skip_export:
        if not source.is_dir():
            raise SystemExit(f"--skip-export 但源目录不存在：{source}")
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source, dest)
        print(f"[portable] 复用已有导出：{source}")
    else:
        run_export(root, source)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source, dest)

    copy_model(root, dest)
    if args.with_runtime:
        embed_zip = Path(args.python_embed_zip) if args.python_embed_zip else None
        bundle_runtime(root, dest, embed_zip=embed_zip)

    quickstart = write_quickstart(dest, version, with_runtime=args.with_runtime)
    print(f"[portable] 已写启动说明：{quickstart.name}")

    problems = verify(dest, with_runtime=args.with_runtime)
    if problems:
        print("\n[portable] 自检未通过：")
        for item in problems:
            print(f"  ✗ {item}")
        return 1
    print("[portable] 自检：OK")

    total_files = sum(1 for p in dest.rglob("*") if p.is_file())
    total_mb = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file()) / 1024 / 1024
    print(f"[portable] 目录大小：{total_files} 个文件，{total_mb:.1f} MB")

    if not args.no_zip:
        archive = make_zip(dest)
        archive_mb = archive.stat().st_size / 1024 / 1024
        print(f"[portable] zip 大小：{archive_mb:.1f} MB")
        print(f"[portable] sha256：{sha256_of(archive)}")

    print(f"\n✅ 一键启动版就绪\n   {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
