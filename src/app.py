"""
Taskbar Todo — 待办项嵌入系统任务栏内部（C-lite 渲染）
======================================================

分层窗口（UpdateLayeredWindow 逐像素 alpha）叠加在系统任务栏上，
渲染成原生风格的半透明圆角 pill，真正融进任务栏 acrylic。

架构：
  app.py           — 主应用，编排各模块（隐藏 Tk root 跑事件循环）
  appbar.py        — Win32 工具：任务栏定位、嵌入、主题检测
  bar_renderer.py  — PIL 合成：把待办画成 RGBA 位图 + 命中区域
  layered_window.py— 分层叠加窗口：UpdateLayeredWindow + 鼠标命中
  bar_ui.py        — 输入浮层 + 右键菜单（仍用 Tk，支持中文输入法）
  todo_manager.py  — 数据模型 + JSON 持久化
  config.py        — 用户设置持久化
  settings_dlg.py  — 设置对话框
  tray.py          — 系统托盘图标

运行:  python app.py
"""

from __future__ import annotations

import ctypes
import os
import queue
import signal
import tkinter as tk
from pathlib import Path

from .appbar import (
    get_taskbar_rect,
    get_tray_notify_info,
    get_taskbar_hwnd,
    get_theme_signature,
    is_dark_theme,
    sample_taskbar_color,
)
from .bar_renderer import render_bar, build_palette, pill_metrics, input_chip_colors
from .bar_ui import InputPopup, popup_menu
from .config import Settings
from .layered_window import LayeredBar, get_cursor_pos, mouse_button_down
from .settings_dlg import SettingsDialog
from .todo_manager import TodoManager
from .tray import TrayIcon
from . import autostart

CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "TaskbarTodo"
CONFIG_FILE = CONFIG_DIR / "settings.json"

_TRAY_GAP = 6            # bar 右边与托盘之间的间距
_LEFT_MARGIN = 8         # bar 最左可到的位置（相对任务栏左）
_THEME_POLL_MS = 1500    # 主题跟随轮询间隔
_MOUSE_POLL_MS = 30      # 鼠标交互轮询间隔（hover / 点击）


