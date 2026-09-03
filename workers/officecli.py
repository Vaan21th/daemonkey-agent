"""可选 OfficeCLI 二进制 · 不绑本机 Office 的 HTML/PNG 预览。"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_VENDOR = _ROOT / "data" / "runtime" / "officecli" / "officecli.exe"
_MAX_PAGES = 12

# OfficeCLI 是 console 子系统（看着像 Python 黑框）· 不藏就会在预览时弹出来
_NO_WINDOW: dict = {}
if sys.platform == "win32":
    _si = subprocess.STARTUPINFO()
    _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _si.wShowWindow = subprocess.SW_HIDE
    _NO_WINDOW = {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": _si,
    }


def find_bin() -> Path | None:
    env = (os.environ.get("OFFICECLI_BIN") or "").strip()
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates.append(_VENDOR)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "OfficeCLI" / "officecli.exe")
    which = shutil.which("officecli")
    if which:
        candidates.append(Path(which))
    for p in candidates:
        try:
            if p.is_file() and p.stat().st_size > 1_000_000:
                return p
        except OSError:
            continue
    return None


def available() -> bool:
    return find_bin() is not None


def run(args: list[str], *, timeout: int = 90) -> tuple[int, str, str]:
    bin_path = find_bin()
    if not bin_path:
        return 127, "", "officecli not installed"
    cmd = [str(bin_path), *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            check=False,
            **_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return 124, "", "officecli timeout"
    except OSError as e:
        return 127, "", str(e)
    out = proc.stdout.decode("utf-8", errors="replace")
    err = proc.stderr.decode("utf-8", errors="replace")
    return proc.returncode, out, err


def export_html(src: Path, dest: Path, *, timeout: int = 90) -> bool:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    code, _, _ = run(
        ["view", str(src), "html", "-o", str(dest)],
        timeout=timeout,
    )
    return code == 0 and dest.is_file() and dest.stat().st_size > 0


def _shot(src: Path, out: Path, render: str, page: int, timeout: int) -> bool:
    code, _, _ = run(
        [
            "view", str(src), "screenshot",
            "--render", render,
            "--page", str(page),
            "-o", str(out),
        ],
        timeout=timeout,
    )
    return code == 0 and out.is_file() and out.stat().st_size > 0


def export_screenshots(src: Path, dest_dir: Path, *, max_pages: int = _MAX_PAGES) -> list[Path]:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    render = "auto"
    for i in range(1, max_pages + 1):
        out = dest_dir / f"{i:03d}.png"
        timeout = 90 if i == 1 else 45
        ok = _shot(src, out, render, i, timeout)
        if not ok and i == 1 and render == "auto":
            render = "html"
            ok = _shot(src, out, render, i, timeout)
        if not ok:
            break
        digest = hashlib.sha1(out.read_bytes()).hexdigest()
        if written and hashlib.sha1(written[-1].read_bytes()).hexdigest() == digest:
            out.unlink(missing_ok=True)
            break
        written.append(out)
    return written


def view_text(src: Path, *, max_lines: int = 200) -> str:
    code, out, err = run(
        ["view", str(src), "text", "--max-lines", str(max_lines)],
        timeout=45,
    )
    if code != 0:
        raise RuntimeError(err.strip() or f"officecli exit {code}")
    return out.strip()
