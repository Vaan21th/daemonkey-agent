"""
agent_tools/manage_info_source.py
==================================

OPUS 通过自然语言管理信息雷达的源清单。

档位：AUTO
  只动 data/radar_sources.json · 不调外网 · 不动文件系统其他位置。
  即使误删一个源 · 用户 一句话能让 OPUS 加回来 · 风险足够低走 AUTO。

action:
  list    · 列出当前所有源 · 不传别的参数
  add     · 加新源 · 需要 name + url · 可选 category / type / max_items
  remove  · 删源 · 需要 source_id 或 name
  update  · 改源属性 · 需要 source_id · 可改 enabled / category / max_items / display
  refresh · 立即让 worker 重新跑一次抓取 · 用于"刚改完源 用户 想看效果"

NLP 触发示例（OPUS 自己决定调这个工具的时机）：
  - "加一个抖音科技板块" → action=add
  - "把 arxiv 删了" → action=remove, source_id="arxiv-ai"
  - "TC AI 太多了 · 改成只看 5 条" → action=update, source_id="tc-ai", max_items=5
  - "少数派暂停一下 · 别抓了" → action=update, source_id="sspai", enabled=False
  - "现在都有哪些源？" → action=list
"""
from __future__ import annotations

from typing import Any

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool

# 兜底领域是【实例配置】(母体 ai / 开源版 self-evolve)·不是代码常量。
try:
    from identity import default_domain as _default_domain
except Exception:
    def _default_domain():
        return "ai"


def _summarize(args: dict) -> str:
    action = args.get("action") or "?"
    extra_parts = []
    if action == "add":
        extra_parts.append(args.get("name") or args.get("url") or "?")
    elif action in ("remove", "update"):
        extra_parts.append(args.get("source_id") or args.get("name") or "?")
    return f"manage_info_source {action} {' '.join(extra_parts)}".strip()


def _format_source_line(s: dict) -> str:
    """单源一行展示 · 给 LLM / 用户 都能读"""
    enabled_mark = "[on]" if s.get("enabled", True) else "[off]"
    return (
        f"  - {s['id']} {enabled_mark}  "
        f"{s.get('display', s['id'])}  "
        f"domain={s.get('domain', _default_domain())}  "
        f"category={s.get('category', '?')}  "
        f"type={s.get('type', 'rss')}  "
        f"max={s.get('max_items', 10)}  "
        f"url={s['url']}"
    )


def _resolve_id(sources: list[dict], hint: str) -> str | None:
    """根据 用户 给的 hint (id / name / display) 找对应 source_id"""
    hint_lower = hint.lower().strip()
    for s in sources:
        if s["id"] == hint:
            return s["id"]
    for s in sources:
        if s["id"].lower() == hint_lower:
            return s["id"]
    for s in sources:
        if s.get("name", "").lower() == hint_lower:
            return s["id"]
    for s in sources:
        if s.get("display", "").lower() == hint_lower:
            return s["id"]
    # 模糊匹配——任何字段包含 hint
    for s in sources:
        if hint_lower in s["id"].lower() or hint_lower in s.get("name", "").lower():
            return s["id"]
    return None


