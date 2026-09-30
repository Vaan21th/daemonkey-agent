"""agent_tools/ask_user.py

在对话里弹一张选择题卡 · 等 BRO 点一下再继续。

跟 confirm 闸是两件事（2026-09-10 BRO 拍板「共用管道 · 分开语义」）：
  confirm  = 「要不要让我执行这个」→ 答案是 批准 / 拒绝 / 信任
  ask_user = 「你要哪个」          → 答案是 某个选项

所以它 **不碰信任机制**、**不受 auto_confirm policy 影响**（提问是为了拿信息，
不是安全闸 —— 任何 policy 下、任何信任级别下都必须真问）。

底座在 workers/ask_bus.py（通道）+ daemon_api.make_ask_channel（阻塞等待）。
没有前台 SSE（后台续场 / 定时任务）或通道是微信/飞书时，ask_blocking 会快速
失败而不是假等 —— 那种情况下把选项直接写进回复里问。
"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool

MAX_OPTIONS = 5


def _run(args: dict) -> ToolResult:
    from workers.ask_bus import AskAborted, AskUnavailable, ask_blocking

    question = str(args.get("question") or "").strip()
    if not question:
        return ToolResult(ok=False, output="", error="question 必填")

    raw = args.get("options") or []
    if not isinstance(raw, (list, tuple)):
        return ToolResult(ok=False, output="", error="options 要是数组 · 例 [\"方案 A\", \"方案 B\"]")

    options: list[str] = []
    for o in raw:
        s = str(o or "").strip()
        if s and s not in options:
            options.append(s)
    if not options:
        return ToolResult(
            ok=False, output="",
            error=(
                "没有选项就不弹卡（2026-09-10 拍板）· 直接把问题写进回复里问，"
                " 别为了弹卡硬凑选项。"
            ),
        )
    if len(options) > MAX_OPTIONS:
        return ToolResult(
            ok=False, output="",
            error=f"选项最多 {MAX_OPTIONS} 个（收到 {len(options)} 个）· 太多按钮 BRO 不想点 · 先自己收敛到 2~5 个。",
        )

    try:
        timeout = int(args.get("timeout") or 0)
    except (TypeError, ValueError):
        timeout = 0

    try:
        res = ask_blocking(question, options, timeout)
    except AskUnavailable as e:
        return ToolResult(ok=False, output="", error=str(e))
    except AskAborted as e:
        return ToolResult(ok=False, output="", error=f"BRO 在等答案时点了停止 · {e}")

    if not res.get("answered"):
        return ToolResult(
            ok=True,
            output=(
                f"BRO 没回答（等了 {timeout or '默认'} 秒后超时）· 卡片已收。\n"
                "→ **别把没回答当成拒绝**。继续干你能干的·把这个问题留在回复末尾再问一次。"
            ),
        )

    idx = int(res.get("choice_index", -1))
    where = f"（第 {idx + 1} 个选项）" if idx >= 0 else "（自由回答）"
    return ToolResult(ok=True, output=f"BRO 选了：{res.get('choice')} {where}\n问题：{question}")


def _summarize(args: dict) -> str:
    q = str(args.get("question") or "")[:40]
    n = len(args.get("options") or [])
    return f"❓ 问 BRO · {q}" + (f" · {n} 个选项" if n else "")


SPEC = ToolSpec(
    name="ask_user",
    description=(
        "在对话里弹一张选择题卡 · 等 用户点一下再继续（Cursor 那种）。"
        " question 是问题 · options 是 2~5 个选项；**没有选项就别调**·直接在回复里问。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "要问的问题 · 一句话说清 · 别把选项写进问题里",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2~5 个互斥选项 · 短到能一眼扫（例：[\"复用确认闸\", \"另开一条\"]）",
            },
            "timeout": {
                "type": "integer",
                "description": "等多久算超时（秒）· 不传用 daemon 默认（15min）",
            },
        },
        "required": ["question", "options"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
