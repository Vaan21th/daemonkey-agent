"""本地磁盘占用 · 设置页可选清理的唯一事实源。

只扫/只删白名单桶。soul / .env / 工坊应用配方 / 知识库不在这里。
"""
from __future__ import annotations

import os
from pathlib import Path

# suggest=True 的默认可勾：缓存/草稿，不是用户成品
BUCKETS = (
    {
        "id": "workshop_outputs",
        "label": "工坊产出",
        "hint": "应用跑出来的图、音、视频",
        "rel": "data/workshop/outputs",
        "danger": False,
        "suggest": False,
    },
    {
        "id": "presentations",
        "label": "演示稿",
        "hint": "PPT、配图、历史版",
        "rel": "data/presentations",
        "danger": False,
        "suggest": False,
    },
    {
        "id": "reports",
        "label": "报告",
        "hint": "生成的 Word",
        "rel": "data/reports",
        "danger": False,
        "suggest": False,
    },
    {
        "id": "spreadsheets",
        "label": "表格",
        "hint": "生成的 Excel",
        "rel": "data/spreadsheets",
        "danger": False,
        "suggest": False,
    },
    {
        "id": "design",
        "label": "HTML 原型",
        "hint": "可点的页面稿",
        "rel": "data/design",
        "danger": False,
        "suggest": False,
    },
    {
        "id": "workshop_exports",
        "label": "工坊导出包",
        "hint": "分享用的导出文件",
        "rel": "data/workshop/exports",
        "danger": False,
        "suggest": False,
    },
    {
        "id": "attachments",
        "label": "对话附件",
        "hint": "往对话里丢过的文件",
        "rel": "data/runtime/attachments",
        "danger": False,
        "suggest": False,
    },
    {
        "id": "shelf_preview",
        "label": "成品预览缓存",
        "hint": "翻页预览用的临时图，清了会再生成",
        "rel": "data/runtime/shelf_preview",
        "danger": False,
        "suggest": True,
    },
    {
        "id": "scratch",
        "label": "运行草稿",
        "hint": "探针和临时文件",
        "rel": "data/runtime/scratch",
        "danger": False,
        "suggest": True,
    },
    {
        "id": "cache",
        "label": "本地缓存",
        "hint": "检索等缓存，清了会再长",
        "rel": "data/cache",
        "danger": False,
        "suggest": True,
    },
    {
        "id": "sessions",
        "label": "对话记录",
        "hint": "工作台聊过的记录，清了找不回",
        "rel": "sessions",
        "danger": True,
        "suggest": False,
    },
)

_BUCKET_BY_ID = {b["id"]: b for b in BUCKETS}


def human_bytes(n: int) -> str:
    n = max(0, int(n or 0))
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def _root(root: Path | None) -> Path:
    return Path(root).resolve() if root is not None else Path(__file__).resolve().parent.parent


def _bucket_dir(root: Path, rel: str) -> Path:
    base = (root / rel).resolve()
    base.relative_to(root)
    return base


def _walk_files(folder: Path):
    if not folder.exists():
        return
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        keep = []
        for name in dirnames:
            p = Path(dirpath) / name
            if p.is_symlink():
                continue
            keep.append(name)
        dirnames[:] = keep
        for name in filenames:
            p = Path(dirpath) / name
            if p.is_symlink():
                continue
            yield p


def _dir_stats(folder: Path) -> tuple[int, int]:
    files = 0
    bytes_ = 0
    for p in _walk_files(folder):
        try:
            bytes_ += p.stat().st_size
            files += 1
        except OSError:
            continue
    return files, bytes_


def usage(*, root: Path | None = None) -> dict:
    base = _root(root)
    buckets = []
    total_files = 0
    total_bytes = 0
    for spec in BUCKETS:
        folder = _bucket_dir(base, spec["rel"])
        files, nbytes = _dir_stats(folder) if folder.exists() else (0, 0)
        total_files += files
        total_bytes += nbytes
        buckets.append({
            "id": spec["id"],
            "label": spec["label"],
            "hint": spec["hint"],
            "rel": spec["rel"],
            "danger": spec["danger"],
            "suggest": spec["suggest"],
            "exists": folder.exists(),
            "files": files,
            "bytes": nbytes,
            "size": human_bytes(nbytes),
        })
    return {
        "buckets": buckets,
        "total_files": total_files,
        "total_bytes": total_bytes,
        "total_size": human_bytes(total_bytes),
    }


def _purge_tree(folder: Path) -> tuple[int, int, list[str]]:
    deleted = 0
    freed = 0
    errors: list[str] = []
    if not folder.exists():
        return deleted, freed, errors
    for p in list(_walk_files(folder)):
        try:
            freed += p.stat().st_size
            p.unlink()
            deleted += 1
        except OSError as e:
            errors.append(f"{p.name}: {e}")
    for dirpath, dirnames, _filenames in os.walk(folder, topdown=False, followlinks=False):
        here = Path(dirpath)
        if here == folder:
            continue
        try:
            here.rmdir()
        except OSError:
            pass
    return deleted, freed, errors


def purge(ids: list[str], *, root: Path | None = None) -> dict:
    wanted = []
    for raw in ids or []:
        bid = str(raw or "").strip()
        if bid and bid not in wanted:
            wanted.append(bid)
    unknown = [i for i in wanted if i not in _BUCKET_BY_ID]
    if unknown:
        raise ValueError("unknown buckets: " + ", ".join(unknown))
    if not wanted:
        raise ValueError("没有选要清理的类别")
    base = _root(root)
    results = []
    total_deleted = 0
    total_freed = 0
    for bid in wanted:
        spec = _BUCKET_BY_ID[bid]
        folder = _bucket_dir(base, spec["rel"])
        deleted, freed, errors = _purge_tree(folder)
        total_deleted += deleted
        total_freed += freed
        results.append({
            "id": bid,
            "label": spec["label"],
            "deleted": deleted,
            "freed": freed,
            "freed_size": human_bytes(freed),
            "errors": errors[:8],
        })
    return {
        "ok": True,
        "deleted": total_deleted,
        "freed": total_freed,
        "freed_size": human_bytes(total_freed),
        "results": results,
        "usage": usage(root=base),
    }
