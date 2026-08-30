"""小房间桌宠 · 透明 WebP 逐帧画 · 文件桥跟橙猫同一套。"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QWidget

from desktop_pet.activities import read_last_notify
from desktop_pet.clip_map import (
    BASE_WH,
    BLINK_GAP_MAX_MS,
    BLINK_GAP_MIN_MS,
    BLINK_MS,
    BLINK_TAKE,
    IDLE_MAIN,
    ONCE_CLIPS,
    ONCE_MOODS,
    ROOM_POS,
    clips_for,
    frame_path,
    load_lock,
    load_pct,
    read_guard_open,
)
from desktop_pet.expressions import DEFAULT_STATE
from desktop_pet.room_hit import alpha_at_widget
from desktop_pet.room_live import (
    arm_rest,
    arm_side,
    go_rest,
    move_drag,
    play_side,
    press_drag,
    release_drag,
    tick_poll,
)
from desktop_pet.room_sync import finish_once
from desktop_pet.room_dock import expand, load_dock, load_flip, paint_ape
from desktop_pet.room_menu import apply_geom, build_menu, open_chat
from desktop_pet.room_rest import wake_from_rest, write_live
from desktop_pet.room_bubble import RoomBubble
from desktop_pet.room_frames import load_clip_pixmaps, preload_scale
from desktop_pet.room_win32 import enable_dpi, force_show, reveal

PET_DIR = Path(__file__).resolve().parent
STATE_FILE = PET_DIR / "state.txt"
BOOT_LOG = PET_DIR / "boot.log"
FRAME_MS = 83


class RoomPet(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Daemonkey 桌宠")
        self._pct = load_pct()
        self._locked = load_lock()
        self._want_dock, self._dock_edge = load_dock()
        self._docked = bool(self._want_dock)
        self._flip = load_flip()
        apply_geom(self)
        self._state = DEFAULT_STATE
        self._clip_id = ""
        self._pix: list[QPixmap] = []
        self._fi = 0
        self._once = False
        self._hold = False
        self._blink_hold = False
        self._resting = False
        self._getting_up = False
        self._wake_next = ""
        self._guard = False
        self._dragging = False
        self._poking = False
        self._drag_off: QPoint | None = None
        self._last_state_txt = ""
        self._last_notify_ts = 0.0
        self._last_guard_mtime = 0.0
        self._last_pulse_ts = 0.0
        self._hit = QImage()
        self._bubble = RoomBubble()
        try:
            notes = read_last_notify(1)
            if notes:
                self._last_notify_ts = float(notes[-1].get("ts", 0) or 0)
        except Exception:
            pass
        self._peek_t = QTimer(self)
        self._peek_t.setSingleShot(True)
        self._peek_t.timeout.connect(lambda: expand(self, keep_want=False))
        self._menu = build_menu(self)
        self._anim = QTimer(self)
        self._anim.timeout.connect(self._tick_frame)
        self._anim.start(FRAME_MS)
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._tick_poll)
        self._poll.start(800)
        self._side = QTimer(self)
        self._side.setSingleShot(True)
        self._side.timeout.connect(lambda: play_side(self))
        self._rest = QTimer(self)
        self._rest.setSingleShot(True)
        self._rest.timeout.connect(lambda: go_rest(self))
        self._state_file = STATE_FILE
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            STATE_FILE.write_text(DEFAULT_STATE, encoding="utf-8")
        except Exception:
            pass
        self._last_state_txt = DEFAULT_STATE
        self._play_state(DEFAULT_STATE)
        QTimer.singleShot(200, preload_scale)

    def _play_clip(
        self, clip_id: str, *, once: bool = False, hold: bool = False, take=None
    ) -> None:
        path = frame_path(clip_id)
        if not path:
            return
        if take is None:
            take = BLINK_TAKE if clip_id == IDLE_MAIN else None
        if clip_id == self._clip_id and self._pix and not hold and take is None:
            return
        tw, th = BASE_WH
        try:
            self._pix = load_clip_pixmaps(path, tw, th, take)
        except Exception:
            self._pix = []
            return
        self._clip_id = clip_id
        self._fi = 0
        self._once = once or clip_id in ONCE_CLIPS
        self._hold = hold
        if not self._anim.isActive():
            self._anim.start(FRAME_MS)
        if clip_id == IDLE_MAIN:
            self._blink_hold = True
            self._anim.setInterval(random.randint(BLINK_GAP_MIN_MS, BLINK_GAP_MAX_MS))
        else:
            self._blink_hold = False
            self._anim.setInterval(FRAME_MS)
        self._paint_frame()
        write_live(self)

    def _play_state(self, state: str) -> None:
        ids = clips_for(state) or clips_for("idle")
        if not ids:
            return
        down = self._resting or self._getting_up
        if down and state in ("working", "thinking"):
            self._state = state
            self._wake_next = "work" if self._getting_up else wake_from_rest(self, "work") or "work"
            return
        if down and state in ONCE_MOODS:
            return
        self._resting = False
        self._poking = False
        self._state = state
        self._play_clip(ids[0], once=ids[0] in ONCE_CLIPS or state in ONCE_MOODS)
        if state == DEFAULT_STATE:
            arm_side(self)
            if not self._rest.isActive():
                arm_rest(self)
            if not self._bubble._sticky and not self._bubble._hide.isActive():
                self._bubble.hide()
        else:
            self._side.stop()
            self._rest.stop()

    def _paint_frame(self) -> None:
        if not self._pix:
            return
        if not self._dragging:
            self._hit = self._pix[self._fi % len(self._pix)].toImage()
        self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self._flip:
            p.translate(self.width(), 0)
            p.scale(-1, 1)
        if self._docked:
            paint_ape(p, self.width(), self.height())
            return
        if not self._pix:
            return
        p.drawPixmap(self.rect(), self._pix[self._fi % len(self._pix)])

    def _tick_frame(self) -> None:
        if not self._pix:
            return
        nxt = self._fi + 1
        if nxt >= len(self._pix):
            if self._guard and read_guard_open():
                self._fi = 0
                self._paint_frame()
                return
            if self._hold:
                self._fi = len(self._pix) - 1
                self._anim.stop()
                self._paint_frame()
                write_live(self)
                return
            if self._once:
                finish_once(self)
                return
            if self._clip_id == IDLE_MAIN:
                self._fi = 0
                self._blink_hold = True
                self._anim.setInterval(random.randint(BLINK_GAP_MIN_MS, BLINK_GAP_MAX_MS))
                self._paint_frame()
                return
            self._fi = 0
            self._paint_frame()
            return
        if self._blink_hold:
            self._blink_hold = False
            self._anim.setInterval(BLINK_MS)
        self._fi = nxt
        self._paint_frame()

    def _tick_poll(self) -> None:
        tick_poll(self)

    def _user_state(self, state: str) -> None:
        try:
            STATE_FILE.write_text(state, encoding="utf-8")
        except Exception:
            pass
        self._last_state_txt = state
        self._play_state(state)

    def _save_pos(self) -> None:
        try:
            ROOM_POS.write_text(f"{self.x()},{self.y()}", encoding="utf-8")
        except Exception:
            pass

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        reveal(self)
        self._bubble.follow(self)

    def mouseDoubleClickEvent(self, e) -> None:
        self._peek_t.stop()
        if e.button() == Qt.MouseButton.LeftButton and alpha_at_widget(self, e.position().toPoint()) >= 16:
            open_chat()
            e.accept()
            return
        e.ignore()

    def mousePressEvent(self, e) -> None:
        press_drag(self, e)

    def mouseMoveEvent(self, e) -> None:
        move_drag(self, e)

    def mouseReleaseEvent(self, e) -> None:
        release_drag(self, e)

def main() -> int:
    enable_dpi()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    pet = RoomPet()
    hwnd = force_show(pet)
    from desktop_pet.room_dock import dock as _dock

    def _boot() -> None:
        if pet._want_dock:
            _dock(pet)
        else:
            reveal(pet)

    QTimer.singleShot(0, _boot)
    QTimer.singleShot(400, _boot)
    try:
        g = pet.geometry()
        BOOT_LOG.write_text(
            f"pct={pet._pct} clip={pet._clip_id} frames={len(pet._pix)} "
            f"geo={g.x()},{g.y()} {g.width()}x{g.height()} hwnd={hwnd}\n",
            encoding="utf-8",
        )
    except Exception:
        pass
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
