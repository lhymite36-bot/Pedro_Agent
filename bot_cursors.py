"""A cursor for each bot.

Windows keeps one system arrow. Each bot gets a small colored pointer with
its name. The badge leaves shortly after the click, and sooner if the
person moves the mouse.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from typing import Callable

_positions: dict[str, tuple[int, int]] = {}
_guard = threading.Lock()
_queue: queue.Queue[tuple] = queue.Queue()
_start = threading.Lock()
_ready = threading.Event()
_thread: threading.Thread | None = None
_thread_id = 0
draw_hook: Callable[[str, int, int, str], None] | None = None

_COLORS = (
    (220, 70, 70),
    (40, 120, 230),
    (30, 160, 90),
    (230, 150, 20),
    (140, 80, 210),
    (220, 80, 160),
)
_WNDPROC = None
_windows: dict[str, int] = {}
_visible: dict[str, bool] = {}
_shown_at: dict[str, float] = {}
_anchors: dict[str, tuple[int, int]] = {}
_HOLD_S = 0.85
_GRACE_S = 0.35
_SLACK = 40
_ARROW = (
    "#",
    "##",
    "###",
    "####",
    "#####",
    "######",
    "#######",
    "########",
    "#########",
    "##########",
    "######",
    "#######",
    "##  ####",
    "#    ###",
    "      ##",
    "       #",
)


def positions() -> dict[str, tuple[int, int]]:
    with _guard:
        return dict(_positions)


def reset() -> None:
    """Drop cursors. Tests use this so the next test starts clean."""
    global draw_hook
    with _guard:
        _positions.clear()
    draw_hook = None
    if _thread is not None and _thread_id:
        _queue.put(("reset",))
        _wake()


def mark(x: int, y: int) -> None:
    """Park the current chat's cursor on this pixel."""
    import desktop_share

    owner = desktop_share.owner() or "pc"
    place(owner, int(x), int(y), _label(owner))


def place(owner: str, x: int, y: int, name: str = "") -> None:
    key = owner or "pc"
    point = (int(x), int(y))
    label = (name or _label(key))[:14]
    with _guard:
        _positions[key] = point
    if draw_hook is not None:
        draw_hook(key, point[0], point[1], label)
    if _skip_real():
        return
    _ensure()
    _queue.put(("place", key, point[0], point[1], label))
    _wake()


def _label(owner: str) -> str:
    if owner.startswith("bot-"):
        try:
            import bots

            bot = bots.get_bot(owner[4:])
            if bot and bot.get("name"):
                return str(bot["name"])[:14]
        except Exception:
            return "Bot"
        return "Bot"
    return "PC"


def _skip_real() -> bool:
    if os.name != "nt":
        return True
    try:
        import agent_core

        if agent_core.pointer_override is not None:
            return True
    except Exception:
        return True
    return False


def _color(owner: str) -> tuple[int, int, int]:
    return _COLORS[sum(owner.encode("utf-8")) % len(_COLORS)]


def _should_hide(shown_at: float, now: float, anchor, cursor) -> bool:
    """The badge is only a moment. A real mouse move dismisses it sooner."""
    age = now - shown_at
    if age >= _HOLD_S:
        return True
    if cursor is None or anchor is None or age < _GRACE_S:
        return False
    return abs(cursor[0] - anchor[0]) + abs(cursor[1] - anchor[1]) > _SLACK


def _wake() -> None:
    if not _thread_id:
        return
    import ctypes

    ctypes.windll.user32.PostThreadMessageW(int(_thread_id), 0x8000, 0, 0)


def _ensure() -> None:
    global _thread
    with _start:
        if _thread is not None and _thread.is_alive():
            return
        _ready.clear()
        _thread = threading.Thread(target=_loop, name="bot-cursors", daemon=True)
        _thread.start()
    _ready.wait(2)


def _loop() -> None:
    global _thread_id, _WNDPROC
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    _thread_id = int(ctypes.windll.kernel32.GetCurrentThreadId())
    LRESULT = ctypes.c_ssize_t
    WPARAM = ctypes.c_size_t
    LPARAM = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint, WPARAM, LPARAM)
    user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, WPARAM, LPARAM]
    user32.DefWindowProcW.restype = LRESULT

    def proc(hwnd, msg, wparam, lparam):
        if msg == 15:  # WM_PAINT
            _validate(int(hwnd))
            return 0
        if msg == 20:  # WM_ERASEBKGND
            return 1
        if msg == 2:  # WM_DESTROY
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    _WNDPROC = WNDPROC(proc)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = (
            ("style", ctypes.c_uint),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", ctypes.c_void_p),
            ("hCursor", ctypes.c_void_p),
            ("hbrBackground", ctypes.c_void_p),
            ("lpszMenuName", ctypes.c_wchar_p),
            ("lpszClassName", ctypes.c_wchar_p),
        )

    klass = WNDCLASSW()
    klass.lpfnWndProc = _WNDPROC
    klass.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
    klass.lpszClassName = "PedroBotCursor"
    klass.hCursor = user32.LoadCursorW(None, 32512)
    user32.RegisterClassW(ctypes.byref(klass))
    timer = ctypes.WINFUNCTYPE(
        ctypes.c_void_p, wintypes.HWND, ctypes.c_size_t, ctypes.c_uint, ctypes.c_void_p
    )(("SetTimer", user32))
    timer(None, 1, 80, None)
    _ready.set()
    message = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        if message.message == 0x8000:
            _drain(user32)
            continue
        if message.message == 0x0113:  # WM_TIMER
            _tick(user32)
            continue
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))


def _drain(user32) -> None:
    while True:
        try:
            item = _queue.get_nowait()
        except queue.Empty:
            return
        if item[0] == "reset":
            for hwnd in list(_windows.values()):
                user32.DestroyWindow(int(hwnd))
            _windows.clear()
            _visible.clear()
            _shown_at.clear()
            _anchors.clear()
            continue
        owner, x, y, label = item[1], item[2], item[3], item[4]
        hwnd = _windows.get(owner)
        if not hwnd:
            hwnd = _make(user32, owner)
            if not hwnd:
                continue
            _windows[owner] = int(hwnd)
        _show(user32, int(hwnd), owner, int(x), int(y), _color(owner), label)


def _tick(user32) -> None:
    now = time.monotonic()
    cursor = _cursor_pos(user32)
    for owner, hwnd in list(_windows.items()):
        if not _visible.get(owner):
            continue
        if _should_hide(_shown_at.get(owner, now), now, _anchors.get(owner), cursor):
            _visible[owner] = False
            _window_show(user32, int(hwnd), 0)


def _make(user32, owner: str) -> int:
    import ctypes
    from ctypes import wintypes

    create = ctypes.WINFUNCTYPE(
        wintypes.HWND,
        wintypes.DWORD,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        ctypes.c_void_p,
    )(("CreateWindowExW", user32))
    ex = 0x00000020 | 0x00000008 | 0x00000080 | 0x08000000 | 0x00080000
    style = 0x80000000
    hwnd = create(
        ex,
        "PedroBotCursor",
        owner,
        style,
        0,
        0,
        16,
        16,
        None,
        None,
        ctypes.windll.kernel32.GetModuleHandleW(None),
        None,
    )
    return int(hwnd or 0)


def _show(
    user32,
    hwnd: int,
    owner: str,
    x: int,
    y: int,
    color: tuple[int, int, int],
    label: str,
) -> None:
    """Draw a small pointer and name, with the tip on the click."""
    import ctypes
    from ctypes import wintypes

    width, height, pixels = _compose(color, label)
    metric = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_int)(("GetSystemMetrics", user32))
    screen_w = int(metric(0) or 0)
    screen_h = int(metric(1) or 0)
    left = int(x) - 1
    top = int(y) - 1
    if screen_w > width:
        left = min(max(0, left), screen_w - width)
    else:
        left = max(0, left)
    if screen_h > height:
        top = min(max(0, top), screen_h - height)
    else:
        top = max(0, top)
    _paint_layered(user32, hwnd, left, top, width, height, pixels)
    _anchors[owner] = (int(x), int(y))
    _shown_at[owner] = time.monotonic()
    _visible[owner] = True


def _compose(color: tuple[int, int, int], label: str) -> tuple[int, int, bytes]:
    """Pointer, soft shadow, and a rounded name chip."""
    text_w, text_h, coverage = _text_coverage(label)
    arrow_w = max(len(row) for row in _ARROW)
    arrow_h = len(_ARROW)
    pad_x = 8
    pill_h = max(16, text_h + 5)
    pill_w = max(28, text_w + pad_x * 2)
    ax, ay = 2, 2
    pill_x = ax + arrow_w - 2
    pill_y = ay + arrow_h - 9
    width = pill_x + pill_w + 4
    height = max(ay + arrow_h, pill_y + pill_h) + 4
    buf = bytearray(width * height * 4)
    fills = [(ax + col, ay + row) for row, line in enumerate(_ARROW) for col, bit in enumerate(line) if bit == "#"]
    fill_set = set(fills)

    def put(px: int, py: int, red: int, green: int, blue: int, alpha: int) -> None:
        if alpha <= 0 or px < 0 or py < 0 or px >= width or py >= height:
            return
        index = (py * width + px) * 4
        inv = 255 - alpha
        buf[index] = (blue * alpha + buf[index] * inv) // 255
        buf[index + 1] = (green * alpha + buf[index + 1] * inv) // 255
        buf[index + 2] = (red * alpha + buf[index + 2] * inv) // 255
        buf[index + 3] = alpha + buf[index + 3] * inv // 255

    def chip(ox: int, oy: int, wide: int, high: int, red: int, green: int, blue: int, alpha: int) -> None:
        radius = high / 2
        for py in range(oy - 1, oy + high + 1):
            for px in range(ox - 1, ox + wide + 1):
                cx = px + 0.5
                cy = py + 0.5
                ix = min(max(cx, ox + radius), ox + wide - radius)
                iy = min(max(cy, oy + radius), oy + high - radius)
                dist = ((cx - ix) ** 2 + (cy - iy) ** 2) ** 0.5
                cover = radius - dist
                if cover >= 1:
                    put(px, py, red, green, blue, alpha)
                elif cover > 0:
                    put(px, py, red, green, blue, int(alpha * cover))

    for px, py in fills:
        put(px + 1, py + 2, 0, 0, 0, 70)
    chip(pill_x + 1, pill_y + 2, pill_w, pill_h, 0, 0, 0, 70)
    for px, py in fills:
        for nx in (px - 1, px, px + 1):
            for ny in (py - 1, py, py + 1):
                if (nx, ny) not in fill_set:
                    put(nx, ny, 255, 255, 255, 255)
    for px, py in fills:
        put(px, py, color[0], color[1], color[2], 255)
    chip(pill_x - 1, pill_y - 1, pill_w + 2, pill_h + 2, 255, 255, 255, 255)
    chip(pill_x, pill_y, pill_w, pill_h, color[0], color[1], color[2], 255)
    tx = pill_x + (pill_w - text_w) // 2
    ty = pill_y + (pill_h - text_h) // 2
    for row in range(text_h):
        for col in range(text_w):
            cover = coverage[row * text_w + col]
            if cover:
                put(tx + col + 1, ty + row + 1, 0, 0, 0, cover * 140 // 255)
    for row in range(text_h):
        for col in range(text_w):
            cover = coverage[row * text_w + col]
            if cover:
                put(tx + col, ty + row, 255, 255, 255, cover)
    return width, height, bytes(buf)


def _text_coverage(label: str) -> tuple[int, int, list[int]]:
    import ctypes
    from ctypes import wintypes

    gdi32 = ctypes.windll.gdi32
    user32 = ctypes.windll.user32

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = (
            ("biSize", ctypes.c_uint32),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", ctypes.c_ushort),
            ("biBitCount", ctypes.c_ushort),
            ("biCompression", ctypes.c_uint32),
            ("biSizeImage", ctypes.c_uint32),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", ctypes.c_uint32),
            ("biClrImportant", ctypes.c_uint32),
        )

    class BITMAPINFO(ctypes.Structure):
        _fields_ = (("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32))

    get_dc = ctypes.WINFUNCTYPE(wintypes.HDC, wintypes.HWND)(("GetDC", user32))
    release = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, wintypes.HDC)(("ReleaseDC", user32))
    make_dc = ctypes.WINFUNCTYPE(wintypes.HDC, wintypes.HDC)(("CreateCompatibleDC", gdi32))
    section = ctypes.WINFUNCTYPE(
        wintypes.HBITMAP,
        wintypes.HDC,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.HANDLE,
        wintypes.DWORD,
    )(("CreateDIBSection", gdi32))
    select = ctypes.WINFUNCTYPE(wintypes.HGDIOBJ, wintypes.HDC, wintypes.HGDIOBJ)(("SelectObject", gdi32))
    drop_dc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HDC)(("DeleteDC", gdi32))
    drop = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HGDIOBJ)(("DeleteObject", gdi32))
    font_new = ctypes.WINFUNCTYPE(
        wintypes.HFONT,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_wchar_p,
    )(("CreateFontW", gdi32))
    bk = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HDC, ctypes.c_int)(("SetBkMode", gdi32))
    ink = ctypes.WINFUNCTYPE(wintypes.DWORD, wintypes.HDC, wintypes.DWORD)(("SetTextColor", gdi32))
    text = ctypes.WINFUNCTYPE(
        ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p, ctypes.c_int
    )(("TextOutW", gdi32))
    wide, high = 180, 28
    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = wide
    info.bmiHeader.biHeight = -high
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    bits = ctypes.c_void_p()
    screen = get_dc(None)
    bitmap = section(screen, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
    memory = make_dc(screen)
    old = select(memory, bitmap)
    font = font_new(-13, 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 4, 0, "Segoe UI")
    old_font = select(memory, font)
    bk(memory, 1)
    ink(memory, 0x00FFFFFF)
    text(memory, 0, 2, label, len(label))
    raw = ctypes.string_at(bits.value, wide * high * 4) if bits.value else b""
    if old_font:
        select(memory, old_font)
    drop(font)
    if old:
        select(memory, old)
    drop(bitmap)
    drop_dc(memory)
    release(None, screen)
    if not raw:
        return 8 * max(1, len(label)), 14, [0] * (8 * max(1, len(label)) * 14)
    used = [index for index, cover in enumerate(raw[2::4]) if cover]
    if not used:
        return 4, 4, [0, 0, 0, 0] * 4
    cols = [index % wide for index in used]
    rows = [index // wide for index in used]
    left, right = min(cols), max(cols)
    top, bottom = min(rows), max(rows)
    crop_w = right - left + 1
    crop_h = bottom - top + 1
    coverage = []
    for row in range(top, bottom + 1):
        start = row * wide
        for col in range(left, right + 1):
            coverage.append(raw[(start + col) * 4 + 2])
    return crop_w, crop_h, coverage


def _paint_layered(user32, hwnd: int, left: int, top: int, width: int, height: int, pixels: bytes) -> None:
    import ctypes
    from ctypes import wintypes

    gdi32 = ctypes.windll.gdi32

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = (
            ("biSize", ctypes.c_uint32),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", ctypes.c_ushort),
            ("biBitCount", ctypes.c_ushort),
            ("biCompression", ctypes.c_uint32),
            ("biSizeImage", ctypes.c_uint32),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", ctypes.c_uint32),
            ("biClrImportant", ctypes.c_uint32),
        )

    class BITMAPINFO(ctypes.Structure):
        _fields_ = (("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32))

    class POINT(ctypes.Structure):
        _fields_ = (("x", ctypes.c_long), ("y", ctypes.c_long))

    class SIZE(ctypes.Structure):
        _fields_ = (("cx", ctypes.c_long), ("cy", ctypes.c_long))

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = (
            ("BlendOp", ctypes.c_ubyte),
            ("BlendFlags", ctypes.c_ubyte),
            ("SourceConstantAlpha", ctypes.c_ubyte),
            ("AlphaFormat", ctypes.c_ubyte),
        )

    get_dc = ctypes.WINFUNCTYPE(wintypes.HDC, wintypes.HWND)(("GetDC", user32))
    release = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, wintypes.HDC)(("ReleaseDC", user32))
    make_dc = ctypes.WINFUNCTYPE(wintypes.HDC, wintypes.HDC)(("CreateCompatibleDC", gdi32))
    section = ctypes.WINFUNCTYPE(
        wintypes.HBITMAP,
        wintypes.HDC,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.HANDLE,
        wintypes.DWORD,
    )(("CreateDIBSection", gdi32))
    select = ctypes.WINFUNCTYPE(wintypes.HGDIOBJ, wintypes.HDC, wintypes.HGDIOBJ)(("SelectObject", gdi32))
    drop_dc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HDC)(("DeleteDC", gdi32))
    drop = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HGDIOBJ)(("DeleteObject", gdi32))
    update = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.HDC,
        ctypes.POINTER(POINT),
        ctypes.POINTER(SIZE),
        wintypes.HDC,
        ctypes.POINTER(POINT),
        wintypes.DWORD,
        ctypes.POINTER(BLENDFUNCTION),
        wintypes.DWORD,
    )(("UpdateLayeredWindow", user32))
    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    bits = ctypes.c_void_p()
    screen = get_dc(None)
    bitmap = section(screen, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
    memory = make_dc(screen)
    old = select(memory, bitmap)
    if bits.value and len(pixels) == width * height * 4:
        ctypes.memmove(bits.value, pixels, len(pixels))
    origin = POINT(0, 0)
    dest = POINT(left, top)
    size = SIZE(width, height)
    blend = BLENDFUNCTION(0, 0, 255, 1)
    update(hwnd, screen, ctypes.byref(dest), ctypes.byref(size), memory, ctypes.byref(origin), 0, ctypes.byref(blend), 2)
    if old:
        select(memory, old)
    drop(bitmap)
    drop_dc(memory)
    release(None, screen)
    _window_show(user32, hwnd, 8)
    raise_top = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    )(("SetWindowPos", user32))
    raise_top(hwnd, wintypes.HWND(-1), left, top, width, height, 0x0010 | 0x0040)


def _window_show(user32, hwnd: int, command: int) -> None:
    import ctypes
    from ctypes import wintypes

    show = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, ctypes.c_int)(("ShowWindow", user32))
    show(hwnd, command)


def _cursor_pos(user32):
    import ctypes
    from ctypes import wintypes

    class POINT(ctypes.Structure):
        _fields_ = (("x", ctypes.c_long), ("y", ctypes.c_long))

    point = POINT()
    found = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.POINTER(POINT))(("GetCursorPos", user32))
    if not found(ctypes.byref(point)):
        return None
    return int(point.x), int(point.y)


def _validate(hwnd: int) -> None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    class PAINTSTRUCT(ctypes.Structure):
        _fields_ = (
            ("hdc", wintypes.HDC),
            ("fErase", wintypes.BOOL),
            ("rcPaint", wintypes.RECT),
            ("fRestore", wintypes.BOOL),
            ("fIncUpdate", wintypes.BOOL),
            ("rgbReserved", ctypes.c_char * 32),
        )

    begin = ctypes.WINFUNCTYPE(wintypes.HDC, wintypes.HWND, ctypes.POINTER(PAINTSTRUCT))(("BeginPaint", user32))
    end = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, ctypes.POINTER(PAINTSTRUCT))(("EndPaint", user32))
    paint = PAINTSTRUCT()
    begin(hwnd, ctypes.byref(paint))
    end(hwnd, ctypes.byref(paint))
