"""
agent_tools/safe_merge.py
=========================

wish-e19edb92 三件套之③ · 2026-07-29 · 安全合主干工具。

为什么造它:
  用户 最怕的两件事之一: "合主干出问题直接崩"。 今天之前 Daemonkey 合主干只有两条路:
    - wish_update(status=live) 走内部 merge_wish_to_master (有闸但绑死 wish 流程)
    - shell_exec git merge (裸奔·没闸·冲突留半合状态·合完没人验跑不跑得起来)
  本工具把 merge_wish_to_master 的全套保护暴露成 Daemonkey 显式可调的第一选择:
    ① 幂等前置闸 (已合过就直接放行·不重复 checkout)
    ② 分支安全门 (前缀/junk 文件检查)
    ③ 分支先吃最新 master · 冲突在分支上暴露 · 自动 abort 报告 · master 不被污染
    ④ 上线闸 (verify: 建 app + 140 路由 smoke + 前端 JS 哨兵) · 过不了不合
    ⑤ 任何一步失败自动回到干净 master · 不留半合状态
  一句话: 要么全绿落 commit · 要么当没发生过。

档位: CONFIRM —— 合主干是有副作用的写操作 · 用户 点头一次才跑。
"""
from __future__ import annotations

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    br = (args or {}).get("branch", "?")
    return f"安全合主干: {br} → master (试合/冲突即退/上线闸/失败自动回滚)"


def _run(args: dict) -> ToolResult:
    branch = str((args or {}).get("branch") or "").strip()
    allow_override = bool((args or {}).get("allow_override", False))
    if not branch:
        return ToolResult(ok=False, output="", error="branch 必填 · 要合回 master 的分支名")
    if branch == "master":
        return ToolResult(ok=False, output="", error="branch 不能是 master 自己")

    try:
        from workers.worktree_state import working_tree_report
        pre = working_tree_report()
        pre_line = f"合并前工作区: 分支 {pre.get('branch') or '?'} · 未提交改动 {pre.get('dirty_count', '?')} 个"
    except Exception:
        pre_line = "合并前工作区: (自检不可用 · 继续)"

    try:
        from workers.git_ops import merge_wish_to_master
        res = merge_wish_to_master(branch, expected_wish_id=None, allow_override=allow_override)
    except Exception as e:
        return ToolResult(ok=False, output="",
                          error=f"merge 执行出错 (master 未被改动): {type(e).__name__}: {e}")

    note = (res.get("note") or "").strip()
    if res.get("ok"):
        head = [
            f"✅ 安全合主干完成: `{branch}` → master",
            f"  {pre_line}",
            f"  结果: {note}",
        ]
        if res.get("branch_deleted"):
            head.append(f"  分支 `{branch}` 已清理 (合一个删一个·不堆积)")
        head.append("")
        head.append("三证核对:")
        head.append("  ① commit 在 master · 上面 sha 即证")
        head.append("  ② 上线闸已过 (建 app + 路由 smoke + 前端 JS 哨兵 · 不过不会合进来)")
        head.append("  ③ 冲突已在分支侧预演 · 有冲突根本不会走到这步")
        head.append("")
        head.append("提示: daemon 侧 .py 有改动的话 · 还需 request_restart 才装得上。")
        return ToolResult(ok=True, output="\n".join(head))

    # 失败/被拦: merge_wish_to_master 内部已 abort / 回干净 master · 这里把原因讲清
    blocked = bool(res.get("blocked"))
    icon = "🛑" if blocked else "❌"
    body = [
        f"{icon} 合主干未执行 · master 保持原样 · 不留半合状态",
        f"  {pre_line}",
        f"  原因: {note}",
    ]
    if not blocked:
        body.append("")
        body.append("排查建议: 先看分支是否存在/拼写 (git branch -a) · 再 worktree_status 看工作区。")
    return ToolResult(ok=False, output="\n".join(body), error=note[:300])


SPEC = ToolSpec(
    name="safe_merge",
    description=(
        "把指定分支【安全】合回 master —— wish-e19edb92 三件套之③ · 治『合主干出问题直接崩』。"
        "BRO 说『把 X 合主干 / 合并 X 分支』时·这是第一选择 (别用 shell_exec git merge 裸奔)。"
        "五道保护: ①已合过幂等放行 ②分支安全门 (防错分支/junk 文件) ③分支先吃最新 master·"
        "冲突在分支上预演·自动 abort 报告冲突清单·master 不被污染 ④上线闸 (建 app + 路由 smoke + "
        "前端 JS 哨兵)·过不了不合 ⑤任何失败自动回到干净 master·不留半合状态。"
        "一句话: 要么全绿落 commit·要么当没发生过。 allow_override=true 可跳过安全门和上线闸 "
        "(仅 用户 明确知道自己在干嘛时用)。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "branch": {
                "type": "string",
                "description": "要合回 master 的分支名 (如 wish-xxx/yyy)",
                "minLength": 1,
            },
            "allow_override": {
                "type": "boolean",
                "description": "跳过安全门+上线闸强合 · 默认 false · 仅 用户 明确知情时用",
            },
        },
        "required": ["branch"],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
