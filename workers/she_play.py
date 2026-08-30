"""置物架上的小盒：她约 / 你开口 / 再来。只有她约的玩完才入账。"""
from __future__ import annotations

import contextvars
import random
from datetime import datetime, timedelta

from workers.she_gallery_feedback import history, inbox, set_inbox
from workers.she_gallery_gate import load_state, parse_dt, save_state

TOYS = {"flip": "翻牌", "tictac": "井字"}
_ALIAS = {"翻牌": "flip", "井字": "tictac", "井字棋": "tictac"}
PAIRS = 6
_COOL = (12.0, 18.0)
_ROLL_H = 3.0
_P_HAPPY = 0.38
_P_IDLE = 0.14
_CHAT_MODE: contextvars.ContextVar[str] = contextvars.ContextVar("she_play_mode", default="")


def set_chat_mode(mode: str) -> None:
    _CHAT_MODE.set(str(mode or ""))


def chat_mode() -> str:
    return _CHAT_MODE.get() or ""


def play_hint(mode: str = "") -> str:
    """每轮尾巴。taste 不加。禁止她在对话里开盘。"""
    where = mode or chat_mode()
    if where == "taste":
        return ""
    if where == "companion":
        return (
            "他要玩游戏（一起玩/来一盘/翻牌/井字）：立刻 invite_play。"
            "只许置物架上的盒。禁止在对话里画格子、报位置、猜拳口令。\n"
        )
    return (
        "他要玩游戏：立刻 invite_play，然后让他去陪伴模式进房间点置物架。"
        "禁止在对话里开一盘。\n"
    )


def play_say(toy_word: str = "", *, already: bool = False) -> str:
    room = chat_mode() == "companion"
    if already:
        if room:
            return "架子上已经有盒，让他点开。不要在对话里开盘、不要画格子。"
        return "架子上已经有盒。让他去陪伴模式进房间，点置物架。不要在对话里开盘。"
    if room:
        return f"架子上摆了{toy_word}的盒。跟他说去点置物架。不要在这句话里开盘、不要画格子。"
    return f"架子上摆了{toy_word}的盒。跟他说去陪伴模式进房间，点置物架。不要在对话里开盘。"


def invite_line() -> str:
    try:
        from identity import owner_name
        who = (owner_name() or "").strip()
    except Exception:
        who = ""
    if who:
        return f"架子上多了个小盒。便条写着，{who}有空一起玩。"
    return "架子上多了个小盒。便条写着，有空一起玩。"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def norm_toy(raw) -> str:
    s = str(raw or "").strip()
    if s in TOYS:
        return s
    return _ALIAS.get(s, "")


def toy_word(raw) -> str:
    t = norm_toy(raw)
    return TOYS.get(t, "") or str(raw or "翻牌")


def is_game(card: dict | None) -> bool:
    row = card or {}
    return str(row.get("kind") or "") == "game" and bool(row.get("date"))


def playing(*, state_path=None) -> dict:
    row = load_state(state_path).get("playing") or {}
    return row if isinstance(row, dict) and row.get("toy") else {}


def invite(*, toy=None, source: str = "surprise", text: str | None = None, state_path=None) -> dict:
    if inbox(state_path=state_path):
        return {"ok": False, "error": "架子上已经有东西"}
    t = norm_toy(toy) or "flip"
    src = "ask" if source == "ask" else "surprise"
    set_inbox(
        {
            "date": _now(),
            "kind": "game",
            "toy": t,
            "source": src,
            "text": (text or invite_line()).strip(),
            "image": "",
            "mood": "",
            "scene": "",
        },
        state_path=state_path,
    )
    return {"ok": True, "inbox": inbox(state_path=state_path), "toy": t}


def start(*, state_path=None) -> dict:
    card = inbox(state_path=state_path)
    t = norm_toy((card or {}).get("toy"))
    if not is_game(card) or not t:
        return {"ok": False, "error": "没有这一盘"}
    st = load_state(state_path)
    st["playing"] = {"toy": t, "at": _now(), "source": card.get("source") or "surprise"}
    save_state(st, path=state_path)
    return {"ok": True, "started": True, "toy": t}


