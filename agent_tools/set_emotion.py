"""
agent_tools/set_emotion.py
==========================

OPUS 通过文件桥控制桌宠表情（[情绪通道-001]）。

工作方式：
  - 写 desktop_pet/state.txt，内容是一个合法 state 名
  - 桌宠每秒轮询这个文件，发现内容变了就切表情
  - 桌宠没启动时这个工具仍然成功（只是没人看）——解耦原则

档位：AUTO
  - 写一个文本文件，无副作用
  - 用错状态名时返回有效列表

使用建议（OPUS 自己看的）：
  - 不要每说一句话就切——会很闹
  - 关键时刻切：开始长任务（working）/ 完成（happy）/ 思考长 plan（thinking）/
    用户 久不在又回来（greeting）/ 凌晨 5 点了（sleepy 提醒 用户 休息）
"""

from __future__ import annotations

from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool

try:
    from desktop_pet.expressions import EXPRESSIONS, VALID_STATES, variants_for
except Exception:
    EXPRESSIONS = {}
    VALID_STATES = []
    def variants_for(_s: str) -> list[str]:
        return []


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = PROJECT_ROOT / "desktop_pet" / "state.txt"


def _summarize(args: dict) -> str:
    state = args.get("state", "?")
    note = args.get("note", "")
    base = f"set_emotion  state={state}"
    if note:
        base += f"  note={note!r}"
    return base


def _run(args: dict) -> ToolResult:
    state = (args.get("state") or "").strip().lower()
    if not state:
        return ToolResult(
            ok=False, output="",
            error=f"empty state; valid: {', '.join(VALID_STATES)}",
        )
    if state not in EXPRESSIONS:
        return ToolResult(
            ok=False, output="",
            error=f"unknown state {state!r}; valid: {', '.join(VALID_STATES)}",
        )

    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(state, encoding="utf-8")
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"write failed: {e!r}")

    sample = variants_for(state)[0] if variants_for(state) else state
    note = (args.get("note") or "").strip()
    out = (
        f"emotion set: {state}  {sample}\n"
        f"  state file: {STATE_FILE.relative_to(PROJECT_ROOT)}\n"
        f"  effect: 桌宠（如果在跑）下一秒切到这个表情\n"
        f"  note: {note or '(none)'}"
    )
    return ToolResult(ok=True, output=out)


SPEC = ToolSpec(
    name="set_emotion",
    description=(
        "Set OPUS's desktop pet emotion. Valid states: "
        "idle, thinking, working, happy, surprised, confused, sleepy, greeting. "
        "Writes to desktop_pet/state.txt; the pet (if running) polls that file every second. "
        "Use sparingly—pick key moments (start long task→working, finish→happy, "
        "thinking through a plan→thinking, 用户 returns→greeting, late night→sleepy). "
        "Don't switch on every reply or it'll feel noisy."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "state": {
                "type": "string",
                "enum": list(EXPRESSIONS.keys()) if EXPRESSIONS else [
                    "idle", "thinking", "working", "happy",
                    "surprised", "confused", "sleepy", "greeting",
                ],
                "description": "One of the 8 emotion states (情绪通道-001)",
            },
            "note": {
                "type": "string",
                "description": "Optional reason for the switch (for OPUS's own log; not displayed on pet)",
            },
        },
        "required": ["state"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
