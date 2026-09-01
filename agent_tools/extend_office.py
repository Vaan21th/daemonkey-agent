"""CONFIRM · 已有 pptx 只加新页，原稿板式和素材留下。"""
from __future__ import annotations

from pathlib import Path

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool

_ROOT = Path(__file__).resolve().parent.parent
_ALLOW = _ROOT / "data" / "presentations"


def _summarize(args: dict) -> str:
    rel = (args.get("path") or "").strip() or "?"
    n = str(args.get("body") or "").count("\n---") + 1
    return f"加页 {rel} · 约 {n} 页新页"


def _resolve(rel: str) -> Path | ToolResult:
    from daemon_runtime import RUNTIME
    from workers.session_docs import accept_upload
    path, err = accept_upload(getattr(RUNTIME, "session_id", "") or "", rel, root=_ROOT)
    if path is None:
        return ToolResult(ok=False, output="", error=err or "只改 data/presentations")
    if path.suffix.lower() not in {".pptx", ".ppt"}:
        return ToolResult(ok=False, output="", error="只给已有 pptx 加页")
    if _ALLOW.resolve() not in path.parents and path.parent != _ALLOW.resolve():
        return ToolResult(ok=False, output="", error="只改 data/presentations")
    return path


def _run(args: dict) -> ToolResult:
    got = _resolve(str(args.get("path") or ""))
    if isinstance(got, ToolResult):
        return got
    body = str(args.get("body") or "").strip()
    if not body:
        return ToolResult(ok=False, output="", error="body 只写新增页的分页 markdown，不要整份重写")
    style = (args.get("style") or "light_studio").strip() or "light_studio"
    from workers.office_extend import append_slides, render_new_pages
    from workers.output_versions import publish, safe_family, staged_path

    family = safe_family(got.stem)
    folder = _ALLOW
    staged = staged_path(folder, family, got.suffix.lower() or ".pptx")
    extra = staged.with_name(staged.stem + ".__extra__.pptx")
    here = folder / "_assets" / family
    try:
        added_n = render_new_pages(body, extra, style=style, here=here, inherit=got)
        info = append_slides(got, extra, staged)
        out, ver = publish(staged, folder, family, got.suffix.lower() or ".pptx", keep=got)
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"加页失败: {type(e).__name__}: {e}")
    finally:
        if extra.exists():
            extra.unlink()

    md_path = out.with_suffix(".md")
    try:
        prev = ""
        if md_path.is_file():
            prev = md_path.read_text(encoding="utf-8").rstrip() + "\n\n"
        md_path.write_text(prev + "<!-- extended -->\n\n" + body, encoding="utf-8")
    except OSError:
        pass

    rel = out.relative_to(_ROOT).as_posix()
    return ToolResult(
        ok=True,
        output="\n".join([
            f"加页完成 · {out.name} · V{ver}",
            f"  路径: {rel}",
            f"  原 {info['base_pages']} 页留下，新加 {info['added']} 页（共 {info['total']}）",
            f"  原稿板式/图还在；新页按原稿配色",
            f"[[DK-OPEN]]{rel}",
        ]),
    )


SPEC = ToolSpec(
    name="extend_office",
    description=(
        "已有 pptx 加页/拓展到 N 页。复制原稿再接新页，原页板式和素材必须留下。"
        "body 只写新增页 markdown。禁止 generate_presentation 整份重出。"
        "新页抄原稿配色/字体，不要另起六套风格。改字仍走 revise_office。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "已有稿，例如 data/presentations/稿.pptx",
            },
            "body": {
                "type": "string",
                "description": "只要新增页。`---` 分页。不要把原页再写一遍。",
            },
            "style": {
                "type": "string",
                "enum": ["light_studio", "dark_keynote", "editorial", "glass", "neon_glitch", "sketch"],
                "description": "一般不用。新页默认抄原稿。抄不到才用这套。",
            },
        },
        "required": ["path", "body"],
        "additionalProperties": False,
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
