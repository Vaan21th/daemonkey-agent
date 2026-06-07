"""
workers/service_runner.py
==========================

卷四十四 K stage 2c++ · wish-8d6b76a6 — OPUS 启长跑服务的正确姿势

**为什么有这个**:
  shell_exec 设计来跑短任务 (默认 30s · 最长 300s)。 OPUS 起 GPT-SoVITS api.py /
  Stable Diffusion / 自己造的 API 服务这种典型长跑后台 · shell_exec 等 subprocess exit
  → timeout 后子进程成孤儿 (Windows PID 17720 真实事故)。

  这个 module 做"detach 启动 + 持久化 + healthcheck + 状态查询"四件套 · 让 OPUS 起服务
  成为一个清晰的工具语义 · 跟 shell_exec (短任务) 彻底分开。

**核心思路**:
  - spawn 用 platform-specific detach (Win: DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
    + (Unix: start_new_session) · daemon 死了子进程也能继续跑
  - 状态落 `data/runtime/services.json` (atomic write) · daemon 重启后仍能 list/stop
  - log 落 `data/runtime/service_logs/<name>.log` · BRO 排错时 OPUS 调 read_file 看
  - PID 是否活的 · 用 psutil (已是 daemon 依赖)

**安全约束** (在工具层 + module 层共同保证):
  - service name 严格 [a-zA-Z0-9_-]{1,64} · 不允许 path traversal
  - 一个 name 一个 service · 重复要先 stop
  - working_dir 必须存在且是目录
  - env 是 dict · merge 进 os.environ (不是替换)
  - shell=True 是有意保留 (OPUS 经常需要 conda activate / set 环境变量后再跑)
  - 但工具层是 TIER_CONFIRM · BRO 看摘要 ✓ 才跑

**跟铁律的协同** (工具描述里强调):
  - BRO 说"建 X API 应用" → create_app 落档 → service_start (不是 shell_exec)
  - 跑 git status / cat 文件 / 短脚本 → shell_exec
  - 起本地 server / api / scheduler → service_start
"""
from __future__ import annotations

import json
import os
import platform
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx
import psutil

from agent_tools._subprocess_helper import detached_kwargs


# ───────────────────────────── 路径 ─────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = ROOT / "data" / "runtime"
SERVICES_FILE = RUNTIME_DIR / "services.json"
LOG_DIR = RUNTIME_DIR / "service_logs"

NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


# ───────────────────────────── 状态文件 IO ─────────────────────────────

def _ensure_dirs() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _load_services() -> dict[str, dict]:
    _ensure_dirs()
    if not SERVICES_FILE.exists():
        return {}
    try:
        data = json.loads(SERVICES_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data.get("services") or {}
    except Exception:
        pass
    return {}


def _save_services(services: dict[str, dict]) -> None:
    _ensure_dirs()
    payload = {"version": 1, "services": services, "saved_at": datetime.now().isoformat(timespec="seconds")}
    tmp = SERVICES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SERVICES_FILE)  # atomic on Windows + Unix


# ───────────────────────────── 进程检测 ─────────────────────────────

def _is_alive(pid: int) -> bool:
    """psutil 检测 pid 是否还活着 · 防止 PID reuse 误判"""
    try:
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    except Exception:
        return False


def _proc_meta(pid: int) -> dict:
    """拿到的元信息 (cpu / memory / running_time) · 失败返回 {}"""
    try:
        p = psutil.Process(pid)
        return {
            "running": p.is_running(),
            "status": p.status(),
            "cpu_percent": p.cpu_percent(interval=0.0),
            "rss_mb": round(p.memory_info().rss / (1024 * 1024), 1),
            "create_time": datetime.fromtimestamp(p.create_time()).isoformat(timespec="seconds"),
        }
    except Exception:
        return {}


# ───────────────────────────── spawn ─────────────────────────────

