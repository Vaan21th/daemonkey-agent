#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daemonkey · macOS 启动器壳 (pywebview) v0
=========================================
与 Windows daemonkey-launcher.ps1 对齐 · 同一份 assets/launcher.html (月光操作台)
Mac:  pywebview (WKWebView) 加载 → 桥接 shim (launcher.html 内置 pywebview 分支)
Win:  同一份代码可跑 (pywebview 走 EdgeChromium) · 用于本地开发验证

用法:
    pip install pywebview
    python3 mac_launcher.py          # Mac 上双击/终端跑
    OPUS_API_PORT=7860 python3 mac_launcher.py   # 换端口

功能 (v0):
  · 启动/停止 daemon (tools/run_api_only.py)
  · 状态推送 (运行中/已停止 · 版本 · 端口)
  · 崩溃自动拉起 (异常退出 90s 后自动重启)
  · 日志推送 (启动器事件 → 终端页/事件区)
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections import deque

# 托盘 (pystray + Pillow) · Mac 菜单栏常驻 · 装不上就跳过 (启动器窗口还能用)
# 分开 try: PIL (Pillow) 在 requirements 必有 (视觉能力) · pystray 才是有无托盘的关键
try:
    from PIL import Image, ImageDraw
except Exception:
    Image = ImageDraw = None

try:
    import pystray
    _HAS_TRAY = Image is not None   # 托盘需要 PIL 画图标
except Exception:
    _HAS_TRAY = False

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("OPUS_API_PORT", "7860"))

# ── 打包/源码 路径分叉 (2026-08-15 v1 · 首装引导) ──
#   源码跑: daemon 代码就在本目录 · 资产 assets/ 同级
#   打包跑 (PyInstaller .app): daemon 代码首装 clone 到 ~/Daemonkey ·
#   资产在 .app 内部 sys._MEIPASS/assets (launcher.html 等随包带走)
FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    DAEMON_DIR = os.path.expanduser("~/Daemonkey")      # 首装 git clone 到这
    ASSET_DIR = os.path.join(sys._MEIPASS, "assets")     # 打包资产目录
else:
    DAEMON_DIR = os.path.dirname(os.path.abspath(__file__))
    ASSET_DIR = os.path.join(DAEMON_DIR, "assets")
ROOT = DAEMON_DIR   # 后面全部 cwd/路径逻辑跟着走 (venv/run_api_only/core_manifest)


