"""画廊回声：房间待看的那张，他说对/别这样，下一张要吃到。"""
from __future__ import annotations

from datetime import datetime

from workers.she_gallery_gate import load_state, parse_dt, save_state

VERDICTS = ("对", "别这样", "看过")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _names() -> tuple[str, str]:
    try:
        from identity import ai_name, owner_name
        return (owner_name() or "他").strip(), (ai_name() or "我").strip()
    except Exception:
        return "他", "我"


def public_image(path: str) -> str:
    p = (path or "").replace("\\", "/").strip()
    if p.startswith("data/"):
        return "/" + p[5:]
    if p.startswith("static/"):
        return "/" + p
    return p


def inbox(*, state_path=None) -> dict:
    row = (load_state(state_path).get("inbox") or {})
    return row if isinstance(row, dict) and row.get("date") else {}


def set_inbox(entry: dict, *, state_path=None) -> None:
    st = load_state(state_path)
    row = {
        "date": str(entry.get("date") or "").strip(),
        "image": str(entry.get("image") or "").strip(),
        "text": str(entry.get("text") or "").strip(),
        "mood": str(entry.get("mood") or "").strip(),
        "scene": str(entry.get("scene") or "").strip(),
    }
    kind = str(entry.get("kind") or "").strip()
    if kind:
        row["kind"] = kind
    toy = str(entry.get("toy") or "").strip()
    if toy:
        row["toy"] = toy
    source = str(entry.get("source") or "").strip()
    if source:
        row["source"] = source
    st["inbox"] = row
    save_state(st, path=state_path)


def last_feedback(*, state_path=None) -> dict:
    row = load_state(state_path).get("last_feedback") or {}
    return row if isinstance(row, dict) and row.get("verdict") else {}


def apply_feedback(verdict: str, quote: str, *, state_path=None) -> dict:
    verdict = (verdict or "").strip()
    quote = (quote or "").strip()[:80]
    if verdict not in VERDICTS:
        return {"ok": False, "error": "反应不对"}
    if not quote:
        return {"ok": False, "error": "没有原话"}
    card = inbox(state_path=state_path)
    if not card:
        try:
            from workers.she_gallery import she_gallery
            items = she_gallery()
            card = items[0] if items else {}
        except Exception:
            card = {}
    if not card.get("date"):
        return {"ok": False, "error": "没有可评的画"}
    st = load_state(state_path)
    row = {
        "at": _now(),
        "date": card.get("date") or "",
        "verdict": verdict,
        "quote": quote,
        "text": card.get("text") or "",
        "mood": card.get("mood") or "",
        "scene": card.get("scene") or "",
    }
    kind = str(card.get("kind") or "").strip()
    if kind:
        row["kind"] = kind
    toy = str(card.get("toy") or "").strip()
    if toy:
        row["toy"] = toy
    hist = [x for x in (st.get("verdicts") or []) if isinstance(x, dict)]
    hist.append(row)
    st["verdicts"] = hist[-12:]
    st["last_feedback"] = row
    st["inbox"] = {}
    save_state(st, path=state_path)
    owner, ai = _names()
    q = quote.replace("「", "").replace("」", "")
    said = {"对": "收下了", "别这样": "不要这种", "看过": "看过了"}.get(verdict, "看过了")
    return {
        "ok": True,
        "verdict": verdict,
        "notice": f"因为{owner}说「{q}」，{ai}这张画记成他{said}。",
        "permanent": False,
    }


def feedback_block(*, state_path=None) -> str:
    hist = [
        x for x in (load_state(state_path).get("verdicts") or [])
        if isinstance(x, dict) and str(x.get("kind") or "") != "game"
    ]
    if not hist:
        return ""
    lines = ["## 他对画廊说过"]
    for r in hist[-6:]:
        lines.append(
            f"- {r.get('verdict')}：「{r.get('quote') or ''}」"
            f"· 心情 {r.get('mood') or '（空）'} · {r.get('text') or ''}"
        )
    if any(r.get("verdict") == "别这样" for r in hist):
        lines.append("他说别这样的，构图和这种味道不要再来。")
    return "\n".join(lines)


