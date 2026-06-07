"""
agent_tools/init_domain.py
==========================

 · 一句话建领域 · NLP 主路径

用户 在对话里说"帮我关注 XX 领域·开始关注资讯" → OPUS:
  1. 在 DOMAIN_META 注册新领域（slug 自动从 name 派生）
  2. 立即批量加 N 个信源进 radar_sources.json
  3. 触发一次 refresh_radar · 让 用户 立刻能在雷达里看到这个新领域的内容

档位：CONFIRM
  会写盘 + 拉外部 RSS · 应该给 用户 一次 confirm
  但 fallback：如果 OPUS 已经在对话里跟 用户 确认了"我要建 XX 领域·拉这几个源"·
  CONFIRM 在 UI 里是一键过的·并不痛苦

NLP 触发：
  - 用户: "帮我关注 D4 新赛季淘金这个领域" →
    OPUS 先用 web_search 找几个 D4 相关 RSS / 论坛 URL → 调本工具一次过

入参：
  - domain_slug    · 领域 slug · 必填 · 比如 "d4-gold" / "ai-video"
  - label          · 中文显示名 · 必填 · 比如 "D4 淘金"
  - icon           · emoji · 可选 · 默认 🧭
  - color          · hex 色 · 可选 · 默认 #a0aec0
  - description    · 一句话说明 · 可选
  - sources        · 信源列表 · 数组 · 每个 {name, url, source_type?='rss', category?='community'}
  - refresh_after  · bool · 默认 True · 加完源是否立即刷新一次

落盘：
  - data/domains_extra.json 加一条
  - data/radar_sources.json 加 N 条
  - data/radar.json 被 refresh_radar 更新（如果 refresh_after=True）
"""
from __future__ import annotations

import logging

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool

logger = logging.getLogger("opus.init_domain")


def _summarize(args: dict) -> str:
    slug = args.get("domain_slug") or "?"
    n = len(args.get("sources") or [])
    return f"init_domain · {slug} · +{n} 信源"


