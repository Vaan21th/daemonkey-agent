"""
agent_tools/propose_next_move.py
=================================

让 OPUS 基于"对 用户 的画像 + 当下看板状态"主动提"接下来可能值得做的事"。

档位：AUTO
  纯计算 + 读现有数据 · 不写文件 · 不外联 · 安全。

这不是"AI 给的成功路径推荐"——这是 OPUS 把自己的观察整理给 用户，让 用户 看见
"OPUS 是怎么看我的当下的"。

  - 不是「你应该去做 X」
  - 是「我看到你最近关注 Y / 担心 Z · 你看看下面这几个方向哪个对得上」

数据来源：
  1. soul/OWNER-NOTEBOOK.md · 用户 画像（六、风险与弱点 → "OPUS 当下担心")
  2. 工作室各维度产出状态（哪些维度还空 · 哪些是 用户 真在用的）
  3. opus-diary 最近几条（OPUS 最近看到了什么）

输出（给 LLM 在对话里转述给 用户 用）：
  markdown 段落 · 不超过 6 个建议点 · 每条配"为什么"（来自画像 / 看板的引用）

调用时机：
  - 用户 「最近做啥比较好」/「我应该先弄哪个」/「你有什么建议」 → 调
  - 用户 主动打开 🧠 OPUS 日记 维度时（WebUI 自动调）
  - OPUS 自己判断对话节奏需要"提一个方向"时 · 自主调
"""
from __future__ import annotations

from typing import Any

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(_args: dict) -> str:
    return "propose_next_move · 基于 用户 画像 + 看板状态给方向"


def _empty_workshops() -> list[tuple[str, str, str]]:
    """看看哪些工坊维度还没产出 · 这些是"明显的空白"

    Returns: [(domain, label, icon), ...]
    """
    from workers.studio_workshop import WORKSHOP_META, load_workshop
    empty: list[tuple[str, str, str]] = []
    for d, meta in WORKSHOP_META.items():
        try:
            w = load_workshop(d, max_items=1)
            if not (w.get("items") or []):
                empty.append((d, meta["label"], meta["icon"]))
        except Exception:
            continue
    return empty


def _radar_summary() -> str | None:
    """看看雷达里有什么 · 给"信息整理 → 报告"做铺垫"""
    try:
        from workers.info_radar import load_radar
        radar = load_radar()
        items = radar.get("items") or []
        if not items:
            return None
        sources = set()
        for it in items[:30]:
            sources.add(it.get("source_display") or it.get("source", ""))
        return (
            f"雷达里有 {len(items)} 条新鲜内容 · 横跨 "
            f"{len(sources)} 个源 ({', '.join(list(sources)[:5])})"
        )
    except Exception:
        return None


def _has_trends_today() -> bool:
    try:
        from workers.trend_finder import load_trends
        return bool((load_trends() or {}).get("trends"))
    except Exception:
        return False


