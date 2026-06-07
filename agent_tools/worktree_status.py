"""
agent_tools/worktree_status.py
==============================

 · P2 · 2026-06-03 · 让 OPUS 在对话里"看见"自己的 git 工作区真相。

档位：AUTO
  纯读 · 跑几条只读 git · 不动任何东西 · 任何场景都安全。

为什么这个工具至关重要：
  今天 (2026-06-03) OPUS 合主干时撞了一次车 —— Cursor 开的 master worktree 占着
  master 分支 · OPUS 一 merge 就被 git 拒。 根因是 OPUS **看不见**"现在工作区什么
  状态、master 是不是被别人占着、有没有未提交改动会被卷走"。

  这个工具把"工作区 / 跨 agent git 真相 + 该怎么处理"端到 OPUS 面前。 典型时机:
    - 准备 merge_wish_to_master / 切分支 / checkpoint 之前 → 先看一眼安不安全
    - 用户 说"你怎么又把自己弄崩了" → 先自检现场再动手
    - 重启 / 自我升级前 → 确认没有半合状态、没被别的 worktree 占用

  底层报告由 workers/worktree_state.py 产出 (自包含 · 只依赖标准库 · daemon 崩了
  维修台和开源用户也能跑同一份逻辑)。
"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    return "查工作区 git 状态自检 (分支/脏改动/跨 agent 占用/该怎么处理)"


def _run(args: dict) -> ToolResult:
    try:
        from workers.worktree_state import working_tree_report, format_report
        rep = working_tree_report()
        return ToolResult(ok=True, output=rep.get("summary") or format_report(rep))
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"工作区自检出错: {type(e).__name__}: {e}")


SPEC = ToolSpec(
    name="worktree_status",
    description=(
        "查当前 git 工作区的真相 + 该怎么处理 ( · P2)。 返回: 当前分支及类型、"
        "相对 master 的领先/落后、未提交改动、有几个工作树 (检测 Cursor 等其它 agent 是否"
        "在并行改 / 是否占着 master)、遗留 stash、opus-last-good 回退点 · 外加大白话的"
        "处理建议。 在 merge 合主干 / 切分支 / checkpoint / 自我升级重启之前先调它自检 · "
        "避免'两个 agent 抢同一棵树'或'把别人的改动卷进自己 commit'这类坑。"
    ),
    tier=TIER_AUTO,
    input_schema={"type": "object", "properties": {}},
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
