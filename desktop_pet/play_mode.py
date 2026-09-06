"""陪玩开关和她的名字 · 名字跟相遇 IDENTITY。"""

from __future__ import annotations

import json
from pathlib import Path

PET_DIR = Path(__file__).resolve().parent
ROOT = PET_DIR.parent
PLAY_ON = PET_DIR / "play_on.txt"
WAKE_FILE = PET_DIR / "play_wake.txt"
SID_FILE = PET_DIR / "play_session.txt"
THINK_FILE = PET_DIR / "play_think.txt"
IDENTITY = ROOT / "soul" / "IDENTITY.json"


def load_on() -> bool:
    try:
        return PLAY_ON.read_text(encoding="utf-8").strip() == "1"
    except Exception:
        return False


def save_on(on: bool) -> None:
    try:
        PLAY_ON.write_text("1" if on else "0", encoding="utf-8")
    except Exception:
        pass


def load_think() -> bool:
    try:
        return THINK_FILE.read_text(encoding="utf-8").strip() != "0"
    except Exception:
        return True


def save_think(on: bool) -> None:
    try:
        THINK_FILE.write_text("1" if on else "0", encoding="utf-8")
    except Exception:
        pass


def load_wake() -> str:
    try:
        w = WAKE_FILE.read_text(encoding="utf-8").strip()
        if w:
            return w
    except Exception:
        pass
    return identity_name() or "hey"


def save_wake(word: str) -> str:
    w = (word or "").strip() or identity_name() or "hey"
    try:
        WAKE_FILE.write_text(w, encoding="utf-8")
    except Exception:
        pass
    return w


def load_sid() -> str:
    try:
        s = SID_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    return s if s.startswith("api-") else ""


def save_sid(sid: str) -> str:
    s = (sid or "").strip()
    if not s.startswith("api-"):
        return ""
    try:
        SID_FILE.write_text(s, encoding="utf-8")
    except Exception:
        pass
    return s


def clear_sid() -> None:
    try:
        SID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def attach_play(pet):
    from desktop_pet.play_talk import PlayTalk
    talk = PlayTalk(pet)
    pet._play = talk
    on = load_on()
    pet._play_on = on
    act = getattr(pet, "_play_act", None)
    if act is not None:
        act.blockSignals(True)
        act.setChecked(on)
        act.blockSignals(False)
    think_act = getattr(pet, "_think_act", None)
    if think_act is not None:
        think_act.blockSignals(True)
        think_act.setChecked(load_think())
        think_act.blockSignals(False)
    if on:
        talk.enable(True, fresh=False)
    return talk


def identity_name() -> str:
    try:
        data = json.loads(IDENTITY.read_text(encoding="utf-8-sig"))
        return str(data.get("name") or "").strip()
    except Exception:
        return ""
