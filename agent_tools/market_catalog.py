"""市集：看货架、装包、列出可以上架的本机资产。"""
from __future__ import annotations

from . import TIER_AUTO, TIER_CONFIRM, ToolResult, ToolSpec, register_tool


def _fmt_item(it: dict) -> str:
    kind = it.get("kind") or "?"
    ver = it.get("version") or "?"
    author = it.get("author") or "佚名"
    score = it.get("score")
    extra = f" · {score}分" if score is not None else ""
    return f"- `{it.get('id')}` {kind} 「{it.get('name')}」 v{ver} · {author}{extra}"


def _list(_args: dict) -> ToolResult:
    from workers.market_index import snapshot
    snap = snapshot()
    items = snap.get("items") or []
    lines = [
        f"# 扩展市场货架 · {snap.get('source')}",
        f"目录网址: {snap.get('catalog_url') or '（还没配，读本机 data/market/index.json）'}",
        f"共 {len(items)} 个",
        "",
    ]
    if not items:
        lines.append("货架是空的。挂上去的东西进专门的市集仓，不进 Daemonkey 源码仓。")
    else:
        lines.extend(_fmt_item(it) for it in items)
    share = snap.get("shareable") or []
    lines += ["", f"# 可以上架（本机有、货架没有或更旧）· {len(share)}"]
    why = {"unpublished": "货架没有", "newer": "本机版本更新", "edited": "装完后又改过"}
    for it in share:
        lines.append(_fmt_item(it) + f" · {why.get(it.get('reason'), it.get('reason'))}")
    return ToolResult(ok=True, output="\n".join(lines))


def _inspect(args: dict) -> ToolResult:
    from workers.market_index import catalog_by_id
    iid = str(args.get("id") or "").strip()
    if not iid:
        return ToolResult(ok=False, output="", error="id 必填")
    it = catalog_by_id().get(iid)
    if not it:
        return ToolResult(ok=False, output="", error=f"货架上没有 `{iid}`")
    import json
    return ToolResult(ok=True, output=json.dumps(it, ensure_ascii=False, indent=2))


def _install(args: dict) -> ToolResult:
    from workers import market_install
    iid = str(args.get("id") or "").strip()
    if not iid:
        return ToolResult(ok=False, output="", error="id 必填")
    got = market_install.install(iid, overwrite=bool(args.get("overwrite")))
    return ToolResult(ok=bool(got.get("ok")), output=got.get("output") or "", error=got.get("error") or "")


def _rate(args: dict) -> ToolResult:
    from workers.market_rate import rate
    got = rate(str(args.get("id") or "").strip(), args.get("score"))
    return ToolResult(ok=bool(got.get("ok")), output=got.get("output") or "", error=got.get("error") or "")


def _shareable(_args: dict) -> ToolResult:
    from workers.market_index import list_shareable
    rows = list_shareable()
    if not rows:
        return ToolResult(ok=True, output="没有可以上架的：本机装修/工坊要么空，要么已经和货架一样。")
    why = {"unpublished": "货架没有", "newer": "本机更新", "edited": "装完后又改过"}
    lines = ["# 可以上架", ""]
    for it in rows:
        lines.append(_fmt_item(it) + f" · {why.get(it.get('reason'), '')}")
    return ToolResult(ok=True, output="\n".join(lines))


def _submit(args: dict) -> ToolResult:
    from workers.market_submit import submit
    got = submit(
        str(args.get("kind") or ""), str(args.get("name") or ""),
        author=str(args.get("author") or ""),
        version=str(args.get("version") or ""),
        description=str(args.get("description") or ""),
    )
    return ToolResult(ok=bool(got.get("ok")), output=got.get("output") or "", error=got.get("error") or "")


