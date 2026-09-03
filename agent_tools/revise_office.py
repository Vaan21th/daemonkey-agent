"""CONFIRM · 局部改已有 pptx/docx/xlsx：圈字原位换，整页 markdown 才重渲。"""
from __future__ import annotations

from pathlib import Path

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool

_ROOT = Path(__file__).resolve().parent.parent
_ALLOW = (
    _ROOT / "data" / "reports",
    _ROOT / "data" / "presentations",
    _ROOT / "data" / "spreadsheets",
)
_OK = {".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".md"}


def _summarize(args: dict) -> str:
    rel = (args.get("path") or "").strip() or "?"
    page = args.get("page")
    bit = f"第{page}页" if page else "一段"
    return f"局部改 {rel} · {bit}"


def _resolve(rel: str) -> Path | ToolResult:
    from daemon_runtime import RUNTIME
    from workers.session_docs import accept_upload
    path, err = accept_upload(getattr(RUNTIME, "session_id", "") or "", rel, root=_ROOT)
    if path is None:
        return ToolResult(ok=False, output="", error=err or "只改办公稿")
    if path.suffix.lower() not in _OK:
        return ToolResult(ok=False, output="", error="只改 docx / pptx / xlsx / 同源 md")
    if not any(path == d.resolve() or d.resolve() in path.parents for d in _ALLOW):
        return ToolResult(ok=False, output="", error="只改 data/reports · presentations · spreadsheets")
    return path


def _want_cover(src) -> bool:
    """只认文稿里写明的 include_cover。圈字改稿绝不能靠页数差推断加封面。"""
    from workers.office_revise import fm_flag
    return bool(fm_flag(src.fm, "include_cover"))


def _here_dir(kind: str, src: Path) -> Path:
    folder = "presentations" if kind == "decks" else "reports"
    return _ROOT / "data" / folder / "_assets" / src.stem.split("__")[0]


def _render_deck(title: str, body: str, fm: dict, cover: bool, out: Path, here: Path) -> None:
    from slides_engine import audit_deck, parse_deck, render_deck, resolve_style

    style = resolve_style(
        fm.get("style") or "light_studio",
        accent=fm.get("accent") or None,
        mood=fm.get("mood") or None,
    )
    slides = parse_deck(body)
    audit_deck(slides, here, cover={"title": title} if cover else None)
    meta = {"title": title} if cover else None
    if meta:
        for key in ("subtitle", "audience", "note", "footer"):
            if fm.get(key):
                meta[key] = fm[key]
    render_deck(slides, out, cover=meta, style=style, here_dir=here)


def _render_report(title: str, body: str, fm: dict, cover: bool, out: Path, here: Path) -> None:
    from report_engine import render_report

    theme = fm.get("theme") or "opus_studio"
    meta = None
    if cover:
        meta = {"title": title}
        for key in ("subtitle", "audience", "note", "footer"):
            if fm.get(key):
                meta[key] = fm[key]
    render_report(md_text=body, output_path=out, cover=meta, theme=theme, here_dir=here)


def _render_sheet(body: str, out: Path) -> int:
    from excel_engine import parse_sheets, render_workbook

    sheets = parse_sheets(body, None)
    if not sheets:
        raise ValueError("拼接后解析不到表")
    render_workbook(sheets, out)
    return len(sheets)


def _splice_deck_page(src: Path, page: int, body: str, out: Path, here: Path) -> None:
    from workers.office_extend import render_new_pages
    from workers.office_slides import replace_slide

    extra = out.with_name(out.stem + ".__page__.pptx")
    try:
        render_new_pages(body, extra, inherit=src, here=here)
        replace_slide(src, extra, out, page)
    finally:
        extra.unlink(missing_ok=True)


def _run(args: dict) -> ToolResult:
    got = _resolve(str(args.get("path") or ""))
    if isinstance(got, ToolResult):
        return got
    try:
        page = args.get("page")
        page = int(page) if page not in (None, "") else None
    except (TypeError, ValueError):
        return ToolResult(ok=False, output="", error="page 必须是页码数字")

    from workers.office_patch import can_patch, patch_office
    from workers.office_revise import (
        dump_markdown,
        apply_splice,
        join_pages,
        load_source,
    )

    excerpt = str(args.get("excerpt") or "")
    body_in = str(args.get("body") or "")
    from workers.office_patch import looks_like_page_md

    try:
        src = load_source(got)
    except FileNotFoundError as e:
        if got.suffix.lower() in {".pptx", ".ppt"} and page and looks_like_page_md(body_in):
            from workers.output_versions import publish, safe_family, staged_path

            family = safe_family(got.stem)
            folder = _ROOT / "data" / "presentations"
            staged = staged_path(folder, family, got.suffix.lower() or ".pptx")
            try:
                _splice_deck_page(got, page, body_in, staged, _here_dir("decks", got))
                out, ver = publish(staged, folder, family, got.suffix.lower() or ".pptx", keep=got)
            except Exception as ex:
                return ToolResult(ok=False, output="", error=f"换页失败: {type(ex).__name__}: {ex}")
            rel = out.relative_to(_ROOT).as_posix()
            return ToolResult(
                ok=True,
                output="\n".join([
                    f"换了第{page}页版式 · {out.name} · V{ver}",
                    f"  路径: {rel}",
                    f"  没有同源文稿，只动这一页，其余页留下",
                    f"[[DK-OPEN]]{rel}",
                ]),
            )
        return ToolResult(ok=False, output="", error=str(e))
    except ValueError as e:
        return ToolResult(ok=False, output="", error=str(e))

    fm = dict(src.fm)
    pages = list(src.pages)
    note = ""
    in_place = can_patch(src.src, excerpt, body_in)
    try:
        pages, fm_patch, note = apply_splice(
            src.pages,
            page=None if in_place else page,
            excerpt=excerpt,
            body=body_in,
            n_slides=None if in_place else src.n_slides,
            include_cover=False if in_place else _want_cover(src),
            fm=src.fm,
        )
        fm.update(fm_patch)
    except ValueError as e:
        if not in_place:
            return ToolResult(ok=False, output="", error=str(e))
        note = f"成品已改；同源文稿没对上（{e}）"

    title = (fm.get("title") or src.md_path.stem).strip()
    body = join_pages(pages)
    cover = False if in_place else _want_cover(src)
    if not in_place:
        fm["include_cover"] = "true" if cover else "false"
    from workers.output_versions import publish, safe_family, staged_path
    family = safe_family(title)
    dirs = {
        "decks": _ROOT / "data" / "presentations",
        "reports": _ROOT / "data" / "reports",
        "sheets": _ROOT / "data" / "spreadsheets",
    }
    ext = {"decks": ".pptx", "reports": ".docx", "sheets": ".xlsx"}[src.kind]
    folder = dirs[src.kind]
    out = staged_path(folder, family, ext)
    try:
        splice = (
            src.kind == "decks"
            and page
            and looks_like_page_md(body_in)
            and "封面" not in note
        )
        if in_place:
            info = patch_office(src.src, out, excerpt=excerpt, new=body_in, page=page)
            note = (
                f"{note} · 原位改字，{info['pages']} 页 / "
                f"{info['pics']} 张图还在"
            )
        elif splice:
            _splice_deck_page(src.src, page, body_in, out, _here_dir("decks", src.src))
            note = f"{note} · 只重渲第{page}页，其余页留下"
        elif src.kind == "decks":
            _render_deck(title, body, fm, cover, out, _here_dir("decks", src.src))
        elif src.kind == "reports":
            _render_report(title, body, fm, cover, out, _here_dir("reports", src.src))
        else:
            _render_sheet(body, out)
        out, ver = publish(out, folder, family, ext, keep=src.src)
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"{'原位改' if in_place else '渲染'}失败: {type(e).__name__}: {e}")

    fm[{ "decks": "pptx", "reports": "docx", "sheets": "xlsx" }[src.kind]] = out.name
    md_path = out.with_suffix(".md")
    md_path.write_text(dump_markdown(fm, body), encoding="utf-8")
    rel = out.relative_to(_ROOT).as_posix()
    return ToolResult(
        ok=True,
        output="\n".join([
            f"局部改完 · {out.name} · V{ver}",
            f"  路径: {rel}",
            f"  {note}",
            f"  上一版进历史，货架只留这一份",
            f"[[DK-OPEN]]{rel}",
        ]),
    )


SPEC = ToolSpec(
    name="revise_office",
    description=(
        "局部改已有 pptx/docx/xlsx。圈字：excerpt=原文，body=改完的那一句，原位换字。"
        "换一页版式：page + 整页 markdown（<!-- layout -->），只重渲这一页。"
        "不要 generate_* 整份重出。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要改的文件，相对工程根，例如 data/presentations/稿.pptx",
            },
            "page": {
                "type": "integer",
                "description": "画布页码（从 1）。换整页时用；自动封面是第 1 页。",
            },
            "excerpt": {
                "type": "string",
                "description": "成品上圈出的字，不必跟 markdown 逐字相同。",
            },
            "body": {
                "type": "string",
                "description": "圈字时只写改完的那一句；整页替换才传一页 markdown。",
            },
        },
        "required": ["path", "body"],
        "additionalProperties": False,
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
