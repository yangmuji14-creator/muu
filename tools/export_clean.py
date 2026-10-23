"""导出一份「纯净版」源码目录。

为什么需要它：当前工作目录同时是**开发环境 + 测试环境 + 运行环境**，
`data/`、`config/settings.json`、`models/`、`packaging/dist`、各种 `*.bak-*`
都躺在里面。直接 zip 整个目录上传会带上个人聊天记录、API 密钥、92MB 模型
和 147MB 的 EXE 产物。

这个脚本只复制**该进 Git 的东西**：

1. 用 `git ls-files -c -o --exclude-standard` 拿「已跟踪 + 未跟踪但未被忽略」
   的路径 —— 也就是 `git add -A` 会加进去的那批。被 `.gitignore` 挡掉的
   密钥/数据/模型/打包产物天然不在里面。
2. 再过一遍显式黑名单（`.env`、`*.bak-*`、`*.db`、`secrets.dpapi` 等）兜底。
3. 只复制磁盘上真实存在的文件（跳过已删除但仍在索引里的旧路径）。
4. 复制完做自检：目录结构、密钥扫描、`import core.app`、可选跑 pytest。

用法::

    python -m tools.export_clean                    # 默认导到 _export/muu-<version>/
    python -m tools.export_clean --dest D:/tmp/muu  # 指定目录
    python -m tools.export_clean --force            # 目标非空时先清空
    python -m tools.export_clean --no-verify        # 跳过自检
    python -m tools.export_clean --zip              # 额外打 zip
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# ── 显式黑名单：即使 .gitignore 漏了，这些也绝不进纯净版 ──
DENY_NAME_PATTERNS = (
    ".env",
    "*.env.local",
    "*.bak",
    "*.bak-*",
    "*.db",
    "*.db-wal",
    "*.db-shm",
    "*.log",
    "*.pyc",
    "*.pyo",
    "secrets.dpapi",
    "*.dpapi",
    ".DS_Store",
    "Thumbs.db",
)

DENY_PATH_PREFIXES = (
    "data/",
    "logs/",
    "models/",
    "packaging/",
    ".venv/",
    "venv/",
    "node_modules/",
    "__pycache__/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".git/",
    ".workbuddy/",
    ".workbuddy-ai/",
    "_export/",
    "pytest-of-",
    "torchinductor_",
)

# 敏感的配置文件名（这些属于用户个人配置，仓库里只留 *.example.json）
DENY_FILES = {
    "config/settings.json",
    "config/personas.json",
    "config/tts_providers.json",
}

# 密钥扫描：形如 sk-xxxxx / Bearer xxxxx 的长串
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
)

# 纯净版必须存在的路径（缺一个就说明导出不完整）
REQUIRED_PATHS = (
    "main.py",
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "core/config.py",
    "core/app.py",
    "webui/server.py",
    "webui/static/index.html",
    "webui/frontend/package.json",
    "mcp_servers",
    "adapters",
    "tools",
    "tests",
    "config/settings.example.json",
    "config/personas.example.json",
)

TEXT_SUFFIXES = {
    ".py", ".md", ".json", ".toml", ".txt", ".yml", ".yaml", ".cfg",
    ".ini", ".js", ".ts", ".svelte", ".css", ".html", ".sh", ".spec",
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_version(root: Path) -> str:
    """从 core/config.py 的 APP_VERSION 取版本号（单一来源）。"""
    config_py = root / "core" / "config.py"
    try:
        text = config_py.read_text(encoding="utf-8")
    except OSError:
        return "0.0.0"
    match = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else "0.0.0"


def _is_denied(rel: str) -> bool:
    posix = rel.replace("\\", "/")
    if posix in DENY_FILES:
        return True
    for prefix in DENY_PATH_PREFIXES:
        if posix.startswith(prefix) or f"/{prefix}" in posix:
            return True
    name = posix.rsplit("/", 1)[-1]
    for pattern in DENY_NAME_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return True
    # tests/ 里的 __pycache__ 已在上面按前缀挡掉；这里只挡目录名本身
    return False


def collect_files(root: Path) -> tuple[list[str], list[str]]:
    """返回 (要复制的相对路径, 被挡掉的相对路径)。"""
    try:
        raw = subprocess.run(
            ["git", "ls-files", "-c", "-o", "--exclude-standard", "-z"],
            cwd=root,
            capture_output=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise SystemExit(f"git ls-files 失败：{exc}") from exc

    keep: list[str] = []
    dropped: list[str] = []
    for chunk in raw.split(b"\x00"):
        if not chunk:
            continue
        rel = chunk.decode("utf-8", "surrogateescape").replace("\\", "/")
        if _is_denied(rel):
            dropped.append(rel)
            continue
        if not (root / rel).is_file():
            # 索引里有、磁盘上已删（比如旧的前端哈希产物）
            dropped.append(f"{rel} (missing)")
            continue
        keep.append(rel)
    keep.sort()
    return keep, dropped


def copy_files(root: Path, dest: Path, files: list[str]) -> None:
    for rel in files:
        src = root / rel
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)


def scan_secrets(dest: Path) -> list[str]:
    """扫纯净版里的明文密钥。返回命中描述列表（空 = 干净）。"""
    hits: list[str] = []
    for path in dest.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                token = match.group(0)
                hits.append(f"{path.relative_to(dest)}: {token[:8]}…({len(token)} 字符)")
    return hits


def verify_structure(dest: Path) -> list[str]:
    missing = [p for p in REQUIRED_PATHS if not (dest / p).exists()]
    return [f"缺少必需路径：{p}" for p in missing]


def verify_import(dest: Path) -> list[str]:
    """在纯净版目录里 import 主链路，确认没有引用已删模块。"""
    code = "import core.app, webui.server, core.chat.pipeline, tools"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=dest,
        capture_output=True,
        text=True,
        env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
    )
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-8:]
        return ["import 自检失败："] + [f"  {line}" for line in tail]
    return []


def verify_tests(dest: Path) -> list[str]:
    # basetemp 指到系统临时目录：否则 pytest 的 tmp_path 会落在导出目录里，
    # 留下一堆 pytest-of-<user>/ 和里面的 .db 文件。
    basetemp = Path(tempfile.mkdtemp(prefix="muu-verify-"))
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q", "--no-header",
            "-p", "no:cacheprovider", f"--basetemp={basetemp}",
        ],
        cwd=dest,
        capture_output=True,
        text=True,
        env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
    )
    shutil.rmtree(basetemp, ignore_errors=True)
    if result.returncode != 0:
        tail = (result.stdout or result.stderr).strip().splitlines()[-12:]
        return ["pytest 失败："] + [f"  {line}" for line in tail]
    summary = (result.stdout or "").strip().splitlines()[-1:] or ["?"]
    print(f"  pytest: {summary[0]}")
    return []


def scrub_artifacts(dest: Path) -> list[str]:
    """清掉验证过程在导出目录里留下的缓存/临时产物。返回清理掉的相对路径。"""
    removed: list[str] = []
    patterns = ("pytest-of-*", "torchinductor_*", "__pycache__", ".pytest_cache")
    for pattern in patterns:
        for path in list(dest.rglob(pattern)):
            if path.is_dir():
                removed.append(str(path.relative_to(dest)) + "/")
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_file():
                removed.append(str(path.relative_to(dest)))
                path.unlink(missing_ok=True)
    return removed


def make_zip(dest: Path) -> Path:
    archive = dest.with_suffix(".zip")
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(dest.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(dest.parent))
    return archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="导出纯净版源码目录（只含该进 Git 的文件）"
    )
    parser.add_argument("--dest", default="", help="目标目录，默认 _export/muu-<version>")
    parser.add_argument("--force", action="store_true", help="目标非空时先清空")
    parser.add_argument("--no-verify", action="store_true", help="跳过自检")
    parser.add_argument("--zip", action="store_true", help="额外打一个 zip")
    args = parser.parse_args(argv)

    root = project_root()
    version = read_version(root)
    dest = Path(args.dest) if args.dest else root / "_export" / f"muu-{version}"
    dest = dest.resolve()

    if dest == root or dest in root.parents:
        raise SystemExit("目标目录不能是项目根，也不能是它的父目录")

    print(f"源目录：{root}")
    print(f"目标  ：{dest}")

    files, dropped = collect_files(root)
    print(f"待复制：{len(files)} 个文件")

    if dest.exists():
        if not args.force:
            raise SystemExit(f"目标已存在：{dest}\n加 --force 覆盖，或换 --dest")
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    copy_files(root, dest, files)

    total = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
    print(f"已写入：{total / 1024 / 1024:.2f} MB")

    if dropped:
        print(f"\n被挡掉 {len(dropped)} 项（前 12 条）：")
        for rel in dropped[:12]:
            print(f"  - {rel}")
        if len(dropped) > 12:
            print(f"  … 另有 {len(dropped) - 12} 条")

    if args.no_verify:
        print("\n（已跳过自检）")
        if args.zip:
            print(f"zip：{make_zip(dest)}")
        return 0

    print("\n自检：")
    problems: list[str] = []

    structure_issues = verify_structure(dest)
    problems += structure_issues
    print(f"  结构：{'OK' if not structure_issues else '有问题'}")

    secret_hits = scan_secrets(dest)
    if secret_hits:
        print(f"  密钥扫描：发现 {len(secret_hits)} 处")
        problems += [f"明文密钥：{h}" for h in secret_hits]
    else:
        print("  密钥扫描：干净")

    import_issues = verify_import(dest)
    problems += import_issues
    print(f"  import：{'OK' if not import_issues else '失败'}")

    test_issues = verify_tests(dest)
    problems += test_issues

    scrubbed = scrub_artifacts(dest)
    if scrubbed:
        print(f"  清理临时产物：{len(scrubbed)} 项")

    if problems:
        print("\n❌ 自检未通过：")
        for item in problems:
            print(f"  {item}")
        return 1

    print("\n✅ 纯净版就绪")
    print(f"   {dest}")
    if args.zip:
        print(f"   {make_zip(dest)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
