"""
workers/audit_logger.py
=======================

API 调用审计 · 卷四十六 III 补丁 5 · Y7

设计 (wish-beb3e):
  落 data/runtime/audit.log · 每行 JSON · 字段:
    ts (UTC ISO8601) / ip / token_prefix (hash 前 6 位 · 不含明文) /
    session_id / endpoint / msg_len / status / duration_ms / trace_id

  使用 RotatingFileHandler (R1 logging 同款) · 单文件上限 5MB · 保留 3 个

不暴露任何 secret · token_prefix 只到 hash 前 6 位 · 不能反查

env:
  OPUS_AUDIT_ENABLED  '1'/'true' 开启 (default off)
  OPUS_AUDIT_MAX_MB   单文件上限 (default 5)
  OPUS_AUDIT_KEEP     滚动文件数 (default 3)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

# ---------- 路径 ----------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_AUDIT_PATH = _PROJECT_ROOT / "data" / "runtime" / "audit.log"

_lock = threading.Lock()
_handler: RotatingFileHandler | None = None
_audit_logger: logging.Logger | None = None


# ---------- 配置 ----------

def is_enabled() -> bool:
    v = (os.environ.get("OPUS_AUDIT_ENABLED") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
        return v if v > 0 else default
    except (ValueError, TypeError):
        return default


# ---------- 初始化 ----------

def _ensure_logger() -> logging.Logger | None:
    """懒初始化 · enabled=false 时返回 None · 调用方应直接 return"""
    global _handler, _audit_logger
    if not is_enabled():
        return None

    with _lock:
        if _audit_logger is not None:
            return _audit_logger

        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)

        max_bytes = _env_int("OPUS_AUDIT_MAX_MB", 5) * 1024 * 1024
        keep = _env_int("OPUS_AUDIT_KEEP", 3)

        h = RotatingFileHandler(
            _AUDIT_PATH,
            maxBytes=max_bytes,
            backupCount=keep,
            encoding="utf-8",
        )
        h.setFormatter(logging.Formatter("%(message)s"))

        lg = logging.getLogger("opus.audit")
        lg.setLevel(logging.INFO)
        lg.propagate = False  # 不冒给 root · 避免污染 daemon.log
        for old in list(lg.handlers):
            try:
                old.close()
            except Exception:
                pass
            lg.removeHandler(old)
        lg.addHandler(h)

        _handler = h
        _audit_logger = lg
        return lg


# ---------- 主接口 ----------

def _token_prefix(token: str | None) -> str:
    """脱敏 · 不暴露明文 · 只留 hash 前 6 位"""
    if not token:
        return "anon"
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:6]


def log_event(
    *,
    endpoint: str,
    ip: str | None = None,
    token: str | None = None,
    session_id: str | None = None,
    msg_len: int = 0,
    status: int = 200,
    duration_ms: float = 0.0,
    trace_id: str | None = None,
    extra: dict | None = None,
) -> None:
    """记一条审计 · disabled 时直接 return · 不影响 hot path"""
    lg = _ensure_logger()
    if lg is None:
        return

    try:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "endpoint": endpoint,
            "ip": ip or "unknown",
            "token_prefix": _token_prefix(token),
            "session_id": session_id or "",
            "msg_len": int(msg_len or 0),
            "status": int(status or 0),
            "duration_ms": round(float(duration_ms or 0.0), 2),
            "trace_id": trace_id or "",
        }
        if extra:
            for k, v in extra.items():
                if k not in record:
                    record[k] = v
        lg.info(json.dumps(record, ensure_ascii=False))
    except Exception:
        # 审计自身不能炸主流程
        pass


def recent(n: int = 50, *, endpoint_filter: str | None = None) -> list[dict]:
    """读最近 n 条审计 · 给 /api/audit/recent endpoint 用

    Args:
        n: 读多少条 (1..500 · 超过截断)
        endpoint_filter: 只看某个 endpoint · 不传给全部

    Returns:
        [{record dict}, ...] · 新在前
    """
    n = max(1, min(500, int(n)))
    if not _AUDIT_PATH.exists():
        return []

    # 从所有 rotated 文件读 · 按时间倒序拼
    files = [_AUDIT_PATH]
    for i in range(1, 10):
        rot = _AUDIT_PATH.with_suffix(f".log.{i}")
        if rot.exists():
            files.append(rot)
    # rotated 越大 = 越老 (logging 的 .log.1 比 .log.2 新)

    lines: list[str] = []
    for f in files:
        try:
            with f.open("r", encoding="utf-8") as fp:
                lines = fp.readlines() + lines
        except OSError:
            continue
        if len(lines) >= n * 3:  # 粗略多读些防 filter 后不够
            break

    out: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if endpoint_filter and rec.get("endpoint") != endpoint_filter:
            continue
        out.append(rec)
        if len(out) >= n:
            break
    return out


def _path_for_test() -> Path:
    return _AUDIT_PATH


def _set_path_for_test(p: Path) -> None:
    global _AUDIT_PATH, _audit_logger, _handler
    _AUDIT_PATH = p
    if _handler is not None:
        try:
            _handler.close()
        except Exception:
            pass
    if _audit_logger is not None:
        for h in list(_audit_logger.handlers):
            try:
                h.close()
            except Exception:
                pass
            _audit_logger.removeHandler(h)
    _audit_logger = None
    _handler = None
