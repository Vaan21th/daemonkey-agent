"""workers/opus_logging.py
==========================

卷四十六 III 补丁 5 · R1 · 统一 logging + trace_id + 滚动文件 · 2026-05-26

为什么需要这个
----------------
之前各模块都 `logger = logging.getLogger("opus.X")` · 但 daemon 主进程
**没有 basicConfig** · logger 默认 WARNING + sys.stderr · 大多数 info 调用
被静默吞掉。 出问题时只能靠 `_daemon_7860.log` 里散落的 print() · 没 trace_id ·
没 module · 没 timestamp 排序 — 排查死循环。

这一模块做四件事:
  1. **`init_logging()`**: daemon 启动时调一次 · 装上 RotatingFileHandler
     ( data/runtime/daemon.log · 10MB 滚动 · 5 个 backup → 上限 60MB )
  2. **`set_trace_id(tid)` + ContextVar**: 每条 chat / tool call 注一个 trace_id ·
     LogRecord 自动带上 · 后续 grep 一条线索走通
  3. **`trace_context(tid)` ctxmgr**: with 块自动 set/clear · 异常安全
  4. **`tail_log(...)`**: 给 /api/logs/tail endpoint 用 · 支 trace_id / since / lines 过滤

设计取舍
----------
- **不引入 structlog / loguru** · stdlib logging 够用 · 减依赖
- **不动 print()** · `_daemon_7860.log` 还保留 · 这层只是把 logger.info 也开始写
  到 `data/runtime/daemon.log` · 两套并行 · 旧的不破
- **ContextVar (asyncio safe)**: 不用 thread-local · 因为 daemon 是 uvicorn 多
  worker · ContextVar 在 async + thread 都能跨
- **滚动文件而非按天**: 跑时间未必稳 · 按大小更稳

跟 daemon_lifecycle 的关系
----------------------------
- daemon_lifecycle: 进程生死 (pid / restart / crash)
- opus_logging: 进程内的活动 (chat / tool call / scheduler tick)
- 两者用同一目录 `data/runtime/` · 但不互相 import
"""
from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
import os
import re
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "data" / "runtime"
LOG_FILE = LOG_DIR / "daemon.log"


_TRACE_ID: contextvars.ContextVar[str] = contextvars.ContextVar("opus_trace_id", default="")

_INIT_LOCK = threading.Lock()
_INITIALIZED = False


