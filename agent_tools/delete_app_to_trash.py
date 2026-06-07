"""agent_tools/delete_app_to_trash.py
=====================================

 K stage 2c++ · wish-6fd76512 · 软删一个工坊 app

**为什么有这个工具**:
    workshop_assets.delete_app 之前是物理 unlink · 删错就没了。 用户 要清理工坊里
    旧 app (app-35ed6c86 GPT Image / app-b08ffda6 SOVITS 等) 时不敢动手 · 怕
    误删之后要重新跟 daemon OPUS 装一遍 · 费 token 又烦。

    这个工具让 OPUS 把 app 移到 _trash · 加 deleted_at 字段 · 可以走 restore_app
    恢复回来。 真要永久删 · 走 empty_trash 工具 (TIER_GUARD)。

**调用时机**:
    - 用户 说 "把 app-xxxx 删了" / "清理一下旧的 GPT Image app"
    - 第一刀就调这个工具 · **不要绕弯先调 shell_exec 跑 rm** · 因为那样就跳过 trash 了

**tier**:
    TIER_CONFIRM —— 删 app 是结构性操作 · 用户 看到摘要后 ✓ 才执行
    虽然能 restore · 但 daemon OPUS 不应该自己随手删别人造的 app

**返回**:
    成功时返回提示文本 + 提醒 用户 "如果删错了 · 可以让我调 restore_app 恢复"
"""

from __future__ import annotations

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    aid = (args.get("app_id") or "").strip() or "(未指定)"
    return f"软删 app `{aid}` · 移到回收站 (可走 restore_app 恢复)"


def _run(args: dict) -> ToolResult:
    from workers import workshop_assets as wa

    aid = (args.get("app_id") or "").strip()
    if not aid:
        return ToolResult(ok=False, output="", error="app_id 必填")
    if not aid.startswith("app-"):
        return ToolResult(
            ok=False,
            output="",
            error=f"app_id 必须以 'app-' 开头 (实际: {aid})",
        )

    existing = wa.load_app(aid)
    if not existing:
        return ToolResult(
            ok=False,
            output="",
            error=f"找不到 app: {aid} (可能已被删 / 已在回收站 / id 拼错)",
        )

    try:
        ok = wa.delete_app(aid)
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"delete_app 失败: {e}")

    if not ok:
        return ToolResult(
            ok=False,
            output="",
            error=f"移到回收站失败: {aid} (磁盘错误 / 权限问题)",
        )

    lines = [
        f"# ✓ app 已移到回收站 · `{aid}`",
        f"  - 名称: {existing.get('name') or '(未命名)'}",
        f"  - 落点: data/workshop/apps/_trash/{aid}.json (加了 deleted_at 字段)",
        f"  - 工坊 active 列表已不含此 app · 用户 F5 看不到了",
        "",
        "**如果删错了**:",
        "  - 调 restore_app · 30 天内可恢复",
        "  - 调 list_trash_apps · 看回收站现状",
        "",
        "**永久删 (不可恢复)**:",
        "  - 调 empty_trash (TIER_GUARD) · 真 unlink · 然后再也找不回",
    ]
    return ToolResult(ok=True, output="\n".join(lines))


_SPEC = ToolSpec(
    name="delete_app_to_trash",
    description=(
        "**软删一个工坊 app**·移到 `data/workshop/apps/_trash/`·加 deleted_at 字段·**可走 restore_app 恢复**。\n\n"
        "🔴 **关键调用次序**:\n"
        "用户 说 `把 app-xxxx 删了` / `清理一下旧的 GPT Image / SOVITS app` 时·**第一刀就是这个工具**·**不要** 自己写 shell_exec 跑 rm/Remove-Item — 那样会跳过回收站语义。\n\n"
        "**调用规则**:\n"
        "- `app_id` 必填·必须以 `app-` 开头 (e.g. `app-35ed6c86`)\n"
        "- TIER_CONFIRM·用户 看到摘要按 ✓ 才执行\n"
        "- 删完返回会提示 用户 如何恢复 / 永久删\n\n"
        "**反面教材**:\n"
        "用户 让 daemon OPUS 删 app-xxx · OPUS 调 shell_exec 跑 `Remove-Item data/workshop/apps/app-xxx.json` → 跳过回收站 · 删了就找不回。 这种调用方式是工艺事故。\n\n"
        "**配套工具**:\n"
        "- `restore_app` — 从回收站恢复\n"
        "- `empty_trash` — 真删 · 不可恢复 (TIER_GUARD)"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "app_id": {
                "type": "string",
                "description": "要软删的 app id · 必须以 'app-' 开头 (e.g. 'app-35ed6c86')",
            },
        },
        "required": ["app_id"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(_SPEC)
