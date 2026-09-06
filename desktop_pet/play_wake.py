"""陪玩唤醒：只认名字，不把游戏声当句子。"""

from __future__ import annotations

OFF = "off"
STANDBY = "standby"
ACK = "ack"
LISTEN = "listen"
THINK = "think"
SPEAK = "speak"

_ECHO = ("我在", "在", "嗯", "啊", "呃")
_PUNCT = " \t，,。.!！?？、…~～"
_OPUS_ALIASES = ("opus", "欧普斯", "欧帕斯", "欧普丝", "欧普", "小欧")
# 短窗常见听岔。不把唤醒词塞回 whisper prompt（会连环醒）
_DAIMENG_ALIASES = ("呆萌", "呆蒙", "再猫", "在猫", "呆猫", "带猫", "代萌", "戴萌")
BYE_TEXT = "那我先做自己事情啦，有事再叫我"
LISTEN_IDLE_SEC = 8


def norm(text: str) -> str:
    out = []
    for ch in (text or "").lower():
        if ch.isalnum() or "\u4e00" <= ch <= "\u9fff":
            out.append(ch)
    return "".join(out)


def wake_phrases(word: str, name: str = "") -> list[str]:
    out: list[str] = []
    keys = [(word or "").strip(), (name or "").strip()]
    for raw in keys:
        if raw:
            out.append(raw)
        if raw.lower() == "opus" or raw in _OPUS_ALIASES:
            out.extend(_OPUS_ALIASES)
        if raw in _DAIMENG_ALIASES:
            out.extend(_DAIMENG_ALIASES)
    seen: set[str] = set()
    uniq: list[str] = []
    for p in out:
        key = norm(p)
        if key and key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _py(text: str) -> list[str] | None:
    try:
        from pypinyin import lazy_pinyin
    except ImportError:
        return None
    s = norm(text)
    return [x.lower() for x in lazy_pinyin(s)] if s else None


def _syl_ok(a: str, b: str) -> bool:
    if a == b:
        return True
    d = _lev(a, b)
    return d <= 1 or (a[:1] == b[:1] and d <= 2)


def _near(chunk: str, key: str) -> bool:
    if not chunk or not key:
        return False
    if chunk == key:
        return True
    pa, pb = _py(chunk), _py(key)
    if not pa or not pb or len(pa) != len(pb):
        return False
    # 两字名短窗常把韵母听飞（呆萌→再猫），声母对上就收
    if len(pa) == 2:
        return _lev(pa[0], pb[0]) <= 1 and pa[1][:1] == pb[1][:1]
    return all(_syl_ok(x, y) for x, y in zip(pa, pb))


def _keys(phrases: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for p in phrases:
        key = norm(p)
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _hit(hay: str, key: str) -> int:
    """命中起点，没有就 -1。先精确再拼音近音。"""
    if not hay or not key:
        return -1
    i = hay.find(key)
    if i >= 0:
        return i
    n = len(key)
    if n < 2 or len(hay) < n:
        return -1
    for j in range(0, len(hay) - n + 1):
        if _near(hay[j : j + n], key):
            return j
    return -1


def heard_wake(text: str, phrases: list[str]) -> bool:
    hay = norm(text)
    if not hay:
        return False
    return any(_hit(hay, key) >= 0 for key in _keys(phrases))


def strip_wake(text: str, phrases: list[str]) -> str:
    hay = norm(text)
    keys = _keys(phrases)
    for _ in range(8):
        hit: tuple[int, int] | None = None
        for key in keys:
            i = _hit(hay, key)
            if i < 0:
                continue
            if hit is None or i < hit[0]:
                hit = (i, len(key))
        if hit is None:
            break
        i, n = hit
        hay = hay[:i] + hay[i + n :]
    return hay.strip(_PUNCT)


def is_echo(text: str) -> bool:
    n = norm(text)
    return (not n) or n in {norm(x) for x in _ECHO}


def on_wake(phase: str, remainder: str) -> tuple[str, str]:
    if phase not in (STANDBY, SPEAK):
        return phase, ""
    return ACK, (remainder or "").strip()


SIT_IDLE_SEC = 30 * 60


def should_sit_idle(phase: str, sit_since: float, now: float, capturing: bool,
                    idle_sec: float = LISTEN_IDLE_SEC) -> bool:
    """会话钟满了才退。人还在说话就等这句说完，噪声不清零。"""
    if phase != LISTEN or sit_since <= 0:
        return False
    if capturing:
        return False
    return (now - sit_since) >= idle_sec


def sitting_expired(last_turn: float, now: float, idle_sec: float = SIT_IDLE_SEC) -> bool:
    """这一轮开着就续；隔太久才换一条。不是每句话换。"""
    if last_turn <= 0:
        return False
    return (now - last_turn) >= idle_sec


def on_ack_done(pending: str) -> str:
    return THINK if (pending or "").strip() else LISTEN


def on_listen_end(text: str) -> str:
    if is_echo(text) or not (text or "").strip():
        return LISTEN
    return THINK


def on_think_done(reply: str) -> str:
    return SPEAK if (reply or "").strip() else LISTEN


def on_speak_done() -> str:
    return LISTEN
