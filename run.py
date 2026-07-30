# -*- coding: utf-8 -*-
"""
Taskbar Todo — 入口点
======================

待办项以半透明圆角 pill 嵌入 Windows 系统任务栏（C-lite 渲染：
PIL 逐像素 alpha + UpdateLayeredWindow 分层窗口）。

原先扁平的 *.py 已重构进 src/ 包（见 src/__init__.py）。

用法:
    python run.py

PyInstaller 打包（见 build.ps1 / build.sh / TaskbarTodo.spec）:
    pyinstaller --onefile --windowed --name TaskbarTodo run.py
"""

from src.app import main

if __name__ == "__main__":
    main()
