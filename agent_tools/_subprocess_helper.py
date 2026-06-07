"""
agent_tools/_subprocess_helper.py
=================================

daemon 跑子进程的**统一姿势** · 避免 Windows 黑框 console 窗口弹出。

为什么需要这个 helper:
  - daemon 跑在 DETACHED_PROCESS 模式 · 自己没 console
  - daemon 通过 subprocess.run/Popen 启子进程 (git / python / curl / ssh / ...)
  - Windows 行为: 父进程没 console 时 · 子进程默认会**自动创建新 console** ·
    即使命令 < 100ms · 黑框也会闪一下
  - 修法 ①: 给 subprocess 调用加 creationflags=CREATE_NO_WINDOW (Windows 后台进程标准做法)
  - 修法 ②: startupinfo 设 SW_HIDE (belt-and-suspenders · 续 · wish-503f93e0 补漏 —
    CREATE_NO_WINDOW 在某些 Windows 版本对 python.exe (console subsystem) 不完全生效 ·
    STARTF_USESHOWWINDOW + SW_HIDE 在内核层直接不让窗口出现)
  - 修法 ③: spawn daemon 自身用 pythonw.exe (GUI subsystem · Windows 从不给它分配 console ·
    续二 · 2026-05-29 — python.exe 作为 console subsystem PE · 无论什么 flag ·
    内核在 CreateProcess 最早期就分配了 console · CREATE_NO_WINDOW + SW_HIDE 只能事后补救 ·
    仍有微秒级闪窗。pythonw.exe 根治)
  - 历史教训: 17 个 .py 用 subprocess · 13 个分散在各处忘加 flag ·
    每个新工具都可能再翻车 · 抽到一处统一管 ( IV)

三个 helper:
  - no_window_kwargs()   : 普通子进程 (短任务 · daemon 等返回)
  - detached_kwargs()    : detach 长跑 (spawn 新 daemon / web service · 父退后子继续)
  - pythonw_path()       : 拿 pythonw.exe 路径 · spawn daemon 自身用 (不弹 console)

POSIX 上 CREATE_NO_WINDOW 不存在 · helper 自动降级为空 dict (零跨平台风险)。

用法:
  proc = subprocess.run(argv, capture_output=True, **no_window_kwargs())
  subprocess.Popen(argv, stdout=..., **detached_kwargs())
  spawn_argv = [pythonw_path()] + sys.argv  # 重启 daemon 用
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


_IS_WINDOWS = sys.platform.startswith("win")


# 续 · wish-503f93e0 补漏 · 2026-05-29
# CREATE_NO_WINDOW 对 python.exe (console subsystem PE) 在某些 Windows 版本不完全生效
# belt-and-suspenders: 同时设 creationflags=CREATE_NO_WINDOW + startupinfo.SW_HIDE
# SW_HIDE 在内核层直接不让窗口出现 · 跟 CreateProcess dwFlags 正交 · 不冲突

def _make_startupinfo_hidden():
    """构造一个 SW_HIDE 的 STARTUPINFO · 确保子进程窗口不出现在任务栏/屏幕。"""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # 1
    si.wShowWindow = subprocess.SW_HIDE             # 0
    return si


def pythonw_path() -> str:
    """返回 pythonw.exe 的绝对路径 · spawn daemon 自身时用它不弹 console。

    pythonw.exe 跟 python.exe 在同一目录 · 同版本 · 唯一的区别是 PE subsystem:
      - python.exe  → IMAGE_SUBSYSTEM_WINDOWS_CUI (console) → Windows 分配 console
      - pythonw.exe → IMAGE_SUBSYSTEM_WINDOWS_GUI (GUI)     → Windows 不分配 console

    GUI subsystem 的代价: sys.stdout/stderr 可能为 None · 但 daemon spawn 时
    stdout/stderr 已被 Popen 重定向到文件 · Python 能正确初始化 sys.stdout。

    如果 pythonw.exe 不存在 (极罕见 · 某些精简 Python 发行版) → 回退 python.exe。
    """
    if not _IS_WINDOWS:
        return sys.executable

    exe = Path(sys.executable)
    pyw = exe.parent / "pythonw.exe"
    if pyw.exists():
        return str(pyw)
    # fallback: 某些精简发行版没 pythonw.exe
    return sys.executable


def no_window_kwargs() -> dict:
    """普通子进程不弹 console 窗口。

    使用场景:
      - shell_exec / python_exec 跑命令
      - 工具内调 git / ssh / clipboard / rg 等

    返回值: { 'creationflags': CREATE_NO_WINDOW, 'startupinfo': SW_HIDE } on Windows · {} on POSIX
    """
    if _IS_WINDOWS:
        return {
            "creationflags": subprocess.CREATE_NO_WINDOW,
            "startupinfo": _make_startupinfo_hidden(),
        }
    return {}


def detached_kwargs() -> dict:
    """detach 长跑子进程 · 父进程退出后子进程继续。

    使用场景:
      - lifecycle.py / request_restart.py spawn 新 daemon
      - service_runner 起 web service / app runtime

    Windows: DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW + SW_HIDE startupinfo
    POSIX:   start_new_session=True (跟 setsid 等效)
    """
    if _IS_WINDOWS:
        return {
            "creationflags": (
                0x00000008  # DETACHED_PROCESS · 子进程不附父 console
                | 0x00000200  # CREATE_NEW_PROCESS_GROUP · 独立信号组
                | subprocess.CREATE_NO_WINDOW  # 不显示 console
            ),
            "startupinfo": _make_startupinfo_hidden(),
        }
    return {"start_new_session": True}
