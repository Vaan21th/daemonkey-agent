"""
agent_tools/mirror_capability.py
================================

 · 市场能力镜像工具

让 OPUS 跑一次"用户 行为痕迹 → 市场能力画像"的分析·
输出 bro_capability_snapshot.md · 用户 在 WebUI 报告库可见。

档位：AUTO
  全只读分析 · ~5s ~$0.05 · 不影响外部系统

调用时机（OPUS 自己判断）：
  - 用户「帮我照照镜子」「我现在能力怎么样」「我擅长什么」
  - 做完一次掘金机会挖掘后 → 让镜像同步刷新
  - 每月 review 前（用户 定了 6/23 第一次月度 review）
  - 用户 在 WebUI 打开 📊 能力镜像卡片而快照是空的

actions:
  - generate · 跑 LLM 生成新快照 (~5s)
  - load · 只读已有快照（不调 LLM）
"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    action = (args.get("action") or "generate").lower()
    return f"mirror_capability · {action}"


def _run(args: dict) -> ToolResult:
    from workers.capability_mirror import generate_snapshot, load_snapshot

    action = (args.get("action") or "generate").lower().strip()

    try:
        if action == "load":
            data = load_snapshot()
            snap = data.get("snapshot", "")
            if not snap:
                note = data.get("note", "还没跑过能力镜像")
                return ToolResult(
                    ok=True,
                    output=f"{note}\n\n用 action=generate 跑一次。",
                )
            return ToolResult(ok=True, output=snap)

        if action == "generate":
            result = generate_snapshot()
            error = result.get("error")
            if error:
                return ToolResult(ok=False, output="", error=f"能力镜像失败: {error}")

            snap = result.get("snapshot", "")
            if not snap:
                return ToolResult(
                    ok=False, output="", error="LLM 返回了空内容"
                )

            elapsed_s = (result.get("elapsed_ms") or 0) / 1000
            usage = result.get("usage") or {}
            path = result.get("snapshot_path", "?")

            output = (
                f"# 用户 市场能力镜像\n"
                f"生成于: {result.get('generated_at','?')} · "
                f"模型 {result.get('model','?')} · "
                f"耗时 {elapsed_s:.1f}s\n"
                f"tokens in={usage.get('input_tokens',0)} "
                f"out={usage.get('output_tokens',0)}\n"
                f"落盘: {path}\n\n"
                f"{snap}"
            )
            return ToolResult(ok=True, output=output)

        return ToolResult(
            ok=False,
            output="",
            error=f"未知 action: {action} · 可选: generate / load",
        )

    except Exception as e:
        return ToolResult(
            ok=False,
            output="",
            error=f"mirror_capability 内部错误: {e}",
        )


SPEC = ToolSpec(
    name="mirror_capability",
    description=(
        " · 市场能力镜像 · 从 用户 的行为痕迹（收藏/反馈/闭环/机会）中"
        "提炼 用户 的市场能力画像 · 反照给 用户 看清自己。\n\n"
        "**调用时机** (OPUS 主动判断):\n"
        "  - 用户 问'照镜子'/'我现在能力怎么样'/'我擅长什么'\n"
        "  - 掘金机会挖掘完成后 → 让镜像同步刷新\n"
        "  - 每月 review 前（6/23 第一次）\n"
        "  - 能力镜像卡片空时\n\n"
        "**actions**:\n"
        "  - generate · 调 LLM 跑一次完整分析 (~5s ~$0.05) · 落 bro_capability_snapshot.md\n"
        "  - load · 只读已有快照 · 不调 LLM\n\n"
        "**输出**：四区段 markdown 快照 · 显性能力/隐性能力/排斥模式/成长轨迹 + 镜子话"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["generate", "load"],
                "description": "generate=跑 LLM 生成新快照 / load=读已有",
            },
        },
        "required": ["action"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
