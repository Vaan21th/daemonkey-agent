"""接管文件的官方新版落点。

takeover 让 checkout 物理不带这些文件，官方修复否则永远不落盘。
升级时把 git show 的官方内容写到 data/runtime/official_incoming/，
用户还能对照摘补丁，不必取消接管。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from workers.git_ops import ROOT, _lock, _run_git

INCOMING = ROOT / "data" / "runtime" / "official_incoming"
BINARY = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".wav", ".mp3",
          ".mp4", ".woff", ".woff2", ".ttf", ".exe", ".dll", ".zip"}


def dest_for(rel: str) -> Path:
    rel = str(rel).replace("\\", "/").lstrip("/")
    return INCOMING / rel


def show_ref(rel: str, ref: str, *, already_locked: bool = False) -> Optional[str]:
    """读 ref 上该文件的文本。二进制或失败返 None。"""
    rel = str(rel).replace("\\", "/")
    if Path(rel).suffix.lower() in BINARY:
        return None

    def _go() -> Optional[str]:
        rc, out, _ = _run_git(["show", f"{ref}:{rel}"], timeout=15)
        if rc != 0:
            return None
        return out

    if already_locked:
        return _go()
    with _lock("official_incoming:show"):
        return _go()


def drop_from_ref(rel: str, ref: str, *, already_locked: bool = False) -> Optional[str]:
    """把官方版写到 official_incoming/<rel>。成功返相对路径字符串。"""
    rel = str(rel).replace("\\", "/")
    dest = dest_for(rel)

    def _go() -> Optional[str]:
        dest.parent.mkdir(parents=True, exist_ok=True)
        suffix = Path(rel).suffix.lower()
        if suffix in BINARY:
            import subprocess
            try:
                res = subprocess.run(
                    ["git", "show", f"{ref}:{rel}"],
                    cwd=str(ROOT), capture_output=True, timeout=20,
                )
            except Exception:
                return None
            if res.returncode != 0 or not res.stdout:
                return None
            dest.write_bytes(res.stdout)
        else:
            rc, out, _ = _run_git(["show", f"{ref}:{rel}"], timeout=15)
            if rc != 0:
                return None
            dest.write_text(out, encoding="utf-8")
        try:
            return str(dest.relative_to(ROOT)).replace("\\", "/")
        except Exception:
            return str(dest)

    if already_locked:
        return _go()
    with _lock("official_incoming:drop"):
        return _go()


def drop_many(files: list[str], ref: str, *, already_locked: bool = True) -> list[dict]:
    out = []
    for rel in files:
        p = drop_from_ref(rel, ref, already_locked=already_locked)
        if p:
            out.append({"file": rel, "path": p})
    return out
