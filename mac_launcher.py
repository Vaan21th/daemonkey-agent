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
        self.win = None
        self.daemon = None               # subprocess.Popen
        self.opts = {"daemon": True, "pet": False, "browser": True, "crash": True}
        self.port = PORT
        self._stop = threading.Event()
        self._watch = None

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
            self.log("(Mac v0: 最小化走系统按钮)")
        elif t == "close":
            self.log("关闭窗口 · 启动器退出 (daemon 继续后台运行)")
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
    win = webview.create_window(
        "Daemonkey",
        html,
        js_api=api,
        width=1080,
        height=700,
        min_size=(960, 620),
    )
    api.win = win
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
    webview.start()
    api._stop.set()


if __name__ == "__main__":
    main()
