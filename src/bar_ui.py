"""
辅助 UI（仍用 Tk）：栏内内联输入 chip + 右键菜单。
==================================================

分层窗口无法承载文本输入 / IME，因此这两块继续用 Tk：
  - InputPopup：点击 ＋ 时在 ＋ 左侧、栏内同一行出现的输入 chip，
    配色/字体/高度/圆角全部对齐 todo pill，看起来就是“在栏里新建一条待办”。
  - popup_menu：右键待办的上下文菜单（完成、优先级、删除）。
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from .appbar import get_toplevel_hwnd, round_window

_PLACEHOLDER = "添加待办…"


class InputPopup:
    """栏内内联输入 chip（样式对齐 todo pill）。"""

    def __init__(
        self, root: tk.Tk,
        on_submit: Callable[[str], None],
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self._root = root
        self._on_submit = on_submit
        self._on_close = on_close
        self._win: tk.Toplevel | None = None
        self._entry: tk.Entry | None = None
        self._ph = False
        self._ready = False
        self._fg = "#000000"
        self._ph_fg = "#888888"

    def visible(self) -> bool:
        return bool(self._win and self._win.winfo_exists())

    def show(
        self, x: int, y: int, w: int, h: int,
        bg: str, fg: str, border: str, ph_fg: str, font_px: int,
    ) -> None:
        if self.visible():
            self.reposition(x, y, w, h)
            self._entry.focus_force()
            return

        self._fg, self._ph_fg = fg, ph_fg
        win = tk.Toplevel(self._root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=border)  # 外层作 1px 细边框
        self._win = win

        inner = tk.Frame(win, bg=bg)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        entry = tk.Entry(
            inner, font=("Microsoft YaHei UI", -font_px),  # 负号=像素，和 pill 一致
            bg=bg, fg=ph_fg, insertbackground=fg,
            relief="flat", bd=0, highlightthickness=0,
        )
        entry.pack(fill="both", expand=True, padx=max(6, font_px // 2), pady=0)
        self._entry = entry
        self._install_placeholder()

        entry.bind("<Return>", self._submit)
        entry.bind("<Escape>", lambda _e: self.hide())
        entry.bind("<FocusOut>", lambda _e: self._root.after(120, self._maybe_hide))

        self.reposition(x, y, w, h)
        win.update()
        entry.focus_force()

        # 防止创建瞬间的 FocusOut 误关闭
        self._ready = False
        win.after(400, lambda: setattr(self, "_ready", True))

    def reposition(self, x: int, y: int, w: int, h: int) -> None:
        if not self.visible():
            return
        self._win.geometry(f"{w}x{h}+{x}+{y}")
        self._win.update_idletasks()
        hwnd = get_toplevel_hwnd(self._win)
        round_window(hwnd, w, h, h // 2)  # 胶囊圆角，和 pill 一致

    def _install_placeholder(self) -> None:
        def show_ph():
            if not self._entry.get():
                self._ph = True
                self._entry.insert(0, _PLACEHOLDER)
                self._entry.configure(fg=self._ph_fg)

        def on_in(_e):
            if self._ph:
                self._entry.delete(0, "end")
                self._entry.configure(fg=self._fg)
                self._ph = False

        self._ph = False
        show_ph()
        self._entry.bind("<FocusIn>", on_in, add="+")

    def set_text(self, text: str) -> None:
        """预填内容（用于编辑已有待办），并全选便于直接替换。"""
        if not self._entry:
            return
        self._ph = False
        self._entry.delete(0, "end")
        self._entry.configure(fg=self._fg)
        self._entry.insert(0, text)
        self._entry.select_range(0, "end")
        self._entry.icursor("end")

    def _submit(self, _e=None) -> None:
        if self._ph or not self._entry:
            return
        text = self._entry.get().strip()
        if text:
            self._on_submit(text)
            # on_submit 可能已关闭本窗口（编辑模式），需判空
            if self._entry and self._entry.winfo_exists():
                self._entry.delete(0, "end")
                self._entry.focus_force()  # 连续添加

    def _maybe_hide(self) -> None:
        if not self._ready:
            return
        if self.visible() and self._root.focus_get() is not self._entry:
            self.hide()

    def hide(self) -> None:
        was_visible = self.visible()
        if was_visible:
            self._win.destroy()
        self._win = None
        self._entry = None
        self._ready = False
        if was_visible and self._on_close:
            self._on_close()


def popup_menu(
    root: tk.Tk, manager, todo_id: str, x: int, y: int, dark: bool
) -> None:
    """右键上下文菜单：完成/待办、优先级、删除。"""
    todo = next((t for t in manager.todos if t.id == todo_id), None)
    if not todo:
        return

    bg = "#2b2b2b" if dark else "#ffffff"
    fg = "#ffffff" if dark else "#1a1a1a"
    active = "#3a3a3a" if dark else "#e8e8e8"
    font = ("Microsoft YaHei UI", 10)

    menu = tk.Menu(
        root, tearoff=0, bg=bg, fg=fg,
        activebackground=active, activeforeground=fg,
        borderwidth=0, relief="flat", font=font,
    )
    toggle_text = "↩ 标记待办" if todo.done else "✓ 标记完成"
    menu.add_command(label=toggle_text, command=lambda: manager.toggle(todo_id))
    menu.add_separator()

    prio_menu = tk.Menu(
        menu, tearoff=0, bg=bg, fg=fg,
        activebackground=active, activeforeground=fg, font=font,
    )
    for val, label in [(0, "○ 普通"), (1, "◆ 重要"), (2, "● 紧急")]:
        prio_menu.add_command(
            label=label, command=lambda v=val: manager.update(todo_id, priority=v)
        )
    menu.add_cascade(label="优先级", menu=prio_menu)
    menu.add_separator()
    menu.add_command(label="🗑 删除", command=lambda: manager.delete(todo_id))

    try:
        menu.tk_popup(x, y)
    finally:
        menu.grab_release()