def _spawn_detached(
    command: str,
    working_dir: Path,
    env_extra: Optional[dict] = None,
    log_path: Optional[Path] = None,
) -> int:
    """
    detach 启动子进程 · daemon 死了它也能继续跑。
    log_path 给了就把 stdout/stderr 重定向过去 (append 模式) · 否则 DEVNULL。
    返回 pid。
    """
    # env merge · 不是替换
    full_env = os.environ.copy()
    if env_extra:
        full_env.update({str(k): str(v) for k, v in env_extra.items()})

    # log 重定向
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_f = open(log_path, "ab")  # append binary
        stdout_target = log_f
    else:
        log_f = None
        stdout_target = subprocess.DEVNULL

    # 卷四十六续 IV · detached_kwargs() 统一: Win 用 DETACHED|GROUP|NO_WINDOW · POSIX 用 start_new_session
    kwargs: dict[str, Any] = dict(
        cwd=str(working_dir),
        env=full_env,
        stdin=subprocess.DEVNULL,
        stdout=stdout_target,
        stderr=subprocess.STDOUT,
        shell=True,  # 让 OPUS 能用 conda activate / && / 管道
        **detached_kwargs(),
    )
    if platform.system() != "Windows":
        kwargs["close_fds"] = True  # POSIX 额外 · daemon 死了子进程不变僵尸

    proc = subprocess.Popen(command, **kwargs)
    # log_f 由子进程持有 · 我们关掉自己的引用 (子进程仍能写)
    if log_f is not None:
        try:
            log_f.close()
        except Exception:
            pass
    return proc.pid


# ───────────────────────────── healthcheck ─────────────────────────────

def _curl_check(url: str, timeout_s: float = 5.0) -> tuple[bool, str]:
    """curl 健康检查 · 返 (ok, message)"""
    try:
        r = httpx.get(url, timeout=timeout_s, follow_redirects=True)
        ok = 200 <= r.status_code < 500  # 4xx 也算"服务起来了" (404/401 表示 endpoint 路由生效)
        return ok, f"HTTP {r.status_code} · {len(r.content)} bytes"
    except httpx.TimeoutException:
        return False, "timeout"
    except httpx.ConnectError:
        return False, "connect refused (服务还没监听 / 或没起起来)"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ───────────────────────────── 高层 API ─────────────────────────────

def validate_name(name: str) -> tuple[bool, str]:
    if not name or not NAME_PATTERN.match(name):
        return False, f"service name 必须匹配 ^[a-zA-Z0-9_-]{{1,64}}$ (得到 {name!r})"
    return True, ""


def list_services() -> list[dict]:
    """返所有已知服务 · 含活/死状态"""
    services = _load_services()
    out = []
    for name, info in services.items():
        pid = info.get("pid")
        alive = _is_alive(pid) if pid else False
        meta = _proc_meta(pid) if alive else {}
        out.append({
            "name": name,
            "pid": pid,
            "port": info.get("port"),
            "alive": alive,
            "stopped": info.get("stopped", False),
            "started_at": info.get("started_at"),
            "command": info.get("command"),
            "working_dir": info.get("working_dir"),
            "log_path": info.get("log_path"),
            "healthcheck_url": info.get("healthcheck_url"),
            "meta": meta,
        })
    return out


def get_service(name: str) -> Optional[dict]:
    """详情 · 包括 alive 状态 + 元信息"""
    services = _load_services()
    info = services.get(name)
    if not info:
        return None
    pid = info.get("pid")
    alive = _is_alive(pid) if pid else False
    return {
        **info,
        "name": name,
        "alive": alive,
        "meta": _proc_meta(pid) if alive else {},
    }


