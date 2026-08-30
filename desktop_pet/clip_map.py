"""小房间桌宠 · 片子名 ↔ 情绪 / 一次性动作。"""

from __future__ import annotations

from pathlib import Path

PET_DIR = Path(__file__).resolve().parent
CLIPS_DIR = PET_DIR / "clips"
FRAMES_DIR = PET_DIR / "frames"
GUARD_CUE = PET_DIR / "guard.cue"
ROOM_POS = PET_DIR / "room_position.txt"

# 文件名是 BRO 看过能用的动作 · 英文 id 给代码
CLIP_FILES: dict[str, str] = {
    "idle_blink": "idle_blink.mp4",
    "idle_look": "idle_look.mp4",
    "idle_drowsy": "idle_drowsy.mp4",
    "idle_rest": "idle_rest.mp4",
    "idle_sing": "idle_sing.mp4",
    "work": "work.mp4",
    "work_done": "work_done.mp4",
    "drag": "drag.mp4",
    "tired": "tired.mp4",
    "guard": "guard.mp4",
}

# 每段循环池 · 播完切下一段，闲着不总是同一张脸
# 出厂 10 段 · 唱歌进短插播
SHIP_CLIPS = (
    "idle_blink",
    "idle_look",
    "idle_drowsy",
    "idle_rest",
    "idle_sing",
    "work",
    "work_done",
    "drag",
    "tired",
    "guard",
)

STATE_CLIPS: dict[str, list[str]] = {
    "idle": ["idle_blink"],
    "thinking": ["work"],
    "working": ["work"],
    "happy": ["idle_look"],
    "greeting": ["idle_look"],
    "surprised": ["work_done"],
    "confused": ["idle_look"],
    "sleepy": ["idle_drowsy"],
}

IDLE_MAIN = "idle_blink"
# 短插播不含趴下 · 长时间没事另切 idle_rest 并停在趴着
IDLE_SIDES = ("idle_look", "idle_drowsy", "idle_sing")
IDLE_SIDE_MIN_S = 15
IDLE_SIDE_MAX_S = 30
REST_CLIP = "idle_rest"
REST_AFTER_S = 90
# 原片趴下后又自己坐起来 · 27–42 是趴桌，43 起起身。冻中间，叫醒播后半
REST_HOLD_I = 36
REST_N = 61
REST_DOWN = tuple(range(0, REST_HOLD_I + 1))
REST_UP = tuple(range(REST_HOLD_I, REST_N))
# 原片闭眼停太久 · 只留开合各几帧 + 短静帧
BLINK_TAKE = (0, 3, 6, 10, 11, 12, 13, 14, 18, 46, 47, 48, 49, 50, 52, 55)
BLINK_MS = 50
# 开合 0.8 秒已经够 · 两次之间睁着眼停 4–7 秒
BLINK_GAP_MIN_MS = 4000
BLINK_GAP_MAX_MS = 7000
WORK_STATES = frozenset({"working", "thinking"})

# 播完一遍回 idle · 不循环
ONCE_CLIPS = frozenset({"work_done"})
# 情绪残留（greeting 等）只播一遍，写回 idle，避免卡死看猫、趴不下
ONCE_MOODS = frozenset({"greeting", "happy", "surprised", "confused"})

# 窗口按去灰后完整房间比例 (~1253:1130)
# 底片按「大」解一次 · 滑块只改窗，不再按档重解
SCALE_SIZES: dict[str, tuple[int, int]] = {
    "小": (280, 253),
    "中": (380, 343),
    "大": (520, 469),
}
BASE_WH = SCALE_SIZES["大"]
PCT_MIN = 25
PCT_MAX = 100
WH_MIN = (196, 177)
WH_MAX = (600, 541)
_OLD_PCT = {"小": 45, "中": 65, "大": 85}
DEFAULT_PCT = 65
DEFAULT_SCALE = "中"
ROOM_SCALE = PET_DIR / "room_scale.txt"
ROOM_LOCK = PET_DIR / "room_lock.txt"


def size_for_pct(pct: int) -> tuple[int, int]:
    pct = max(PCT_MIN, min(PCT_MAX, int(pct)))
    t = (pct - PCT_MIN) / (PCT_MAX - PCT_MIN)
    w = int(WH_MIN[0] + (WH_MAX[0] - WH_MIN[0]) * t)
    h = int(WH_MIN[1] + (WH_MAX[1] - WH_MIN[1]) * t)
    return w, h


def load_pct() -> int:
    try:
        raw = ROOM_SCALE.read_text(encoding="utf-8").strip()
        if raw in _OLD_PCT:
            return _OLD_PCT[raw]
        n = int(raw)
        if PCT_MIN <= n <= PCT_MAX:
            return n
    except Exception:
        pass
    return DEFAULT_PCT


def save_pct(pct: int) -> None:
    try:
        ROOM_SCALE.write_text(str(int(pct)), encoding="utf-8")
    except Exception:
        pass


def load_lock() -> bool:
    try:
        return ROOM_LOCK.read_text(encoding="utf-8").strip() == "1"
    except Exception:
        return False


def save_lock(on: bool) -> None:
    try:
        ROOM_LOCK.write_text("1" if on else "0", encoding="utf-8")
    except Exception:
        pass


def load_scale() -> str:
    pct = load_pct()
    if pct <= 50:
        return "小"
    if pct <= 75:
        return "中"
    return "大"


def save_scale(name: str) -> None:
    save_pct(_OLD_PCT.get(name, DEFAULT_PCT))


def clip_path(clip_id: str) -> Path | None:
    name = CLIP_FILES.get(clip_id)
    if not name:
        return None
    p = CLIPS_DIR / name
    return p if p.exists() else None


def frame_path(clip_id: str) -> Path | None:
    p = FRAMES_DIR / f"{clip_id}.webp"
    return p if p.exists() else None


def clips_for(state: str) -> list[str]:
    ids = STATE_CLIPS.get(state, STATE_CLIPS["idle"])
    return [i for i in ids if frame_path(i)]


def read_guard_open() -> bool:
    try:
        if not GUARD_CUE.exists():
            return False
        return GUARD_CUE.read_text(encoding="utf-8").strip() == "open"
    except Exception:
        return False