def _run(args: dict) -> ToolResult:
    from workers.info_radar import (
        DOMAIN_META,
        add_domain,
        add_source,
        refresh_radar,
    )

    domain_slug = (args.get("domain_slug") or "").strip()
    label = (args.get("label") or "").strip()
    if not domain_slug:
        return ToolResult(ok=False, output="", error="domain_slug 必填")
    if not label:
        return ToolResult(ok=False, output="", error="label 必填 · 比如 'D4 淘金'")

    sources_arg = args.get("sources") or []
    if not isinstance(sources_arg, list):
        return ToolResult(ok=False, output="", error="sources 必须是数组")

    # 1) 建 domain
    try:
        dom_result = add_domain(
            domain_slug,
            label=label,
            icon=args.get("icon") or "🧭",
            color=args.get("color") or "#a0aec0",
            description=args.get("description") or "",
        )
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"add_domain 失败: {e}")

    final_slug = dom_result.get("slug") or domain_slug
    was_new = not dom_result.get("no_op")

    # 2) 批量加源
    added: list[dict] = []
    failed: list[dict] = []
    for s in sources_arg[:15]:  # 一次最多 15 条 · 防 LLM 失控
        if not isinstance(s, dict):
            failed.append({"input": str(s), "error": "需要 dict"})
            continue
        name = (s.get("name") or "").strip()
        url = (s.get("url") or "").strip()
        if not name or not url:
            failed.append({"input": str(s), "error": "name + url 必填"})
            continue
        try:
            new = add_source(
                name=name,
                url=url,
                source_type=s.get("source_type") or "rss",
                category=s.get("category") or "community",
                display=s.get("display") or name[:20],
                max_items=int(s.get("max_items") or 10),
                tags=s.get("tags") or [],
                domain=final_slug,
            )
            added.append({"id": new.get("id"), "name": name, "url": url})
        except Exception as e:
            failed.append({"name": name, "url": url, "error": str(e)})

    # 3) 刷新（可选）
    refresh_summary: dict | None = None
    if args.get("refresh_after", True) and added:
        try:
            refresh_summary = refresh_radar()
        except Exception as e:
            logger.warning("init_domain refresh_after failed: %s", e)
            refresh_summary = {"error": str(e)}

    # 4) 渲染输出
    lines: list[str] = []
    if was_new:
        lines.append(f"# ✓ 新建领域 · {DOMAIN_META[final_slug]['icon']} {label} ({final_slug})")
    else:
        lines.append(f"# ℹ 领域已存在 · {DOMAIN_META[final_slug]['icon']} {label} ({final_slug})")
    lines.append("")
    if added:
        lines.append(f"## 已添加 {len(added)} 个信源")
        for s in added:
            lines.append(f"- `{s['id']}` · {s['name']} · {s['url']}")
        lines.append("")
    if failed:
        lines.append(f"## 添加失败 {len(failed)} 条")
        for f in failed:
            name = f.get("name") or f.get("input") or "?"
            lines.append(f"- {name}: {f.get('error', '?')}")
        lines.append("")
    if refresh_summary:
        if refresh_summary.get("error"):
            lines.append(f"⚠ refresh_radar 失败: {refresh_summary['error']}")
        else:
            lines.append(
                f"## ✓ 已立即刷新雷达 · "
                f"{refresh_summary.get('ok_sources', '?')}/{refresh_summary.get('sources', '?')} 源 OK "
                f"· {refresh_summary.get('total', '?')} 条 · "
                f"{refresh_summary.get('elapsed_ms', '?')}ms"
            )
            lines.append("")
            lines.append("用户 现在去 📡 信息雷达 · 用顶部 domain 过滤器选 "
                         f"「{DOMAIN_META[final_slug]['icon']} {label}」就能看到结果。")
    elif added:
        lines.append("（没自动 refresh · 你说一句「刷新雷达」我再跑）")

    if not added and not failed:
        # 补丁 · 允许"占位建领域"——不再当作半失败
        # 原因：用户 上次试"文玩"领域时·DuckDuckGo 限流让 LLM 没法 search 出可靠源
        # 卡死在"search 失败 → 不敢调 init_domain"的循环
        # 现在允许 LLM 先建领域占位 · 后续慢慢用 manage_info_source 加源
        lines.append(
            "ℹ 领域已建·但还没加源。下一步可以：\n"
            f"  - 用 web_search / browser_fetch 找到该领域的 RSS / blog URL\n"
            f"  - 再调 manage_info_source action=add (一次加一个)·或重新调 init_domain 带 sources 一次性加多个\n"
            f"  - 也可以让 用户 直接给几个他知道的网址·OPUS 一一验证\n"
            f"  - **不要因为 search 不顺就放弃这一步**·领域占位先建好·后面慢慢填"
        )

    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="init_domain",
    description=(
        " · 一句话建领域 · 自动加信源 + 立即刷雷达。\n\n"
        "**调用时机**（OPUS 主动判断）:\n"
        "  - 用户 说'帮我关注 D4 新赛季淘金' / '帮我加一个文玩类目' → OPUS 直接调本工具\n"
        "  - 用户 说'我要开始追 AI 视频生成这个方向' → 同上\n"
        "  - 任何'帮我关注 X' / '加一个 Y 领域' 都触发\n\n"
        "**补丁 · 优先策略**:\n"
        "  - **可以先建空领域占位**（sources=[]）·然后慢慢加源·不要求一次找齐\n"
        "  - 如果 web_search 限流 / 找不到可用 RSS·**先建领域**·再用 manage_info_source 单加\n"
        "  - 比起'卡死在 search'·**先建占位再补源**几乎总是更好的策略\n\n"
        "**理想路径**:\n"
        "  1. 先调 web_search 看看·能找到 2-3 个像样的 RSS 就一起传\n"
        "  2. 找不到也没关系·sources=[] 也能调·领域先建出来\n"
        "  3. domain_slug 用 ascii + dash · 比如 'd4-gold' 'ai-video' 'wenwan'\n"
        "  4. label 用中文 · 给 UI 看的\n"
        "  5. icon 选 emoji 时要扣题 · 不要硬上 🧭\n\n"
        "**示例 sources**:\n"
        "  [{\"name\": \"Diablo 4 Subreddit\", \"url\": \"https://www.reddit.com/r/diablo4/.rss\", "
        "\"source_type\": \"rss\", \"category\": \"community\"}]"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "domain_slug": {
                "type": "string",
                "description": "领域 slug · ascii + dash · 比如 'd4-gold'",
                "minLength": 2,
                "maxLength": 40,
            },
            "label": {
                "type": "string",
                "description": "中文显示名 · 比如 'D4 淘金'",
                "minLength": 1,
                "maxLength": 30,
            },
            "icon": {
                "type": "string",
                "description": "emoji 图标 · 默认 🧭",
                "maxLength": 4,
            },
            "color": {
                "type": "string",
                "description": "hex 颜色 · 默认 #a0aec0",
                "maxLength": 9,
            },
            "description": {
                "type": "string",
                "description": "一句话说明",
                "maxLength": 120,
            },
            "sources": {
                "type": "array",
                "description": "要立即加的信源列表 · 每条 {name, url, source_type?, category?}",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "url": {"type": "string"},
                        "source_type": {"type": "string", "enum": ["rss", "html"]},
                        "category": {"type": "string"},
                        "display": {"type": "string"},
                        "max_items": {"type": "integer"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["name", "url"],
                },
                "maxItems": 15,
            },
            "refresh_after": {
                "type": "boolean",
                "description": "加完源是否立即触发一次 refresh_radar · 默认 true",
            },
        },
        "required": ["domain_slug", "label"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
