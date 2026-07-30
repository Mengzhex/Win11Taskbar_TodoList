"""
分层叠加窗口 — UpdateLayeredWindow 逐像素 alpha
================================================

C-lite 方案的 Win32 半：创建一个 WS_EX_LAYERED 窗口，SetParent 嵌入任务栏，
用 UpdateLayeredWindow 把 bar_renderer 合成的 RGBA 位图逐像素混合上去
（真正的半透明，能透出任务栏 acrylic）。

⚠️ 重要设计：窗口类使用系统自带的 DefWindowProc（纯 C，无 Python 回调）。
   鼠标交互由上层用 root.after 轮询实现（GetCursorPos + GetAsyncKeyState），
   全程 Python→C 单向调用，**不使用 ctypes WNDPROC 回调**——因为 C→Python
   回调在 Tk mainloop / pystray 多线程环境下会触发 GIL/线程状态 fatal crash。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable

from PIL import Image, ImageChops

# =========================================================================
# 常量
# =========================================================================
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000

WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

ULW_ALPHA = 0x02
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01

SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

DIB_RGB_COLORS = 0
IDC_ARROW = 32512
CS_HREDRAW = 0x0002
CS_VREDRAW = 0x0001

SW_HIDE = 0
SW_SHOWNA = 8

VK_LBUTTON = 0x01
VK_RBUTTON = 0x02

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


# =========================================================================
# 结构体
# =========================================================================
class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class WNDCLASSEX(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


# =========================================================================
# DLL 签名
# =========================================================================
_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32
_kernel32 = ctypes.windll.kernel32

_user32.CreateWindowExW.restype = wintypes.HWND
_user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
_user32.DefWindowProcW.restype = LRESULT
_user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.RegisterClassExW.restype = wintypes.ATOM
_user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEX)]
_user32.SetParent.restype = wintypes.HWND
_user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
_user32.UpdateLayeredWindow.restype = wintypes.BOOL
_user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND, wintypes.HDC, ctypes.c_void_p, ctypes.c_void_p,
    wintypes.HDC, ctypes.c_void_p, wintypes.COLORREF,
    ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD,
]
_user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.GetDC.restype = wintypes.HDC
_user32.GetDC.argtypes = [wintypes.HWND]
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
_user32.GetAsyncKeyState.restype = ctypes.c_short
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.LoadCursorW.restype = wintypes.HANDLE
_user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.DestroyWindow.argtypes = [wintypes.HWND]

_gdi32.CreateCompatibleDC.restype = wintypes.HDC
_gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
_gdi32.CreateDIBSection.restype = wintypes.HBITMAP
_gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
]
_gdi32.SelectObject.restype = wintypes.HGDIOBJ
_gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
_gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_gdi32.DeleteDC.argtypes = [wintypes.HDC]

_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


# =========================================================================
# 输入辅助（供上层轮询）
# =========================================================================
def get_cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def mouse_button_down(right: bool = False) -> bool:
    vk = VK_RBUTTON if right else VK_LBUTTON
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


# =========================================================================
# 位图转换：PIL RGBA -> 预乘 alpha 的 DIBSection
# =========================================================================
def _pil_to_dib(img: Image.Image, screen_dc: int) -> tuple[int, tuple[int, int]]:
    img = img.convert("RGBA")
    w, h = img.size
    r, g, b, a = img.split()
    r = ImageChops.multiply(r, a)  # 预乘 alpha
    g = ImageChops.multiply(g, a)
    b = ImageChops.multiply(b, a)
    bgra = Image.merge("RGBA", (b, g, r, a)).tobytes()  # DIB 字节序 BGRA

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h  # 负 = top-down
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0  # BI_RGB

    ppv = ctypes.c_void_p()
    hbmp = _gdi32.CreateDIBSection(
        screen_dc, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(ppv), None, 0
    )
    if hbmp and ppv.value:
        ctypes.memmove(ppv, bgra, len(bgra))
    return hbmp, (w, h)


# =========================================================================
# 分层窗口
# =========================================================================
class LayeredBar:
    """嵌入任务栏的分层叠加窗口（无 WNDPROC 回调；交互靠上层轮询）。"""

    _CLASS_NAME = "TaskbarTodoLayeredBar"
    _class_atom = None
    _defwndproc = None  # 保持对 DefWindowProc 指针的引用

    def __init__(
        self,
        *,
        render_fn: Callable[[str | None, bool], tuple[Image.Image, list, int, int, int, int]],
    ) -> None:
        self._render_fn = render_fn
        self.hwnd: int = 0
        self._regions: list = []
        self._hovered_id: str | None = None
        self._hovered_plus = False
        self._rect = (0, 0, 0, 0)  # 屏幕坐标 (l, t, r, b)

    # ---- 创建 / 嵌入 ----
    def create(self, taskbar_hwnd: int) -> int:
        hinst = _kernel32.GetModuleHandleW(None)
        if LayeredBar._class_atom is None:
            # 用系统 DefWindowProc 作为窗口过程（纯 C，无 Python 回调）
            LayeredBar._defwndproc = ctypes.cast(_user32.DefWindowProcW, WNDPROC)
            wc = WNDCLASSEX()
            wc.cbSize = ctypes.sizeof(WNDCLASSEX)
            wc.style = CS_HREDRAW | CS_VREDRAW
            wc.lpfnWndProc = LayeredBar._defwndproc
            wc.hInstance = hinst
            wc.hCursor = _user32.LoadCursorW(None, ctypes.c_wchar_p(IDC_ARROW))
            wc.lpszClassName = self._CLASS_NAME
            atom = _user32.RegisterClassExW(ctypes.byref(wc))
            if not atom:
                raise ctypes.WinError(ctypes.get_last_error())
            LayeredBar._class_atom = atom
            LayeredBar._wc_ref = wc

        ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        self.hwnd = _user32.CreateWindowExW(
            ex, self._CLASS_NAME, None, WS_POPUP | WS_VISIBLE,
            0, 0, 10, 10, None, None, hinst, None,
        )
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())

        _user32.SetParent(self.hwnd, taskbar_hwnd)
        return self.hwnd

    # ---- 重绘 ----
    def repaint(self) -> None:
        if not self.hwnd:
            return
        img, regions, x, y, w, h = self._render_fn(self._hovered_id, self._hovered_plus)
        self._regions = regions

        _user32.SetWindowPos(
            self.hwnd, None, x, y, w, h,
            SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )
        # 记录实际屏幕矩形，供命中测试
        rc = wintypes.RECT()
        if _user32.GetWindowRect(self.hwnd, ctypes.byref(rc)):
            self._rect = (rc.left, rc.top, rc.right, rc.bottom)

        screen_dc = _user32.GetDC(None)
        mem_dc = _gdi32.CreateCompatibleDC(screen_dc)
        hbmp, (bw, bh) = _pil_to_dib(img, screen_dc)
        old = _gdi32.SelectObject(mem_dc, hbmp)
        try:
            size = wintypes.SIZE(bw, bh)
            src = wintypes.POINT(0, 0)
            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            _user32.UpdateLayeredWindow(
                self.hwnd, screen_dc, None, ctypes.byref(size),
                mem_dc, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA,
            )
        finally:
            _gdi32.SelectObject(mem_dc, old)
            _gdi32.DeleteObject(hbmp)
            _gdi32.DeleteDC(mem_dc)
            _user32.ReleaseDC(None, screen_dc)

    # ---- 命中测试（屏幕坐标）----
    def hit_region_at(self, sx: int, sy: int):
        l, t, r, b = self._rect
        if not (l <= sx < r and t <= sy < b):
            return None
        local_x = sx - l
        for reg in self._regions:
            if reg.x0 <= local_x < reg.x1:
                return reg
        return None

    def region_screen(self, kind: str) -> tuple[int, int, int, int] | None:
        """返回某类区域（如 'input'）的屏幕矩形 (x, y, w, h)，无则 None。"""
        l, t, r, b = self._rect
        for reg in self._regions:
            if reg.kind == kind:
                return (l + reg.x0, t, reg.x1 - reg.x0, b - t)
        return None

    def todo_screen_rect(self, todo_id: str) -> tuple[int, int, int, int] | None:
        """返回某待办整条 pill 的屏幕矩形（合并 check + todo 两个子区）。"""
        l, t, r, b = self._rect
        xs = [(reg.x0, reg.x1) for reg in self._regions if reg.todo_id == todo_id]
        if not xs:
            return None
        x0 = min(a for a, _ in xs)
        x1 = max(bb for _, bb in xs)
        return (l + x0, t, x1 - x0, b - t)

    def set_hover(self, hovered_id: str | None, hovered_plus: bool) -> None:
        if hovered_id != self._hovered_id or hovered_plus != self._hovered_plus:
            self._hovered_id = hovered_id
            self._hovered_plus = hovered_plus
            self.repaint()

    # ---- 显隐 / 销毁 ----
    def show(self) -> None:
        if self.hwnd:
            _user32.ShowWindow(self.hwnd, SW_SHOWNA)

    def hide(self) -> None:
        if self.hwnd:
            _user32.ShowWindow(self.hwnd, SW_HIDE)

    def destroy(self) -> None:
        if self.hwnd:
            _user32.DestroyWindow(self.hwnd)
            self.hwnd = 0
