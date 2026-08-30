"""workers/face_tag.py · 陪伴脸标签：解析 + 事实兜底

说明书在 system 常量段。这里只认白名单，不扫形容词加分。
漏标时只有茶桌已经在抽的身体/情绪信号才能补 care。
"""
from __future__ import annotations

import re

_ALIASES = {
    "care": "care", "关心": "care",
    "sad": "sad", "难过": "sad",
    "shy": "shy", "羞": "shy",
    "puff": "puff", "鼓脸": "puff",
    "happy": "happy", "高兴": "happy",
}
_TAG = re.compile(r"<face>\s*([^<]+?)\s*</face>", re.I)


def parse_face(text: str) -> str:
    m = _TAG.search(text or "")
    if not m:
        return ""
    raw = m.group(1).strip()
    return _ALIASES.get(raw) or _ALIASES.get(raw.lower()) or ""


def fallback_face(user_message: str) -> str:
    try:
        from workers.closure_check import peek_care_signal
        if peek_care_signal(user_message):
            return "care"
    except Exception:
        pass
    return ""


def resolve_face(user_message: str, reply: str) -> str:
    return parse_face(reply) or fallback_face(user_message)
