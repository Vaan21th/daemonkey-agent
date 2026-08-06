"""workers/env_reloader.py
==============================

卷四十六 III 补丁 5 · Y6 · .env hot reload · 2026-05-26

为什么需要这个
----------------
BRO 改 .env 想换 LLM model / 切 log level / 调 scheduler interval · 现状是
**必须重启 daemon** 才能生效 (env 在 daemon 启动时一次性加载到 os.environ)。

但很多字段其实不需要重启:
  - `OPUS_RADAR_INTERVAL_MIN`: scheduler tick 之前才读 · 改了下次 tick 就生效
  - `OPUS_LOG_LEVEL`: logging 系统 set level 一行就切
  - `OPUS_API_DEFAULT_CONFIRM`: _chat_impl 每次入口才读

这些都应该可以**不重启**生效。

不能热切的字段 (改了必须重启 · daemon 启动时一次性消费):
  - `OPUS_API_PORT`: uvicorn 已经绑端口
  - `OPUS_API_TOKEN`: auth middleware 启动时缓存
  - `OPUS_MODEL` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`: provider client 已实例化

这一模块:
  1. 后台 thread · poll .env mtime · 默认每 5s
  2. 检测到改了 · 重新 parse · diff 出新 / 改 / 删的 key
  3. 白名单内的 → 写回 os.environ · log 通知
  4. 黑名单内 (或不在白名单) 改动 → log WARN "改了 X · daemon 重启才生效"
  5. /api/env/reload_status endpoint 给 BRO 查状态

为什么不用 watchdog 包
-----------------------
工程当前依赖都是 stdlib + 已有的 anthropic/openai/fastapi 等 · 加 watchdog
就为了一个 mtime poll 不划算。 5s poll 足够·daemon 单进程 · 没 inotify/FSEvents
压力。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


_log = logging.getLogger("opus.env_reloader")


# ─────────────────── 白名单 (可热切) ───────────────────
# 这些字段所有 worker / module 都是 "下次读取 env 时" 才用 · 写回 os.environ
# 后下次 tick 自动生效 · 不需要重启 daemon
_HOT_RELOAD_KEYS = frozenset({
    "OPUS_RADAR_INTERVAL_MIN",
    "OPUS_CAPABILITY_MIRROR_INTERVAL_DAYS",
    "OPUS_API_DEFAULT_CONFIRM",
    "OPUS_RESUME_AUTO_CONFIRM",
    "OPUS_LOG_LEVEL",
    "OPUS_HEALTH_CHECK_INTERVAL_SEC",
    "OPUS_DEBUG_VERBOSE",
    # scripted app 相关 (workers/http_executor 用)
    "OPUS_HTTP_TIMEOUT_SEC",
    "OPUS_HTTP_DEFAULT_RETRIES",
    # cache / context window
    "OPUS_CONTEXT_WINDOW_MAX_TURNS",
    "OPUS_AUTO_COMPACT_THRESHOLD",
})

# ─────────────────── 黑名单 (改了必须重启) ───────────────────
# 这些字段是 daemon 启动时一次性消费 · 改了热切没用 · 让 caller 知道要重启
_REQUIRES_RESTART_KEYS = frozenset({
    "OPUS_API_PORT",
    "OPUS_API_TOKEN",
    "OPUS_MODEL",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPUS_PROVIDER",
    "OPUS_BASE_URL",
    "OPUS_API_HOST",
})


# ─────────────────── 状态 ───────────────────

class _ReloaderState:
    """ReLoader 的运行时状态 · 单例 · 不动用 module-level dict (单进程 OK 但显式更清楚)"""
    def __init__(self):
        self.thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.last_mtime: float = 0.0
        self.last_reload_at: Optional[str] = None
        self.last_reload_changes: list[dict] = []  # [{key, action, hot}]
        self.reload_count: int = 0
        self.warn_count: int = 0
        self.poll_interval_sec: float = 5.0


_STATE = _ReloaderState()


def _read_env_text(path: Path) -> str:
    """容错读 .env 文本 · 与 tools/run_api_only._read_env_text 同语义。

    先 UTF-8(含 BOM)·失败按行回退 GBK/latin-1·防混合编码 .env 让
    hot-reload watcher 永久读不出新值 (历史: 中文注释被按 GBK 写入)。
    """
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    lines = []
    for bline in raw.split(b"\n"):
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                lines.append(bline.decode(enc))
                break
            except UnicodeDecodeError:
                continue
        else:
            lines.append(bline.decode("utf-8", errors="replace"))
    return "\n".join(lines)


def _parse_env_file(path: Path) -> dict[str, str]:
    """复刻 tools/run_api_only._load_env · 但返回 dict 不写 os.environ"""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in _read_env_text(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _do_reload(new_env: dict[str, str], current_env_snapshot: dict[str, str]) -> list[dict]:
    """对比新旧 · 写回热切 · log 警告非热切

    Args:
        new_env: 刚从 .env 读出的
        current_env_snapshot: 上一次 .env 读出的 (供 diff)

    Returns:
        changes: [{key, action: 'set'|'change'|'delete'|'unchanged',
                   hot: bool, requires_restart: bool}, ...]
    """
    changes: list[dict] = []
    all_keys = set(new_env.keys()) | set(current_env_snapshot.keys())

    for key in sorted(all_keys):
        new_v = new_env.get(key)
        old_v = current_env_snapshot.get(key)

        if new_v == old_v:
            continue  # 不动

        is_hot = key in _HOT_RELOAD_KEYS
        is_required_restart = key in _REQUIRES_RESTART_KEYS

        if old_v is None:
            action = "set"
        elif new_v is None:
            action = "delete"
        else:
            action = "change"

        change_record = {
            "key": key,
            "action": action,
            "hot": is_hot,
            "requires_restart": is_required_restart,
            "old": _mask(old_v) if old_v else None,
            "new": _mask(new_v) if new_v else None,
        }

        if is_hot:
            if action == "delete":
                os.environ.pop(key, None)
            else:
                os.environ[key] = new_v or ""
            _log.info("env hot reload · %s · %s (热切生效)", action, key)
        elif is_required_restart:
            _log.warning(
                ".env 改了 %s (%s) · 这个字段 daemon 启动时已消费 · "
                "需要重启 daemon 才生效 · WebUI 🔄 或双击 start.bat",
                key, action,
            )
            _STATE.warn_count += 1
        else:
            # 不在白名单也不在黑名单 · 默认按热切处理 (用户自定义 env)
            if action == "delete":
                os.environ.pop(key, None)
            else:
                os.environ[key] = new_v or ""
            change_record["hot"] = True  # 隐式热切
            _log.info("env hot reload · %s · %s (用户自定义 · 已写 os.environ)",
                      action, key)

        changes.append(change_record)

    return changes


def _mask(value: Optional[str]) -> Optional[str]:
    """log 里把可能的 secret 值 mask 一下 · 留头尾 · 中间 *"""
    if value is None:
        return None
    s = str(value)
    if len(s) <= 8:
        return "***"
    return s[:3] + "*" * 4 + s[-3:]


def _poll_loop():
    """后台 thread · 每 N 秒检查 .env mtime · 变了就 reload"""
    snapshot = _parse_env_file(ENV_FILE)
    try:
        _STATE.last_mtime = ENV_FILE.stat().st_mtime if ENV_FILE.exists() else 0.0
    except OSError:
        _STATE.last_mtime = 0.0

    _log.info(".env hot reload watcher 启动 · interval=%.1fs · 监听: %s",
              _STATE.poll_interval_sec, ENV_FILE)

    while not _STATE.stop_event.is_set():
        try:
            if not ENV_FILE.exists():
                _STATE.stop_event.wait(_STATE.poll_interval_sec)
                continue

            mtime = ENV_FILE.stat().st_mtime
            if mtime == _STATE.last_mtime:
                _STATE.stop_event.wait(_STATE.poll_interval_sec)
                continue

            # .env 改了
            _STATE.last_mtime = mtime
            new_env = _parse_env_file(ENV_FILE)
            changes = _do_reload(new_env, snapshot)
            snapshot = new_env

            if changes:
                _STATE.reload_count += 1
                _STATE.last_reload_at = _now_iso()
                _STATE.last_reload_changes = changes
                hot = sum(1 for c in changes if c["hot"])
                warn = sum(1 for c in changes if c["requires_restart"])
                _log.info(
                    ".env reload 完成 · %d 改动 · %d 热切 · %d 需要重启",
                    len(changes), hot, warn,
                )

        except Exception as e:
            _log.warning("env reloader 循环出错 (继续 polling): %s: %s",
                         type(e).__name__, e)

        _STATE.stop_event.wait(_STATE.poll_interval_sec)


def start_in_background(poll_interval_sec: float = 5.0) -> Optional[threading.Thread]:
    """daemon 启动时调一次 · 起后台 watcher thread

    幂等 · 调多次返同一个 thread
    """
    if _STATE.thread is not None and _STATE.thread.is_alive():
        return _STATE.thread

    _STATE.poll_interval_sec = max(1.0, poll_interval_sec)
    _STATE.stop_event.clear()
    t = threading.Thread(target=_poll_loop, name="opus-env-reloader", daemon=True)
    t.start()
    _STATE.thread = t
    return t


def stop() -> None:
    """让 watcher thread 退出 · 测试用"""
    _STATE.stop_event.set()
    if _STATE.thread is not None:
        _STATE.thread.join(timeout=2.0)
    _STATE.thread = None


def get_status() -> dict:
    """给 /api/env/reload_status endpoint 用"""
    return {
        "alive": _STATE.thread is not None and _STATE.thread.is_alive(),
        "poll_interval_sec": _STATE.poll_interval_sec,
        "last_reload_at": _STATE.last_reload_at,
        "reload_count": _STATE.reload_count,
        "warn_count": _STATE.warn_count,
        "last_changes": _STATE.last_reload_changes,
        "hot_keys": sorted(_HOT_RELOAD_KEYS),
        "restart_keys": sorted(_REQUIRES_RESTART_KEYS),
    }


__all__ = ["start_in_background", "stop", "get_status",
           "_HOT_RELOAD_KEYS", "_REQUIRES_RESTART_KEYS"]
