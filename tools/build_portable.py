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
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

MODEL_DIRNAME = "bge-small-zh-v1.5"

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


def write_quickstart(dest: Path, version: str) -> Path:
    """在包根写一份最短的上手说明（GitHub 上的 README 太长，解压时只想看怎么开）。"""
    path = dest / "启动说明.txt"
    path.write_text(
        f"""慕 v{version} — 一键启动版
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
        ,
        encoding="utf-8",
    )
    return path


def verify(dest: Path) -> list[str]:
    """发布包自检。返回问题列表，空表示通过。"""
    problems: list[str] = []

    for rel in REQUIRED_IN_PACKAGE:
        if not (dest / rel).exists():
            problems.append(f"缺少必需文件：{rel}")

    for rel in FORBIDDEN_IN_PACKAGE:
        target = dest / rel
        if target.exists():
            problems.append(f"不该出现的路径：{rel}")

    # 密钥兜底扫描（export_clean 已扫过，这里只查模型/说明文件之外的文本）
    secret = re.compile(r"\bsk-[A-Za-z0-9]{20,}")
    for path in dest.rglob("*"):
        if not path.is_file():
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
            problems.append(f"疑似密钥泄露：{path.relative_to(dest)}")

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
    parser.add_argument("--dest", default="", help="目标目录，默认 _export/muu-<version>-portable")
    parser.add_argument("--no-zip", action="store_true", help="只生成目录，不压 zip")
    parser.add_argument("--skip-export", action="store_true", help="复用已导出的 _export/muu-<version>")
    args = parser.parse_args(argv)

    root = project_root()
    version = read_version(root)
    source = root / "_export" / f"muu-{version}"
    dest = Path(args.dest) if args.dest else root / "_export" / f"muu-{version}-portable"
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
    quickstart = write_quickstart(dest, version)
    print(f"[portable] 已写启动说明：{quickstart.name}")

    problems = verify(dest)
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