class TaskbarTodoApp:
    """主应用：协调配置、数据、分层 bar、托盘。"""

    def __init__(self) -> None:
        self.settings = Settings(CONFIG_FILE)
        data_dir = self.settings.resolve_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        self.data_file = data_dir / "todos.json"
        self.manager = TodoManager(self.data_file)

        self.root: tk.Tk | None = None
        self.bar: LayeredBar | None = None
        self.input_popup: InputPopup | None = None
        self._tray: TrayIcon | None = None
        self._pal = None
        self._theme_sig: tuple | None = None
        self._visible = True
        self._taskbar_hwnd = 0
        self._mode: str | None = None   # None / 'add' / 'edit'
        self._edit_id: str | None = None
        # 托盘回调跨线程队列（pystray 在别的线程，不能直接碰 Tk）
        self._cmd_q: queue.Queue = queue.Queue()
        # 鼠标轮询状态
        self._prev_l = False
        self._prev_r = False
        self._press_l = None  # 左键按下时命中的 (kind, todo_id)
        self._press_r = None

    # ------------------------------------------------------------------
    def run(self) -> None:
        # 隐藏的 Tk root：只用来跑事件循环 + 承载输入浮层/菜单/设置框
        self.root = tk.Tk()
        self.root.withdraw()

        self.input_popup = InputPopup(
            self.root, on_submit=self._on_input_submit, on_close=self._close_input
        )

        self._taskbar_hwnd = get_taskbar_hwnd()
        if not self._taskbar_hwnd:
            print("[错误] 找不到任务栏 (Shell_TrayWnd)")
            return

        self._pal = build_palette()
        self.bar = LayeredBar(render_fn=self._render)
        self.bar.create(self._taskbar_hwnd)

        # 数据变化 → 重绘
        self.manager.add_listener(
            lambda: self.root.after(0, self._safe_repaint)
        )
        self._safe_repaint()

        # 鼠标交互轮询（不用 WNDPROC 回调，避免 GIL 崩溃）
        self.root.after(_MOUSE_POLL_MS, self._poll_mouse)
        # 托盘命令泵（主线程执行入队的托盘动作）
        self.root.after(60, self._pump_commands)

        # 主题跟随
        self._theme_sig = get_theme_signature(self._taskbar_hwnd)
        self.root.after(_THEME_POLL_MS, self._poll_theme)

        print("✅ Taskbar Todo 已启动（C-lite 渲染）")
        print("💡 左键完成/取消，右键菜单，＋ 添加；托盘可退出")

        self._tray = TrayIcon(
            on_quit=lambda: self._cmd_q.put(self._quit),
            on_toggle_visible=lambda: self._cmd_q.put(self._toggle_visible),
            on_clear_done=lambda: self._cmd_q.put(self._clear_done),
            on_settings=lambda: self._cmd_q.put(self._open_settings),
        )
        self._tray.start()

        signal.signal(signal.SIGINT, lambda *_: self.root.after(0, self._quit))

        # 测试钩子：自动打开设置窗（验证打包后主题/依赖是否齐全）
        if os.environ.get("TASKBARTODO_TEST_SETTINGS"):
            self.root.after(1000, lambda: self._cmd_q.put(self._open_settings))

        # 测试钩子：设置该环境变量则自动退出（用于自动化验证不崩溃）
        _q = os.environ.get("TASKBARTODO_TEST_QUIT_MS")
        if _q:
            self.root.after(int(_q), self._quit)

        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            pass
        finally:
            if self._tray:
                self._tray.stop()
            if self.bar:
                self.bar.destroy()

    # ------------------------------------------------------------------
    # 渲染回调（供 LayeredBar 调用）
    # ------------------------------------------------------------------
    def _render(self, hovered_id, hovered_plus):
        tb = get_taskbar_rect()
        bar_h = (tb.bottom - tb.top) if tb else 48

        tray = get_tray_notify_info(self._taskbar_hwnd)
        tray_left = tray[0] if tray else (tb.right - tb.left - 200 if tb else 800)

        max_w = max(120, tray_left - _LEFT_MARGIN - _TRAY_GAP)
        font_scale = self.settings.font_size / 11.0

        slot_w = 0
        if self._mode == "add":
            _, font_px = pill_metrics(bar_h, font_scale)
            slot_w = max(140, int(font_px * 11))

        img, regions, total_w = render_bar(
            self.manager.todos, bar_h,
            max_w=max_w, hovered_id=hovered_id, hovered_plus=hovered_plus,
            pal=self._pal, font_scale=font_scale, input_slot_w=slot_w,
        )
        x = tray_left - _TRAY_GAP - total_w
        x = max(_LEFT_MARGIN, x)
        return img, regions, x, 0, total_w, bar_h

    def _safe_repaint(self) -> None:
        try:
            if self.bar:
                self.bar.repaint()
            # 布局可能变宽（新增待办），让输入 chip 跟随位置重新定位（不重置内容）
            if self._mode and self.input_popup.visible():
                rect = self._active_chip_rect()
                if rect:
                    x, y, w, h, _ = rect
                    self.input_popup.reposition(x, y, w, h)
        except Exception as e:
            print(f"[警告] 重绘失败: {e}")

    def _active_chip_rect(self):
        """当前模式下输入 chip 应覆盖的 (x, y, w, h, font_px)；无则 None。"""
        if not self.bar:
            return None
        if self._mode == "add":
            r = self.bar.region_screen("input")
        elif self._mode == "edit" and self._edit_id:
            r = self.bar.todo_screen_rect(self._edit_id)
        else:
            return None
        if not r:
            return None
        x, t, w, barh = r
        pill_h, font_px = pill_metrics(barh, self.settings.font_size / 11.0)
        return x, t + (barh - pill_h) // 2, w, pill_h, font_px

    def _show_chip(self, prefill: str | None = None) -> None:
        """按当前模式弹出/定位输入 chip，配色对齐 pill；prefill 用于编辑。"""
        rect = self._active_chip_rect()
        if not rect:
            return
        x, y, w, pill_h, font_px = rect
        bg, fg, border, ph = input_chip_colors(
            self._pal, sample_taskbar_color(self._taskbar_hwnd)
        )
        self.input_popup.show(x, y, w, pill_h, bg, fg, border, ph, font_px)
        if prefill is not None:
            self.input_popup.set_text(prefill)

    # ------------------------------------------------------------------
    # 托盘命令泵（把 pystray 线程入队的动作放到主线程执行）
    # ------------------------------------------------------------------
    def _pump_commands(self) -> None:
        if not self.root or not self.root.winfo_exists():
            return
        try:
            while True:
                cmd = self._cmd_q.get_nowait()
                try:
                    cmd()
                except Exception as e:
                    print(f"[警告] 托盘命令执行失败: {e}")
        except queue.Empty:
            pass
        finally:
            if self.root.winfo_exists():
                self.root.after(60, self._pump_commands)

    # ------------------------------------------------------------------
    # 鼠标交互（主线程轮询：hover / 左键 / 右键）
    # ------------------------------------------------------------------
    def _poll_mouse(self) -> None:
        if not self.root or not self.root.winfo_exists():
            return
        try:
            if self._visible and self.bar and self.bar.hwnd:
                sx, sy = get_cursor_pos()
                reg = self.bar.hit_region_at(sx, sy)
                hov_id = reg.todo_id if (reg and reg.kind in ("todo", "check")) else None
                hov_plus = bool(reg and reg.kind == "plus")
                self.bar.set_hover(hov_id, hov_plus)

                key = (reg.kind, reg.todo_id) if reg else None
                l = mouse_button_down(False)
                r = mouse_button_down(True)

                # 左键：按下记录命中，松开且落点一致才触发
                if l and not self._prev_l:
                    self._press_l = key
                if self._prev_l and not l:
                    if key is not None and key == self._press_l:
                        if reg.kind == "check":       # 圆圈 → 切换完成
                            self.manager.toggle(reg.todo_id)
                        elif reg.kind == "todo":      # 文字 → 内联编辑
                            self._start_edit(reg.todo_id)
                        elif reg.kind == "plus":
                            self._on_plus()
                    self._press_l = None

                # 右键：松开且按下/松开都在同一待办上 → 菜单
                if r and not self._prev_r:
                    self._press_r = key
                if self._prev_r and not r:
                    if key is not None and key == self._press_r and reg.kind in ("todo", "check"):
                        cx, cy = get_cursor_pos()
                        self._on_menu(reg.todo_id, cx, cy)
                    self._press_r = None

                self._prev_l, self._prev_r = l, r
        except Exception as e:
            print(f"[警告] 鼠标轮询失败: {e}")
        finally:
            self.root.after(_MOUSE_POLL_MS, self._poll_mouse)

    def _on_plus(self) -> None:
        if self.input_popup.visible():
            self.input_popup.hide()  # -> _close_input
            return
        self._mode = "add"
        self._edit_id = None
        self._safe_repaint()   # 先渲染出输入位
        self._show_chip()      # 再把输入框覆盖上去

    def _start_edit(self, todo_id: str) -> None:
        """点击待办文字 → 就地编辑该待办标题。"""
        todo = next((t for t in self.manager.todos if t.id == todo_id), None)
        if not todo:
            return
        self._mode = "edit"
        self._edit_id = todo_id
        self._safe_repaint()               # 收起可能存在的 add 输入位
        self._show_chip(prefill=todo.title)  # 覆盖到该 pill 上并预填标题

    def _on_input_submit(self, text: str) -> None:
        """输入框回车：add 模式新增；edit 模式改标题后收起。"""
        if self._mode == "edit" and self._edit_id:
            self.manager.update(self._edit_id, title=text)
            self.input_popup.hide()  # -> _close_input
        else:
            self.manager.add(text)   # add 模式保持打开，连续添加

    def _close_input(self) -> None:
        """输入 chip 关闭（Esc / 点开 / 提交后）→ 复位模式并重绘。"""
        self._mode = None
        self._edit_id = None
        self._safe_repaint()

    def _on_menu(self, todo_id: str, screen_x: int, screen_y: int) -> None:
        popup_menu(self.root, self.manager, todo_id, screen_x, screen_y, is_dark_theme())

    # ------------------------------------------------------------------
    # 主题跟随
    # ------------------------------------------------------------------
    def _poll_theme(self) -> None:
        if not self.root or not self.root.winfo_exists():
            return
        try:
            sig = get_theme_signature(self._taskbar_hwnd)
            if sig != self._theme_sig:
                self._theme_sig = sig
                self._pal = build_palette()
                self._safe_repaint()
                print(f"主题变化 → 重绘: dark={sig[0]}, accent={sig[1]}")
        except Exception as e:
            print(f"[警告] 主题轮询失败: {e}")
        finally:
            self.root.after(_THEME_POLL_MS, self._poll_theme)

    # ------------------------------------------------------------------
    # 托盘回调
    # ------------------------------------------------------------------
    def _toggle_visible(self) -> None:
        if not self.bar:
            return
        self._visible = not self._visible
        self.bar.show() if self._visible else self.bar.hide()

    def _clear_done(self) -> None:
        self.manager.clear_done()

    def _open_settings(self) -> None:
        result = SettingsDialog(self.root, self.settings).result
        if result is None:
            return

        old_dir = self.settings.resolve_data_dir()
        self.settings.set("font_size", result["font_size"])
        self.settings.set("data_dir", result["data_dir"])
        new_dir = self.settings.resolve_data_dir()

        if new_dir != old_dir:
            try:
                new_dir.mkdir(parents=True, exist_ok=True)
                old_file = old_dir / "todos.json"
                new_file = new_dir / "todos.json"
                if old_file.exists():
                    old_file.rename(new_file)
                self.data_file = new_file
                self.manager = TodoManager(self.data_file)
                self.manager.add_listener(lambda: self.root.after(0, self._safe_repaint))
                print(f"数据已迁移到: {new_dir}")
            except OSError as e:
                print(f"[警告] 数据迁移失败: {e}")

        # 开机自启（注册表 Run 键）
        try:
            autostart.set_enabled(bool(result.get("autostart")))
        except OSError as e:
            print(f"[警告] 设置开机自启失败: {e}")

        self.settings.save()
        self._safe_repaint()
        print(
            f"设置已保存: 字体={self.settings.font_size}, 路径={new_dir}, "
            f"开机自启={autostart.is_enabled()}"
        )

    def _quit(self) -> None:
        if self.bar:
            self.bar.destroy()
        if self.root:
            self.root.destroy()


def main() -> None:
    # 高 DPI 感知（per-monitor v2 优先）
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass

    TaskbarTodoApp().run()


if __name__ == "__main__":
    main()
