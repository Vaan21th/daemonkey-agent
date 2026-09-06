"""陪伴会话号 · 房间和桌宠陪玩共用，不是第二张嘴。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SID_PATH = ROOT / "data" / "runtime" / "companion_session.txt"


def valid_sid(sid: str) -> bool:
    s = (sid or "").strip()
    return bool(s) and s.startswith("api-") and not s.startswith("tmp-")


def load_sid() -> str:
    try:
        s = SID_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    return s if valid_sid(s) else ""


def save_sid(sid: str) -> str:
    s = (sid or "").strip()
    if not valid_sid(s):
        return ""
    SID_PATH.parent.mkdir(parents=True, exist_ok=True)
    SID_PATH.write_text(s, encoding="utf-8")
    return s
