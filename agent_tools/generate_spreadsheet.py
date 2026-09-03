"""CONFIRM · markdown 表 / 结构化 sheets → data/spreadsheets/*.xlsx。"""
from __future__ import annotations

import datetime
import re
from pathlib import Path

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool

_ROOT = Path(__file__).resolve().parent.parent
_DIR = _ROOT / "data" / "spreadsheets"
_UNSAFE = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _safe_filename(title: str) -> str:
    cleaned = _UNSAFE.sub("_", (title or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned.strip("._-")[:80] or "sheet"


def _summarize(args: dict) -> str:
    title = (args.get("title") or "未命名表格").strip()
    body = args.get("body") or ""
    n = body.count("|")
    extra = f" · {len(args['sheets'])} 张表" if isinstance(args.get("sheets"), list) else ""
    return f"生成表格《{title}》{extra}" + (f" · 约 {n} 个单元格记号" if n else "")


def _dump_preview(sheets: list[dict], limit: int = 8) -> list[str]:
    lines = []
    for sh in sheets:
        lines.append(f"  [{sh['name']}] " + " | ".join(str(h) for h in sh["headers"]))
        for row in sh["rows"][:limit]:
            lines.append("    " + " | ".join("" if c is None else str(c) for c in row))
        more = len(sh["rows"]) - limit
        if more > 0:
            lines.append(f"    … 还有 {more} 行")
    return lines


def _run(args: dict) -> ToolResult:
    from ._hotpath_guard import require_scenario
    blocked = require_scenario("spreadsheet")
    if blocked:
        return ToolResult(ok=False, output="", error=blocked)

    title = (args.get("title") or "").strip()
    if not title:
        return ToolResult(ok=False, output="", error="title 必填 · 表格标题 + 文件名")

    body = args.get("body") or ""
    grabbed = False
    if (not body or not str(body).strip()) and not args.get("sheets"):
        try:
            from . import current_turn_text
            grabbed_text = (current_turn_text() or "").strip()
        except Exception:
            grabbed_text = ""
        if grabbed_text:
            body = grabbed_text
            grabbed = True

    try:
        from excel_engine import parse_sheets, render_workbook
    except ImportError as e:
        return ToolResult(ok=False, output="", error=f"excel_engine / openpyxl 缺失: {e}")

    sheets = parse_sheets(body, args.get("sheets"))
    if not sheets:
        return ToolResult(
            ok=False, output="",
            error=(
                "没解析到表。给法：① body 里写 markdown 表（`# 表名` + `| 列 |`，多表用 `---`）；"
                "② 传 sheets: [{name, headers, rows}]；③ 先把表写在回复里再只传 title。"
            ),
        )

    _DIR.mkdir(parents=True, exist_ok=True)
    safe = _safe_filename(title)
    from workers.output_versions import publish, safe_family, staged_path
    family = safe_family(safe)
    out_path = staged_path(_DIR, family, ".xlsx")
    try:
        wip = render_workbook(sheets, out_path)
        final, ver = publish(wip, _DIR, family, ".xlsx")
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"渲染失败: {type(e).__name__}: {e}")

    md_path = final.with_suffix(".md")
    try:
        fm = [
            "---", f"title: {title}",
            f"generated_at: {datetime.datetime.now().isoformat(timespec='seconds')}",
            f"xlsx: {final.name}", "---",
        ]
        md_path.write_text("\n".join(fm) + "\n\n" + (body or ""), encoding="utf-8")
    except Exception:
        pass

    size_kb = final.stat().st_size / 1024
    try:
        rel = final.relative_to(_ROOT)
    except ValueError:
        rel = final
    lines = [
        f"已生成表格 · {final.name} · V{ver}",
        f"  路径: {rel.as_posix() if hasattr(rel, 'as_posix') else rel}",
        f"  大小: {size_kb:.1f} KB · {len(sheets)} 张表 · "
        + " / ".join(f"{s['name']}({len(s['rows'])}行)" for s in sheets),
    ]
    if grabbed:
        lines.append("  （正文来自本轮回复 · 两步法兜底）")
    lines.append("  预览（公式会在 Excel 里算，这里是原文）：")
    lines.extend(_dump_preview(sheets))
    lines.append("")
    lines.append("产物库「表格」可见 · 点结果里的打开进 Excel/WPS。")
    try:
        lines.append(f"[[DK-OPEN]]{final.relative_to(_ROOT).as_posix()}")
    except ValueError:
        lines.append(f"[[DK-OPEN]]{final.as_posix()}")
    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="generate_spreadsheet",
    description=(
        "把 markdown 表或结构化 sheets 渲成可编辑 xlsx，落 data/spreadsheets/。"
        "出表 / 台账 / Excel / 对比。写法见 read_scenario(name='spreadsheet')。CONFIRM。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "表格标题 · 文件名 · 必填"},
            "body": {
                "type": "string",
                "description": "markdown 表。`# 表名` + `| 列 |`，多表 `---`。不传则抓本条回复。",
            },
            "sheets": {
                "type": "array",
                "description": "结构化表，优先于 body。每项 {name, headers, rows}。",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "headers": {"type": "array", "items": {"type": "string"}},
                        "rows": {"type": "array"},
                    },
                },
            },
        },
        "required": ["title"],
        "additionalProperties": False,
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
