"""
agent_tools/read_dashboard.py
==============================

让 OPUS 在对话里"看见"工作室看板的实际数据。

档位：AUTO
  纯读 · 不动数据 · 不外联 · 任何场景都安全。

为什么这个工具至关重要：
   用户 说："这些聚合了的信息，我是否在对话中直接提到一些什么他就可以
  进行一些动作，例如写报告/写文稿/出原型？"

  这个需求的底层缺口是 OPUS 在对话里**不知道当前看板有什么**——用户 说"把第三条
  雷达写成报告"时，OPUS 不知道第三条是啥，只能瞎猜。

  解决方案有两种：
    (a) 系统提示词里塞当前看板摘要——每次对话开头都塞 → token 浪费 + 信息过时；
    (b) **加一个 read_dashboard 工具，OPUS 需要时主动调** → 按需 · 即时 · 不污染上下文。

  选 (b)。这也是为什么这个工具 tier=AUTO——OPUS 想读就读 · 不打扰 用户。

NLP 触发场景：
  - 用户 "把第 3 条做成报告"      → read_dashboard(domain=radar, head=5) → 找第 3 条
  - 用户 "今天的趋势怎么样"       → read_dashboard(domain=trends)
  - 用户 "上周生成的报告还在吗"   → read_dashboard(domain=reports, head=20)
  - 用户 "我们工坊里有什么草稿"   → read_dashboard(domain=content/design/dev/docs)
  - 用户 "你最近怎么看我"         → read_dashboard(domain=cognition)
  - 用户 "整个工作室什么状态"     → read_dashboard(domain=all) → 调 cockpit aggregate

输出格式：精简 markdown 给 LLM 读 · 不是 JSON · LLM 直接拿来引用 用户。
"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


_DOMAIN_HANDLERS: dict[str, str] = {
    "radar": "信息雷达",
    "trends": "今日趋势",
    "reports": "报告库",
    "cognition": "OPUS 日记 / 用户 画像",
    "content": "内容制作",
    "design": "产品设计",
    "dev": "产品开发",
    "docs": "文档撰写",
    "wishlist": "OPUS 心愿单 · 自演化任务清单",
    "opportunities": "掘金机会 · 已评估的赚钱点",
    "feasibility": "可行性分析 · SWOT + Go/No-Go",
    "outcomes": "执行反馈 · 落地结果",
    "all": "工作室全部维度概览",
}


def _summarize(args: dict) -> str:
    domain = (args.get("domain") or "?").strip()
    head = args.get("head") or 5
    return f"read_dashboard {domain} (head={head})"


def _format_radar(data: dict, head: int) -> str:
    items = (data.get("items") or [])[:head]
    if not items:
        return "（雷达暂时没数据 · 可以让 OPUS 调 refresh_radar 重新抓）"
    lines = [f"📡 信息雷达 · 取前 {len(items)} 条（共 {len(data.get('items') or [])} 条）"]
    for i, it in enumerate(items, 1):
        title = it.get("title", "(无标题)")
        src = it.get("source_display") or it.get("source", "")
        url = it.get("url", "")
        published = it.get("published_at", "")
        sum_ = (it.get("summary") or "").strip().replace("\n", " ")
        lines.append(f"\n{i}. {title}")
        lines.append(f"   源: {src} · 时间: {published}")
        if url:
            lines.append(f"   链接: {url}")
        if sum_:
            lines.append(f"   摘要: {sum_[:200]}")
    return "\n".join(lines)


def _format_trends(data: dict, head: int) -> str:
    trends = (data.get("trends") or [])[:head]
    if not trends:
        return "（今日趋势还没生成 · 可以让 OPUS 调 trend_finder 现总结）"
    lines = [f"🌊 今日趋势 · {len(trends)} 个"]
    for i, t in enumerate(trends, 1):
        title = t.get("title", "")
        summary = (t.get("summary") or "").strip().replace("\n", " ")
        lines.append(f"\n{i}. {title}")
        if summary:
            lines.append(f"   {summary[:240]}")
    return "\n".join(lines)


def _format_reports(data: dict, head: int) -> str:
    items = (data.get("items") or [])[:head]
    if not items:
        return "（报告库为空 · 用 generate_report 生成第一份）"
    lines = [f"📑 报告库 · 取前 {len(items)} 份（共 {data.get('count', len(items))} 份）"]
    for i, it in enumerate(items, 1):
        lines.append(
            f"\n{i}. {it.get('name')}"
            f"\n   大小: {it.get('size_kb')} KB · 时间: {it.get('created_at')}"
        )
    return "\n".join(lines)


def _format_cognition(data: dict, head: int) -> str:
    bro = data.get("bro_profile", {})
    diary = data.get("opus_diary", {})
    open_qs = data.get("open_questions", [])

    lines = ["🧠 OPUS 日记 + 用户 画像"]
    lines.append(f"\nBRO 画像 (soul/OWNER-NOTEBOOK.md · {bro.get('size_bytes', 0)} 字节)")
    for sec in (bro.get("sections") or [])[:head]:
        lines.append(f"  · {sec.get('heading')}")

    entries = diary.get("entries") or []
    if entries:
        lines.append(f"\nOPUS 最近日记 ({len(entries)} 条)")
        for e in entries[:head]:
            lines.append(f"  · {e.get('date')} · {e.get('title')}")

    if open_qs:
        lines.append(f"\nOPUS 当下关注的开放问题 ({len(open_qs)} 条)")
        for q in open_qs[:head]:
            lines.append(f"  · [{q.get('section', '')[:14]}] {q.get('text', '')}")

    return "\n".join(lines)


def _format_wishlist(data: dict, head: int) -> str:
    """ · OPUS 心愿单 · 让 OPUS 调出自己写的心愿继续干活."""
    wishes = (data.get("wishes") or [])[:head]
    if not wishes:
        return "（心愿单空 · OPUS 还没写过心愿）"
    total = data.get("count") or len(wishes)
    lines = [f"💝 OPUS 心愿单 · 取前 {len(wishes)} 条（共 {total} 条）"]
    for i, w in enumerate(wishes, 1):
        wid = w.get("id", "?")
        title = w.get("title", "(无标题)")
        status = w.get("status", "?")
        phase = w.get("daemon_phase") or ""
        path = w.get("integration_path") or ""
        prio = "⭐" * (w.get("priority") or 3)
        lines.append(f"\n{i}. [{wid}] {title}")
        lines.append(f"   状态: {status} · 路径: {path or '(未定)'} · phase: {phase or '(未启动)'} · 优先级: {prio}")
        why = (w.get("why") or "").strip().replace("\n", " ")
        if why:
            lines.append(f"   why: {why[:200]}")
        plan = (w.get("implementation_plan") or "").strip()
        if plan:
            lines.append(f"   plan 已存 ({len(plan)} 字符)")
        sketch = (w.get("design_sketch") or "").strip().replace("\n", " ")
        if sketch and not plan:
            lines.append(f"   design_sketch: {sketch[:200]}")
        log = (w.get("implementation_log") or "").strip()
        if log:
            lines.append(f"   log 末尾: {log.splitlines()[-1][:150] if log.splitlines() else ''}")
        diff = (w.get("diff_summary") or "").strip()
        if diff:
            lines.append(f"   diff 摘要: {diff[:200]}")
        branch = (w.get("dev_branch") or "").strip()
        if branch:
            lines.append(f"   git 分支: {branch}")
        #  · wish reflection 回流 (Hermes '从经验改进' 那一环): 完成后写的复盘心得
        # 摆进 NLP read · OPUS 翻自己心愿单时看得到上次干这事学到了啥·不重复踩坑
        refl = (w.get("reflection") or "").strip().replace("\n", " ")
        if refl:
            lines.append(f"   💭 复盘: {refl[:220]}")
        #  测谎仪 · 只在 status 和 git 对不上时报警:
        #   live 但没合 = 谎报上线 (最危险)·active/review 没合 = 正常 (活儿在分支上)
        if w.get("git_merge_state") == "unmerged":
            n = w.get("git_unmerged_commits", 0)
            if status == "live":
                lines.append(
                    f"   🔴 测谎仪: status=live 但 git 没合进 master ({n} 提交躺在分支上)! "
                    f"= 谎报上线·一回退就丢。 应重新走 live 触发真 merge·或把 status 改回 review")
            else:
                lines.append(f"   ℹ️ git: {n} 个提交在分支上没合 (active/review 阶段正常·验收后标 live 会自动合)")
    return "\n".join(lines)


def _format_opportunities(data: dict, head: int) -> str:
    items = (data.get("opportunities") or data.get("items") or [])[:head]
    if not items:
        return "（掘金机会暂时没数据 · OPUS 可以调 mine_opportunities 重新生成）"
    lines = [f"💎 掘金机会 · 取前 {len(items)} 条"]
    for i, o in enumerate(items, 1):
        title = o.get("title", "(无标题)")
        fit = o.get("fit", "?")
        cost = o.get("cost_effort", "?")
        upside = o.get("upside", "?")
        recommend = o.get("recommend", "?")
        lines.append(f"\n{i}. {title}")
        lines.append(f"   fit: {fit} · cost: {cost} · upside: {upside} · 推荐: {recommend}")
        why = (o.get("fit_reason") or "").strip().replace("\n", " ")
        if why:
            lines.append(f"   匹配 用户 的理由: {why[:200]}")
    return "\n".join(lines)


def _format_feasibility(data: dict, head: int) -> str:
    items = (data.get("analyses") or data.get("items") or [])[:head]
    if not items:
        return "（可行性分析没数据 · OPUS 可以调 analyze_feasibility）"
    lines = [f"📊 可行性分析 · 取前 {len(items)} 条"]
    for i, a in enumerate(items, 1):
        title = a.get("title") or a.get("opp_title", "(无标题)")
        score = a.get("score", "?")
        decision = a.get("decision", "?")
        lines.append(f"\n{i}. {title}")
        lines.append(f"   score: {score}/100 · 决定: {decision}")
        risks = a.get("risks") or []
        if risks:
            lines.append(f"   风险: {', '.join((r.get('title') if isinstance(r, dict) else str(r))[:30] for r in risks[:3])}")
    return "\n".join(lines)


def _format_outcomes(data: dict, head: int) -> str:
    items = (data.get("outcomes") or data.get("items") or [])[:head]
    if not items:
        return "（执行反馈还没数据 · 用户 干完事用 record_outcome 落一条）"
    lines = [f"🏁 执行反馈 · 取前 {len(items)} 条"]
    for i, o in enumerate(items, 1):
        title = o.get("title") or o.get("opp_title", "(无标题)")
        status = o.get("status", "?")
        lines.append(f"\n{i}. {title}")
        lines.append(f"   状态: {status}")
        decision_reason = (o.get("decision_reason") or "").strip().replace("\n", " ")
        if decision_reason:
            lines.append(f"   决定: {decision_reason[:200]}")
        actuals = o.get("actuals") or {}
        if actuals:
            lines.append(f"   实际: 时间 {actuals.get('time_spent', '?')} / 收益 {actuals.get('revenue', '?')}")
        lessons = (o.get("lessons_learned") or "").strip().replace("\n", " ")
        if lessons:
            lines.append(f"   复盘: {lessons[:200]}")
    return "\n".join(lines)


def _format_workshop(data: dict, head: int, icon: str, label: str) -> str:
    items = (data.get("items") or [])[:head]
    if not items:
        return f"（{icon} {label} 工坊空 · 跟 OPUS 说做一份就有了 · 引导: {data.get('empty_hint', '')}）"
    lines = [f"{icon} {label} · {len(items)} 份产出"]
    for i, it in enumerate(items, 1):
        kind = it.get("kind") or ""
        kind_str = f" · {kind}" if kind else ""
        lines.append(f"\n{i}. {it.get('title')}{kind_str}")
        lines.append(f"   {it.get('created_at')} · {it.get('path')}")
        excerpt = (it.get("excerpt") or "").strip().replace("\n", " ")
        if excerpt:
            lines.append(f"   {excerpt[:160]}")
    return "\n".join(lines)


def _format_all(head: int) -> str:
    from workers.info_radar import load_radar
    from workers.trend_finder import load_trends
    from workers.cognition_loader import load_cognition
    from workers.studio_workshop import WORKSHOP_META, load_workshop

    parts: list[str] = ["工作室全维度概览"]

    try:
        radar = load_radar()
        items = (radar.get("items") or [])[:3]
        parts.append(f"\n📡 雷达 ({len(radar.get('items') or [])} 条)")
        for i, it in enumerate(items, 1):
            parts.append(f"  {i}. {it.get('title')} ({it.get('source_display') or it.get('source')})")
    except Exception as e:
        parts.append(f"\n📡 雷达 — 读取失败: {e}")

    try:
        trends = load_trends()
        ts = (trends.get("trends") or [])[:3]
        parts.append(f"\n🌊 趋势 ({len(trends.get('trends') or [])} 个)")
        for i, t in enumerate(ts, 1):
            parts.append(f"  {i}. {t.get('title')}")
    except Exception as e:
        parts.append(f"\n🌊 趋势 — 读取失败: {e}")

    try:
        cog = load_cognition(section_excerpt_chars=60, diary_max_entries=3)
        parts.append(f"\n🧠 OPUS 日记 ({len(cog['opus_diary'].get('entries') or [])} 条 / "
                     f"画像 {len(cog['bro_profile'].get('sections') or [])} 节)")
    except Exception as e:
        parts.append(f"\n🧠 OPUS 日记 — 读取失败: {e}")

    for d in ("content", "design", "dev", "docs"):
        try:
            w = load_workshop(d, max_items=3)
            meta = WORKSHOP_META[d]
            parts.append(f"\n{meta['icon']} {meta['label']} ({len(w.get('items') or [])} 份)")
            for it in (w.get("items") or [])[:3]:
                kind = it.get("kind") or ""
                kind_str = f" · {kind}" if kind else ""
                parts.append(f"  - {it.get('title')}{kind_str}")
        except Exception as e:
            parts.append(f"\n{d} — 读取失败: {e}")

    return "\n".join(parts)


def _run(args: dict) -> ToolResult:
    domain = (args.get("domain") or "").strip().lower()
    head = args.get("head") or 5
    try:
        head = max(1, min(int(head), 30))
    except (TypeError, ValueError):
        head = 5

    if domain not in _DOMAIN_HANDLERS:
        return ToolResult(
            ok=False, output="",
            error=(
                f"未知 domain: {domain!r}。 "
                f"可选: {', '.join(_DOMAIN_HANDLERS.keys())}"
            ),
        )

    try:
        if domain == "all":
            return ToolResult(ok=True, output=_format_all(head))

        if domain == "radar":
            from workers.info_radar import load_radar
            return ToolResult(ok=True, output=_format_radar(load_radar(), head))

        if domain == "trends":
            from workers.trend_finder import load_trends
            return ToolResult(ok=True, output=_format_trends(load_trends(), head))

        if domain == "reports":
            from daemon_api import build_app  # noqa: F401 (force same import path)
            # 直接走 listing helper · 不依赖 HTTP
            from pathlib import Path
            ROOT = Path(__file__).resolve().parent.parent
            reports_dir = ROOT / "data" / "reports"
            items = []
            if reports_dir.exists():
                for p in sorted(reports_dir.glob("*.docx"),
                                key=lambda p: p.stat().st_mtime, reverse=True)[:head]:
                    stat = p.stat()
                    items.append({
                        "name": p.name,
                        "size_kb": round(stat.st_size / 1024, 1),
                        "created_at": __import__("time").strftime(
                            "%Y-%m-%dT%H:%M:%S",
                            __import__("time").localtime(stat.st_mtime),
                        ),
                    })
            return ToolResult(
                ok=True,
                output=_format_reports({"items": items, "count": len(items)}, head),
            )

        if domain == "cognition":
            from workers.cognition_loader import load_cognition
            return ToolResult(
                ok=True,
                output=_format_cognition(load_cognition(diary_max_entries=head), head),
            )

        if domain in ("content", "design", "dev", "docs"):
            from workers.studio_workshop import WORKSHOP_META, load_workshop
            data = load_workshop(domain, max_items=head)
            meta = WORKSHOP_META[domain]
            return ToolResult(
                ok=True,
                output=_format_workshop(data, head, meta["icon"], meta["label"]),
            )

        if domain == "wishlist":
            from workers.wishlist import list_wishes
            all_w = list_wishes()  # list[dict] · 已按 priority 排
            wishes = all_w[:head]
            #  · 给 OPUS 也标 git 真实合并状态 (从 git 算·不只信 status 标签)
            try:
                from workers.git_ops import audit_wishes_merge_state
                audit = audit_wishes_merge_state(wishes)
                for w in wishes:
                    st = audit.get(w.get("id"), {})
                    w["git_merge_state"] = st.get("state", "none")
                    w["git_unmerged_commits"] = st.get("ahead", 0)
            except Exception:
                pass
            return ToolResult(
                ok=True,
                output=_format_wishlist({"wishes": wishes, "count": len(all_w)}, head),
            )

        if domain == "opportunities":
            from workers.opportunity_miner import load_opportunities
            data = load_opportunities() or {}
            return ToolResult(
                ok=True,
                output=_format_opportunities(data, head),
            )

        if domain == "feasibility":
            from workers.feasibility_analyzer import list_feasibility
            data = list_feasibility(max_items=head)
            items = (data or {}).get("items") or (data or {}).get("analyses") or []
            return ToolResult(
                ok=True,
                output=_format_feasibility({"analyses": items}, head),
            )

        if domain == "outcomes":
            from workers.outcomes import list_outcomes
            data = list_outcomes(max_items=head)
            items = (data or {}).get("outcomes") or (data or {}).get("items") or []
            return ToolResult(
                ok=True,
                output=_format_outcomes({"outcomes": items}, head),
            )

    except Exception as e:
        return ToolResult(
            ok=False, output="",
            error=f"读 {domain} 时出错: {type(e).__name__}: {e}",
        )

    return ToolResult(ok=False, output="", error=f"未实现的 domain: {domain}")


SPEC = ToolSpec(
    name="read_dashboard",
    description=(
        "读 OPUS 工作室任意一维的实际数据 · 让 OPUS 在对话里能引用「第 3 条雷达」/"
        "「这周第一份报告」/「上次写的口播稿」这样的具体内容。"
        " 任何时候 用户 指向看板内容 · OPUS 都应该先读这个工具拿到事实再操作。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "enum": list(_DOMAIN_HANDLERS.keys()),
                "description": (
                    "维度: radar (信息雷达) / trends (今日趋势) / reports (报告库) / "
                    "cognition (OPUS 日记 + 用户 画像) / content / design / dev / docs / "
                    "all (全维度概览 · 每维 3 条)"
                ),
            },
            "head": {
                "type": "integer",
                "description": "返回前 N 条 · 默认 5 · 上限 30",
            },
        },
        "required": ["domain"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
