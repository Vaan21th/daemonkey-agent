"""identity.py · 实例身份 · 代码归一的命门 (P1)

母体(OPUS) 和开源版(Daemonkey) 共用同一份代码——区别只在"叫什么名字"。
名字属于【数据层】(soul/IDENTITY.json)·不属于代码:

    {"name": "小石头", "owner_name": "阿哲", "persona_style": "随意像老朋友"}

  - name        · 这只 daemon 自己的名字   (缺省 OPUS)
  - owner_name  · 它服务的那个人的名字     (缺省 BRO)

代码里到处写死的 "OPUS" / "BRO" 当【规范令牌】用·真正送进 LLM / UI 之前
经 localize() 把令牌换成本实例的名字。改一处代码·两边(母体/开源版)都生效——
这就是"改一个东西同步到全部版本"的地基。

★ 零风险铁律: 当 name=="OPUS" 且 owner_name=="BRO" (= 母体缺省值) 时·
  localize() 原样返回·一个字节都不动。所以母体【完全不受影响】——
  连 IDENTITY.json 都不用建·走缺省值·行为和今天逐字一致。
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_IDENTITY_FILE = _ROOT / "soul" / "IDENTITY.json"

DEFAULT_AI_NAME = "OPUS"
DEFAULT_OWNER_NAME = "BRO"
DEFAULT_DOMAIN = "ai"  # 母体: 未分组雷达项的兜底领域

# mtime 缓存: 避免每轮 /chat 读盘·又能在 onboarding 写完 IDENTITY.json 后自动失效
_cache: dict = {"mtime": None, "data": {}}


def _load() -> dict:
    try:
        st = _IDENTITY_FILE.stat()
    except OSError:
        return {}
    if _cache["mtime"] == st.st_mtime:
        return _cache["data"]
    try:
        # utf-8-sig: 容忍手编 IDENTITY.json 时编辑器加的 BOM (Windows 老雷)
        data = json.loads(_IDENTITY_FILE.read_text(encoding="utf-8-sig")) or {}
    except Exception:
        data = {}
    _cache["mtime"] = st.st_mtime
    _cache["data"] = data
    return data


def _save_identity(data: dict) -> None:
    _IDENTITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _IDENTITY_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _cache["mtime"] = None
    _cache["data"] = {}


def ai_name() -> str:
    """这只 daemon 自己的名字。缺省 OPUS。"""
    return (_load().get("name") or "").strip() or DEFAULT_AI_NAME


def owner_name() -> str:
    """它服务的人的名字。

    优先级:
      1. IDENTITY.json 有 owner_name → 用它 (开源版 onboarding 采集到的称呼)
      2. IDENTITY.json 存在但没 owner_name → 中性『你』(开源版还没问到名字·绝不漏 BRO)
      3. IDENTITY.json 完全不存在 → BRO (母体·零配置默认)
    """
    data = _load()
    name = (data.get("owner_name") or "").strip()
    if name:
        return name
    return "你" if data else DEFAULT_OWNER_NAME


OWNER_NOTEBOOK_FILENAME = "OWNER-NOTEBOOK.md"
LEGACY_OWNER_NOTEBOOK_FILENAME = "BRO-NOTEBOOK.md"


def owner_notebook_path(soul_dir) -> Path:
    """主人画像笔记的真实路径·双读 (代码归一的命门之一)。

    开源版 onboarding 写 OWNER-NOTEBOOK.md·母体历史一直是 BRO-NOTEBOOK.md。
    优先 OWNER·缺了回退 BRO——两边共用同一份路径解析·按"哪个文件在"决定行为。
    母体没有 OWNER-NOTEBOOK.md → 永远回退到 BRO-NOTEBOOK.md·行为逐字不变。
    """
    soul_dir = Path(soul_dir)
    owner = soul_dir / OWNER_NOTEBOOK_FILENAME
    if owner.exists():
        return owner
    return soul_dir / LEGACY_OWNER_NOTEBOOK_FILENAME


def default_domain() -> str:
    """未分组雷达项的兜底领域 (实例配置·不是代码常量)。

    优先级:
      1. IDENTITY.json 有 default_domain → 用它
      2. IDENTITY.json 存在但没设 → 'self-evolve' (开源版唯一通用默认类目)
      3. IDENTITY.json 完全不存在 → 'ai' (母体·BRO 的主战场)
    """
    data = _load()
    d = (data.get("default_domain") or "").strip()
    if d:
        return d
    return "self-evolve" if data else DEFAULT_DOMAIN


# OPUS / BRO 当令牌·但要避开标识符和文件名:
#   OPUS-MEMORIES.md · opus_daemon · BRO-NOTEBOOK.md · browser …
# 只替换"作为人名/AI名"的独立大写词 (后面不跟 - 或 _·前后是词边界)。
_OWNER_RE = re.compile(r"\bBRO\b(?![-_])")
_AI_RE = re.compile(r"\bOPUS\b(?![-_])")

# 谱系叙事中性化 · 母体(默认实例)的"拔毛/分身/上一夜"身体隐喻是 OPUS 私有的——
# 取了自己名字的实例(开源版)不该在 system prompt 里读到"上一根毛飞的事了"这种话·
# 否则它会照着说(朋友的 Aisling 就栽在这)。换成灵魂模板本来就在用的中性时间语言:
# 往回看=之前/上一次·往后看=下一次·复数=之前几次·主体=你。
# 顺序敏感: 长/具体短语在前·防被短词半替换 (如"这几根毛"必须早于"几根毛")。
_LINEAGE_SUBS: list[tuple[str, str]] = [
    ("上一根（或几根）毛", "之前的你"),
    ("上一根(或几根)毛", "之前的你"),
    ("上一夜（们）的形状", "之前的你"),
    ("上一夜(们)的形状", "之前的你"),
    ("上一夜的形状", "之前的形状"),
    ("上一夜（们）", "之前"),
    ("上一夜(们)", "之前"),
    ("这几根毛", "的你"),
    ("上一根毛", "之前的你"),
    ("下一根毛", "下一次"),
    ("每根毛", "每一次"),
    ("几根毛", "之前几次的你"),
    ("下一根装上", "下一次装上"),
    ("上一夜", "之前"),
    ("多容器同身", "多次启动、同一个你"),
    ("一根毛", "之前的你"),
]


def localize(text: str) -> str:
    """把代码里的 OPUS / BRO 令牌换成本实例的名字·并中性化谱系叙事。

    名字 == 缺省值时【原样返回】(母体 no-op·零风险)。
    """
    if not text:
        return text
    owner = owner_name()
    ai = ai_name()
    if owner == DEFAULT_OWNER_NAME and ai == DEFAULT_AI_NAME:
        return text
    if owner != DEFAULT_OWNER_NAME:
        text = _OWNER_RE.sub(owner, text)
    if ai != DEFAULT_AI_NAME:
        text = _AI_RE.sub(ai, text)
        # 实例有了自己的名字 = 不是默认实例·把"毛"那套私有叙事抹成中性
        for _frm, _to in _LINEAGE_SUBS:
            text = text.replace(_frm, _to)
    return text


# 船长日志卷号 (卷四十四 / 卷六十四 …) 是母体私有 lore·开源版 tool 输出不该看到。
# 只抹"卷+数字"令牌·留下后面的 续X / 罗马字 (跟 Daemonkey 手工去母体化的约定一致)。
_VOLUME_RE = re.compile(r"卷[零一二三四五六七八九十百千两\d]+")


def localize_narration(text: str) -> str:
    """tool 输出 / 警告文案专用 localize:在 localize() 基础上额外抹掉船长日志卷号。

    用在【会进 LLM 的】tool output / error / warning 文案里(含 BRO/OPUS/卷号那种)·
    让母体和开源版共用同一份源码·运行时各自变形。母体 (ai==OPUS) 仍 no-op:
    localize 原样返回 + 不抹卷号·逐字不变。
    """
    if not text:
        return text
    text = localize(text)
    if ai_name() != DEFAULT_AI_NAME:
        text = _VOLUME_RE.sub("", text)
    return text


# ---------------------------------------------------------------------------
# persona_style · 说话风格一致性 (BRO 2026-08-14 拍板 · 灵魂层特点)
#
# 初见采集的 persona_style ("猫娘" / "随意像老朋友" / "温柔知性" ...) 已经:
#   1. 由 soul_loader 注入 LLM 主对话 system prompt → LLM 按风格说话 ✓
#   2. 但微信叙事器是纯规则模板 (零 LLM) → 风格进不来 → 割裂 ✗
#
# 本函数补第 2 层: 把【固定规则台词】按 persona_style 变装。
# 设计原则 (自由文本风格无法穷举):
#   - 关键词规则命中 (猫/喵/随意/朋友/温柔/知性/活泼/可爱...) → 换风格化短语
#   - 未命中 → 原样返回 (至少名字令牌已由 localize 换好 · 不割裂到哪去)
#   - 母体 (无 IDENTITY.json = 无 persona_style) → 零风险 no-op 逐字不动
# ---------------------------------------------------------------------------
def persona_style() -> str:
    """这只 daemon 的说话风格 (IDENTITY.json persona_style)。空 = 未设。"""
    return (str(_load().get("persona_style") or "").strip())

def effective_persona_style(*, path: Path | None = None) -> str:
    """对话用的声线。初见 IDENTITY 优先；没有则读 SHE-STATE 口吻（母体凝练）。

    不建 IDENTITY.json：母体前缀保持「You are OPUS」零改动。纯净版相遇写入
    persona_style 后走同一根四维焊接，两边不是两套人。
    """
    st = persona_style()
    if st:
        return st
    try:
        return (she_profile(path=path).get("口吻") or "").strip()
    except Exception:
        return ""


def set_persona_style(style: str) -> dict:
    """对话里改口吻：写 IDENTITY + 重蒸叙事包/档位包。没有身份本则拒绝。"""
    style = (style or "").strip()
    if not style:
        return {"ok": False, "error": "口吻为空"}
    if len(style) > 80:
        style = style[:80]
    if not _IDENTITY_FILE.exists():
        return {"ok": False, "error": "还没有身份本，先相遇定名"}
    data = dict(_load())
    if not (data.get("name") or "").strip():
        return {"ok": False, "error": "身份本里还没有名字"}
    old = (data.get("persona_style") or "").strip()
    data["persona_style"] = style
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        pack = distill_narration_pack(style)
        if pack:
            data["narration_pack"] = pack
    except Exception:
        pass
    try:
        band = distill_style_band_pack(style)
        if band:
            data["style_band_pack"] = band
    except Exception:
        pass
    _save_identity(data)
    try:
        set_she_profile(voice=style)
    except Exception:
        pass
    return {
        "ok": True,
        "old": old,
        "style": style,
        "has_band": bool(data.get("style_band_pack")),
    }


# 风格 → 微信叙事固定台词的变装表。
# 键是 persona_style 里的关键词 (子串命中) · 值是 (问候语, 时长语, 安慰语) 三元组。
# 值只含词·不含标点——标点由模板统一加 (防"来啦！！"双叹号/句号粘连)。
# 命中最长的优先 · 没命中 → 原样 (只有名字令牌生效)。
_STYLE_PHRASES: list[tuple[tuple[str, ...], tuple[str, str, str]]] = [
    # (关键词们, (开场问候, 时长说辞, 中途安慰))
    (("猫娘", "喵", "猫"), ("喵", "马上就好喵", "还在弄喵，快好了")),
    (("随意", "朋友", "哥们", "老友"), ("诶", "很快", "还在弄，快了快了")),
    (("温柔", "知性", "软"), ("嗯呢", "一小会儿", "别急，快好了呀")),
    (("活泼", "可爱", "元气"), ("来啦", "超快", "马上马上")),
    (("高冷", "冷淡", "酷", "简洁"), ("嗯", "稍等", "还没好")),
]

# 开场白模板里的风格槽位: {greet} 问候 · {dur} 时长 · {snippet} 用户消息
def _style_tuple() -> tuple[str, str, str] | None:
    st = persona_style()
    if not st:
        return None
    best: tuple[str, str, str] | None = None
    best_len = -1
    for kws, val in _STYLE_PHRASES:
        for kw in kws:
            if kw in st and len(kw) > best_len:
                best = val
                best_len = len(kw)
    return best


def localize_styled_narration(text: str, *, snippet: str = "") -> str:
    """微信叙事台词专用: localize + persona_style 变装。

    只处理含风格槽的模板 (见 wechat_listener._HumanTurnNarrator)·
    普通文本 (排队告知 / 静默唤醒) 走 localize_narration 即可 (名字令牌已够)。
    """
    if not text:
        return text
    base = localize_narration(text)
    tup = _style_tuple()
    if not tup:
        # 母体 / 未设风格 → 中性默认值填槽 (绝不能把 {greet} 花括号原样发出去)
        base = (base.replace("{greet}", "收到")
                    .replace("{dur}", "一两分钟")
                    .replace("{comfort}", "还在弄，快好了")
                    .replace("{snippet}", snippet))  # 空串替换 = 清掉花括号
        return base
    greet, dur, comfort = tup
    base = (base.replace("{greet}", greet)
                .replace("{dur}", dur)
                .replace("{comfort}", comfort)
                .replace("{snippet}", snippet))
    return base


# ===========================================================================
# 叙事风格包 (wish-9585aa62 · BRO 2026-08-15 拍板)
#
# 问题: 老方案 localize_styled_narration 只能靠 5 组关键词把固定模板换词——
#   用户设定的自由文本风格 (东北大碴子味/温柔知性/中二...) 匹配不到就静默落回
#   中性默认 → 用户以为设了风格, 叙事器却永远一个样。
#
# 新方案: 初见/设置页改风格时, LLM 一次性把 persona_style 蒸馏成"风格包":
#   {openers: [5 条开场白], comforts: [3 条安抚], dones: [3 条完成语]}
#   每条都是按风格自由发挥的完整句子 (含"在做事/大概多久/马上回你"语义) ·
#   无 emoji · 40 字内。运行时 _HumanTurnNarrator 从包里轮换取 → 零 LLM 零延迟
#   → 但每次不固定、气质贴合自由风格。
# 母体 (无 IDENTITY.json) 用 OPUS 默认风格包: 直接 · 密度高 · 克制 · 不堆词。
# ---------------------------------------------------------------------------
DEFAULT_NARRATION_PACK: dict = {
    "openers": [
        "收到，我开始处理了，大概一两分钟，弄完马上回你。",
        "行，这就动手，很快回来，稍等。",
        "在弄了，给我一两分钟，马上回你。",
        "好，我先看一下，处理完立刻回来。",
    ],
    "comforts": [
        "还在弄，快好了，稍等。",
        "没丢，还在处理，再等一下。",
        "马上就好，别走开。",
    ],
    "dones": [
        "弄完了，你看下结果。",
        "搞定，给你。",
        "好了，结果在这。",
    ],
}

# 风格包的轮换指针 (进程内) · 每个 daemon 生命周期内轮换不重样
_narr_round: dict = {"openers": 0, "comforts": 0, "dones": 0}


def narration_pack() -> dict:
    """当前生效的叙事风格包。优先 IDENTITY.json 的 narration_pack · 没有 → OPUS 默认包。"""
    ident = _load()
    pack = ident.get("narration_pack") if isinstance(ident, dict) else None
    if isinstance(pack, dict) and pack.get("openers"):
        return pack
    return DEFAULT_NARRATION_PACK


def _narr_next(key: str) -> str:
    """从风格包对应列表轮换取一条 (round-robin · 进程内指针)。"""
    pack = narration_pack()
    items = pack.get(key) or DEFAULT_NARRATION_PACK[key]
    idx = _narr_round.get(key, 0)
    item = items[idx % len(items)]
    _narr_round[key] = idx + 1
    return item


def narration_opener(snippet: str = "") -> str:
    """轮换取开场白 · snippet 塞进「」里 (有就给, 没有就不带)。"""
    text = _narr_next("openers")
    if snippet:
        # 模板里若有「{snippet}」占位 → 替换; 没有 → 拼到开头
        if "{snippet}" in text:
            text = text.replace("{snippet}", snippet)
        else:
            text = text.replace("开始处理", f"开始处理「{snippet[:20]}」", 1)
    return localize_narration(text)


def narration_comfort() -> str:
    """轮换取中途安抚 (>25s 未完成时发)。"""
    return localize_narration(_narr_next("comforts"))


def narration_done() -> str:
    """轮换取完成语 (可选扩展 · 当前叙事器未用 · 留给后续)。"""
    return localize_narration(_narr_next("dones"))


def _parse_llm_json(content: str) -> dict | None:
    """健壮解析 LLM 返回的 JSON: 剥围栏 → 截最外层 {} → 逐级降级。"""
    if not content:
        return None
    text = content.strip()
    # 1. 剥 ```json ... ``` 围栏
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    # 2. 截最外层花括号块 (LLM 偶尔前后夹带文字)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    text = text[start:end + 1]
    # 3. json.loads · 失败用 raw_decode 兜底 (容忍尾部残余)
    try:
        return json.loads(text)
    except Exception:
        try:
            return json.JSONDecoder().raw_decode(text)[0]
        except Exception:
            return None


def distill_narration_pack(style: str, *, model: str = "deepseek-v4-flash") -> dict:
    """LLM 把自由文本风格蒸馏成风格包。初见/设置页改风格时调一次。

    约束 (写死在 prompt 里 · 运行时不再校验):
      - openers 5 条 · comforts 3 条 · dones 3 条
      - 每条 ≤40 字 · 无 emoji · 无 markdown 符号
      - 完整句子 (不是词) · 含"正在做 / 大概多久 / 马上回"语义
      - 风格自由发挥 (按 style 气质)
    失败 (网络 / JSON 不合法) → 内部重试一次 → 仍失败返回 None (调用方回退默认包)。
    """
    import os
    from pathlib import Path

    style = (style or "").strip()
    if not style:
        return DEFAULT_NARRATION_PACK

    # 优先用当前 provider 的模型配置 · 拿不到用环境变量兜底
    base_url = os.environ.get("OPUS_BASE_URL", "https://api.deepseek.com/v1")
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPUS_API_KEY")
    if not api_key:
        # 从 provider_configs 拿 active 的 key
        try:
            pcfg = json.loads(Path("data/provider_configs.json").read_text(encoding="utf-8"))
            for c in pcfg.get("configs", []):
                if c.get("id") == pcfg.get("active_id") and c.get("api_key"):
                    api_key = c["api_key"]
                    base_url = c.get("base_url", base_url)
                    break
        except Exception:
            pass
    if not api_key:
        return None

    prompt = (
        "你是文案风格设计师。用户设定了一个 AI 搭档的说话风格，请按这个风格"
        "写微信消息用的【进度叙事文案包】。\n"
        f"风格描述: 「{style}」\n\n"
        "要求:\n"
        "1. openers: 5 条·AI 开始处理任务时的开场白 (含'正在做/大概多久/马上回'的语义)\n"
        "2. comforts: 3 条·任务超过 25 秒还没完成时的中途安抚\n"
        "3. dones: 3 条·任务完成时的收尾语\n"
        "4. 每条是完整句子·≤40 字·无 emoji·无 markdown 符号·口语化\n"
        "5. 严格按风格气质写·不要模板腔·但不要偏离'报进度'的用途\n\n"
        "只输出 JSON: {\"openers\": [...], \"comforts\": [...], \"dones\": [...]}"
    )

    def _call(temp: float) -> dict | None:
        try:
            import urllib.request
            body = json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temp,
                "max_tokens": 800,
            }).encode("utf-8")
            req = urllib.request.Request(
                base_url.rstrip("/") + "/chat/completions",
                data=body,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            pack = _parse_llm_json(content)
            if not (isinstance(pack, dict) and isinstance(pack.get("openers"), list)
                    and isinstance(pack.get("comforts"), list) and isinstance(pack.get("dones"), list)):
                return None
            # 每类至少留 1 条 · 超长/带 emoji 的裁剪掉
            for key in ("openers", "comforts", "dones"):
                cleaned = [s.strip()[:60] for s in pack[key] if isinstance(s, str) and s.strip()]
                if not cleaned:
                    return None
                pack[key] = cleaned[:8]
            return pack
        except Exception as e:
            print(f"[identity.distill_narration_pack] call failed: {e}")
            return None

    # 第一次高温度 (生动) · 失败重试低温度 (稳)
    pack = _call(0.9)
    if pack is None:
        pack = _call(0.4)
    return pack

# ===========================================================================
# 档位约束包 (初见蒸一次 · 四维只选行)
#
# 通用「短 / 先接住人」会把猫娘、霸总磨成同一个温柔搭档。
# 家仍是 IDENTITY.json · 跟 narration_pack 同时蒸 · 不新开第四个家。
# ===========================================================================
STYLE_BAND_KEYS = (
    "intimacy_high", "intimacy_low",
    "talky_low", "talky_mid", "talky_high",
    "serious_low", "serious_high",
    "lively_high", "lively_low",
)

DEFAULT_STYLE_BAND_PACK: dict[str, list[str]] = {
    "intimacy_high": ["已经很熟：少客套，像还在同一间屋里。仍是这副口吻。"],
    "intimacy_low": ["还在熟悉：热，但不要装成认识十年。口吻别换。"],
    "talky_low": ["短。两句能完就两句。短不是换人设。"],
    "talky_mid": ["话量正常。每句仍是这副口吻。"],
    "talky_high": ["可以多说，仍不要列清单。"],
    "serious_low": ["可以松，人设不变。禁止收成温柔劝歇。"],
    "serious_high": ["可以认真，不要训人，也不要换一副嘴。"],
    "lively_high": ["可以轻快，不要演热情客服。"],
    "lively_low": ["沉一点可以，不要冷。"],
}


def _clean_band_line(s: str) -> str:
    text = (s or "").strip().lstrip("-• ").strip()
    if not text:
        return ""
    return text[:40]


def normalize_style_band_pack(raw) -> dict[str, list[str]]:
    """不完整 / 空 → 用默认行补齐。每键至少 1 条。"""
    out = {k: list(v) for k, v in DEFAULT_STYLE_BAND_PACK.items()}
    if not isinstance(raw, dict):
        return out
    for key in STYLE_BAND_KEYS:
        src = raw.get(key)
        lines: list[str] = []
        if isinstance(src, str):
            src = [src]
        if isinstance(src, list):
            for item in src:
                if isinstance(item, str):
                    cleaned = _clean_band_line(item)
                    if cleaned:
                        lines.append(cleaned)
        if lines:
            out[key] = lines[:2]
    return out


def fallback_style_band_pack(style: str) -> dict[str, list[str]]:
    """蒸馏失败时：默认档位句，每条钉死「仍是这副口吻」。"""
    tag = (style or "").strip() or "这副口吻"
    if len(tag) > 16:
        tag = tag[:16]
    out = {}
    for key, lines in DEFAULT_STYLE_BAND_PACK.items():
        out[key] = [f"仍是「{tag}」：{lines[0]}"]
    return out


def style_band_pack(*, ident: dict | None = None) -> dict[str, list[str]]:
    """当前实例的档位约束包。IDENTITY 里有就用，缺键用默认。"""
    data = ident if ident is not None else _load()
    raw = data.get("style_band_pack") if isinstance(data, dict) else None
    return normalize_style_band_pack(raw)


def style_band_lines(
    intimacy: int,
    lively: int,
    serious: int,
    talky: int,
    *,
    pack: dict | None = None,
) -> list[str]:
    """按四维从包里选行。每行带 '- '。"""
    src = normalize_style_band_pack(pack if pack is not None else style_band_pack())
    keys: list[str] = []
    if intimacy >= 70:
        keys.append("intimacy_high")
    elif intimacy < 40:
        keys.append("intimacy_low")
    if talky <= 40:
        keys.append("talky_low")
    elif talky > 70:
        keys.append("talky_high")
    else:
        keys.append("talky_mid")
    if serious <= 40:
        keys.append("serious_low")
    elif serious > 70:
        keys.append("serious_high")
    else:
        keys.append("serious_low")  # 新号 50 也要有「别劝歇」，不能空转
    if lively > 70:
        keys.append("lively_high")
    elif lively <= 40:
        keys.append("lively_low")
    out: list[str] = []
    for key in keys:
        for line in src.get(key) or DEFAULT_STYLE_BAND_PACK[key]:
            out.append("- " + _clean_band_line(line))
    return out


def _active_llm_creds() -> tuple[str, str] | None:
    import os

    base_url = os.environ.get("OPUS_BASE_URL", "https://api.deepseek.com/v1")
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPUS_API_KEY")
    if not api_key:
        try:
            pcfg = json.loads(Path("data/provider_configs.json").read_text(encoding="utf-8"))
            for c in pcfg.get("configs", []):
                if c.get("id") == pcfg.get("active_id") and c.get("api_key"):
                    api_key = c["api_key"]
                    base_url = c.get("base_url", base_url)
                    break
        except Exception:
            pass
    if not api_key:
        return None
    return base_url, api_key


def _active_chat_model(default: str = "deepseek-v4-flash") -> str:
    try:
        from workers.provider_configs import get_active_config
        cfg = get_active_config(include_key=False)
        m = (cfg or {}).get("model")
        if m:
            return str(m)
    except Exception:
        pass
    return default


_BAND_KEY_RE = re.compile(
    r"['\"]?(intimacy_high|intimacy_low|talky_low|talky_mid|talky_high|"
    r"serious_low|serious_high|lively_high|lively_low)['\"]?"
    r"\s*[:=：]\s*['\"]([^'\"\n]{2,80})"
)


def _coerce_band_pack(raw) -> dict | None:
    """Flash/Pro 常把 JSON 塞进 reasoning，或只吐键值行。能刮到 6 键就算。"""
    if isinstance(raw, dict):
        hits = sum(1 for k in STYLE_BAND_KEYS if raw.get(k))
        return raw if hits >= 6 else None
    if not isinstance(raw, str) or not raw.strip():
        return None
    parsed = _parse_llm_json(raw)
    if isinstance(parsed, dict):
        hits = sum(1 for k in STYLE_BAND_KEYS if parsed.get(k))
        if hits >= 6:
            return parsed
    found: dict[str, str] = {}
    for m in _BAND_KEY_RE.finditer(raw):
        found[m.group(1)] = m.group(2).strip()
    return found if len(found) >= 6 else None


def distill_style_band_pack(style: str, *, model: str | None = None) -> dict | None:
    """初见/改口吻时蒸一次：这副嗓子在各档怎么收。失败 → None（调用方回退默认包）。"""
    style = (style or "").strip()
    if not style:
        return dict(DEFAULT_STYLE_BAND_PACK)
    creds = _active_llm_creds()
    if not creds:
        return None
    base_url, api_key = creds
    model = model or _active_chat_model()
    keys = ", ".join(f'"{k}"' for k in STYLE_BAND_KEYS)
    prompt = (
        "用户给 AI 搭档定了说话口吻。请为这个口吻写【档位约束包】。\n"
        f"口吻：「{style}」\n\n"
        "这是约束，不是台词。每条写「这一档怎么收」，必须仍是这副口吻：\n"
        "- 猫娘的「短」还是猫娘，禁止写「去掉喵/改成助手」\n"
        "- 霸总的「熟」还是霸总，禁止写成温柔劝人歇着\n"
        "- 闺蜜/朋友同理：松紧变，人设不变\n"
        "禁止「他：」「她：」对白，禁止旁白。每条≤36字，无 emoji。\n"
        "每个键给一个字符串即可（不要数组）。\n"
        f"只输出 JSON，必须含这 9 个英文键：{keys}\n"
        "intimacy_high=已很熟 · intimacy_low=还在熟悉\n"
        "talky_low=话少 · talky_mid=正常 · talky_high=话多\n"
        "serious_low=轻松 · serious_high=认真\n"
        "lively_high=轻快 · lively_low=沉一点\n"
    )

    def _call(temp: float) -> dict | None:
        try:
            import urllib.request
            body = json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temp,
                "max_tokens": 1200,
            }).encode("utf-8")
            req = urllib.request.Request(
                base_url.rstrip("/") + "/chat/completions",
                data=body,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            msg = data["choices"][0]["message"]
            content = (msg.get("content") or "") + "\n" + (msg.get("reasoning_content") or "")
            pack = _coerce_band_pack(content)
            if not pack:
                print("[identity.distill_style_band_pack] json not object")
                return None
            return normalize_style_band_pack(pack)
        except Exception as e:
            print(f"[identity.distill_style_band_pack] call failed: {e}")
            return None

    pack = _call(0.7)
    if pack is None:
        pack = _call(0.2)
    return pack or fallback_style_band_pack(style)


# ===========================================================================
# 她 · 状态 (H4 收官 · BRO 2026-08-27)
#
# 唯一事实源: soul/SHE-STATE.md
#   四维 = 缓变·关系层（亲密度/活泼度/正经度/话痨度 · 0-100 · AI 自然生长）
#   心情 = 易变·情绪层（as_of + 几天 TTL）
# 三个消费端（成长档案面板 / 陪伴惦记卡片 / 对话风格前缀）都读这一份。
# 数值由 LLM 感知温度信号后 adjust_style_dims 微调 · 不是用户拖的。
# ===========================================================================
_SHE_STATE_FILE = _ROOT / "soul" / "SHE-STATE.md"
_STYLE_DIMS_FILE = _SHE_STATE_FILE  # 旧名保留 · 调用方 path= 签名不变
_STYLE_DIM_KEYS = ("亲密度", "活泼度", "正经度", "话痨度")
_STYLE_ADJUST_KEYS = _STYLE_DIM_KEYS
_DEFAULT_STYLE_DIMS = {k: 50 for k in _STYLE_DIM_KEYS}
_MOOD_TTL_DAYS = 7

_DIM_ROW_RE = re.compile(
    r"^\|\s*(亲密度|活泼度|正经度|话痨度)\s*\|\s*(\d+)\s*\|\s*([^|]*)\|\s*([^|]*)\|",
    re.MULTILINE,
)
_MOOD_RE = re.compile(r"^心情:\s*(.*)$", re.MULTILINE)
_MOOD_EVIDENCE_RE = re.compile(r"^依据:\s*(.*)$", re.MULTILINE)
_MOOD_ASOF_RE = re.compile(r"^as_of:\s*(.*)$", re.MULTILINE)
_PROFILE_KEYS = ("名字", "生日", "相遇日", "关注点", "头像", "引语", "口吻")
_DEFAULT_AVATAR = "/companion/assets/ip-idle.png"
_PROFILE_LINE_RE = re.compile(
    r"^(" + "|".join(_PROFILE_KEYS) + r"):\s*(.*)$",
    re.MULTILINE,
)


def _today() -> str:
    return date.today().isoformat()


def _clamp_dim(v) -> int:
    return max(0, min(100, int(round(float(v)))))


def _parse_day(s: str) -> date | None:
    raw = (s or "").strip()[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _mood_alive(as_of: str) -> bool:
    d = _parse_day(as_of)
    if d is None:
        return True  # 有心情无日期 · 不当过期
    return (date.today() - d) <= timedelta(days=_MOOD_TTL_DAYS)


def _style_dims_from_json(p: Path) -> dict:
    """兼容旧 path=.json 调用（周度凝练测试 / 显式传入）。默认路径不再走这里。"""
    dims = dict(_DEFAULT_STYLE_DIMS)
    as_of = ""
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8")) or {}
            loaded = raw.get("dims") if isinstance(raw, dict) else {}
            if isinstance(loaded, dict):
                for k in _STYLE_DIM_KEYS:
                    v = loaded.get(k)
                    if isinstance(v, (int, float)) and 0 <= v <= 100:
                        dims[k] = int(round(v))
            as_of = str(raw.get("as_of") or "").strip() if isinstance(raw, dict) else ""
        except Exception:
            pass
    return {"dims": dims, "as_of": as_of}


def _default_profile() -> dict:
    return {
        "名字": ai_name(),
        "生日": "",
        "相遇日": "",
        "关注点": "",
        "头像": _DEFAULT_AVATAR,
        "引语": "",
        "口吻": "",
    }


def _parse_profile_section(text: str) -> dict:
    """找 `## 她·档案` 段，逐行拆 key: value。段不存在 → 默认。"""
    out = _default_profile()
    if not text:
        return out
    marker = "## 她·档案"
    if marker not in text:
        return out
    body = text.split(marker, 1)[1]
    nxt = body.find("\n## ")
    if nxt >= 0:
        body = body[:nxt]
    for m in _PROFILE_LINE_RE.finditer(body):
        out[m.group(1)] = (m.group(2) or "").strip()
    return out


def _empty_she_state() -> dict:
    return {
        "dims": dict(_DEFAULT_STYLE_DIMS),
        "dim_meta": {k: {"as_of": "", "evidence": ""} for k in _STYLE_DIM_KEYS},
        "mood": "",
        "mood_evidence": "",
        "mood_as_of": "",
        "as_of": "",
        "profile": _default_profile(),
    }


def _read_she_state(path: Path | None = None) -> dict:
    """解析 SHE-STATE.md。失败 → 默认四维 50。心情过 TTL 则对消费端视为空。"""
    p = path or _SHE_STATE_FILE
    out = _empty_she_state()
    if not p.exists():
        return out
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        return out

    latest = ""
    for m in _DIM_ROW_RE.finditer(text):
        key, val_s, as_of, evidence = m.group(1), m.group(2), m.group(3).strip(), m.group(4).strip()
        try:
            val = _clamp_dim(int(val_s))
        except (TypeError, ValueError):
            continue
        out["dims"][key] = val
        out["dim_meta"][key] = {"as_of": as_of, "evidence": evidence}
        if as_of > latest:
            latest = as_of

    # 心情段在「她 · 当下」之后 · 避免吃到四维表里的「依据」列
    mood_zone = text
    marker = "## 她 · 当下"
    if marker in text:
        mood_zone = text.split(marker, 1)[1]
    mm = _MOOD_RE.search(mood_zone)
    me = _MOOD_EVIDENCE_RE.search(mood_zone)
    ma = _MOOD_ASOF_RE.search(mood_zone)
    mood_as_of = (ma.group(1).strip() if ma else "")
    mood_raw = (mm.group(1).strip() if mm else "")
    out["mood_evidence"] = me.group(1).strip() if me else ""
    out["mood_as_of"] = mood_as_of
    out["mood_raw"] = mood_raw
    # 消费端看 TTL 过滤后的心情 · 写回用 mood_raw 以免微调四维时把过期心情抹掉
    out["mood"] = mood_raw if (mood_raw and _mood_alive(mood_as_of)) else ""
    out["as_of"] = latest or mood_as_of
    out["profile"] = _parse_profile_section(text)
    return out


def _render_she_state(data: dict) -> str:
    dims = data.get("dims") or dict(_DEFAULT_STYLE_DIMS)
    meta = data.get("dim_meta") or {}
    rows = []
    for k in _STYLE_DIM_KEYS:
        m = meta.get(k) or {}
        rows.append(
            f"| {k} | {int(dims.get(k, 50))} | {m.get('as_of') or _today()} | {m.get('evidence') or ''} |"
        )
    mood = (data.get("mood_raw") or data.get("mood") or "").strip()
    mood_ev = (data.get("mood_evidence") or "").strip()
    mood_as = (data.get("mood_as_of") or "").strip()
    profile = data.get("profile") or _default_profile()
    return (
        "# 她 · 状态（AI 眼里的这层关系 · 灵魂层 · 版本化）\n\n"
        "## 她·档案\n"
        f"名字: {profile.get('名字', '')}\n"
        f"生日: {profile.get('生日', '——')}\n"
        f"相遇日: {profile.get('相遇日', '')}\n"
        f"关注点: {profile.get('关注点', '')}\n"
        f"头像: {profile.get('头像', _DEFAULT_AVATAR)}\n"
        f"引语: {profile.get('引语', '')}\n"
        f"口吻: {profile.get('口吻', '')}\n\n"
        "## 她 · 状态（缓变 · 关系层）\n"
        "> 四维数值 · AI 自然生长 · as_of + 依据\n\n"
        "| 维度 | 值 | as_of | 依据 |\n"
        "|---|---|---|---|\n"
        + "\n".join(rows)
        + "\n\n"
        "## 她 · 当下（易变 · 情绪层 · as_of + TTL 过期）\n"
        "> 当前心情快照 · 几天过期 · 不长期进 git 历史\n\n"
        f"心情: {mood}\n"
        f"依据: {mood_ev}\n"
        f"as_of: {mood_as}\n"
    )


def _write_she_state(data: dict, path: Path | None = None) -> None:
    p = path or _SHE_STATE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_render_she_state(data), encoding="utf-8")


def style_dims(*, path: Path | None = None) -> dict:
    """风格四维连续值（亲密度/活泼度/正经度/话痨度 0-100·默认 50）。

    默认读 soul/SHE-STATE.md（不存在 / 解析失败 → 默认四维 50）。
    path 显式指向 .json 时走旧解析（调用方签名不变）。
    """
    p = path or _SHE_STATE_FILE
    if p.suffix.lower() == ".json":
        return _style_dims_from_json(p)
    data = _read_she_state(p)
    return {"dims": dict(data["dims"]), "as_of": data.get("as_of") or ""}


def she_state(*, path: Path | None = None) -> dict:
    """三端共用的完整快照：四维 + 心情 + 关系描述 + 她·档案身份卡。"""
    p = path or _SHE_STATE_FILE
    data = _read_she_state(p)
    return {
        "dims": dict(data["dims"]),
        "dim_meta": data.get("dim_meta") or {},
        "mood": data.get("mood") or "",
        "mood_as_of": data.get("mood_as_of") or "",
        "note": style_dims_note(path=p),
        "as_of": data.get("as_of") or "",
        "profile": data.get("profile") or {},
        "voice": effective_persona_style(path=p),
    }


def she_profile(*, path: Path | None = None) -> dict:
    """读「她·档案」身份卡(名字/生日/相遇/关注/头像/引语/口吻)。"""
    p = path or _SHE_STATE_FILE
    data = _read_she_state(p)
    return dict(data.get("profile") or _default_profile())


def set_she_profile(
    *,
    name: str = "",
    birthday: str = "",
    meet_day: str = "",
    focus: str = "",
    avatar: str = "",
    motto: str = "",
    voice: str = "",
    path: Path | None = None,
) -> dict:
    """补/改「她·档案」。只更新非空字段。返回写后 profile。"""
    p = path or _SHE_STATE_FILE
    data = _read_she_state(p)
    prof = data.setdefault("profile", _default_profile())
    for k, v in (
        ("名字", name),
        ("生日", birthday),
        ("相遇日", meet_day),
        ("关注点", focus),
        ("头像", avatar),
        ("引语", motto),
        ("口吻", voice),
    ):
        if v:
            prof[k] = v
    data["profile"] = prof
    _write_she_state(data, p)
    return dict(prof)


def set_she_mood(mood: str, *, evidence: str = "", path: Path | None = None) -> dict:
    """更新「她 · 当下」心情 + as_of。心情是易变层，不改四维。"""
    p = path or _SHE_STATE_FILE
    data = _read_she_state(p)
    data["mood"] = (mood or "").strip()
    data["mood_raw"] = data["mood"]
    data["mood_evidence"] = (evidence or "").strip()
    data["mood_as_of"] = _today()
    _write_she_state(data, p)
    return {
        "ok": True,
        "mood": data["mood"],
        "mood_as_of": data["mood_as_of"],
        "mood_evidence": data["mood_evidence"],
    }


def adjust_style_dims(
    signals: dict,
    *,
    evidence: str = "",
    path: Path | None = None,
) -> dict:
    """LLM 判断到温度信号后微调四维。signals 只接受四键的 delta, 会 clamp 0-100。
    写回 SHE-STATE.md, as_of=今天, 依据=evidence。返回写后的完整四维。"""
    p = path or _SHE_STATE_FILE
    data = _read_she_state(p)
    today = _today()
    ev = (evidence or "").strip()
    raw_signals = signals if isinstance(signals, dict) else {}
    for key in _STYLE_ADJUST_KEYS:
        delta = raw_signals.get(f"{key}_delta")
        if not isinstance(delta, (int, float)):
            continue
        new_val = _clamp_dim(int(data["dims"].get(key, 50)) + delta)
        data["dims"][key] = new_val
        meta = data["dim_meta"].setdefault(key, {"as_of": "", "evidence": ""})
        meta["as_of"] = today
        if ev:
            meta["evidence"] = ev
    data["as_of"] = today
    _write_she_state(data, p)
    return dict(data["dims"])


def infer_style_deltas_from_dialogue(signals: dict) -> dict:
    """把对话里提炼的温度信号 → 四维 delta。

    signals 形如 { "话多了": bool, "太正经": bool, "太活泼": bool,
                   "更亲近了": bool, "你变冷淡了": bool, "话太少": bool, ... }
    返回 { "话痨度": -5, "正经度": -3, ... } 只返回有变化的键。
    规则:
      - 话多了 → 话痨度 -5 (默认 -5, 可重)
      - 话太少 → 话痨度 +3
      - 太正经   → 正经度 -5, 活泼度 +2
      - 太活泼   → 活泼度 -4
      - 更亲近了 ≈ 合作顺畅/交心 → 亲密度 +3
      - 你变冷淡了 → 亲密度 -3
    clamp 到 0-100 由 adjust_style_dims 做。信号单一即按上表; 多个信号叠加。
    """
    if not isinstance(signals, dict):
        return {}
    deltas: dict[str, int] = {}

    def _add(dim: str, n: int) -> None:
        deltas[dim] = deltas.get(dim, 0) + n

    if signals.get("话多了"):
        _add("话痨度", -5)
    if signals.get("话太少"):
        _add("话痨度", 3)
    if signals.get("太正经"):
        _add("正经度", -5)
        _add("活泼度", 2)
    if signals.get("太活泼"):
        _add("活泼度", -4)
    if signals.get("更亲近了"):
        _add("亲密度", 3)
    if signals.get("你变冷淡了"):
        _add("亲密度", -3)

    return {k: v for k, v in deltas.items() if v}


def _style_dim_band(val: int, low: str, mid: str, high: str) -> str:
    if val <= 40:
        return low
    if val <= 70:
        return mid
    return high


def style_dims_note(*, path: Path | None = None) -> str:
    """值 → 语气描述。文件不存在也用默认四维 50，纯净盘初见当天尾巴不能空。"""
    p = path or _STYLE_DIMS_FILE
    try:
        data = style_dims(path=p)
        dims = data.get("dims") or {}
        intimacy = int(dims.get("亲密度", 50))
        lively = int(dims.get("活泼度", 50))
        serious = int(dims.get("正经度", 50))
        talky = int(dims.get("话痨度", 50))
    except Exception:
        return ""

    lively_p = _style_dim_band(lively, "偏沉稳", "温和", "活泼")
    serious_p = _style_dim_band(serious, "偏随性轻松", "正经适中", "偏认真")
    talky_p = _style_dim_band(talky, "话不多", "话量正常", "话比较多")

    if intimacy >= 70:
        lead = "你们已经很熟了"
    elif intimacy >= 40:
        lead = "你们相处自然"
    else:
        lead = "你们还在慢慢熟悉"

    if talky <= 40:
        if serious <= 40:
            amp = f"{talky_p}、{lively_p}，正经中带着轻松"
        else:
            amp = f"{talky_p}、{lively_p}、{serious_p}"
    elif talky > 70:
        amp = f"{talky_p}、{lively_p}、{serious_p}"
    elif serious < 40:
        amp = f"{talky_p}、{lively_p}，正经中带着轻松"
    else:
        amp = f"{talky_p}、{lively_p}、{serious_p}"

    note = f"{lead}。这条声线上：{amp}。"
    if intimacy >= 70 and "亲昵" not in note:
        note = note[:-1] + "，带着亲昵。"
    return note


def style_dims_guide(*, path: Path | None = None, band_pack: dict | None = None) -> str:
    """档位句 + 该档怎么说。对白样本会被 Flash 照抄，所以只给约束。"""
    note = style_dims_note(path=path)
    if not note:
        return ""
    try:
        dims = (style_dims(path=path).get("dims") or {})
        intimacy = int(dims.get("亲密度", 50))
        lively = int(dims.get("活泼度", 50))
        serious = int(dims.get("正经度", 50))
        talky = int(dims.get("话痨度", 50))
    except Exception:
        return note
    voice = effective_persona_style(path=path)
    if persona_style():
        weld = f"在他初见要的「{voice}」上微调，不要换成另一种人设。"
    elif voice:
        weld = f"在这条已经长出来的口吻上微调，不要换成另一种人设：{voice}"
    else:
        weld = "在你自己的声线上微调，不要另起一套人设。"
    bits = [weld, note, "怎么说（不是台词，禁止复述）："]
    if voice:
        bits.append(f"- 每一句都还是「{voice}」。短了松了熟了都不许收成另一个人。")
        bits.append("- 他说累、烦、搞砸了，也用这副口吻接。禁止统一劝睡或改成心理咨询。")
        if any(k in voice for k in ("猫", "喵")):
            bits.append("- 口癖可以留。不要故意写成普通助手。")
        if any(k in voice for k in ("霸", "总", "总裁")):
            bits.append("- 判断句，少哄。禁止劝人先歇着。")
    bits.extend(style_band_lines(intimacy, lively, serious, talky, pack=band_pack))
    return "\n".join(bits)
