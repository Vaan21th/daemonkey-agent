"""workers/safe_write.py
==========================

卷四十六 III 补丁 5 · R5 · 关键 JSON 原子写 + 时间戳备份 · 2026-05-26

为什么需要这个
----------------
工程里 11 处独立实现了 `_atomic_write` (wishlist / radar / opportunities /
trends / outcomes / favorites / app_secrets / provider_configs / info_radar /
workshop_assets / radar_feedback / feasibility_analyzer / opportunity_miner ·
trend_finder)。 都用 `tmp.write_text + os.replace` 拼出来 · 形态各异但都做
一件事: 防止半写。

少了的一块是 **写前备份**。 如果:
  - OPUS 写了一个空 dict 进 wishlist.json (LLM hallucinate)
  - workshop_assets 的 manifest 半写后 LLM 把破坏的写进去 (没半写但内容是错的)
  - BRO 手工编辑 JSON 写错括号

→ 文件就坏了 · 没有时间戳备份 · 只能去 git history 翻 (但工作中的 JSON 不全 commit)。

这一模块做三件事:
  1. **`atomic_write_text(path, content, backup=True)`**: 写前先 copy 旧文件到
     `data/_backups/<filename>_<ISO_ts>.bak` · 然后原子写新内容
  2. **`atomic_write_json(path, data, backup=True)`**: text 的 json wrapper
  3. **`_rotate_backups(path)`**: 同 path 的 backup 保留最近 10 份 · 老的删

设计取舍
----------
- **opt-in 不强制**: 暴露新 module · 旧 11 处 `_atomic_write` 不动 · 只给关键
  JSON (wishlist / radar / opportunities) 迁移用 · 防 一次性大改起反作用
- **backup 失败不阻断写**: backup IO 失败仍然写入 · 只在 log warn (caller 不
  会因 backup 失败丢主写)
- **timestamp 用 ISO 没冒号**: Windows 文件名不能含冒号 · 替换成 _
- **不压缩 backup**: 简单优先 · 主要是 JSON 小文件 · 10 份占用可接受
- **跟 daemon_lifecycle 同目录**: 都用 data/runtime/ ? 不对 · _backups 单独
  目录 data/_backups/ · 已 gitignore

用法 (callers migrate 一行):
    # 旧
    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))
    # 新
    from workers.safe_write import atomic_write_json
    atomic_write_json(path, data)  # 自动备份 + 原子写
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union


ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT / "data" / "_backups"
DEFAULT_KEEP = 10  # 同 path 保留最近 N 份 backup


_log = logging.getLogger("opus.safe_write")


def _ensure_backup_dir() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _backup_key(path: Path) -> str:
    """同 path 的 backup 用统一 key 前缀 · 比如 data/opus_wishlist.json →
    opus_wishlist.json · 嵌套结构压平不再保留 · 文件名碰撞用 hash 区分"""
    name = path.name
    rel_parent = path.parent.relative_to(ROOT) if ROOT in path.parents else Path(".")
    rel_str = str(rel_parent).replace("\\", "_").replace("/", "_")
    if rel_str and rel_str != ".":
        return f"{rel_str}_{name}"
    return name


def _ts_for_filename() -> str:
    """Windows 安全 · 不含 : · 例 20260526T170230"""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def _rotate_backups(key: str, keep: int = DEFAULT_KEEP) -> None:
    """同 key 的备份保留最近 keep 份 · 老的删"""
    if not BACKUP_DIR.exists():
        return
    candidates = sorted(
        [p for p in BACKUP_DIR.iterdir() if p.is_file() and p.name.startswith(key + "_")],
        key=lambda p: p.name,
        reverse=True,  # 新在前
    )
    for p in candidates[keep:]:
        try:
            p.unlink()
        except OSError as e:
            _log.debug("无法删旧 backup %s: %s", p, e)


def _do_backup(path: Path, *, keep: int = DEFAULT_KEEP) -> Optional[Path]:
    """备份 path 当前内容到 BACKUP_DIR · 不存在的 path 跳过 · 返备份文件路径或 None

    backup 失败仅 warn · 不 raise · 不阻塞主写
    """
    if not path.exists():
        return None
    try:
        _ensure_backup_dir()
        key = _backup_key(path)
        ts = _ts_for_filename()
        backup_name = f"{key}_{ts}.bak"
        dst = BACKUP_DIR / backup_name
        shutil.copy2(path, dst)
        _rotate_backups(key, keep=keep)
        return dst
    except Exception as e:
        _log.warning("backup 失败 (主写仍会继续) · path=%s err=%s: %s",
                     path, type(e).__name__, e)
        return None


# ── Windows 瞬态句柄锁重试 (社区 7/31 反馈 · Defender 实时扫描持锁 ~50-200ms) ──────

def _is_permission_err(e: BaseException) -> bool:
    """只认「瞬态文件锁」类错误才值得重试 · 磁盘满/路径错等直接抛。

    errno 13 = Permission denied (Defender 常见) · 32 = Windows sharing violation
    (另一进程持有句柄)。 其他 OSError 不重试 —— 重试无效场景只会掩盖真问题。
    """
    if isinstance(e, PermissionError):
        return True
    if isinstance(e, OSError):
        return getattr(e, "errno", None) in (13, 32)
    return False


def _retry_replace(src, dst, retries: int = 3) -> None:
    """os.replace 带瞬态锁重试 · 指数退避 0.05s → 0.1s → 0.2s · 超次仍失败则抛原异常。"""
    delay = 0.05
    for i in range(retries):
        try:
            os.replace(src, dst)
            return
        except OSError as e:
            if _is_permission_err(e) and i < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise


def atomic_write_text(
    path: Union[str, Path],
    content: str,
    *,
    backup: bool = True,
    keep_backups: int = DEFAULT_KEEP,
) -> dict:
    """原子写 text + 自动备份

    Args:
        path: 目标文件
        content: 写入内容
        backup: 默认 True · 写前 backup 旧文件到 data/_backups/
        keep_backups: 同 path 最多保留多少份 · 默认 10

    Returns:
        {"ok": True, "path": str, "backup": Optional[str], "bytes": int}

    Raises:
        OSError: 原子写失败 (磁盘满 / 权限) · 跟标准 atomic write 一致
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    backup_path: Optional[Path] = None
    if backup:
        backup_path = _do_backup(p, keep=keep_backups)

    fd, tmp_name = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        _retry_replace(tmp_name, p)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

    size = len(content.encode("utf-8"))
    return {
        "ok": True,
        "path": str(p),
        "backup": str(backup_path) if backup_path else None,
        "bytes": size,
    }