def ensure_daemon_dir(api):
    """首装引导 (仅打包模式): 确保 ~/Daemonkey 有 daemon 代码 + venv + 依赖。

    对齐 Windows 一键链路 (Ensure-RepoAndSource):
      无代码 → git clone gitee → 建 .venv → pip install -r requirements.txt
    源码模式直接过 (代码就在旁边)。 进度经 api.log 推送到启动器 UI。
    """
    if not FROZEN:
        return True, "源码模式"
    d = DAEMON_DIR
    code_ok = os.path.exists(os.path.join(d, "tools", "run_api_only.py"))
    if not code_ok:
        api.log("首次使用 · 正在拉取 Daemonkey 代码...", "warn")
        try:
            r = subprocess.run(["git", "clone", "--depth", "1",
                                "https://gitee.com/vaan21th/dae-monkey.git", d],
                               capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                return False, f"git clone 失败: {r.stderr[-200:]}"
        except Exception as e:
            return False, f"clone 异常: {e}"
    py_venv = os.path.join(d, ".venv", "bin", "python")
    if not os.path.exists(py_venv):
        api.log("首次使用 · 创建运行环境 (venv)...", "warn")
        try:
            subprocess.run(["python3", "-m", "venv", os.path.join(d, ".venv")],
                           timeout=300)
        except Exception as e:
            return False, f"venv 创建失败: {e}"
    api.log("首次使用 · 安装依赖 (几分钟·请稍候)...", "warn")
    try:
        subprocess.run([py_venv, "-m", "pip", "install", "--upgrade", "pip", "-q"],
                       timeout=300)
        r = subprocess.run([py_venv, "-m", "pip", "install", "-r",
                            os.path.join(d, "requirements.txt"), "-q"],
                           timeout=900)
        if r.returncode != 0:
            return False, f"依赖安装失败: {r.stderr[-200:]}"
    except Exception as e:
        return False, f"依赖异常: {e}"
    return True, "就绪"


class LauncherApi:
    """HTML (launcher.html) ↔ Python 桥接。HTML 侧经 pywebview shim
    调 window.pywebview.api.on_msg(jsonStr)；Python 侧经 win.evaluate_js
    调 window._dkRecv(jsonStr) 回推。"""

    def __init__(self):
        self.win = None                  # 主窗口 (launcher.html)
        self.guard_win = None            # 守护面板窗口 (guard-panel.html)
        self.daemon = None               # subprocess.Popen
        self.opts = {"daemon": True, "pet": False, "browser": True, "crash": True}
        self.port = PORT
        self._stop = threading.Event()
        self._watch = None
        self._tray = None
        self._tray_th = None
        self._started_at = time.time()   # 守护面板「已运行」时长
        self.events = deque(maxlen=8)    # 事件环形缓冲 (守护面板最近事件)

    # ─────────────────────── HTML → Python ───────────────────────

    def on_msg(self, payload_json):
        try:
            msg = json.loads(payload_json)
        except Exception:
            return
        t = msg.get("type")
        if t == "start":
            self.start_daemon()
        elif t == "opt":
            key = msg.get("key")
            if key in self.opts:
                self.opts[key] = bool(msg.get("on"))
                self.log(f"开关 {key} → {'开' if self.opts[key] else '关'}")
                self.push_state()
        elif t == "port":
            try:
                self.port = int(msg.get("text", str(PORT)))
                self.log(f"端口 → {self.port}")
            except ValueError:
                pass
        elif t == "action":
            self.on_action(msg.get("id"))
        elif t == "openurl":
            self.on_openurl(msg.get("id"))
        elif t == "min":
            # 最小化 = 收托盘 (托盘常驻 · 点图标呼出)
            self.hide_main()
        elif t == "close":
            # 关主窗口 = 收托盘 (daemon 继续跑 · 托盘常驻)
            self.log("窗口已收托盘 · 点托盘图标呼出 (daemon 继续运行)", "warn")
            self.hide_main()
        elif t == "gclose":
            # 守护面板关闭 (guard-panel.html 专属 · 与主窗口 close 区分)
            self.hide_guard()
        elif t == "open":
            # 守护面板「打开启动器」
            self.show_main()
        elif t == "nav":
            pass  # 页面切换无需后端动作
        elif t == "drag":
            pass  # v0: 窗口拖动走系统标题栏 (无边框在 Mac 上可后续加)

    def on_action(self, action_id):
        if action_id == "restart":
            self.restart_daemon()
        elif action_id == "stop":
            self.stop_daemon()

    def on_openurl(self, url_id):
        import webbrowser
        links = {
            "api-deepseek": "https://platform.deepseek.com/",
            "api-glm": "https://open.bigmodel.cn/",
        }
        url = links.get(url_id)
        if url:
            webbrowser.open(url)

    # ─────────────────────── daemon 启停 ───────────────────────

    def _python(self):
        # 跨平台: POSIX (.venv/bin/python) / Windows (.venv\Scripts\python.exe)
        for py in (os.path.join(ROOT, ".venv", "bin", "python"),
                   os.path.join(ROOT, ".venv", "Scripts", "python.exe")):
            if os.path.exists(py):
                return py
        return "python3"

    def start_daemon(self):
        if self.daemon and self.daemon.poll() is None:
            self.log(f"daemon 已在运行 (pid={self.daemon.pid})", "ok")
            return
        try:
            self.daemon = subprocess.Popen(
                [self._python(), "tools/run_api_only.py", "--host", "127.0.0.1",
                 "--port", str(self.port)],
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.log(f"daemon 启动中 (pid={self.daemon.pid}) …", "warn")
            threading.Thread(target=self._wait_up, daemon=True).start()
            self.push_state()
        except Exception as e:
            self.log(f"daemon 启动失败: {e}", "err")

    def _wait_up(self):
        for _ in range(90):
            if self._port_open(self.port):
                self.log(f"daemon 已就绪 · http://127.0.0.1:{self.port}", "ok")
                self.push_state()
                return
            time.sleep(0.5)
        self.log("daemon 等待超时 (45s) · 看日志", "err")

    def stop_daemon(self):
        if self.daemon and self.daemon.poll() is None:
            pid = self.daemon.pid
            self.daemon.terminate()
            try:
                self.daemon.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.daemon.kill()
            self.log(f"daemon 已停止 (pid={pid})", "ok")
        else:
            self.log("daemon 未在运行", "warn")
        self.push_state()

    def restart_daemon(self):
        self.stop_daemon()
        time.sleep(1)
        self.start_daemon()

    @staticmethod
    def _port_open(port):
        s = socket.socket()
        s.settimeout(0.3)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False
        finally:
            s.close()

    # ─────────────────────── Python → HTML ───────────────────────

    def push(self, payload):
        if not self.win:
            return
        try:
            js = json.dumps(json.dumps(payload, ensure_ascii=False))
            self.win.evaluate_js(f"window._dkRecv({js})")
        except Exception:
            pass

    def push_state(self):
        running = self.daemon is not None and self.daemon.poll() is None
        self.push({
            "type": "state",
            "ver": self._version(),
            "opts": dict(self.opts),
            "port": str(self.port),
            "status": "running" if running else "stopped",
            "btn": {"text": "停止 daemon" if running else "启动 daemon", "enabled": True},
        })

    def log(self, text, kind="line"):
        self.push({"type": "log", "log": text, "logKind": kind})
        # 事件缓冲 (守护面板最近事件) · 只记关键级别
        if kind in ("ok", "warn", "err"):
            t = time.strftime("%H:%M")
            self.events.appendleft({"t": t, "kind": kind, "msg": text})
            self.push_guard_state()

    # ─────────────────────── 托盘 (pystray · Mac 菜单栏常驻) ───────────────────────

    def _tray_image(self):
        """64×64 紫底圆角 + 白色月牙 (和启动器主视觉呼应)。"""
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([2, 2, 62, 62], radius=16, fill=(124, 108, 240, 255))
        d.ellipse([15, 13, 45, 43], fill=(255, 255, 255, 255))
        d.ellipse([26, 13, 52, 43], fill=(124, 108, 240, 255))
        return img

    def start_tray(self):
        if not _HAS_TRAY or self._tray:
            return
        try:
            menu = pystray.Menu(
                pystray.MenuItem("打开启动器", self.show_main, default=True),
                pystray.MenuItem("守护面板", self.show_guard),
                pystray.MenuItem("崩溃自动拉起", self._tray_toggle_crash,
                                 checked=lambda item: bool(self.opts.get("crash"))),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", self._tray_quit),
            )
            self._tray = pystray.Icon("daemonkey", self._tray_image(), "Daemonkey", menu)
            self._tray_th = threading.Thread(target=self._tray.run, daemon=True)
            self._tray_th.start()
            self.log("托盘已就绪 · 菜单栏图标常驻", "ok")
        except Exception as e:
            self.log(f"托盘启动失败: {e} (不影响启动器)", "err")

    def _tray_toggle_crash(self, icon, item):
        self.opts["crash"] = not self.opts.get("crash")
        self.log(f"崩溃自动拉起 → {'开' if self.opts['crash'] else '关'}", "warn")
        self.push_guard_state()

    def _tray_quit(self, icon, item):
        # 全退: 停 daemon + 退托盘 + 关窗口
        try:
            self.stop_daemon()
        except Exception:
            pass
        self._stop.set()
        try:
            icon.stop()
        except Exception:
            pass
        for w in (self.guard_win, self.win):
            if w:
                try:
                    w.destroy()
                except Exception:
                    pass
        time.sleep(1.5)
        os._exit(0)   # 保底退出

    # ─────────────────────── 窗口显隐 ───────────────────────

    def show_main(self, icon=None, item=None):
        if self.win:
            try:
                self.win.show()
            except Exception:
                pass

    def hide_main(self):
        if self.win:
            try:
                self.win.hide()
            except Exception:
                pass

    def show_guard(self, icon=None, item=None):
        if self.guard_win:
            try:
                self.guard_win.show()
                self.push_guard_state()
            except Exception:
                pass

    def hide_guard(self):
        if self.guard_win:
            try:
                self.guard_win.hide()
            except Exception:
                pass

    # ─────────────────────── 守护面板状态推送 ───────────────────────

    def push_guard_state(self):
        if not self.guard_win:
            return
        running = self.daemon is not None and self.daemon.poll() is None
        if running and self.daemon:
            pid = self.daemon.pid
            uptime = int(time.time() - self._started_at)
            m, s = divmod(uptime, 60)
            h, m = divmod(m, 60)
            dur = f"{h}小时{m}分" if h else f"{m}分{s}秒"
            detail = f"PID {pid} | 端口 {self.port} | 已运行 {dur}"
        else:
            detail = f"端口 {self.port}"
        payload = {
            "st": "running" if running else "stopped",
            "main": "守护中 · daemon 运行正常" if running else "已停止 · daemon 未运行",
            "detail": detail,
            "auto": bool(self.opts.get("crash")),
            "sub": "daemonkey-launcher · 守护进程",
            "events": list(self.events)[:3],
        }
        try:
            js = json.dumps(json.dumps(payload, ensure_ascii=False))
            self.guard_win.evaluate_js(f"window._dkRecv({js})")
        except Exception:
            pass

    def _version(self):
        try:
            with open(os.path.join(ROOT, "core_manifest.json"), encoding="utf-8-sig") as f:
                cv = json.load(f).get("core_version", "?")
            return f"v{cv}"
        except Exception:
            return "v?"

    # ─────────────────────── 崩溃自动拉起 ───────────────────────

    def start_watch(self):
        def loop():
            while not self._stop.is_set():
                if (self.opts.get("crash") and self.daemon
                        and self.daemon.poll() is not None):
                    self.log("daemon 异常退出 · 90s 后自动拉起", "err")
                    time.sleep(90)
                    if (self.opts.get("crash")
                            and (self.daemon is None or self.daemon.poll() is not None)):
                        self.start_daemon()
                time.sleep(5)

        self._watch = threading.Thread(target=loop, daemon=True)
        self._watch.start()


def main():
    import webview

    api = LauncherApi()
    html = os.path.join(ASSET_DIR, "launcher.html")
    guard_html = os.path.join(ASSET_DIR, "guard-panel.html")

    # 主窗口 (月光操作台)
    win = webview.create_window(
        "Daemonkey",
        html,
        js_api=api,
        width=1080,
        height=700,
        min_size=(960, 620),
    )
    api.win = win
    api.main_win = win

    # 守护面板窗口 (预创建 · 隐藏 · 托盘呼出) · 同一份 guard-panel.html (跨平台)
    try:
        guard = webview.create_window(
            "Daemonkey 守护",
            guard_html,
            js_api=api,
            width=380,
            height=430,
            hidden=True,
            on_top=True,
        )
        api.guard_win = guard
    except Exception as e:
        api.log(f"守护面板窗口创建失败: {e}", "err")
    # 首装引导 (打包模式): 后台线程跑 · 进度经 api.log 推送到 UI · 不阻塞窗口
    if FROZEN:
        def _ensure():
            ok, note = ensure_daemon_dir(api)
            if ok:
                api.log("运行环境就绪 · 点【启动 daemon】开始", "ok")
            else:
                api.log(f"⚠ 首次安装失败: {note} · 可关掉重开重试", "err")
        threading.Thread(target=_ensure, daemon=True).start()
    api.start_watch()
    api.start_tray()
    api.log("守护面板已就绪 · 托盘常驻", "ok")
    webview.start()
    api._stop.set()


if __name__ == "__main__":
    main()
