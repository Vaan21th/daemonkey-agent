"""相处磨合 · 闲聊里定五维。mode=taste 时挂进 system。不进稳定灵魂文件。"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SETTLED = ROOT / "data" / "runtime" / "taste_settled.json"

# 前端静默开场用同一句 · daemon 用它当第一句，不进气泡。
TASTE_OPEN = "开始问说话方式。"

def taste_mode_note() -> str:
    voice = ""
    try:
        from identity import effective_persona_style
        voice = (effective_persona_style() or "").strip()
    except Exception:
        voice = ""
    if not voice:
        voice = "直接、密度高、克制，像很熟的搭档，不客套不端着"
    return (
    "\n\n=== 这场是问说话方式 ===\n"
    f"现在这张嘴：{voice}。没让你换人就按这张说。\n"
    "问的是以后你怎么跟他说话。他用人话答，你在心里对上段名。段名只进 commit_taste，不准出现在你说出口的句子里。\n"
    "禁止问卷腔：禁止报选项清单，禁止「记下『X』」，禁止「下一件」，禁止「五件事」，"
    "禁止「无口/寡言/平常/健谈/话痨」这类词出现在对他说的话里。\n"
    "- 每轮只问一件，一句人话。他回了再问下一件。顺序固定，问法按初见口吻改，不要照抄：\n"
    "  1 话量：以后我话多一点，还是收着点说？\n"
    "  2 调性：正经聊，还是可以贫两句？\n"
    "  3 语气：损你两句你吃得住，还是温柔点？\n"
    "  4 礼节：客套我就不整了？\n"
    "  5 表现力：说话普通一点，还是放开一点？\n"
    "- 听他的人话对段名（对不上就这维不传）：\n"
    "  话量 无口/寡言/平常/健谈/话痨；调性 正经/自然/梗多；"
    "语气 毒舌/随和/温柔；礼节 敬语/得体/随便；表现力 棒读/普通/鲜活。\n"
    "- 「正常就行」→平常；「玩笑多一点」→梗多；「随便来」→随便；「你看着来」→这维不传。\n"
    "- 五件问完：一句人话收，「那以后我就少说点、损一点，别那么客气。就这样？」按他对过的改。\n"
    "- 他说行 / 就这样 / 嗯：立刻 commit_taste，停问。某一维再改：只改那维，再确认一次。\n"
    "- 他说今天先这样：不要 commit_taste。\n"
    "- commit_taste：没让你换一种人就不要传 persona_style；他说改成猫娘/换嘴这种才传。"
    "五维只传对上的段名，没对上的不要传。\n"
    "- 不要举例对照，不要问处境，不要报数字。除了 commit_taste 不要调其它工具。\n"
    )

_BAND_VALUES: dict[str, dict[str, int]] = {
    "话量": {"无口": 22, "寡言": 35, "平常": 50, "健谈": 72, "话痨": 88},
    "调性": {"正经": 28, "自然": 50, "梗多": 78},
    "语气": {"毒舌": 28, "随和": 50, "温柔": 78},
    "力度": {"毒舌": 28, "随和": 50, "温柔": 78},
    "礼节": {"敬语": 28, "得体": 50, "随便": 78},
    "表现力": {"棒读": 28, "普通": 50, "含着": 50, "适度": 50, "鲜活": 78},
}


def named_band_value(dim: str, word: str) -> int | None:
    table = _BAND_VALUES.get(dim) or {}
    key = (word or "").strip()
    if key in table:
        return table[key]
    return None


def taste_settled() -> bool:
    try:
        return _SETTLED.is_file()
    except OSError:
        return False


def mark_taste_settled() -> None:
    _SETTLED.parent.mkdir(parents=True, exist_ok=True)
    _SETTLED.write_text(
        json.dumps({"ok": True, "as_of": date.today().isoformat()}, ensure_ascii=False),
        encoding="utf-8",
    )


def apply_named_bands(bands: dict, *, evidence: str = "相处磨合") -> dict:
    """把段名写成 SHE-STATE 五维。只动传入的维。"""
    from identity import adjust_style_dims, style_dims

    raw = bands if isinstance(bands, dict) else {}
    current = (style_dims().get("dims") or {})
    signals: dict[str, int] = {}
    applied: dict[str, str] = {}
    for dim, table in _BAND_VALUES.items():
        if dim == "力度":
            continue
        word = str(raw.get(dim) or (raw.get("力度") if dim == "语气" else "") or "").strip()
        if not word or word not in table:
            continue
        target = table[word]
        now = int(current.get(dim, 50))
        delta = target - now
        if delta:
            signals[f"{dim}_delta"] = delta
        applied[dim] = word
    dims = current
    if signals:
        dims = adjust_style_dims(signals, evidence=evidence)
    return {"dims": dims, "applied": applied}
