#!/usr/bin/env bash
# ================================================================
#  Taskbar Todo 打包脚本
#  从 TaskbarTodo.spec 打包为单文件、无控制台的可执行程序。
#  （spec 内已处理 conda 多环境下 tcl/tk DLL 版本冲突问题）
# ================================================================

set -euo pipefail

# ---- 可选：切换 conda 环境（如需指定 Python 解释器，取消注释修改） ----
# CONDA_ENV="C:/Users/19360/.conda/envs/rknn"
# conda run --no-capture-output -p "$CONDA_ENV" pyinstaller --noconfirm --clean TaskbarTodo.spec
# exit 0

pyinstaller --noconfirm --clean TaskbarTodo.spec

echo "OK 打包完成！输出位于 dist/TaskbarTodo.exe"
