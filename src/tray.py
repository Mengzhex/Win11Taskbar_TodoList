"""
系统托盘图标 — 提供设置入口和退出功能
========================================
使用 pystray 创建系统托盘图标，右键菜单包含：
  - 显示/隐藏 todo 窗口
  - 清空已完成
  - 退出

图标优先从 assets/icon_checklist.ico 读取；读不到则回退到内存绘制。
"""

from __future__ import annotations

import os
import sys
import threading
from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem

_ICON_FILE = "icon_checklist.ico"


def _asset_path(name: str) -> str:
    """返回资源文件路径，兼容源码运行与 PyInstaller 打包（_MEIPASS）。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "assets", name)
    # 源码：src/ 的上级目录即项目根
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "assets", name)


def _draw_fallback_icon() -> Image.Image:
    """回退：内存绘制一个蓝底白勾。"""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([4, 4, size - 4, size - 4], radius=12, fill=(0, 120, 212, 255))
    draw.line(
        [(16, 34), (26, 46), (48, 18), (44, 14), (26, 38), (20, 30)],
        fill=(255, 255, 255, 255), width=5, joint="curve",
    )
    return img


def _create_icon_image() -> Image.Image:
    """加载托盘图标（assets/*.ico），失败则回退内存绘制。"""
    try:
        return Image.open(_asset_path(_ICON_FILE)).convert("RGBA")
    except Exception:
        return _draw_fallback_icon()


class TrayIcon:
    """系统托盘图标管理器。"""

    def __init__(
        self,
        on_quit: callable,
        on_toggle_visible: callable | None = None,
        on_clear_done: callable | None = None,
        on_settings: callable | None = None,
    ) -> None:
        self._on_quit = on_quit
        self._on_toggle = on_toggle_visible
        self._on_clear = on_clear_done
        self._on_settings = on_settings
        self._icon: Icon | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """在后台线程启动托盘图标。"""
        menu = Menu(
            MenuItem(
                "显示/隐藏",
                self._handle_toggle,
                default=True,  # 双击触发
            ),
            MenuItem(
                "设置…",
                self._handle_settings,
            ),
            MenuItem(
                "清除已完成",
                self._handle_clear,
            ),
            Menu.SEPARATOR,
            MenuItem(
                "退出",
                self._handle_quit,
            ),
        )

        self._icon = Icon(
            name="TaskbarTodo",
            icon=_create_icon_image(),
            title="Taskbar Todo",
            menu=menu,
        )
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """停止托盘图标。"""
        if self._icon:
            self._icon.stop()

    # ---- 事件处理 ----

    def _handle_toggle(self, _icon, _item) -> None:
        if self._on_toggle:
            self._on_toggle()

    def _handle_clear(self, _icon, _item) -> None:
        if self._on_clear:
            self._on_clear()

    def _handle_settings(self, _icon, _item) -> None:
        if self._on_settings:
            self._on_settings()

    def _handle_quit(self, _icon, _item) -> None:
        if self._icon:
            self._icon.stop()
        if self._on_quit:
            self._on_quit()
