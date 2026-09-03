"""LibreOffice headless 预览 · Mac/无 OfficeCLI 时的退路。"""
from __future__ import annotations

import subprocess
from pathlib import Path

from workers.host_bins import find_soffice


def available() -> bool:
    return find_soffice() is not None


def export(src: Path, dest: Path, *, fmt: str = "html") -> bool:
    """fmt=html|pdf · 产物落到 dest/preview.html 或 dest/preview.pdf。"""
    exe = find_soffice()
    if not exe:
        return False
    dest.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(
            [exe, "--headless", "--norestore", "--convert-to", fmt,
             "--outdir", str(dest), str(src)],
            capture_output=True, timeout=120,
        )
    except Exception:
        return False
    if r.returncode != 0:
        return False
    stem = src.stem
    produced = dest / f"{stem}.{fmt}"
    target = dest / f"preview.{fmt}"
    if produced.is_file() and produced != target:
        try:
            if target.exists():
                target.unlink()
            produced.replace(target)
        except OSError:
            return False
    return target.is_file() and target.stat().st_size > 0
