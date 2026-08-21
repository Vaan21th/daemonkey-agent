"""
agent_tools/kernel_takeover.py · 内核文件接管 (0.9.6)
====================================================

用户对某个内核文件说【这个归我管 · 官方升级别碰它】。 接管后 update_core 连
checkout 参数表都不会带上它 —— 物理上不可能被覆盖。

和"合并我的改动"(merge_user_override)的分工:
  接管 = 事前声明 · 一次生效长期有效 · 官方版根本不落盘
  合并 = 事后补救 · 已经被覆盖了 · 从备份里把自己的版本融回来

什么时候该接管 (OPUS 判断 · 主动建议用户):
  · 用户把某个文件改到面目全非 (最典型: static/chat.js 大改前端)
  · 用户明确说过"这块我按自己的口味来"
  · 升级报告连续几次都提示同一个文件冲突

什么时候【不该】接管:
  · 用户只是顺手改了两行 → 让官方继续管 · 靠"合并我的改动"更省事
  · 用户想改的是行为参数 → 优先找配置项 / 写 soul · 别把整个内核文件冻住
  · 升级机制自身的文件 → 工具会直接拒绝 (冻住它 = 以后所有修复都进不来)

NLP 触发示例:
  - "chat.js 我自己管 · 官方别动"        → action=add
  - "我接管了哪些文件"                    → action=list
  - "把 chat.js 交还给官方管"             → action=remove
"""
from __future__ import annotations

from . import TIER_AUTO, TIER_CONFIRM, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    act = (args or {}).get("action", "list")
    files = (args or {}).get("files") or []
    tail = ("· " + ", ".join(files[:3]) + ("…" if len(files) > 3 else "")) if files else ""
    if act == "add":
        return f"声明接管内核文件(官方升级不再覆盖) {tail}"
    if act == "remove":
        return f"取消接管 · 交还官方管 {tail}"
    return "看我接管了哪些内核文件"


def _classify(args: dict) -> str:
    return TIER_AUTO if (args.get("action") or "list").strip() == "list" else TIER_CONFIRM


def _fmt_status(st: dict) -> str:
    if not st["count"]:
        return ("你还没有接管任何内核文件 · 官方升级会照常同步全部白名单文件。\n"
                "想接管某个文件 → 对我说「<文件> 我自己管」。")
    lines = [f"你接管的内核文件 ({st['count']} 个) · 官方升级物理不碰它们:", ""]
    for f in st["files"]:
        note = (st.get("notes") or {}).get(f)
        lines.append(f"  = {f}" + (f"    ({note})" if note else ""))
    if st.get("stale"):
        lines.append("")
        lines.append("以下已不在当前内核白名单里 · 接管声明留着无害但也不起作用:")
        lines += [f"    ? {f}" for f in st["stale"]]
    lines.append("")
    lines.append(f"清单文件: {st['path']} (在 never_sync 里 · 升级不会覆盖这份声明)")
    lines.append("想交还官方管 → 「取消接管 <文件>」")
    return "\n".join(lines)


def _run(args: dict) -> ToolResult:
    from workers import kernel_takeover as kt

    action = (args.get("action") or "list").strip().lower()
    if action == "list":
        return ToolResult(ok=True, output=_fmt_status(kt.status()))

    files = args.get("files")
    if isinstance(files, str):
        files = [files]
    if not files or not isinstance(files, list):
        return ToolResult(ok=False, output="",
                          error="missing 'files' (要接管/取消接管的文件路径数组)")

    if action == "add":
        r = kt.add(files, note=(args.get("note") or "").strip())
        lines: list[str] = []
        if r["added"]:
            lines.append(f"✅ 已接管 {len(r['added'])} 个 · 官方升级从此不会覆盖它们:")
            lines += [f"    = {f}" for f in r["added"]]
        if r["already"]:
            lines.append("  (本来就已接管: " + ", ".join(r["already"]) + ")")
        if r["not_kernel"]:
            lines.append("")
            lines.append("以下不在内核白名单里 · 官方本来就不碰 · 接管声明已记下(将来白名单扩到它就生效):")
            lines += [f"    ? {f}" for f in r["not_kernel"]]
        if r["rejected"]:
            lines.append("")
            lines.append("❌ 以下【不能】接管:")
            for rj in r["rejected"]:
                lines.append(f"    {rj['file']} —— {rj['reason']}")
        if not lines:
            return ToolResult(ok=False, output="", error="没有有效路径")
        lines.append("")
        lines.append("代价要知道:官方以后对这些文件的修复(含 bug 修复)都不会自动进来。")
        lines.append("想看官方后来改了什么 → 「内核更新预览」· 想交还 → 「取消接管 <文件>」")
        return ToolResult(ok=True, output="\n".join(lines))

    if action == "remove":
        r = kt.remove(files)
        lines = []
        if r["removed"]:
            lines.append(f"已取消接管 {len(r['removed'])} 个 · 下次升级官方会照常同步它们:")
            lines += [f"    ~ {f}" for f in r["removed"]]
            lines.append("")
            lines.append("注意:如果你本地改过它们 · 下次升级会覆盖(但会先备份 · 可「合并我的改动」拿回)。")
        if r["missing"]:
            lines.append("  (本来就不在接管清单里: " + ", ".join(r["missing"]) + ")")
        return ToolResult(ok=True, output="\n".join(lines) or "接管清单没有变化")

    return ToolResult(ok=False, output="",
                      error=f"未知 action: {action} · 可选 list / add / remove")


SPEC = ToolSpec(
    name="kernel_takeover",
    description=(
        "内核文件接管 (0.9.6)。 用户说「这个文件我自己管 · 官方别碰」时用这个。"
        "接管后 update_core 物理上不会把官方版落进这些文件 (连 checkout 参数都不带它)。"
        "list=看接管了哪些 · add=声明接管 · remove=交还给官方管。"
        "与 merge_user_override 的分工: 接管是事前不让覆盖 · 合并是事后把被覆盖的改动融回来。"
        "升级机制自身的文件会被拒绝接管 (冻住它们=以后所有内核修复都进不来)。"
        "★ 用户想改前端界面时先别急着接管: 加面板/改配色/加维度/显示 token 消耗 这类"
        "写 static/user/user.js 或 user.css 就行 —— 那个目录在 never_sync 里·官方永不覆盖·"
        "且排在所有官方资源之后加载(API 是 window.Daemonkey · 示例见 static/user/EXAMPLES.js)。"
        "只有『要直接大改 chat.js 这种内核文件本身』才需要接管。"
    ),
    tier=TIER_CONFIRM,
    classify=_classify,
    input_schema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "add", "remove"],
                       "description": "list=看清单 / add=接管 / remove=取消接管"},
            "files": {"type": "array", "items": {"type": "string"},
                      "description": "add/remove 用 · 内核文件相对路径 (如 static/chat.js)"},
            "note": {"type": "string", "description": "add 用 · 为什么接管 (以后自己看得懂)"},
        },
        "required": ["action"],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
