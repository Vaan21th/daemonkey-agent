"""本机脉搏 · 跟着对话实例：分身 + 这场拉起的服务。"""
from __future__ import annotations

import time
from typing import Any, Optional

_CACHE: dict[str, Any] = {"at": 0.0, "key": None, "snap": None}
_TTL = 1.5


def _age_sec(started_at: Any) -> Optional[float]:
    if started_at is None or started_at == "":
        return None
    if isinstance(started_at, (int, float)):
        return max(0.0, time.time() - float(started_at))
    try:
        from datetime import datetime
        return max(0.0, (datetime.now() - datetime.fromisoformat(str(started_at))).total_seconds())
    except Exception:
        return None


def _real_sid(session_id: Any) -> str:
    sid = str(session_id or "").strip()
    if not sid or sid.startswith("tmp-"):
        return ""
    if sid[0] == "t" and sid[1:].isdigit():
        return ""
    return sid


def _spawns() -> list[dict]:
    try:
        from agent_tools.dispatch_subagent import pulse_spawns
        return pulse_spawns()
    except Exception:
        return []


def _pid_matches(pid: Any, started_at: Any) -> bool:
    if not pid:
        return False
    rec = _age_sec(started_at)
    try:
        import psutil
        created = time.time() - psutil.Process(int(pid)).create_time()
    except Exception:
        return False
    if rec is None:
        return True
    return abs(created - rec) < 90


def _owned_sub(s: dict) -> str:
    port = s.get("port")
    pid = s.get("pid")
    bits = ["活"]
    if port:
        bits.insert(0, f"127.0.0.1:{port}")
    elif pid:
        bits.insert(0, f"pid {pid}")
    return " · ".join(bits)


def _owned_services() -> list[dict]:
    try:
        from workers.service_runner import list_services
        rows = list_services()
    except Exception:
        return []
    out = []
    for s in rows:
        if not s.get("alive"):
            continue
        if not _pid_matches(s.get("pid"), s.get("started_at")):
            continue
        out.append({
            "id": s.get("name"),
            "name": s.get("name"),
            "title": s.get("name"),
            "kind": "owned",
            "port": s.get("port"),
            "pid": s.get("pid"),
            "ok": True,
            "owned": True,
            "can_stop": True,
            "session_id": _real_sid(s.get("session_id")),
            "sub": _owned_sub(s),
            "age_sec": _age_sec(s.get("started_at")),
            "detail": (s.get("command") or "")[:160],
        })
    return out


def _scope(rows: list[dict], session_id: str, all_sessions: bool, key: str) -> list[dict]:
    if all_sessions:
        return rows
    sid = _real_sid(session_id)
    if not sid:
        return []
    return [r for r in rows if _real_sid(r.get(key)) == sid]


def snapshot(
    *,
    session_id: Optional[str] = None,
    force: bool = False,
    all_sessions: bool = False,
) -> dict:
    now = time.time()
    key = ("*" if all_sessions else _real_sid(session_id))
    if (
        not force
        and _CACHE["snap"] is not None
        and _CACHE["key"] == key
        and (now - _CACHE["at"]) < _TTL
    ):
        return _CACHE["snap"]
    spawns = _scope(_spawns(), session_id or "", all_sessions, "parent_session_id")
    services = _scope(_owned_services(), session_id or "", all_sessions, "session_id")
    snap = {"spawns": spawns, "services": services, "ts": now, "session_id": key}
    _CACHE["at"] = now
    _CACHE["key"] = key
    _CACHE["snap"] = snap
    return snap


def prompt_line(session_id: Optional[str] = None) -> str:
    snap = snapshot(session_id=session_id)
    spawns = snap.get("spawns") or []
    services = snap.get("services") or []
    bits = []
    if spawns:
        goals = " / ".join((s.get("goal") or s.get("id") or "?")[:24] for s in spawns[:3])
        bits.append(f"分身 {len(spawns)} 路在跑（{goals}）")
    if services:
        bits.append("服务 " + " · ".join(
            f"{s.get('title')}" + (f":{s.get('port')}" if s.get("port") else "") + " 活"
            for s in services[:4]
        ))
    if not bits:
        return ""
    return "- 本机脉搏: " + "；".join(bits) + "\n"


def stop_for(
    session_id: Optional[str] = None,
    *,
    all_sessions: bool = False,
) -> dict:
    """关掉这场（或全部）对话里的分身 + 可停服务。"""
    snap = snapshot(session_id=session_id, force=True, all_sessions=all_sessions)
    cancelled: list[str] = []
    stopped: list[str] = []
    try:
        from agent_tools.dispatch_subagent import _cancel_subagent
    except Exception:
        _cancel_subagent = None
    try:
        from workers.service_runner import stop_service
    except Exception:
        stop_service = None
    for s in snap.get("spawns") or []:
        sid = s.get("id")
        if not sid or _cancel_subagent is None:
            continue
        r = _cancel_subagent(sid)
        if r.ok:
            cancelled.append(sid)
    for s in snap.get("services") or []:
        name = s.get("id") or s.get("name")
        if not name or not s.get("can_stop") or stop_service is None:
            continue
        r = stop_service(name)
        if r.get("ok"):
            stopped.append(name)
    return {
        "ok": True,
        "cancelled": cancelled,
        "stopped": stopped,
        "pulse": snapshot(
            session_id=session_id, force=True, all_sessions=all_sessions,
        ),
    }
