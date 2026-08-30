"""桌宠通知 / 确认卡文件桥 · 从 activities 拆出以免超 300 行。"""

from __future__ import annotations

import json
import time
from pathlib import Path

_DIR = Path(__file__).parent
_NOTIFY_JSONL = _DIR / "notify.jsonl"
_CONFIRM_FILE = _DIR / "confirm.txt"
MAX_NOTIFY_LINES = 100


def write_confirm(text: str) -> None:
    try:
        _CONFIRM_FILE.write_text((text or "等你拍板").strip()[:40], encoding="utf-8")
    except Exception:
        pass


def clear_confirm() -> None:
    try:
        if _CONFIRM_FILE.exists():
            _CONFIRM_FILE.unlink()
    except Exception:
        pass


def read_confirm() -> str:
    try:
        if not _CONFIRM_FILE.exists():
            return ""
        return _CONFIRM_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def write_notify(kind: str, text: str) -> None:
    """写 notify.jsonl。confirm 同时落 confirm.txt，点掉对话卡才清。"""
    try:
        event = {
            "ts": time.time(),
            "kind": (kind or "info").strip() or "info",
            "text": (text or "").strip()[:120],
        }
        if not event["text"]:
            return
        if event["kind"] == "confirm":
            write_confirm(event["text"])
        _NOTIFY_JSONL.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        if _NOTIFY_JSONL.exists():
            try:
                raw = _NOTIFY_JSONL.read_text(encoding="utf-8").strip().split("\n")
                lines = [l for l in raw if l.strip()]
            except Exception:
                lines = []
        lines.append(json.dumps(event, ensure_ascii=False))
        if len(lines) > MAX_NOTIFY_LINES:
            lines = lines[-MAX_NOTIFY_LINES:]
        _NOTIFY_JSONL.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass


def read_last_notify(n: int = 3) -> list[dict]:
    try:
        if not _NOTIFY_JSONL.exists():
            return []
        text = _NOTIFY_JSONL.read_text(encoding="utf-8").strip()
        if not text:
            return []
        out = []
        for line in text.split("\n")[-n:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return out
    except Exception:
        return []
