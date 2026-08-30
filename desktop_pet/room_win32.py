"""启动器 WindowStyle Hidden 会把第一扇窗的 Show 改成 SW_HIDE。"""

from __future__ import annotations

import sys


def _work_area():
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
    return rect


def pin_center(widget) -> None:
    if sys.platform != "win32":
        return
    import ctypes

    r = _work_area()
    w, h = widget.width(), widget.height()
    x = r.left + (r.right - r.left - w) // 2
    y = r.top + (r.bottom - r.top - h) // 2
    ctypes.windll.user32.MoveWindow(int(widget.winId()), x, y, w, h, True)


def reveal(widget) -> int:
    if sys.platform != "win32":
        return 0
    import ctypes

    hwnd = int(widget.winId())
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 8)
    user32.ShowWindow(hwnd, 5)
    if not getattr(widget, "_docked", False) and not getattr(widget, "_want_dock", False):
        pin_center(widget)
    return hwnd


def enable_dpi() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


def force_show(widget) -> int:
    widget.show()
    widget.raise_()
    widget.showNormal()
    return reveal(widget)
