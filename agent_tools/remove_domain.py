"""
agent_tools/remove_domain.py
============================

补丁 · 用户 NLP 删一个雷达 domain

用例：
  - 用户: "把文玩这个领域删了" / "我不关注某某领域了"
  - OPUS: 调本工具 · 默认 reassign 模式（保留源·改归 self-evolve·防误删）

档位：CONFIRM
  改写 domains_extra.json + 可能改 radar_sources.json · 应给 用户 确认
  尤其 sources_action=delete 是不可逆的·必须 CONFIRM

红线：
  - self-evolve 是唯一内置领域·不能删
  - 默认 reassign · 把源归到 self-evolve · 而不是 delete
"""
from __future__ import annotations

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    slug = args.get("domain_slug") or "?"
    act = args.get("sources_action") or "reassign"
    return f"remove_domain · {slug} · sources={act}"


def _run(args: dict) -> ToolResult:
    from workers.info_radar import DOMAIN_META, remove_domain

    slug = (args.get("domain_slug") or "").strip()
    sources_action = (args.get("sources_action") or "reassign").strip()
    target_domain = (args.get("target_domain") or "").strip() or None

    if not slug:
        return ToolResult(ok=False, output="", error="domain_slug 必填")
    if sources_action not in ("reassign", "delete", "keep"):
        return ToolResult(
            ok=False, output="",
            error=f"sources_action 必须是 reassign/delete/keep · 收到 {sources_action!r}",
        )

    r = remove_domain(slug, sources_action=sources_action, target_domain=target_domain)
    if not r.get("ok"):
        return ToolResult(ok=False, output="", error=r.get("error") or "remove_domain 失败")

    affected = r.get("affected_sources") or []
    actual_target = r.get("target_domain")
    lines = [
        f"# ✓ 已删除领域 · {slug}",
        f"  - 信源处理：**{sources_action}**",
    ]
    if sources_action == "reassign" and actual_target:
        tmeta = DOMAIN_META.get(actual_target) or {}
        lines.append(f"  - 归宿领域：{tmeta.get('icon', '·')} {tmeta.get('label', actual_target)} ({actual_target})")
    lines.append(f"  - 受影响信源数：{len(affected)}")
    if affected:
        if sources_action == "delete":
            lines.append(f"  - 这些源也一起删了：")
        elif sources_action == "reassign":
            tlabel = (DOMAIN_META.get(actual_target) or {}).get("label", actual_target)
            lines.append(f"  - 这些源已改归 「{tlabel}」：")
        else:
            lines.append(f"  - 这些源没动·domain 字段悬挂（不推荐）：")
        for s in affected[:15]:
            lines.append(f"    - `{s.get('id')}` · {s.get('name')}")
        if len(affected) > 15:
            lines.append(f"    - ...还有 {len(affected) - 15} 条")

    lines.append("")
    lines.append("下次刷新雷达就生效 · 也可以让 OPUS 立即 manage_info_source action=refresh")

    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="remove_domain",
    description=(
        "删雷达领域。默认 sources_action=reassign 把源归到 fallback。self-evolve 永远不能删。真要连源删须显式 delete。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "domain_slug": {
                "type": "string",
                "description": "要删的 domain slug · 比如用户自建的 'indie-game' 'pixel-art'",
                "minLength": 2,
                "maxLength": 40,
            },
            "sources_action": {
                "type": "string",
                "enum": ["reassign", "delete", "keep"],
                "description": (
                    "怎么处理这个 domain 下的源："
                    "reassign(默认·归 target_domain) / delete(连源一起删) / keep(留着但不归)"
                ),
            },
            "target_domain": {
                "type": "string",
                "description": (
                    "reassign 模式下·源要归到哪个 domain · 不传默认归到 self-evolve"
                ),
            },
        },
        "required": ["domain_slug"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
