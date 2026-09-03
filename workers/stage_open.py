"""HTML 原型铺中栏：哪些路径算成品、打 DK-OPEN、拼可服务地址。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_PREFIXES = (
    "data/workshop/outputs/",
    "data/design/",
    "data/docs/",
    "data/dev/",
    "data/content/",
    "data/presentations/",
)

_HTML = {".html", ".htm"}
_ASSETS = _HTML | {
    ".css", ".js",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".woff", ".woff2", ".ttf",
}

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
}


def rel_posix(path: Path | str, root: Path | None = None) -> str:
    base = (root or ROOT).resolve()
    p = Path(path)
    if not p.is_absolute():
        p = base / p
    try:
        return p.resolve().relative_to(base).as_posix()
    except ValueError:
        return ""


def is_stage_html(path: Path | str, root: Path | None = None) -> bool:
    rel = rel_posix(path, root)
    if not rel or Path(rel).suffix.lower() not in _HTML:
        return False
    return any(rel.startswith(p) for p in _PREFIXES)


def append_open_mark(output: str, path: Path | str, root: Path | None = None) -> str:
    if not is_stage_html(path, root):
        return output
    rel = rel_posix(path, root)
    mark = f"[[DK-OPEN]]{rel}"
    if not rel or mark in (output or ""):
        return output
    return (output or "").rstrip() + "\n" + mark + "\n"


def mime_for(path: Path | str) -> str:
    return _MIME.get(Path(str(path)).suffix.lower(), "")


def resolve_served(rel: str, root: Path | None = None) -> Path | None:
    """只放行工坊成品树里的 HTML/样式/配图，挡住路径穿越。"""
    p = str(rel or "").replace("\\", "/").lstrip("/")
    if not p or ".." in p or p.startswith("/") or "\x00" in p:
        return None
    if not any(p.startswith(pref) for pref in _PREFIXES):
        return None
    if Path(p).suffix.lower() not in _ASSETS:
        return None
    base = (root or ROOT).resolve()
    full = (base / p).resolve()
    try:
        full.relative_to(base)
    except ValueError:
        return None
    if not full.is_file():
        return None
    return full
