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
    html = os.path.join(ROOT, "assets", "launcher.html")
    win = webview.create_window(
        "Daemonkey",
        html,
        js_api=api,
        width=1080,
        height=700,
        min_size=(960, 620),
    )
    api.win = win
    api.start_watch()
    webview.start()
    api._stop.set()


if __name__ == "__main__":
    main()
