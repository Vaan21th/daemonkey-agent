"""产物货架 · 报告 / 演示稿 / 表格 清单与预览 md。"""
from __future__ import annotations

import time
from pathlib import Path

from workers.output_versions import deck_pages, family_key, fold_items, is_hidden_output, restore_current

_ROOT = Path(__file__).resolve().parent.parent

_KIND_SPEC = {
    "reports": {
        "rel": Path("data") / "reports",
        "suffix": ".docx",
        "download_prefix": "/reports/",
        "preview_prefix": "/reports/preview/",
    },
    "decks": {
        "rel": Path("data") / "presentations",
        "suffix": ".pptx",
        "download_prefix": "/presentations/",
        "preview_prefix": "/shelf/preview/decks/",
    },
    "sheets": {
        "rel": Path("data") / "spreadsheets",
        "suffix": ".xlsx",
        "download_prefix": "/spreadsheets/",
        "preview_prefix": "/shelf/preview/sheets/",
    },
}


def _root(root: Path | None = None) -> Path:
    return Path(root) if root is not None else _ROOT


def _safe_name(name: str, suffix: str) -> str:
    name = (name or "").strip()
    if not name.lower().endswith(suffix):
        raise ValueError(f"filename 必须以 {suffix} 结尾")
    if "/" in name or "\\" in name or ".." in name or "\x00" in name:
        raise ValueError("invalid filename")
    if name.startswith(".") or name.startswith("~") or name.startswith("~$"):
        raise ValueError("hidden / temp files forbidden")
    return name


def list_kind(kind: str, *, root: Path | None = None) -> dict:
    spec = _KIND_SPEC.get(kind)
    if not spec:
        raise ValueError(f"unknown shelf kind: {kind}")
    base = _root(root)
    folder = base / spec["rel"]
    folder.mkdir(parents=True, exist_ok=True)
    items = []
    for p in sorted(folder.glob(f"*{spec['suffix']}"), key=lambda x: x.stat().st_mtime, reverse=True):
        if is_hidden_output(p.name):
            continue
        try:
            stat = p.stat()
            items.append({
                "name": p.name,
                "kind": kind,
                "size_kb": round(stat.st_size / 1024, 1),
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                "download_url": spec["download_prefix"] + p.name,
                "preview_url": spec["preview_prefix"] + p.name,
                "has_md_source": p.with_suffix(".md").exists(),
                "open_path": str(spec["rel"] / p.name).replace("\\", "/"),
                "pages": deck_pages(p) if kind == "decks" else 0,
            })
        except OSError:
            continue
    items = fold_items(items, folder=folder, kind=kind, spec=spec)
    try:
        directory = str(folder.relative_to(base))
    except ValueError:
        directory = str(folder)
    return {
        "kind": kind,
        "count": len(items),
        "items": items,
        "directory": directory,
    }


def list_shelf(*, root: Path | None = None) -> dict:
    reports = list_kind("reports", root=root)
    decks = list_kind("decks", root=root)
    sheets = list_kind("sheets", root=root)
    return {
        "domain": "reports",
        "label": "产物库",
        "count": reports["count"],
        "items": reports["items"],
        "directory": reports["directory"],
        "kinds": {"reports": reports, "decks": decks, "sheets": sheets},
    }


def resolve_item(kind: str, filename: str, *, root: Path | None = None) -> Path:
    spec = _KIND_SPEC.get(kind)
    if not spec:
        raise ValueError(f"unknown shelf kind: {kind}")
    filename = _safe_name(filename, spec["suffix"])
    folder = (_root(root) / spec["rel"]).resolve()
    path = (folder / filename).resolve()
    try:
        path.relative_to(folder)
    except ValueError:
        raise ValueError("path escapes shelf directory")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(filename)
    return path


def restore_item(kind: str, filename: str, *, root: Path | None = None) -> dict:
    spec = _KIND_SPEC.get(kind)
    if not spec:
        raise ValueError("unknown shelf kind")
    src = resolve_item(kind, filename, root=root)
    dest, ver = restore_current(src.parent, src, family_key(src.name), spec["suffix"])
    return {
        "ok": True,
        "name": dest.name,
        "kind": kind,
        "version": ver,
        "from": filename,
        "preview_url": spec["preview_prefix"] + dest.name,
        "open_path": open_rel(kind, dest.name),
    }


def open_rel(kind: str, filename: str) -> str:
    spec = _KIND_SPEC.get(kind)
    if not spec:
        raise ValueError(f"unknown shelf kind: {kind}")
    return str(spec["rel"] / filename).replace("\\", "/")


def preview_md(kind: str, filename: str, *, root: Path | None = None) -> dict:
    spec = _KIND_SPEC[kind]
    path = resolve_item(kind, filename, root=root)
    filename = path.name
    md_path = path.with_suffix(".md")
    meta: dict = {}
    md_body = ""
    has_md = md_path.exists()
    if has_md:
        raw = md_path.read_text(encoding="utf-8")
        md_body = raw
        if raw.startswith("---\n"):
            end = raw.find("\n---\n", 4)
            if end > 0:
                fm = raw[4:end]
                md_body = raw[end + 5:].lstrip("\n")
                for line in fm.splitlines():
                    if ":" in line:
                        k, _, v = line.partition(":")
                        meta[k.strip()] = v.strip()
    size_kb = 0.0
    try:
        size_kb = round(path.stat().st_size / 1024, 1)
    except OSError:
        pass
    return {
        "ok": True,
        "name": filename,
        "kind": kind,
        "size_kb": size_kb,
        "pages": deck_pages(path) if kind == "decks" else 0,
        "has_md_source": has_md,
        "source": "md" if has_md else "none",
        "markdown": md_body,
        "meta": meta,
        "download_url": spec["download_prefix"] + filename,
        "open_path": open_rel(kind, filename),
        "note": "" if has_md else {
            "sheets": "这份表格没有 markdown 源 · 成品预览仍可看表。",
            "decks": "这份演示稿没有 markdown 源 · 请下载用本机软件打开。",
        }.get(kind, "这份报告没有 markdown 源。"),
    }
