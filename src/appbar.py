"""
Win32 工具函数 — 任务栏定位 + 透明窗口 + 点击穿透
=================================================

提供以下能力：
  - 检测系统任务栏的精确位置和 HWND
  - 获取系统托盘（TrayNotifyWnd）位置（TrafficMonitor 定位策略）
  - SetParent 把 Tkinter 窗口嵌入任务栏
  - 屏幕像素采样获取任务栏真实背景色
  - 系统主题 / 强调色检测
"""

from __future__ import annotations

import ctypes
import winreg
from ctypes import wintypes

# =========================================================================
# 常量
# =========================================================================

# 用作「透明色键」的颜色：极暗蓝，不会被正常 UI 使用
# hex 格式给 Tkinter，COLORREF 格式给 Win32 API
TRANSPARENT_KEY = "#010001"
TRANSPARENT_KEY_RGB = 0x000001  # COLORREF: 0x00BBGGRR

TASKBAR_CLASS = "Shell_TrayWnd"
TRAY_NOTIFY_CLASS = "TrayNotifyWnd"

# 任务栏消息
ABM_GETTASKBARPOS = 0x00000005

# SetWindowPos 标志
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_FRAMECHANGED = 0x0020
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001

HWND_TOPMOST = -1

# 图标区 class 名（用于枚举子窗口找空闲区域）
_ICON_CLASSES = {"MSTaskListWClass", "MSTaskSwWClass", "ReBarWindow32"}
# 排除我们自己的 Tk 窗口（避免自我干扰检测）
_SKIP_CLASSES = {"TkTopLevel", "TkChild"}


# =========================================================================
# 结构体
# =========================================================================

class APPBARDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uCallbackMessage", wintypes.UINT),
        ("uEdge", wintypes.UINT),
        ("rc", wintypes.RECT),
        ("lParam", wintypes.LPARAM),
    ]


class _DWMCOLORIZATIONPARAMS(ctypes.Structure):
    _fields_ = [
        ("ColorizationColor", wintypes.UINT),
        ("ColorizationAfterglow", wintypes.UINT),
        ("ColorizationAfterglowBalance", wintypes.UINT),
        ("ColorizationBlurBalance", wintypes.UINT),
        ("ColorizationGlassReflectionIntensity", wintypes.UINT),
        ("ColorizationOpaqueBlend", wintypes.UINT),
        ("ColorizationTint", wintypes.UINT),
    ]


# 子窗口枚举回调类型
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


# =========================================================================
# DLL 初始化（统一在此声明函数签名）
# =========================================================================

_shell32 = ctypes.windll.shell32
_shell32.SHAppBarMessage.restype = ctypes.c_ulong
_shell32.SHAppBarMessage.argtypes = [wintypes.DWORD, ctypes.POINTER(APPBARDATA)]

_user32 = ctypes.windll.user32
_user32.GetParent.restype = wintypes.HWND
_user32.GetParent.argtypes = [wintypes.HWND]
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.UINT,
]
_user32.SetParent.restype = wintypes.HWND
_user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
_user32.FindWindowW.restype = wintypes.HWND
_user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
_user32.FindWindowExW.restype = wintypes.HWND
_user32.FindWindowExW.argtypes = [
    wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
]
_user32.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]
_user32.EnumChildWindows.restype = wintypes.BOOL
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.restype = ctypes.c_int
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]
_user32.GetDC.restype = wintypes.HDC
_user32.GetDC.argtypes = [wintypes.HWND]
_user32.ReleaseDC.restype = ctypes.c_int
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]

_gdi32 = ctypes.windll.gdi32
_gdi32.GetPixel.restype = wintypes.COLORREF
_gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]

_dwm = ctypes.windll.dwmapi
_dwm.DwmGetWindowAttribute.restype = ctypes.c_long
_dwm.DwmGetWindowAttribute.argtypes = [
    wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
]


# =========================================================================
# 任务栏位置检测
# =========================================================================

