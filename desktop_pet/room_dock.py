"""贴边猴头 · 完成/GUARD 才展开房间 · 水平翻转落在绘制侧。"""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QPainter
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QWidget

from desktop_pet.activities import read_confirm
from desktop_pet.clip_map import ROOM_POS
from desktop_pet.room_win32 import _work_area

PET_DIR = Path(__file__).resolve().parent
APE_SVG = PET_DIR / "ape.svg"
DOCK_FILE = PET_DIR / "room_dock.txt"
FLIP_FILE = PET_DIR / "room_flip.txt"
_DONE_WAV = PET_DIR.parent / "ding" / "manbo.wav"
_NOTIFY_CFG = PET_DIR.parent / "data" / "notification_config.json"
DOCK_N = 64
_APE: QSvgRenderer | None = None


def _ape() -> QSvgRenderer:
    global _APE
    if _APE is None:
        _APE = QSvgRenderer(str(APE_SVG))
    return _APE


def load_flip() -> bool:
    try:
        return FLIP_FILE.read_text(encoding="utf-8").strip() == "1"
    except Exception:
        return False


def save_flip(on: bool) -> None:
    try:
        FLIP_FILE.write_text("1" if on else "0", encoding="utf-8")
    except Exception:
        pass


def load_dock() -> tuple[bool, str]:
    try:
        raw = DOCK_FILE.read_text(encoding="utf-8-sig").strip()
        if not raw:
            return False, "right"
        edge = raw if raw in ("left", "right", "top", "bottom") else "right"
        return True, edge
    except Exception:
        return False, "right"


def save_dock(on: bool, edge: str) -> None:
    try:
        DOCK_FILE.write_text(edge if on else "", encoding="utf-8")
    except Exception:
        pass


def paint_ape(p: QPainter, w: int, h: int) -> None:
    _ape().render(p, QRectF(0, 0, w, h))


def nearest_edge(pet: QWidget) -> str:
    r = _work_area()
    cx = pet.x() + pet.width() // 2
    cy = pet.y() + pet.height() // 2
    d = {
        "left": cx - r.left,
        "right": r.right - cx,
        "top": cy - r.top,
        "bottom": r.bottom - cy,
    }
    return min(d, key=d.get)


def snap_dock(pet) -> None:
    r = _work_area()
    cx = pet.x() + pet.width() // 2
    cy = pet.y() + pet.height() // 2
    pet.setFixedSize(DOCK_N, DOCK_N)
    edge = getattr(pet, "_dock_edge", None) or "right"
    pet._dock_edge = edge
    pad = 4
    if edge == "right":
        x, y = r.right - DOCK_N - pad, cy - DOCK_N // 2
    elif edge == "left":
        x, y = r.left + pad, cy - DOCK_N // 2
    elif edge == "top":
        x, y = cx - DOCK_N // 2, r.top + pad
    else:
        x, y = cx - DOCK_N // 2, r.bottom - DOCK_N - pad
    x = max(r.left, min(x, r.right - DOCK_N))
    y = max(r.top, min(y, r.bottom - DOCK_N))
    pet.move(x, y)
    bub = getattr(pet, "_bubble", None)
    if bub is not None:
        bub.follow(pet)


def dock(pet) -> None:
    if not pet._docked:
        try:
            ROOM_POS.write_text(f"{pet.x()},{pet.y()}", encoding="utf-8")
        except Exception:
            pass
        pet._dock_edge = nearest_edge(pet)
    pet._want_dock = True
    pet._docked = True
    save_dock(True, pet._dock_edge)
    snap_dock(pet)
    pet.update()


def expand(pet, *, keep_want: bool = True) -> None:
    pet._docked = False
    if not keep_want:
        pet._want_dock = False
        save_dock(False, pet._dock_edge)
        act = getattr(pet, "_dock_act", None)
        if act is not None:
            act.blockSignals(True)
            act.setChecked(False)
            act.blockSignals(False)
    from desktop_pet.room_menu import apply_geom
    apply_geom(pet)
    try:
        raw = ROOM_POS.read_text(encoding="utf-8").strip()
        x, y = (int(p) for p in raw.split(",", 1))
        pet.move(x, y)
    except Exception:
        pass
    pet.update()
    pet._bubble.follow(pet)


def emerge(pet, _reason: str = "") -> None:
    if pet._docked:
        expand(pet, keep_want=True)


def maybe_redock(pet) -> None:
    if not getattr(pet, "_want_dock", False) or pet._docked:
        return
    if pet._guard or pet._clip_id in ("work_done", "guard"):
        return
    if pet._bubble._sticky:
        return
    dock(pet)


def press_dock(pet, e) -> bool:
    if not getattr(pet, "_docked", False):
        return False
    if e.button() == Qt.MouseButton.LeftButton:
        if not pet._locked:
            pet._drag_off = e.globalPosition().toPoint() - pet.frameGeometry().topLeft()
        e.accept()
        return True
    if e.button() == Qt.MouseButton.RightButton:
        pet._menu.exec(e.globalPosition().toPoint())
        e.accept()
        return True
    return False


def move_dock(pet, e) -> bool:
    if not getattr(pet, "_docked", False):
        return False
    if pet._locked or pet._drag_off is None or not (e.buttons() & Qt.MouseButton.LeftButton):
        return True
    dest = e.globalPosition().toPoint() - pet._drag_off
    if not pet._dragging:
        if (dest - pet.frameGeometry().topLeft()).manhattanLength() < 4:
            return True
        pet._dragging = True
    pet.move(dest)
    pet._bubble.follow(pet)
    e.accept()
    return True


def release_dock(pet, e) -> bool:
    if not getattr(pet, "_docked", False):
        return False
    if e.button() != Qt.MouseButton.LeftButton:
        return True
    was = pet._dragging
    pet._drag_off = None
    pet._dragging = False
    if was:
        pet._dock_edge = nearest_edge(pet)
        snap_dock(pet)
        save_dock(True, pet._dock_edge)
        e.accept()
        return True
    if getattr(pet, "_play_on", False):
        hook = getattr(pet, "_play", None)
        if hook is not None:
            hook.tap()
        e.accept()
        return True
    t = getattr(pet, "_peek_t", None)
    if t is not None:
        t.start(280)
    e.accept()
    return True


def play_done_sound(pet) -> None:
    try:
        if _NOTIFY_CFG.exists():
            cfg = json.loads(_NOTIFY_CFG.read_text(encoding="utf-8"))
            if isinstance(cfg, dict) and not cfg.get("pet_sound", True):
                return
    except Exception:
        pass
    try:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtMultimedia import QSoundEffect
        if getattr(pet, "_done_sound", None) is None:
            if not _DONE_WAV.exists():
                return
            snd = QSoundEffect(pet)
            snd.setSource(QUrl.fromLocalFile(str(_DONE_WAV)))
            snd.setVolume(0.8)
            pet._done_sound = snd
        pet._done_sound.play()
    except Exception:
        pass


def sync_confirm(pet) -> bool:
    txt = read_confirm()
    if txt:
        if not pet._bubble._sticky or pet._bubble._text != txt:
            pet._bubble.show_text(txt, sticky=True)
        pet._bubble.follow(pet)
        return True
    if pet._bubble._sticky and pet._bubble._text.startswith("等你拍板"):
        pet._bubble._sticky = False
        pet._bubble.hide()
    return False
