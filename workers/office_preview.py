"""成品预览：有 HTML 就嵌 iframe（划字钉批注）；没有才 PPT 截图翻页。"""
from __future__ import annotations

import hashlib
import re
import shutil
import threading
from pathlib import Path

from workers.output_shelf import open_rel, resolve_item
from workers.output_versions import deck_pages

CACHE_REL = Path("data") / "runtime" / "shelf_preview"
_KINDS = ("reports", "decks", "sheets")
_ASSET_RE = re.compile(r"^(preview\.pdf|preview\.html|\d{3}\.png)$", re.I)
_CACHE_ID_RE = re.compile(r"^[a-f0-9]{16}$")
_KEEP_CACHES = 40
_SB_MARK = 'id="dk-sb"'
# 成品 HTML 是 iframe · 父页主题滚条进不去 · 先盖一层跟画布走的细条
_SB_STYLE = (
    '<style id="dk-sb">'
    "html{color-scheme:dark}"
    "*{scrollbar-width:thin!important;"
    "scrollbar-color:rgba(232,223,201,.32) transparent!important}"
    "*::-webkit-scrollbar{width:8px!important;height:8px!important}"
    "*::-webkit-scrollbar-track{background:transparent!important}"
    "*::-webkit-scrollbar-thumb{background:rgba(232,223,201,.32)!important;border-radius:4px}"
    "*::-webkit-scrollbar-thumb:hover{background:rgba(232,223,201,.55)!important}"
    "</style>"
)


def stamp_preview_scroll(html: str) -> str:
    if _SB_MARK in html:
        return html
    low = html.lower()
    for tag in ("<head", "<html"):
        i = low.find(tag)
        if i < 0:
            continue
        j = html.find(">", i)
        if j >= 0:
            return html[: j + 1] + _SB_STYLE + html[j + 1 :]
    return _SB_STYLE + html


def _root(root: Path | None = None) -> Path:
    return Path(root) if root is not None else Path(__file__).resolve().parent.parent


def cache_id(src: Path) -> str:
    st = src.stat()
    raw = f"{src.resolve()}|{st.st_mtime_ns}|{st.st_size}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def resolve_asset(kind: str, cid: str, name: str, *, root: Path | None = None) -> Path:
    if kind not in _KINDS:
        raise ValueError("unknown shelf kind")
    if not _CACHE_ID_RE.fullmatch(cid or ""):
        raise ValueError("invalid cache id")
    if not _ASSET_RE.fullmatch(name or ""):
        raise ValueError("invalid asset name")
    base = (_root(root) / CACHE_REL / kind / cid).resolve()
    path = (base / name).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        raise ValueError("path escapes preview cache")
    if not path.is_file():
        raise FileNotFoundError(name)
    return path


def _pngs(dest: Path) -> list[Path]:
    files = [p for p in dest.iterdir() if p.is_file() and p.suffix.lower() == ".png"]

    def key(p: Path) -> int:
        m = re.search(r"(\d+)", p.stem)
        return int(m.group(1)) if m else 10**9

    return sorted(files, key=key)


def _cache_ready(dest: Path) -> bool:
    if not dest.is_dir():
        return False
    pdf = dest / "preview.pdf"
    html = dest / "preview.html"
    if pdf.is_file() and pdf.stat().st_size > 0:
        return True
    if html.is_file() and html.stat().st_size > 0:
        return True
    return bool(_pngs(dest))


def _prune(root: Path) -> None:
    base = root / CACHE_REL
    if not base.exists():
        return
    dirs = [p for p in base.glob("*/*") if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for old in dirs[_KEEP_CACHES:]:
        shutil.rmtree(old, ignore_errors=True)


def _has_html(dest: Path) -> bool:
    html = dest / "preview.html"
    return html.is_file() and html.stat().st_size > 0


def _payload(kind: str, filename: str, cid: str, dest: Path, *, cached: bool, pages: int = 0) -> dict:
    open_path = open_rel(kind, filename)
    prefix = f"/shelf/preview-asset/{kind}/{cid}/"
    pdf = dest / "preview.pdf"
    html = dest / "preview.html"
    files = _pngs(dest)
    n = pages if pages > 0 else (len(files) or 1)
    # 截图好看但不能划字。有 HTML 一律走 iframe，批注层才能圈出成品原文。
    if html.is_file() and html.stat().st_size > 0:
        return {
            "ok": True, "kind": kind, "name": filename, "mode": "html",
            "cache_id": cid, "cached": cached, "pages": n,
            "pdf_url": None, "html_url": prefix + "preview.html",
            "assets": [], "open_path": open_path,
        }
    if pdf.is_file() and pdf.stat().st_size > 0:
        return {
            "ok": True, "kind": kind, "name": filename, "mode": "pdf",
            "cache_id": cid, "cached": cached, "pages": n,
            "pdf_url": prefix + "preview.pdf", "html_url": None,
            "assets": [], "open_path": open_path,
        }
    return {
        "ok": True, "kind": kind, "name": filename, "mode": "slides",
        "cache_id": cid, "cached": cached, "pages": n,
        "pdf_url": None, "html_url": None,
        "assets": [{"page": i, "url": f"{prefix}{p.name}"} for i, p in enumerate(files, 1)],
        "open_path": open_path,
    }


def _fail(kind: str, filename: str, error: str) -> dict:
    return {
        "ok": False, "kind": kind, "name": filename,
        "error": error, "open_path": open_rel(kind, filename),
    }


def _try_com(kind: str, src: Path, dest: Path) -> bool:
    try:
        import pythoncom  # noqa: F401
        import win32com.client  # noqa: F401
    except ImportError:
        return False
    from workers.office_com import export_docx, export_pptx

    try:
        if kind == "decks":
            export_pptx(src, dest)
        elif kind == "reports":
            export_docx(src, dest / "preview.pdf")
        else:
            return False
    except Exception:
        return False
    return _cache_ready(dest)


def _try_officecli_html(src: Path, dest: Path) -> bool:
    try:
        from workers import officecli
        if officecli.available():
            return officecli.export_html(src, dest / "preview.html")
    except Exception:
        return False
    return False


def _try_officecli(kind: str, src: Path, dest: Path) -> bool:
    try:
        from workers import officecli
    except Exception:
        return False
    if not officecli.available():
        return False
    try:
        if kind == "decks" and officecli.export_html(src, dest / "preview.html"):
            return True
        return bool(officecli.export_screenshots(src, dest))
    except Exception:
        return False


def _try_officecli_shots(src: Path, dest: Path) -> bool:
    try:
        from workers import officecli
        if not officecli.available():
            return False
        n = max(deck_pages(src) or 12, 12)
        return bool(officecli.export_screenshots(src, dest, max_pages=n))
    except Exception:
        return False


def _try_sheet_html(src: Path, dest: Path) -> bool:
    try:
        from excel_engine.preview import write_preview
        write_preview(src, dest / "preview.html")
    except Exception:
        return False
    return _cache_ready(dest)


def build_visual(kind: str, filename: str, *, root: Path | None = None) -> dict:
    """失败不抛，返 ok=False 让前端退回文稿。"""
    src = resolve_item(kind, filename, root=root)
    base = _root(root)
    cid = cache_id(src)
    dest = base / CACHE_REL / kind / cid
    if _cache_ready(dest):
        if kind == "decks" and not _has_html(dest):
            try:
                _try_officecli_html(src.resolve(), dest)
            except Exception:
                pass
        elif kind == "reports" and not _has_html(dest):
            threading.Thread(
                target=_try_officecli_html,
                args=(src.resolve(), dest),
                daemon=True,
            ).start()
        pages = deck_pages(src) if kind == "decks" else 0
        return _payload(kind, filename, cid, dest, cached=True, pages=pages)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    ok = False
    src_abs = src.resolve()
    if kind == "sheets":
        ok = _try_sheet_html(src_abs, dest)
    elif kind == "decks":
        ok = _try_officecli_html(src_abs, dest)
        if not ok:
            ok = _try_com(kind, src_abs, dest)
        if not ok:
            ok = _try_officecli_shots(src_abs, dest)
    else:
        ok = _try_officecli_html(src_abs, dest)
        if not ok:
            ok = _try_com(kind, src_abs, dest)
        if not ok:
            shutil.rmtree(dest, ignore_errors=True)
            dest.mkdir(parents=True, exist_ok=True)
            ok = _try_officecli(kind, src_abs, dest)
    if not ok:
        from workers import soffice_preview
        if soffice_preview.available():
            dest.mkdir(parents=True, exist_ok=True)
            ok = soffice_preview.export(src_abs, dest, fmt="html")
            if not ok:
                ok = soffice_preview.export(src_abs, dest, fmt="pdf")
    if not ok:
        shutil.rmtree(dest, ignore_errors=True)
        return _fail(
            kind, filename,
            "成品预览渲不出来。本机没有 Office/WPS/OfficeCLI，也没有 LibreOffice。"
            "Mac 可 brew install --cask libreoffice。可以下载或用软件打开。",
        )
    _prune(base)
    pages = deck_pages(src) if kind == "decks" else 0
    return _payload(kind, filename, cid, dest, cached=False, pages=pages)
