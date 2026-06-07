"""
agent_tools/monthly_review.py
=============================

 II · wish-bf190d9c · 月度复盘工具 (用户 6/23 第一次截止)

用户 2026-05-23 15:50 A1 决议:
  - 5/23 → 6/23 作为第一次月度 review · 不凑自然月
  - OPUS 6/15-6/20 起 B2 review 工具 (= 本工具)
  - 6/22 起草 review 草稿
  - 6/23 跟 用户 一起 review

档位: TIER_CONFIRM
  - draft mode 调 LLM 跑 4 块产物 (~$0.15-0.30) · 写入 data/reviews/<period_end>-draft.md
  - final mode 把 用户 批注合并 · 写入 -final.md (不自动改 OWNER-NOTEBOOK · 由 OPUS 之后手动调 update_bro_note 合并)

actions:
  - draft    · 起草新月度复盘 (默认)
  - final    · 用户 批注后归档 final 版
  - list     · 列出 data/reviews/ 下所有 review
  - load     · 读某一份已有 review markdown
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


ROOT = Path(__file__).resolve().parents[1]


def _summarize(args: dict) -> str:
    action = (args.get("action") or "draft").lower()
    if action == "draft":
        ps = args.get("period_start", "auto")
        pe = args.get("period_end", "today")
        return f"monthly_review · draft · {ps} → {pe}"
    if action == "final":
        return f"monthly_review · final · period_end={args.get('period_end', '?')}"
    if action == "list":
        return "monthly_review · list (列出所有 review)"
    if action == "load":
        return f"monthly_review · load · {args.get('filename', '?')}"
    if action == "reflow":
        pe = args.get("period_end")
        return f"monthly_review · reflow · {pe}" if pe else "monthly_review · reflow (列出待回流)"
    return f"monthly_review · {action}"


def _default_period_end() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _default_period_start(end: str) -> str:
    """默认: end 往前 30 天 (不凑自然月 · 跟 用户 A1 决议一致)"""
    try:
        end_dt = datetime.fromisoformat(end)
    except Exception:
        end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=30)
    return start_dt.strftime("%Y-%m-%d")


def _run(args: dict) -> ToolResult:
    from workers.review_generator import (
        generate_monthly_review,
        render_review_markdown,
        save_review_draft,
        save_review_final,
        list_reviews,
    )

    action = (args.get("action") or "draft").lower().strip()

    try:
        if action == "list":
            items = list_reviews()
            if not items:
                return ToolResult(
                    ok=True,
                    output="(data/reviews/ 还没有任何 review · 用 action=draft 起草第一份)",
                )
            lines = ["# 已有月度复盘", ""]
            for it in items:
                size_kb = it["size_bytes"] / 1024
                lines.append(
                    f"- [{it['status']}] **{it['period_end']}** · {it['filename']} · "
                    f"{size_kb:.1f}KB · {it['mtime']}"
                )
            return ToolResult(ok=True, output="\n".join(lines))

        if action == "load":
            filename = (args.get("filename") or "").strip()
            if not filename or "/" in filename or "\\" in filename or ".." in filename:
                return ToolResult(ok=False, output="", error="filename 必须是单文件名 · 不能含 / \\ ..")
            if not filename.endswith(".md"):
                return ToolResult(ok=False, output="", error="filename 必须以 .md 结尾")
            path = ROOT / "data" / "reviews" / filename
            if not path.exists():
                return ToolResult(ok=False, output="", error=f"review 不存在: {filename}")
            text = path.read_text(encoding="utf-8")
            return ToolResult(ok=True, output=text)

        if action == "draft":
            period_end = (args.get("period_end") or _default_period_end()).strip()
            period_start = (args.get("period_start") or _default_period_start(period_end)).strip()
            refresh_cap = bool(args.get("refresh_capability", True))

            review = generate_monthly_review(
                period_start=period_start,
                period_end=period_end,
                refresh_capability=refresh_cap,
            )
            path = save_review_draft(review)

            blocks = review["blocks"]
            bro = blocks["bro_notebook_changes"]
            summary = (
                f"# ✓ 月度复盘草稿已生成\n"
                f"\n"
                f"- 周期: **{review['period_start']} → {review['period_end']}**\n"
                f"- 落盘: `{path.relative_to(ROOT)}`\n"
                f"- OWNER-NOTEBOOK commit 数: {bro['commit_count']} · "
                f"行变化 +{bro['lines_added']}/-{bro['lines_removed']}\n"
                f"- 能力镜像: {'重新生成' if refresh_cap else '使用缓存'}\n"
                f"\n"
                f"## 4 块产物预览 (前 200 字)\n"
                f"\n"
                f"### 一 · 用户 画像变更\n"
                f"commit {bro['commit_count']} 个 · {bro.get('note', '')}\n"
                f"\n"
                f"### 二 · 能力镜像\n"
                f"```\n{blocks['capability_snapshot'][:200]}{'...' if len(blocks['capability_snapshot']) > 200 else ''}\n```\n"
                f"\n"
                f"### 三 · 工程里程碑\n"
                f"```\n{blocks['engineering_milestones'][:200]}{'...' if len(blocks['engineering_milestones']) > 200 else ''}\n```\n"
                f"\n"
                f"### 四 · 下月建议\n"
                f"```\n{blocks['next_month_advice'][:200]}{'...' if len(blocks['next_month_advice']) > 200 else ''}\n```\n"
                f"\n"
                f"---\n"
                f"\n"
                f"## 📍 用户 看 review 的两条路径 (reviews 不在 WebUI 报告库 · 不要找错地方)\n"
                f"\n"
                f"1. **直接打开文件**: `{path.relative_to(ROOT)}` (任何 .md 编辑器都行 · 推荐 Typora / VSCode)\n"
                f"2. **浏览器**: 用 daemon endpoint · `GET /reviews/preview/{path.name}` 拿 markdown · 或 `GET /reviews/file/{path.name}` 下载 (需 token)\n"
                f"\n"
                f"用户 边读边批注 (4 个批注区已留空) · 完成后跟 OPUS 说 『把批注合并归档』 · OPUS 调 "
                f"`monthly_review` action=final + annotations='...' 归档 final 版。"
            )
            return ToolResult(ok=True, output=summary)

        if action == "final":
            period_end = (args.get("period_end") or "").strip()
            if not period_end:
                return ToolResult(ok=False, output="", error="final mode 必须传 period_end")
            annotations = args.get("annotations") or ""

            draft_path = ROOT / "data" / "reviews" / f"{period_end}-draft.md"
            if not draft_path.exists():
                return ToolResult(
                    ok=False,
                    output="",
                    error=f"draft 不存在: {draft_path.name} · 先跑 action=draft",
                )
            draft_text = draft_path.read_text(encoding="utf-8")

            review_stub = {
                "period_start": "see-draft",
                "period_end": period_end,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "blocks": {
                    "bro_notebook_changes": {
                        "file": "see draft",
                        "period": "see draft",
                        "commit_count": 0,
                        "lines_added": 0,
                        "lines_removed": 0,
                        "commits": [],
                    },
                    "capability_snapshot": "(see draft)",
                    "engineering_milestones": "(see draft)",
                    "next_month_advice": "(see draft)",
                },
            }
            final_path = save_review_final(review_stub, annotations)
            (ROOT / "data" / "reviews" / f"{period_end}-final.md").write_text(
                draft_text.replace("status=draft", "status=final")
                + "\n\n---\n\n## 用户 实际批注 (final)\n\n"
                + (annotations or "_(空)_"),
                encoding="utf-8",
            )

            return ToolResult(
                ok=True,
                output=(
                    f"# ✓ Review final 已归档\n"
                    f"\n"
                    f"- 周期: {period_end}\n"
                    f"- final 文件: `{final_path.relative_to(ROOT)}`\n"
                    f"- 批注长度: {len(annotations)} 字\n"
                    f"\n"
                    f"⚠ **注意**: 当前 final 不自动改 soul/OWNER-NOTEBOOK.md (避免脚本 bug 损坏灵魂层) · "
                    f"OPUS 之后看 用户 批注 · 手动调 `update_bro_note` 工具把"
                    f"下月建议 / 月度 summary 段合并回 OWNER-NOTEBOOK。\n"
                    f"\n"
                    f"🔴 **对账闭环最后一棒**: 合并完 · 调 `monthly_review` action=reflow period_end={period_end} 盖回流戳 · "
                    f"否则这份批注会一直挂在闭环温度计『复盘批注→画像回流』里亮红 (= 没进画像)。"
                ),
            )

        if action == "reflow":
            from workers.review_generator import mark_reflowed, pending_reflows

            period_end = (args.get("period_end") or "").strip()
            if not period_end:
                pend = pending_reflows()
                if not pend:
                    return ToolResult(
                        ok=True,
                        output="✓ 没有待回流的 final · 所有复盘批注都已进 OWNER-NOTEBOOK。",
                    )
                lines = ["# 待回流的复盘 (批注还没进 OWNER-NOTEBOOK)", ""]
                for it in pend:
                    lines.append(f"- **{it['period_end']}** · {it['filename']} · {it['mtime']}")
                lines += [
                    "",
                    "## 回流步骤 (对账闭环最后一棒)",
                    "1. `monthly_review` action=load filename=<期>-final.md · 读 用户 批注",
                    "2. `update_bro_note` · 把『下月建议 / 月度 summary』合并进 soul/OWNER-NOTEBOOK.md",
                    "3. `monthly_review` action=reflow period_end=<期> · 盖回流戳 · 闭环温度计提醒消失",
                ]
                return ToolResult(ok=True, output="\n".join(lines))

            note = args.get("annotations") or ""
            path = mark_reflowed(period_end, note=note)
            return ToolResult(
                ok=True,
                output=(
                    f"# ✓ 回流戳已盖\n"
                    f"\n"
                    f"- 文件: `{path.relative_to(ROOT)}`\n"
                    f"- 含义: {period_end} 的 用户 批注已合并进 OWNER-NOTEBOOK · 闭环温度计『复盘批注→画像回流』提醒会消失\n"
                    f"\n"
                    f"⚠ 只在你**真的**调过 `update_bro_note` 合并后才盖戳 · 别空盖。"
                ),
            )

        return ToolResult(
            ok=False,
            output="",
            error=f"未知 action: {action} · 可选: draft / final / list / load / reflow",
        )

    except Exception as e:
        return ToolResult(
            ok=False,
            output="",
            error=f"monthly_review 内部错误: {e}",
        )


SPEC = ToolSpec(
    name="monthly_review",
    description=(
        " II · 月度复盘工具 (wish-bf190d9c · 用户 5/23 A1 决议 6/23 第一次截止)\n\n"
        "**调用时机** (OPUS 主动判断):\n"
        "  - 每月固定周期 (5/23 → 6/23 → 7/23 ...) · 不凑自然月\n"
        "  - 每周期前 1-2 天 用户 提『复盘』/『月报』/『我这个月做了啥』 时\n"
        "  - 6/22 / 7/22 这类前夜 OPUS 主动起草\n"
        "  - 用户 在 WebUI 报告库点 『月度复盘』 入口 (后续 wish-149eab3f 加)\n\n"
        "**actions**:\n"
        "  - draft · 起草新月度复盘 (生成 4 块 + 落 data/reviews/<period_end>-draft.md · ~$0.20)\n"
        "  - final · 用户 批注后归档 final + 提示 OPUS 手动合并回 OWNER-NOTEBOOK\n"
        "  - reflow · 对账闭环最后一棒 · 不传 period_end=列出所有待回流 final · 传了=盖回流戳\n"
        "             (先 update_bro_note 合并批注 · 再 reflow 盖戳 · 否则闭环温度计一直亮红)\n"
        "  - list · 列出所有已有 review\n"
        "  - load · 读某一份 review markdown\n\n"
        "**4 块产物**:\n"
        "  1. OWNER-NOTEBOOK 30 天 git log 变更摘要\n"
        "  2. 用户 能力镜像切片 (调 capability_mirror)\n"
        "  3. CAPTAINS-LOG 工程里程碑 LLM 提炼\n"
        "  4. 下月能力建议 (LLM 综合 1+2+3 · 6 种掘金形态 ≥ 2)\n\n"
        "**⚠ 沉淀位说明 · 别误导 用户**:\n"
        "  - reviews 落 `data/reviews/<period>-{draft,final}.md` · **不在 docs 报告库** (报告库是 data/docs)\n"
        "  - WebUI 当前**没有 reviews 卡片入口** (wish-149eab3f phase B 才会做)\n"
        "  - 告诉 用户 看 review 时 · 给具体路径 `data/reviews/<filename>` 或浏览器开 `http://127.0.0.1:7860/reviews/preview/<filename>?token=$tok`\n"
        "  - **不要**说 『进 WebUI 报告库就能看到』 / 『在报告库找』 · 那是错的\n\n"
        "**注意**: draft 跑一次约 5-15s ($0.10-0.30) · CONFIRM 是因为它会调 LLM 多次。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["draft", "final", "list", "load", "reflow"],
                "description": "draft=起草 / final=归档 / list=列表 / load=读单份 / reflow=盖回流戳(对账闭环最后一棒)",
            },
            "period_start": {
                "type": "string",
                "description": "ISO date e.g. 2026-05-23 · draft 时默认 period_end 往前 30 天",
            },
            "period_end": {
                "type": "string",
                "description": "ISO date e.g. 2026-06-23 · 默认今天 · final/load 时必须明确",
            },
            "filename": {
                "type": "string",
                "description": "load 时用 · 单文件名 (如 2026-06-23-draft.md) · 不含路径",
            },
            "annotations": {
                "type": "string",
                "description": "final 时用 · 用户 批注的 markdown 文本",
            },
            "refresh_capability": {
                "type": "boolean",
                "description": "draft 时用 · True=重新跑能力镜像 (耗时 +5s) · False=用缓存。 默认 True",
            },
        },
        "required": ["action"],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
