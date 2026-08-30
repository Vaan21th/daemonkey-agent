"""透明像素点穿 · 灰抠掉之后别挡住桌面。"""

from __future__ import annotations

import sys

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QImage


def alpha_at(hit: QImage, p: QPoint) -> int:
    if hit.isNull():
        return 0
    x, y = p.x(), p.y()
    if x < 0 or y < 0 or x >= hit.width() or y >= hit.height():
        return 0
    return hit.pixelColor(x, y).alpha()


def alpha_at_widget(pet, p: QPoint) -> int:
    """窗被滑块拉伸后，点要映回底片像素。"""
    if getattr(pet, "_docked", False):
        cx, cy = pet.width() / 2, pet.height() / 2
        rad = min(pet.width(), pet.height()) * 0.42
        dx, dy = p.x() - cx, p.y() - cy
        return 255 if dx * dx + dy * dy <= rad * rad else 0
    hit = getattr(pet, "_hit", None)
    if hit is None or hit.isNull() or pet.width() <= 0 or pet.height() <= 0:
        return 0
    x = int(p.x() * hit.width() / pet.width())
    y = int(p.y() * hit.height() / pet.height())
    if getattr(pet, "_flip", False):
        x = hit.width() - 1 - x
    return alpha_at(hit, QPoint(x, y))


def nchittest(widget, eventType, message, hit: QImage):
    if sys.platform != "win32":
        return None
    et = bytes(eventType) if not isinstance(eventType, (bytes, bytearray)) else eventType
    if et != b"windows_generic_MSG":
        return None
    import ctypes
    from ctypes import wintypes

    msg = wintypes.MSG.from_address(int(message))
    if msg.message != 0x0084:
        return None
    lp = int(msg.lParam)
    x = ctypes.c_int16(lp & 0xFFFF).value
    y = ctypes.c_int16((lp >> 16) & 0xFFFF).value
    local = widget.mapFromGlobal(QPoint(x, y))
    # 第一帧还没来时整窗点穿 · 看起来就像没起来
    if hit.isNull():
        return True, 1
    if alpha_at(hit, local) < 16:
        return True, -1
    return True, 1
