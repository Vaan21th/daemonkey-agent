"""趴下停住 / 起身 / 监控文件。短插播不准碰这段。"""

from __future__ import annotations

import time
from pathlib import Path

from desktop_pet.clip_map import REST_AFTER_S, REST_CLIP, REST_DOWN, REST_UP, WORK_STATES
from desktop_pet.expressions import DEFAULT_STATE

PET_DIR = Path(__file__).resolve().parent
LIVE_FILE = PET_DIR / "live.txt"
CMD_FILE = PET_DIR / "rest.cmd"


def write_live(pet) -> None:
    try:
        b = getattr(pet, "_bubble", None)
        bub = ""
        if b is not None:
            bub = (
                f" bub={b._text!r} sticky={int(b._sticky)} "
                f"vis={int(b.isVisible())}"
            )
        LIVE_FILE.write_text(
            f"ts={time.time():.3f} clip={pet._clip_id} fi={pet._fi} "
            f"n={len(pet._pix)} hold={int(pet._hold)} rest={int(pet._resting)} "
            f"up={int(pet._getting_up)} next={pet._wake_next or '-'} "
            f"state={pet._state} poke={int(pet._poking)}{bub}\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def arm_rest(pet) -> None:
    pet._rest.start(REST_AFTER_S * 1000)


def go_rest(pet) -> None:
    if pet._state != DEFAULT_STATE or pet._guard or pet._dragging or pet._poking:
        arm_rest(pet)
        return
    if pet._getting_up:
        return
    pet._resting = True
    pet._getting_up = False
    pet._wake_next = ""
    pet._play_clip(REST_CLIP, once=True, hold=True, take=REST_DOWN)


def wake_from_rest(pet, nxt: str) -> None:
    """nxt: idle / drag / work · 从趴桌帧播到坐起来。"""
    pet._resting = False
    pet._getting_up = True
    pet._wake_next = nxt
    pet._side.stop()
    pet._rest.stop()
    pet._play_clip(REST_CLIP, once=True, take=REST_UP)


def after_getup(pet) -> None:
    pet._getting_up = False
    nxt = pet._wake_next or "idle"
    pet._wake_next = ""
    if nxt == "drag":
        pet._poking = True
        pet._play_clip("drag", once=not pet._dragging)
        return
    if nxt == "work":
        pet._play_state("working")
        return
    pet._play_state(DEFAULT_STATE)


def take_cmd(pet) -> None:
    try:
        if not CMD_FILE.exists():
            return
        cmd = CMD_FILE.read_text(encoding="utf-8-sig").strip().lower()
        CMD_FILE.unlink(missing_ok=True)
    except Exception:
        return
    if cmd == "rest":
        go_rest(pet)
    elif cmd == "wake":
        if pet._resting:
            wake_from_rest(pet, "idle")
    elif cmd == "drag":
        if pet._resting:
            wake_from_rest(pet, "drag")
        else:
            pet._poking = True
            pet._play_clip("drag", once=True)
    elif cmd == "work":
        try:
            pet._state_file.write_text("working", encoding="utf-8")
        except Exception:
            pass
        pet._last_state_txt = "working"
        pet._state = "working"
        if pet._resting:
            wake_from_rest(pet, "work")
        elif not pet._getting_up:
            pet._play_state("working")