def start_service(
    name: str,
    command: str,
    working_dir: str,
    env: Optional[dict] = None,
    port: Optional[int] = None,
    healthcheck_url: Optional[str] = None,
    healthcheck_after_sec: float = 5.0,
) -> dict:
    """
    启动服务 · 返 {ok, pid, status, healthcheck_status, log_path, message}
    (失败时 ok=False · 不抛异常 · 让上层工具决定怎么报给 LLM)
    """
    ok, msg = validate_name(name)
    if not ok:
        return {"ok": False, "message": msg}

    if not command or not command.strip():
        return {"ok": False, "message": "command 不能为空"}

    wd = Path(working_dir).resolve()
    if not wd.exists():
        return {"ok": False, "message": f"working_dir 不存在: {wd}"}
    if not wd.is_dir():
        return {"ok": False, "message": f"working_dir 不是目录: {wd}"}

    services = _load_services()
    existing = services.get(name)
    if existing and existing.get("pid") and _is_alive(existing["pid"]):
        return {
            "ok": False,
            "message": (
                f"service `{name}` 已经跑着 · pid={existing['pid']} (started_at={existing.get('started_at')}) · "
                f"先调 service_stop 再起新的"
            ),
        }

    log_path = LOG_DIR / f"{name}.log"

    try:
        pid = _spawn_detached(
            command=command,
            working_dir=wd,
            env_extra=env,
            log_path=log_path,
        )
    except Exception as e:
        return {"ok": False, "message": f"spawn 失败: {type(e).__name__}: {e}"}

    started_at = datetime.now().isoformat(timespec="seconds")
    info = {
        "pid": pid,
        "command": command,
        "working_dir": str(wd),
        "env": env or {},
        "port": port,
        "started_at": started_at,
        "log_path": str(log_path.relative_to(ROOT).as_posix()),
        "healthcheck_url": healthcheck_url,
        "stopped": False,
    }
    services[name] = info
    _save_services(services)

    # spawn 后 quick check · 子进程是不是立刻就崩了
    time.sleep(0.5)
    if not _is_alive(pid):
        return {
            "ok": False,
            "pid": pid,
            "log_path": str(log_path.relative_to(ROOT).as_posix()),
            "message": (
                f"spawn 返回 pid={pid} 但 0.5s 后子进程已经死了 · "
                f"基本上是 command 本身就崩 · 看 log: {log_path.relative_to(ROOT).as_posix()}"
            ),
        }

    # healthcheck (如果给了)
    health_status = None
    health_msg = ""
    if healthcheck_url:
        time.sleep(max(0.0, healthcheck_after_sec - 0.5))  # 减去刚才 sleep 的 0.5s
        health_status, health_msg = _curl_check(healthcheck_url)

    return {
        "ok": True,
        "pid": pid,
        "name": name,
        "started_at": started_at,
        "log_path": str(log_path.relative_to(ROOT).as_posix()),
        "healthcheck_status": health_status,
        "healthcheck_msg": health_msg,
        "message": (
            f"service `{name}` 启动成功 · pid={pid}"
            + (f" · port={port}" if port else "")
            + (f" · healthcheck={health_status} ({health_msg})" if healthcheck_url else "")
        ),
    }


