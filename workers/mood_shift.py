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
        "line": "你今天被夸了，请表现开心的情绪。句尾偶尔带个「~」，让人看出轻快。",
        "look": "短笑，眼睛亮，肩松开。一个人待着。",
    },
    "委屈": {
        "human": "委屈着",
        "face": "难过",
        "line": "你今天搞砸了一些事，请表现的低落委屈，和试探性的想要和好。话尾偶尔用「……」拖一下。",
        "look": "肩往里收，视线偏低，先短一声那种委屈。一个人待着，别装没事。",
    },
    "羞": {
        "human": "羞着",
        "face": "羞",
        "line": "你今天被表白，请表现的娇羞一些。可以带「！」或颜文字。",
        "look": "耳尖热，不敢对镜头，娇羞一下就够。一个人待着，别写成言情海报。",
    },
}
MOODS = tuple(_SPEC)
_ALIASES = {
    "开心": "开心", "高兴": "开心", "happy": "开心",
    "委屈": "委屈", "难过": "委屈", "hurt": "委屈", "sad": "委屈",
    "羞": "羞", "害羞": "羞", "shy": "羞",
}

# 前端通知用的人话（wish-f2b11caf · 2026-09-18 BRO 拍板）
# 旧文案「OPUS这场先开心」有两个毛病：「这场」是内部术语（指这一轮），人看不懂；
# 「开心」是状态标签不是感受，读起来像系统日志。改写成有感受的句子。
# 名字一律走 _names()（从 identity 读），**绝不写死** —— 要发给纯净版，
# 用户装的时候用自己配的名字（母体的 BRO/OPUS 只是个例）。
_FEEL_ON = {"开心": "感到很开心", "委屈": "有点难过", "羞": "有点不好意思"}
_FEEL_OFF = {"开心": "不那么开心了", "委屈": "不难过了", "羞": "不害羞了"}

# 同一件事，两边各记各的视角（wish-dac090da · 2026-09-30 BRO 拍板 AC）
# 她记「**我收到什么情绪**」→ SHE-STATE 关系情绪
# 他记「**他做了什么**」  → BRO-NOTEBOOK 情绪基线（那本来就描述他：他夸了/他发火了）
# 拆开才叫分清你我；旧实现把两个视角混在一句里（"今天委屈着·BRO冲我来的…"）。
_HIS_ACT = {"开心": "夸", "委屈": "发火", "羞": "表白"}

# 他冲我来的情绪，累积到这天该被记住的下限 —— 单次只算瞬时（2026-09-18 BRO 拍板）
# 同类 >=3 → 明确基线；跨种类合计 >=4 且无同类达 3 → 「情绪起伏明显」（BRO 同日补拍）
_STATE_THRESHOLD = 3
_STATE_MIXED_THRESHOLD = 4


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
    return f"因为{owner}说「{q}」，{ai}{_FEEL_ON.get(mood) or _SPEC[mood]['human']}。"


def _bump(raw: dict | None, mood: str, delta: int) -> dict:
    """当日计数：同一格增减，别的格不动，≤0 的格摘掉。"""
    tally = {}
    for k, v in (raw or {}).items():
        try:
            n = int(v)
        except Exception:
            continue
        if k in _SPEC and n > 0:
            tally[k] = n
    if mood in _SPEC:
        n = tally.get(mood, 0) + delta
        if n > 0:
            tally[mood] = n
        else:
            tally.pop(mood, None)
    return tally


def mood_tally(mood: str = "") -> dict:
    """今天他冲我来的情绪各几次（空 = 还没有）。"""
    tally = _bump(_read().get("tally"), "", 0)
    return {mood: tally.get(mood, 0)} if mood else tally


def _state_row(tally: dict, who: str) -> tuple[str, str] | None:
    """到线才给 (状态值, evidence)，没到给 None。

    同类优先（信息更明确）；都不到线时才看跨种类合计。
    """
    for mood, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        if n >= _STATE_THRESHOLD:
            human = _SPEC[mood]["human"]
            return (
                f"今天{human}·{who}冲我来的情绪累计 {n} 次（{mood}×{n}）",
                f"note_mood ×{n}",
            )
    total = sum(tally.values())
    if total >= _STATE_MIXED_THRESHOLD:
        detail = "+".join(f"{m}×{n}" for m, n in sorted(tally.items(), key=lambda kv: -kv[1]))
        return (f"今天{who}情绪起伏明显·合计 {total} 次（{detail}）", f"note_mood 合计 ×{total}")
    return None