def _run(args: dict) -> ToolResult:
    from workers.info_radar import (
        add_source,
        list_sources,
        load_radar,
        refresh_radar,
        remove_source,
        update_source,
    )

    action = (args.get("action") or "list").lower().strip()

    try:
        if action == "list":
            from workers.info_radar import DOMAIN_META, list_domains
            sources = list_sources(domain=args.get("domain"))
            on = sum(1 for s in sources if s.get("enabled", True))
            off = len(sources) - on
            domain_filter = args.get("domain")
            header = f"信息雷达源清单 · 共 {len(sources)} 个 ({on} 启用 · {off} 暂停)"
            if domain_filter:
                meta = DOMAIN_META.get(domain_filter, {})
                header += f" · 领域={meta.get('icon', '')} {domain_filter}"
            lines = [header, ""]

            # 按 domain 分组展示 · 一目了然
            by_domain: dict[str, list[dict]] = {}
            for s in sources:
                d = s.get("domain", _default_domain())
                by_domain.setdefault(d, []).append(s)

            for did, group in by_domain.items():
                meta = DOMAIN_META.get(did, {"icon": "?", "label": did})
                lines.append(f"  {meta['icon']} {meta.get('label', did)} ({did}) · {len(group)} 个源")
                for s in group:
                    lines.append(_format_source_line(s))
                lines.append("")

            if not domain_filter:
                lines.append("领域概览:")
                for d in list_domains():
                    lines.append(
                        f"  {d['icon']} {d['label']} ({d['id']}) · "
                        f"{d['sources_count']} 源 · {d['items_count']} 条资讯"
                    )
                lines.append("")

            radar = load_radar()
            generated = radar.get("generated_at")
            if generated:
                lines.append(
                    f"上次抓取: {generated} · {radar.get('total_items', 0)} 条资讯"
                )
            return ToolResult(ok=True, output="\n".join(lines))

        if action == "add":
            name = (args.get("name") or "").strip()
            url = (args.get("url") or "").strip()
            if not (name and url):
                return ToolResult(
                    ok=False,
                    output="",
                    error="add 需要 name + url 两个必填字段",
                )
            new = add_source(
                name=name,
                url=url,
                source_type=(args.get("type") or "rss"),
                category=(args.get("category") or "tech"),
                display=args.get("display"),
                max_items=int(args.get("max_items") or 10),
                tags=args.get("tags"),
                domain=(args.get("domain") or "self-evolve"),
            )
            return ToolResult(
                ok=True,
                output=(
                    f"已添加源 · id={new['id']} · name={new['name']}\n"
                    f"  url={new['url']}\n"
                    f"  domain={new.get('domain', _default_domain())}  category={new['category']}  type={new['type']}\n"
                    f"\n下次 worker 跑时会包含这个源。立即生效请用 action=refresh。"
                ),
            )

        if action == "remove":
            sid = (args.get("source_id") or args.get("name") or "").strip()
            if not sid:
                return ToolResult(
                    ok=False,
                    output="",
                    error="remove 需要 source_id 或 name",
                )
            sources_now = list_sources()
            resolved = _resolve_id(sources_now, sid)
            if not resolved:
                return ToolResult(
                    ok=False,
                    output="",
                    error=(
                        f"找不到源: {sid}\n"
                        f"现有源 id: {[s['id'] for s in sources_now]}"
                    ),
                )
            removed = remove_source(resolved)
            return ToolResult(
                ok=True,
                output=(
                    f"已删除源 · {removed['id']} ({removed.get('display', '')})\n"
                    f"  原 url: {removed['url']}\n"
                    f"\n如果误删 · 跟 OPUS 说'恢复 {removed['id']}'即可重加。"
                ),
            )

        if action == "update":
            sid = (args.get("source_id") or "").strip()
            if not sid:
                return ToolResult(
                    ok=False,
                    output="",
                    error="update 需要 source_id",
                )
            sources_now = list_sources()
            resolved = _resolve_id(sources_now, sid)
            if not resolved:
                return ToolResult(
                    ok=False,
                    output="",
                    error=(
                        f"找不到源: {sid}\n"
                        f"现有源 id: {[s['id'] for s in sources_now]}"
                    ),
                )
            allowed_keys = {"enabled", "category", "max_items", "display", "url", "tags", "name", "type", "domain"}
            changes: dict[str, Any] = {}
            for k in allowed_keys:
                if k in args:
                    changes[k] = args[k]
            if not changes:
                return ToolResult(
                    ok=False,
                    output="",
                    error=(
                        f"update 需要至少一个可改字段: {sorted(allowed_keys)}"
                    ),
                )
            if "max_items" in changes:
                try:
                    changes["max_items"] = int(changes["max_items"])
                except (ValueError, TypeError):
                    return ToolResult(
                        ok=False, output="",
                        error="max_items 必须是整数",
                    )
            updated = update_source(resolved, **changes)
            return ToolResult(
                ok=True,
                output=(
                    f"已更新源 · {updated['id']}\n"
                    f"  改动: {changes}\n"
                    f"  现状: enabled={updated.get('enabled', True)}  "
                    f"category={updated.get('category', '?')}  "
                    f"max_items={updated.get('max_items', 10)}"
                ),
            )

        if action == "refresh":
            result = refresh_radar()
            return ToolResult(
                ok=True,
                output=(
                    f"雷达已刷新 · {result['ok_sources']}/{result['sources']} 源 OK · "
                    f"{result['total']} 条资讯 · {result['elapsed_ms']}ms"
                ),
            )

        return ToolResult(
            ok=False,
            output="",
            error=f"未知 action: {action} · 可选: list / add / remove / update / refresh",
        )

    except KeyError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except ValueError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"tool internal error: {e}")


