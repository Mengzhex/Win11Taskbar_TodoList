"""
设置对话框 — Win11 Fluent 风格（sv-ttk 美化）
=============================================
修改字体大小、存储路径、开机自启（滑动开关）。
"""

from __future__ import annotations

import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog

import sv_ttk

from . import autostart
from .appbar import is_dark_theme

_UI_FONT = "Microsoft YaHei UI"


class SettingsDialog:
    """设置对话框（模态窗口，Fluent 主题）。"""

    def __init__(self, parent: tk.Tk, settings) -> None:
        self.settings = settings
        self._result: dict | None = None

        self.win = tk.Toplevel(parent)
        self.win.withdraw()  # 先隐藏，布局好再显示
        self.win.title("设置")
        self.win.resizable(False, False)

        # 应用 Fluent 主题（跟随系统深浅色）+ 中文原生字体
        sv_ttk.set_theme("dark" if is_dark_theme() else "light")
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            try:
                tkfont.nametofont(name).configure(family=_UI_FONT, size=10)
            except tk.TclError:
                pass

        self._build_ui()

        # 尺寸 + 居中
        self.win.update_idletasks()
        w = max(440, self.win.winfo_reqwidth())
        h = self.win.winfo_reqheight()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        self.win.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

        # 主 root 隐藏，需主动置顶抢焦点（不要 transient 到隐藏 owner）
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)
        self.win.focus_force()
        try:
            self.win.grab_set()
        except tk.TclError:
            pass

        self.win.wait_window()

    def _build_ui(self) -> None:
        root = ttk.Frame(self.win, padding=(24, 20))
        root.pack(fill="both", expand=True)

        ttk.Label(root, text="设置", font=(_UI_FONT, 16, "bold")).pack(anchor="w")
        ttk.Separator(root).pack(fill="x", pady=(10, 16))

        # ---- 字体大小 ----
        r1 = ttk.Frame(root)
        r1.pack(fill="x", pady=6)
        ttk.Label(r1, text="字体大小", width=9).pack(side="left")
        self._font_var = tk.IntVar(value=self.settings.font_size)
        ttk.Spinbox(r1, from_=8, to=20, width=6, textvariable=self._font_var).pack(side="left")
        ttk.Label(r1, text="8 – 20", foreground="gray").pack(side="left", padx=10)

        # ---- 存储路径 ----
        r2 = ttk.Frame(root)
        r2.pack(fill="x", pady=6)
        ttk.Label(r2, text="存储路径", width=9).pack(side="left")
        self._dir_var = tk.StringVar(value=self.settings.data_dir)
        ttk.Entry(r2, textvariable=self._dir_var).pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )
        ttk.Button(r2, text="浏览…", command=self._browse, width=7).pack(side="left")
        ttk.Label(
            root, text="留空则使用默认路径  %APPDATA%\\TaskbarTodo",
            foreground="gray", font=(_UI_FONT, 8),
        ).pack(anchor="w", pady=(2, 0))

        # ---- 开机自启（滑动开关）----
        r3 = ttk.Frame(root)
        r3.pack(fill="x", pady=(18, 6))
        ttk.Label(r3, text="开机自启", width=9).pack(side="left")
        self._autostart_var = tk.BooleanVar(value=autostart.is_enabled())
        ttk.Checkbutton(
            r3, variable=self._autostart_var, style="Switch.TCheckbutton",
        ).pack(side="left")

        # ---- 按钮 ----
        r4 = ttk.Frame(root)
        r4.pack(fill="x", pady=(22, 0))
        ttk.Button(r4, text="保存", command=self._save, style="Accent.TButton", width=9).pack(
            side="right"
        )
        ttk.Button(r4, text="取消", command=self._cancel, width=9).pack(
            side="right", padx=(0, 8)
        )

    def _browse(self) -> None:
        d = filedialog.askdirectory(
            initialdir=self._dir_var.get() or os.environ.get("APPDATA", "C:\\"),
        )
        if d:
            self._dir_var.set(d)

    def _save(self) -> None:
        self._result = {
            "font_size": self._font_var.get(),
            "data_dir": self._dir_var.get().strip(),
            "autostart": self._autostart_var.get(),
        }
        self.win.destroy()

    def _cancel(self) -> None:
        self._result = None
        self.win.destroy()

    @property
    def result(self) -> dict | None:
        """返回用户选择的设置，取消则返回 None。"""
        return self._result
