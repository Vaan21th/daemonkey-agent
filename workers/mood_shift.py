"""听懂情绪：当天覆盖，不写五维。跟房间脸、画廊同一套词。"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_OVERLAY = ROOT / "data" / "runtime" / "mood_shift_today.json"

_SPEC = {
    "开心": {
        "human": "开心",
        "face": "高兴",
        "line": "这一场先短笑。可以说哈哈哈，一句就够。别改口吻，别写成鸡汤。",
        "look": "短笑，眼睛亮，肩松开。一个人待着。",
    },
    "委屈": {
        "human": "委屈着",
        "face": "难过",
        "line": "这一场先委屈。先短一声，别立刻解释、别去修东西、别装没事。口吻别换。",
        "look": "肩往里收，视线偏低，先短一声那种委屈。一个人待着，别装没事。",
    },
    "羞": {
        "human": "羞着",
        "face": "羞",
        "line": "你今天被表白，请表现的娇羞一些。别写成言情。",
        "look": "耳尖热，不敢对镜头，娇羞一下就够。一个人待着，别写成言情海报。",
    },
}
MOODS = tuple(_SPEC)
_ALIASES = {
    "开心": "开心", "高兴": "开心", "happy": "开心",
    "委屈": "委屈", "难过": "委屈", "hurt": "委屈", "sad": "委屈",
    "羞": "羞", "害羞": "羞", "shy": "羞",
}


def _today() -> str:
    return date.today().isoformat()


def _names() -> tuple[str, str]:
    try:
        from identity import ai_name, owner_name
        return (owner_name() or "他").strip(), (ai_name() or "我").strip()
    except Exception:
        return "他", "我"


def _read() -> dict:
    if not _OVERLAY.is_file():
        return {}
    try:
        data = json.loads(_OVERLAY.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    if str(data.get("as_of") or "") != _today():
        return {}
    return data if isinstance(data, dict) else {}


def _write(data: dict) -> None:
    _OVERLAY.parent.mkdir(parents=True, exist_ok=True)
    _OVERLAY.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def norm_mood(raw: str) -> str:
    key = (raw or "").strip()
    return _ALIASES.get(key) or _ALIASES.get(key.lower()) or ""


def live_mood() -> str:
    mood = str(_read().get("mood") or "")
    return mood if mood in _SPEC else ""


def live_quote() -> str:
    return str(_read().get("quote") or "").strip()


def live_mood_line() -> str:
    row = _read()
    custom = str(row.get("line") or "").strip()
    if custom:
        return custom
    spec = _SPEC.get(live_mood()) or {}
    return str(spec.get("line") or "")


def face_word() -> str:
    spec = _SPEC.get(live_mood()) or {}
    return str(spec.get("face") or "")


def gallery_look(mood: str = "") -> str:
    """画廊构图用：这场情绪长什么样。空 = 今天没覆盖。"""
    key = norm_mood(mood) or live_mood()
    return str((_SPEC.get(key) or {}).get("look") or "")


def room_mood_view() -> dict:
    """房间卡用：覆盖压过 SHE-STATE 当下。不写本子。"""
    mood = live_mood()
    if not mood:
        return {"live": False, "mood": "", "human": "", "face": ""}
    spec = _SPEC[mood]
    return {
        "live": True,
        "mood": mood,
        "human": spec["human"],
        "face": spec["face"],
    }


def gallery_signal(since: datetime | None) -> str:
    """覆盖比上一条画廊新，才算新信号。"""
    mood = live_mood()
    if not mood or not _OVERLAY.is_file():
        return ""
    mt = datetime.fromtimestamp(_OVERLAY.stat().st_mtime)
    if since is not None:
        cut = since.replace(tzinfo=None) if since.tzinfo else since
        if mt <= cut:
            return ""
    return f"她今天{mood}"


def notice_line(*, quote: str, mood: str) -> str:
    owner, ai = _names()
    q = (quote or "").strip().replace("「", "").replace("」", "")
    return f"因为{owner}说「{q}」，{ai}这场先{_SPEC[mood]['human']}。"


def apply_mood(mood: str, quote: str, line: str = "") -> dict:
    mood = norm_mood(mood)
    quote = (quote or "").strip()[:80]
    if mood not in _SPEC:
        return {"ok": False, "error": "情绪不对"}
    if not quote:
        return {"ok": False, "error": "没有原话"}
    prev = _read()
    extra = (line or "").strip()
    if not extra and prev.get("mood") == mood:
        extra = str(prev.get("line") or "").strip()
    row = {"as_of": _today(), "mood": mood, "quote": quote}
    if extra:
        row["line"] = extra
    _write(row)
    return {
        "ok": True,
        "mood": mood,
        "notice": notice_line(quote=quote, mood=mood),
        "permanent": False,
    }


def clear_mood(quote: str) -> dict:
    quote = (quote or "").strip()[:80]
    if not quote:
        return {"ok": False, "error": "没有原话"}
    prev = live_mood()
    if not prev:
        return {"ok": False, "error": "这场没有覆盖"}
    if _OVERLAY.is_file():
        _OVERLAY.unlink()
    owner, ai = _names()
    q = quote.replace("「", "").replace("」", "")
    return {
        "ok": True,
        "mood": "",
        "cleared": prev,
        "notice": f"因为{owner}说「{q}」，{ai}这场不当成{_SPEC[prev]['human']}了。",
        "permanent": False,
    }
