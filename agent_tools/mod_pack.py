"""MOD 叠层的导出 / 导入 / 列表。"""
from __future__ import annotations

from pathlib import Path

from . import TIER_AUTO, TIER_CONFIRM, ToolResult, ToolSpec, register_tool


def _list(args: dict) -> ToolResult:
    from workers.mod_runtime import list_mods
    rows = list_mods()
    if not rows:
        return ToolResult(ok=True, output=(
            "还没有叠层 MOD。写在 data/mods/<id>/ 或 agent_tools_user/，"
            "升级不会覆盖。说「导出 MOD <id>」可打包给别人。"
        ))
    lines = [f"本机叠层 MOD ({len(rows)}):", ""]
    for m in rows:
        flag = "开" if m.get("enabled") else "关"
        lines.append(f"  [{flag}] {m['id']}  {m.get('name')}  v{m.get('version')}")
    lines.append("")
    lines.append("目录 data/mods/ · 官方升级物理不碰。分享：导出 MOD <id>")
    return ToolResult(ok=True, output="\n".join(lines))


def _export(args: dict) -> ToolResult:
    from workers.mod_pack_io import export_zip
    mid = str(args.get("id") or args.get("name") or "").strip()
    if not mid:
        return ToolResult(ok=False, output="", error="id 必填（data/mods/<id>）")
    path, err = export_zip(
        mid,
        author=str(args.get("author") or ""),
        version=str(args.get("version") or ""),
        description=str(args.get("description") or ""),
    )
    if path is None:
        return ToolResult(ok=False, output="", error=err)
    rel = path.as_posix()
    try:
        rel = str(path.relative_to(Path(__file__).resolve().parent.parent)).replace("\\", "/")
    except Exception:
        pass
    return ToolResult(ok=True, output=(
        f"已打包 MOD `{mid}` → `{rel}`\n"
        "发给别人，对方说「导入 MOD <路径>」即装。市集 kind=mod。"
    ))


def _import(args: dict) -> ToolResult:
    from workers.mod_pack_io import import_zip
    raw = str(args.get("path") or "").strip()
    if not raw:
        return ToolResult(ok=False, output="", error="path 必填（.dkpkg）")
    root = Path(__file__).resolve().parent.parent
    p = Path(raw)
    if not p.is_absolute():
        p = root / raw
    if not p.exists():
        return ToolResult(ok=False, output="", error=f"文件不存在: {raw}")
    ok, msg = import_zip(p, overwrite=bool(args.get("overwrite")))
    return ToolResult(ok=ok, output=msg if ok else "", error="" if ok else msg)


register_tool(ToolSpec(
    name="list_mods",
    description="列出本机叠层 MOD（data/mods）。升级不覆盖这些目录。",
    tier=TIER_AUTO,
    input_schema={"type": "object", "properties": {}, "required": []},
    run=_list,
    summarize=lambda args: "列出叠层 MOD",
))

register_tool(ToolSpec(
    name="export_mod",
    description="把 data/mods/<id> 打成 .dkpkg（kind=mod），可发给别人或上架市集。",
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "MOD 目录名"},
            "name": {"type": "string", "description": "同 id，兼容叫法"},
            "version": {"type": "string"},
            "description": {"type": "string"},
            "author": {"type": "string"},
        },
        "required": ["id"],
    },
    run=_export,
    summarize=lambda args: f"导出 MOD {args.get('id') or args.get('name')}",
))

register_tool(ToolSpec(
    name="import_mod",
    description="导入 kind=mod 的 .dkpkg 到 data/mods/<id>。同名默认拒装。",
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": ".dkpkg 路径"},
            "overwrite": {"type": "boolean"},
        },
        "required": ["path"],
    },
    run=_import,
    summarize=lambda args: f"导入 MOD {args.get('path')}",
))
