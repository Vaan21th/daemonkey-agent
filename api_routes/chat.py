"""api_routes/chat.py · /chat /chat/stream + turns/{turn_id}/{abort,confirm,pending_confirms}

wish-413999da phase 1 · 5 路由 · 含 SSE 流式

依赖 daemon_api 的 module-level helpers · lazy import 防循环依赖:
  _chat_impl / _resolve_max_tokens / _resolve_session_id
  _ACTIVE_TURNS / _TURNS_LOCK / _TURN_TO_SID
  _PENDING_CONFIRMS / _PENDING_CONFIRMS_LOCK
  _supports_trust / _trust_decision_to_minutes / _extract_trust_pattern
  _short_json_preview
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from api_routes._deps import check_auth, check_rate_limit

router = APIRouter()


@router.post("/chat")
async def chat(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
    request: Request = None,
):
    check_auth(authorization)
    check_rate_limit(request, authorization)
    if not isinstance(payload, dict):
        raise HTTPException(400, "request body must be a JSON object")

    from daemon_api import _chat_impl, _resolve_max_tokens

    message = payload.get("message", "")
    session_id = payload.get("session_id")
    auto_confirm = payload.get("auto_confirm")
    max_tokens = _resolve_max_tokens(payload.get("max_tokens"))
    attachments = payload.get("attachments")  # wish-4a6331b2 · WebUI 图片上传

    # 卷四十六 III 补丁 5 · Y7 · audit log
    _audit_start = time.monotonic()
    _audit_ip = (request.client.host if request and request.client else None) or "unknown"
    _audit_sid_from_request = session_id or ""
    _audit_status = 200
    _audit_result_sid = ""

    try:
        result = _chat_impl(
            message=message,
            session_id=session_id,
            auto_confirm=auto_confirm,
            max_tokens=max_tokens,
            attachments=attachments,
        )
        _audit_result_sid = result.get("session_id", "") if isinstance(result, dict) else ""
    except ValueError as e:
        _audit_status = 400
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        _audit_status = 500
        raise HTTPException(500, str(e))
    finally:
        try:
            from workers.audit_logger import log_event as _audit
            _audit(
                endpoint="/chat",
                ip=_audit_ip,
                token=(authorization or "")[7:].strip() if authorization else None,
                session_id=_audit_result_sid or _audit_sid_from_request,
                msg_len=len(message or ""),
                status=_audit_status,
                duration_ms=(time.monotonic() - _audit_start) * 1000,
            )
        except Exception:
            pass
    return JSONResponse(result)


@router.post("/chat/stream")
async def chat_stream(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """SSE 流式版 (卷十七加 · 解决 524 + 让 BRO 看 OPUS 思考过程)"""
    check_auth(authorization)
    if not isinstance(payload, dict):
        raise HTTPException(400, "request body must be a JSON object")

    from daemon_api import (
        _chat_impl,
        _resolve_max_tokens,
        _resolve_session_id,
        _TURNS_LOCK,
        _ACTIVE_TURNS,
        _TURN_TO_SID,
    )

    message = payload.get("message", "")
    session_id = payload.get("session_id")
    auto_confirm = payload.get("auto_confirm")
    max_tokens = _resolve_max_tokens(payload.get("max_tokens"))
    attachments = payload.get("attachments")  # wish-4a6331b2

    if not message or not message.strip():
        raise HTTPException(400, "message is required and cannot be empty")

    # wish-351793b8 · 第一字节就 push session_id · 流断了也能接力
    try:
        sid = _resolve_session_id(session_id)
    except ValueError as e:
        raise HTTPException(400, str(e))

    turn_id = "turn-" + uuid.uuid4().hex[:12]
    cancel_event = threading.Event()
    with _TURNS_LOCK:
        _ACTIVE_TURNS[turn_id] = cancel_event
        _TURN_TO_SID[turn_id] = sid

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def push_event(event_type: str, data: dict):
        asyncio.run_coroutine_threadsafe(queue.put((event_type, data)), loop)

    def worker():
        try:
            result = _chat_impl(
                message=message,
                session_id=sid,
                auto_confirm=auto_confirm,
                max_tokens=max_tokens,
                attachments=attachments,
                progress=push_event,
                cancel_event=cancel_event,
                turn_id=turn_id,
            )
            push_event("done", result)
        except ValueError as e:
            push_event("error", {"status": 400, "detail": str(e)})
        except Exception as e:
            push_event("error", {"status": 500, "detail": f"{type(e).__name__}: {e}"})
        finally:
            with _TURNS_LOCK:
                _ACTIVE_TURNS.pop(turn_id, None)
                _TURN_TO_SID.pop(turn_id, None)

    threading.Thread(target=worker, daemon=True).start()

    async def event_stream():
        hello_payload = json.dumps({"turn_id": turn_id, "session_id": sid})
        yield f"event: hello\ndata: {hello_payload}\n\n"

        last_event_at = time.time()
        KEEPALIVE_INTERVAL = 25

        while True:
            try:
                event_type, data = await asyncio.wait_for(
                    queue.get(), timeout=KEEPALIVE_INTERVAL
                )
            except asyncio.TimeoutError:
                yield f": keepalive {int(time.time() - last_event_at)}s\n\n"
                continue

            last_event_at = time.time()
            try:
                data_str = json.dumps(data, ensure_ascii=False)
            except Exception:
                data_str = json.dumps({"error": "non-serializable event payload"})
            yield f"event: {event_type}\ndata: {data_str}\n\n"

            if event_type in ("done", "error"):
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/turns/{turn_id}/abort")
async def abort_turn(
    turn_id: str,
    authorization: Optional[str] = Header(None),
):
    """卷三十六 · BRO 点停止按钮 · 中断正在跑的 turn"""
    check_auth(authorization)
    from daemon_api import _TURNS_LOCK, _ACTIVE_TURNS
    with _TURNS_LOCK:
        evt = _ACTIVE_TURNS.get(turn_id)
    if evt is None:
        raise HTTPException(404, f"turn not found or already done: {turn_id}")
    evt.set()
    return {"ok": True, "turn_id": turn_id, "note": "abort signaled; will stop at next tool decision"}


@router.post("/turns/{turn_id}/confirm")
async def confirm_tool_call(
    turn_id: str,
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """wish-2a4d8c1e · BRO 在 chat 卡片点 4 按钮 (approve/trust_*/deny)"""
    check_auth(authorization)
    if not isinstance(payload, dict):
        raise HTTPException(400, "request body must be a JSON object")

    from daemon_api import (
        _PENDING_CONFIRMS,
        _PENDING_CONFIRMS_LOCK,
        _supports_trust,
        _trust_decision_to_minutes,
        _extract_trust_pattern,
    )

    tool_call_id = (payload.get("tool_call_id") or "").strip()
    decision = (payload.get("decision") or "").strip()
    reason = (payload.get("reason") or "").strip()[:500]

    if not tool_call_id:
        raise HTTPException(400, "tool_call_id is required")
    if decision not in {"approve_once", "trust_30min", "trust_24h", "trust_permanent", "deny"}:
        raise HTTPException(400, f"invalid decision: {decision!r}")

    with _PENDING_CONFIRMS_LOCK:
        pending = _PENDING_CONFIRMS.get(tool_call_id)
        if pending is None:
            raise HTTPException(404, f"no pending confirm for tool_call_id={tool_call_id}")
        if pending["event"].is_set():
            return {
                "ok": False,
                "detail": "already resolved",
                "previous_decision": pending.get("decision"),
            }
        if pending.get("turn_id") and pending["turn_id"] != turn_id:
            raise HTTPException(
                400,
                f"turn_id mismatch · pending belongs to {pending['turn_id']!r} · got {turn_id!r}",
            )
        pending["decision"] = decision
        pending["reason"] = reason
        ev = pending["event"]
        tool_name = pending.get("tool_name") or ""

    # wish-2a4d8c1e 续 · trust_* 决议时立刻调 add_trusted (不等 worker)
    applied_trust = None
    if decision.startswith("trust_"):
        if _supports_trust(tool_name):
            minutes = _trust_decision_to_minutes(decision)
            duration_for_add = minutes if (minutes is not None and minutes > 0) else None
            try:
                args_clean = pending.get("args_clean") or {}
                pattern = _extract_trust_pattern(tool_name, args_clean)
                from workers.trusted_commands import add_trusted as _add_trusted
                item = _add_trusted(
                    pattern,
                    duration_minutes=duration_for_add,
                    reason=f"BRO inline confirm ({decision}): {reason[:120]}",
                )
                applied_trust = {
                    "ok": True,
                    "supports_trust": True,
                    "pattern": item.get("pattern") or pattern,
                    "permanent": (minutes == 0),
                    "minutes": minutes if (minutes is not None and minutes > 0) else None,
                    "expires_at": item.get("expires_at"),
                    "created_at": item.get("created_at"),
                }
            except ValueError as ve:
                applied_trust = {
                    "ok": False,
                    "supports_trust": True,
                    "error": str(ve),
                    "attempted_pattern": _extract_trust_pattern(tool_name, pending.get("args_clean") or {}),
                    "note": "trust 没写入 trusted_commands.json · 本次仍按 approve_once 放行 · 下次同命令还会弹卡片",
                }
            except Exception as e:
                applied_trust = {
                    "ok": False,
                    "supports_trust": True,
                    "error": f"{type(e).__name__}: {e}",
                    "note": "trust 写入异常 · 本次仍按 approve_once 放行",
                }
        else:
            applied_trust = {
                "ok": False,
                "supports_trust": False,
                "note": f"{tool_name} 不支持 trust · 已按 approve_once 处理",
            }

    ev.set()

    return {
        "ok": True,
        "tool_call_id": tool_call_id,
        "decision": decision,
        "applied_trust": applied_trust,
    }


@router.get("/turns/{turn_id}/pending_confirms")
async def list_pending_confirms(
    turn_id: str,
    authorization: Optional[str] = Header(None),
):
    """wish-2a4d8c1e 配套 · F5 后重新拉一遍未决 confirm · 重新渲染卡片"""
    check_auth(authorization)
    from daemon_api import (
        _PENDING_CONFIRMS,
        _PENDING_CONFIRMS_LOCK,
        _supports_trust,
        _short_json_preview,
    )
    out = []
    with _PENDING_CONFIRMS_LOCK:
        for tcid, p in _PENDING_CONFIRMS.items():
            if p.get("turn_id") != turn_id:
                continue
            if p["event"].is_set():
                continue
            out.append({
                "tool_call_id": tcid,
                "turn_id": p.get("turn_id"),
                "session_id": p.get("session_id"),
                "tool_name": p.get("tool_name"),
                "args_preview": _short_json_preview(p.get("args_clean") or {}, max_chars=400),
                "command": p.get("command", ""),
                "supports_trust": _supports_trust(p.get("tool_name") or ""),
                "created_at": p.get("created_at"),
            })
    return {"ok": True, "pending": out}


@router.post("/spawn-task")
async def spawn_task(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """派发后台任务到新会话 · 不污染当前对话 (打捞自 wish-94bf05eb · 卷五十一)

    前端按钮 (雷达/趋势/机会/心愿/工坊) 点"执行"时 · 走此端点创建新 session ·
    后台跑 LLM turn · 原会话不受污染 · 前端拿到 session_id 后自动切到新标签。

    入参:
      - prompt (必填): 发给 OPUS 的任务指令
      - task_label (可选): 任务名 · 空则取 prompt 前 40 字符

    返回 {ok, session_id, task_label, message}
    """
    check_auth(authorization)

    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt is required")
    task_label = (payload.get("task_label") or "").strip()
    if not task_label:
        task_label = (prompt[:40] + "…") if len(prompt) > 40 else prompt

    from daemon_api import _resolve_session_id
    from daemon_session import set_session_meta
    from workers.resume_runner import _run_background_turn

    new_sid = _resolve_session_id(None)
    set_session_meta(new_sid, label=task_label)  # 新会话即时命名 · 标签栏不再显示 api-xxxx

    t = threading.Thread(
        target=_run_background_turn,
        args=(prompt, new_sid),
        daemon=True,
        name=f"spawn-{new_sid[-8:]}",
    )
    t.start()

    return {
        "ok": True,
        "session_id": new_sid,
        "task_label": task_label,
        "message": f"任务「{task_label}」已派发到新会话 {new_sid} · 后台执行中",
    }
