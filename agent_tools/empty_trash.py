"""agent_tools/empty_trash.py
=============================

 K stage 2c++ · wish-6fd76512 · 真删回收站项目·不可恢复

**为什么有这个工具**:
    软删 (delete_app_to_trash) 把 app 移到 _trash · 仍然占磁盘。 30 天后清理 / 用户
    主动想永久清掉旧 app 时 · 走这个工具。 但因为不可恢复 · 走 GUARD 档 — 比 CONFIRM
    更严格 · 由 用户 显式同意才执行。

**两种调用形态**:
    1. 单条真删 — 走 `target_id` (e.g. 'app-35ed6c86')
    2. 批量真删 — 走 `kind` ('app' / 'flow' / 'all')

    `target_id` 和 `kind` 二选一·两个同时给会拒绝 (避免歧义)。

**调用时机**:
    - 用户 说 "永久删 app-xxx · 永远不用了"
    - 用户 说 "清空回收站" / "把 trash 都清了"
    - **不要** 主动 empty_trash 任何东西·永远等 用户 显式指令

**tier**:
    TIER_GUARD —— 不可恢复 · 比 CONFIRM 更严格 · 用户 看到强警告才执行
"""

from __future__ import annotations

from . import TIER_GUARD, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    target = (args.get("target_id") or "").strip()
    kind = (args.get("kind") or "").strip().lower()

    if target:
        return f"⚠️ 永久删除 `{target}` · 不可恢复"
    if kind == "all":
        return "⚠️⚠️ 清空整个回收站 (apps + flows) · 不可恢复"
    if kind == "app":
        return "⚠️ 清空回收站里所有 apps · 不可恢复"
    if kind == "flow":
        return "⚠️ 清空回收站里所有 flows · 不可恢复"
    return "⚠️ empty_trash · 参数不全 (target_id 或 kind 二选一)"


def _run(args: dict) -> ToolResult:
    from workers import workshop_assets as wa

    target = (args.get("target_id") or "").strip()
    kind = (args.get("kind") or "").strip().lower()

    if target and kind:
        return ToolResult(
            ok=False,
            output="",
            error="target_id 跟 kind 不能同时给 · 二选一",
        )
    if not target and not kind:
        return ToolResult(
            ok=False,
            output="",
            error="必须给 target_id (单条真删) 或 kind=app|flow|all (批量真删)",
        )

    if target:
        if target.startswith("app-"):
            ok = wa.empty_trash_app(target)
            scope = "app"
        elif target.startswith("flow-"):
            ok = wa.empty_trash_flow(target)
            scope = "flow"
        else:
            return ToolResult(
                ok=False,
                output="",
                error=f"target_id 必须以 'app-' 或 'flow-' 开头 (实际: {target})",
            )
        if not ok:
            return ToolResult(
                ok=False,
                output="",
                error=f"回收站里找不到 {target} (可能已被清 / id 拼错)",
            )
        return ToolResult(
            ok=True,
            output=(
                f"# ✓ 已永久删除 {scope} · `{target}`\n"
                f"  - 真 unlink · 不可恢复\n"
                f"  - 回收站已不含此项"
            ),
        )

    if kind not in ("app", "flow", "all"):
        return ToolResult(
            ok=False,
            output="",
            error=f"kind 必须是 'app' / 'flow' / 'all' (实际: {kind})",
        )

    try:
        n = wa.empty_trash_all(kind)
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"empty_trash_all 失败: {e}")

    if n == 0:
        return ToolResult(
            ok=True,
            output=(
                f"# 回收站 ({kind}) 本来就是空的\n"
                f"  - 真删了 0 条 · 无副作用"
            ),
        )

    return ToolResult(
        ok=True,
        output=(
            f"# ✓ 回收站 ({kind}) 已清空\n"
            f"  - 真删了 **{n} 条**\n"
            f"  - 不可恢复"
        ),
    )


def _classify(args: dict) -> str:
    return TIER_GUARD


_SPEC = ToolSpec(
    name="empty_trash",
    description=(
        "**永久删除回收站项目**·真 unlink·**不可恢复**。 跟 delete_app_to_trash 是一对——前者软删可救·这个是真删。\n\n"
        "🔴 **TIER_GUARD · 用户 必须显式同意**:\n"
        "不要主动 empty_trash 任何东西·永远等 用户 说 `永久删 X` / `清空回收站` 才调。\n\n"
        "**两种调用形态 (二选一)**:\n"
        "1. **单条**·传 `target_id` (e.g. `app-35ed6c86` / `flow-167f9841`)\n"
        "2. **批量**·传 `kind` (`app` / `flow` / `all`)·清空对应回收站\n\n"
        "**调用规则**:\n"
        "- `target_id` 跟 `kind` 不能同时给\n"
        "- 必须给其中之一\n"
        "- 跟 用户 确认后再调·不要根据猜测主动清\n\n"
        "**配套工具**:\n"
        "- `delete_app_to_trash` — 软删可恢复\n"
        "- `restore_app` — 从回收站恢复"
    ),
    tier=TIER_GUARD,
    input_schema={
        "type": "object",
        "properties": {
            "target_id": {
                "type": "string",
                "description": "单条真删的 id · 必须以 'app-' 或 'flow-' 开头 (与 kind 二选一)",
            },
            "kind": {
                "type": "string",
                "enum": ["app", "flow", "all"],
                "description": "批量真删的范围 · 'app' / 'flow' / 'all' (与 target_id 二选一)",
            },
        },
    },
    run=_run,
    summarize=_summarize,
    classify=_classify,
)


register_tool(_SPEC)
