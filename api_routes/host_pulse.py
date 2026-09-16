"""api_routes/host_pulse.py · 输入框上本机脉搏（跟着对话实例）

GET  /host/pulse
POST /host/pulse/stop
POST /host/pulse/spawn/{id}/cancel
POST /host/pulse/spawn/{id}/message
POST /host/pulse/service/{name}/stop
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from api_routes._deps import check_auth

router = APIRouter()


class SpawnMessageBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class StopBody(BaseModel):
    session_id: Optional[str] = None
    all: bool = False


def _snap(session_id: Optional[str] = None, all_sessions: bool = False):
    from workers.host_pulse import snapshot
    return snapshot(session_id=session_id, force=True, all_sessions=all_sessions)


@router.get("/host/pulse")
def host_pulse_get(
    authorization: Optional[str] = Header(None),
    session_id: Optional[str] = Query(None),
    all: bool = Query(False),
):
    check_auth(authorization)
    return _snap(session_id, all)


@router.post("/host/pulse/stop")
def host_pulse_stop(body: StopBody, authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    from workers.host_pulse import stop_for
    return stop_for(body.session_id, all_sessions=bool(body.all))


@router.post("/host/pulse/spawn/{subagent_id}/cancel")
def host_pulse_spawn_cancel(
    subagent_id: str,
    authorization: Optional[str] = Header(None),
    session_id: Optional[str] = Query(None),
):
    check_auth(authorization)
    sid = (subagent_id or "").strip()
    if not sid:
        raise HTTPException(400, "subagent_id 必填")
    from agent_tools.dispatch_subagent import _cancel_subagent
    r = _cancel_subagent(sid)
    if not r.ok:
        raise HTTPException(404, r.error or "分身不在")
    return {"ok": True, "output": r.output, "pulse": _snap(session_id)}


@router.post("/host/pulse/spawn/{subagent_id}/message")
def host_pulse_spawn_message(
    subagent_id: str,
    body: SpawnMessageBody,
    authorization: Optional[str] = Header(None),
    session_id: Optional[str] = Query(None),
):
    check_auth(authorization)
    sid = (subagent_id or "").strip()
    if not sid:
        raise HTTPException(400, "subagent_id 必填")
    from agent_tools.dispatch_subagent import _message_subagent
    r = _message_subagent(sid, body.message.strip())
    if not r.ok:
        raise HTTPException(409, r.error or "传话失败")
    return {"ok": True, "output": r.output, "pulse": _snap(session_id)}


@router.post("/host/pulse/service/{name}/stop")
def host_pulse_service_stop(
    name: str,
    authorization: Optional[str] = Header(None),
    session_id: Optional[str] = Query(None),
):
    check_auth(authorization)
    nm = (name or "").strip()
    if not nm:
        raise HTTPException(400, "name 必填")
    from workers.service_runner import stop_service
    r = stop_service(nm)
    if not r.get("ok"):
        raise HTTPException(404, r.get("message") or "停不了")
    return {"ok": True, "output": r.get("message"), "pulse": _snap(session_id)}


@router.get("/host/pulse/service/{name}/log")
def host_pulse_service_log(
    name: str,
    authorization: Optional[str] = Header(None),
    tail: int = Query(60, ge=1, le=2000),
):
    """服务日志尾巴 —— 药丸面板里「看命令行输出」用。只读 data/runtime/service_logs/<name>.log 的尾部。"""
    check_auth(authorization)
    nm = (name or "").strip()
    if not nm:
        raise HTTPException(400, "name 必填")
    from workers.service_runner import read_service_log
    return read_service_log(nm, tail_lines=tail)
