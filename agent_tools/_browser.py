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

import contextlib
import os
import re
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx

from agent_tools._subprocess_helper import no_window_kwargs

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CDP_HOST = "127.0.0.1"
# 专属调试端口——刻意避开用户可能自设的 9222，确保永远连的是 daemon 自己的 Edge
CDP_PORT = int(os.environ.get("DAEMONKEY_EDGE_CDP_PORT") or "9333")
CDP_URL = f"http://{CDP_HOST}:{CDP_PORT}"

# daemon 专属 Edge profile——与用户日常 Edge 物理隔离
EDGE_PROFILE = Path(
    os.environ.get("DAEMONKEY_EDGE_PROFILE") or (PROJECT_ROOT / "sessions" / "edge_cdp_profile")
)
BROWSER_PID_FILE = EDGE_PROFILE / "daemon_browser.pid"
_CDP_LOCK = threading.Lock()

def _find_browser() -> str | None:
    """用户指定 > 本机 Chrome/Edge > Playwright 自带 Chromium。"""
    from workers.host_bins import find_chromium
    return find_chromium()


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


def _kill_stale_browser() -> int:
    """只杀命令行里带本 profile 路径的浏览器进程。返回杀掉的个数。"""
    if os.name != "nt":
        return _kill_stale_posix()
    killed = 0
    needle = str(EDGE_PROFILE).lower().replace("/", "\\")
    try:
        out = subprocess.check_output(
            ["wmic", "process", "where",
             "name='msedge.exe' or name='chrome.exe'",
             "get", "ProcessId,CommandLine"],
            text=True, errors="replace", timeout=10,
            **no_window_kwargs(),
        )
    except Exception:
        out = ""
    for line in out.splitlines():
        low = line.lower().replace("/", "\\")
        if needle in low:
            m = re.search(r"(\d+)\s*$", line.strip())
            if m:
                subprocess.run(["taskkill", "/F", "/T", "/PID", m.group(1)],
                               capture_output=True, **no_window_kwargs())
                killed += 1
    # 兜底: wmic 没查到但 pid 档案在 → 直接按 pid 杀
    if killed == 0 and BROWSER_PID_FILE.exists():
        pid = BROWSER_PID_FILE.read_text().split()[0]
        if pid.isdigit() and _pid_alive(int(pid)):
            subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True,
                           **no_window_kwargs())
            killed += 1
        else:
            try:
                BROWSER_PID_FILE.unlink(missing_ok=True)
            except OSError:
                pass
    if killed:
        time.sleep(1.5)  # 等句柄/锁释放
    return killed


def _kill_stale_posix() -> int:
    killed = 0
    if BROWSER_PID_FILE.exists():
        raw = BROWSER_PID_FILE.read_text(encoding="utf-8", errors="replace").split()
        pid = raw[0] if raw else ""
        if pid.isdigit() and _pid_alive(int(pid)):
            try:
                os.kill(int(pid), 15)
                killed += 1
            except OSError:
                pass
        else:
            try:
                BROWSER_PID_FILE.unlink(missing_ok=True)
            except OSError:
                pass
    needle = str(EDGE_PROFILE)
    try:
        r = subprocess.run(
            ["pkill", "-f", needle],
            capture_output=True, timeout=5,
            **no_window_kwargs(),
        )
        if r.returncode == 0:
            killed += 1
    except Exception:
        pass
    if killed:
        time.sleep(1.0)
    return killed


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return True
        except Exception:
            return False
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _clean_singleton_locks():
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        try:
            (EDGE_PROFILE / name).unlink(missing_ok=True)
        except OSError:
            pass


# ---------- 后台静默：专属浏览器不抢 BRO 的前台（2026-09-20） ----------

_PID_CACHE: tuple[float, set[int]] = (0.0, set())


def _own_browser_pids(ttl: float = 30.0) -> set[int]:
    """本 profile 的浏览器主进程 pid。

    优先 pid 档案（daemon 拉起浏览器时写的，零成本）；档案缺失/进程已死才回退
    wmic 按命令行匹配（带 30s 缓存）。绝不认用户日常浏览器。
    """
    global _PID_CACHE
    if os.name != "nt":
        return set()
    try:
        if BROWSER_PID_FILE.exists():
            raw = BROWSER_PID_FILE.read_text(encoding="utf-8", errors="replace").split()
            if raw and raw[0].isdigit() and _pid_alive(int(raw[0])):
                return {int(raw[0])}
    except Exception:
        pass
    now = time.time()
    if _PID_CACHE[1] and now - _PID_CACHE[0] < ttl:
        return _PID_CACHE[1]
    try:
        out = subprocess.check_output(
            ["wmic", "process", "where",
             "name='msedge.exe' or name='chrome.exe'",
             "get", "ProcessId,CommandLine"],
            text=True, errors="replace", timeout=10, **no_window_kwargs(),
        )
    except Exception:
        return _PID_CACHE[1]
    needle = str(EDGE_PROFILE).lower().replace("/", "\\")
    pids: set[int] = set()
    for line in out.splitlines():
        if needle in line.lower().replace("/", "\\"):
            m = re.search(r"(\d+)\s*$", line.strip())
            if m:
                pids.add(int(m.group(1)))
    _PID_CACHE = (now, pids)
    return pids