def get_taskbar_rect() -> wintypes.RECT | None:
    """获取系统任务栏的精确位置和尺寸。"""
    abd = APPBARDATA()
    abd.cbSize = ctypes.sizeof(APPBARDATA)
    if _shell32.SHAppBarMessage(ABM_GETTASKBARPOS, ctypes.byref(abd)):
        return abd.rc

    hwnd = get_taskbar_hwnd()
    if hwnd:
        rect = wintypes.RECT()
        if _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return rect
    return None


def get_taskbar_hwnd() -> int:
    """获取任务栏窗口句柄 (Shell_TrayWnd)。"""
    return _user32.FindWindowW(TASKBAR_CLASS, None) or 0


def get_toplevel_hwnd(tk_window) -> int:
    """从 Tkinter 窗口对象逐层向上找到顶层 Win32 HWND。"""
    tk_window.update_idletasks()
    hwnd = tk_window.winfo_id()
    while True:
        parent = _user32.GetParent(hwnd)
        if parent:
            hwnd = parent
        else:
            break
    return hwnd


def get_tray_notify_info(taskbar_hwnd: int | None = None) -> tuple[int, int, int, int] | None:
    """
    获取系统托盘 (TrayNotifyWnd) 相对于任务栏的位置。

    参考 TrafficMonitor 的 Win11 策略：直接用 FindWindowEx 查找。

    返回 (left, top, width, height)，坐标相对于任务栏左上角。
    找不到返回 None。
    """
    if taskbar_hwnd is None:
        taskbar_hwnd = get_taskbar_hwnd()
    if not taskbar_hwnd:
        return None

    tb_rect = wintypes.RECT()
    if not _user32.GetWindowRect(taskbar_hwnd, ctypes.byref(tb_rect)):
        return None

    tray_hwnd = _user32.FindWindowExW(taskbar_hwnd, 0, TRAY_NOTIFY_CLASS, None)
    if not tray_hwnd:
        return None

    tray_rect = wintypes.RECT()
    if not _user32.GetWindowRect(tray_hwnd, ctypes.byref(tray_rect)):
        return None

    return (
        tray_rect.left - tb_rect.left,
        tray_rect.top - tb_rect.top,
        tray_rect.right - tray_rect.left,
        tray_rect.bottom - tray_rect.top,
    )


def get_taskbar_free_area() -> tuple[int, int, int, int] | None:
    """
    枚举任务栏子窗口，找图标区结束 → 系统托盘开始之间的空闲区域。

    返回相对于任务栏的 (x, y, width, height)。找不到返回 None。
    """
    taskbar_hwnd = get_taskbar_hwnd()
    if not taskbar_hwnd:
        return None

    tb_rect = wintypes.RECT()
    if not _user32.GetWindowRect(taskbar_hwnd, ctypes.byref(tb_rect)):
        return None

    tb_left = tb_rect.left
    tb_right = tb_rect.right
    tb_h = tb_rect.bottom - tb_rect.top

    icon_area_right = 0        # 应用图标区结束位置（相对）
    tray_area_left = tb_right  # 系统托盘区开始位置（屏幕绝对）

    def _enum_callback(hwnd, _lparam):
        nonlocal icon_area_right, tray_area_left
        cls_buf = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(hwnd, cls_buf, 256)
        cls_name = cls_buf.value

        if cls_name in _SKIP_CLASSES:
            return True

        r = wintypes.RECT()
        _user32.GetWindowRect(hwnd, ctypes.byref(r))
        rel_left = r.left - tb_left
        rel_right = r.right - tb_left

        # 跳过异常巨大的窗口（如 XAML bridge 占满全屏）
        if rel_right - rel_left > tb_right - tb_left:
            return True

        if cls_name in _ICON_CLASSES and rel_right > icon_area_right:
            icon_area_right = rel_right
        if cls_name == TRAY_NOTIFY_CLASS and r.left < tray_area_left:
            tray_area_left = r.left
        return True

    _user32.EnumChildWindows(taskbar_hwnd, WNDENUMPROC(_enum_callback), 0)

    margin = 6
    free_x = icon_area_right + margin
    free_w = (tray_area_left - tb_left) - margin - free_x

    if free_w < 200:
        free_x = icon_area_right + margin
        free_w = max(400, (tray_area_left - tb_left) - icon_area_right - margin * 2)

    return (free_x, 0, free_w, tb_h)


