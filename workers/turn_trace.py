"""回合轨迹 · 可回放，不进 git。

只记决策点（工具/压缩/中止），不记流式 token。字符串截断，避免工具结果把盘撑爆。
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_PATH = _ROOT / "data" / "runtime" / "turn_trace.jsonl"
_LOCK = threading.Lock()
_MAX = 800
_FILE_CAP = 8 * 1024 * 1024


def enabled() -> bool:
    v = (os.environ.get("OPUS_TURN_TRACE") or "1").strip().lower()
    return v not in ("0", "false", "off", "no")


def _clip(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= _MAX else value[:_MAX] + "…"
    if isinstance(value, dict):
        return {str(k)[:40]: _clip(v) for k, v in list(value.items())[:24]}
    if isinstance(value, list):
        return [_clip(x) for x in value[:12]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _clip(str(value))


def emit(event: str, **fields: Any) -> None:
    if not enabled():
        return
    rec: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": event,
    }
    try:
        from agent_tools import current_session_id
        rec["session"] = current_session_id() or ""
    except Exception:
        rec["session"] = ""
    rec.update({k: _clip(v) for k, v in fields.items()})
    line = json.dumps(rec, ensure_ascii=False)
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            if _PATH.exists() and _PATH.stat().st_size > _FILE_CAP:
                bak = _PATH.with_suffix(".jsonl.prev")
                if bak.exists():
                    bak.unlink()
                _PATH.replace(bak)
            with _PATH.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass
