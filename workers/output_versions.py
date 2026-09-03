"""产物同题只留最新一份 · 旧的进历史，货架按家族折叠。"""
from __future__ import annotations

import hashlib
import re
import shutil
import time
from pathlib import Path

_STAMP = re.compile(r"^(?P<stem>.+?)__(?P<ts>\d{8}-\d{4,6}(?:-\d+)?)$")
_UNSAFE = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_WIP = ".__wip__"
_HIST = "_hist_"


def family_key(name: str) -> str:
    stem = Path(name or "").stem
    if stem.startswith(_HIST):
        rest = stem[len(_HIST):]
        m = re.match(r"(.+)_v\d+_", rest)
        if m:
            return m.group(1)
    m = _STAMP.match(stem)
    return ((m.group("stem") if m else stem) or "deck").strip()


def safe_family(title: str) -> str:
    cleaned = _UNSAFE.sub("_", (title or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._-")
    return family_key(cleaned[:80] or "deck")


def current_name(family: str, suffix: str) -> str:
    return f"{family}{suffix}"


def deck_pages(path: Path) -> int:
    """pptx 真页数。假文件 / 坏文件返 0。"""
    if path.suffix.lower() not in {".pptx", ".ppt"}:
        return 0
    try:
        from pptx import Presentation
        return len(Presentation(str(path)).slides)
    except Exception:
        return 0


def is_hidden_output(name: str) -> bool:
    n = name or ""
    return (
        n.startswith("~$")
        or n.startswith(_WIP)
        or n.startswith(_HIST)
        or n.startswith(".")
    )


def _hist_dir_files(folder: Path, family: str, suffix: str) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(
        (p for p in folder.glob(f"{_HIST}{family}_v*{suffix}") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
    )


def _count_hist(folder: Path, family: str, suffix: str) -> int:
    return len(_hist_dir_files(folder, family, suffix))


def _digest(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _same_bytes(a: Path, b: Path) -> bool:
    try:
        if not a.is_file() or not b.is_file():
            return False
        if a.resolve() == b.resolve():
            return True
        if a.stat().st_size != b.stat().st_size:
            return False
        return _digest(a) == _digest(b)
    except OSError:
        return False


def _already_archived(folder: Path, family: str, suffix: str, path: Path) -> bool:
    try:
        size = path.stat().st_size
        digest = None
        for old in _hist_dir_files(folder, family, suffix):
            if old.stat().st_size != size:
                continue
            if digest is None:
                digest = _digest(path)
            if _digest(old) == digest:
                return True
    except OSError:
        return False
    return False


def _archive_one(path: Path, folder: Path, family: str, suffix: str) -> Path | None:
    if not path.exists() or not path.is_file():
        return None
    if path.name.startswith(_WIP) or path.name.startswith(_HIST):
        return None
    if _already_archived(folder, family, suffix, path):
        return None
    n = _count_hist(folder, family, suffix) + 1
    ts = time.strftime("%Y%m%d-%H%M%S")
    dest = folder / f"{_HIST}{family}_v{n}_{ts}{suffix}"
    i = 2
    while dest.exists():
        dest = folder / f"{_HIST}{family}_v{n}-{i}_{ts}{suffix}"
        i += 1
    shutil.move(str(path), str(dest))
    md = path.with_suffix(".md")
    if md.exists():
        shutil.move(str(md), str(dest.with_suffix(".md")))
    return dest


def archive_family(folder: Path, family: str, suffix: str, *, keep: Path | None = None) -> int:
    """把当前稿和带时间戳的旧稿推进历史。返回即将写出的版本号。"""
    folder.mkdir(parents=True, exist_ok=True)
    keep_r = keep.resolve() if keep and keep.exists() else None
    moved = 0
    cur = folder / current_name(family, suffix)
    if cur.exists() and (keep_r is None or cur.resolve() != keep_r):
        if _archive_one(cur, folder, family, suffix):
            moved += 1
    for p in list(folder.glob(f"{family}__*{suffix}")):
        if is_hidden_output(p.name):
            continue
        if keep_r and p.resolve() == keep_r:
            continue
        if _archive_one(p, folder, family, suffix):
            moved += 1
    if keep_r and keep.exists() and keep.resolve() == keep_r:
        if _archive_one(keep, folder, family, suffix):
            moved += 1
    return _count_hist(folder, family, suffix) + 1


def staged_path(folder: Path, family: str, suffix: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{_WIP}{family}{suffix}"


def publish(wip: Path, folder: Path, family: str, suffix: str, *, keep: Path | None = None) -> tuple[Path, int]:
    if not wip.exists():
        raise FileNotFoundError(str(wip))
    dest = folder / current_name(family, suffix)
    if dest.exists() and _same_bytes(dest, wip):
        if wip.resolve() != dest.resolve():
            wip.unlink()
            md_wip = wip.with_suffix(".md")
            if md_wip.exists():
                md_wip.unlink()
        return dest, _count_hist(folder, family, suffix) + 1
    ver = archive_family(folder, family, suffix, keep=keep)
    if dest.exists():
        dest.unlink()
    wip.replace(dest)
    md_wip = wip.with_suffix(".md")
    if md_wip.exists():
        md_wip.replace(dest.with_suffix(".md"))
    return dest, ver


def _item(path: Path, kind: str, spec: dict, extra: dict | None = None) -> dict:
    stat = path.stat()
    rec = {
        "name": path.name,
        "kind": kind,
        "size_kb": round(stat.st_size / 1024, 1),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
        "download_url": spec["download_prefix"] + path.name,
        "preview_url": spec["preview_prefix"] + path.name,
        "has_md_source": path.with_suffix(".md").exists(),
        "open_path": str(spec["rel"] / path.name).replace("\\", "/"),
        "pages": deck_pages(path) if kind == "decks" else 0,
    }
    if extra:
        rec.update(extra)
    return rec


def fold_items(items: list[dict], *, folder: Path, kind: str, spec: dict) -> list[dict]:
    """同一题只露最新 · 其余进 history · 带 version。"""
    suffix = spec["suffix"]
    groups: dict[str, list[dict]] = {}
    for it in items:
        if is_hidden_output(it.get("name") or ""):
            continue
        groups.setdefault(family_key(it["name"]), []).append(it)
    out = []
    for key, members in groups.items():
        members.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        cur = dict(members[0])
        hist = []
        for old in members[1:]:
            hist.append(_hist_rec(old, spec))
        for p in reversed(_hist_dir_files(folder, key, suffix)):
            try:
                hist.append(_hist_rec(_item(p, kind, spec), spec))
            except OSError:
                continue
        hist.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        total = len(hist) + 1
        for i, h in enumerate(hist):
            h["version"] = total - 1 - i
        hist = _collapse_hist(hist)
        cur["title"] = key
        cur["version"] = total
        cur["history"] = hist
        out.append(cur)
    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return out


def _collapse_hist(hist: list[dict]) -> list[dict]:
    """同一份原文件被反复归档时，货架只露一行。"""
    out: list[dict] = []
    for h in hist:
        sig = (h.get("size_kb"), h.get("created_at") or "")
        if out:
            prev = out[-1]
            if (prev.get("size_kb"), prev.get("created_at") or "") == sig:
                v = int(h.get("version") or 0)
                prev["dupes"] = (prev.get("dupes") or 1) + 1
                prev["version_lo"] = min(int(prev.get("version_lo") or prev.get("version") or v), v)
                continue
        rec = dict(h)
        rec["dupes"] = 1
        rec["version_lo"] = rec.get("version") or 0
        out.append(rec)
    return out


def _hist_rec(rec: dict, spec: dict) -> dict:
    name = rec.get("name") or ""
    return {
        "name": name,
        "version": 0,
        "created_at": rec.get("created_at") or "",
        "size_kb": rec.get("size_kb") or 0,
        "download_url": rec.get("download_url") or (spec["download_prefix"] + name),
        "preview_url": rec.get("preview_url") or (spec["preview_prefix"] + name),
        "open_path": rec.get("open_path") or str(spec["rel"] / name).replace("\\", "/"),
        "pages": rec.get("pages") or 0,
    }


def restore_current(folder: Path, src: Path, family: str, suffix: str) -> tuple[Path, int]:
    """把某份旧稿抄回当前名。现在的最新版先进历史。"""
    folder = folder.resolve()
    src = src.resolve()
    try:
        src.relative_to(folder)
    except ValueError:
        raise ValueError("path escapes folder")
    if not src.is_file():
        raise FileNotFoundError(src.name)
    if family_key(src.name) != family:
        raise ValueError("not the same family")
    dest = folder / current_name(family, suffix)
    if dest.exists() and dest.resolve() == src:
        return dest, _count_hist(folder, family, suffix) + 1
    archive_family(folder, family, suffix)
    if dest.exists():
        dest.unlink()
    shutil.copy2(src, dest)
    md_src = src.with_suffix(".md")
    md_dest = dest.with_suffix(".md")
    if md_src.exists():
        shutil.copy2(md_src, md_dest)
    return dest, _count_hist(folder, family, suffix) + 1
