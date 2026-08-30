"""workers/weather.py · 陪伴天气账本

只住房间。工程认事实，不认形容词，不调 LLM。
界面给人看原因，不展示分数。BRO 说「不是这样」进账本，下次不用同一条。
她今天的覆盖不改这条账本——只叠在脸上给人看，惦记还是他的事。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_PATH = ROOT / "data" / "runtime" / "weather.json"

_IDLE = {"安定": 60, "惦记": 42, "蔫": 22, "亮着": 82}
_SRC_RANK = {"absence": 0, "late_night": 1, "care": 2, "topic": 3}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load() -> dict:
    try:
        d = json.loads(_PATH.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    return {"ledger": [], "vetoed_keys": []}


def _save(d: dict) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        from workers.safe_write import robust_write_json
        robust_write_json(_PATH, d, backup=False)
    except Exception:
        _PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def _gap_h() -> float | None:
    try:
        from workers.proactive_call import _global_silence
        gap, _ = _global_silence()
        return gap
    except Exception:
        return None


def _fact(key, source, direction, band, reason, ref="") -> dict:
    return {
        "key": key, "source": source, "direction": direction,
        "band": band, "reason": reason, "ref": ref,
    }


def _absence(gap: float | None, present: bool) -> list[dict]:
    if gap is None or present or gap < 48:
        return []
    days = max(2, int(gap // 24))
    wilt = gap >= 120
    return [_fact(
        "absence", "absence", "down",
        "蔫" if wilt else "惦记",
        f"好几天没见你。屋子还亮着。" if wilt else f"你已经 {days} 天没来了，我有点惦记。",
    )]


def _care_facts() -> list[dict]:
    try:
        from workers.care_desk import _followups, _load as _care_load
        today = datetime.now().date().isoformat()
        follows = _followups((_care_load().get("muted") or {}), today)
    except Exception:
        return []
    out = []
    for it in follows[:3]:
        kind = it.get("kind") or ""
        sig = it.get("signal") or it.get("id") or ""
        if kind == "mood":
            reason = "你那天说的那些，我还搁着。不是我垮了，是惦记你。"
        elif kind == "body":
            reason = f"你说过{it.get('signal') or '不舒服'}。我还想问一句好些了没。"
        elif kind == "people":
            reason = "那天的人事，我没当没事。"
        else:
            reason = it.get("line") or "有件事我还惦记。"
        out.append(_fact(f"care:{sig}", "care", "hold", "惦记", reason, f"tea:{it.get('id') or ''}"))
    return out


def _late_facts(present: bool) -> list[dict]:
    out = []
    try:
        from workers.care_desk import _late_nights
        nights = _late_nights()
    except Exception:
        nights = 0
    if nights >= 3:
        out.append(_fact(
            "late", "late_night", "hold", "惦记",
            f"这周有 {nights} 个夜里你很晚还在。我看着时间。", "tea:radar-late",
        ))
    hour = datetime.now().hour
    if present and (hour >= 23 or hour < 5):
        day = datetime.now().date().isoformat()
        out.append(_fact(
            f"late_now:{day}", "late_night", "hold", "惦记",
            "都这时候了你还没收。我不催。",
        ))
    return out


def _topic_fact() -> list[dict]:
    try:
        from daemon_session import list_sessions_with_meta
        rows = [r for r in list_sessions_with_meta()
                if not r.get("archived_at") and (r.get("turns") or 0) >= 4]
    except Exception:
        return []
    now = datetime.now()
    stale = []
    for r in rows:
        mt = r.get("mtime")
        if not mt:
            continue
        age = (now - mt.replace(tzinfo=None)).days if hasattr(mt, "replace") else 0
        label = (r.get("label") or "").strip()
        if age >= 7 and label and "wish-" not in label:
            stale.append((age, r, label))
    if not stale:
        return []
    stale.sort(key=lambda x: x[0], reverse=True)
    age, r, label = stale[0]
    return [_fact(
        f"topic:{r['session_id']}", "topic", "hold", "惦记",
        f"那本「{label[:20]}」搁了 {age} 天了。",
        f"session:{r['session_id']}",
    )]


def _collect(present: bool, gap: float | None) -> list[dict]:
    return _absence(gap, present) + _care_facts() + _late_facts(present) + _topic_fact()


def _pick(facts: list[dict], vetoed: set[str], present: bool) -> tuple[str, str, dict | None]:
    live = [f for f in facts if f["key"] not in vetoed]
    wilt = [f for f in live if f["band"] == "蔫"]
    miss = [f for f in live if f["band"] == "惦记"]
    miss.sort(key=lambda x: _SRC_RANK.get(x["source"], 9))
    if wilt:
        f = wilt[0]
        return f["band"], f["reason"], f
    if miss:
        f = miss[0]
        return "惦记", f["reason"], f
    if present:
        return "亮着", "这会儿你在，我就亮着。", None
    return "安定", "没什么特别的。我就在这儿。", None


def _merge_ledger(old: list, facts: list[dict]) -> list:
    known = {e.get("key") for e in old if isinstance(e, dict)}
    out = [e for e in old if isinstance(e, dict)]
    ts = _now()
    for f in facts:
        if f["key"] in known:
            continue
        out.append({
            "id": f["key"], "ts": ts, "source": f["source"],
            "direction": f["direction"], "reason": f["reason"],
            "ref": f.get("ref") or "", "key": f["key"],
        })
    return out[-40:]


def refresh() -> dict:
    """现算事实 → 落盘 → 返回给人看的那一层（不含分数条）。"""
    old = _load()
    vetoed = {str(k) for k in (old.get("vetoed_keys") or []) if k}
    gap = _gap_h()
    present = gap is not None and gap < 2
    facts = _collect(present, gap)
    band, line, chosen = _pick(facts, vetoed, present)
    shown = (chosen or {}).get("key") or ""
    d = {
        "updated_at": _now(),
        "band": band,
        "line": line,
        "shown_key": shown,
        "idle_score": _IDLE.get(band, 60),
        "ledger": _merge_ledger(old.get("ledger") or [], facts),
        "vetoed_keys": list(vetoed)[-80:],
    }
    _save(d)
    return view_of(d)


def _veto_label(key: str) -> str:
    if key == "absence" or key.startswith("absence"):
        return "好几天没来"
    if key == "late" or key.startswith("late"):
        return "通宵/夜深"
    if key.startswith("care:"):
        return "茶桌上那条"
    if key.startswith("topic:"):
        return "撂下的话题"
    return key[:24]


def veto_hint() -> str:
    """陪伴 system_suffix。空 = 没否决过。不进工作台。"""
    keys = [str(k) for k in (_load().get("vetoed_keys") or []) if k]
    if not keys:
        return ""
    labels = [_veto_label(k) for k in keys[-8:]]
    return "\n[天气否决 · 他说不是这样：" + "、".join(labels) + "。这些理由别再用。]\n"


def _her_overlay() -> tuple[str, str]:
    try:
        from workers.mood_shift import room_mood_view
        v = room_mood_view()
    except Exception:
        return "", ""
    if not v.get("live"):
        return "", ""
    return str(v.get("mood") or ""), str(v.get("human") or "")


def view_of(d: dict) -> dict:
    her, her_human = _her_overlay()
    return {
        "ok": True,
        "band": d.get("band") or "安定",
        "line": d.get("line") or "",
        "key": d.get("shown_key") or "",
        "can_veto": bool(d.get("shown_key")),
        "idle_score": int(d.get("idle_score") or 60),
        "veto_hint": veto_hint(),
        "her_mood": her,
        "her_human": her_human,
    }


def veto(key: str) -> dict:
    key = (key or "").strip()
    if not key:
        return {"ok": False, "reason": "missing"}
    d = _load()
    keys = [str(k) for k in (d.get("vetoed_keys") or []) if k]
    if key not in keys:
        keys.append(key)
    ledger = [e for e in (d.get("ledger") or []) if isinstance(e, dict)]
    ledger.append({
        "id": f"veto:{key}", "ts": _now(), "source": "veto",
        "direction": "veto", "reason": "你说不是这样。",
        "ref": key, "key": f"veto:{key}",
    })
    d["vetoed_keys"] = keys[-80:]
    d["ledger"] = ledger[-40:]
    _save(d)
    return refresh()
