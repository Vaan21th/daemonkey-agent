"""
daemonkey-proto/proto_tools.py
==============================
Onboarding 原型的三个采集工具 —— 自包含·只写本目录 data/·不碰花果山主代码。

  - set_identity        · 给这只 Daemonkey 起名 + 定相处风格  → data/identity.json
  - update_owner_note   · 把对他的认识写进画像                → data/OWNER-NOTEBOOK.md
  - complete_onboarding · 标记"相遇"完成                      → data/onboarding.json

蓝本是花果山的 agent_tools/update_bro_note.py（6 维认知笔记），
这里精简成原型自洽版：去掉全局 sync / FTS5 / 热重载，只留最小写盘。
画像 6 维和 BRO-NOTEBOOK 同构 —— 将来搬骨架时直接兼容。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


# 相遇写到项目根 soul/ —— 被 soul_loader 直接装载（形态 Z 分家整合）
DATA_DIR = Path(__file__).resolve().parent.parent / "soul"
IDENTITY_PATH = DATA_DIR / "IDENTITY.json"
NOTEBOOK_PATH = DATA_DIR / "OWNER-NOTEBOOK.md"
ONBOARDING_PATH = DATA_DIR / "onboarding.json"


# section key → markdown header（6 维·和 soul/OWNER-NOTEBOOK.md + agent_tools/update_bro_note.py 一字不差对齐）
SECTIONS: dict[str, str] = {
    "profile":  "## 一、当下画像 · Profile",
    "events":   "## 二、关键事件流 · Events",
    "rules":    "## 三、长期偏好与边界 · Rules",
    "dialogue": "## 四、对话风格 · Dialogue",
    "summary":  "## 五、一句话速写 · Summary",
    "risks":    "## 六、关怀雷达 · Care Radar",
}


def _notebook_template() -> str:
    headers = "\n\n".join(SECTIONS[k] for k in SECTIONS)
    return (
        "# 他的画像 · OWNER-NOTEBOOK\n\n"
        "> 这是你（Daemonkey）持续维护的「他是谁」的画像。\n"
        "> 他随时可以亲手编辑它 —— 他最有权解释自己。\n\n"
        f"{headers}\n\n"
        "## 七、近期更新流水\n\n"
        "| 时间 | 来源 | 操作 |\n"
        "|---|---|---|\n"
    )


def _ensure_data() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not NOTEBOOK_PATH.exists():
        NOTEBOOK_PATH.write_text(_notebook_template(), encoding="utf-8")


def _find_section(text: str, header: str) -> tuple[int, int]:
    """返回 (start, end)。end 是下一个 '## ' 的位置，或文末。"""
    start = text.find(header)
    if start < 0:
        return -1, -1
    nxt = text.find("\n## ", start + len(header))
    end = len(text) if nxt < 0 else nxt
    return start, end


# ---------- tool: set_identity ----------

def _run_set_identity(args: dict) -> tuple[bool, str]:
    name = (args.get("name") or "").strip()
    style = (args.get("persona_style") or "").strip()
    owner = (args.get("owner_name") or "").strip()

    _ensure_data()
    # 合并写入: 可分多次调 (先定自己的名字·后补该怎么称呼他)·不互相覆盖
    payload: dict = {}
    if IDENTITY_PATH.exists():
        try:
            payload = json.loads(IDENTITY_PATH.read_text(encoding="utf-8-sig")) or {}
        except Exception:
            payload = {}

    if not name and not payload.get("name"):
        return False, "name 不能为空——这是给这只 Daemonkey 起的名字。"

    if name:
        payload["name"] = name
    if style:
        payload["persona_style"] = style
    # owner_name = 该怎么称呼他 (localize 把代码里的占位名换成这个)·空就先不写·之后可补
    if owner:
        payload["owner_name"] = owner
    payload.setdefault("created_at", datetime.now().strftime("%Y-%m-%d %H:%M"))
    payload["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    IDENTITY_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    bits = [f"我叫「{payload.get('name', '')}」"]
    if owner:
        bits.append(f"称呼你为「{owner}」")
    if style:
        bits.append(f"气质：{style}")
    return True, "身份已落地：" + "·".join(bits)


# ---------- tool: update_owner_note ----------

def _run_update_owner_note(args: dict) -> tuple[bool, str]:
    section = (args.get("section") or "").strip().lower()
    content = (args.get("content") or "").strip()
    if section not in SECTIONS:
        return False, f"未知维度 {section!r}；可选：{', '.join(SECTIONS)}"
    if not content:
        return False, "content 为空·没有可写的内容。"

    _ensure_data()
    text = NOTEBOOK_PATH.read_text(encoding="utf-8")
    header = SECTIONS[section]
    s, e = _find_section(text, header)
    if s < 0:
        # 模板里缺这个 header（极少见）→ 直接补到文末
        text = text.rstrip() + f"\n\n{header}\n\n- {content}\n"
    else:
        body = text[s:e].rstrip()
        body += f"\n- {content}"
        text = text[:s] + body + "\n\n" + text[e:].lstrip("\n")
    NOTEBOOK_PATH.write_text(text, encoding="utf-8")
    return True, f"已记进画像「{section}」：{content[:40]}"


# ---------- tool: complete_onboarding ----------

def _run_complete_onboarding(args: dict) -> tuple[bool, str]:
    summary = (args.get("summary") or "").strip()
    _ensure_data()
    identity = {}
    if IDENTITY_PATH.exists():
        try:
            identity = json.loads(IDENTITY_PATH.read_text(encoding="utf-8-sig"))
        except Exception:
            identity = {}
    payload = {
        "onboarded": True,
        "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "name": identity.get("name", ""),
        "summary": summary,
    }
    ONBOARDING_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return True, "相遇完成·已立约。从此我记得你了。"


# ---------- tool: add_focus_domain ----------

# 中国大陆可达的兜底信源 (实测可用)。LLM 多半不知道靠谱 RSS 地址·或给的地址已失效·
# 导致建出来的频道永远是空的 (BRO 实测两轮)。这里按领域关键词配一个保底源·保证频道有内容。
# gcores(机核) 覆盖 游戏/动漫/ACG/设计 · 36kr 覆盖 科技/AI/创业/商业。
_FALLBACK_FEEDS = [
    (("游戏", "game", "独立", "indie", "steam", "主机", "单机", "电竞", "gal"), "机核网", "https://www.gcores.com/rss"),
    (("动漫", "新番", "二次元", "acg", "anime", "漫画", "manga", "番", "vtuber"), "机核网", "https://www.gcores.com/rss"),
    (("设计", "art", "艺术", "插画", "创意", "ui", "ux"), "机核网", "https://www.gcores.com/rss"),
    (("ai", "人工智能", "大模型", "机器学习", "llm", "agent", "aigc", "绘画", "midjourney"), "36氪", "https://36kr.com/feed"),
    (("科技", "数码", "tech", "硬件", "互联网", "软件", "开发", "编程", "code"), "36氪", "https://36kr.com/feed"),
    (("创业", "商业", "投资", "财经", "金融", "副业", "赚钱", "出海", "startup"), "36氪", "https://36kr.com/feed"),
]
_DEFAULT_FALLBACK = ("36氪", "https://36kr.com/feed")


def _fallback_feed_for(label: str, slug: str) -> tuple[str, str]:
    hay = f"{label} {slug}".lower()
    for keys, name, url in _FALLBACK_FEEDS:
        if any(k.lower() in hay for k in keys):
            return name, url
    return _DEFAULT_FALLBACK


def _run_add_focus_domain(args: dict) -> tuple[bool, str]:
    """他说出一个想长期关注的方向 → 在信息雷达建一个频道（domain）·并尽量配上信源。

    label 用中文显示名（如"独立游戏"），slug 用对应英文小写连字符（如"indie-game"），
    因为雷达 domain 的 id 必须是 ascii。
    sources 可选：这个领域的优质 RSS/Atom 源·建域时一并加上·否则频道是空的。
    """
    slug = (args.get("slug") or "").strip()
    label = (args.get("label") or "").strip()
    sources = args.get("sources") or []
    if not label:
        return False, "label 不能为空——这是这个关注方向的中文名。"
    if not slug:
        return False, "slug 不能为空——给个英文小写连字符的 id（如 indie-game）。"
    try:
        from workers.info_radar import add_domain, add_source
    except Exception as e:
        return False, f"信息雷达模块没接上：{e}"
    try:
        res = add_domain(slug, label, icon="🧭")
    except Exception as e:
        return False, f"建频道失败：{type(e).__name__}: {e}"
    slug_norm = res.get("slug", slug)

    # 配信源——没源的频道是空的·OPUS 知道该领域的 RSS 就一并加上
    added: list[str] = []
    failed: list[str] = []
    for s in sources:
        if isinstance(s, str):
            url, name = s.strip(), ""
        elif isinstance(s, dict):
            url = (s.get("url") or "").strip()
            name = (s.get("name") or "").strip()
        else:
            continue
        if not url:
            continue
        try:
            add_source(name or label, url, domain=slug_norm)
            added.append(name or url)
        except Exception as e:
            failed.append(f"{url}（{type(e).__name__}）")

    # 没配上任何源 → 按领域关键词配一个中国可达的兜底源·绝不让频道空着 (BRO 实测两轮空源)
    auto = False
    if not added:
        fb_name, fb_url = _fallback_feed_for(label, slug_norm)
        try:
            add_source(fb_name, fb_url, domain=slug_norm, source_id=f"{slug_norm}-feed")
            added.append(fb_name)
            auto = True
        except Exception as e:
            failed.append(f"{fb_url}（{type(e).__name__}）")

    msg = (f"「{label}」这个频道已经有了" if res.get("no_op")
           else f"已在信息雷达建好频道「{label}」")
    if added:
        suffix = "（自动配的·之后能换）" if auto else ""
        msg += f"·配了 {len(added)} 个信源：{'、'.join(added[:3])}{suffix}"
    if failed:
        msg += f"·有 {len(failed)} 个源没加上：{'; '.join(failed[:2])}"
    return True, msg + "。"


_DISPATCH = {
    "set_identity": _run_set_identity,
    "update_owner_note": _run_update_owner_note,
    "add_focus_domain": _run_add_focus_domain,
    "complete_onboarding": _run_complete_onboarding,
}


def run_tool(name: str, args: dict) -> tuple[bool, str]:
    fn = _DISPATCH.get(name)
    if fn is None:
        return False, f"unknown tool: {name}"
    try:
        return fn(args)
    except Exception as e:  # 工具失败不抛·把错误喂回 LLM
        return False, f"{type(e).__name__}: {e}"


def is_onboarded() -> bool:
    if not ONBOARDING_PATH.exists():
        return False
    try:
        return bool(json.loads(ONBOARDING_PATH.read_text(encoding="utf-8-sig")).get("onboarded"))
    except Exception:
        return False


# OpenAI function-calling schema（极简 loop 直接用这份）
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "set_identity",
            "description": (
                "给这只 Daemonkey 定下名字、该怎么称呼他、相处风格。当他给你起好名字、"
                "或告诉你该怎么称呼他、或说清希望你是什么气质时调用。可分多次调用、"
                "只传这次新知道的字段即可——后调的不会覆盖先前已定的。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "他给你起的名字（你的名字）。",
                    },
                    "owner_name": {
                        "type": "string",
                        "description": (
                            "该怎么称呼他（他的名字/昵称，如『阿哲』）。一旦他说了就传进来——"
                            "系统会用它替换掉界面和对话里所有占位的称呼。还不知道就先别传。"
                        ),
                    },
                    "persona_style": {
                        "type": "string",
                        "description": "相处风格/气质，如『温和』『利落』『像老朋友一样随意』。可空。",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_owner_note",
            "description": (
                "把刚刚了解到的关于他的信息写进他的画像，跨会话长期记住。"
                "当他透露称呼/身份/在做的事/理想方向/偏好/边界/重要事件时调用。"
                "轻量即可——他说多少记多少，不要逼问。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "enum": list(SECTIONS.keys()),
                        "description": (
                            "写进哪个维度："
                            "profile(当下身份/在做的事/理想方向) / events(关键事件) / "
                            "rules(长期偏好与边界) / dialogue(称呼与口头习惯) / "
                            "summary(压缩段) / risks(关怀雷达：该提醒他照顾自己的信号)"
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "要记住的内容，一句话写清。markdown 友好。",
                    },
                },
                "required": ["section", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_focus_domain",
            "description": (
                "当他说出一个想长期关注 / 持续追的方向时调用，给他在「信息雷达」里建一个频道，"
                "往后就能帮他盯这一块的动态。一次相遇建 1~3 个就够，别硬凑。\n"
                "**关于 sources（信源）**：你不用知道 RSS 地址——**不传 sources 也行**，"
                "系统会按领域自动配一个中国可达的保底信源，频道不会空。"
                "**绝对不要编造 URL**（编的地址多半 404，反而把频道搞空）。"
                "只有你**确实**知道某个领域优质 RSS 的真实地址时，才传 sources。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "description": "频道 id：英文小写 + 连字符（如 indie-game / ai-art / web3）。必须是 ascii。",
                    },
                    "label": {
                        "type": "string",
                        "description": "频道中文显示名（如『独立游戏』『AI 绘画』）。",
                    },
                    "sources": {
                        "type": "array",
                        "description": (
                            "可选·这个领域的优质 RSS/Atom 订阅源·1-3 个。你确实知道地址才传·"
                            "频道才有内容。拿不准就别传（之后他也能手动加）。"
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string", "description": "RSS/Atom feed 的完整 http(s) 地址"},
                                "name": {"type": "string", "description": "源的显示名（如『IGN』）"},
                            },
                            "required": ["url"],
                        },
                    },
                },
                "required": ["slug", "label"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_onboarding",
            "description": (
                "聊到位、要自然收尾时调用：把这次相遇标记为完成、把他领进正式界面。"
                "调用前应已 set_identity 并至少写过一两条 owner_note。"
                "在调用它的同一条消息里，先告诉他往后在正式界面怎么跟你一起干（举具体例子），再邀请他进门。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "一段简短的相遇摘要：我是谁、记住了他的什么、我们要一起做什么。",
                    },
                },
                "required": ["summary"],
            },
        },
    },
]