def atomic_write_json(
    path: Union[str, Path],
    data: Any,
    *,
    backup: bool = True,
    keep_backups: int = DEFAULT_KEEP,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> dict:
    """原子写 JSON + 自动备份 · atomic_write_text 的 JSON wrapper

    Args 同 atomic_write_text · 加 indent / ensure_ascii (默认 indent=2 不 ASCII 转义)
    """
    text = json.dumps(data, ensure_ascii=ensure_ascii, indent=indent)
    return atomic_write_text(path, text, backup=backup, keep_backups=keep_backups)


def list_backups(path: Union[str, Path]) -> list[dict]:
    """列出 path 的所有备份 · 新在前

    Returns:
        [{"path": str, "ts": str, "bytes": int}, ...]
    """
    p = Path(path)
    key = _backup_key(p)
    if not BACKUP_DIR.exists():
        return []
    out = []
    for f in sorted(BACKUP_DIR.iterdir(), key=lambda x: x.name, reverse=True):
        if not f.is_file() or not f.name.startswith(key + "_"):
            continue
        try:
            stat = f.stat()
            out.append({
                "path": str(f),
                "name": f.name,
                "ts": f.name[len(key) + 1:-4],  # 去掉 key_ 前缀和 .bak 后缀
                "bytes": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
        except OSError:
            continue
    return out


def restore_backup(backup_path: Union[str, Path], target_path: Union[str, Path]) -> dict:
    """把指定 backup 恢复到 target_path · 恢复前再备份一份 target 当前状态

    Args:
        backup_path: data/_backups/ 下的 .bak 文件
        target_path: 要恢复到的目标

    Returns:
        {"ok": True, "restored_from": str, "pre_restore_backup": str, "bytes": int}
    """
    bp = Path(backup_path)
    if not bp.exists():
        raise FileNotFoundError(f"backup not found: {bp}")

    content = bp.read_text(encoding="utf-8")
    result = atomic_write_text(target_path, content, backup=True)
    result["restored_from"] = str(bp)
    result["pre_restore_backup"] = result.pop("backup")
    return result


__all__ = [
    "atomic_write_text",
    "atomic_write_json",
    "list_backups",
    "restore_backup",
    "robust_write_text",
    "robust_write_json",
    "robust_open_append",
    "robust_replace",
    "BACKUP_DIR",
]


# ── robust 系列 (社区 7/31 · Bug #8 · 批量补全瞬态锁防护) ─────────────────────────

def robust_write_text(
    path: Union[str, Path],
    content: str,
    *,
    backup: bool = True,
    keep_backups: int = DEFAULT_KEEP,
    retries: int = 3,
) -> dict:
    """atomic_write_text + 瞬态 PermissionError 重试 · 其余行为完全一致。

    返回同 atomic_write_text ({ok, path, backup, bytes})。
    """
    delay = 0.05
    for i in range(retries):
        try:
            return atomic_write_text(path, content, backup=backup, keep_backups=keep_backups)
        except OSError as e:
            if _is_permission_err(e) and i < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise


def robust_write_json(
    path: Union[str, Path],
    data: Any,
    *,
    backup: bool = True,
    keep_backups: int = DEFAULT_KEEP,
    indent: int = 2,
    ensure_ascii: bool = False,
    retries: int = 3,
) -> dict:
    """atomic_write_json + 瞬态锁重试。"""
    text = json.dumps(data, ensure_ascii=ensure_ascii, indent=indent)
    return robust_write_text(path, text, backup=backup, keep_backups=keep_backups, retries=retries)


def robust_open_append(path: Union[str, Path], *, retries: int = 3):
    """open(path, 'a', encoding='utf-8') 带瞬态锁重试 · 返回已打开的 file object。

    调用方负责 close (用 with 最稳)。 自动创建父目录。
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    delay = 0.05
    for i in range(retries):
        try:
            return p.open("a", encoding="utf-8")
        except OSError as e:
            if _is_permission_err(e) and i < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise


def robust_replace(src: Union[str, Path], dst: Union[str, Path], *, retries: int = 3) -> None:
    """os.replace 带瞬态锁重试 · 直接暴露给裸 tmp.replace 调用方迁移。"""
    _retry_replace(src, dst, retries=retries)