def _main_window_hwnds(pids: set[int]) -> list[int]:
    """专属浏览器的顶层主窗口句柄（类名 Chrome_WidgetWin_1，不碰 IME 之类的杂窗）。"""
    if os.name != "nt" or not pids:
        return []
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        found: list[int] = []
        CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def _cb(hwnd, _lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids:
                cls = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(hwnd, cls, 64)
                if cls.value == "Chrome_WidgetWin_1":
                    found.append(int(hwnd))
            return True

        user32.EnumWindows(CB(_cb), 0)
        return found
    except Exception:
        return []


def _fg_hwnd() -> int:
    try:
        import ctypes
        return int(ctypes.windll.user32.GetForegroundWindow())
    except Exception:
        return 0


def _is_minimized(hwnd: int) -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.user32.IsIconic(hwnd))
    except Exception:
        return True


@contextlib.contextmanager
def silent_window():
    """让专属浏览器后台干活时保持"收着"，不顶掉 BRO 正在用的窗口。

    为什么要这层：Playwright 的 page.bring_to_front() / context.new_page() 走 CDP
    Target.activateTarget —— 会把最小化的专属窗口还原并抢前台（2026-09-20 实测坐实）。
    daemon 的浏览器是后台干活的，不该打断 BRO 手上的事。

    进时记下「自己的窗口 / 谁在前台 / 谁本来是收着的」，出时把被顶起来的收回去。
    任何一步失败都静默放过——这是体贴，不是能力依赖。非 Windows 直接 no-op。
    """
    if os.name != "nt":
        yield
        return
    own = _main_window_hwnds(_own_browser_pids())
    fg_before = _fg_hwnd()
    was_min = {h: _is_minimized(h) for h in own}
    # 2026-09-30 · 兜住「首次现场拉起浏览器」这条路径。
    # 病: ensure_cdp 拉起的窗口在快照【之后】才出现, was_min 里根本没有它;
    #     而 Playwright 的 new_page() 走 CDP Target.activateTarget 会把最小化的窗口
    #     还原顶到前台 —— 于是新窗口没人收, BRO 看到浏览器自己弹出来
    #     (原话:「你现在调用浏览器的时候，为什么又会跑到前台了？之前不都是静默的吗」)。
    # 判据: 进这一个上下文时, 我自己的窗口【一个都没露在外面】(全收着 / 压根没起)
    #   → 那出的时候凡是露着的, 只可能是被这趟操作顶出来的, 一律收回。
    #   反之进时就露着(说明 BRO 自己正在用专属浏览器) → 照旧不碰, 不会误伤。
    all_hidden_before = all(was_min.values()) if own else True
    disturbed = False   # 本趟是否真动过自己的窗口(决定出时要不要还前台)
    try:
        yield
    finally:
        try:
            import ctypes
            user32 = ctypes.windll.user32
            cur_own = set(own) | set(_main_window_hwnds(_own_browser_pids()))
            for h in cur_own:
                # 只处理「进就快照里、且原本收着」的窗口：被顶出来就收回去。
                # 快照之后新冒出来的窗口（不在 was_min 里）默认不碰 —— 那可能是
                # BRO 自己刚点开的，误最小化比不还原更糟（2026-09-20 审查坐实：
                # 默认 True 会误伤他正在用的窗口）。
                # 例外: all_hidden_before —— 进时我一个都没露, 那就是我自己拉起来的, 得收。
                if (was_min.get(h, False) or (all_hidden_before and h not in was_min)) \
                        and not user32.IsIconic(h):
                    user32.ShowWindow(h, 6)  # SW_MINIMIZE
                    disturbed = True
            # 2026-10-01 (wish-94b2546b) · 放宽还原条件。
            # 老条件「出时前台还停在我的窗口上」有个盲区：一旦系统把 BRO 自己的别的
            # 窗口(实测是 Chrome)顶到了前台，条件就不成立 → 不还 → 他的游戏回不去。
            # 现在补一条：只要【我确实动过自己的窗口】(disturbed) 且【出时前台已经不是我
            # 进来时那个】→ 也尝试还。
            # 不误伤的依据：Windows 只允许【当前前台进程】调 SetForegroundWindow —— BRO
            # 若在这几秒自己切了窗口，本进程已非前台，这次调用会被系统直接拒。
            # 而「没动过窗口」的路径(disturbed=False)完全不碰前台，行为与旧版一致。
            fg_now = user32.GetForegroundWindow()
            if fg_before and fg_before not in cur_own \
                    and (fg_now in cur_own or (disturbed and fg_now != fg_before)):
                try:
                    user32.SetForegroundWindow(fg_before)
                except Exception:
                    pass
        except Exception:
            pass