# =========================================================================
# 窗口操作
# =========================================================================

def set_parent(child_hwnd: int, parent_hwnd: int) -> int:
    """将窗口嵌入另一个窗口（SetParent）。"""
    return _user32.SetParent(child_hwnd, parent_hwnd)


def move_window(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    """移动并调整窗口位置（SetWindowPos，物理像素）。"""
    flags = SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW
    _user32.SetWindowPos(hwnd, 0, x, y, w, h, flags)


# =========================================================================
# 颜色 / 主题检测
# =========================================================================

def is_dark_theme() -> bool:
    """检测系统当前是否为深色主题（注册表 AppsUseLightTheme）。"""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return value == 0  # 0 = 深色, 1 = 浅色
    except OSError:
        return True


def get_taskbar_accent_color() -> str:
    """获取系统强调色 (DwmGetColorizationParameters)，返回 #RRGGBB。"""
    try:
        params = _DWMCOLORIZATIONPARAMS()
        _dwm[127](ctypes.byref(params))  # ordinal 127 = DwmGetColorizationParameters
        color = params.ColorizationColor & 0x00FFFFFF
        return f"#{color >> 16 & 0xFF:02X}{color >> 8 & 0xFF:02X}{color & 0xFF:02X}"
    except Exception:
        return "#0078d4"


def get_taskbar_actual_color(taskbar_hwnd: int | None = None) -> str:
    """
    推断任务栏背景色（DWM 属性优先，回退到主题推断）。

    返回 #RRGGBB。仅作为屏幕采样的 fallback。
    """
    if taskbar_hwnd is None:
        taskbar_hwnd = get_taskbar_hwnd()

    # 方案 1: DwmGetWindowAttribute 读标题色 (DWMWA_CAPTION_COLOR = 35)
    try:
        color = wintypes.COLORREF()
        hr = _dwm.DwmGetWindowAttribute(
            taskbar_hwnd, 35, ctypes.byref(color), ctypes.sizeof(color),
        )
        if hr == 0 and color != 0:
            r, g, b = color & 0xFF, (color >> 8) & 0xFF, (color >> 16) & 0xFF
            return f"#{r:02X}{g:02X}{b:02X}"
    except Exception:
        pass

    # 方案 2: 主题推断
    return "#1f1f1f" if is_dark_theme() else "#f3f3f3"


def sample_taskbar_color(
    taskbar_hwnd: int | None = None, sample_x: int | None = None,
) -> str:
    """
    直接从屏幕采样任务栏像素颜色（最准确）。

    采样策略（比单条横线更稳）：
      - 在任务栏「左侧 15%~45%」区间取样，避开右侧我们自己的叠加窗口；
      - 采样多行多列，对每个通道取中位数（median），天然抗图标/壁纸噪声。

    Args:
        taskbar_hwnd: 任务栏窗口句柄
        sample_x: 采样中心屏幕 X 坐标，None 则自动取左侧安全区

    返回 #RRGGBB。采样失败回退到 get_taskbar_actual_color()。
    """
    if taskbar_hwnd is None:
        taskbar_hwnd = get_taskbar_hwnd()

    rect = wintypes.RECT()
    _user32.GetWindowRect(taskbar_hwnd, ctypes.byref(rect))
    tb_left, tb_right, tb_top, tb_bottom = rect.left, rect.right, rect.top, rect.bottom
    tb_w = tb_right - tb_left
    tb_h = tb_bottom - tb_top

    # 采样窗口默认落在任务栏左侧 15%~45%：那里通常是空白/开始按钮附近，
    # 且远离右对齐的 Todo 叠加窗，避免采到自己的像素形成反馈回路。
    if sample_x is not None:
        x_left = max(tb_left + 4, sample_x - 120)
        x_right = min(tb_right - 4, sample_x + 120)
    else:
        x_left = tb_left + tb_w * 15 // 100
        x_right = tb_left + tb_w * 45 // 100

    hdc = _user32.GetDC(0)
    if not hdc:
        return get_taskbar_actual_color(taskbar_hwnd)

    reds: list[int] = []
    greens: list[int] = []
    blues: list[int] = []
    try:
        # 两行（1/3、2/3 高度）× 多列，构成一个采样网格
        ys = [tb_top + tb_h // 3, tb_top + tb_h * 2 // 3]
        cols = 12
        for y in ys:
            for i in range(cols):
                x = x_left + (x_right - x_left) * i // (cols - 1)
                cref = _gdi32.GetPixel(hdc, x, y)
                if cref == 0xFFFFFFFF:  # CLR_INVALID：坐标无效，跳过
                    continue
                reds.append(cref & 0xFF)
                greens.append((cref >> 8) & 0xFF)
                blues.append((cref >> 16) & 0xFF)
    finally:
        _user32.ReleaseDC(0, hdc)

    if not reds:
        return get_taskbar_actual_color(taskbar_hwnd)

    def _median(vals: list[int]) -> int:
        vals = sorted(vals)
        n = len(vals)
        return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) // 2

    return f"#{_median(reds):02X}{_median(greens):02X}{_median(blues):02X}"


def get_theme_signature(taskbar_hwnd: int | None = None) -> tuple[bool, str, str]:
    """
    返回可比对的「主题指纹」：(是否深色, 强调色, 采样任务栏色)。

    用于运行时轮询：指纹变化即说明用户切换了主题/强调色/壁纸，
    此时应重新构建配色并刷新 UI。
    """
    if taskbar_hwnd is None:
        taskbar_hwnd = get_taskbar_hwnd()
    return (
        is_dark_theme(),
        get_taskbar_accent_color(),
        sample_taskbar_color(taskbar_hwnd),
    )


# =========================================================================
# Acrylic 玻璃效果（SetWindowCompositionAttribute）
# =========================================================================

class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_uint),
        ("AccentFlags", ctypes.c_uint),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId", ctypes.c_uint),
    ]


