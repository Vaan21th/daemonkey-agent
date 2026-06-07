"""
agent_tools/tag_radar_item.py
==============================

 · 雷达条目打标工具（闭环反馈）

让 用户 用对话或 UI 给雷达条目打标：
  👍 thumbs_up   · "对路 · 多关注这类"
  👎 thumbs_down · "不对 · 别再抓"
  ⭐ starred     · "收藏"
  🗑 hidden      · "藏起来"

档位：AUTO
  只写 data/radar_feedback.json · 不外联 · 不调 LLM · 没什么风险

NLP 触发：
  - "把第 N 条雷达 thumbs down·因为没意思" → action=set, item_index=N, feedback=thumbs_down
  - "收藏一下那条 Anthropic Cowork 的" → action=set, query="Anthropic Cowork", feedback=starred
  - "把那条藏起来" → action=set, item_index=N, feedback=hidden
  - "看看我收藏了哪些" → action=list, only=starred
"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


_FB_LABEL = {
    "thumbs_up": "👍 关注这类",
    "thumbs_down": "👎 别再抓",
    "starred": "⭐ 收藏",
    "hidden": "🗑 隐藏",
}


def _summarize(args: dict) -> str:
    action = (args.get("action") or "set").lower()
    if action == "list":
        return f"tag_radar_item · list only={args.get('only') or 'all'}"
    if action == "clear":
        return f"tag_radar_item · clear {args.get('item_id') or args.get('item_index') or '?'}"
    fb = args.get("feedback", "?")
    ref = args.get("item_id") or args.get("item_index") or args.get("query") or "?"
    return f"tag_radar_item · {ref} · {fb}"


def _resolve_item_id(args: dict) -> tuple[str | None, dict | None, str | None]:
    """
    根据 args 找出 item_id + 拿到 radar item 快照 + 错误信息
    支持 item_id / item_index (1-based 在最近一次 radar listing) / query (标题模糊匹配)
    """
    from workers.info_radar import load_radar
    from workers.radar_feedback import item_id_for_url

    if args.get("item_id"):
        iid = args["item_id"].strip()
        radar = load_radar()
        for it in radar.get("items") or []:
            if item_id_for_url(it.get("url") or "") == iid:
                return iid, it, None
        # 找不到也允许 · feedback 还是会存
        return iid, None, None

    if args.get("item_index") is not None:
        try:
            idx = int(args["item_index"])
        except (TypeError, ValueError):
            return None, None, f"item_index 必须是整数 · 收到 {args['item_index']!r}"
        radar = load_radar()
        items = radar.get("items") or []
        if idx < 1 or idx > len(items):
            return None, None, f"item_index 越界 · 范围 1-{len(items)}"
        it = items[idx - 1]
        return item_id_for_url(it.get("url") or ""), it, None

    if args.get("query"):
        q = (args["query"] or "").strip().lower()
        if not q:
            return None, None, "query 不能为空"
        radar = load_radar()
        items = radar.get("items") or []
        # 优先全词 · 再退化 substring
        matches = []
        for it in items:
            title = (it.get("title_zh") or it.get("title") or "").lower()
            if q in title:
                matches.append(it)
        if not matches:
            return None, None, f"没找到包含「{args['query']}」的条目"
        if len(matches) > 1:
            preview = "\n".join(
                f"  - {(m.get('title_zh') or m.get('title') or '')[:60]}"
                for m in matches[:5]
            )
            return None, None, (
                f"匹配到 {len(matches)} 条 · 太多 · 请用更精确的 query 或 item_index：\n"
                + preview
            )
        it = matches[0]
        return item_id_for_url(it.get("url") or ""), it, None

    return None, None, "需要 item_id / item_index / query 之一"


def _run(args: dict) -> ToolResult:
    from workers.radar_feedback import (
        FEEDBACK_LABEL,
        clear_feedback,
        list_feedback,
        set_feedback,
    )

    action = (args.get("action") or "set").lower().strip()

    try:
        if action == "list":
            only = args.get("only")
            if only and only not in {"thumbs_up", "thumbs_down", "starred", "hidden"}:
                return ToolResult(ok=False, output="",
                                  error=f"only 必须是 4 种 feedback 之一·收到 {only!r}")
            data = list_feedback(only=only)
            items = data.get("items") or []
            if not items:
                hint = f"没有 {only}" if only else "雷达里还没打过任何标"
                return ToolResult(ok=True, output=hint + " · 用户 在 UI 上点 👍/👎/⭐/🗑 或在对话里说就行")
            counts = data.get("by_feedback") or {}
            lines = [
                f"# 雷达打标 · 共 {data['total']} 条",
                f"统计: 👍 {counts.get('thumbs_up',0)} · 👎 {counts.get('thumbs_down',0)} "
                f"· ⭐ {counts.get('starred',0)} · 🗑 {counts.get('hidden',0)}",
                "",
            ]
            for it in items[:20]:
                lines.append(
                    f"- {it.get('label','?')} [{it.get('source','?')}] "
                    f"{(it.get('title') or '?')[:60]}"
                )
                if it.get("note"):
                    lines.append(f"    用户 备注：{it['note']}")
            return ToolResult(ok=True, output="\n".join(lines))

        if action == "clear":
            iid, _it, err = _resolve_item_id(args)
            if err:
                return ToolResult(ok=False, output="", error=err)
            r = clear_feedback(iid)
            return ToolResult(
                ok=True,
                output=(
                    "已清除标记" if not r.get("no_op")
                    else f"opp_id={iid} 本来就没标记 · no-op"
                ),
            )

        # action=set · 主路径
        fb = (args.get("feedback") or "").strip().lower()
        if fb not in _FB_LABEL:
            return ToolResult(ok=False, output="",
                              error=f"feedback 必须是 thumbs_up/thumbs_down/starred/hidden 之一·收到 {fb!r}")
        iid, it, err = _resolve_item_id(args)
        if err:
            return ToolResult(ok=False, output="", error=err)

        title_hint = None
        url_hint = None
        if it:
            title_hint = (it.get("title_zh") or it.get("title") or "")[:200]
            url_hint = it.get("url")

        result = set_feedback(
            iid,
            fb,
            note=args.get("note"),
            title_hint=title_hint,
            url_hint=url_hint,
        )
        if not result.get("ok"):
            return ToolResult(ok=False, output="", error=result.get("error") or "记录失败")
        entry = result.get("entry") or {}
        title_show = entry.get("title_snap") or title_hint or "?"
        return ToolResult(
            ok=True,
            output=(
                f"✓ 已标 {_FB_LABEL[fb]}\n"
                f"  条目：{title_show[:80]}\n"
                f"  来源：{entry.get('source','?')}\n\n"
                "下次 mine_opportunities / trend_finder 跑 LLM 时会读到这条反馈·"
                "OPUS 会逐渐知道你想看什么 / 不想看什么。"
            ),
        )

    except Exception as e:
        return ToolResult(ok=False, output="", error=f"tag_radar_item 失败: {e}")


SPEC = ToolSpec(
    name="tag_radar_item",
    description=(
        " · 信息雷达条目打标 · 4 种反馈 + 闭环反哺。\n\n"
        "**调用时机**（OPUS 主动判断）:\n"
        "  - 用户 说'把第 3 条 thumbs down' → action=set, item_index=3, feedback=thumbs_down\n"
        "  - 用户 说'收藏那条 Anthropic 的' → action=set, query='Anthropic', feedback=starred\n"
        "  - 用户 说'把那条藏起来' → action=set, item_index=N, feedback=hidden\n"
        "  - 用户 说'看看我收藏了什么' → action=list, only=starred\n"
        "  - 用户 在 WebUI 上点 👍/👎/⭐/🗑 按钮也会落到同一份 data\n\n"
        "**actions**:\n"
        "  - set · 主路径 · 必填 feedback + (item_id/item_index/query 之一)\n"
        "  - list · 列已标记·可加 only=starred 等过滤\n"
        "  - clear · 清掉某条标记（留 history）\n\n"
        "**反馈机制**：所有标会被 mine_opportunities / trend_finder 在跑 LLM 前读到·"
        "👎 的源被记为'用户 拒过'·next time OPUS 会避开同源同类。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["set", "list", "clear"],
                "description": "set=打标（默认） / list=列已标 / clear=取消标记",
            },
            "feedback": {
                "type": "string",
                "enum": ["thumbs_up", "thumbs_down", "starred", "hidden"],
                "description": "thumbs_up=认可 / thumbs_down=拒 / starred=收藏 / hidden=隐藏",
            },
            "item_id": {
                "type": "string",
                "description": "条目稳定 id (md5(url) 前 12 位) · 一般 UI 来调",
            },
            "item_index": {
                "type": "integer",
                "description": "条目在最近一次 list_items() 输出里的 1-based 序号",
                "minimum": 1,
                "maximum": 500,
            },
            "query": {
                "type": "string",
                "description": "按标题模糊匹配·命中唯一时使用·命中多条会要求换更精确的",
            },
            "only": {
                "type": "string",
                "enum": ["thumbs_up", "thumbs_down", "starred", "hidden"],
                "description": "action=list 时按 feedback 过滤",
            },
            "note": {
                "type": "string",
                "description": "可选备注·比如 thumbs_down 的具体原因（用户 的负反馈信号最值钱）",
                "maxLength": 200,
            },
        },
        "required": ["action"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