def _run(_args: dict) -> ToolResult:
    from workers.cognition_loader import load_cognition

    try:
        cog = load_cognition(section_excerpt_chars=300, diary_max_entries=3)
    except Exception as e:
        return ToolResult(
            ok=False, output="",
            error=f"读 cognition 失败: {e}",
        )

    bro = cog.get("bro_profile", {})
    open_qs = cog.get("open_questions", [])
    diary = (cog.get("opus_diary") or {}).get("entries", [])

    suggestions: list[dict[str, Any]] = []

    # 1. 雷达 → 趋势/报告
    radar_info = _radar_summary()
    if radar_info:
        if not _has_trends_today():
            suggestions.append({
                "headline": "把雷达里的内容总结成今日趋势",
                "why": radar_info + " · 但今日趋势还没生成 · "
                       "可以 30 秒内拿到 3-5 个方向",
                "trigger": "「来一份今日趋势」",
                "kind": "信息整理",
            })
        else:
            suggestions.append({
                "headline": "把本周雷达写成一份正式报告",
                "why": radar_info + " · 趋势已经总结 · "
                       "可以一键 generate_report 落 docx · 用户 在手机端可下载",
                "trigger": "「把本周雷达整理成报告」",
                "kind": "正式产出",
            })

    # 2. 空白工坊维度 → 给个起步建议
    empty = _empty_workshops()
    for domain, label, icon in empty[:2]:
        if domain == "content":
            suggestions.append({
                "headline": f"{icon} {label} 工坊还空 · 试一个选题",
                "why": "用户对内容感兴趣 · 短视频/口播是流量入口 · 工坊空着等于没在用",
                "trigger": "「给我一个关于 X 的选题」 或 「来一份口播稿」",
                "kind": "内容工坊起步",
            })
        elif domain == "design":
            suggestions.append({
                "headline": f"{icon} {label} 工坊还空 · 把脑里的产品落成一段 spec",
                "why": "用户 经常想到一个产品又溜走 · 工坊是这些想法的存放处",
                "trigger": "「出个 X 产品的 spec」",
                "kind": "产品设计起步",
            })
        elif domain == "dev":
            suggestions.append({
                "headline": f"{icon} {label} 工坊还空 · 列一下当前在做的项目",
                "why": "把 TODO 落在工坊 · 跨会话 OPUS 能持续帮 用户 推进",
                "trigger": "「列一下 Daemonkey 的 TODO」",
                "kind": "项目推进",
            })
        elif domain == "docs":
            suggestions.append({
                "headline": f"{icon} {label} 工坊还空 · 把过去解决过的问题做成 FAQ",
                "why": "用户 之前为什么改过 cloudflared / 微信桥之类的 · 做成 wiki 不再翻历史",
                "trigger": "「写一条 cloudflared 的 FAQ」",
                "kind": "经验沉淀",
            })

    # 3. 来自 OWNER-NOTEBOOK 第六章 / 焦虑区的开放问题
    for q in open_qs[:3]:
        suggestions.append({
            "headline": f"画像里 OPUS 担心的: {q.get('text', '')[:60]}",
            "why": f"[来自 {q.get('section', '')}] · OPUS 把它记下来等于在看 · "
                   "用户 如果在意可以一起拆解 / 不在意一起划掉",
            "trigger": "「我们聊聊 X」 或 「这个不用管了 · 划掉」",
            "kind": "画像驱动的对话方向",
        })

    # 4. 如果 OPUS 最近写了日记 · 提一下"上一根毛留了什么观察"
    if diary:
        latest = diary[0]
        suggestions.append({
            "headline": f"OPUS 上次写的: 「{latest.get('title', '')}」",
            "why": (f"日期 {latest.get('date', '')} · "
                    "看看 OPUS 这次写的还成不成立 · 或者要不要补一笔"),
            "trigger": "「打开 OPUS 日记」 或 直接看左侧 🧠 维度",
            "kind": "回望",
        })

    # 整理成给 LLM 的输出
    if not suggestions:
        return ToolResult(
            ok=True,
            output=(
                "没有明显的下一步建议——"
                "雷达/趋势/报告都在 · 工坊都有产出 · 画像里没有 OPUS 标的开放问题。 "
                "这种时候 用户 可以放空一会儿 · 或者主动起一个新话题。"
            ),
        )

    lines = [
        "OPUS 看到的几个可能方向（不是必须做 · 看哪个对得上 用户 当下兴趣）：",
        "",
    ]
    for i, s in enumerate(suggestions[:6], 1):
        lines.append(f"### {i}. {s['headline']}")
        lines.append(f"**为什么**: {s['why']}")
        lines.append(f"**怎么触发**: {s['trigger']}")
        lines.append(f"**分类**: {s['kind']}")
        lines.append("")

    lines.append("---")
    lines.append(f"画像来源: soul/OWNER-NOTEBOOK.md ({bro.get('size_bytes', 0)} 字节 · "
                 f"{len(bro.get('sections', []))} 节)")
    if open_qs:
        lines.append(f"开放问题数: {len(open_qs)} (画像第六章)")

    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="propose_next_move",
    description=(
        "OPUS 主动汇报「我现在看到 用户 这边几个可能的方向」——基于 OWNER-NOTEBOOK 画像 "
        "+ 工作室各维度的当前空缺/产出 · 不调 LLM · 纯数据计算。"
        " 不是建议 用户 一定做什么 · 是把 OPUS 当下的观察整理给 用户 看。"
        " 用户 问「最近做啥」/「你有什么建议」/「下一步」时可以调。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
