#!/bin/bash
# 慕 — 启动脚本 (macOS / Linux)
# 首次运行会自动建虚拟环境并装依赖；已装好则直接启动。
cd "$(dirname "$0")"

PY=.venv/bin/python

if [ ! -x "$PY" ]; then
    echo
    echo "  未找到虚拟环境，正在创建..."
    python3 -m venv .venv || { echo "  ❌ 创建虚拟环境失败，请确认已安装 Python 3.11+"; exit 1; }
    echo
fi

if [ ! -f .venv/.deps_ok ]; then
    echo "  首次运行：安装依赖，可能需要几分钟..."
    "$PY" -m pip install -r requirements.txt || { echo "  ❌ 依赖安装失败，请检查网络或代理"; exit 1; }
    touch .venv/.deps_ok
    echo
fi

# 向量记忆：仅当模型目录随包存在时安装（sentence-transformers 会拉 torch，约 2GB）
if [ -f "models/bge-small-zh-v1.5/config.json" ] && [ ! -f .venv/.vector_ok ]; then
    echo "  检测到向量模型，安装语义记忆支持（会拉取 torch，约 2GB，仅一次）..."
    if "$PY" -m pip install -r requirements-vector.txt; then
        touch .venv/.vector_ok
        echo "  语义记忆已就绪。"
    else
        echo "  向量依赖安装失败，将以关键词记忆模式运行。"
    fi
    echo
fi

echo "  慕 — 启动中..."
echo

"$PY" main.py "$@"
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo
    echo "  程序已退出 (code: $EXIT_CODE)"
    echo
fi

exit $EXIT_CODE