class _WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.c_void_p),
        ("SizeOfData", ctypes.c_size_t),
    ]


_ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
_ACCENT_ENABLE_BLURBEHIND = 3
_WCA_ACCENT_POLICY = 19

try:
    _user32.SetWindowCompositionAttribute.argtypes = [
        wintypes.HWND, ctypes.POINTER(_WINCOMPATTRDATA),
    ]
    _user32.SetWindowCompositionAttribute.restype = wintypes.BOOL
    _HAS_SWCA = True
except AttributeError:
    _HAS_SWCA = False


def enable_acrylic(hwnd: int, tint_argb: int, *, acrylic: bool = True) -> bool:
    """
    给顶层窗口开启 acrylic 玻璃（模糊+着色）。

    tint_argb: 0xAABBGGRR —— 高字节 alpha 控制着色浓度，其余为 BGR。
               例：亮色玻璃 0xB0FFFFFF；暗色玻璃 0xB01E1E1E。
    acrylic=False 时退回普通 blurbehind（较老系统）。

    仅对普通顶层窗口有效（嵌入任务栏的子窗口无效）。返回是否成功。
    """
    if not _HAS_SWCA or not hwnd:
        return False
    state = _ACCENT_ENABLE_ACRYLICBLURBEHIND if acrylic else _ACCENT_ENABLE_BLURBEHIND
    accent = _ACCENT_POLICY(state, 0, tint_argb & 0xFFFFFFFF, 0)
    data = _WINCOMPATTRDATA(
        _WCA_ACCENT_POLICY,
        ctypes.cast(ctypes.byref(accent), ctypes.c_void_p),
        ctypes.sizeof(accent),
    )
    return bool(_user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data)))


def round_window(hwnd: int, w: int, h: int, radius: int = 16) -> None:
    """把窗口裁成圆角矩形（overrideredirect 窗口也适用）。"""
    if not hwnd:
        return
    rgn = _gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, radius, radius)
    _user32.SetWindowRgn(hwnd, rgn, True)


def get_luminance(hex_color: str) -> float:
    """计算颜色亮度 (ITU-R BT.601)，返回 0~255，用于自动选择黑/白文字。"""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 0.299 * r + 0.587 * g + 0.114 * b
