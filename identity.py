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
