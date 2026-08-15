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