def _inbox(args: dict) -> ToolResult:
    from workers import market_inbox as inbox
    action = str(args.get("action") or "list").strip()
    if action == "list":
        box = inbox.list_inbox()
        if not box.get("ok"):
            return ToolResult(ok=False, output="", error=box.get("error") or "待审读不到")
        counts = box.get("counts") or {}
        lines = [f"# 市集待审 · 绿{counts.get('pass', 0)} 黄{counts.get('review', 0)} 红{counts.get('reject', 0)}", ""]
        for it in box.get("items") or []:
            lines.append(f"#{it.get('number')} {it.get('verdict')} {it.get('title')} {it.get('url')}")
            if it.get("report"):
                lines.append(it["report"])
                lines.append("")
        return ToolResult(ok=True, output="\n".join(lines) if box.get("items") else "没有待审的合并申请。")
    if action == "merge":
        got = inbox.merge_one(int(args.get("number") or 0))
    elif action == "close":
        got = inbox.close_one(int(args.get("number") or 0), str(args.get("reason") or ""))
    elif action in ("sweep_red", "merge_green"):
        got = inbox.sweep(action)
    else:
        return ToolResult(ok=False, output="", error="action 用 list/merge/close/sweep_red/merge_green")
    return ToolResult(ok=bool(got.get("ok")), output=got.get("output") or "", error=got.get("error") or "")


register_tool(ToolSpec(
    name="list_market",
    description="看扩展市场货架和本机可以上架的皮肤/工坊/操作手册。货架是市集仓清单，不是源码仓。",
    tier=TIER_AUTO,
    input_schema={"type": "object", "properties": {}, "required": []},
    run=_list,
    summarize=lambda _a: "查看扩展市场货架",
))

register_tool(ToolSpec(
    name="inspect_market",
    description="看货架上某一个包的清单行（名字、说明、分享人、下载地址）。",
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {"id": {"type": "string", "description": "货架条目 id"}},
        "required": ["id"],
    },
    run=_inspect,
    summarize=lambda a: f"查看市集 {a.get('id')}",
))

register_tool(ToolSpec(
    name="list_shareable",
    description="列出本机可以上架的：货架没有、或本机版本更新、或从货架装完后又改过。",
    tier=TIER_AUTO,
    input_schema={"type": "object", "properties": {}, "required": []},
    run=_shareable,
    summarize=lambda _a: "列出可以上架的本机资产",
))

register_tool(ToolSpec(
    name="rate_market",
    description="给货架上已安装的包打 1-5 分。没装过不能打。分先记本机；写回市集仓清单后，别人才能看到公共分。",
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "货架条目 id"},
            "score": {"type": "integer", "description": "1 到 5"},
        },
        "required": ["id", "score"],
    },
    run=_rate,
    summarize=lambda a: f"给市集 {a.get('id')} 打 {a.get('score')} 分",
))

register_tool(ToolSpec(
    name="install_market",
    description="从货架安装一个包到本机对应槽。同名默认拒装，overwrite=true 才覆盖。",
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "货架条目 id"},
            "overwrite": {"type": "boolean", "description": "同名覆盖"},
        },
        "required": ["id"],
    },
    run=_install,
    summarize=lambda a: f"安装市集 {a.get('id')}",
))

register_tool(ToolSpec(
    name="submit_market",
    description="把本机皮肤/工坊打成 .dkpkg 并提市集仓 PR。机器闸红灯不提交。要 Gitee 令牌。",
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "kind": {"type": "string", "description": "app / flow / skin"},
            "name": {"type": "string", "description": "id 或名称"},
            "author": {"type": "string"},
            "version": {"type": "string"},
            "description": {"type": "string"},
        },
        "required": ["kind", "name"],
    },
    run=_submit,
    summarize=lambda a: f"上架 {a.get('kind')}/{a.get('name')}",
))

register_tool(ToolSpec(
    name="review_market",
    description="仓主看市集 PR 待审。action=list/merge/close/sweep_red/merge_green。红灯可一批关，绿灯可一批合。",
    tier=TIER_AUTO,
    classify=lambda a: TIER_CONFIRM if str(a.get("action") or "list") != "list" else TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "list / merge / close / sweep_red / merge_green"},
            "number": {"type": "integer", "description": "PR 号，merge/close 用"},
            "reason": {"type": "string"},
        },
        "required": [],
    },
    run=_inbox,
    summarize=lambda a: f"市集待审 {a.get('action') or 'list'}",
))
