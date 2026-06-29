"""
agent_tools/_browser.py
=======================

浏览器基建共享层——daemon **专属 Edge** 的 CDP 探测 / 自启 / 标签页选择。

设计取向：daemon 不碰用户日常浏览器，而是自己拥有一个**独立 profile 的浏览器实例**
（专属 user-data-dir + 专属调试端口）。需要时自动拉起、跨调用复用。因为用的是独立
profile + 独立端口，所以**哪怕用户主浏览器开着也不冲突、绝不杀它**。

内核浏览器：Edge 优先（Win 出厂自带），没装则自动退到 Chrome（同为 Chromium，CDP 一致）；
都没有时用户可设 DAEMONKEY_BROWSER_PATH 指定任意 Chromium 内核浏览器。

browser_fetch（眼）和 browser_act（手）共用这同一个实例 —— 杜绝"眼手连到不同浏览器"。

首次使用某个需登录的站点（豆包/知乎/微信…），在这个专属窗口里登录一次即可，
登录态持久化在专属 profile 里，跟用户日常浏览完全隔离。
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CDP_HOST = "127.0.0.1"
# 专属调试端口——刻意避开用户可能自设的 9222，确保永远连的是 daemon 自己的 Edge
CDP_PORT = int(os.environ.get("DAEMONKEY_EDGE_CDP_PORT") or "9333")
CDP_URL = f"http://{CDP_HOST}:{CDP_PORT}"

# daemon 专属 Edge profile——与用户日常 Edge 物理隔离
EDGE_PROFILE = Path(
    os.environ.get("DAEMONKEY_EDGE_PROFILE") or (PROJECT_ROOT / "sessions" / "edge_cdp_profile")
)

# 候选浏览器——都是 Chromium 内核，CDP 完全一样。Edge 优先（Win 出厂自带、几乎人人有），
# 没有再退 Chrome。用户也可用 DAEMONKEY_BROWSER_PATH 显式指定（绿色版 / 其他 Chromium 内核）。
_BROWSER_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)

_LOCAL_CANDIDATES = (
    Path("Microsoft") / "Edge" / "Application" / "msedge.exe",
    Path("Google") / "Chrome" / "Application" / "chrome.exe",
)


def _find_browser() -> str | None:
    """找一个 Chromium 内核浏览器：用户指定 > Edge > Chrome。找不到返回 None。"""
    override = os.environ.get("DAEMONKEY_BROWSER_PATH")
    if override and Path(override).exists():
        return override
    for p in _BROWSER_CANDIDATES:
        if Path(p).exists():
            return p
    local = os.environ.get("LOCALAPPDATA")
    if local:
        for sub in _LOCAL_CANDIDATES:
            cand = Path(local) / sub
            if cand.exists():
                return str(cand)
    return None


def cdp_available() -> bool:
    """快速 TCP 探测端口，再确认 /json/version——避免每次等 httpx 长 timeout。"""
    try:
        with socket.create_connection((CDP_HOST, CDP_PORT), timeout=0.5):
            pass
    except (OSError, ConnectionError):
        return False
    try:
        return httpx.get(f"{CDP_URL}/json/version", timeout=2.0).status_code == 200
    except httpx.HTTPError:
        return False


def ensure_cdp(launch: bool = True, wait_secs: int = 25) -> bool:
    """确保 daemon 专属 CDP Edge 在跑。

    已在 → True；没在且 launch → 用独立 profile + 独立端口起一个浏览器（不碰用户主浏览器）。
    起不来（没装 Edge/Chrome / 端口没拉起）→ False，由调用方给出可读错误。
    """
    if cdp_available():
        return True
    if not launch:
        return False
    exe = _find_browser()
    if not exe:
        return False
    EDGE_PROFILE.mkdir(parents=True, exist_ok=True)
    args = [
        exe,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={EDGE_PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    flags = 0
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP —— Edge 不随 daemon 重启而死
        flags = 0x00000008 | 0x00000200
    try:
        subprocess.Popen(args, creationflags=flags, close_fds=True)
    except Exception:
        return False
    for _ in range(max(1, wait_secs)):
        if cdp_available():
            return True
        time.sleep(1)
    return False


def pick_page(browser, url_contains: str = "", create_if_missing: bool = False):
    """在已连的 Edge 里挑目标标签页。

    url_contains 给定 → 选 url 含它的第一个页；否则取最近活跃的页。
    都没有且 create_if_missing → 新开一页。找不到返回 None。
    """
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    pages = list(ctx.pages)
    if url_contains:
        for pg in pages:
            try:
                if url_contains.lower() in (pg.url or "").lower():
                    return pg
            except Exception:
                continue
    if pages:
        return pages[-1]
    if create_if_missing:
        return ctx.new_page()
    return None
