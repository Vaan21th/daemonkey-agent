"""本机可执行文件探测 · Mac/Windows 共用。启动器只 pip，系统级工具在这里找。"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

_WIN_CHROME = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)
_MAC_CHROME = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
)
_MAC_SOFFICE = (
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "/opt/homebrew/bin/soffice",
    "/usr/local/bin/soffice",
)


def venv_python(root: Path | None = None) -> str:
    base = Path(root) if root is not None else _ROOT
    for rel in (Path(".venv") / "bin" / "python", Path(".venv") / "Scripts" / "python.exe"):
        p = base / rel
        if p.is_file():
            return str(p)
    return sys.executable


def is_foreign_venv(root: Path | None = None) -> bool:
    """Windows 的 .venv 拷到 Mac（或反过来）· bin/python 对不上。"""
    base = Path(root) if root is not None else _ROOT
    venv = base / ".venv"
    if not venv.is_dir():
        return False
    posix = (venv / "bin" / "python").is_file()
    win = (venv / "Scripts" / "python.exe").is_file()
    if sys.platform == "win32":
        return win is False and posix is True
    return posix is False and win is True


def find_chromium() -> str | None:
    override = (os.environ.get("DAEMONKEY_BROWSER_PATH") or "").strip()
    if override and Path(override).exists():
        return override
    cands: list[str] = []
    if sys.platform == "win32":
        cands.extend(_WIN_CHROME)
        local = os.environ.get("LOCALAPPDATA")
        if local:
            cands += [
                str(Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe"),
                str(Path(local) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
            ]
    elif sys.platform == "darwin":
        cands.extend(_MAC_CHROME)
    else:
        for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
            w = shutil.which(name)
            if w:
                return w
    for p in cands:
        if Path(p).exists():
            return p
    return find_playwright_chromium()


def find_playwright_chromium() -> str | None:
    home = Path.home()
    roots = [
        Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]) if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") else None,
        home / "AppData" / "Local" / "ms-playwright",
        home / "Library" / "Caches" / "ms-playwright",
        home / ".cache" / "ms-playwright",
    ]
    needles = (
        "chrome-win/chrome.exe",
        "chrome-win64/chrome.exe",
        "chrome-mac/Chromium.app/Contents/MacOS/Chromium",
        "chrome-mac-arm64/Chromium.app/Contents/MacOS/Chromium",
        "chrome-linux/chrome",
    )
    for root in roots:
        if root is None or not root.is_dir():
            continue
        for n in needles:
            hits = list(root.glob(f"chromium-*/{n}"))
            if hits:
                return str(hits[-1])
    return None


def playwright_channels() -> list[str | None]:
    """standalone launch 尝试顺序 · None = 自带 Chromium。"""
    if sys.platform == "win32":
        return ["msedge", "chrome", None]
    if sys.platform == "darwin":
        return ["chrome", "msedge", None]
    return ["chrome", None]


def find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def find_soffice() -> str | None:
    w = shutil.which("soffice") or shutil.which("libreoffice")
    if w:
        return w
    if sys.platform == "darwin":
        for p in _MAC_SOFFICE:
            if Path(p).exists():
                return p
    if sys.platform == "win32":
        for p in (
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ):
            if Path(p).exists():
                return p
    return None


def ffmpeg_grab_args(outfile: str, duration: int, region: str = "desktop") -> list[str]:
    """按平台拼 ffmpeg 抓屏参数。Mac 要系统「屏幕录制」权限。"""
    common_out = [
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        outfile,
    ]
    if sys.platform == "darwin":
        # 1 = 整块屏幕（avfoundation）；区域裁剪用 crop
        grab = ["ffmpeg", "-y", "-f", "avfoundation", "-framerate", "30", "-i", "1"]
        if region and region != "desktop":
            parts = region.replace(":", " ").replace("x", " ").split()
            if len(parts) != 4:
                raise ValueError(f"invalid region format: {region}")
            x, y, w, h = parts
            grab += ["-vf", f"crop={w}:{h}:{x}:{y}"]
        return grab + common_out
    if sys.platform == "win32":
        if region == "desktop" or not region:
            return ["ffmpeg", "-y", "-f", "gdigrab", "-framerate", "30",
                    "-i", "desktop", *common_out]
        parts = region.replace(":", " ").replace("x", " ").split()
        if len(parts) != 4:
            raise ValueError(f"invalid region format: {region}")
        x, y, w, h = parts
        return [
            "ffmpeg", "-y", "-f", "gdigrab", "-framerate", "30",
            "-offset_x", str(x), "-offset_y", str(y),
            "-video_size", f"{w}x{h}", "-i", "desktop", *common_out,
        ]
    # Linux
    disp = os.environ.get("DISPLAY") or ":0"
    if region == "desktop" or not region:
        return ["ffmpeg", "-y", "-f", "x11grab", "-framerate", "30",
                "-i", disp, *common_out]
    parts = region.replace(":", " ").replace("x", " ").split()
    if len(parts) != 4:
        raise ValueError(f"invalid region format: {region}")
    x, y, w, h = parts
    return ["ffmpeg", "-y", "-f", "x11grab", "-framerate", "30",
            "-video_size", f"{w}x{h}", "-i", f"{disp}+{x},{y}", *common_out]


def ensure_playwright_chromium(py: str, timeout: int = 600) -> bool:
    try:
        r = subprocess.run(
            [py, "-m", "playwright", "install", "chromium"],
            capture_output=True, timeout=timeout,
        )
        return r.returncode == 0
    except Exception:
        return False
