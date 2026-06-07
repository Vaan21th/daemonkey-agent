"""
daemonkey-proto/proto_tools.py
==============================
Onboarding 原型的三个采集工具 —— 自包含·只写本目录 data/·不碰花果山主代码。

  - set_identity        · 给这只 Daemonkey 起名 + 定相处风格  → data/identity.json
  - update_owner_note   · 把对主人的认识写进画像              → data/OWNER-NOTEBOOK.md
  - complete_onboarding · 标记"相遇"完成                      → data/onboarding.json

蓝本是花果山的 agent_tools/update_bro_note.py（6 维认知笔记），
这里精简成原型自洽版：去掉全局 sync / FTS5 / 热重载，只留最小写盘。
画像 6 维和 BRO-NOTEBOOK 同构 —— 将来搬骨架时直接兼容。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent / "data"
IDENTITY_PATH = DATA_DIR / "identity.json"
NOTEBOOK_PATH = DATA_DIR / "OWNER-NOTEBOOK.md"
ONBOARDING_PATH = DATA_DIR / "onboarding.json"


# section key → markdown header（用户版 6 维·和花果山 BRO-NOTEBOOK 同构）
# 去符号化：把"BRO/风险弱点/预警雷达"换成中性温和的措辞
SECTIONS: dict[str, str] = {
    "profile":  "## 一、当下画像 · Profile",
    "events":   "## 二、关键事件流 · Events",
    "rules":    "## 三、长期偏好与边界 · Rules",
    "dialogue": "## 四、称呼与口头习惯 · Dialogue",
    "summary":  "## 五、压缩段 · Summary",
    "risks":    "## 六、关怀雷达 · Care Radar",
}


def _notebook_template() -> str:
    headers = "\n\n".join(SECTIONS[k] for k in SECTIONS)
    return (
        "# OWNER-NOTEBOOK · 我对你的认识\n\n"
        "> 这是你的 Daemonkey 持续维护的「你是谁」的画像。\n"
        "> 你随时可以亲手编辑它 —— 你最有权解释你自己。\n\n"
        f"{headers}\n"
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
    if not name:
        return False, "name 不能为空——这是给这只 Daemonkey 起的名字。"
    _ensure_data()
    payload = {
        "name": name,
        "persona_style": style,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    IDENTITY_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return True, f"身份已落地：我叫「{name}」" + (f"·气质：{style}" if style else "")


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
            identity = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
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


_DISPATCH = {
    "set_identity": _run_set_identity,
    "update_owner_note": _run_update_owner_note,
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
        return bool(json.loads(ONBOARDING_PATH.read_text(encoding="utf-8")).get("onboarded"))
    except Exception:
        return False


# OpenAI function-calling schema（极简 loop 直接用这份）
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "set_identity",
            "description": (
                "给这只 Daemonkey 定下名字和相处风格。当主人给你起好名字、"
                "并且大致说清希望你是什么气质的搭档时调用。一次相遇通常只调一次。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "主人给你起的名字（你的名字）。",
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
                "把刚刚了解到的关于主人的信息写进他的画像，跨会话长期记住。"
                "当主人透露称呼/身份/在做的事/偏好/边界/重要事件时调用。"
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
                            "profile(当下身份/在做的事) / events(关键事件) / "
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
            "name": "complete_onboarding",
            "description": (
                "在第三幕『立约』收尾时调用：把这次相遇标记为完成。"
                "调用前应已 set_identity 并至少写过一条 owner_note。"
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
