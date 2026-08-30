"""相处账合读：日记心情 + 置物架往来。陪伴值只在这里加。"""
from __future__ import annotations

_SHELF_TITLE = {
    "点赞": "置物架 · 你点了赞",
    "对话": "置物架 · 你回了对话",
    "忽略": "置物架 · 你看过了",
    "不要这种": "置物架 · 你说不要这种",
    "玩完": "置物架 · 你玩完了",
}
_TOY_WORD = {"flip": "翻牌", "tictac": "井字"}
_LOW = frozenset({"委屈", "难过", "低落", "伤心", "sad"})
THIN_MASK = {
    "话量": "无口",
    "调性": "正经",
    "语气": "毒舌",
    "礼节": "敬语",
    "表现力": "普通",
}


def _day(iso: str) -> str:
    return str(iso or "")[:10]


def _mood_rows(entries: list) -> list:
    out = []
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        title = str(e.get("title") or "").strip()
        out.append({
            "kind": "mood",
            "date": e.get("date") or "",
            "at": e.get("date") or "",
            "title": title,
            "body": e.get("body_excerpt") or e.get("body") or "",
            "weight": 2 if title in ("开心", "羞") else 0,
        })
    return out


def _shelf_rows(*, state_path=None) -> list:
    from workers.she_gallery_feedback import history
    out = []
    for r in history(state_path=state_path, limit=40):
        act = str(r.get("act") or "看过")
        game = str(r.get("kind") or "") == "game" or act == "玩完"
        if game:
            word = _TOY_WORD.get(str(r.get("toy") or ""), "") or str(r.get("toy") or r.get("text") or "翻牌")
            scored = act == "玩完" and str(r.get("source") or "") != "ask"
            out.append({
                "kind": "shelf",
                "date": _day(r.get("date") or r.get("at")),
                "at": r.get("at") or r.get("date") or "",
                "title": _SHELF_TITLE.get(act, "置物架 · " + act),
                "body": "游戏：" + word,
                "toy": str(r.get("toy") or ""),
                "weight": 2 if scored else 0,
            })
            continue
        if act == "对话":
            w = 2
        elif act == "点赞":
            w = 1
        elif act == "忽略" and str(r.get("mood") or "") in _LOW:
            w = -1
        else:
            w = 0
        out.append({
            "kind": "shelf",
            "date": _day(r.get("date") or r.get("at")),
            "at": r.get("at") or r.get("date") or "",
            "title": _SHELF_TITLE.get(act, "置物架 · " + act),
            "body": ("明信片：" + r["text"]) if r.get("text") else "明信片",
            "weight": w,
        })
    return out


def _mood_from_disk() -> list:
    try:
        from workers.cognition_loader import _load_opus_diary
        return (_load_opus_diary(max_entries=40) or {}).get("mood_entries") or []
    except Exception:
        return []


def _band(points: int, n: int) -> str:
    if n <= 0:
        return "empty"
    if points <= 2:
        return "thin"
    if points >= 9:
        return "thick"
    return "mid"


def _why(rows: list, band: str) -> str:
    if band != "thin":
        return ""
    scold = any(r.get("kind") == "mood" and r.get("title") == "委屈" for r in rows)
    comfort = any(r.get("kind") == "shelf" and "对话" in str(r.get("title") or "") for r in rows)
    if scold and not comfort:
        return "这几天你说重了，相处质感收着。"
    return "这几天往来少，相处质感收着。"


def _last(rows: list) -> str:
    if not rows:
        return ""
    r = rows[0]
    t = str(r.get("title") or "")
    if r.get("kind") == "shelf":
        return t.replace("置物架 · ", "")
    return t


def ledger(*, mood_entries=None, state_path=None) -> dict:
    rows = _mood_rows(mood_entries or []) + _shelf_rows(state_path=state_path)
    rows.sort(key=lambda x: x.get("at") or x.get("date") or "", reverse=True)
    points = sum(int(x.get("weight") or 0) for x in rows)
    band = _band(points, len(rows))
    empty = "还没有相处落点 · 她听懂心情、你接住信、或玩完一盘，会记在这里"
    return {
        "entries": rows,
        "points": points,
        "band": band,
        "last": _last(rows),
        "why": _why(rows, band),
        "note": empty if not rows else (_why(rows, band) or None),
    }


def snapshot(*, mood_entries=None, state_path=None) -> dict:
    pack = ledger(mood_entries=mood_entries if mood_entries is not None else _mood_from_disk(), state_path=state_path)
    return {
        "bond_now": pack["points"],
        "bond_band": pack["band"],
        "bond_last": pack["last"],
        "bond_why": pack["why"],
    }


def thin_mask(*, mood_entries=None, state_path=None) -> dict:
    if snapshot(mood_entries=mood_entries, state_path=state_path).get("bond_band") != "thin":
        return {}
    return dict(THIN_MASK)


def reach_scale(*, mood_entries=None, state_path=None) -> float:
    b = snapshot(mood_entries=mood_entries, state_path=state_path).get("bond_band")
    if b == "thin":
        return 0.55
    if b == "thick":
        return 1.25
    return 1.0


def attach_bond(payload: dict, *, state_path=None) -> dict:
    """挂到 /dashboard/cognition。不往 opus-diary 抄置物架。"""
    diary = (payload or {}).get("opus_diary") or {}
    pack = ledger(mood_entries=diary.get("mood_entries") or [], state_path=state_path)
    payload["bond_entries"] = pack["entries"]
    payload["bond_points"] = pack["points"]
    payload["bond_now"] = pack["points"]
    payload["bond_band"] = pack["band"]
    payload["bond_last"] = pack["last"]
    payload["bond_why"] = pack["why"]
    if "opus_diary" in payload:
        payload["opus_diary"]["note"] = pack["note"]
    return payload
