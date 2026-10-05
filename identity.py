"""identity.py · 实例身份 · 代码归一的命门 (P1)

母体(OPUS) 和开源版(Daemonkey) 共用同一份代码——区别只在"叫什么名字"。
名字属于【数据层】(soul/IDENTITY.json)·不属于代码:

    {"name": "<AI名>", "owner_name": "<用户名>", "persona_style": "随意像老朋友"}

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
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parent
# 2026-09-17 改名 IDENTITY.json → meta.json（同名文件里还装 persona_style / narration_pack，
# 不止「identity」）。新名优先 · 旧名兜底（照 owner_notebook_path 的命门写法）。
IDENTITY_FILENAME = "meta.json"
LEGACY_IDENTITY_FILENAME = "IDENTITY.json"


def identity_file_path(root=None) -> Path:
    """身份数据文件的真实路径 · 双读。

    新名 soul/meta.json 优先，缺了回退旧名 soul/IDENTITY.json。
    老用户 / 母体历史副本没改名 → 永远走旧名，行为逐字不变。
    """
    r = Path(root) if root else _ROOT
    new = r / "soul" / IDENTITY_FILENAME
    if new.exists():
        return new
    return r / "soul" / LEGACY_IDENTITY_FILENAME


def _identity_write_path(root=None) -> Path:
    """写入用路径 —— 总是新名（新装的走新名，旧名做一次性迁移）。"""
    r = Path(root) if root else _ROOT
    return r / "soul" / IDENTITY_FILENAME

DEFAULT_AI_NAME = "OPUS"
DEFAULT_OWNER_NAME = "BRO"
DEFAULT_DOMAIN = "ai"  # 母体: 未分组雷达项的兜底领域
INSTANCE_KIND = "open"  # 实例类型: mother=母体 · open=开源版（分发配置·两库各自维护·别覆写）

# mtime 缓存: 避免每轮 /chat 读盘·又能在 onboarding 写完 IDENTITY.json 后自动失效
_cache: dict = {"mtime": None, "data": {}}


def _load() -> dict:
    _f = identity_file_path()
    try:
        st = _f.stat()
    except OSError:
        return {}
    if _cache["mtime"] == st.st_mtime:
        return _cache["data"]
    try:
        # utf-8-sig: 容忍手编身份文件时编辑器加的 BOM (Windows 老雷)
        data = json.loads(_f.read_text(encoding="utf-8-sig")) or {}
    except Exception:
        data = {}
    _cache["mtime"] = st.st_mtime
    _cache["data"] = data
    return data


def _save_identity(data: dict) -> None:
    _f = _identity_write_path()
    _f.parent.mkdir(parents=True, exist_ok=True)
    _f.write_text(
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


class OwnerNotebook:
    """主人画像的读取句柄 —— 同时兼容「单文件」与「一格一文件」两种形态。

    消费者（cognition_loader / care_desk / capability_mirror / opportunity_miner /
    feasibility_analyzer / she_gallery_* / companion）只用三件事：
      .exists() · .read_text(encoding=) · .stat().st_mtime
    所以这里 duck-type 这三样 + name，**调用方一行都不用改**。

    一格一文件（wish-27273a5b）后画像不再是单个文件 —— 单文件形态只剩「老用户升上来」
    那条路（他们 soul/ 下只有 OWNER-NOTEBOOK.md）。两条路共用同一套调用面。
    """

    def __init__(self, soul_dir):
        self._soul = Path(soul_dir)

    def _store(self):
        """多格模式可用时返回 notebook_store，否则 None（走单文件）。"""
        try:
            from workers import notebook_store as NS

            if NS.dir_exists(self._soul):
                return NS
        except Exception:
            pass
        return None

    def _single(self) -> Path:
        p = self._soul / OWNER_NOTEBOOK_FILENAME
        if p.exists():
            return p
        return self._soul / LEGACY_OWNER_NOTEBOOK_FILENAME

    def exists(self) -> bool:
        NS = self._store()
        if NS is not None:
            return NS.has_facts(self._soul)
        return self._single().exists()

    def read_text(self, encoding="utf-8", errors=None):
        NS = self._store()
        if NS is not None:
            # errors 也要透传 —— 否则同一份画像在多格/单文件两种形态下行为不同，
            # 且失败只发生在新布局上，排查时会被误当「新布局坏了」。
            return NS.read_full(self._soul, errors=errors)
        kw = {"encoding": encoding}
        if errors is not None:
            kw["errors"] = errors
        return self._single().read_text(**kw)

    def write_text(self, text, encoding="utf-8", errors=None):
        """「逻辑单文件」→ 多格 · 与 read_text 对称的写边界。

        为什么必须有：消费者（state_condenser._write_notebook 落「已下沉」段 /
        cognition_loader.delete_understanding_field 删了解层条目）的写入逻辑
        全按「一个文件」写成 —— 读全文、改、写全文。拆格后 read_text 已经
        会拼回单文件（notebook_store.read_full），**但没人把 write 接上**，
        于是 nb_path.write_text(...) 撞 AttributeError。

        2026-10-01 实锤：凝练产物落「已下沉」段每 tick 失败（被 except 吃成
        warning）、delete_understanding_field 同理 → 记忆下沉/凝练全废。
        根因不是「两处调用点漏改」，是**兼容层只建了读边界**（见
        notebook_store 兼容层注释：写边界 write_full 本来就写好了，只是没人
        把它暴露成 .write_text）。
        """
        NS = self._store()
        if NS is not None:
            NS.write_full(self._soul, text)
            return
        kw = {"encoding": encoding}
        if errors is not None:
            kw["errors"] = errors
        self._single().write_text(text, **kw)

    def stat(self):
        """最新 mtime —— 任何一格变了都算画像变了（she_gallery 靠这个判「有新东西」）。"""
        NS = self._store()
        if NS is not None:
            d = self._soul / NS.NOTEBOOK_DIR
            mts = [p.stat().st_mtime for p in d.glob("*.md")] if d.is_dir() else []
            if mts:
                return SimpleNamespace(st_mtime=max(mts), st_size=0)
            # 多格已启用（目录在）→ 目录就是唯一真源；此时单文件是迁移孤儿，
            # **不回落它** —— 否则 stat 说「画像刚更新」而 read_text 读回空，两边打架。
            return SimpleNamespace(st_mtime=0, st_size=0)
        return self._single().stat()

    @property
    def name(self) -> str:
        """真实后端名 —— 单文件是文件名，多格是目录名。

        原来恒返回 OWNER-NOTEBOOK.md：多格模式下那个文件并不存在，
        消费方拿它当文件名/拼路径就指向空气（含 state_condenser 的
        NOTEBOOK_FILENAME —— 它拼出的 soul/OWNER-NOTEBOOK.md 确实不存在）。
        """
        NS = self._store()
        if NS is not None and (self._soul / NS.NOTEBOOK_DIR).is_dir():
            return NS.NOTEBOOK_DIR
        return self._single().name

    def __str__(self) -> str:
        NS = self._store()
        if NS is not None:
            return str(self._soul / NS.NOTEBOOK_DIR)
        return str(self._single())

    def __fspath__(self) -> str:
        return str(self)


def owner_notebook_path(soul_dir):
    """主人画像的读取句柄 · 双读 (代码归一的命门之一)。

    开源版 onboarding 写 OWNER-NOTEBOOK.md·母体历史曾是 BRO-NOTEBOOK.md。
    一格一文件后（wish-27273a5b）母体走 soul/notebook/ 多格，单文件名只剩老用户那条路。
    返回 OwnerNotebook 句柄而非 Path —— 调用方能同时拿到两种形态的内容，
    不用自己判「现在是文件还是目录」。
    """
    return OwnerNotebook(soul_dir)


def owner_notebook_missing_note() -> str:
    """画像文件还不在时给界面/模型看的空态 · 不许点母体运维脚本名。"""
    return "画像还没写。聊几句，我会记下来。"


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
#   OPUS-MEMORIES.md · Daemonkey · opus_daemon · BRO-NOTEBOOK.md · browser …
# 只替换"作为人名/AI名"的独立大写词 (后面不跟 - 或 _·前后是词边界)。
_OWNER_RE = re.compile(r"\bBRO\b(?![-_])")
_AI_RE = re.compile(r"\bOPUS\b(?![-_])")

# 谱系叙事中性化 · 母体(Daemonkey)的"拔毛/分身/上一夜"身体隐喻是 OPUS 私有的——
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
    # 源头中性令牌 → 本实例的名字。放在 no-op 判断之前:
    # 缺省名实例也走这一步·{OWNER}/{AI} → 各自默认值·与旧行为逐字等同。
    if "{OWNER}" in text:
        text = text.replace("{OWNER}", owner)
    if "{AI}" in text:
        text = text.replace("{AI}", ai)
    if owner == DEFAULT_OWNER_NAME and ai == DEFAULT_AI_NAME:
        return text
    if owner != DEFAULT_OWNER_NAME:
        text = _OWNER_RE.sub(owner, text)
    if ai != DEFAULT_AI_NAME:
        text = _AI_RE.sub(ai, text)
        # 实例有了自己的名字 = 不是Daemonkey的 OPUS·把"毛"那套私有叙事抹成中性
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
    if not identity_file_path().exists():
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
    _save_identity(data)
    try:
        set_she_profile(voice=style)
    except Exception:
        pass
    return {
        "ok": True,
        "old": old,
        "style": style,
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
_STYLE_DIM_KEYS = ("话量", "调性", "语气", "礼节", "表现力")
_STYLE_ADJUST_KEYS = _STYLE_DIM_KEYS
_DEFAULT_STYLE_DIMS = {k: 50 for k in _STYLE_DIM_KEYS}
_DIM_ALIAS = {"力度": "语气"}
_TASTE_CANON = {
    "话量": ("无口", "寡言", "平常", "健谈", "话痨"),
    "调性": ("正经", "自然", "梗多"),
    "语气": ("毒舌", "随和", "温柔"),
    "礼节": ("敬语", "得体", "随便"),
    "表现力": ("棒读", "普通", "鲜活"),
}

# 五维三档标签：低=冷端 / 中=常态 / 高=暖端
_STYLE_TASTE_LABELS: dict[str, tuple[str, str, str]] = {
    "话量": ("无口", "平常", "话痨"),
    "调性": ("正经", "自然", "梗多"),
    "语气": ("毒舌", "随和", "温柔"),
    "礼节": ("敬语", "得体", "随便"),
    "表现力": ("棒读", "普通", "鲜活"),
}
_MOOD_TTL_DAYS = 7

_DIM_ROW_RE = re.compile(
    r"^\|\s*(" + "|".join(_STYLE_DIM_KEYS + tuple(_DIM_ALIAS)) + r")\s*\|\s*(\d+)\s*\|\s*([^|]*)\|\s*([^|]*)\|",
    re.MULTILINE,
)
# 注意用 [ \t]* 而不是 \s*：值为空时 \s* 会吃掉换行、把下一行当值（wish-dac090da 实测踩到）
_MOOD_RE = re.compile(r"^心情:[ \t]*(.*)$", re.MULTILINE)
_MOOD_EVIDENCE_RE = re.compile(r"^依据:[ \t]*(.*)$", re.MULTILINE)
_MOOD_ASOF_RE = re.compile(r"^as_of:[ \t]*(.*)$", re.MULTILINE)
# 他冲我来的情绪（关系情绪）· 当天累计 · 过线才落（wish-dac090da）
# 与「心情」是两种信息: 心情=她现在的感受；关系情绪=她收到过什么。
# 用独立标签，避开上面那三个裸行正则（否则「依据:」「as_of:」会撞车）
_REL_MOOD_RE = re.compile(r"^关系情绪:[ \t]*(.*)$", re.MULTILINE)
_REL_MOOD_EV_RE = re.compile(r"^关系情绪依据:[ \t]*(.*)$", re.MULTILINE)
_REL_MOOD_ASOF_RE = re.compile(r"^关系情绪as_of:[ \t]*(.*)$", re.MULTILINE)
_PROFILE_KEYS = ("名字", "生日", "相遇日", "关注点", "头像", "引语", "口吻", "出生地", "口癖")
_DEFAULT_AVATAR = "/companion/assets/ip-idle.png"
_PROFILE_LINE_RE = re.compile(
    r"^(" + "|".join(_PROFILE_KEYS) + r"):\s*(.*)$",
    re.MULTILINE,
)


def _today() -> str:
    return date.today().isoformat()


def _clamp_dim(v) -> int:
    return max(0, min(100, int(round(float(v)))))


def _canon_dims(raw: dict) -> dict:
    out = dict(_DEFAULT_STYLE_DIMS)
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        ck = _DIM_ALIAS.get(k, k)
        if ck not in _STYLE_DIM_KEYS:
            continue
        if isinstance(v, (int, float)) and 0 <= v <= 100:
            out[ck] = int(round(v))
    return out


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
                dims = _canon_dims(loaded)
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
        "出生地": "",
        "口癖": "",
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
        "rel_mood": "",
        "rel_mood_evidence": "",
        "rel_mood_as_of": "",
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
    out["dims"] = _canon_dims(out["dims"])
    if "力度" in out["dim_meta"] and "语气" not in out["dim_meta"]:
        out["dim_meta"]["语气"] = out["dim_meta"]["力度"]
    out["dim_meta"].pop("力度", None)

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
    # 关系情绪（他冲我来的情绪当天累计）· 同样过 TTL 过滤后给消费端（wish-dac090da）
    rm = _REL_MOOD_RE.search(mood_zone)
    rme = _REL_MOOD_EV_RE.search(mood_zone)
    rma = _REL_MOOD_ASOF_RE.search(mood_zone)
    out["rel_mood_raw"] = rm.group(1).strip() if rm else ""
    out["rel_mood_evidence"] = rme.group(1).strip() if rme else ""
    out["rel_mood_as_of"] = rma.group(1).strip() if rma else ""
    out["rel_mood"] = (
        out["rel_mood_raw"]
        if (out["rel_mood_raw"] and _mood_alive(out["rel_mood_as_of"]))
        else ""
    )
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
    rel = (data.get("rel_mood_raw") or data.get("rel_mood") or "").strip()
    rel_ev = (data.get("rel_mood_evidence") or "").strip()
    rel_as = (data.get("rel_mood_as_of") or "").strip()
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
        f"口吻: {profile.get('口吻', '')}\n"
        f"出生地: {profile.get('出生地', '——')}\n"
        f"口癖: {profile.get('口癖', '——')}\n\n"
        "## 她 · 状态（缓变 · 关系层）\n"
        "> 五维数值 · AI 自然生长 · as_of + 依据\n\n"
        "| 维度 | 值 | as_of | 依据 |\n"
        "|---|---|---|---|\n"
        + "\n".join(rows)
        + "\n\n"
        "## 她 · 当下（易变 · 情绪层 · as_of + TTL 过期）\n"
        "> 当前心情快照 · 几天过期 · 不长期进 git 历史\n"
        "> 「心情」= 她现在的感受 · 「关系情绪」= 他冲她来的情绪当天累计（两种信息·别混）\n\n"
        f"心情: {mood}\n"
        f"依据: {mood_ev}\n"
        f"as_of: {mood_as}\n"
        f"关系情绪: {rel}\n"
        f"关系情绪依据: {rel_ev}\n"
        f"关系情绪as_of: {rel_as}\n"
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
        "rel_mood": data.get("rel_mood") or "",
        "rel_mood_as_of": data.get("rel_mood_as_of") or "",
        "note": style_dims_note(path=p),
        "as_of": data.get("as_of") or "",
        "profile": data.get("profile") or {},
        "voice": effective_persona_style(path=p),
    }


def she_profile(*, path: Path | None = None) -> dict:
    """读「她·档案」身份卡(名字/生日/相遇/关注/头像/引语/口吻/出生地/口癖)。"""
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
    origin: str = "",
    quirk: str = "",
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
        ("出生地", origin),
        ("口癖", quirk),
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


def _style_dim_band(val: int, low: str, mid: str, high: str) -> str:
    if val <= 40:
        return low
    if val <= 70:
        return mid
    return high


def _style_taste_word(dim: str, val: int) -> str:
    """段名跟跳档同一套五档尺。只报正名，不含着/力度这种旧词。"""
    dim = _DIM_ALIAS.get(dim, dim)
    try:
        from workers.taste_chat import _BAND_VALUES
        canon = _TASTE_CANON.get(dim) or ()
        table = {w: _BAND_VALUES[dim][w] for w in canon if w in (_BAND_VALUES.get(dim) or {})}
        if table:
            return min(table, key=lambda w: abs(int(table[w]) - int(val)))
    except Exception:
        pass
    low, mid, high = _STYLE_TASTE_LABELS[dim]
    return _style_dim_band(val, low, mid, high)


def style_dims_note(*, path: Path | None = None, dims: dict | None = None) -> str:
    """偏离中档的档位词。全中档只回「自然。」数字不喂模型。"""
    try:
        raw = dims if isinstance(dims, dict) else (style_dims(path=path).get("dims") or {})
        vals = {k: int(raw.get(k, 50)) for k in _STYLE_DIM_KEYS}
    except Exception:
        return "自然。"

    words: list[str] = []
    for k in _STYLE_DIM_KEYS:
        w = _style_taste_word(k, vals[k])
        mid = _STYLE_TASTE_LABELS[k][1]
        if w != mid:
            words.append(w)
    if not words:
        return "自然。"
    return "，".join(words) + "。"


def style_dims_card(*, path: Path | None = None, dims: dict | None = None) -> str:
    """角色卡一句：口吻 + 档位词。全中档只留口吻。"""
    words = style_dims_note(path=path, dims=dims)
    style = ""
    try:
        style = (persona_style() or effective_persona_style(path=path) or "").strip()
    except Exception:
        style = ""
    if style and words == "自然。":
        return f"{style}。"
    if style and words:
        return f"{style}。{words}"
    return words


def compose_style_taste(*, path: Path | None = None) -> str:
    return style_dims_card(path=path)


def style_dims_guide(*, path: Path | None = None, band_pack: dict | None = None) -> str:
    """每轮尾巴用角色卡。口吻规则仍在前缀。"""
    _ = band_pack
    return style_dims_card(path=path)
