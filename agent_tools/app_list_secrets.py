"""agent_tools/app_list_secrets.py
====================================

 K stage 2c++ · wish-96ee1b52 · 列一个 app 已存的 secret 字段名

**只列 name · 不返 value** —— 给 LLM 看是谁存了 · 不是看真值。

**调用时机**:
    - OPUS 写 system_prompt 前 · 想知道 用户 之前给过这个 app 哪些 KEY
    - OPUS 调 app_set_secret 后 · 立刻 verify 落到位
    - shell_exec 报"环境变量缺失" · 看是不是 secret 名打错了

**tier**:
    TIER_AUTO —— 不写不删 · 只读 metadata
"""

from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    app_id = args.get("app_id") or "(未指定)"
    return f"列 app `{app_id}` 已存的 secret 字段名 (不显示真值)"


def _run(args: dict) -> ToolResult:
    from workers import app_secrets

    app_id = (args.get("app_id") or "").strip()
    if not app_id:
        return ToolResult(ok=False, output="", error="app_id 必填")

    try:
        names = app_secrets.list_secrets(app_id)
    except ValueError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"list_secrets 失败: {e}")

    if not names:
        return ToolResult(ok=True, output=f"app `{app_id}` 暂无 secret · 用 app_set_secret 存一个")

    lines = [f"# app `{app_id}` 已存的 secret 字段:", ""]
    for n in names:
        lines.append(f"  - `{n}` · 引用方式: `${{secret:{app_id}:{n}}}`")
    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="app_list_secrets",
    description=(
        "列一个 app 已存的 secret 字段名 · 不显示真值 (LLM 安全)\n\n"
        "**用途**:\n"
        "  - 写 system_prompt 前 · 看 用户 之前给过哪些 KEY · 用对的 placeholder 名\n"
        "  - 调 app_set_secret 后 verify 落到位\n"
        "  - 调试 shell_exec 报『env 变量缺失』时 · 验 secret 名是不是打错"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "app_id": {
                "type": "string",
                "description": "目标 app 的 id · 例如 'app-35ed6c86'",
                "minLength": 4,
                "maxLength": 64,
            },
        },
        "required": ["app_id"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
