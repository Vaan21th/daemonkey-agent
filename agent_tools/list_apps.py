"""
agent_tools/list_apps.py
========================

修补 · 让 AI 看见工坊里有什么应用 (沉淀闭环 v2 · 修用户看到的"0 个 flow / 1 个 app"假象)

为什么需要这个工具 (背景):
  之前 AI 想"看工坊里有什么 app" · 只能用 glob_files 找 data/workshop/apps/*.json
  但 .gitignore 把 apps/*.json 排除了 (apps/flows 不进 git 是有意的 · 见 .gitignore 第 36/39 行)
  → rg --files 默认尊重 .gitignore · AI 看到的是"1 个 app" · 实际磁盘有 12 个
  → 用户一脸懵: "旧的应用怎么就都不能用了?"

正确做法:
  app/flow 是 daemon 内部状态 · 不该走文件系统看 · 走 workshop_assets 元数据 API
  这个工具就是 list_apps() 的 thin wrapper · 输出对 LLM 友好的速查清单

AUTO tier · 纯读 · 不动任何状态
"""

from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    q = args.get("query")
    extras = []
    if q:
        extras.append(f"q={q!r}")
    if args.get("shipped_only"):
        extras.append("shipped_only")
    if args.get("detailed"):
        extras.append("detailed")
    suffix = " · ".join(extras)
    return f"list_apps · 列工坊所有应用" + (f" ({suffix})" if suffix else "")


def _strip_icon(icon: str) -> str:
    """图标可能是 emoji 或 <i class="ri-xxx"> · LLM 看 emoji 即可 · HTML tag 去掉"""
    if not icon:
        return ""
    if icon.startswith("<"):
        return "□"  # placeholder · 不让 HTML 进 LLM 视野
    return icon


def _run(args: dict) -> ToolResult:
    try:
        from workers.workshop_assets import list_apps
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"workshop_assets import failed: {e!r}")

    query = (args.get("query") or "").strip().lower()
    shipped_only = bool(args.get("shipped_only"))
    detailed = bool(args.get("detailed"))
    limit = int(args.get("limit") or 50)

    try:
        apps = list_apps(max_items=200)
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"list_apps failed: {e!r}")

    # 修补 (用户反馈) · 检测坏 json (UTF-16/mojibake) · workshop_assets.list_apps
    # 静默 skip 不可读文件 · 但 AI 应该看到"有这个 id 但文件坏了" · 不然以为应用丢了
    import pathlib
    apps_dir = pathlib.Path("data/workshop/apps")
    corrupted: list[str] = []
    if apps_dir.exists():
        on_disk_ids = {p.stem for p in apps_dir.glob("app-*.json") if p.is_file()}
        ok_ids = {a.get("id") for a in apps}
        for aid in sorted(on_disk_ids - ok_ids):
            corrupted.append(aid)

    # 过滤
    if shipped_only:
        apps = [a for a in apps if a.get("shipped")]
    if query:
        def _hit(a: dict) -> bool:
            blob = " ".join([
                a.get("id") or "", a.get("name") or "", a.get("description") or "",
            ]).lower()
            return query in blob
        apps = [a for a in apps if _hit(a)]

    if not apps:
        hint = f" (筛选: query={query!r})" if query else ""
        return ToolResult(ok=True, output=f"(工坊里目前没有匹配的应用{hint})")

    total = len(apps)
    truncated = total > limit
    apps = apps[:limit]

    lines = [f"# 工坊 · 共 {total} 个应用" + (f" (显示前 {limit} 个)" if truncated else "")]
    for a in apps:
        aid = a.get("id") or "?"
        name = a.get("name") or "(未命名)"
        icon = _strip_icon(a.get("icon") or "")
        shipped = "★" if a.get("shipped") else ""
        runs = a.get("runs") or 0
        version = a.get("version") or 1
        desc = (a.get("description") or "").strip().replace("\n", " ")
        if len(desc) > 80:
            desc = desc[:78] + "…"

        head = f"- {shipped}{icon} **{name}** · `{aid}` · v{version} · 跑过 {runs} 次"
        lines.append(head)
        if desc:
            lines.append(f"  · {desc}")

        if detailed:
            tools = a.get("tools") or []
            slots = a.get("asset_slots") or []
            outputs = a.get("output_schema") or []
            ui_form = a.get("ui_form_schema") or []
            model_hint = a.get("model_hint") or ""
            exec_kind = a.get("exec_kind") or "agentic"

            extras = []
            extras.append(f"exec={exec_kind}")
            if model_hint:
                extras.append(f"model_hint={model_hint}")
            if tools:
                extras.append(f"tools=[{', '.join(tools[:6])}{'…' if len(tools) > 6 else ''}]")
            if ui_form:
                form_names = [s.get("name", "?") for s in ui_form[:5]]
                extras.append(f"inputs=[{', '.join(form_names)}{'…' if len(ui_form) > 5 else ''}]")
            if outputs:
                out_names = [s.get("name", "?") for s in outputs[:5]]
                extras.append(f"outputs=[{', '.join(out_names)}{'…' if len(outputs) > 5 else ''}]")
            if slots:
                slot_names = [s.get("name", "?") for s in slots[:5]]
                extras.append(f"asset_slots=[{', '.join(slot_names)}{'…' if len(slots) > 5 else ''}]")
            lines.append(f"  · {' · '.join(extras)}")

    if corrupted:
        lines.append("")
        lines.append(f"⚠ 损坏文件 ({len(corrupted)} 个 · 文件存在但 JSON 解析失败 · 通常是 PowerShell 误用 UTF-16 写盘):")
        for aid in corrupted:
            lines.append(f"  - `{aid}.json` (data/workshop/apps/ · 建议手工删除或用 UTF-8 重写)")

    lines.append("")
    lines.append("提示:")
    lines.append("  - 跑某个 app: 用 run_app(app_id=..., inputs={...})")
    lines.append("  - 看 app 细节 (system_prompt / 历史版本): 用 open_app(app_id=...) 或 app_versions")
    lines.append("  - 想看完整字段: 加 detailed=true")
    lines.append("  - ★ 标记 = shipped (随 DK 出厂的内置 app · 不删)")
    return ToolResult(ok=True, output="\n".join(lines), truncated=truncated)


SPEC = ToolSpec(
    name="list_apps",
    description=(
        "List all apps in the workshop (data/workshop/apps/*.json). "
        "Use whenever you want to know what apps exist — DO NOT use glob_files for this "
        "(.gitignore hides apps/*.json from rg). "
        "Returns id / name / icon / version / runs and (with detailed=true) tools / inputs / outputs / asset_slots. "
        "Filter by query (substring match in id/name/description) or shipped_only=true. Read-only."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Optional substring filter (matches in id / name / description, case-insensitive).",
            },
            "shipped_only": {
                "type": "boolean",
                "description": "If true, only return shipped (built-in) apps. Default false.",
            },
            "detailed": {
                "type": "boolean",
                "description": "If true, also show tools / inputs / outputs / asset_slots for each app. Default false.",
            },
            "limit": {
                "type": "integer",
                "description": "Max apps to return. Default 50.",
            },
        },
        "required": [],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
