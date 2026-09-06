"""生成文件落点 · 单一事实源。

用户产物、运行时、草稿各有固定的家。升级（update_core）物理上不碰这些路径；
write_file / 生图新建文件时也不许再在 data/ 或工程根下随手开新目录。
"""
from __future__ import annotations

from pathlib import Path

# 允许在其下新建子目录的 data/ 分类。已在磁盘上的旧目录仍可写入（不逼搬家）。
KNOWN_DATA_DIRS = frozenset({
    "reports", "presentations", "spreadsheets",
    "workshop", "runtime", "design", "docs", "dev", "content",
    "knowledge", "clients", "playbooks", "learnings", "cognition",
    "ledgers", "reviews", "feasibility", "outcomes",
    "cache", "market", "trend_briefs", "trends_archive",
    "_backups", "softcopyright",
})

# update_core checkout 参数里出现这些前缀 = 事故，直接丢掉。
USER_DATA_PREFIXES = (
    "data/",
    "soul/",
    "sessions/",
    "static/user/",
)

SCRATCH = "data/runtime/scratch"
_HINT = (
    "报告 data/reports · PPT data/presentations · 表 data/spreadsheets · "
    "工坊产出 data/workshop/outputs · HTML 原型 data/design · "
    "操作手册 data/playbooks（只能 extract_playbook） · "
    f"运行时/草稿 {SCRATCH}/"
)


def posix_rel(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def is_user_data_path(rel: str) -> bool:
    """内核白名单里不该出现的用户数据 / 灵魂 / 会话路径。"""
    p = (rel or "").replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    p = p.lstrip("/")
    if p == ".env" or p.startswith(".env."):
        return True
    for pref in USER_DATA_PREFIXES:
        if p == pref.rstrip("/") or p.startswith(pref):
            return True
    return False


def drop_user_data_paths(files: list[str]) -> tuple[list[str], list[str]]:
    """白名单拍平后丢掉用户数据路径。返 (可同步, 被拒)。"""
    keep, drop = [], []
    for f in files:
        rel = str(f or "").replace("\\", "/").strip()
        if not rel:
            continue
        if is_user_data_path(rel):
            drop.append(rel)
        else:
            keep.append(rel)
    return keep, drop


def _is_scratch_name(rel: str) -> bool:
    return any(part.startswith("_tmp") for part in rel.split("/") if part)


def refuse_new_path(path: Path, root: Path) -> str | None:
    """新建文件时的归类闸。None = 放行。已存在的文件不要走这里。"""
    try:
        rel = posix_rel(path, root)
    except ValueError:
        return "只能写在工程根目录内"
    if _is_scratch_name(rel):
        return f"探针/草稿不要放 {rel}。写到 {SCRATCH}/ 。用户产物：{_HINT}"
    parts = rel.split("/")
    top = parts[0]
    if top == "data" and len(parts) >= 2:
        bucket = parts[1]
        if bucket in KNOWN_DATA_DIRS or (root / "data" / bucket).exists():
            return None
        return f"不要新建 data/{bucket}/。归类：{_HINT}"
    if not (root / top).exists():
        return f"不要在工程根下新开 {top}/。代码进现有模块，产物进 data/ 已有分类（{_HINT}）。"
    return None


def coerce_out_dir(raw, default: Path, root: Path) -> Path:
    """生图等 out_dir：非法/越界/乱开目录 → 落到默认分类。"""
    root_r = root.resolve()
    dest = default if default.is_absolute() else (root_r / default)
    dest = dest.resolve()
    if raw is None or str(raw).strip() == "":
        return dest
    p = Path(str(raw).strip())
    if not p.is_absolute():
        p = root_r / p
    try:
        p = p.resolve()
        p.relative_to(root_r)
    except (ValueError, OSError):
        return dest
    if refuse_new_path(p / ".sink_probe", root_r) is None:
        return p
    return dest
