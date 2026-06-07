"""
workers/token_budget_guard.py
=============================

Token 预算守护 · 卷四十六 III 补丁 5 · Y2

设计 (wish-Y2-token-budget-guard):
  - 限制单 session 累计 token 数 + 单日累计 token 数 · 防止 LLM 跑飞
  - 入口 (check_budget): chat 调 LLM 前判断 · 超阈值返回 ok=False · 上层拒绝调用
  - 出口 (consume): chat 调 LLM 后累加用量 · 持久化到 data/runtime/token_budget.json
  - default 全部禁用 (env=0) · 不破现状 · BRO 调高才生效

env:
  OPUS_TOKEN_BUDGET_SESSION  单 session 上限 (input + output 合计 · default 0=off)
  OPUS_TOKEN_BUDGET_DAY      单日上限 (default 0=off)

跨进程一致性: 每次 check/consume 都从 data/runtime/token_budget.json 重读 ·
不在内存里 cache (并发读写 OK · file 操作走 safe_write 原子写)。
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .safe_write import atomic_write_json

# ---------- 路径 ----------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BUDGET_PATH = _PROJECT_ROOT / "data" / "runtime" / "token_budget.json"

# 读写并发锁 (同进程内串行化 · 跨进程靠原子 rename)
_LOCK = threading.Lock()


# ---------- env 读取 ----------

def _read_env_int(name: str, default: int = 0) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
        return v if v >= 0 else default
    except (ValueError, TypeError):
        return default


def get_limits() -> dict[str, int]:
    """读当前生效的限额 · 0 = 禁用"""
    return {
        "session": _read_env_int("OPUS_TOKEN_BUDGET_SESSION"),
        "day": _read_env_int("OPUS_TOKEN_BUDGET_DAY"),
    }


# ---------- 持久化 ----------

def _today_key() -> str:
    """UTC+8 日历日 · 跟 BRO 时区一致"""
    now = datetime.now(timezone.utc).astimezone()
    return now.strftime("%Y-%m-%d")


def _load() -> dict[str, Any]:
    if not _BUDGET_PATH.exists():
        return {"version": 1, "by_session": {}, "by_day": {}}
    try:
        with _BUDGET_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"version": 1, "by_session": {}, "by_day": {}}
        data.setdefault("by_session", {})
        data.setdefault("by_day", {})
        return data
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "by_session": {}, "by_day": {}}


def _save(data: dict[str, Any]) -> None:
    _BUDGET_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(_BUDGET_PATH, data, backup=False)


# ---------- 核心 API ----------

def check_budget(session_id: str | None = None) -> dict[str, Any]:
    """LLM 调用前查预算 · 返回 ok=False 时上层应拒绝调用

    返回:
      {
        "ok": bool,
        "reason": str | None,                 # 拒绝原因
        "limits": {"session": int, "day": int},
        "current": {"session": int, "day": int},
      }
    """
    limits = get_limits()
    session_id = session_id or "default"

    with _LOCK:
        data = _load()
        session_total = int(data.get("by_session", {}).get(session_id, {}).get("total", 0))
        day_total = int(data.get("by_day", {}).get(_today_key(), {}).get("total", 0))

    result = {
        "ok": True,
        "reason": None,
        "limits": limits,
        "current": {"session": session_total, "day": day_total},
    }

    if limits["session"] > 0 and session_total >= limits["session"]:
        result["ok"] = False
        result["reason"] = (
            f"session token budget exceeded · {session_total}/{limits['session']} tokens · "
            f"set OPUS_TOKEN_BUDGET_SESSION higher 或开新 session"
        )
        return result

    if limits["day"] > 0 and day_total >= limits["day"]:
        result["ok"] = False
        result["reason"] = (
            f"daily token budget exceeded · {day_total}/{limits['day']} tokens · "
            f"等到明日 UTC+8 0:00 重置 或调高 OPUS_TOKEN_BUDGET_DAY"
        )
        return result

    return result


def consume(session_id: str | None, input_tokens: int, output_tokens: int) -> dict[str, Any]:
    """LLM 调用后累加用量 · 总是返回最新 totals (不管限额是否启用)

    cache_creation / cache_read 这里不单独处理 · 调用方先合并好 (按 tool_loop
    里 UsageStats.input_tokens/output_tokens 总数传过来即可)
    """
    session_id = session_id or "default"
    delta = max(0, int(input_tokens or 0)) + max(0, int(output_tokens or 0))

    with _LOCK:
        data = _load()
        sess = data["by_session"].setdefault(session_id, {"total": 0, "calls": 0})
        sess["total"] = int(sess.get("total", 0)) + delta
        sess["calls"] = int(sess.get("calls", 0)) + 1
        sess["last_input"] = int(input_tokens or 0)
        sess["last_output"] = int(output_tokens or 0)
        sess["updated_at"] = datetime.now(timezone.utc).isoformat()

        today = _today_key()
        day = data["by_day"].setdefault(today, {"total": 0, "calls": 0})
        day["total"] = int(day.get("total", 0)) + delta
        day["calls"] = int(day.get("calls", 0)) + 1

        _save(data)

        return {
            "session_total": sess["total"],
            "day_total": day["total"],
            "day": today,
        }


def get_status(session_id: str | None = None) -> dict[str, Any]:
    """快照 · 给 /api/token_budget/status endpoint 用"""
    limits = get_limits()
    with _LOCK:
        data = _load()

    today = _today_key()
    by_session = data.get("by_session", {}) or {}
    by_day = data.get("by_day", {}) or {}

    snapshot: dict[str, Any] = {
        "limits": limits,
        "today": today,
        "day_total": int(by_day.get(today, {}).get("total", 0)),
        "day_calls": int(by_day.get(today, {}).get("calls", 0)),
        "session_count": len(by_session),
    }

    if session_id:
        sess = by_session.get(session_id, {})
        snapshot["session_id"] = session_id
        snapshot["session_total"] = int(sess.get("total", 0))
        snapshot["session_calls"] = int(sess.get("calls", 0))

    return snapshot


def reset_session(session_id: str) -> None:
    """单 session 计数清零 (开新对话 / 切换主题时上层可显式调)"""
    if not session_id:
        return
    with _LOCK:
        data = _load()
        if session_id in data.get("by_session", {}):
            del data["by_session"][session_id]
            _save(data)


def reset_day(day: str | None = None) -> None:
    """单日计数清零 (主要给 cron / 测试用)"""
    day = day or _today_key()
    with _LOCK:
        data = _load()
        if day in data.get("by_day", {}):
            del data["by_day"][day]
            _save(data)


def _path_for_test() -> Path:
    """暴露给 pytest fixture · 改写路径用"""
    return _BUDGET_PATH


def _set_path_for_test(p: Path) -> None:
    """测试隔离用 · 切换 _BUDGET_PATH"""
    global _BUDGET_PATH
    _BUDGET_PATH = p
