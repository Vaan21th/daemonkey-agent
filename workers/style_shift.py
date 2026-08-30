"""听懂换挡：当天临时覆盖，30 天同向满 3 次写本子。"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from workers.taste_chat import _BAND_VALUES, apply_named_bands, named_band_value

ROOT = Path(__file__).resolve().parent.parent
_LEDGER = ROOT / "data" / "runtime" / "style_shift.jsonl"
_OVERLAY = ROOT / "data" / "runtime" / "style_shift_today.json"

DIMS = ("话量", "调性", "语气", "礼节", "表现力")
_DIM_ALIAS = {"力度": "语气"}
WINDOW_DAYS = 30
PERM_HITS = 3

_ORDER: dict[str, tuple[str, ...]] = {
    "话量": ("无口", "寡言", "平常", "健谈", "话痨"),
    "调性": ("正经", "自然", "梗多"),
    "语气": ("毒舌", "随和", "温柔"),
    "礼节": ("敬语", "得体", "随便"),
    "表现力": ("棒读", "普通", "鲜活"),
}
_HUMAN = {
    ("话量", "down"): "少说",
    ("话量", "up"): "多说",
    ("调性", "down"): "正经一点",
    ("调性", "up"): "可以贫一点",
    ("语气", "down"): "损一点",
    ("语气", "up"): "温柔一点",
    ("礼节", "down"): "客套一点",
    ("礼节", "up"): "随便一点",
    ("表现力", "down"): "普通一点",
    ("表现力", "up"): "放开一点",
}


def _today() -> str:
    return date.today().isoformat()


def _names() -> tuple[str, str]:
    try:
        from identity import ai_name, owner_name
        return (owner_name() or "他").strip(), (ai_name() or "我").strip()
    except Exception:
        return "他", "我"


def _nearest_word(dim: str, val: int) -> str:
    table = _BAND_VALUES[dim]
    return min(table, key=lambda w: abs(int(table[w]) - int(val)))


def step_word(dim: str, val: int, direction: str) -> str:
    order = _ORDER[dim]
    word = _nearest_word(dim, val)
    idx = order.index(word)
    if direction == "down":
        idx = max(0, idx - 1)
    else:
        idx = min(len(order) - 1, idx + 1)
    return order[idx]


def _read_overlay() -> dict:
    if not _OVERLAY.is_file():
        return {}
    try:
        data = json.loads(_OVERLAY.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    if str(data.get("as_of") or "") != _today():
        return {}
    return data if isinstance(data, dict) else {}


def _write_overlay(data: dict) -> None:
    _OVERLAY.parent.mkdir(parents=True, exist_ok=True)
    _OVERLAY.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def live_dims() -> dict:
    from identity import style_dims
    base = dict((style_dims().get("dims") or {}))
    ov = _read_overlay().get("dims") or {}
    if isinstance(ov, dict):
        for k, v in ov.items():
            ck = _DIM_ALIAS.get(k, k)
            if ck in DIMS:
                try:
                    base[ck] = int(v)
                except (TypeError, ValueError):
                    pass
    try:
        from workers.bond_ledger import thin_mask
        from workers.taste_chat import named_band_value
        for dim, word in (thin_mask() or {}).items():
            val = named_band_value(dim, word)
            if val is not None:
                base[dim] = val
    except Exception:
        pass
    return base


def _append_ledger(row: dict) -> None:
    _LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with _LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def count_hits(dim: str, direction: str, *, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=WINDOW_DAYS)
    n = 0
    if not _LEDGER.is_file():
        return 0
    for line in _LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("dim") != dim or rec.get("direction") != direction:
            continue
        raw = str(rec.get("ts") or "")
        try:
            ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if ts >= cutoff:
            n += 1
    return n


def notice_line(*, quote: str, human: str, permanent: bool) -> str:
    owner, ai = _names()
    q = (quote or "").strip().replace("「", "").replace("」", "")
    when = "以后" if permanent else "这场先"
    return f"因为{owner}说「{q}」，{ai}{when}{human}。"


def apply_shift(dim: str, direction: str, quote: str) -> dict:
    dim = _DIM_ALIAS.get((dim or "").strip(), (dim or "").strip())
    direction = (direction or "").strip().lower()
    if direction in ("降", "少", "低"):
        direction = "down"
    if direction in ("升", "多", "高"):
        direction = "up"
    quote = (quote or "").strip()[:80]
    if dim not in DIMS:
        return {"ok": False, "error": "维不对"}
    if direction not in ("down", "up"):
        return {"ok": False, "error": "方向不对"}
    if not quote:
        return {"ok": False, "error": "没有原话"}

    from identity import style_dims
    base = int((style_dims().get("dims") or {}).get(dim, 50))
    word = step_word(dim, base, direction)
    val = named_band_value(dim, word)
    if val is None:
        return {"ok": False, "error": "对不上段"}

    now = datetime.now(timezone.utc)
    _append_ledger({
        "ts": now.isoformat(),
        "dim": dim,
        "direction": direction,
        "quote": quote,
        "word": word,
    })
    hits = count_hits(dim, direction, now=now)
    permanent = hits >= PERM_HITS
    human = _HUMAN[(dim, direction)]

    ov = _read_overlay() or {"as_of": _today(), "dims": {}, "words": {}}
    ov["as_of"] = _today()
    ov.setdefault("dims", {})[dim] = val
    ov.setdefault("words", {})[dim] = word
    _write_overlay(ov)

    if permanent:
        apply_named_bands({dim: word}, evidence=f"跳档:{quote}")

    notice = notice_line(quote=quote, human=human, permanent=permanent)
    return {
        "ok": True,
        "dim": dim,
        "direction": direction,
        "word": word,
        "hits": hits,
        "permanent": permanent,
        "notice": notice,
        "human": human,
    }
