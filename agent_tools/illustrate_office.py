"""CONFIRM · 已有 pptx 某一页的相对位置贴一张配图，其余页不动。"""
from __future__ import annotations

from pathlib import Path

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool

_ROOT = Path(__file__).resolve().parent.parent
_ALLOW = _ROOT / "data" / "presentations"


def _summarize(args: dict) -> str:
    rel = (args.get("path") or "").strip() or "?"
    page = args.get("page") or "?"
    return f"第{page}页加图 {rel}"


def _resolve(rel: str) -> Path | ToolResult:
    from daemon_runtime import RUNTIME
    from workers.session_docs import accept_upload

    path, err = accept_upload(getattr(RUNTIME, "session_id", "") or "", rel, root=_ROOT)
    if path is None:
        return ToolResult(ok=False, output="", error=err or "只改 data/presentations")
    if path.suffix.lower() not in {".pptx", ".ppt"}:
        return ToolResult(ok=False, output="", error="只给已有 pptx 加图")
    if _ALLOW.resolve() not in path.parents and path.parent != _ALLOW.resolve():
        return ToolResult(ok=False, output="", error="只改 data/presentations")
    return path


def _image(args: dict, here: Path) -> Path | ToolResult:
    raw = (args.get("image") or "").strip()
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = (_ROOT / raw).resolve()
        try:
            p.relative_to(_ROOT.resolve())
        except ValueError:
            return ToolResult(ok=False, output="", error="配图路径必须在工程内")
        if not p.is_file():
            return ToolResult(ok=False, output="", error=f"找不到配图 {raw}")
        return p
    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        return ToolResult(ok=False, output="", error="给 prompt 生图，或给 image 现成图路径")
    from agent_tools.generate_image import generate_one

    here.mkdir(parents=True, exist_ok=True)
    got = generate_one(prompt, out_dir=here)
    if got is None:
        return ToolResult(
            ok=False, output="",
            error="生图没出来。设好生图应用或 DAEMONKEY_IMAGE_MODEL，或改传 image=现成图。",
        )
    return Path(got)


def _run(args: dict) -> ToolResult:
    got = _resolve(str(args.get("path") or ""))
    if isinstance(got, ToolResult):
        return got
    try:
        page = int(args.get("page") or 0)
    except (TypeError, ValueError):
        return ToolResult(ok=False, output="", error="page 必须是页码数字")
    if page < 1:
        return ToolResult(ok=False, output="", error="page 从 1 起")
    from workers.office_slides import place_picture
    from workers.output_versions import publish, safe_family, staged_path

    family = safe_family(got.stem)
    folder = _ALLOW
    here = folder / "_assets" / family
    img = _image(args, here)
    if isinstance(img, ToolResult):
        return img
    staged = staged_path(folder, family, got.suffix.lower() or ".pptx")
    try:
        info = place_picture(
            got, staged, img,
            page=page,
            x=args.get("x", 0.5),
            y=args.get("y", 0.5),
            w=args.get("w", 0.36),
        )
        out, ver = publish(staged, folder, family, got.suffix.lower() or ".pptx", keep=got)
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"加图失败: {type(e).__name__}: {e}")
    rel = out.relative_to(_ROOT).as_posix()
    return ToolResult(
        ok=True,
        output="\n".join([
            f"第{info['page']}页加了配图 · {out.name} · V{ver}",
            f"  路径: {rel}",
            f"  位置约 {info['x']:.0%} / {info['y']:.0%}，其余页没动",
            f"[[DK-OPEN]]{rel}",
        ]),
    )


SPEC = ToolSpec(
    name="illustrate_office",
    description=(
        "已有 pptx 某一页按坐标贴配图。x/y 是页内 0-1（批注钉子）。"
        "prompt 生图或 image 用现成图。其余页和板式留下。不要整份重出。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "已有稿，例如 data/presentations/稿.pptx"},
            "page": {"type": "integer", "description": "画布页码，从 1 起"},
            "prompt": {"type": "string", "description": "要画的画面。画面里不要有字。"},
            "image": {"type": "string", "description": "现成图相对路径。有就不再生。"},
            "x": {"type": "number", "description": "图心横向 0-1。批注钉子的 x。"},
            "y": {"type": "number", "description": "图心纵向 0-1。批注钉子的 y。"},
            "w": {"type": "number", "description": "图宽占页宽，默认 0.36"},
        },
        "required": ["path", "page"],
        "additionalProperties": False,
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