SPEC = ToolSpec(
    name="manage_info_source",
    description=(
        "Manage the info radar source list (data/radar_sources.json). "
        "Use this when 用户 asks to add/remove/pause/adjust info sources, or asks "
        "what sources are being watched, or asks to refresh the radar now.\n\n"
        "Actions:\n"
        "  list      · enumerate all sources with their state\n"
        "  add       · add a new source (requires name + url; type defaults to rss)\n"
        "  remove    · remove a source by id (or fuzzy name match)\n"
        "  update    · update fields like enabled/category/max_items/display\n"
        "  refresh   · trigger an immediate worker run (takes 20-60s, fetches all enabled sources)\n\n"
        "Categories used: tech / community / academic / tech-zh / startup / indie / ...\n"
        "Types supported: rss (default · works for RSS 2.0 and Atom feeds), html (reserved).\n\n"
        "Examples (NLP triggers):\n"
        "  - 用户 says '加个少数派' → action=list first to check; then action=add\n"
        "  - 用户 says '别看 arxiv 了' → action=remove, source_id='arxiv-ai'\n"
        "  - 用户 says '看下都有哪些源' → action=list\n"
        "  - 用户 says '现在刷一下雷达' → action=refresh"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "add", "remove", "update", "refresh"],
                "description": "Which operation to perform.",
            },
            "name": {
                "type": "string",
                "description": "Human-readable source name (used for add; also fallback id lookup for remove/update).",
            },
            "url": {
                "type": "string",
                "description": "Feed URL (RSS or Atom). Required for add.",
            },
            "source_id": {
                "type": "string",
                "description": "Source id slug (lowercase, hyphenated). Required for remove/update. Fuzzy match against name/display also works.",
            },
            "category": {
                "type": "string",
                "description": "Source category: tech / community / academic / tech-zh / startup / indie / etc.",
            },
            "type": {
                "type": "string",
                "enum": ["rss", "html"],
                "description": "Source type. 'rss' covers both RSS 2.0 and Atom. 'html' reserved for future Playwright-driven sources.",
            },
            "max_items": {
                "type": "integer",
                "description": "Max items to keep from this source per fetch. Default 10.",
                "minimum": 1,
                "maximum": 50,
            },
            "display": {
                "type": "string",
                "description": "Short display label shown in UI chips (e.g. 'HN' / 'arxiv cs.AI').",
            },
            "enabled": {
                "type": "boolean",
                "description": "Toggle on/off without deleting. Used for 'pause source'.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags for grouping (e.g. ['ZH', 'tech-news']).",
            },
            "domain": {
                "type": "string",
                "description": (
                    "领域桶 · slug · 默认只内置 self-evolve · "
                    "用户在相遇 / 对话里挖出来的关注方向通过 add_focus_domain / init_domain 加成新 domain · "
                    "所以本字段不限定 enum · 但写错 domain add_source/update_source 会校验拒绝。"
                ),
            },
        },
        "required": ["action"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
