"""桌宠脉搏：守护 / 通知 / 对话气泡 / 待机插播。"""

from __future__ import annotations

import random

from PyQt6.QtCore import Qt

from desktop_pet.activities import read_last_events, read_last_notify


def pulse_action(ev: dict) -> str:
    """贴边气泡跟脉搏：开始出示，结束改「在想」，空闲收掉。"""
    status = (ev or {}).get("status") or ""
    if status == "idle":
        return "hide"
    if status == "start" and str((ev or {}).get("desc") or "").strip():
        return "show"
    if status in ("end", "error"):
        return "think"
    return "keep"
from desktop_pet.clip_map import (
    GUARD_CUE,
    IDLE_SIDE_MAX_S,
    IDLE_SIDE_MIN_S,
    IDLE_SIDES,
    ONCE_CLIPS,
    WORK_STATES,
    frame_path,
    read_guard_open,
)
from desktop_pet.expressions import DEFAULT_STATE
from desktop_pet.room_dock import (
    emerge,
    maybe_redock,
    move_dock,
    play_done_sound,
    press_dock,
    release_dock,
    sync_confirm,
)
from desktop_pet.room_hit import alpha_at_widget
from desktop_pet.room_rest import take_cmd, wake_from_rest, write_live
from desktop_pet.room_sync import apply_work_face, wake_if_working


def arm_side(pet) -> None:
    pet._side.start(random.randint(IDLE_SIDE_MIN_S, IDLE_SIDE_MAX_S) * 1000)


def play_side(pet) -> None:
    if (
        pet._state != DEFAULT_STATE
        or pet._guard
        or pet._dragging
        or pet._resting
        or pet._getting_up
        or pet._poking
        or pet._clip_id in ONCE_CLIPS
        or getattr(pet, "_docked", False)
    ):
        arm_side(pet)
        return
    pool = [c for c in IDLE_SIDES if frame_path(c)]
    if pool:
        pet._play_clip(random.choice(pool), once=True)
    arm_side(pet)


def _wake_drag(pet) -> None:
    pet._poking = True
    pet._side.stop()
    pet._rest.stop()
    if pet._resting or pet._getting_up:
        wake_from_rest(pet, "drag")
        return
    if pet._clip_id == "drag":
        pet._fi = 0
        pet._once = False
        pet._hold = False
        if not pet._anim.isActive():
            pet._anim.start(83)
        pet._anim.setInterval(83)
        pet._paint_frame()
        return
    pet._play_clip("drag")


def press_drag(pet, e) -> None:
    if press_dock(pet, e):
        return
    if e.button() == Qt.MouseButton.LeftButton:
        if alpha_at_widget(pet, e.position().toPoint()) < 16:
            e.ignore()
            return
        pet._drag_off = None if pet._locked else e.globalPosition().toPoint() - pet.frameGeometry().topLeft()
        _wake_drag(pet)
        e.accept()
        return
    if e.button() == Qt.MouseButton.RightButton:
        pet._menu.exec(e.globalPosition().toPoint())
        e.accept()


def move_drag(pet, e) -> None:
    if move_dock(pet, e):
        return
    if pet._locked or pet._drag_off is None or not (e.buttons() & Qt.MouseButton.LeftButton):
        return
    dest = e.globalPosition().toPoint() - pet._drag_off
    if not pet._dragging:
        if (dest - pet.frameGeometry().topLeft()).manhattanLength() < 4:
            return
        pet._dragging = True
        pet._poking = False
        if pet._clip_id != "drag":
            _wake_drag(pet)
    pet.move(dest)
    pet._bubble.follow(pet)
    e.accept()


def release_drag(pet, e) -> None:
    if release_dock(pet, e):
        return
    if e.button() != Qt.MouseButton.LeftButton:
        return
    was = pet._dragging
    poking = pet._poking
    pet._drag_off = None
    pet._dragging = False
    if pet._getting_up:
        if was:
            pet._save_pos()
        e.accept()
        return
    if was:
        pet._poking = False
        pet._save_pos()
        if pet._state in WORK_STATES:
            pet._play_state(pet._state)
        else:
            pet._play_state(DEFAULT_STATE)
        e.accept()
        return
    if poking:
        pet._once = True
    e.accept()


def _poll_while_down(pet) -> None:
    write_live(pet)
    try:
        notes = read_last_notify(1)
        if notes:
            nts = float(notes[-1].get("ts", 0) or 0)
            if nts > pet._last_notify_ts:
                pet._last_notify_ts = nts
    except Exception:
        pass
    _apply_pulse(pet, waiting=pet._bubble._sticky)
    wake_if_working(pet)


def tick_poll(pet) -> None:
    if pet._dragging:
        return
    take_cmd(pet)
    waiting = sync_confirm(pet)
    if pet._resting or pet._getting_up:
        _poll_while_down(pet)
        return
    try:
        mt = GUARD_CUE.stat().st_mtime if GUARD_CUE.exists() else 0.0
    except Exception:
        mt = 0.0
    if mt and mt != pet._last_guard_mtime:
        pet._last_guard_mtime = mt
        if read_guard_open():
            pet._guard = True
            emerge(pet, "guard")
            pet._play_clip("guard")
            pet._bubble.show_text("守护中", sticky=True)
            pet._bubble.follow(pet)
            return
        if pet._guard:
            pet._guard = False
            if not waiting:
                pet._bubble._sticky = False
            pet._play_state(pet._state)
    elif pet._guard and read_guard_open():
        return
    try:
        notes = read_last_notify(2)
        if notes:
            latest = notes[-1]
            nts = float(latest.get("ts", 0) or 0)
            if nts > pet._last_notify_ts:
                pet._last_notify_ts = nts
                kind = latest.get("kind", "info")
                text = latest.get("text", "")
                if kind == "done":
                    emerge(pet, "done")
                    pet._state = DEFAULT_STATE
                    pet._play_clip("work_done", once=True)
                    play_done_sound(pet)
                    pet._bubble.show_text(text or "做完了", 6000)
                    pet._bubble.follow(pet)
                    return
                if kind == "confirm" and text:
                    emerge(pet, "guard")
                    pet._bubble.show_text(text, sticky=True)
                    pet._bubble.follow(pet)
                    return
                if text and not waiting:
                    pet._bubble.show_text(text, 8000)
                    pet._bubble.follow(pet)
    except Exception:
        pass
    _apply_pulse(pet, waiting)
    apply_work_face(pet)
    maybe_redock(pet)


def _apply_pulse(pet, waiting: bool) -> None:
    try:
        evs = read_last_events(1)
        if not evs:
            return
        ev = evs[-1]
        ts = float(ev.get("ts", 0) or 0)
        if ts <= pet._last_pulse_ts:
            return
        pet._last_pulse_ts = ts
        if waiting:
            return
        act = pulse_action(ev)
        if act == "show":
            pet._bubble.show_text(str(ev.get("desc") or "").strip())
            pet._bubble.follow(pet)
        elif act == "think":
            pet._bubble.show_text("在想")
            pet._bubble.follow(pet)
        elif act == "hide" and not pet._bubble._sticky:
            pet._bubble.hide()
    except Exception:
        pass
