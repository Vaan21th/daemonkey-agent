"""agent_tools/restore_app.py
=============================

 K stage 2c++ · wish-6fd76512 · 从回收站恢复一个工坊 app

**为什么有这个工具**:
    用户 说 "我刚才让你删的那个 app-xxx · 其实还要用 · 帮我恢复" — daemon OPUS
    必须有工具能恢复。 不然只能让 用户 自己 F5 工坊去翻回收站点恢复按钮 · UX 差。

**调用时机**:
    - 用户 说 "恢复 app-xxx" / "刚才删的那个 app 找回来"
    - OPUS 自己软删后立刻想撤回 (理论上不应该 · 但留个口子)

**tier**:
    TIER_CONFIRM —— 恢复也是结构性操作 · 让 用户 知道 OPUS 在动 active 列表
    虽然语义比删轻 · 但仍然走 ✓ 流程 · 保守

**返回**:
    成功时返回提示 + 提醒 用户 F5 工坊看新增的卡片
"""

from __future__ import annotations

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    aid = (args.get("app_id") or "").strip() or "(未指定)"
    return f"从回收站恢复 app `{aid}` · 移回 active 列表"


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

    trash_list = wa.list_trash_apps()
    target = next((it for it in trash_list if it["id"] == aid), None)
    if not target:
        return ToolResult(
            ok=False,
            output="",
            error=f"回收站里没有: {aid} (可能已永久删 / id 拼错)",
        )

    if wa.load_app(aid) is not None:
        return ToolResult(
            ok=False,
            output="",
            error=(
                f"active 列表里已经有 {aid} · 不能恢复覆盖。 "
                f"如果想用回收站版本 · 先 delete_app_to_trash 当前 active 那个 · "
                f"或者直接 empty_trash 掉回收站这个旧版"
            ),
        )

    try:
        ok = wa.restore_app(aid)
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"restore_app 失败: {e}")

    if not ok:
        return ToolResult(
            ok=False,
            output="",
            error=f"恢复失败: {aid} (磁盘错误 / 文件已变)",
        )

    lines = [
        f"# ✓ app 已恢复 · `{aid}`",
        f"  - 名称: {target.get('name') or '(未命名)'}",
        f"  - 落点: data/workshop/apps/{aid}.json (回到 active 列表)",
        f"  - 回收站里已清掉此项",
        "",
        "**下一步**:",
        "  - 用户 F5 工坊 → 应用列表会看到这张卡片回来了",
        "  - 如果要再次删 · 调 delete_app_to_trash",
    ]
    return ToolResult(ok=True, output="\n".join(lines))


_SPEC = ToolSpec(
    name="restore_app",
    description=(
        "**从回收站恢复一个工坊 app**·移回 `data/workshop/apps/`·去掉 deleted_at 字段。\n\n"
        "🔴 **关键约束**:\n"
        "- 如果 active 列表已经有同 id 的 app·**会拒绝恢复**·避免覆盖。 这种情况下 OPUS 应该提示 用户 二选一 (留 active 那个 / 还是用回收站旧版)。\n\n"
        "**调用时机**:\n"
        "用户 说 `恢复 app-xxxx` / `刚删的那个找回来` / `我后悔了 · 把 X 恢复` 时·调这个工具。\n\n"
        "**调用规则**:\n"
        "- `app_id` 必填·必须以 `app-` 开头\n"
        "- TIER_CONFIRM·用户 看到摘要按 ✓ 才执行\n\n"
        "**配套工具**:\n"
        "- `delete_app_to_trash` — 软删到回收站\n"
        "- 走 daemon GET `/workshop/trash` 看回收站现状 (UI 已有 Tab)"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "app_id": {
                "type": "string",
                "description": "要恢复的 app id · 必须以 'app-' 开头 (e.g. 'app-35ed6c86')",
            },
        },
        "required": ["app_id"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(_SPEC)
