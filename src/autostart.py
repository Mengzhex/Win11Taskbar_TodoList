# -*- coding: utf-8 -*-
"""
开机自启 — 通过注册表 Run 键实现
=================================

写入 HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run，
用户级、无需管理员权限。注册表是「是否自启」的唯一真相来源。

  - 打包成 exe 运行时：启动命令 = exe 自身路径
  - 源码运行时：启动命令 = pythonw.exe run.py（pythonw 无控制台窗口）
"""

from __future__ import annotations

import sys
import winreg
from pathlib import Path

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_NAME = "TaskbarTodo"


def _launch_command() -> str:
    """返回写入注册表的启动命令行（已加引号）。"""
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后的 exe
        return f'"{sys.executable}"'
    # 源码运行：优先用 pythonw（无黑框），指向项目根的 run.py
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    py = str(pyw) if pyw.exists() else str(exe)
    run_py = Path(__file__).resolve().parent.parent / "run.py"
    return f'"{py}" "{run_py}"'


def is_enabled() -> bool:
    """当前是否已设置开机自启。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _APP_NAME)
        return True
    except OSError:
        return False


def enable() -> None:
    """写入自启项（命令随当前运行方式自动确定）。"""
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, _launch_command())


def disable() -> None:
    """删除自启项（不存在时静默）。"""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, _APP_NAME)
    except OSError:
        pass


def set_enabled(on: bool) -> None:
    enable() if on else disable()
