"""画廊惊喜闸：冷却掷点 / 新信号 / 构图复读。"""
from __future__ import annotations

import json
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_STATE = _ROOT / "data" / "runtime" / "she_gallery.json"
_COOL_MIN = 18.0
_COOL_MAX = 48.0
_WAKE = frozenset({"醒了", "刚醒", "早安"})
_MARKS = _WAKE | frozenset({"窗台", "窗边", "杯子", "杯", "windowsill", "mug"})


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    try:
        return float(raw)
    except ValueError:
        return default


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def parse_dt(raw: str) -> datetime | None:
    s = (raw or "").strip().replace("Z", "+00:00")
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo:
            return dt.astimezone().replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def load_state(path: Path | None = None) -> dict:
    p = path or _STATE
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(data: dict, path: Path | None = None) -> None:
    p = path or _STATE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def last_post_dt(entries: list[dict]) -> datetime | None:
    if not entries:
        return None
    return parse_dt((entries[0] or {}).get("date") or "")


def cooldown_blocked(
    now: datetime,
    entries: list[dict],
    *,
    state_path: Path | None = None,
) -> bool:
    """发完锁 18–48h。没账本时按上一条 + 18h 兜底。"""
    st = load_state(state_path)
    nxt = parse_dt(str(st.get("next_eligible_at") or ""))
    if nxt is None:
        last = last_post_dt(entries)
        if last is None:
            return False
        nxt = last + timedelta(hours=_env_float("OPUS_GALLERY_COOLDOWN_MIN", _COOL_MIN))
    return _naive(now) < nxt


def mark_posted(now: datetime, *, state_path: Path | None = None) -> float:
    lo = _env_float("OPUS_GALLERY_COOLDOWN_MIN", _COOL_MIN)
    hi = _env_float("OPUS_GALLERY_COOLDOWN_MAX", _COOL_MAX)
    if hi < lo:
        hi = lo
    hours = random.uniform(lo, hi)
    nxt = _naive(now) + timedelta(hours=hours)
    st = load_state(state_path)
    st["last_posted_at"] = _naive(now).strftime("%Y-%m-%dT%H:%M:%S")
    st["next_eligible_at"] = nxt.strftime("%Y-%m-%dT%H:%M:%S")
    st["cooldown_hours"] = round(hours, 2)
    save_state(st, path=state_path)
    return hours


def roll_dice() -> bool:
    """跟主动 CALL 同款：够格也不一定这拍开口。"""
    p = _env_float("OPUS_GALLERY_SPONTANEITY", 0.35)
    try:
        from workers.bond_ledger import reach_scale
        p *= reach_scale()
    except Exception:
        pass
    p = min(1.0, max(0.0, p))
    return random.random() <= p


def _mtime_after(path: Path, since: datetime) -> bool:
    if not path.exists():
        return False
    return datetime.fromtimestamp(path.stat().st_mtime) > since


def _talked_after(since: datetime) -> bool:
    try:
        from daemon_session import get_last_user_turn_ts, list_sessions_with_meta
        rows = [r for r in list_sessions_with_meta() if not r.get("archived_at")]
    except Exception:
        return False
    rows.sort(key=lambda r: r.get("mtime") or datetime.min, reverse=True)
    for row in rows[:8]:
        ts = get_last_user_turn_ts(row.get("session_id") or "")
        dt = parse_dt(ts or "")
        if dt and dt > since:
            return True
    return False


def _care_after(since: datetime) -> bool:
    p = _ROOT / "data" / "runtime" / "care_followups.json"
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    for it in data.get("items") or []:
        dt = parse_dt(str(it.get("first_ts") or ""))
        if dt and dt > since:
            return True
    return False


def _weather_veto_after(since: datetime) -> bool:
    p = _ROOT / "data" / "runtime" / "weather.json"
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    for row in data.get("ledger") or []:
        if (row.get("source") or "") != "veto":
            continue
        dt = parse_dt(str(row.get("ts") or ""))
        if dt and dt > since:
            return True
    return False


def new_signals(since: datetime | None) -> list[str]:
    """上一条之后有没有新的一点。没有 since = 空画廊，任何活痕迹都算。"""
    if since is None:
        since = datetime(2000, 1, 1)
    since = _naive(since)
    found: list[str] = []
    if _talked_after(since):
        found.append("回来过")
    if _care_after(since):
        found.append("茶桌惦记")
    if _weather_veto_after(since):
        found.append("天气否决")
    try:
        from identity import owner_notebook_path
        nb = owner_notebook_path(_ROOT / "soul")
    except Exception:
        nb = _ROOT / "soul" / "BRO-NOTEBOOK.md"
    if _mtime_after(nb, since):
        found.append("画像")
    if _card_after(since):
        found.append("状态卡")
    if _mtime_after(_ROOT / "soul" / "SHE-STATE.md", since):
        found.append("她的状态")
    try:
        from workers.mood_shift import gallery_signal
        sig = gallery_signal(since)
        if sig:
            found.append(sig)
    except Exception:
        pass
    try:
        from workers.she_gallery_feedback import feedback_signal
        fb = feedback_signal(since)
        if fb:
            found.append(fb)
    except Exception:
        pass
    return found


def _card_after(since: datetime) -> bool:
    try:
        from identity import owner_notebook_path
        from workers.cognition_loader import _parse_state_card

        nb = owner_notebook_path(_ROOT / "soul")
        if not nb.exists():
            return False
        sc = _parse_state_card(nb.read_text(encoding="utf-8"))
    except Exception:
        return False
    for entry in (sc or {}).values():
        dt = parse_dt(str((entry or {}).get("as_of") or ""))
        if dt and dt.date() > since.date():
            return True
    return False


def used_from(entries: list[dict], n: int = 3) -> dict:
    rows = (entries or [])[:n]
    return {
        "texts": [str(r.get("text") or "") for r in rows],
        "moods": [str(r.get("mood") or "") for r in rows],
        "scenes": [str(r.get("scene") or "") for r in rows],
    }


def used_block(used: dict) -> str:
    lines = ["## 已经寄过（构图和这几句不能再来）"]
    texts = used.get("texts") or []
    scenes = used.get("scenes") or []
    moods = used.get("moods") or []
    if not any(texts):
        lines.append("（还没有）")
        return "\n".join(lines)
    for i, text in enumerate(texts):
        scene = scenes[i] if i < len(scenes) else ""
        mood = moods[i] if i < len(moods) else ""
        lines.append(f"- 文案: {text} · 心情: {mood} · 画面: {scene or '（当时没记）'}")
    return "\n".join(lines)


def _marks(s: str) -> set[str]:
    blob = (s or "").lower()
    return {m for m in _MARKS if m.lower() in blob}


def scene_repeats(scene: str, text: str, used: dict) -> bool:
    now = _marks(scene) | _marks(text)
    if not now:
        return False
    if now & _WAKE:
        for old in used.get("texts") or []:
            if _marks(old) & _WAKE:
                return True
    texts = used.get("texts") or []
    scenes = used.get("scenes") or []
    for i, old_t in enumerate(texts):
        old_s = scenes[i] if i < len(scenes) else ""
        old = _marks(old_t) | _marks(old_s)
        if len(now & old) >= 2:
            return True
    return False
