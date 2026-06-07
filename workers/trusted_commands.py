"""
workers/trusted_commands.py
============================

卷四十四 K stage 2c++ · wish-f563a56d · shell_exec 一次授权 · 30 min 信任窗口

**为什么要这个**:
  BRO 2026-05-25 19:36 截图: daemon OPUS 想给 BRO 找滨崎步照片 · 走 `pip install duckduckgo_search`
  探路 · BRO 那边 auto_confirm=auto 一刀切被 skip · OPUS 没法施工。

  落点: BRO 在 settings 里维护一个『信任命令头』清单 + 时长 (30min/24h/永久) · shell_exec
  classify 时检查命中 trusted pattern → downgrade tier 到 AUTO 自动 go。

**数据 schema** (data/trusted_commands.json):
  {
    "version": 1,
    "items": [
      {
        "id": "tc-<uuid8>",
        "pattern": "pip install",   ← 命令头匹配 (空格分隔的 prefix)
        "expires_at": "2026-05-25T22:30:00" or null,  ← null 表示永久
        "added_at": "2026-05-25T22:00:00",
        "reason": "BRO 临时让 OPUS 装 duckduckgo_search"
      },
      ...
    ]
  }

**安全约束**:
  - 即使 trusted · GUARD 黑名单 (rm -rf / format / shutdown / git push --force) 永远不能
    downgrade · GUARD 仍然 GUARD
  - pattern 必须是空格分隔的 token 序列 · 不允许 regex / 通配 (减少误匹)
  - 匹配是『命令头精确前缀』· 例如 pattern="pip install" 命中 "pip install xxx" 但不命中 "sudo pip install xxx"
"""
from __future__ import annotations

import json
import shlex
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent.parent
TRUSTED_FILE = ROOT / "data" / "trusted_commands.json"

_LOCK = threading.RLock()


def _now() -> datetime:
    return datetime.now()


def _ensure_dir() -> None:
    TRUSTED_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load() -> dict:
    _ensure_dir()
    if not TRUSTED_FILE.exists():
        return {"version": 1, "items": []}
    try:
        data = json.loads(TRUSTED_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"version": 1, "items": []}
        data.setdefault("version", 1)
        data.setdefault("items", [])
        return data
    except Exception:
        return {"version": 1, "items": []}


def _save(data: dict) -> None:
    _ensure_dir()
    tmp = TRUSTED_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(TRUSTED_FILE)


def _norm_pattern(pattern: str) -> str:
    """规整 pattern · 确保 token 边界清晰 (单空格分隔)"""
    return " ".join((pattern or "").split())


def _is_expired(item: dict) -> bool:
    exp = item.get("expires_at")
    if not exp:  # 永久
        return False
    try:
        return _now() > datetime.fromisoformat(exp)
    except Exception:
        return True  # 解析失败按过期处理 · 安全侧


def _command_head_tokens(command: str, n: int) -> list[str]:
    """提取命令前 n 个 token · 跨 platform shell-quote 安全"""
    s = (command or "").strip()
    if not s:
        return []
    # 先 strip 掉 PowerShell 子表达式包裹
    s = s.lstrip("([{ \t")
    try:
        # posix=False 允许 Windows-style quotes 不被吃掉
        tokens = shlex.split(s, posix=False)
    except ValueError:
        tokens = s.split()
    return tokens[:n]


# ───────────────────────────── public API ─────────────────────────────

def list_trusted(prune_expired: bool = True) -> list[dict]:
    """返回所有 trusted items · 默认顺手清过期"""
    with _LOCK:
        data = _load()
        items = data.get("items", []) or []
        if prune_expired:
            kept = [x for x in items if not _is_expired(x)]
            if len(kept) != len(items):
                data["items"] = kept
                _save(data)
                items = kept
        return list(items)


def is_trusted(command: str) -> Optional[dict]:
    """
    检查 command 是否命中 trusted pattern · 命中返 item · 未命中返 None。
    匹配规则: pattern 用 shlex 分 token · 用作命令的前缀 (token-level prefix match · 大小写敏感)。
    """
    items = list_trusted(prune_expired=True)
    if not items:
        return None
    cmd_tokens = _command_head_tokens(command, n=8)
    if not cmd_tokens:
        return None
    for item in items:
        pat = _norm_pattern(item.get("pattern") or "")
        if not pat:
            continue
        try:
            pat_tokens = shlex.split(pat, posix=False)
        except ValueError:
            pat_tokens = pat.split()
        if not pat_tokens:
            continue
        if len(pat_tokens) > len(cmd_tokens):
            continue
        if cmd_tokens[: len(pat_tokens)] == pat_tokens:
            return item
    return None


def add_trusted(
    pattern: str,
    duration_minutes: Optional[int] = None,
    reason: str = "",
) -> dict:
    """
    加一条 trusted command。
    duration_minutes: None / 0 表示永久 · 否则按分钟计算 expires_at。
    返回新建的 item dict。
    """
    pattern = _norm_pattern(pattern)
    if not pattern:
        raise ValueError("pattern 不能为空")
    if len(pattern) > 200:
        raise ValueError(f"pattern 太长 ({len(pattern)} > 200)")
    if any(ch in pattern for ch in ("|", "&", ";", "`", "$", ">", "<")):
        raise ValueError(f"pattern 不能含 shell 控制字符 (got: {pattern!r})")

    with _LOCK:
        data = _load()
        items = data.get("items", []) or []
        # 同 pattern 去重 · 用最新的覆盖 (BRO 想延长就再加一次)
        items = [x for x in items if _norm_pattern(x.get("pattern") or "") != pattern]

        now = _now()
        if duration_minutes and duration_minutes > 0:
            expires_at = (now + timedelta(minutes=int(duration_minutes))).isoformat(timespec="seconds")
        else:
            expires_at = None  # 永久

        item = {
            "id": f"tc-{uuid.uuid4().hex[:8]}",
            "pattern": pattern,
            "expires_at": expires_at,
            "added_at": now.isoformat(timespec="seconds"),
            "reason": (reason or "").strip()[:200],
        }
        items.append(item)
        data["items"] = items
        _save(data)
        return item


def remove_trusted(item_id: str) -> bool:
    """按 id 删一条 · 返 True 表示删了"""
    with _LOCK:
        data = _load()
        items = data.get("items", []) or []
        new_items = [x for x in items if x.get("id") != item_id]
        if len(new_items) == len(items):
            return False
        data["items"] = new_items
        _save(data)
        return True


def clear_all() -> int:
    """清空所有 · 返清掉的条数 (谨慎调用 · 没 confirm 防护层 · 仅给 BRO admin endpoint 用)"""
    with _LOCK:
        data = _load()
        n = len(data.get("items", []) or [])
        data["items"] = []
        _save(data)
        return n


def remaining_seconds(item: dict) -> Optional[int]:
    """这条 item 还剩多少秒 · 永久返 None · 已过期返 0"""
    exp = item.get("expires_at")
    if not exp:
        return None
    try:
        delta = (datetime.fromisoformat(exp) - _now()).total_seconds()
        return max(0, int(delta))
    except Exception:
        return 0