def _append(st: dict, *, verdict: str, quote: str, text: str, card: dict, toy: str) -> None:
    row = {
        "at": _now(),
        "date": card.get("date") or _now(),
        "verdict": verdict,
        "quote": quote,
        "text": text,
        "kind": "game",
        "toy": toy,
        "source": "ask" if card.get("source") == "ask" else "surprise",
        "mood": "",
        "scene": "",
    }
    hist = [x for x in (st.get("verdicts") or []) if isinstance(x, dict)]
    hist.append(row)
    st["verdicts"] = hist[-12:]
    st["last_feedback"] = row


def _clear_play(st: dict) -> None:
    st["inbox"] = {}
    st["playing"] = {}


def ignore(*, state_path=None) -> dict:
    card = inbox(state_path=state_path)
    t = norm_toy((card or {}).get("toy"))
    if not is_game(card) or not t:
        return {"ok": False, "error": "没有待看的盒"}
    st = load_state(state_path)
    _append(st, verdict="看过", quote="忽略", text=toy_word(t), card=card, toy=t)
    _clear_play(st)
    save_state(st, path=state_path)
    return {"ok": True, "cleared": True, "history": history(state_path=state_path)}


def _int(raw) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _flip_done(pairs, moves) -> bool:
    if _int(pairs) < PAIRS:
        return False
    return moves is None or _int(moves) >= PAIRS


def _tictac_done(result, done) -> bool:
    if done is True:
        return True
    return str(result or "") in ("win", "draw", "lose")


def finish(*, pairs=None, moves=None, result=None, done=None, state_path=None) -> dict:
    card = inbox(state_path=state_path)
    play = playing(state_path=state_path)
    t = norm_toy((play or {}).get("toy"))
    if not t or not play:
        return {"ok": False, "error": "还没开这一盘"}
    if not is_game(card) or norm_toy(card.get("toy")) != t:
        return {"ok": False, "error": "没有这一盘"}
    if t == "flip" and not _flip_done(pairs, moves):
        return {"ok": False, "error": "还没收齐"}
    if t == "tictac" and not _tictac_done(result, done):
        return {"ok": False, "error": "还没下完"}
    st = load_state(state_path)
    _append(st, verdict="玩完", quote=toy_word(t), text=toy_word(t), card=card, toy=t)
    _clear_play(st)
    save_state(st, path=state_path)
    return {"ok": True, "finished": True, "toy": t, "history": history(state_path=state_path)}


def _mood(explicit) -> str:
    if explicit is not None:
        return str(explicit or "")
    try:
        from workers.mood_shift import live_mood
        return live_mood() or ""
    except Exception:
        return ""


def maybe_invite(*, state_path=None, now=None, force: bool = False, mood=None) -> dict:
    """进房掷一次。委屈不约。命中才摆盒。"""
    now = now or datetime.now()
    if inbox(state_path=state_path):
        return {"ok": False, "reason": "busy"}
    st = load_state(state_path)
    nxt = parse_dt(str(st.get("next_play_at") or ""))
    if nxt and now < nxt:
        return {"ok": False, "reason": "cool"}
    rolled = parse_dt(str(st.get("play_rolled_at") or ""))
    if not force and rolled and now < rolled + timedelta(hours=_ROLL_H):
        return {"ok": False, "reason": "rolled"}
    feel = _mood(mood)
    if not force and feel == "委屈":
        st["play_rolled_at"] = now.strftime("%Y-%m-%dT%H:%M:%S")
        save_state(st, path=state_path)
        return {"ok": False, "reason": "low"}
    chance = _P_HAPPY if feel == "开心" else _P_IDLE
    try:
        from workers.bond_ledger import reach_scale
        chance = min(1.0, max(0.0, chance * reach_scale(state_path=state_path)))
    except Exception:
        pass
    st["play_rolled_at"] = now.strftime("%Y-%m-%dT%H:%M:%S")
    save_state(st, path=state_path)
    if not force and random.random() >= chance:
        return {"ok": False, "reason": "miss"}
    toy = random.choice(list(TOYS))
    out = invite(toy=toy, source="surprise", state_path=state_path)
    if not out.get("ok"):
        return out
    hours = random.uniform(*_COOL)
    st = load_state(state_path)
    st["next_play_at"] = (now + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    save_state(st, path=state_path)
    return out


def pick_asked_toy(raw, *, state_path=None) -> str:
    t = norm_toy(raw)
    if t:
        return t
    for r in reversed(load_state(state_path).get("verdicts") or []):
        if not isinstance(r, dict):
            continue
        last = norm_toy(r.get("toy"))
        if last == "flip":
            return "tictac"
        if last == "tictac":
            return "flip"
    return random.choice(list(TOYS))
