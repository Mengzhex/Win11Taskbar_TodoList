# -*- coding: utf-8 -*-
"""Taskbar Todo — 源码包。

各模块职责见各文件 docstring：
  app.py           — 主应用编排（隐藏 Tk root 跑事件循环 + 分层 bar）
  appbar.py        — Win32 工具：任务栏定位/嵌入/主题检测/acrylic/圆角
  bar_renderer.py  — PIL 合成待办为 RGBA 位图 + 命中区域
  layered_window.py— 分层叠加窗口（UpdateLayeredWindow 逐像素 alpha）
  bar_ui.py        — 内联输入 chip + 右键菜单（Tk，支持中文输入法）
  todo_manager.py  — 数据模型 + JSON 持久化
  config.py        — 用户设置持久化
  settings_dlg.py  — 设置对话框
  tray.py          — 系统托盘图标
  autostart.py     — 开机自启（注册表 Run 键）
"""
