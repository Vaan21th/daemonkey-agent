"""agent_tools/app_delete_secret.py
=====================================

 K stage 2c++ · wish-96ee1b52 · 删一个 app 的 secret

**调用时机**:
    - 用户 让 OPUS 把某个 KEY 旋转/失效掉
    - OPUS 调 app_set_secret 时打错 name · 想清理重存
    - app 不再使用 · 用户 让 OPUS 整体清掉

**tier**:
    TIER_CONFIRM —— 删 KEY 是敏感操作 · 删错了 用户 要重新去 API 平台拿 · 麻烦
"""

from __future__ import annotations

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    app_id = args.get("app_id") or "(未指定)"
    name = args.get("secret_name") or "(未指定)"
    return f"删 app `{app_id}` 的 secret · 字段 `{name}`"


def _run(args: dict) -> ToolResult:
    from workers import app_secrets

    app_id = (args.get("app_id") or "").strip()
    secret_name = (args.get("secret_name") or "").strip()
    if not app_id:
        return ToolResult(ok=False, output="", error="app_id 必填")
    if not secret_name:
        return ToolResult(ok=False, output="", error="secret_name 必填")

    try:
        deleted = app_secrets.delete_secret(app_id, secret_name)
    except ValueError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"delete_secret 失败: {e}")

    if deleted:
        return ToolResult(ok=True, output=f"# ✓ secret 已删 · `{app_id}` :: `{secret_name}`")
    return ToolResult(
        ok=True,
        output=f"# - secret 不存在 · `{app_id}` :: `{secret_name}` · 本来就没有 · 不算错",
    )


SPEC = ToolSpec(
    name="app_delete_secret",
    description=(
        "删一个 app 的 secret · 删错要重新去 API 平台拿 KEY · 谨慎调用\n\n"
        "**用途**:\n"
        "  - KEY 旋转 / 失效 / app 清理\n"
        "  - app_set_secret 打错 name 想清理重存"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "app_id": {
                "type": "string",
                "description": "目标 app 的 id · 例如 'app-35ed6c86'",
                "minLength": 4,
                "maxLength": 64,
            },
            "secret_name": {
                "type": "string",
                "description": "字段名 · 例如 'api_key'",
                "minLength": 1,
                "maxLength": 64,
            },
        },
        "required": ["app_id", "secret_name"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