def feedback_signal(since, *, state_path=None) -> str:
    row = last_feedback(state_path=state_path)
    at = parse_dt(str(row.get("at") or ""))
    if not at:
        return ""
    if since is not None and at <= since:
        return ""
    if str(row.get("kind") or "") == "game":
        return ""
    if row.get("verdict") == "对":
        return "他说这张对"
    if row.get("verdict") == "别这样":
        return "他说别这样"
    if row.get("verdict") == "看过":
        return "他看过这张"
    return ""


def vetoed_used(*, state_path=None) -> dict:
    hist = [x for x in (load_state(state_path).get("verdicts") or []) if isinstance(x, dict)]
    no = [r for r in hist if r.get("verdict") == "别这样"]
    return {
        "texts": [str(r.get("text") or "") for r in no],
        "moods": [str(r.get("mood") or "") for r in no],
        "scenes": [str(r.get("scene") or "") for r in no],
    }


_LOW = frozenset({"委屈", "难过", "低落", "伤心", "sad"})
_ACT = {"like": "点赞", "ignore": "忽略", "talk": "对话"}


def card_is_low(card: dict) -> bool:
    raw = str((card or {}).get("mood") or "").strip()
    try:
        from workers.mood_shift import norm_mood
        if norm_mood(raw) == "委屈":
            return True
    except Exception:
        pass
    return raw in _LOW


def history(*, state_path=None, limit: int = 12) -> list:
    st = load_state(state_path)
    rows = [x for x in (st.get("verdicts") or []) if isinstance(x, dict)]
    images = {}
    try:
        from workers.she_gallery import she_gallery
        for it in she_gallery():
            d = str((it or {}).get("date") or "")
            if d:
                images[d] = (it or {}).get("image") or ""
    except Exception:
        pass
    out = []
    for r in reversed(rows[-limit:]):
        img = r.get("image") or images.get(str(r.get("date") or "")) or ""
        v, q = str(r.get("verdict") or ""), str(r.get("quote") or "")
        if v == "玩完":
            act = "玩完"
        elif v == "看过" and q in ("忽略", "对话"):
            act = q
        elif v == "对":
            act = "点赞"
        elif v == "别这样":
            act = "不要这种"
        else:
            act = q or v
        kind = str(r.get("kind") or "")
        toy = str(r.get("toy") or "")
        out.append({
            "at": r.get("at") or "",
            "date": r.get("date") or "",
            "text": r.get("text") or "",
            "mood": r.get("mood") or "",
            "act": act,
            "kind": kind or ("game" if v == "玩完" or toy else ""),
            "toy": toy,
            "source": str(r.get("source") or ""),
            "image_url": public_image(img) if img else "",
        })
    return out


def respond(action: str, *, state_path=None, clear_low: bool = True) -> dict:
    """置物架上点赞 / 忽略 / 对话。看过不当成「别这样」，下次还能寄这种。"""
    action = (action or "").strip()
    if action not in _ACT:
        return {"ok": False, "error": "这个反应没有"}
    card = inbox(state_path=state_path)
    if not card.get("date"):
        return {"ok": False, "error": "没有待看的"}
    if str(card.get("kind") or "") == "game":
        return {"ok": False, "error": "这不是明信片"}
    low = card_is_low(card)
    if action == "like" and low:
        return {"ok": False, "error": "这张不是点赞那种"}
    if action in ("ignore", "talk") and not low:
        return {"ok": False, "error": "这张不用哄"}
    if action == "like":
        out = apply_feedback("对", "点赞", state_path=state_path)
    else:
        out = apply_feedback("看过", _ACT[action], state_path=state_path)
        if not out.get("ok"):
            return out
        if clear_low:
            try:
                from workers.mood_shift import clear_mood, live_mood
                if live_mood() == "委屈":
                    clear_mood(_ACT[action])
            except Exception:
                pass
    if not out.get("ok"):
        return out
    out["cleared"] = True
    out["talk"] = action == "talk"
    out["history"] = history(state_path=state_path)
    return out