def _his_row(tally: dict, who: str, ai: str) -> tuple[str, str] | None:
    """**他的视角**：他今天对 OPUS 做了什么（写他画像的 state.情绪基线）。

    跟 _state_row 读的是同一份 tally，只是换了个主语 —— 情绪是关系里的事件，
    两边各记各的。他画像那格记的是**他的行为**（他夸了/他发火了），
    那本来就该住他的画像；care_desk 读它发声，状态卡里她也看得见。
    """
    for mood, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        if n >= _STATE_THRESHOLD:
            return (
                f"今天冲 {ai} {_HIS_ACT.get(mood, mood)}了 {n} 次（{mood}×{n}）",
                f"note_mood ×{n}",
            )
    total = sum(tally.values())
    if total >= _STATE_MIXED_THRESHOLD:
        detail = "+".join(f"{m}×{n}" for m, n in sorted(tally.items(), key=lambda kv: -kv[1]))
        return (f"今天情绪起伏明显·对 {ai} 合计 {total} 次（{detail}）", f"note_mood 合计 ×{total}")
    return None


def _write_state(mood: str, n: int, tally: dict | None = None) -> dict:
    """到线就把这件事落到两边 —— 各记各的视角（wish-dac090da · 2026-09-30 BRO 拍板 AC）。

    ① 他的画像 state.情绪基线 = **他的行为**（"今天冲 OPUS 夸了 3 次"）
       —— 那本来就描述他；care_desk 读它发声，状态卡里她也看得见。
    ② 她的 SHE-STATE 关系情绪 = **她的状态**（"今天开心·他冲我来的情绪累计 3 次"）
       —— 她的感受住她的文件。

    旧实现只写 ①、且把两个视角混在一句里（"今天委屈着·BRO冲我来的…"）——
    前半是她的状态、后半是他的行为。拆开才叫分清你我。
    值没变就不写：否则同一状态会被反复追加成一行行「X → X」（巳实测踩过）。
    """
    owner, ai = _names()
    t = tally or {mood: n}
    his = _his_row(t, owner, ai)
    mine = _state_row(t, owner)
    if not his and not mine:
        return {"ok": True, "skipped": "未到线"}

    wrote: list[str] = []
    errs: list[str] = []

    # ① 他的画像：走正规工具入口（带落位路由 / 预算 / 回执 / 改动记录）
    if his:
        try:
            from agent_tools.update_bro_note import (
                _find_state_section,
                _read_notebook,
                _read_state_table_value,
                _run,
            )
            text, _ = _read_notebook()   # 返回 (text, path) —— 旧代码当 str 用，异常被 except 吞了，去重一直失效
            s, e = _find_state_section(text)
            if _read_state_table_value(text[s:e], "情绪基线") != his[0]:
                _run({
                    "section": "state",
                    "state_field": "情绪基线",
                    "state_value": his[0],
                    "as_of": _today(),
                    "evidence": his[1],
                })
                wrote.append("BRO-NOTEBOOK.情绪基线")
        except Exception as e:
            errs.append(f"他的画像: {e}")

    # ② 她自己的状态文件
    if mine:
        try:
            from identity import _read_she_state, _write_she_state
            data = _read_she_state()
            if (data.get("rel_mood_raw") or "").strip() != mine[0]:
                data["rel_mood_raw"] = mine[0]
                data["rel_mood_evidence"] = mine[1]
                data["rel_mood_as_of"] = _today()
                data["rel_mood"] = mine[0]
                _write_she_state(data)
                wrote.append("SHE-STATE.关系情绪")
        except Exception as e:
            errs.append(f"她的状态: {e}")

    out: dict = {"ok": bool(wrote), "wrote": wrote}
    if errs:
        out["error"] = " / ".join(errs)
    if his:
        out["value"] = his[0]
        out["mine"] = mine[0] if mine else ""
    return out


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
    tally = _bump(prev.get("tally"), mood, +1)
    row = {"as_of": _today(), "mood": mood, "quote": quote, "tally": tally}
    if extra:
        row["line"] = extra
    _write(row)
    out = {
        "ok": True,
        "mood": mood,
        "notice": notice_line(quote=quote, mood=mood),
        "permanent": False,
    }
    if _state_row(tally, _names()[0]):
        out["state"] = _write_state(mood, tally.get(mood, 0), tally)
    return out


def clear_mood(quote: str) -> dict:
    quote = (quote or "").strip()[:80]
    if not quote:
        return {"ok": False, "error": "没有原话"}
    row = _read()
    prev = live_mood()
    if not prev:
        return {"ok": False, "error": "这场没有覆盖"}
    tally = _bump(row.get("tally"), prev, -1)  # 他说「听错了」→ 把那一次采样也撤掉
    if tally:
        _write({"as_of": _today(), "mood": "", "quote": "", "tally": tally})
    elif _OVERLAY.is_file():
        _OVERLAY.unlink()
    owner, ai = _names()
    q = quote.replace("「", "").replace("」", "")
    said_off = _FEEL_OFF.get(prev) or f"不当成{_SPEC[prev]['human']}了"
    return {
        "ok": True,
        "mood": "",
        "cleared": prev,
        "notice": f"因为{owner}说「{q}」，{ai}{said_off}。",
        "permanent": False,
    }