class _TraceIdFilter(logging.Filter):
    """把 ContextVar 里的 trace_id 注到 LogRecord 上 · formatter 才能读到"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = _TRACE_ID.get() or "-"
        return True


# 格式: [time] [LEVEL] [trace_id] [module] message
# trace_id 走 8 字符短码 (uuid4().hex[:8]) · 看着不晕 · 碰撞率够低
_FORMAT = "[%(asctime)s] [%(levelname)-5s] [%(trace_id)-8s] [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def init_logging(level: Optional[str] = None, file_max_bytes: int = 10 * 1024 * 1024,
                 backup_count: int = 5) -> None:
    """daemon 启动时调一次 · 装 RotatingFileHandler + console handler

    幂等 · 调多次不重复加 handler。

    Args:
        level: log level · None → 读 OPUS_LOG_LEVEL env · 默认 INFO
        file_max_bytes: 单文件大小上限 (字节) · 默认 10MB
        backup_count: 滚动备份份数 · 默认 5 → 总上限 60MB
    """
    global _INITIALIZED
    with _INIT_LOCK:
        if _INITIALIZED:
            return

        LOG_DIR.mkdir(parents=True, exist_ok=True)

        if level is None:
            level = (os.environ.get("OPUS_LOG_LEVEL") or "INFO").strip().upper()
        numeric_level = getattr(logging, level, logging.INFO)

        formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)
        trace_filter = _TraceIdFilter()

        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE,
            maxBytes=file_max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(trace_filter)

        # console handler 走 stderr · 跟 daemon 早期 print 一致 · 但比 print 多了 level/trace
        # 仅 WARNING+ 上控制台 · 避免刷屏
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(trace_filter)

        root = logging.getLogger()
        root.setLevel(numeric_level)
        # 不清已有 handler · 防 uvicorn 之类已经装上的也被吃掉
        # 但要避免重复加自己装的 → 用 mark 标识
        for h in root.handlers:
            if getattr(h, "_opus_handler", False):
                root.removeHandler(h)
        file_handler._opus_handler = True  # type: ignore[attr-defined]
        console_handler._opus_handler = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)
        root.addHandler(console_handler)

        # 噪音 logger 降级 (httpx 默认 INFO 每次请求一行 · 吵)
        for noisy in ("httpx", "httpcore", "urllib3", "asyncio"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

        _INITIALIZED = True

        opus_log = logging.getLogger("opus.logging")
        opus_log.info("logging initialized · level=%s · file=%s · max=%dMB × %d",
                      level, LOG_FILE, file_max_bytes // (1024 * 1024), backup_count)


def is_initialized() -> bool:
    return _INITIALIZED


# ─────────────────────────── trace_id ─────────────────────────────


def new_trace_id() -> str:
    """生成新 8 字符 trace_id · uuid4 hex 前 8 位"""
    return uuid.uuid4().hex[:8]


def set_trace_id(tid: str) -> contextvars.Token:
    """显式 set · 返回 token 供后续 reset_trace_id 用"""
    return _TRACE_ID.set(tid)


def reset_trace_id(token: contextvars.Token) -> None:
    try:
        _TRACE_ID.reset(token)
    except (ValueError, LookupError):
        pass


def get_trace_id() -> str:
    return _TRACE_ID.get() or ""


class trace_context:
    """with 块自动 set/clear trace_id · 异常安全

    Usage:
        with trace_context(turn_id):
            # logger.info 都带这个 trace_id
            do_work()
    """

    def __init__(self, tid: Optional[str] = None):
        self.tid = tid or new_trace_id()
        self._token: Optional[contextvars.Token] = None

    def __enter__(self) -> str:
        self._token = set_trace_id(self.tid)
        return self.tid

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._token is not None:
            reset_trace_id(self._token)


# ─────────────────────────── tail / 查询 ─────────────────────────────


_LINE_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\] \[(?P<level>[^\]]+)\] \[(?P<tid>[^\]]+)\] \[(?P<mod>[^\]]+)\] (?P<msg>.*)$"
)


def _iter_log_files() -> list[Path]:
    """daemon.log + daemon.log.1 .. .N · 按修改时间倒序 · 最新在前"""
    files = []
    if LOG_FILE.exists():
        files.append(LOG_FILE)
    for i in range(1, 10):
        p = LOG_FILE.with_name(f"{LOG_FILE.name}.{i}")
        if p.exists():
            files.append(p)
    return files


def tail_log(*, lines: int = 200, trace_id: Optional[str] = None,
             since: Optional[str] = None, level_min: Optional[str] = None,
             module_prefix: Optional[str] = None) -> dict:
    """给 /api/logs/tail endpoint 用 · 返 dict

    Args:
        lines: 最多返多少行 (默认 200 · 上限 5000)
        trace_id: 只返此 trace · 8 字符短码或前缀
        since: ISO timestamp · 只返此后的
        level_min: 'DEBUG' / 'INFO' / 'WARNING' / 'ERROR' · 含此 level 及以上
        module_prefix: logger name 前缀过滤 · 例 'opus.scheduler'

    Returns:
        {
          "ok": True,
          "lines": ["[ts] [LEVEL] [tid] [mod] msg", ...],  # 最新在末尾
          "count": int,
          "from_files": ["daemon.log", "daemon.log.1", ...],
          "total_size_bytes": int,
        }
    """
    lines = max(1, min(lines, 5000))

    level_order = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "WARN": 30, "ERROR": 40, "CRITICAL": 50}
    level_min_v = level_order.get((level_min or "").upper(), 0) if level_min else 0

    since_ts: Optional[str] = None
    if since:
        # 接受简化的 'YYYY-MM-DDTHH:MM:SS' · 我们 _DATE_FORMAT 是同款
        since_ts = since.strip()

    files = _iter_log_files()
    total_size = sum(f.stat().st_size for f in files if f.exists())

    collected: list[str] = []
    # 文件从旧到新读 (按倒序索引 · 因为 _iter_log_files 新在前)
    for f in reversed(files):
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in content.splitlines():
            if not raw:
                continue
            m = _LINE_RE.match(raw)
            if m is None:
                # 跨行 (栈) · 拼到上一行
                if collected:
                    collected[-1] = collected[-1] + "\n" + raw
                continue
            d = m.groupdict()
            if trace_id and not d["tid"].strip().startswith(trace_id):
                continue
            if level_min_v and level_order.get(d["level"].strip(), 0) < level_min_v:
                continue
            if module_prefix and not d["mod"].strip().startswith(module_prefix):
                continue
            if since_ts and d["ts"].strip() < since_ts:
                continue
            collected.append(raw)

    if len(collected) > lines:
        collected = collected[-lines:]

    return {
        "ok": True,
        "lines": collected,
        "count": len(collected),
        "from_files": [f.name for f in files],
        "total_size_bytes": total_size,
    }


# ─────────────────────────── 公开 API ─────────────────────────────

__all__ = [
    "init_logging",
    "is_initialized",
    "new_trace_id",
    "set_trace_id",
    "reset_trace_id",
    "get_trace_id",
    "trace_context",
    "tail_log",
    "LOG_FILE",
    "LOG_DIR",
]
