"""workers/care_desk.py · 陪伴「泡的茶」数据组装

咖啡边桌用人情味层: 待回访 / 当下惦记 / 作息模式。
纯读磁盘 + 规则句, 不调 LLM。卡片自己不出声, 开口走 speak_care 落进会话。
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_CARE = ROOT / "data" / "runtime" / "care_followups.json"
_CARE_LOCK = threading.Lock()  # B-① · 2026-08-27 · 护理卡状态 RMW 保护 (Grok 全量审计)
_CST = timezone(timedelta(hours=8))  # B-② · 2026-08-27 · 跟进计算固定 UTC+8 · 不随 UTC/系统时区漂 (Grok 全量审计)

# H4 · 理解触发式惦记 · cognition 模块级缓存 (按 notebook mtime 失效 · 不每轮 load)
_COG_CACHE: dict = {"mtime": 0.0, "data": None}
_LATE_NIGHT_MARKERS = ("熬夜", "晚睡", "夜里", "凌晨", "缺觉", "睡眠不足", "昼伏夜出", "夜猫")

_PEOPLE = ("吵架", "吵了一架", "和同事", "跟同事", "被骂", "委屈", "闹别扭")
_BODY = ("累", "困", "睡", "失眠", "熬夜", "病", "感冒", "烧", "疼", "住院", "手术", "不舒服")
_MOOD = ("烦", "焦虑", "难过", "丧", "抑郁", "压力", "崩溃", "想哭", "扛不住", "撑不住")


def _ai_name() -> str:
    p = ROOT / "soul" / "IDENTITY.json"
    try:
        if p.exists():
            return (json.loads(p.read_text(encoding="utf-8-sig")).get("name") or "").strip()
    except Exception:
        pass
    return ""


def _load() -> dict:
    try:
        d = json.loads(_CARE.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            return d
    except Exception:
        # B-① · 2026-08-27 · 损坏先备份 · 防空壳覆盖 (Grok 全量审计)
        try:
            import shutil
            import time as _t
            bak = _CARE.with_name(f"care_followups.json.corrupt-{int(_t.time())}")
            shutil.copy2(_CARE, bak)
        except Exception:
            pass
    return {"items": [], "muted": {}}


def _save(d: dict) -> None:
    try:
        _CARE.parent.mkdir(parents=True, exist_ok=True)
        from workers.safe_write import robust_write_json
        robust_write_json(_CARE, d, backup=False)
    except Exception:
        _CARE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def _kind(signal: str, text: str) -> str:
    blob = f"{signal} {text}"
    if any(k in blob for k in _PEOPLE):
        return "people"
    if any(k in blob for k in _BODY):
        return "body"
    if any(k in blob for k in _MOOD):
        return "mood"
    return "life"


def _days(ts: str) -> int:
    try:
        ft = datetime.strptime(ts or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(_CST) - ft).total_seconds() // 86400))
    except Exception:
        return 0


def _cached_cognition() -> dict:
    """读 cognition · 按 BRO-NOTEBOOK mtime 缓存 · 同文件不重复 load。"""
    global _COG_CACHE
    mtime = 0.0
    try:
        from workers.cognition_loader import BRO_NOTEBOOK, load_cognition
        if BRO_NOTEBOOK.exists():
            mtime = BRO_NOTEBOOK.stat().st_mtime
    except Exception:
        return _COG_CACHE.get("data") or {}
    if _COG_CACHE.get("data") is not None and _COG_CACHE.get("mtime") == mtime:
        return _COG_CACHE["data"]
    try:
        data = load_cognition(section_excerpt_chars=400, diary_max_entries=2)
    except Exception:
        data = {}
    _COG_CACHE = {"mtime": mtime, "data": data}
    return data


def _sc_val(sc: dict, field: str) -> str:
    v = (sc.get(field) or {}).get("value") or ""
    return "" if v in ("", "-", "待确认") else v.strip()


def _clip(s: str, n: int = 24) -> str:
    s = (s or "").strip().replace("\n", " ")
    return s[:n] + "…" if len(s) > n else s


def _understanding_fact(cog: dict, kind: str) -> str:
    keys = {
        "body": ("健康", "作息", "睡眠", "身体", "病"),
        "mood": ("情绪", "心情", "压力", "焦虑"),
        "people": ("关系", "同事", "家人", "人事"),
        "life": ("生活", "事件"),
    }.get(kind, ())
    for u in cog.get("understanding") or []:
        field = u.get("field") or ""
        text = u.get("text") or ""
        if any(k in field or k in text for k in keys):
            return _clip(text, 28)
    return ""


# update_bro_note 流水壳 / 长期品格 · 不是"那天发生的事"
_FLOW_LOG_PREFIX = re.compile(
    r"^(?:section=events\s*\(append\)|events\s*\(append\))\s*[:：]?\s*",
    re.I,
)
_FLOW_DATE_PREFIX = re.compile(
    r"^\d{4}-\d{1,2}-\d{1,2}(?:\s+\d{1,2}:\d{2})?\s*[/·\-：:\s]+",
)
# 剥掉流水壳里残留的『… · 』『…·』『…』等杂质前缀（如 events (append)：… · 猫生病了）
# U+2026 省略号是单个字符，需单独匹配；兼容 ASCII 点点点
_ELLIPSIS_PREFIX = re.compile(r"^(?:(?:…|\.{2,}|\u2026)\s*[·\-—:：]?\s*)+")
_BARE_DATE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}(?:\s+\d{1,2}:\d{2})?$")
_TRAIT_MARKERS = ("重命名能手", "命名习惯", "项目状态", "他用语言塑造现实", "长期品格")


def _is_trait_or_profile_line(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return True
    if any(m in s for m in _TRAIT_MARKERS):
        return True
    low = s.lower()
    if low.startswith("section=profile") or low.startswith("section=preferences"):
        return True
    return False


def _parse_user_event(text: str) -> str:
    """从 recent_flow / 事件章节行剥掉工程流水壳 · 只留用户事件描述。"""
    s = re.sub(r"\s+", " ", (text or "").strip())
    if not s or _is_trait_or_profile_line(s):
        return ""
    low = s.lower()
    if low.startswith("section=events (append)") or low.startswith("section=events(append)"):
        return ""
    if low.startswith("events (append)") or "events (append)" in low[:48]:
        s = _FLOW_LOG_PREFIX.sub("", s).strip()
        s = _FLOW_DATE_PREFIX.sub("", s).strip()
        s = _ELLIPSIS_PREFIX.sub("", s).strip()
        if not s or _BARE_DATE.match(s) or _is_trait_or_profile_line(s):
            return ""
        return s
    if "update_bro_note" in low and "|" in s:
        return ""
    return s


def _latest_event_fact(cog: dict) -> str:
    for item in cog.get("recent_flow") or []:
        parsed = _parse_user_event(item.get("text") or "")
        if parsed:
            return _clip(parsed, 28)
    for sec in (cog.get("bro_profile") or {}).get("sections") or []:
        heading = sec.get("heading") or ""
        if "事件" not in heading and "Event" not in heading:
            continue
        body = sec.get("body_excerpt") or sec.get("body_full") or ""
        for line in body.splitlines():
            line = line.strip().lstrip("-*·| ").strip()
            if not line or line.startswith("…"):
                continue
            if line.startswith("|"):
                if line.split("|")[0].strip() in ("时间", "date", "Time"):
                    continue
                cells = [c.strip() for c in line.strip("|").split("|") if c.strip()]
                line = max(cells, key=len) if cells else ""
            if not line or line.split("|")[0].strip() in ("时间", "date", "Time"):
                continue
            parsed = _parse_user_event(line)
            if parsed:
                return _clip(parsed, 28)
    return ""


def _line_for(kind: str, text: str, cog: dict | None = None) -> str:
    """模板 + 状态卡/了解层/事件流字段拼接 · 不调 LLM。"""
    cog = cog or {}
    sc = cog.get("state_card") or {}
    t = _clip(text, 28)
    if kind == "body":
        # 候选 text 是当下具体的事（如"好累，昨晚没睡"），优先于长期状态卡标签
        if t:
            return f"好些了没 · {t}"
        schedule = _sc_val(sc, "作息模式")
        health = _sc_val(sc, "健康基线")
        fact = _understanding_fact(cog, "body")
        if schedule and schedule != "正常":
            return f"最近作息是不是乱了点 · {_clip(schedule, 20)}"
        if health and any(k in health for k in ("熬夜", "睡", "病", "不舒服", "累")):
            return f"最近作息是不是乱了点 · {_clip(health, 20)}"
        if fact:
            return f"好些了没 · {fact}"
        return "好些了没，别硬扛"
    if kind == "mood":
        # 候选 text（"那阵子缓不过来，一直烦"）优先于情绪基线标签（"平稳"）
        if t:
            return f"那阵子缓过来没 · {t}"
        mood = _sc_val(sc, "情绪基线")
        if mood:
            return f"那阵子缓过来没 · {_clip(mood, 20)}"
        fact = _understanding_fact(cog, "mood")
        if fact:
            return f"那阵子缓过来没 · {fact}"
        return "那阵子缓过来没"
    if kind == "people":
        fact = t or _understanding_fact(cog, "people")
        if fact:
            return f"那天的事，过了没 · {fact}"
        return "那天的事，过了没"
    fact = t or _understanding_fact(cog, "life")
    if fact:
        return f"{fact}，还搁在心里吗"
    return "还好吗"


def is_busy_daemon() -> bool:
    """忙时探测 · 只读 workshop runs · 任一 running/pending 即忙。"""
    runs_dir = ROOT / "data" / "workshop" / "runs"
    try:
        if not runs_dir.is_dir():
            return False
        for p in runs_dir.glob("run-*.json"):
            try:
                status = (json.loads(p.read_text(encoding="utf-8")).get("status") or "").strip()
                if status in ("running", "pending"):
                    return True
            except Exception:
                continue
    except Exception:
        return False
    return False


def _followups(muted: dict, today: str) -> list[dict]:
    from workers.closure_check import _expire_care, _care_parse
    now = datetime.now(_CST)
    cog = _cached_cognition()
    raw = _load().get("items") or []
    items, _ = _expire_care(list(raw), now)
    out = []
    for it in items:
        sid = "f-" + (it.get("signal") or it.get("first_ts") or "")
        if muted.get(sid) == today:
            continue
        if int(it.get("surfaced_count") or 0) >= 2:
            continue
        days = _days(it.get("first_ts") or "")
        kind = _kind(it.get("signal") or "", it.get("text") or "")
        ft = _care_parse(it.get("first_ts"))
        ripe = bool(ft and (now - ft).total_seconds() >= 18 * 3600)
        out.append({
            "id": sid,
            "kind": kind,
            "title": (it.get("text") or it.get("signal") or "").strip()[:48],
            "signal": it.get("signal") or "",
            "days": days,
            "ripe": ripe,
            "line": _line_for(kind, it.get("text") or "", cog),
        })
    if is_busy_daemon():
        busy = [x for x in out if x.get("ripe")]
        out = busy[:1]
    return out[:4]


def _late_nights() -> int:
    """从状态卡读作息/健康基线 · 不再扫 sessions 反推。"""
    sc = (_cached_cognition().get("state_card") or {})
    blob = f"{_sc_val(sc, '健康基线')} {_sc_val(sc, '作息模式')}"
    if any(k in blob for k in _LATE_NIGHT_MARKERS):
        return 3
    return 0


def _late_night_title() -> str:
    sc = (_cached_cognition().get("state_card") or {})
    health = _sc_val(sc, "健康基线")
    schedule = _sc_val(sc, "作息模式")
    return health or schedule or "最近作息有点晚"


def _last_chat() -> dict:
    # 2026-08-29 · 「上次聊到」mtime 抽奖已卸 · 形状留给茶桌 JSON，不再填
    return {"title": "", "gap": "", "gap_hours": None}


def _focus() -> dict | None:
    """关键事件流大半是工程流水账, 当「惦记」会假。先空着。"""
    return None


def _hero(hour: int, nights: int, follows: list) -> str:
    if 5 <= hour < 11:
        if nights >= 3:
            return "夜里你两点还在，我没吵你。早上第一句从我开始——吃了吗，别用咖啡顶。"
        return "早。我在这儿。"
    if hour >= 23 or hour < 5:
        return "还没收是吧。我不催，茶放这儿。"
    if follows:
        return "有几件我想问问。你点了，我再说。"
    return "没什么非说不可的。茶还热着。"


def build_care_desk() -> dict:
    today = datetime.now().date().isoformat()
    d = _load()
    muted = d.get("muted") or {}
    follows = _followups(muted, today)
    nights = _late_nights()
    last = _last_chat()
    focus = _focus()
    if focus and muted.get(focus["id"]) == today:
        focus = None
    name = _ai_name()
    radar = None
    if nights >= 3:
        radar = {
            "id": "radar-late",
            "nights": nights,
            "title": _late_night_title(),
            "line": "今晚早点收，我看着时间",
        }
        if muted.get("radar-late") == today:
            radar = None
    hour = datetime.now().hour
    return {
        "ai_name": name,
        "title": f"{name or '她'}给你泡的茶",
        "hero": _hero(hour, nights, follows),
        "followups": follows,
        "focus": focus,
        "radar": radar,
        "last": last,
        "empty": not follows and not focus and not radar,
    }


def dismiss_care(item_id: str) -> dict:
    item_id = (item_id or "").strip()
    if not item_id:
        return {"ok": False}
    d = _load()
    muted = dict(d.get("muted") or {})
    muted[item_id] = datetime.now().date().isoformat()
    d["muted"] = muted
    _save(d)
    return {"ok": True, "id": item_id}


def speak_care(session_id: str, line: str, signal: str = "") -> dict:
    """把她亲口那一句写进会话 · 卡片自己不出声。"""
    line = (line or "").strip()
    sid = (session_id or "").strip()
    if not line or not sid:
        return {"ok": False, "reason": "missing"}
    from daemon_session import append_turn
    append_turn(sid, "assistant", line, meta={"src": "tea"})
    try:
        from daemon_api import _API_SESSIONS
        msgs = _API_SESSIONS.get(sid)
        if isinstance(msgs, list):
            msgs.append({"role": "assistant", "content": line})
    except Exception:
        pass
    if signal:
        try:
            from workers.closure_check import mark_care_surfaced
            mark_care_surfaced(signal, proactive=True)
        except Exception:
            pass
    return {"ok": True}
