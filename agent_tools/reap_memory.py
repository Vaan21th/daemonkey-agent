"""agent_tools/reap_memory.py
============================

记忆新陈代谢 · 谁该退役的建议器（**只读 · 不动手**）

什么时候调：格子满了写不进 / BRO 问「有什么该清的」/ 想做一轮记忆体检。

判据只有一份（`workers/memory_reaper.retire_score`），跟将来的写入自救共用一把尺 ——
短命格（state 30 天 / stories 90 天）到点提示，**critical 永不提示**。

**本工具不删任何东西。** 要清哪条：画像走 `update_owner_note` 的 replace/delete，
其余走界面删除。

档位：AUTO · 纯只读
"""
from __future__ import annotations

from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool

_ROOT = Path(__file__).resolve().parent.parent


def _summarize(args: dict) -> str:
    return "reap_memory · 扫记忆退役建议"


def _run(args: dict) -> ToolResult:
    from workers.memory_reaper import render_suggestions, scan

    text = None
    for fn in ("OWNER-NOTEBOOK.md", "BRO-NOTEBOOK.md"):
        p = _ROOT / "soul" / fn
        if p.exists():
            text = p.read_text(encoding="utf-8")
            break
    if text is None:
        return ToolResult(False, "", "画像文件不存在（soul/ 下没有 OWNER-NOTEBOOK.md / BRO-NOTEBOOK.md）")

    result = scan(text)
    n = sum(len(v) for v in result.values())
    if n == 0:
        return ToolResult(True, "✓ 记忆体检：没有建议退役的条目 —— 各格都还新鲜。", "")
    return ToolResult(
        True,
        f"✓ 记忆体检：{n} 条建议（分 {len(result)} 格）—— 只给建议，不自动删\n\n"
        + render_suggestions(result),
        "",
    )


SPEC = ToolSpec(
    name="reap_memory",
    description=(
        "看记忆里谁该退役（格子满了写不进 / BRO 问「有什么该清的」时调）。"
        "只出建议不动手 —— 短命格(state 30天/stories 90天)到点提示 · critical 永不提示。"
        "要真清走 update_owner_note 或界面删除。"
    ),
    tier=TIER_AUTO,
    input_schema={"type": "object", "properties": {}, "required": []},
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
