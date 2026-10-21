"""慕 — 本地优先的 AI 伴侣

集成情绪状态机、人格引擎、工具调用、向量记忆等完整功能。

最简单的用法：
    python main.py 启动
    
或者用命令行：
    python main.py setup     — 首次运行，配置模型+人设
    python main.py           — 启动聊天（自动检测微信配置）
    python main.py wechat    — 首次配置微信
    python main.py import-skill <路径>  — 导入 ex-skill 人设文件
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Embedded Python distributions can omit the launched script's directory from
# sys.path. Register the resource root explicitly so packaged layouts behave
# like a normal source checkout on every platform.
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


# ========== 自动切换虚拟环境（必须在第三方 import 之前）==========
# 必须在 import dotenv/loguru 等第三方依赖之前调用，否则系统 Python
# 加载 main.py 时会因找不到依赖而崩溃，永远到不了 main() 里的调用。
# 注意：Windows 上 os.execv 会 spawn 新进程并让原进程退出，导致 cmd
# 提示符立刻回来、新进程 stdin 与终端断开，交互式 input() 失效。
# 因此 Windows 下必须用 subprocess.run 同步等待子进程结束再退出。

def _ensure_venv():
    """检测并使用 .venv 虚拟环境（如有）。

    必须在 import dotenv/loguru 等第三方依赖之前调用，
    否则系统 Python 加载 main.py 时会因找不到依赖而崩溃，
    永远到不了 main() 里的 _ensure_venv() 调用。

    注意：Windows 上 os.execv 行为与 Unix 不同 —— 它会 spawn 新进程
    然后让原进程退出，导致 cmd 提示符立刻回来、新进程的 stdin 与
    cmd 终端断开，交互式输入（input()）会被 cmd 当成命令解析。因此
    Windows 下必须用 subprocess.run 同步等待子进程结束，再退出。
    """
    if sys.prefix != sys.base_prefix:
        return  # 已在 venv 中

    venv_dir = Path(__file__).parent / ".venv"
    if not venv_dir.exists():
        return  # 没有 .venv，用系统 Python

    if sys.platform == "win32":
        venv_python = venv_dir / "Scripts" / "python.exe"
    else:
        venv_python = venv_dir / "bin" / "python"

    if not venv_python.exists():
        return

    # 用 venv 的 Python 重新执行本脚本
    print("\n  🔄 自动切换到虚拟环境...\n")

    if sys.platform == "win32":
        # Windows: os.execv 会让原进程立即退出，新进程的 stdin 与
        # cmd 终端断开，交互式 input() 失效。必须用 subprocess 同步等待。
        import subprocess
        result = subprocess.run([str(venv_python)] + sys.argv)
        sys.exit(result.returncode)
    else:
        # Unix: os.execv 真正替换当前进程，stdio 完整继承
        os.execv(str(venv_python), [str(venv_python)] + sys.argv)


_ensure_venv()

from dotenv import load_dotenv
from loguru import logger
from core.runtime.paths import resolve_runtime_paths

_RUNTIME_PATHS = resolve_runtime_paths()
load_dotenv(_RUNTIME_PATHS.home_dir / ".env")

from core.config import ROOT, RESOURCE_DIR, CONFIG_DIR, DATA_DIR, LOGS_DIR, load_advanced
from core.app import AppComponents, create_components


def _apply_queued_restore() -> None:
    """Apply Web-scheduled restores before any component opens a database."""
    from core.storage.backup import BackupValidationError, apply_pending_restore

    try:
        result = apply_pending_restore(DATA_DIR, CONFIG_DIR)
    except (BackupValidationError, OSError, ValueError) as e:
        logger.error(f"待恢复备份无效，已保留以便排查：{e}")
        print("\n  ⚠️ 数据恢复未完成，原数据未被替换。请重新选择备份。\n")
        return
    if result:
        print(f"\n  ✅ 数据恢复完成：{len(result['restored'])} 个文件")
        print(f"  恢复前安全备份：{result['safety_backup']}\n")

# 日志
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level:8}</level> | {message}")
LOGS_DIR.mkdir(parents=True, exist_ok=True)
logger.add(str(LOGS_DIR / "app.log"), rotation="10 MB", retention="7 days", level="DEBUG")

ADVANCED = load_advanced()


# ========== 依赖检查 ==========

DEPENDENCIES = [
    ("dotenv", "python-dotenv"),
    ("loguru", "loguru"),
    ("pydantic", "pydantic"),
    ("litellm", "litellm"),
    ("numpy", "numpy"),
]


def _check_dependencies() -> bool:
    """启动前检查关键依赖是否已安装，缺失则给出友好提示"""
    missing = []
    for mod_name, pkg_name in DEPENDENCIES:
        try:
            __import__(mod_name)
        except ImportError:
            missing.append(pkg_name)

    if missing:
        print()
        print("=" * 50)
        print("  ❌ 缺少依赖包")
        print("=" * 50)
        print()
        print(f"  请先安装依赖：")
        print()
        print(f"    python install.py")
        print()
        if len(missing) <= 3:
            print(f"  缺失：{'、'.join(missing)}")
        print()
        input("  按回车键退出...")
        return False
    return True


# ========== 环境自检（doctor）==========

def _doctor() -> int:
    """环境自检：非专业用户一键排查。返回 0=通过，1=有阻塞问题。

    覆盖：Python 版本 / 依赖 / .env / 数据目录可写 / 端口占用 / 模型配置。
    """
    import socket
    import sys

    problems: list[str] = []
    warnings: list[str] = []
    ok: list[str] = []

    # 1. Python 版本
    v = sys.version_info
    if v >= (3, 11):
        ok.append(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        problems.append(
            f"Python 版本过旧（{v.major}.{v.minor}），需要 3.11+，"
            "去 python.org 下载安装（勾选 Add to PATH）"
        )

    # 2. 关键依赖
    missing = []
    for mod_name, pkg_name in DEPENDENCIES:
        try:
            __import__(mod_name)
        except ImportError:
            missing.append(pkg_name)
    if missing:
        problems.append(f"缺少依赖：{'、'.join(missing)}\n       修复：.venv\\Scripts\\python.exe -m pip install -r requirements.txt")
    else:
        ok.append(f"依赖完整（{len(DEPENDENCIES)} 个关键包）")

    # 3. .env
    if (ROOT / ".env").exists():
        ok.append(".env 配置文件存在")
    else:
        warnings.append("还没有 .env 配置文件 —— 首次使用请先运行：python main.py setup")

    # 4. 数据目录可写
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe = DATA_DIR / ".doctor_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        ok.append("数据目录可写")
    except OSError as e:
        problems.append(f"数据目录不可写（{DATA_DIR}）：{e}")

    # 5. 8000 端口占用
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        occupied = sock.connect_ex(("127.0.0.1", 8000)) == 0
    finally:
        sock.close()
    if occupied:
        warnings.append(
            "8000 端口已有服务在监听 —— 可能旧进程没退干净，"
            "网页能打开就不用管；打不开就重启电脑或结束旧的 python 进程"
        )
    else:
        ok.append("8000 端口空闲")

    # 6. 模型配置
    try:
        settings = json.loads((CONFIG_DIR / "settings.json").read_text(encoding="utf-8"))
        if settings.get("models"):
            ok.append(f"模型已配置（{len(settings['models'])} 个提供商）")
        else:
            warnings.append("尚未配置对话模型 —— 打开网页端 → 设置 → 模型设置，选服务商填 Key 即可")
    except Exception as e:
        warnings.append(f"settings.json 读取失败：{e}")

    print()
    print("=" * 52)
    print("  慕 · 环境自检")
    print("=" * 52)
    for item in ok:
        print(f"  ✅ {item}")
    for item in warnings:
        print(f"  ⚠️  {item}")
    for item in problems:
        print(f"  ❌ {item}")
    print()

    if problems:
        print("  有阻塞问题需要先解决，按上面 ❌ 项的提示修复后重试。\n")
        return 1
    print("  环境没问题，可以直接启动（python main.py web）。\n")
    return 0


# ========== 微信配置检测 ==========

def _has_wechat_config() -> bool:
    """检查是否已配置微信且允许自动启动"""
    credentials_file = DATA_DIR / "credentials" / "wechat.json"
    if not credentials_file.exists():
        return False

    # 检查 settings.json 中的 auto_start 配置（默认允许自启）
    settings_path = CONFIG_DIR / "settings.json"
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            adapters = settings.get("advanced", {}).get("adapters", {})
            wechat = adapters.get("wechat", {})
            # auto_start 未设置时默认允许，兼容旧版无此配置的情况
            if wechat.get("auto_start") is False:
                return False
        except Exception:
            pass

    return True


# ========== CLI 入口 ==========

def main():
    import argparse

    parser = argparse.ArgumentParser(description="慕")
    parser.add_argument(
        "command", nargs="?", default="run",
        choices=["setup", "run", "web", "wechat", "restore", "doctor"],
        help="setup=配置向导, run=启动（默认）, web=网页端, wechat=配置微信, restore=恢复备份, doctor=环境自检",
    )
    parser.add_argument(
        "path", nargs="?",
        help="restore 时的备份文件路径",
    )
    args = parser.parse_args()

    if args.command == "doctor":
        sys.exit(_doctor())

    if args.command == "setup":
        from setup_wizard import run_setup
        try:
            run_setup()
        except KeyboardInterrupt:
            print("\n\n  设置已取消\n")
        return

    if args.command == "web":
        _run_web()
        return

    if args.command == "wechat":
        _setup_wechat()
        return

    if args.command == "restore":
        _restore_backup_cli(args.path)
        return

    # ── run（默认） ──
    if not _check_dependencies():
        return

    if not (ROOT / ".env").exists():
        print("\n" + "=" * 40)
        print("  首次使用，请先运行设置向导")
        print("=" * 40)
        print("\n  命令: python main.py setup")
        print("\n  按回车键退出...")
        try:
            input()
        except (EOFError, OSError):
            pass
        return

    logger.info("慕 启动中...")
    _apply_queued_restore()
    app: AppComponents = create_components()

    # 智能启动：如果已配置微信，自动启动微信+CLI
    if _has_wechat_config():
        print("\n  检测到微信配置，同时启动微信 Bot + 本地聊天")
        print("  微信消息和本地消息都会由同一个 AI 处理")
        print("  按 Ctrl+C 退出\n")
        from core.app import run_with_adapters
        try:
            asyncio.run(run_with_adapters(app, ["wechat"]))
        except KeyboardInterrupt:
            print()
            logger.info("拜拜~")
    else:
        print("\n  本地聊天模式")
        print("  输入 /help 查看命令，输入 /quit 退出\n")
        try:
            asyncio.run(app.handler.run())
        except KeyboardInterrupt:
            print()
            logger.info("拜拜~")


# ========== 网页端 ==========

def _run_web():
    """启动网页端（对话 + 参数配置）"""
    if not _check_dependencies():
        return

    try:
        import aiohttp  # noqa: F401
    except ImportError:
        print("\n  ❌ 网页端需要 aiohttp，请先安装：")
        print("    pip install aiohttp\n")
        return

    logger.info("网页端启动中...")
    _apply_queued_restore()
    app: AppComponents = create_components()

    from webui.server import run_web
    try:
        host = os.getenv("MU_WEB_HOST") or os.getenv("CC_WEB_HOST", "127.0.0.1")
        port = int(os.getenv("MU_WEB_PORT") or os.getenv("CC_WEB_PORT", "8000"))
        asyncio.run(run_web(app, host=host, port=port))
    except KeyboardInterrupt:
        print()
        logger.info("网页端已停止")


# ========== 微信配置 ==========

def _setup_wechat():
    """配置微信 — 委托给 setup_wechat.py 统一入口"""
    from setup_wechat import run_wechat_setup
    run_wechat_setup()


def _restore_backup_cli(path_arg: str | None):
    """Restore a full backup before application components open database files."""
    if not path_arg:
        print("\n  用法: python main.py restore <备份文件.zip>\n")
        return
    from core.storage.backup import BackupValidationError, restore_backup
    try:
        result = restore_backup(Path(path_arg), DATA_DIR, CONFIG_DIR)
        print(f"\n  恢复完成：{len(result['restored'])} 个文件")
        print(f"  恢复前备份：{result['safety_backup']}")
        print("  请重新启动慕。\n")
    except (BackupValidationError, OSError) as e:
        print(f"\n  恢复失败：{e}\n")


if __name__ == "__main__":
    main()