def stop_service(name: str, timeout_sec: float = 5.0) -> dict:
    """
    优雅停止服务 · 先 SIGTERM/CTRL_BREAK_EVENT · 等 timeout · 还活就 SIGKILL/TerminateProcess
    返 {ok, message}
    """
    ok, msg = validate_name(name)
    if not ok:
        return {"ok": False, "message": msg}

    services = _load_services()
    info = services.get(name)
    if not info:
        return {"ok": False, "message": f"service `{name}` 没在记录里 · 调 service_list 看现有"}

    pid = info.get("pid")
    if not pid:
        info["stopped"] = True
        services[name] = info
        _save_services(services)
        return {"ok": True, "message": f"service `{name}` 没 pid 记录 · 标 stopped 即可"}

    if not _is_alive(pid):
        info["stopped"] = True
        services[name] = info
        _save_services(services)
        return {"ok": True, "message": f"service `{name}` (pid={pid}) 已经死了 · 标 stopped"}

    # shell=True 在 Win 下让 cmd.exe 包一层跑 Python · 我们记的 pid 是 cmd
    # .venv launcher 在 exec system Python 后会 exit · system Python 成孤儿
    # → children(recursive) 拿不到孤儿 · 但孤儿仍 listen 端口
    # 双保险: (a) 杀 parent + children 递归; (b) 如果 port 给了 · 兜底杀所有 listen 该 port 的 pid
    is_win = platform.system() == "Windows"
    port = info.get("port")

    def _collect_targets() -> list[psutil.Process]:
        """收集要杀的所有 process · 含 parent + children(recursive) + 监听同 port 的孤儿"""
        seen: set[int] = set()
        out: list[psutil.Process] = []
        try:
            p = psutil.Process(pid)
            out.append(p)
            seen.add(pid)
            for child in p.children(recursive=True):
                if child.pid not in seen:
                    out.append(child)
                    seen.add(child.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        # port 兜底 · 找所有 listen 在该 port 的 pid (孤儿也能逮到)
        if port:
            try:
                for c in psutil.net_connections(kind="inet"):
                    if (
                        c.status == psutil.CONN_LISTEN
                        and c.laddr
                        and c.laddr.port == port
                        and c.pid
                        and c.pid not in seen
                    ):
                        try:
                            out.append(psutil.Process(c.pid))
                            seen.add(c.pid)
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
            except Exception:
                pass
        return out

    procs_to_kill = _collect_targets()

    # 第一步 · graceful (terminate / SIGTERM)
    for p in procs_to_kill:
        try:
            if is_win:
                p.terminate()
            else:
                os.kill(p.pid, signal.SIGTERM)
        except Exception:
            pass

    # 等 graceful exit · port 还在 listen 也算没死透
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if not any(_is_alive(p.pid) for p in procs_to_kill):
            # 重新扫一遍 port · 看是不是又冒出新的孤儿 (多层 launcher)
            extras = _collect_targets()
            if not any(p.pid not in {x.pid for x in procs_to_kill} for p in extras):
                break
            # 加进 procs_to_kill 继续 terminate
            for p in extras:
                if p.pid not in {x.pid for x in procs_to_kill}:
                    procs_to_kill.append(p)
                    try:
                        p.terminate()
                    except Exception:
                        pass
        time.sleep(0.2)

    forced = False
    # 第二步 · force kill 仍活的
    still_alive = [p for p in procs_to_kill if _is_alive(p.pid)]
    if still_alive:
        forced = True
        for p in still_alive:
            try:
                p.kill()
            except Exception:
                pass
        time.sleep(1.0)
    # 终极兜底 · 再扫一次 port · 强杀任何还 listen 的
    if port:
        for p in _collect_targets():
            if p.pid != pid and p.pid not in {x.pid for x in procs_to_kill}:
                try:
                    p.kill()
                    forced = True
                except Exception:
                    pass

    # 综合判断: 收集到的 + port 上仍 listen 的都死了才算
    final_targets = _collect_targets()
    final_dead = not any(_is_alive(p.pid) for p in final_targets)
    n_killed = len(procs_to_kill)
    info["stopped"] = True
    info["stopped_at"] = datetime.now().isoformat(timespec="seconds")
    services[name] = info
    _save_services(services)

    if final_dead:
        return {
            "ok": True,
            "message": f"service `{name}` (pid={pid}) 已停 · forced={forced} · 杀了 {n_killed} 个进程",
            "forced": forced,
        }
    return {
        "ok": False,
        "message": (
            f"service `{name}` (pid={pid}) 杀了 {n_killed} 个进程但还有人活着/listen "
            f"· 可能要 BRO 手动处理 (netstat -ano | findstr :{port}{') (port: ' + str(port) if port else ''})"
        ),
    }


def remove_service(name: str) -> dict:
    """从 services.json 里移掉一条记录 (服务必须先 stop)"""
    services = _load_services()
    info = services.get(name)
    if not info:
        return {"ok": False, "message": f"没这条记录: {name}"}
    pid = info.get("pid")
    if pid and _is_alive(pid):
        return {"ok": False, "message": f"service `{name}` 还活着 (pid={pid}) · 先 service_stop"}
    services.pop(name, None)
    _save_services(services)
    return {"ok": True, "message": f"service `{name}` 已从记录里移除 (log 保留)"}
