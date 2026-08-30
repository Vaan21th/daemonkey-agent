"""对话还在跑时，收工片 / 情绪片不许把桌宠按回待机。"""

from __future__ import annotations

import random

from desktop_pet.activities import should_stay_working
from desktop_pet.clip_map import (
    IDLE_MAIN,
    IDLE_SIDE_MAX_S,
    IDLE_SIDE_MIN_S,
    ONCE_CLIPS,
    ONCE_MOODS,
    WORK_STATES,
)
from desktop_pet.expressions import DEFAULT_STATE, EXPRESSIONS
from desktop_pet.room_dock import maybe_redock
from desktop_pet.room_rest import after_getup, wake_from_rest


def _busy(pet) -> bool:
    try:
        txt = pet._state_file.read_text(encoding="utf-8").strip()
        return should_stay_working(txt) or pet._state in WORK_STATES
    except Exception:
        return pet._state in WORK_STATES


def finish_once(pet) -> None:
    pet._once = False
    if pet._getting_up:
        after_getup(pet)
        return
    pet._poking = False
    if pet._clip_id in ONCE_CLIPS:
        if _busy(pet):
            pet._last_state_txt = "working"
            pet._play_state("working")
            return
        if pet._state in WORK_STATES or pet._state in ONCE_MOODS:
            try:
                pet._state_file.write_text(DEFAULT_STATE, encoding="utf-8")
            except Exception:
                pass
            pet._last_state_txt = DEFAULT_STATE
        pet._play_state(DEFAULT_STATE)
        maybe_redock(pet)
        return
    if pet._state in WORK_STATES:
        pet._play_state(pet._state)
        return
    if pet._state in ONCE_MOODS or pet._clip_id == "drag":
        if pet._state in ONCE_MOODS:
            try:
                pet._state_file.write_text(DEFAULT_STATE, encoding="utf-8")
            except Exception:
                pass
            pet._last_state_txt = DEFAULT_STATE
        pet._play_state(DEFAULT_STATE)
        maybe_redock(pet)
        return
    pet._play_clip(IDLE_MAIN)
    pet._side.start(random.randint(IDLE_SIDE_MIN_S, IDLE_SIDE_MAX_S) * 1000)
    maybe_redock(pet)


def wake_if_working(pet) -> None:
    try:
        txt = pet._state_file.read_text(encoding="utf-8").strip()
        if not should_stay_working(txt):
            return
        if txt == pet._last_state_txt and pet._state in WORK_STATES:
            return
        pet._last_state_txt = "working"
        pet._state = "working"
        if pet._getting_up:
            pet._wake_next = "work"
        else:
            wake_from_rest(pet, "work")
    except Exception:
        pass


def apply_work_face(pet) -> None:
    try:
        txt = pet._state_file.read_text(encoding="utf-8").strip()
        if should_stay_working(txt) and pet._state not in WORK_STATES and not pet._guard:
            if pet._clip_id not in ONCE_CLIPS and not pet._dragging:
                pet._last_state_txt = "working"
                pet._play_state("working")
                return
        if txt and txt != pet._last_state_txt and txt in EXPRESSIONS:
            pet._last_state_txt = txt
            if getattr(pet, "_docked", False):
                pet._state = txt
            elif not pet._guard and pet._clip_id != "work_done":
                pet._play_state(txt)
    except Exception:
        pass
