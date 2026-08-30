"""陪伴纸色对话气泡 · 跟 #say-bubble 同一套暖杏纸。"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRect, QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

_LIVE = Path(__file__).resolve().parent / "bubble.txt"

FACE = QColor("#FFFEF8")
SHADE = QColor("#C4B49A")
INK = QColor("#453B26")
FONT = QFont("Microsoft YaHei", 11, QFont.Weight.DemiBold)
PAD = 12
MAX_W = 220


class RoomBubble(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._text = ""
        self._sticky = False
        self._hide = QTimer(self)
        self._hide.setSingleShot(True)
        self._hide.timeout.connect(self.hide)

    def show_text(self, text: str, ms: int = 0, *, sticky: bool = False) -> None:
        text = (text or "").strip()
        if not text:
            self._sticky = False
            self.hide()
            return
        self._text = text
        self._sticky = sticky
        self.setFont(FONT)
        tw, th = self._box_for(text)
        self.resize(tw, th)
        self.update()
        self.show()
        self.raise_()
        if sticky:
            self._hide.stop()
        elif ms > 0:
            self._hide.start(ms)
        else:
            self._hide.stop()
        self._dump()

    def hide(self) -> None:
        super().hide()
        self._dump()

    def _dump(self) -> None:
        try:
            _LIVE.write_text(
                f"vis={int(self.isVisible())} sticky={int(self._sticky)} "
                f"x={self.x()} y={self.y()} w={self.width()} h={self.height()} "
                f"text={self._text}\n",
                encoding="utf-8",
            )
        except Exception:
            pass

    def _box_for(self, text: str) -> tuple[int, int]:
        fm = self.fontMetrics()
        flags = Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap
        laid = fm.boundingRect(0, 0, MAX_W - PAD * 2, 400, flags, text)
        ink = fm.tightBoundingRect(text)
        single = laid.height() <= fm.lineSpacing() + 4
        text_h = ink.height() if single else max(ink.height(), laid.height() - fm.descent())
        text_w = max(ink.width(), min(laid.width(), MAX_W - PAD * 2))
        return min(MAX_W, text_w + PAD * 2 + 4), text_h + PAD * 2 + 10

    def follow(self, host: QWidget) -> None:
        if not self.isVisible():
            return
        if getattr(host, "_docked", False):
            self._follow_dock(host)
            return
        # 头大约在窗宽四成、窗高三成 · 气泡贴头右上（BRO 标的红箭头）
        hx, hy = host.x(), host.y()
        self.move(
            hx + int(host.width() * 0.48),
            hy + int(host.height() * 0.30) - self.height() + 4,
        )
        self._dump()

    def _follow_dock(self, host: QWidget) -> None:
        # 贴边时气泡朝屏幕里侧，别贴出屏外
        edge = getattr(host, "_dock_edge", "right")
        hx, hy, hw, hh = host.x(), host.y(), host.width(), host.height()
        if edge == "right":
            self.move(hx - self.width() + 6, hy + hh // 2 - self.height() // 2)
        elif edge == "left":
            self.move(hx + hw - 6, hy + hh // 2 - self.height() // 2)
        elif edge == "top":
            self.move(hx + hw // 2 - self.width() // 2, hy + hh - 4)
        else:
            self.move(hx + hw // 2 - self.width() // 2, hy - self.height() + 8)
        self._dump()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        body = h - 10
        shade = QPainterPath()
        shade.addRoundedRect(2, 2, w - 2, body, 16, 16)
        face = QPainterPath()
        face.addRoundedRect(0, 0, w - 2, body, 16, 16)
        tail_s = QPainterPath()
        tail_s.moveTo(w * 0.18 + 2, body + 2)
        tail_s.lineTo(w * 0.18 + 16, body + 2)
        tail_s.lineTo(w * 0.08 + 2, h)
        tail_s.closeSubpath()
        tail = QPainterPath()
        tail.moveTo(w * 0.18, body)
        tail.lineTo(w * 0.18 + 14, body)
        tail.lineTo(w * 0.08, h - 2)
        tail.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(SHADE)
        p.drawPath(shade.united(tail_s))
        p.setBrush(FACE)
        p.drawPath(face.united(tail))
        p.setPen(QPen(INK))
        p.setFont(FONT)
        self._paint_text(p, w, body)

    def _paint_text(self, p: QPainter, w: float, body: float) -> None:
        # YaHei 下行距 CJK 用不上 · AlignVCenter 会把字顶上去
        fm = p.fontMetrics()
        inner = max(8, int(w) - PAD * 2)
        flags = Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap
        laid = fm.boundingRect(0, 0, inner, 400, flags, self._text)
        ink = fm.tightBoundingRect(self._text)
        if laid.height() <= fm.lineSpacing() + 4:
            x = (w - 2 - ink.width()) / 2.0 - ink.x()
            y = (body - ink.height()) / 2.0 - ink.y()
            p.drawText(round(x), round(y), self._text)
            return
        top = int((body - (laid.height() - fm.descent())) / 2)
        p.drawText(
            QRect(PAD, top, inner, laid.height()),
            flags | Qt.AlignmentFlag.AlignTop,
            self._text,
        )
