"""
Todo 任务栏渲染器 — PIL 逐像素 alpha 合成
==========================================

C-lite 方案的渲染半：把整条待办渲染成一张带逐像素透明度的 RGBA 位图，
交给 layered_window.py 通过 UpdateLayeredWindow 叠加到任务栏上。

为什么这样能"融进任务栏"：
  任务栏本身是 acrylic（半透明+模糊壁纸）。我们在它之上画**半透明**圆角
  pill —— 任务栏那层已经有的模糊会从 pill 底下透上来，pill 只加一层淡淡的
  tint。于是观感上就是原生 acrylic 卡片，而不是一块死色补丁。
  （Tk 做不到这点，因为它画不了半透明像素。）

本模块只负责"画"和"命中区域计算"，不碰任何 Win32；便于单独导出 PNG 预览。
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from .appbar import (
    get_taskbar_accent_color,
    is_dark_theme,
)
from .todo_manager import TodoItem

# =========================================================================
# 可调设计常量（相对 bar 高度的比例，自动适配 DPI / 任务栏高度）
# =========================================================================

_MARGIN_V_RATIO = 0.16      # pill 上下留白占 bar 高比例
_PILL_GAP = 6               # pill 之间水平间距 (px)
_PILL_PAD_L_RATIO = 0.42    # pill 内左侧留白 / pill 高
_PILL_PAD_R_RATIO = 0.55    # pill 内右侧留白 / pill 高
_CIRCLE_TEXT_GAP_RATIO = 0.34
_FONT_RATIO = 0.40          # 文字像素高 / pill 高（0.46→0.40 缩小）
_RADIUS_RATIO = 0.5         # 1.0=胶囊全圆角；0.5≈Win11 圆角矩形
_CIRCLE_R_RATIO = 0.24      # 状态圈半径 / pill 高
_MAX_TITLE_CHARS = 24

_FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"  # 微软雅黑：中英文都原生
_FONT_FALLBACK = r"C:\Windows\Fonts\segoeui.ttf"


@dataclass
class HitRegion:
    """一个可点击区域（图像坐标，x 方向），kind: 'todo' | 'plus'。"""
    x0: int
    x1: int
    kind: str
    todo_id: str | None = None


@dataclass
class Palette:
    """C-lite 配色：多为带 alpha 的 RGBA，用于半透明合成。"""
    fg: tuple[int, int, int]
    fg_dim: tuple[int, int, int]
    fg_done: tuple[int, int, int]
    pill: tuple[int, int, int, int]
    pill_hover: tuple[int, int, int, int]
    pill_done: tuple[int, int, int, int]
    border: tuple[int, int, int, int]
    accent: tuple[int, int, int]
    green: tuple[int, int, int]
    yellow: tuple[int, int, int]
    red: tuple[int, int, int]


# ---- 字体缓存 -----------------------------------------------------------
_font_cache: dict[int, ImageFont.FreeTypeFont] = {}


def _load_font(px: int) -> ImageFont.FreeTypeFont:
    if px in _font_cache:
        return _font_cache[px]
    font = None
    for path, idx in ((_FONT_PATH, 1), (_FONT_PATH, 0), (_FONT_FALLBACK, 0)):
        try:
            font = ImageFont.truetype(path, px, index=idx)
            break
        except (OSError, ValueError):
            continue
    if font is None:
        font = ImageFont.load_default()
    _font_cache[px] = font
    return font


# ---- 配色 ---------------------------------------------------------------
def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def build_palette(dark: bool | None = None) -> Palette:
    """根据深/浅色主题 + 强调色构建 C-lite 半透明配色。dark 传 None 则读系统。"""
    accent = _hex_to_rgb(get_taskbar_accent_color())
    if dark is None:
        dark = is_dark_theme()

    if dark:
        # 暗色任务栏：pill 用极淡白提亮，营造"上层卡片"
        return Palette(
            fg=(255, 255, 255),
            fg_dim=(190, 190, 190),
            fg_done=(150, 150, 150),
            pill=(255, 255, 255, 26),
            pill_hover=(255, 255, 255, 46),
            pill_done=(255, 255, 255, 12),
            border=(255, 255, 255, 30),
            accent=accent,
            green=(108, 203, 95),
            yellow=(255, 200, 90),
            red=(255, 95, 95),
        )
    # 亮色任务栏：pill 用半透明白做磨砂，配淡黑边
    return Palette(
        fg=(28, 28, 28),
        fg_dim=(90, 90, 90),
        fg_done=(140, 140, 140),
        pill=(255, 255, 255, 140),
        pill_hover=(255, 255, 255, 200),
        pill_done=(255, 255, 255, 90),
        border=(0, 0, 0, 28),
        accent=accent,
        green=(45, 138, 45),
        yellow=(176, 128, 11),
        red=(200, 51, 51),
    )


def _priority_color(pal: Palette, priority: int) -> tuple[int, int, int]:
    return {0: pal.fg_dim, 1: pal.yellow, 2: pal.red}.get(priority, pal.fg_dim)


def _lighten(rgb: tuple[int, int, int], amt: int = 32) -> tuple[int, int, int]:
    return tuple(min(255, c + amt) for c in rgb)


def pill_metrics(bar_h: int, font_scale: float = 1.0) -> tuple[int, int]:
    """返回 (pill_h, font_px)，与 render_bar 内部算法一致，供输入框对齐。"""
    pill_h = max(18, int(bar_h * (1 - 2 * _MARGIN_V_RATIO)))
    font_px = max(9, int(pill_h * _FONT_RATIO * font_scale))
    return pill_h, font_px


def input_chip_colors(pal: Palette, taskbar_hex: str) -> tuple[str, str, str, str]:
    """
    计算与 pill 视觉一致的「不透明」输入框配色。
    返回 (bg, fg, border, placeholder) 十六进制。
    """
    tb = _hex_to_rgb(taskbar_hex)

    def _over(base: tuple[int, int, int], rgba: tuple[int, int, int, int]) -> tuple[int, int, int]:
        a = rgba[3] / 255.0
        return tuple(int(base[i] * (1 - a) + rgba[i] * a) for i in range(3))

    def _hx(c: tuple[int, int, int]) -> str:
        return f"#{c[0]:02X}{c[1]:02X}{c[2]:02X}"

    bg = _over(tb, pal.pill_hover)      # 用 hover 态，稍实一点、更清晰
    border = _over(tb, pal.border)
    return _hx(bg), _hx(pal.fg), _hx(border), _hx(pal.fg_dim)


# ---- 绘制基元 -----------------------------------------------------------
def _draw_check_circle(
    draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int,
    *, done: bool, color: tuple[int, int, int],
) -> None:
    """画状态圈：未完成=空心环；已完成=实心圆+白勾。"""
    box = (cx - r, cy - r, cx + r, cy + r)
    if done:
        draw.ellipse(box, fill=color)
        # 白色对勾
        w = max(2, r // 4)
        p1 = (cx - r * 0.45, cy + r * 0.02)
        p2 = (cx - r * 0.08, cy + r * 0.42)
        p3 = (cx + r * 0.5, cy - r * 0.38)
        draw.line([p1, p2, p3], fill=(255, 255, 255), width=w, joint="curve")
    else:
        w = max(2, r // 4)
        draw.ellipse(box, outline=color, width=w)


def _sort_todos(todos: list[TodoItem]) -> list[TodoItem]:
    return sorted(todos, key=lambda t: (t.done, -t.priority, -t.created_at))


def _clip_title(title: str) -> str:
    return title if len(title) <= _MAX_TITLE_CHARS else title[: _MAX_TITLE_CHARS - 1] + "…"


# =========================================================================
# 主渲染
# =========================================================================
def render_bar(
    todos: list[TodoItem],
    bar_h: int,
    *,
    max_w: int | None = None,
    hovered_id: str | None = None,
    hovered_plus: bool = False,
    pal: Palette | None = None,
    font_scale: float = 1.0,
    input_slot_w: int = 0,
) -> tuple[Image.Image, list[HitRegion], int]:
    """
    渲染整条待办为 RGBA 图像。

    返回 (image, hit_regions, total_w)。布局从右到左：最右是 ＋ 按钮，
    紧邻其左是高优先级待办。空白/圆角外区域 alpha=0，会透出真任务栏。
    """
    if pal is None:
        pal = build_palette()

    pill_h = max(18, int(bar_h * (1 - 2 * _MARGIN_V_RATIO)))
    pad_l = int(pill_h * _PILL_PAD_L_RATIO)
    pad_r = int(pill_h * _PILL_PAD_R_RATIO)
    gap_ct = int(pill_h * _CIRCLE_TEXT_GAP_RATIO)
    font_px = max(9, int(pill_h * _FONT_RATIO * font_scale))
    radius = int(pill_h * _RADIUS_RATIO)
    circle_r = max(4, int(pill_h * _CIRCLE_R_RATIO))
    font = _load_font(font_px)

    ordered = _sort_todos(todos)

    # 先量每个 pill 的宽度
    measure_img = Image.new("RGBA", (1, 1))
    md = ImageDraw.Draw(measure_img)

    @dataclass
    class _Seg:
        w: int
        kind: str  # 'todo' | 'plus' | 'input'
        todo: TodoItem | None = None

    segs: list[_Seg] = []
    for t in ordered:
        title = _clip_title(t.title)
        tw = int(md.textlength(title, font=font))
        w = pad_l + circle_r * 2 + gap_ct + tw + pad_r
        segs.append(_Seg(w=w, kind="todo", todo=t))

    # ＋ 按钮：一个圆角小方块
    plus_seg = _Seg(w=pill_h, kind="plus")

    # 视觉左→右顺序：低优先级在左、高优先级靠右；输入位（若有）紧邻 ＋ 左边
    left_to_right = list(reversed(segs))
    if input_slot_w > 0:
        left_to_right.append(_Seg(w=input_slot_w, kind="input"))
    left_to_right.append(plus_seg)

    total_w = sum(s.w for s in left_to_right) + _PILL_GAP * (len(left_to_right) - 1)

    # 宽度上限：超出则从最左（最旧/已完成）开始丢弃
    if max_w is not None and total_w > max_w:
        while len(left_to_right) > 1 and total_w > max_w:
            dropped = left_to_right.pop(0)
            total_w -= dropped.w + _PILL_GAP

    img = Image.new("RGBA", (max(1, total_w), bar_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cy = bar_h // 2
    regions: list[HitRegion] = []

    x = 0
    for seg in left_to_right:
        x0 = x
        x1 = x + seg.w
        top = (bar_h - pill_h) // 2
        bottom = top + pill_h

        if seg.kind == "input":
            # 输入位：栏内留空，实际输入框由上层 Tk 覆盖在此区域
            regions.append(HitRegion(x0, x1, "input"))
        elif seg.kind == "plus":
            # ＋ 按钮：强调色实心圆 + 白色 ＋（清爽、明确的添加入口）
            pcx, pcy = (x0 + x1) // 2, cy
            br = int(pill_h * 0.32)
            fill = _lighten(pal.accent, 34) if hovered_plus else pal.accent
            draw.ellipse([pcx - br, pcy - br, pcx + br, pcy + br], fill=fill)
            pr = int(br * 0.5)
            lw = max(2, br // 4)
            draw.line([(pcx - pr, pcy), (pcx + pr, pcy)], fill=(255, 255, 255), width=lw)
            draw.line([(pcx, pcy - pr), (pcx, pcy + pr)], fill=(255, 255, 255), width=lw)
            regions.append(HitRegion(x0, x1, "plus"))
        else:  # kind == "todo"
            t = seg.todo
            hovered = (t.id == hovered_id)
            if t.done:
                fill = pal.pill_done
            elif hovered:
                fill = pal.pill_hover
            else:
                fill = pal.pill
            draw.rounded_rectangle([x0, top, x1 - 1, bottom], radius=radius, fill=fill)
            if pal.border[3] > 0:
                draw.rounded_rectangle(
                    [x0, top, x1 - 1, bottom], radius=radius, outline=pal.border, width=1,
                )

            # 状态圈
            ccx = x0 + pad_l + circle_r
            circ_color = pal.green if t.done else _priority_color(pal, t.priority)
            _draw_check_circle(draw, ccx, cy, circle_r, done=t.done, color=circ_color)

            # 标题
            tx = ccx + circle_r + gap_ct
            fg = pal.fg_done if t.done else pal.fg
            title = _clip_title(t.title)
            draw.text((tx, cy), title, font=font, fill=fg, anchor="lm")
            if t.done:  # 删除线
                tw = int(draw.textlength(title, font=font))
                draw.line([(tx, cy), (tx + tw, cy)], fill=fg, width=max(1, font_px // 12))

            # 命中区拆两半：圆圈区(check)=切换完成；文字区(todo)=内联编辑
            check_x1 = ccx + circle_r + gap_ct // 2
            regions.append(HitRegion(x0, check_x1, "check", t.id))
            regions.append(HitRegion(check_x1, x1, "todo", t.id))

        x = x1 + _PILL_GAP

    return img, regions, total_w


# =========================================================================
# 预览（脱离 Win32，导出 PNG 便于目测调样式）
# =========================================================================
def preview(path: str, bg_hex: str = "#D4E0F6", bar_h: int = 48) -> None:
    """把渲染结果合成到模拟任务栏底色上，导出 PNG。"""
    import time

    demo = [
        TodoItem(id="a", title="买牛奶", priority=0, created_at=time.time() - 50),
        TodoItem(id="b", title="重要会议 14:00", priority=1, created_at=time.time() - 40),
        TodoItem(id="c", title="紧急修复登录 bug", priority=2, created_at=time.time() - 30),
        TodoItem(id="d", title="已完成的事项", priority=0, done=True, created_at=time.time() - 10),
    ]
    fg_img, regions, total_w = render_bar(demo, bar_h, hovered_id="b")

    bg = Image.new("RGBA", (total_w + 40, bar_h), (*_hex_to_rgb(bg_hex), 255))
    bg.alpha_composite(fg_img, (20, 0))
    bg.convert("RGB").save(path)
    print(f"preview -> {path}  (total_w={total_w}, regions={len(regions)})")
