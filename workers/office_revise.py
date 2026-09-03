"""已有 Office 稿的局部拼接：只换一页或一段，其余 markdown 照抄。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_PAGE_SPLIT = re.compile(r"\n---\n")
_UNSAFE = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_SOFT = re.compile(r"[\s·•|.,;:：#*_`\"'“”\-—]+")


def fold_key(s: str) -> str:
    return _SOFT.sub("", s or "").lower()


def fold_span(text: str, needle: str) -> tuple[int, int] | None:
    """成品圈字对 md：忽略空白、·、标题井号。只命中一次才算。"""
    n_key = fold_key(needle)
    if not n_key:
        return None
    keys: list[str] = []
    imap: list[int] = []
    for i, ch in enumerate(text or ""):
        if _SOFT.fullmatch(ch):
            continue
        keys.append(ch.lower())
        imap.append(i)
    blob = "".join(keys)
    if blob.count(n_key) != 1:
        return None
    at = blob.index(n_key)
    return imap[at], imap[at + len(n_key) - 1] + 1


def safe_filename(title: str) -> str:
    cleaned = _UNSAFE.sub("_", (title or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._-")
    return cleaned[:80] or "deck"


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    raw = (text or "").lstrip("\ufeff")
    if not raw.startswith("---"):
        return {}, raw
    rest = raw[3:]
    if rest.startswith("\n"):
        rest = rest[1:]
    end = rest.find("\n---")
    if end < 0:
        return {}, raw
    head, body = rest[:end], rest[end + 4 :]
    if body.startswith("\n"):
        body = body[1:]
    fm: dict[str, str] = {}
    for line in head.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        fm[key.strip()] = val.strip()
    return fm, body


def split_pages(body: str) -> list[str]:
    parts = _PAGE_SPLIT.split((body or "").strip())
    return [p.strip() for p in parts if p.strip()]


def join_pages(pages: list[str]) -> str:
    return "\n\n---\n\n".join(p.strip() for p in pages if p.strip())


def dump_markdown(fm: dict[str, str], body: str) -> str:
    lines = ["---"]
    for key in (
        "title", "style", "accent", "mood", "theme",
        "include_cover", "subtitle", "audience", "note", "footer",
        "pptx", "docx", "xlsx",
    ):
        val = (fm.get(key) or "").strip()
        if val:
            lines.append(f"{key}: {val}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + (body or "").strip() + "\n"


def fm_flag(fm: dict[str, str], key: str) -> bool | None:
    raw = (fm.get(key) or "").strip().lower()
    if raw in ("false", "0", "no", "off"):
        return False
    if raw in ("true", "1", "yes", "on"):
        return True
    return None


def map_visual_page(
    visual: int,
    n_md: int,
    n_slides: int | None,
    include_cover: bool | None,
) -> int:
    """画布页码 → 文稿页码（1-based）。0 = 自动封面，不在分页正文里。"""
    extra = include_cover
    if extra is None:
        extra = n_slides is not None and n_slides == n_md + 1
    if extra:
        if visual <= 1:
            return 0
        idx = visual - 1
    else:
        idx = visual
    if idx < 1 or idx > n_md:
        raise ValueError(f"第{visual}页对不上文稿（文稿 {n_md} 页）")
    return idx


def replace_excerpt(text: str, excerpt: str, new: str) -> str:
    needle = (excerpt or "").strip()
    new = (new or "").strip()
    if not needle:
        raise ValueError("excerpt 是空的")
    n = text.count(needle)
    if n == 1:
        return text.replace(needle, new, 1)
    if n > 1:
        raise ValueError(f"「{needle[:40]}」出现 {n} 次，请加上 page 收窄，或圈更长一段")
    hits = []
    for i, line in enumerate(text.splitlines()):
        fl, fn = fold_key(line), fold_key(needle)
        if fl and fn and (fn == fl or fn.startswith(fl) or fl.startswith(fn)):
            hits.append(i)
    if len(hits) == 1:
        lines = text.splitlines(keepends=True)
        raw = lines[hits[0]]
        nl = "\n" if raw.endswith("\n") else ""
        core = raw.rstrip("\n")
        vis = re.sub(r"^[\s#]+", "", core)
        longer = fold_key(needle).startswith(fold_key(core)) and fold_key(needle) != fold_key(core)
        repl = new.split("·")[0].strip() if longer and "·" in needle else new
        span = fold_span(core, vis) or fold_span(core, needle)
        if span:
            lines[hits[0]] = core[: span[0]] + repl + core[span[1] :] + nl
            return "".join(lines)
    span = fold_span(text, needle)
    if span:
        return text[: span[0]] + new + text[span[1] :]
    raise ValueError(f"文稿里找不到「{needle[:40]}」")


def apply_splice(
    pages: list[str],
    *,
    page: int | None,
    excerpt: str,
    body: str,
    n_slides: int | None = None,
    include_cover: bool | None = None,
    fm: dict[str, str] | None = None,
) -> tuple[list[str], dict[str, str], str]:
    """返回 (新分页, 可能改过的 fm 补丁, 一句说明)。"""
    if not pages:
        raise ValueError("文稿是空的")
    new_text = (body or "").strip()
    if not new_text:
        raise ValueError("body 是空的 · 要写下替换后的那一页或那段")
    needle = (excerpt or "").strip()
    fm_patch: dict[str, str] = {}
    cover_title = ((fm or {}).get("title") or "").strip()

    if page and page > 0:
        idx = map_visual_page(page, len(pages), n_slides, include_cover)
        if idx == 0:
            title = new_text.lstrip("# ").splitlines()[0].strip() if new_text else ""
            if not title:
                raise ValueError("第1页是自动封面 · body 里给新标题")
            fm_patch["title"] = title
            return list(pages), fm_patch, "改了自动封面标题，正文页未动"
        cur = pages[idx - 1]
        if needle:
            pages = list(pages)
            pages[idx - 1] = replace_excerpt(cur, needle, new_text)
            return pages, fm_patch, f"第{page}页里换了一段"
        pages = list(pages)
        pages[idx - 1] = new_text
        return pages, fm_patch, f"换了第{page}页，其余 {len(pages) - 1} 页照抄"

    if needle and cover_title and fold_key(needle) == fold_key(cover_title):
        title = new_text.lstrip("# ").splitlines()[0].strip()
        if not title:
            raise ValueError("封面标题是空的")
        fm_patch["title"] = title
        return list(pages), fm_patch, "改了封面标题，正文页未动"

    if needle:
        joined = "\n\n---\n\n".join(pages)
        updated = replace_excerpt(joined, needle, new_text)
        return split_pages(updated), fm_patch, "按圈出的原文换了一段"

    if len(pages) == 1:
        return [new_text], fm_patch, "单页稿整页换了"
    raise ValueError("多页稿必须给 page 或 excerpt，避免整份重写")


@dataclass
class OfficeSource:
    kind: str
    src: Path
    md_path: Path
    fm: dict[str, str]
    pages: list[str]
    n_slides: int | None


def _slide_count(path: Path) -> int | None:
    if path.suffix.lower() not in {".pptx", ".ppt"}:
        return None
    try:
        from pptx import Presentation
        return len(Presentation(str(path)).slides)
    except Exception:
        return None


def kind_of(path: Path, fm: dict[str, str] | None = None) -> str:
    ext = path.suffix.lower()
    if ext in {".pptx", ".ppt"}:
        return "decks"
    if ext in {".docx", ".doc"}:
        return "reports"
    if ext in {".xlsx", ".xls"}:
        return "sheets"
    fm = fm or {}
    if fm.get("pptx"):
        return "decks"
    if fm.get("docx"):
        return "reports"
    if fm.get("xlsx"):
        return "sheets"
    parent = path.parent.name.lower()
    if "presentation" in parent:
        return "decks"
    if "spreadsheet" in parent:
        return "sheets"
    return "reports"


def load_source(path: Path) -> OfficeSource:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    md_path = path if path.suffix.lower() == ".md" else path.with_suffix(".md")
    if not md_path.is_file():
        raise FileNotFoundError(
            f"没有同源 markdown（{md_path.name}）。外来稿不能局部改，只能整份重出。"
        )
    fm, body = parse_front_matter(md_path.read_text(encoding="utf-8"))
    pages = split_pages(body)
    if not pages:
        raise ValueError("同源 markdown 没有正文")
    src = path if path.suffix.lower() != ".md" else path
    n_slides = _slide_count(src) if src.suffix.lower() in {".pptx", ".ppt"} else None
    if n_slides is None and fm.get("pptx"):
        n_slides = _slide_count(md_path.with_name(fm["pptx"]))
    return OfficeSource(
        kind=kind_of(src if src.suffix.lower() != ".md" else md_path, fm),
        src=src,
        md_path=md_path,
        fm=fm,
        pages=pages,
        n_slides=n_slides,
    )
