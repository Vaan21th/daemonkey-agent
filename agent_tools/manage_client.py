"""
agent_tools/manage_client.py
============================

OPUS 通过自然语言管理【客户档案】—— "合伙人记得每个客户"。

不是 CRM 表:每个客户是一份会长厚的档案(偏好 / 交付复盘 / 上次聊到哪 / pipeline 阶段)。
notes 进 FTS5·recall_memory 能召回;知识库文档可用 manage_knowledge(action='link') 挂到某客户。

档位：AUTO
  只动 data/clients/ · 无外联 · 误改一句话能补 · 风险低。

action:
  add    · 建档 · 需 name · 可选 company/role/contact/status/tags/notes/need
  list   · 列所有客户(按 pipeline 阶段排)
  get    · 看一个客户完整档案(需求+时间线+挂名下资料)· 需 client 或 name
  update · 改字段 · 需 client + 要改的字段(含 need)
  note   · 往时间线追加一条动态(带日期+kind)· 需 client + text · 档案主要靠这个长厚
  status · 改 pipeline 阶段(lead/active/paused/done)· 需 client + status
  remove · 删档 · 需 client

NLP 触发示例:
  - "新客户 张三, 星途科技 CTO, 微信 zs123, 想做数字人" → add
  - "客户都有谁 / 我的客户列表" → list
  - "星途科技 聊到哪了" → get
  - "给张三档案加一条: 今天谈定首款 2 万" → note
  - "星途转成在合作了" → status
"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool

_STATUS_CN = {"lead": "线索", "active": "在合作", "paused": "暂停", "done": "已结束"}
_KIND_CN = {"need": "需求", "meeting": "会议", "progress": "进展", "deliver": "交付", "note": "备注"}


def _summarize(args: dict) -> str:
    action = args.get("action") or "?"
    tgt = args.get("client") or args.get("name") or ""
    return f"manage_client {action}{(' · ' + str(tgt)[:40]) if tgt else ''}"


def _fmt_line(m: dict) -> str:
    st = _STATUS_CN.get(m.get("status"), m.get("status") or "")
    comp = f" · {m.get('company')}" if m.get("company") else ""
    role = f" · {m.get('role')}" if m.get("role") else ""
    tags = m.get("tags") or []
    tag_str = f"  #{' #'.join(tags)}" if tags else ""
    return f"  [{m.get('id')}] {m.get('name')}{comp}{role}  [{st}]{tag_str}"


def _linked_docs(client_id: str) -> list[dict]:
    try:
        from workers.knowledge_base import list_documents
        return [d for d in list_documents() if d.get("client_id") == client_id]
    except Exception:
        return []


def _resolve(args: dict) -> tuple[str | None, str | None]:
    from workers.clients import resolve_client_id

    hint = (args.get("client") or args.get("name") or args.get("client_id") or "").strip()
    if not hint:
        return None, "需要 client(id 或名字)指定哪个客户"
    cid = resolve_client_id(hint)
    if not cid:
        return None, f"找不到客户: {hint} · 用 action=list 看现有清单"
    return cid, None


def _run(args: dict) -> ToolResult:
    from workers import clients as cl

    action = (args.get("action") or "list").lower().strip()

    try:
        if action == "add":
            name = (args.get("name") or "").strip()
            if not name:
                return ToolResult(ok=False, output="", error="add 需要 name(客户名/公司简称)")
            meta = cl.add_client(
                name,
                company=(args.get("company") or "").strip(),
                role=(args.get("role") or "").strip(),
                contact=(args.get("contact") or "").strip(),
                status=(args.get("status") or "lead").strip(),
                tags=args.get("tags") or [],
                notes=(args.get("notes") or ""),
                need=(args.get("need") or "").strip(),
                intent=(args.get("intent") or "").strip(),
                quote=(args.get("quote") or "").strip(),
                next=(args.get("next") or "").strip(),
            )
            return ToolResult(
                ok=True,
                output=(
                    f"已建档 · [{meta['id']}] {meta['name']}"
                    f"{(' · ' + meta['company']) if meta['company'] else ''} "
                    f"[{_STATUS_CN.get(meta['status'], meta['status'])}]\n"
                    f"  之后可用 note 加交付复盘 · 用 manage_knowledge link 把资料挂到他名下。"
                ),
            )

        if action == "list":
            docs = cl.list_clients()
            st = cl.stats()
            if not docs:
                return ToolResult(ok=True, output="还没有客户档案 · 用 action=add + name 建第一个。")
            by = st["by_status"]
            head = " · ".join(f"{_STATUS_CN.get(k, k)} {v}" for k, v in by.items())
            lines = [f"# 客户档案 · 共 {st['total']} 个({head})", ""]
            lines.extend(_fmt_line(m) for m in docs)
            return ToolResult(ok=True, output="\n".join(lines))

        if action == "get":
            cid, err = _resolve(args)
            if err:
                return ToolResult(ok=False, output="", error=err)
            m = cl.get_client(cid) or {}
            docs = _linked_docs(cid)
            lines = [
                f"# {m.get('name')} · [{_STATUS_CN.get(m.get('status'), m.get('status'))}]",
                f"  公司: {m.get('company') or '—'} · 角色: {m.get('role') or '—'}",
                f"  联系: {m.get('contact') or '—'} · 标签: {m.get('tags') or []}",
            ]
            glance = []
            if (m.get("intent") or "").strip():
                glance.append(f"意向 {m['intent']}")
            if (m.get("quote") or "").strip():
                glance.append(f"报价 {m['quote']}")
            if (m.get("next") or "").strip():
                glance.append(f"下一步 {m['next']}")
            if glance:
                lines.append("  " + " · ".join(glance))
            if (m.get("need") or "").strip():
                lines += ["", "## 客户需求", m["need"].strip()]
            log = m.get("log") or []
            if log:
                lines += ["", f"## 动态时间线({len(log)} 条 · 新→旧)"]
                for e in reversed(log):
                    kn = _KIND_CN.get(e.get("kind"), "备注")
                    lines.append(f"  [{e.get('date', '')}] 〔{kn}〕{e.get('text', '')}")
            elif (m.get("notes") or "").strip():
                lines += ["", "## 历史备注", m["notes"].strip()]
            else:
                lines += ["", "(还没有动态 · 用 action=note + kind 记需求/会议/进展/交付)"]
            if docs:
                lines.append("")
                lines.append(f"## 交付与过程 · 挂在名下的资料({len(docs)})")
                for d in docs:
                    lines.append(f"  - [{d.get('id')}] {d.get('title')}")
            return ToolResult(ok=True, output="\n".join(lines))

        if action == "update":
            cid, err = _resolve(args)
            if err:
                return ToolResult(ok=False, output="", error=err)
            changes = {k: args.get(k) for k in
                       ("name", "company", "role", "contact", "status", "tags", "notes",
                        "need", "intent", "quote", "next")
                       if args.get(k) is not None}
            if not changes:
                return ToolResult(ok=False, output="", error="update 需要至少一个要改的字段")
            m = cl.update_client(cid, **changes)
            return ToolResult(ok=True, output=f"[{m['id']}] {m['name']} 已更新 · 改了: {list(changes.keys())}")

        if action == "note":
            cid, err = _resolve(args)
            if err:
                return ToolResult(ok=False, output="", error=err)
            text = (args.get("text") or args.get("notes") or "").strip()
            if not text:
                return ToolResult(ok=False, output="", error="note 需要 text(要追加的动态)")
            kind = (args.get("kind") or "note").strip().lower()
            if kind not in cl.KINDS:
                kind = "note"
            m = cl.append_note(cid, text, kind=kind)
            return ToolResult(
                ok=True,
                output=f"[{m['id']}] {m['name']} 已记一条〔{_KIND_CN.get(kind, '备注')}〕(时间线越来越厚了)。",
            )

        if action == "status":
            cid, err = _resolve(args)
            if err:
                return ToolResult(ok=False, output="", error=err)
            status = (args.get("status") or "").strip()
            if status not in cl.STATUSES:
                return ToolResult(ok=False, output="", error=f"status 只能是 {list(cl.STATUSES)}")
            m = cl.update_client(cid, status=status)
            return ToolResult(ok=True, output=f"[{m['id']}] {m['name']} → {_STATUS_CN.get(status, status)}")

        if action == "remove":
            cid, err = _resolve(args)
            if err:
                return ToolResult(ok=False, output="", error=err)
            m = cl.remove_client(cid)
            return ToolResult(ok=True, output=f"已删除客户档案 · [{m['id']}] {m['name']}")

        return ToolResult(
            ok=False, output="",
            error=f"未知 action: {action} · 可选: add/list/get/update/note/status/remove",
        )

    except KeyError as e:
        return ToolResult(ok=False, output="", error=f"找不到客户: {e}")
    except Exception as e:  # noqa: BLE001
        return ToolResult(ok=False, output="", error=f"tool internal error: {e}")


SPEC = ToolSpec(
    name="manage_client",
    description=(
        "管理 BRO 的【客户档案】——让 OPUS 像合伙人一样记得每个客户。\n\n"
        "不是 CRM 表:每个客户是一份会长厚的档案(偏好/历次交付复盘/上次聊到哪/pipeline 阶段)。"
        "notes 会进记忆索引·recall_memory 能召回;知识库文档可用 manage_knowledge(action='link', "
        "client=...) 挂到客户名下。\n\n"
        "**调用时机**(OPUS 主动判断):\n"
        "  - BRO 提到一个新客户/合作方(给了名字/公司/需求) → action=add(需求写进 need)\n"
        "  - BRO 问'客户都有谁 / X 聊到哪了' → action=list / get\n"
        "  - 一次沟通/会议/交付后 → action=note 把动态记进时间线(带日期)\n"
        "  - 合作状态变了('转成在合作了'/'这单结了') → action=status\n\n"
        "**动态归类(note 的 kind)**——记进时间线时按内容选类型:\n"
        "  - need   客户的诉求/目标('他们想做数字人客服')\n"
        "  - meeting 会议/通话记录('今天电话会:确认首期范围+排期')——会议纪要模式整理出的纪要就存这里\n"
        "  - progress 阶段进展('demo 已发·等对方反馈')\n"
        "  - deliver 交付动作('交付第一版脚本·3 条')\n"
        "  - note   其它备注(默认)\n"
        "kind 拿不准就用 note·别漏记。need 字段是「当前需求速览」·会议里聊出的新需求既可更新 need 也可记一条 kind=need。\n"
        "**速览字段**(update/add 顺手更新·别硬问):intent(意向 高/中/低)、quote(报价/预算)、next(下一步动作)。\n\n"
        "**pipeline 阶段**: lead(线索) / active(在合作) / paused(暂停) / done(结束)。\n"
        "**actions**: add / list / get / update / note / status / remove"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "list", "get", "update", "note", "status", "remove"],
            },
            "client": {"type": "string", "description": "get/update/note/status/remove 用:客户 id 或名字(模糊匹配)"},
            "name": {"type": "string", "description": "add 用:客户名/公司简称(必填);update 用:改名"},
            "company": {"type": "string", "description": "公司全称"},
            "role": {"type": "string", "description": "对接人角色/职位"},
            "contact": {"type": "string", "description": "联系方式(微信/电话/邮箱·自由文本)"},
            "status": {"type": "string", "enum": ["lead", "active", "paused", "done"], "description": "pipeline 阶段"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "标签数组"},
            "need": {"type": "string", "description": "add/update 用:客户当前需求速览(一句话·会随合作推进更新)"},
            "intent": {"type": "string", "description": "add/update 用:成交意向(高/中/低·自由文本)"},
            "quote": {"type": "string", "description": "add/update 用:报价/预算(如 '8.6 万' / '年框谈判中')"},
            "next": {"type": "string", "description": "add/update 用:下一步动作(如 '7/20 交付第一版')"},
            "notes": {"type": "string", "description": "add/update 用:整段备注(覆盖)。追加动态请用 action=note + text + kind"},
            "text": {"type": "string", "description": "note 用:要追加的一条动态(自动带日期)"},
            "kind": {
                "type": "string",
                "enum": ["need", "meeting", "progress", "deliver", "note"],
                "description": "note 用:这条动态的类型(需求/会议/进展/交付/备注)· 默认 note",
            },
        },
        "required": ["action"],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