@contextlib.contextmanager
def peeking():
    """截图专用：临时把收着的窗口"展开到屏幕外且不激活"，截完立刻收回。

    为什么要这一步：最小化的窗口没有合成帧 —— 原生 page.screenshot 会超时
    （30s）、CDP Page.captureScreenshot 会直接挂死（2026-09-20 实测坐实）。
    窗口在屏幕外展开时合成器正常工作，截图可靠且 BRO 看不见、焦点不受影响。
    本来就是展开的窗口（BRO 在自己看）不动。
    """
    if os.name != "nt":
        yield
        return
    hwnds = _main_window_hwnds(_own_browser_pids())
    minimized = [h for h in hwnds if _is_minimized(h)]
    if not minimized:
        yield
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        SWP_NOACTIVATE, SWP_NOZORDER = 0x0010, 0x0004
        for h in minimized:
            user32.SetWindowPos(h, 1, -32000, -32000, 1280, 800,
                                SWP_NOACTIVATE | SWP_NOZORDER)  # 1 = HWND_BOTTOM
            user32.ShowWindow(h, 4)  # SW_SHOWNOACTIVATE（显示但不抢焦点）
        time.sleep(0.6)              # 等合成器出一帧
    except Exception:
        pass
    try:
        yield
    finally:
        try:
            import ctypes
            user32 = ctypes.windll.user32
            for h in minimized:
                user32.ShowWindow(h, 6)  # SW_MINIMIZE · 收回
        except Exception:
            pass


def cdp_healthy() -> bool:
    """/json/version 200 且至少有一个 page target —— 白屏僵尸(主进程活、渲染全崩)判不健康。"""
    if not cdp_available():
        return False
    try:
        targets = httpx.get(f"{CDP_URL}/json/list", timeout=2.0).json()
        return any(t.get("type") == "page" for t in targets)
    except Exception:
        return False


def restart_browser(wait_secs: int = 25) -> bool:
    """杀僵尸 + 清锁 + 重拉专属浏览器。"""
    _kill_stale_browser()
    _clean_singleton_locks()
    return ensure_cdp(launch=True, wait_secs=wait_secs)


def ensure_cdp(launch: bool = True, wait_secs: int = 25) -> bool:
    """确保 daemon 专属 CDP Edge 在跑且健康。

    健康 → True；不健康/没在且 launch → 清僵尸+锁后重拉。
    起不来（没装 Edge/Chrome / 端口没拉起）→ False，由调用方给出可读错误。
    """
    with _CDP_LOCK:
        # 2026-09-20 · 首次拉起浏览器时窗口创建会抢一次 BRO 前台 → 静默包住，
        # 启动完自动收位（实测：重启后前台会变成"新标签页"）。
        with silent_window():
            return _ensure_cdp_locked(launch, wait_secs)


def _ensure_cdp_locked(launch: bool = True, wait_secs: int = 25) -> bool:
    """确保 daemon 专属 CDP Edge 在跑且健康。

    健康 → True；不健康/没在且 launch → 清僵尸+锁后重拉。
    起不来（没装 Edge/Chrome / 端口没拉起）→ False，由调用方给出可读错误。
    """
    if cdp_healthy():
        return True
    if not launch:
        return False
    # 半死/尸体: 端口被占但 CDP 不应答 → 先清僵尸+锁, 否则 Popen 撞单实例锁静默退出
    if cdp_available() or BROWSER_PID_FILE.exists():
        _kill_stale_browser()
        _clean_singleton_locks()
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
        # 2026-09-15 · 后台干活不抢 BRO 焦点：daemon 拉起的专属 Edge 一律最小化
        # 起（偶尔需要看时任务栏点回来即可）。CDP 是独立通道，最小化不影响任何
        # browser_act / browser_fetch 能力。
        "--start-minimized",
        # 2026-09-20 · 窗口长期收着也不让页面装死：后台/被遮挡时照常跑 JS 定时器与渲染，
        # 否则最小化状态下的自动化点击/等待会踩到「页面被节流」
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
    ]
    popen_kw: dict = {"close_fds": True}
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP —— Edge 不随 daemon 重启而死
        popen_kw["creationflags"] = 0x00000008 | 0x00000200
    else:
        popen_kw["start_new_session"] = True
    try:
        proc = subprocess.Popen(args, **popen_kw)
        BROWSER_PID_FILE.write_text(f"{proc.pid} {time.time():.0f}", encoding="utf-8")
    except Exception:
        return False
    for _ in range(max(1, wait_secs)):
        if cdp_healthy():
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
