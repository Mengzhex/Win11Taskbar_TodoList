# -*- mode: python ; coding: utf-8 -*-
import os
import sys

from PyInstaller.utils.hooks import collect_data_files

# sv-ttk 主题的 .tcl 文件必须随包携带，否则打开设置窗时找不到主题文件
_datas = collect_data_files("sv_ttk")
# 托盘图标（运行时从 assets/ 读取，需打进包）
_datas += [("assets/icon_checklist.ico", "assets")]

# ----------------------------------------------------------------------
# 修复：conda 多环境下，PyInstaller 会顺着系统 PATH 收集到「基座 Anaconda」
# 里版本不一致的 tcl86t.dll（8.6.14），而 tcl 脚本库来自当前环境（8.6.15），
# 运行时报 “version conflict for package Tcl: have 8.6.14 need exactly 8.6.15”。
#
# 这里强制使用「当前解释器 sys.prefix」自带的 tcl/tk：
#   1) 把本环境 Library/bin 前置到 PATH，让依赖扫描先找到正确 DLL
#   2) 再显式把这两个 DLL 作为 binaries 打进包（双保险）
# ----------------------------------------------------------------------
_env_bin = os.path.join(sys.prefix, "Library", "bin")
if os.path.isdir(_env_bin):
    os.environ["PATH"] = _env_bin + os.pathsep + os.environ.get("PATH", "")

_tk_binaries = []
for _dll in ("tcl86t.dll", "tk86t.dll"):
    _p = os.path.join(_env_bin, _dll)
    if os.path.exists(_p):
        _tk_binaries.append((_p, "."))


a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=_tk_binaries,
    datas=_datas,
    hiddenimports=['pystray._win32'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TaskbarTodo',
    icon='assets/icon_checklist.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
