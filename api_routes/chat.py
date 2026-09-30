"""api_routes/chat.py · /chat /chat/stream + turns/{turn_id}/{abort,confirm,pending_confirms}

wish-413999da phase 1 · 5 路由 · 含 SSE 流式

依赖 daemon_api 的 module-level helpers · lazy import 防循环依赖:
  _chat_impl / _resolve_max_tokens / _resolve_session_id
  register_turn / unregister_turn / get_turn_cancel (正在跑的活儿注册表收口点)
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

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from api_routes._deps import check_auth, check_rate_limit

# wish-93b0cabf (2026-08-06) · /context-usage 的 soul 固定块缓存 · 30s 过期。
# 病根: async 端点里同步 load_soul (读灵魂+画像文件+拼 prompt) · 60s 轮询+done 重刷高频触发。
# soul 内容低频变 (画像更新走 reload_soul_into_runtime 单独重建) · 30s 缓存足够 · 大幅降负载。
_ctx_soul_cache = {"ts": 0.0, "sp": None}

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
    _thinking = payload.get("thinking") or None            # 卷七十五续五 · 模型行为
    _reasoning_effort = payload.get("reasoning_effort") or None
    _advisor_coop = bool(payload.get("advisor_coop"))      # wish-0e749752 · 顾问协同模式
    _mode = str(payload.get("mode") or "standard")         # 2026-08-26 · companion=陪伴房间
    _tool_profile = str(payload.get("tool_profile") or "")  # wish-16fa5930 · 新对话首轮选的档
    _project_id = str(payload.get("project_id") or "")      # wish-8f9e4f05 · 新对话挂在哪个外部项目

    # 卷四十六 III 补丁 5 · Y7 · audit log
    _audit_start = time.monotonic()
    _audit_ip = (request.client.host if request and request.client else None) or "unknown"
    _audit_sid_from_request = session_id or ""
    _audit_status = 200
    _audit_result_sid = ""

    # 2026-09-17 · 修「第二个对话卡死」: async 端点里同步跑整个 turn(分钟级)会独占
    # uvicorn event loop → 同 daemon 一切其他 HTTP(第二个对话/SSE 推送/轮询)全部排队冻结。
    # 复现: 长 /chat 期间轻端点 0.01s → 20.38s(卡到该 turn 结束)。修法同 /chat/stream
    # 的 threading.Thread: 挪进工作线程。RUNTIME.* 在轮次入口是快照取值, 并行不串场。
    try:
        result = await asyncio.to_thread(
            _chat_impl,
            message=message,
            session_id=session_id,
            auto_confirm=auto_confirm,
            max_tokens=max_tokens,
            attachments=attachments,
            thinking=_thinking,
            reasoning_effort=_reasoning_effort,
            advisor_coop=_advisor_coop,
            mode=_mode,
            tool_profile=_tool_profile,
            project_id=_project_id,
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
    request: Request = None,
):
    """SSE 流式版 (卷十七加 · 解决 524 + 让 BRO 看 OPUS 思考过程)"""
    check_auth(authorization)
    # 限流必须跟 /chat 一致: WebUI 全走这条 SSE · 只在 /chat 上装闸等于没装
    check_rate_limit(request, authorization)
    if not isinstance(payload, dict):
        raise HTTPException(400, "request body must be a JSON object")

    from daemon_api import (
        _chat_impl,
        _resolve_max_tokens,
        _resolve_session_id,
        register_turn,
        unregister_turn,
    )

    message = payload.get("message", "")
    session_id = payload.get("session_id")
    auto_confirm = payload.get("auto_confirm")
    max_tokens = _resolve_max_tokens(payload.get("max_tokens"))
    attachments = payload.get("attachments")  # wish-4a6331b2
    _thinking = payload.get("thinking") or None            # 卷七十五续五 · 模型行为
    _reasoning_effort = payload.get("reasoning_effort") or None
    _advisor_coop = bool(payload.get("advisor_coop"))      # wish-0e749752 · 顾问协同模式
    _mode = str(payload.get("mode") or "standard")         # 2026-08-26 · companion=陪伴房间
    _tool_profile = str(payload.get("tool_profile") or "")  # wish-16fa5930 · 新对话首轮选的档
    _project_id = str(payload.get("project_id") or "")      # wish-8f9e4f05 · 新对话挂在哪个外部项目

    if not message or not message.strip():
        raise HTTPException(400, "message is required and cannot be empty")

    # wish-351793b8 · 第一字节就 push session_id · 流断了也能接力
    try:
        sid = _resolve_session_id(session_id)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # 会话记住模型 · 每轮以本对话记的 cfg 为准 (wish-1518b97f)
    # 以前是「只记这一笔用了谁」+ 只在切标签时恢复 → 切回正在跑的对话会拒绝切 →
    # 全局留着上一场的模型 · 下一轮跑的是别人的。现在反过来: 请求一进来先对齐。
    try:
        from daemon_api import ensure_session_model as _esm
        from workers.provider_configs import list_configs as _lpc
        from daemon_session import get_session_meta as _gsm, set_session_meta as _ssm
        _esm(sid)                                    # 全局 → 本对话的 cfg (不同才切)
        _aid = (_lpc(include_keys=False) or {}).get("active_id")
        if _aid and (_gsm(sid) or {}).get("last_model_cfg") != _aid:  # 没变就不写盘
            _ssm(sid, last_model_cfg=_aid)
    except Exception:
        pass

    turn_id = "turn-" + uuid.uuid4().hex[:12]
    cancel_event = threading.Event()
    register_turn(turn_id, sid, cancel_event)

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
                thinking=_thinking,
                reasoning_effort=_reasoning_effort,
                advisor_coop=_advisor_coop,
                mode=_mode,
                tool_profile=_tool_profile,
                project_id=_project_id,
            )
            push_event("done", result)
        except ValueError as e:
            push_event("error", {"status": 400, "detail": str(e)})
        except Exception as e:
            push_event("error", {"status": 500, "detail": f"{type(e).__name__}: {e}"})
        finally:
            unregister_turn(turn_id)

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


def _abort_trace(turn_id: str, request: Request, evt) -> None:
    """2026-09-16 · 断链排查(wish-a717b4e9) · 记录「谁发的停止请求」。

    双通道: loguru WARNING + data/runtime/abort_trace.jsonl
    (后者不依赖日志配置 · 用于排除『日志通道吞了』的情况)。
    只读观测 · 不改任何行为。
    """
    from pathlib import Path as _Path
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "turn": turn_id,
        "hit": evt is not None,
        "sid": "",
        "ip": (request.client.host if request.client else "") or "-",
        "ua": (request.headers.get("user-agent") or "-")[:160],
        "ref": (request.headers.get("referer") or "-")[:120],
    }
    try:
        from daemon_api import _TURN_TO_SID
        rec["sid"] = _TURN_TO_SID.get(turn_id, "") or ""
    except Exception:
        pass
    try:
        from loguru import logger as _lg
        _lg.warning("[abort] " + " ".join(f"{k}={v}" for k, v in rec.items() if k != "ts"))
    except Exception:
        pass
    try:
        _p = _Path(__file__).resolve().parent.parent / "data" / "runtime" / "abort_trace.jsonl"
        _p.parent.mkdir(parents=True, exist_ok=True)
        with _p.open("a", encoding="utf-8") as _f:
            _f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as _e:
        # 兼底通道自身失败也要留痕 (review 20260916: 两通道同时哑 = 排查者会误判"没收到请求")
        try:
            import sys as _sys
            print(f"[abort_trace] write failed: {_e}", file=_sys.stderr)
        except Exception:
            pass


@router.post("/turns/{turn_id}/abort")
async def abort_turn(
    turn_id: str,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """卷三十六 · BRO 点停止按钮 · 中断正在跑的 turn"""
    check_auth(authorization)
    from daemon_api import get_turn_cancel
    evt = get_turn_cancel(turn_id)
    # 2026-09-16 · 断链排查(wish-a717b4e9) · 记录「谁发的停止请求」· 双通道见 _abort_trace。
    _abort_trace(turn_id, request, evt)
    if evt is None:
        raise HTTPException(404, f"turn not found or already done: {turn_id}")
    evt.set()
    return {"ok": True, "turn_id": turn_id, "note": "abort signaled; will stop at next tool decision"}


def _resolve_confirm_inline(
    tool_call_id: str,
    turn_id: str,
    decision: str,
    reason: str = "",
) -> dict:
    """wish-2f0c731a · 把 confirm endpoint 核心抽成进程内可调函数。

    WebUI 卡片 (POST /turns/{turn_id}/confirm) 和微信文字回复
    (wechat_listener._maybe_resolve_confirm) 共用同一套 resolve 逻辑。
    返回 {ok, detail, decision, applied_trust?}。
    """
    from daemon_api import (
        _PENDING_CONFIRMS,
        _PENDING_CONFIRMS_LOCK,
        _supports_trust,
        _trust_decision_to_minutes,
        _extract_trust_pattern,
    )

    decision = (decision or "").strip()
    reason = (reason or "").strip()[:500]

    if not tool_call_id:
        return {"ok": False, "detail": "tool_call_id is required"}
    if decision not in {"approve_once", "trust_30min", "trust_24h", "trust_permanent", "deny"}:
        return {"ok": False, "detail": f"invalid decision: {decision!r}"}

    with _PENDING_CONFIRMS_LOCK:
        pending = _PENDING_CONFIRMS.get(tool_call_id)
        if pending is None:
            return {"ok": False, "detail": f"no pending confirm for tool_call_id={tool_call_id}"}
        if pending["event"].is_set():
            return {
                "ok": False,
                "detail": "already resolved",
                "previous_decision": pending.get("decision"),
            }
        if pending.get("turn_id") and turn_id and pending["turn_id"] != turn_id:
            return {
                "ok": False,
                "detail": f"turn_id mismatch · pending belongs to {pending['turn_id']!r} · got {turn_id!r}",
            }
        pending["decision"] = decision
        pending["reason"] = reason
        ev = pending["event"]
        tool_name = pending.get("tool_name") or ""

    # trust_* 决议时立刻调 add_trusted (不等 worker)
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


def _resolve_ask_inline(
    tool_call_id: str,
    turn_id: str,
    choice: str,
    choice_index: int = -1,
) -> dict:
    """wish-db46ff9b · 选择题卡的答案回写（进程内可调·WebUI 和以后的通道 UI 共用）。

    与 _resolve_confirm_inline 的分工：
      confirm → decision（approve_once / trust_* / deny）+ 可写 trusted_commands
      ask     → choice（选项原文）+ choice_index · **不碰信任机制**
    """
    from daemon_api import _PENDING_CONFIRMS, _PENDING_CONFIRMS_LOCK

    tool_call_id = (tool_call_id or "").strip()
    choice = (choice or "").strip()[:200]
    idx = int(choice_index if choice_index is not None else -1)

    if not tool_call_id:
        return {"ok": False, "detail": "tool_call_id is required"}
    if not choice:
        return {"ok": False, "detail": "choice is required（空答案请用跳过·别拿空白当回答）"}

    with _PENDING_CONFIRMS_LOCK:
        pending = _PENDING_CONFIRMS.get(tool_call_id)
        if pending is None:
            return {"ok": False, "detail": f"no pending ask for tool_call_id={tool_call_id}"}
        if pending.get("kind") != "ask":
            return {
                "ok": False,
                "detail": "这不是提问·是审批卡片 · 走 POST /turns/{turn_id}/confirm",
            }
        if pending["event"].is_set():
            return {
                "ok": False,
                "detail": "already answered",
                "previous_choice": pending.get("choice"),
            }
        if pending.get("turn_id") and turn_id and pending["turn_id"] != turn_id:
            return {
                "ok": False,
                "detail": f"turn_id mismatch · pending belongs to {pending['turn_id']!r} · got {turn_id!r}",
            }
        pending["choice"] = choice
        pending["choice_index"] = idx
        ev = pending["event"]

    ev.set()
    return {"ok": True, "tool_call_id": tool_call_id, "choice": choice, "choice_index": idx}


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

    tool_call_id = (payload.get("tool_call_id") or "").strip()
    decision = (payload.get("decision") or "").strip()
    reason = (payload.get("reason") or "").strip()[:500]

    if not tool_call_id:
        raise HTTPException(400, "tool_call_id is required")
    if decision not in {"approve_once", "trust_30min", "trust_24h", "trust_permanent", "deny"}:
        raise HTTPException(400, f"invalid decision: {decision!r}")

    result = _resolve_confirm_inline(tool_call_id, turn_id, decision, reason)
    if not result.get("ok"):
        detail = result.get("detail") or "resolve failed"
        if "no pending confirm" in detail or "already resolved" in detail:
            raise HTTPException(404, detail)
        if "turn_id mismatch" in detail:
            raise HTTPException(400, detail)
        raise HTTPException(400, detail)

    return {
        "ok": True,
        "tool_call_id": result.get("tool_call_id"),
        "decision": result.get("decision"),
        "applied_trust": result.get("applied_trust"),
    }


@router.post("/turns/{turn_id}/answer")
async def answer_tool_call(
    turn_id: str,
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """wish-db46ff9b · BRO 在对话里点了一个选项 · 把答案回写给还在等的 OPUS"""
    check_auth(authorization)
    if not isinstance(payload, dict):
        raise HTTPException(400, "request body must be a JSON object")

    result = _resolve_ask_inline(
        str(payload.get("tool_call_id") or ""),
        turn_id,
        str(payload.get("choice") or ""),
        payload.get("choice_index", -1),
    )
    if not result.get("ok"):
        detail = result.get("detail") or "resolve failed"
        if "no pending ask" in detail or "already answered" in detail:
            raise HTTPException(404, detail)
        raise HTTPException(400, detail)

    return {
        "ok": True,
        "tool_call_id": result.get("tool_call_id"),
        "choice": result.get("choice"),
        "choice_index": result.get("choice_index"),
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
        _TURN_TO_SID,
        _TURNS_LOCK,
    )
    out = []
    with _PENDING_CONFIRMS_LOCK:
        # 卷·修重启续场 confirm 卡片漏显示:
        # 后台续场 turn 的 pending 挂在 resume-xxx turn_id 上 · 而 BRO 在主对话前端
        # 轮询时传的是主对话的 turn_id · 两者不同 → 精确等值匹配永远捞不到 · 前端不渲染。
        # 改用 _TURN_TO_SID 把前端 turn_id 反查回 session_id · 按 session_id 匹配 pending
        # (同一会话不管哪个 turn · 后台/主对话都能捞到) · 其次 fallback 到 turn_id 精确。
        front_sid = None
        if turn_id:
            with _TURNS_LOCK:
                front_sid = _TURN_TO_SID.get(turn_id)
        for tcid, p in _PENDING_CONFIRMS.items():
            pend_sid = p.get("session_id")
            if front_sid and pend_sid and front_sid == pend_sid:
                pass  # session 命中 · 放行
            elif p.get("turn_id") != turn_id:
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
                # 卷四十六续 · 后台 turn 轮询补捞卡片需要这些字段渲染 (而非降级占位)
                "risk_explanation": p.get("risk_explanation", ""),
                "mitigation": p.get("mitigation", ""),
                "args_summary": p.get("args_summary", ""),
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


# ── 前缀全貌查看器（wish-740b2d2c）─────────────────────────────────
# 切段判据只此一份：/context-usage 要 tokens · /context-prefix 要 tokens + 原文。
# 各写各的就是「改一处忘一处 → 面板默默显示 0」的老毛病（SECTION_MARKS 那次）。
_CTX_SEG_ORDER = ("structure", "identity", "rules", "const_common", "const_local",
                  "runtime", "catalog", "memories", "notebook", "evolution")

# key → (显示名, 层名, 颜色)
_CTX_SEG_META = {
    "identity":      ("身份层", "身份层 · 我是谁", "#B794F4"),
    "rules":         ("工程铁律", "规则层 · 规矩与红线", "#F6AD55"),
    "const_common":  ("宪法 · 内核通用三条", "规则层 · 规矩与红线", "#F6AD55"),
    "const_local":   ("宪法 · 本实例六条", "规则层 · 规矩与红线", "#F6AD55"),
    "structure":     ("沉淀位地图", "规则层 · 规矩与红线", "#F6AD55"),
    "runtime":       ("Runtime 环境", "规则层 · 规矩与红线", "#F6AD55"),
    "catalog":       ("延迟工具目录", "工具层 · 手边 + 延迟", "#48BB78"),
    "notebook":      ("画像", "灵魂层 · 画像 / 成长", "#F687B3"),
    "memories":      ("自传", "灵魂层 · 画像 / 成长", "#F687B3"),
    "evolution":     ("成长档案", "灵魂层 · 画像 / 成长", "#F687B3"),
}


def _soul_segments(sp: str):
    """把 system prompt 按 SECTION_MARKS 切成块（含原文）。切段判据只此一份。"""
    if not sp:
        return []
    try:
        import tiktoken
        _e = tiktoken.get_encoding("cl100k_base")

        def _t(s):
            return len(_e.encode(s)) if s else 0
    except Exception:
        def _t(s):
            return int(len(s) / 0.67) if s else 0
    try:
        from soul_loader import SECTION_MARKS as _SM
        from soul_loader import SECTION_META as _SMT
    except Exception:
        return []
    _marks = [_SM[k] for k in _CTX_SEG_ORDER if k in _SM]
    out = []
    for _k in _CTX_SEG_ORDER:
        _mk = _SM.get(_k)
        if not _mk:
            continue
        _m = _SMT.get(_k) or ("", True, "")
        _i = sp.find(_mk)
        if _i < 0:
            out.append({"key": _k, "text": "", "tokens": 0, "pos": 1 << 30,
                        "inject": bool(_m[1]), "why": _m[2] if len(_m) > 2 else ""})
            continue
        _end = len(sp)
        for _o in _marks:
            if _o == _mk:
                continue
            _j = sp.find(_o, _i + 1)
            if 0 <= _j < _end:
                _end = _j
        _seg = sp[_i:_end]
        out.append({"key": _k, "text": _seg, "tokens": _t(_seg),
                    "inject": bool(_m[1]), "why": _m[2] if len(_m) > 2 else "",
                    "pos": _i})
    # 按**实际在 system prompt 里的位置**排 —— _CTX_SEG_ORDER 只是“值得切哪几块”的名单，
    #   不是装配顺序。BRO 要看的就是真正拼出来那个样子（wish-740b2d2c）。
    out.sort(key=lambda s: s.get("pos", 1 << 30))
    # 首块之前若有前导（system prompt 的开场白 —— 不落在任何 SECTION_MARKS 里），
    #   补进首块。否则「完整拼装」会惄惄少掉一段，而面板数字又对不上（wish-740b2d2c）。
    if out and 0 < out[0].get("pos", 0) < (1 << 30):
        _lead = sp[:out[0]["pos"]]
        if _lead:
            out[0]["text"] = _lead + out[0]["text"]
            out[0]["tokens"] += _t(_lead)
    return out


_PFX_CSS = """<style>
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{color-scheme:dark;display:flex;background:var(--bg,#16131f);color:var(--text,#ece8f5);font:13px/1.65 "Segoe UI",system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;-webkit-font-smoothing:antialiased}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-thumb{background:var(--border,#352c4d);border-radius:6px;border:2px solid var(--bg,#16131f)}
aside{width:322px;flex:0 0 322px;border-right:1px solid var(--border,#352c4d);overflow:auto;padding:14px 12px 40px;transition:border-color .45s ease}
nav{width:330px;flex:0 0 330px;border-right:1px solid var(--border,#352c4d);overflow:auto;padding:14px 12px 40px}
main{flex:1;overflow:auto;padding:18px 26px 110px}
h1{font-size:14px;margin:0 0 3px}
.sum{font-size:11px;color:var(--dim,#9a90b3);margin-bottom:10px;line-height:1.55}
.sum b{color:var(--accent,#a78bfa);font-weight:600}
.btnrow{display:flex;gap:6px;margin-bottom:10px;align-items:center;flex-wrap:wrap}
button{font:inherit;font-size:11px;cursor:pointer;border-radius:8px;padding:4px 11px;background:var(--bg3,#241e34);color:var(--dim,#9a90b3);border:1px solid var(--border,#352c4d);white-space:nowrap}
.btnrow button{flex:0 0 auto}
button:hover{background:color-mix(in srgb,var(--accent,#a78bfa) 12%,var(--bg3,#241e34));color:var(--text,#ece8f5)}
.prow{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:8px}
.pbtn{font-size:11px;cursor:pointer;border-radius:14px;padding:3px 11px;background:var(--bg2,#1f1a2c);color:var(--dim,#9a90b3);border:1px solid var(--border,#352c4d)}
.pbtn:hover{background:var(--bg3,#241e34);color:var(--text,#ece8f5)}
.pbtn.on{background:color-mix(in srgb,var(--accent,#a78bfa) 20%,var(--bg,#16131f));color:var(--accent,#a78bfa);border-color:var(--accent,#a78bfa)}
/* wish-36ef3ea9 续 · 编辑条 + 已改点 */
.ovd{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--sys,#F6AD55);margin-left:5px;vertical-align:2px}
.ped{display:none;gap:6px;margin:2px 0 8px;flex-wrap:wrap}
.ped.on{display:flex}
.ped button{font-size:10.5px;padding:3px 10px}
.ped button.danger:hover{border-color:#e0655f;color:#e0655f}
.pinfo{font-size:11px;color:var(--dim,#9a90b3);margin-bottom:5px}
.pinfo b{color:var(--text,#ece8f5)}
aside .warn,.warn{font-size:10.5px;line-height:1.55;color:var(--sys,#F6AD55);background:color-mix(in srgb,var(--sys,#F6AD55) 14%,var(--bg,#16131f));border-left:2px solid var(--sys,#F6AD55);padding:5px 8px;border-radius:0 5px 5px 0;margin-bottom:9px}
aside .warn b{color:var(--sys,#F6AD55)}
/* 三级目录：层 → 段 → 条目（wish-f1595d19 · BRO 2026-09-21：尽可能都靠左 —— 缩进从 44/70 压到 12/26） */
.l1{display:flex;align-items:center;gap:8px;font-size:12.5px;font-weight:600;color:var(--text,#ece8f5);padding:6px 6px 3px;margin-top:8px}
.l1 .tk{margin-left:auto;font-size:10.5px;color:var(--dim,#9a90b3);font-variant-numeric:tabular-nums}
.l2{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--dim,#9a90b3);padding:5px 6px 5px 12px;border-radius:7px;cursor:pointer}
.l2:hover{background:var(--border,#352c4d)}
.l2 .tk{margin-left:auto;font-size:10.5px;color:var(--dim,#9a90b3);font-variant-numeric:tabular-nums}
.l2 .nm{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.l2c{width:13px;height:13px;margin:0;flex:none;accent-color:var(--accent,#a78bfa);cursor:pointer}
.l3{display:flex;align-items:center;gap:9px;font-size:12px;color:var(--dim,#9a90b3);padding:4px 6px 4px 26px;border-radius:7px;cursor:pointer}
.l3:hover{background:var(--border,#352c4d)}
.l3 input{accent-color:var(--accent,#a78bfa);margin:0;cursor:pointer;width:14px;height:14px;flex:none}
.l3 .nm{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.l3 .tk{font-size:10.5px;color:var(--dim,#9a90b3);font-variant-numeric:tabular-nums}
.sec{margin:0 0 34px;scroll-margin-top:16px}
.sec h2{font-size:13px;margin:0 0 4px;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.sec h2 .tk{font-size:11px;color:var(--dim,#9a90b3);font-weight:400;font-variant-numeric:tabular-nums}
.sec .meta{font-size:11px;color:var(--dim,#9a90b3);margin-bottom:7px}
.sec .warn{color:var(--sys,#F6AD55)}
.ib{margin:0 0 10px}
.ib>pre{margin:0}
pre{margin:0;white-space:pre-wrap;word-break:break-word;background:var(--bg2,#1f1a2c);border-left:3px solid var(--accent,#a78bfa);border-radius:0 8px 8px 0;padding:12px 15px;font:12px/1.7 Consolas,"Cascadia Mono",monospace;color:var(--text,#ece8f5)}
.off{opacity:.18;filter:grayscale(1)}
/* wish-9de9bce3 · 未选条目/段自动折叠（BRO 2026-09-21：版面清晰）——预览里的未装提示词收起 */
.ib.off{opacity:1;filter:none;margin:0 0 4px}
.ib.off>pre{display:none}
.ibh{display:none;font-size:10.5px;color:var(--dim2,#6f6685);padding:2px 0 2px 2px}
.ib.off .ibh{display:block}
.sec.fold>.ib{display:none}
.sec.fold h2{opacity:.55}
.sec.fold h2::after{content:'（未装 · 已折叠）';font-size:11px;color:var(--dim2,#6f6685);font-weight:400}
.qm{display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;flex:none;border-radius:50%;border:1px solid var(--dim2,#6f6685);color:var(--dim2,#6f6685);font-size:10px;font-weight:600;cursor:help}
.qm:hover{border-color:var(--accent,#a78bfa);color:var(--accent,#a78bfa)}
.empty{color:var(--dim,#9a90b3);font-style:italic;padding:8px 0}
.ts{width:100%;margin-bottom:8px;background:var(--bg3,#241e34);color:var(--text,#ece8f5);border:1px solid var(--border,#352c4d);border-radius:8px;padding:6px 9px;font:inherit;font-size:11.5px}
.ts:focus{outline:none;border-color:var(--accent,#a78bfa)}
.tlist{border:1px solid var(--border,#352c4d);border-radius:9px;overflow:hidden}
.titem{display:flex;align-items:center;gap:8px;padding:4.5px 9px;cursor:pointer;border-bottom:1px solid var(--border,#352c4d)}
.tlist .titem:last-child{border-bottom:0}
.titem:hover{background:var(--bg3,#241e34)}
.titem .bx{width:13px;height:13px;flex:0 0 13px;border:1.5px solid var(--dim2,#6f6685);border-radius:4px;display:flex;align-items:center;justify-content:center;font-size:9px;line-height:1;color:var(--bg,#171322)}
.titem.on .bx{background:var(--accent,#a78bfa);border-color:var(--accent,#a78bfa);font-weight:900}
.titem .cn{flex:1;font-size:11.5px;color:var(--text,#ece8f5);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.titem.on .cn{color:var(--text,#ece8f5)}
.titem .nm{flex:0 0 auto;max-width:44%;font-size:10px;color:var(--dim2,#6f6685);font-family:Consolas,"Cascadia Mono",monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.titem .tk{flex:0 0 auto;min-width:34px;text-align:right;font-size:10px;color:var(--dim,#9a90b3);font-variant-numeric:tabular-nums;font-family:Consolas,monospace}
.tags{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:8px}
.tg{font-size:10.5px;cursor:pointer;border-radius:12px;padding:2px 9px;background:var(--bg2,#1f1a2c);color:var(--dim,#9a90b3);border:1px solid var(--border,#352c4d)}
.tg:hover{color:var(--text,#ece8f5)}
.tg.on{background:color-mix(in srgb,var(--accent,#a78bfa) 20%,var(--bg,#16131f));color:var(--accent,#a78bfa);border-color:var(--accent,#a78bfa)}
#tgops{display:flex;align-items:center;gap:6px;margin:0 0 8px;flex-wrap:wrap}
#tgops .sm{margin-left:auto;font-size:10.5px;color:var(--dim,#9a90b3)}
.tally{font-size:11px;color:var(--dim,#9a90b3);align-self:center;white-space:nowrap}
.tally b{color:var(--accent,#a78bfa);font-weight:600}
.tknote{font-size:10px;color:var(--dim2,#6f6685);margin-left:2px}
.tknote b{color:var(--dim,#9a90b3);font-weight:600}
.twarn{font-size:10.5px;color:var(--sys,#F6AD55);white-space:nowrap}
.td{margin-top:8px;font-size:11px;line-height:1.6;color:var(--dim,#9a90b3);background:var(--bg2,#1f1a2c);border:1px solid var(--border,#352c4d);border-radius:8px;padding:9px 11px;min-height:48px;max-height:150px;overflow:auto}
.td b{color:var(--accent,#a78bfa);font-family:Consolas,"Cascadia Mono",monospace}
.ask{margin:0 0 10px;padding:9px 10px;border:1px solid var(--border,#352c4d);border-radius:9px;background:var(--bg2,#1f1a2c)}
.ask-t{font-size:10.5px;color:var(--dim,#9a90b3);margin-bottom:6px;line-height:1.45}
.ask textarea{width:100%;box-sizing:border-box;background:var(--bg,#16131f);border:1px solid var(--border,#352c4d);border-radius:7px;color:var(--text,#ece8f5);font:inherit;font-size:11.5px;padding:6px 8px;resize:vertical;min-height:42px}
.ask textarea:focus{outline:none;border-color:var(--accent,#a78bfa)}
.adv{font-size:11px;color:var(--text,#ece8f5);line-height:1.5;margin-top:7px}
.adv b{color:var(--accent,#a78bfa)}
/* wish-0571fd96 批次 · 两层结构（BRO 2026-09-21）：默认简洁（对话卡居中）⇄ 点「我要自己配置」后输入框飞回左上角 + 三栏淡入 */
#askWrap{visibility:hidden;transform-origin:top left;transform:translate(var(--tx0,0px),var(--ty0,0px));
  transition:transform .55s cubic-bezier(.22,1,.36,1),width .55s cubic-bezier(.22,1,.36,1),
    background-color .45s ease,border-color .45s ease,box-shadow .45s ease,padding .55s ease,border-radius .45s ease}
body.full #askWrap{transform:none}
body:not(.fullDone) aside{overflow:visible;border-right-color:transparent}   /* 展开过渡期先保持 visible：滚动条/栏线都等卡到位（BRO 2026-09-21 报“过程中就出来”）*/
html:has(body:not(.fullDone)){overflow:hidden}   /* 简洁态+展开过渡期：aside 泄洪会撑视口滚动条（量过 2148px）—— 堵到“栏相关”一起进门（fullDone）为止 */
body:not(.full){overflow:hidden}
body:not(.full) #askWrap{position:relative;z-index:9;width:540px;max-width:calc(100vw - 48px);
  background:var(--bg2,#1f1a2c);border:1px solid var(--border,#352c4d);border-radius:14px;
  padding:16px 18px 12px;box-shadow:0 14px 48px rgba(0,0,0,.45)}
body:not(.full) #askWrap h1{font-size:16px}
body:not(.full) #askWrap .ask{border:0;background:transparent;padding:0;margin:0}
body:not(.full) .ask textarea{min-height:70px;font-size:12px}
body:not(.full) .ask .btnrow button{background:var(--accent,#a78bfa);color:#171322;border-color:transparent;font-size:12px;padding:6px 14px}
body:not(.full) .ask .btnrow button:hover{filter:brightness(1.08)}
/* 展开：0~0.5s 只有卡在飞（栏线/滚动条/三栏全不出）；满 0.5s（fullDone）栏相关一起进 */
aside>:not(#askWrap),nav,main{opacity:0;transform:translateY(14px);pointer-events:none;transition:opacity .3s ease,transform .3s ease}
body.fullDone aside>:not(#askWrap),body.fullDone nav,body.fullDone main{opacity:1;transform:none;pointer-events:auto;transition:opacity .45s ease,transform .45s ease}
.pinrow{margin-top:10px;padding-top:9px;border-top:1px solid var(--border,#352c4d)}
#gsumMini{font-size:11px;color:var(--dim,#9a90b3);line-height:1.7}
#gsumMini b{color:var(--accent,#a78bfa);font-weight:600}
body.full #gsumMini{display:none}
.moreLnk{margin-top:7px;font-size:11px;color:var(--dim,#9a90b3);cursor:pointer;user-select:none;display:inline-block}
.moreLnk:hover{color:var(--text,#ece8f5)}
.mask{display:none;position:fixed;inset:0;background:#0b0910cc;z-index:999;align-items:center;justify-content:center}
.mask.on{display:flex}
.dlg{background:var(--bg2,#1f1a2c);border:1px solid var(--border,#352c4d);border-radius:16px;padding:20px 20px 16px;width:392px;box-shadow:0 24px 60px #0009}
.dlg h3{margin:0 0 4px;font-size:15px}
.dlg p{margin:0 0 14px;font-size:11.5px;color:var(--dim,#9a90b3);line-height:1.55}
.dlg label{display:block;font-size:11px;color:var(--dim,#9a90b3);margin-bottom:12px}
.dlg input{width:100%;margin-top:4px;background:var(--bg3,#241e34);color:var(--text,#ece8f5);border:1px solid var(--border,#352c4d);border-radius:8px;padding:7px 10px;font:inherit;font-size:12.5px}
.dlg input:focus{outline:none;border-color:var(--accent,#a78bfa)}
.dlg .row{display:flex;gap:8px;justify-content:flex-end;margin-top:4px}
.dlg .row button.primary{background:var(--accent,#a78bfa);color:var(--bg,#171322);border-color:var(--accent,#a78bfa);font-weight:600}
.tst{position:fixed;left:50%;bottom:26px;transform:translate(-50%,20px);background:var(--bg3,#241e34);border:1px solid color-mix(in srgb,var(--accent,#a78bfa) 38%,var(--border,#352c4d));color:var(--text,#ece8f5);font-size:12px;padding:8px 15px;border-radius:20px;opacity:0;transition:.25s;z-index:1000;pointer-events:none}
.tst.on{opacity:1;transform:translate(-50%,0)}

#tip{position:fixed;z-index:99;left:0;top:0;display:none;max-width:360px;background:var(--bg2,#1f1a2c);border:1px solid var(--border,#352c4d);border-radius:9px;padding:8px 11px;font-size:11px;color:var(--text,#ece8f5);line-height:1.55;box-shadow:0 8px 26px rgba(0,0,0,.5);pointer-events:none}
#tip b{color:var(--accent,#a78bfa);font-size:11.5px}
#tip .tn{color:var(--dim2,#6f6685);font-family:Consolas,"Cascadia Mono",monospace;font-size:10px}
#tip .tdd{margin-top:5px;color:var(--dim,#9a90b3);white-space:pre-wrap}
#tip .tmt{margin-top:6px;font-size:10px;color:var(--dim2,#6f6685)}</style>""" 

_PFX_JS = """<script>
/* wish-6350cced · 皮肤跟随：颜色不写死 —— 从父页（工作台）读当前主题的 CSS 变量。自定义主题也对（computedStyle 拿的是最终值）；独立打开时吃 CSS 里的 fallback。
   wish-36ef3ea9 续 · 实时跟随（BRO 2026-09-21：切主题装配台不跟着走）——观察父页 body/html 的属性变化，主题一换当场重同步。 */
(function(){try{
  if(!window.parent||window.parent===window)return;
  var KEYS=['--bg','--bg2','--bg3','--border','--text','--dim','--dim2','--accent','--opus','--sys'];
  function sync(){
    try{
      var pd=window.parent.document;
      var ps=getComputedStyle(pd.body);
      KEYS.forEach(function(k){
        var v=ps.getPropertyValue(k);
        if(!v||!v.trim()){try{v=getComputedStyle(pd.documentElement).getPropertyValue(k);}catch(e2){}}
        if(v&&v.trim())document.body.style.setProperty(k,v.trim());
      });
    }catch(e){}
  }
  sync();
  function watch(el){if(!el)return;try{new MutationObserver(sync).observe(el,{attributes:true,attributeFilter:['style','class']});}catch(e){}}
  watch(window.parent.document.body);
  watch(window.parent.document.documentElement);
}catch(e){}})();
function selKey(k,on){document.querySelectorAll('aside input[data-ck="'+k+'"]').forEach(function(i){i.checked=on;});
  document.querySelectorAll('main [id^="i-'+k+'-"]').forEach(function(b){b.classList.toggle('off',!on);});
  tSum();}
function iKey(el){var b=document.getElementById('i-'+el.dataset.ck+'-'+el.dataset.j);if(b)b.classList.toggle('off',!el.checked);l2Sync(el.dataset.ck);tSum();}
/* 2026-09-21 · 子类全选框（BRO：工程铁律左边一个勾）与 l3 条目双向同步 —— 半勾显 indeterminate */
function l2Sync(k){var ck=document.querySelector('aside input[data-l2ck="'+k+'"]');if(!ck)return;
var bs=document.querySelectorAll('aside input[data-ck="'+k+'"]');
if(!bs.length){ck.checked=false;ck.indeterminate=false;return;}   /* 空段（无条目·如自传/成长）不进 layers（BRO 2026-09-23：此前强制勾着 → 被当“选中”保存）*/
var on=0;bs.forEach(function(i){if(i.checked)on++;});
ck.checked=(on===bs.length);ck.indeterminate=(on>0&&on<bs.length);}
function l2SyncAll(){document.querySelectorAll('aside input[data-l2ck]').forEach(function(ck){l2Sync(ck.dataset.l2ck);});}
function selAll(on){document.querySelectorAll('main .ib').forEach(function(b){b.classList.toggle('off',!on)});
document.querySelectorAll('aside input[type=checkbox]').forEach(function(i){i.checked=on});
l2SyncAll();if(typeof tSum==='function')tSum();}
function jump(k){var s=document.getElementById('s-'+k);if(s)s.scrollIntoView({behavior:'smooth',block:'start'});}
/* wish-740b2d2c 第三栏 · 工具勾选（查看器 · 零破坏性：不决定任何工具进不进 tools[]） */
function tTotal(){var c=0,n=0;document.querySelectorAll('nav .titem').forEach(function(el){if(el.classList.contains('on')){c+=(+el.dataset.t||0);n++;}});return [c,n];}
function tPaint(){
  var r=tTotal();var w=document.getElementById('tn');if(w)w.textContent=r[1];
  /* wish-36ef3ea9 · 顶部计数改「实装口径」（BRO 2026-09-21：37,112 易被误读成'装进去这么大'）
     >40 件只核心手全量；另加延迟目录常驻 ≈；完整 schema 之和降级小字。 */
  var rr=tReal();
  var k=document.getElementById('tk');if(k)k.textContent=rr.tools.toLocaleString();
  var kn=document.getElementById('tkNote');
  if(kn){kn.innerHTML=rr.over
    ?('实装口径（超 40 → 只核心手全量）· 另加延迟目录 '+DIR_TOK.toLocaleString()+' ≈ <b>'+(rr.tools+DIR_TOK).toLocaleString()+'</b> · 完整 schema '+r[0].toLocaleString())
    :'';}
  var a=document.getElementById('tall');if(a)a.classList.toggle('off',r[1]===0);
  /* wish-379e5f5a · 40 = 预设上限（save_user_preset）——超了存不进 */
  var w2=document.getElementById('twarn');if(w2)w2.style.display=(r[1]>40)?'':'none';
  tSum();
}
/* wish-379e5f5a · 实装口径（BRO 2026-09-21：全选后还是 5W 多？）——
   按真实装配机制估「这个组合存成档位后，前缀 ≈ 多大」：
   ≤40 件（tight 名单）：勾选的全部全量进 tools[]，延迟目录为空；
   >40 件：核心手全量 + 其余只以「名字+一句简介」进延迟目录（_tool_catalog.visible_names）。
   旧口径把每件工具的完整 schema 全加 → 全勾时虚高到 5.8 万。 */
function tReal(){
  var n=0,fullAll=0,coreFull=0;
  document.querySelectorAll('nav .titem.on').forEach(function(el){n++;
    var f=+el.dataset.t||0;fullAll+=f;
    if(CORE_SET.has(el.dataset.n))coreFull+=f;});
  if(n<=40)return {n:n,tools:fullAll,over:false};
  return {n:n,tools:coreFull,over:true};
}
function tSum(){
  /* 2026-09-21 修正（wish-e1178ade）：延迟目录固定烤进 sp、不随档缩（已核实 soul_loader
     是 directory_block 的唯一生产调用点）——旧版「≤40 目录为空」的增减是错的，删掉。
     真相：合计 = 已勾段（含目录段·勾着即装）+ tools[]（≤40 全量 / >40 核心手）。*/
  var ts=0;document.querySelectorAll('main .ib').forEach(function(b){if(!b.classList.contains('off'))ts+=(+b.dataset.t||0);});
  var r=tReal(),el=document.getElementById('gsum');
  if(el){
    /* BRO 2026-09-21：三个数值搬到 stage 标题栏（一直显眼）——实时同步给父窗；这里只留 可存预设 / 超限 提示 */
    var tail=(r.over
      ?'<span style="color:var(--sys,#F6AD55)">⚠ '+r.n+' 件超上限 40 —— 超出的不装全量 · 合计按实装估</span>'
      :'<span style="color:var(--dim,#9a90b3)">✓ 可存预设（'+r.n+'/40 件）</span>');
    el.innerHTML=tail;
    try{
      var _pp=window.parent&&window.parent.document;
      var _st=_pp&&_pp.getElementById('stageAsmStats');
      if(_st){
        _st.innerHTML='已勾层 <b>'+ts.toLocaleString()+'</b> · 工具全量 <b>'+r.tools.toLocaleString()+'</b> · 合计 ≈<b>'+(ts+r.tools).toLocaleString()+'</b> tok';   /* BRO 2026-09-21：数字< b> 拼色 · 对齐其他顶栏（.dh-chip b 同款） */
        _st.title='已勾层 '+ts.toLocaleString()+' tok ＋ 工具全量 '+r.tools.toLocaleString()+' tok = 合计 ≈'+(ts+r.tools).toLocaleString()+' tok';
      }
    }catch(e){}
  }
  /* wish-0571fd96 · 简洁态的账：多少工具 / 多少前缀层 / 一共多少 tok（BRO 2026-09-21） */
  var mi=document.getElementById('gsumMini');
  if(mi){
    var segN=0;document.querySelectorAll('main .sec').forEach(function(s){if(s.querySelector('.ib:not(.off)'))segN++;});
    mi.innerHTML='工具 <b>'+r.n+'</b> 件 · 前缀层 <b>'+segN+'</b> 段 · 合计 ≈<b>'+(ts+r.tools).toLocaleString()+'</b> tok';
  }
  foldSync();
}
/* wish-9de9bce3 · 未选段自动折叠（BRO 2026-09-21）：段内一个都没勾 → 整段收起 */
function foldSync(){
  document.querySelectorAll('main .sec').forEach(function(s){
    var ibs=s.querySelectorAll('.ib');
    s.classList.toggle('fold', ibs.length>0 && !s.querySelector('.ib:not(.off)'));
  });
}
/* wish-36ef3ea9 · 切档时按该档把「已到手」的工具行从右栏目录预览里划掉（BRO 2026-09-21）
   —— 只过滤显示，不重新请求后端、不重排整页；切回「当前会话」还原。 */
function dirPaint(k){
  var pre=document.querySelector('#s-catalog pre');if(!pre)return;
  if(!pre.dataset.full)pre.dataset.full=pre.textContent;
  var cfg=(k&&PROF[k])||null;
  var allow=(cfg&&cfg.tools&&cfg.tools!=='CORE')?cfg.tools:null;
  if(!allow){pre.textContent=pre.dataset.full;return;}
  var nm={};allow.forEach(function(n){nm[n]=1;});
  pre.textContent=pre.dataset.full.split('\\n').filter(function(ln){
    var m=ln.match(/^- ([A-Za-z0-9_]+):/);return !(m&&nm[m[1]]);}).join('\\n');
}
function tToggle(el){el.classList.toggle('on');
  var b=el.querySelector('.bx');if(b)b.textContent=el.classList.contains('on')?'\u2713':'';tPaint();}
function tEsc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
var tgCur='';
function tgPick(el){tgCur=(tgCur===el.dataset.tag)?'':(el.dataset.tag||'');
  document.querySelectorAll('#tags .tg').forEach(function(x){x.classList.toggle('on',(x.dataset.tag||'')===tgCur);});
  tFilter();}
function tFilter(){
  var q=(document.getElementById('tq').value||'').trim().toLowerCase();
  document.querySelectorAll('nav .titem').forEach(function(el){
    var okT=!tgCur||el.dataset.tag===tgCur;
    var hay=((el.dataset.n||'')+' '+(el.dataset.cn||'')+' '+(el.dataset.d||'')).toLowerCase();
    el.style.display=(okT&&(!q||hay.indexOf(q)>=0))?'':'none';
  });
  tgOps();
}
/* wish-f1595d19 · 分类级全选（BRO：能不能有单独的全选 · 某个工具分类的）—— 动的是当前列出的这些 */
function tgOps(){
  var o=document.getElementById('tgops');if(!o)return;
  if(!tgCur){o.style.display='none';return;}
  o.style.display='';
  var n=0;document.querySelectorAll('nav .titem').forEach(function(el){if(el.style.display!=='none')n++;});
  var s=document.getElementById('tgos');if(s)s.textContent='「'+tgCur+'」列出 '+n+' 件';
}
function tgSelect(on){
  document.querySelectorAll('nav .titem').forEach(function(el){
    if(el.style.display==='none')return;
    el.classList.toggle('on',!!on);var b=el.querySelector('.bx');if(b)b.textContent=on?'\u2713':'';});
  tPaint();
}
function tAll(on){document.querySelectorAll('nav .titem').forEach(function(el){
  el.classList.toggle('on',!!on);var b=el.querySelector('.bx');if(b)b.textContent=on?'\u2713':'';});tPaint();}
function tCore(){document.querySelectorAll('nav .titem').forEach(function(el){
  var on=CORE_SET.has(el.dataset.n);el.classList.toggle('on',on);
  var b=el.querySelector('.bx');if(b)b.textContent=on?'\u2713':'';});tPaint();}
function tShow(el){
  var d=document.getElementById('td');
  if(!d)return;
  var cn=el.dataset.cn||'',nm=el.dataset.n||'';
  d.innerHTML=(cn?('<b>'+tEsc(cn)+'</b> <span style="color:#67607e;font-size:10.5px">'+tEsc(nm)+'</span>'):('<b>'+tEsc(nm)+'</b>'))
    +' · '+(+el.dataset.t||0)+' tok<br>'+tEsc(el.dataset.d||'（无简介）');
}
(function(){var L=document.getElementById('tlist');if(!L)return;
  L.addEventListener('click',function(e){var el=e.target.closest('.titem');if(!el)return;tShow(el);tToggle(el);});
  /* 悬停 → 鼠标旁浮层显示完整说明（BRO 2026-09-21：要像完整工具说明 · 跟鼠标走）*/
  var tip=document.getElementById('tip');
  L.addEventListener('mouseover',function(e){var el=e.target.closest('.titem');
    if(!el){if(tip)tip.style.display='none';return;}
    if(!tip)return;
    var cn=el.dataset.cn||'',nm=el.dataset.n||'';
    tip.innerHTML=(cn?('<b>'+tEsc(cn)+'</b> <span class="tn">'+tEsc(nm)+'</span>'):('<b>'+tEsc(nm)+'</b>'))
      +'<div class="tdd">'+tEsc(el.dataset.d||'（无简介）')+'</div>'
      +'<div class="tmt">'+((+el.dataset.t)||0).toLocaleString()+' tok'+(el.dataset.tag?(' · '+tEsc(el.dataset.tag)):'')+'</div>';
    tip.style.display='block';
    /* 只 mouseover 没 mousemove 时也要有位置 —— 不然浮层落在 (0,0) 挡住左上角（BRO 2026-09-21 抓到）*/
    var px=e.clientX+16,py=e.clientY+16;
    if(px+tip.offsetWidth>window.innerWidth-10)px=Math.max(8,e.clientX-tip.offsetWidth-16);
    if(py+tip.offsetHeight>window.innerHeight-10)py=Math.max(8,e.clientY-tip.offsetHeight-16);
    tip.style.left=px+'px';tip.style.top=py+'px';});
  L.addEventListener('mousemove',function(e){
    if(!tip||tip.style.display!=='block')return;
    var w=tip.offsetWidth,h=tip.offsetHeight,x=e.clientX+16,y=e.clientY+16;
    if(x+w>window.innerWidth-10)x=Math.max(8,e.clientX-w-16);
    if(y+h>window.innerHeight-10)y=Math.max(8,e.clientY-h-16);
    tip.style.left=x+'px';tip.style.top=y+'px';});
  L.addEventListener('mouseleave',function(){if(tip)tip.style.display='none';});
  L.addEventListener('click',function(){if(tip)tip.style.display='none';});
  var q=document.getElementById('tq');if(q)q.addEventListener('input',tFilter);
  pInit();tPaint();})();
/* wish-9de9bce3 · 左栏「延迟工具目录」? 说明（复用 #tip · 跟鼠标走） */
(function(){var A=document.querySelector('aside');if(!A)return;
  var tip=document.getElementById('tip');
  A.addEventListener('mouseover',function(e){
    var el=e.target.closest?e.target.closest('.qm'):null;
    if(!el){return;}
    if(!tip)return;
    tip.innerHTML='<b>延迟工具目录</b><div class="tdd">'+tEsc(el.dataset.q||'')+'</div>';
    tip.style.display='block';
    var px=e.clientX+16,py=e.clientY+16;
    if(px+tip.offsetWidth>window.innerWidth-10)px=Math.max(8,e.clientX-tip.offsetWidth-16);
    if(py+tip.offsetHeight>window.innerHeight-10)py=Math.max(8,e.clientY-tip.offsetHeight-16);
    tip.style.left=px+'px';tip.style.top=py+'px';});
  A.addEventListener('mousemove',function(e){
    if(!tip||tip.style.display!=='block')return;
    var w=tip.offsetWidth,h=tip.offsetHeight,x=e.clientX+16,y=e.clientY+16;
    if(x+w>window.innerWidth-10)x=Math.max(8,e.clientX-w-16);
    if(y+h>window.innerHeight-10)y=Math.max(8,e.clientY-h-16);
    tip.style.left=x+'px';tip.style.top=y+'px';});
  A.addEventListener('mouseout',function(e){
    var el=e.target.closest?e.target.closest('.qm'):null;
    if(el&&tip)tip.style.display='none';});
})();
/* wish-36ef3ea9 续 · 档位/预设编辑（BRO 2026-09-21：保存当时的状态 + 回到初始）*/
function pedCur(){var b=document.querySelector('aside .pbtn.on');return (b&&b.dataset.k)||'';}
function pedGather(){
  var tools=[];
  document.querySelectorAll('nav .titem.on').forEach(function(el){if(el.dataset.n)tools.push(el.dataset.n);});
  var keep=[],off=0;
  document.querySelectorAll('aside input[data-l2ck]').forEach(function(ck){
    if(ck.dataset.ni)return;   /* 空段 / 不进前缀的段：不参与层配置（BRO 2026-09-23）*/
    if(ck.checked||ck.indeterminate)keep.push(ck.dataset.l2ck);else off++;});
  return {tools:tools,layers:(off===0?null:keep)};
}
function pedPaint(){
  var k=pedCur();
  var isUser=k.indexOf('u-')===0;
  try{  /* BRO 2026-09-21：按钮挪到 stage 标题栏（父窗）· 文案按当前档同步过去 */
    var pp=window.parent&&window.parent.document;
    if(pp&&k){
      var b1=pp.getElementById('stageAsmSave2'),b2=pp.getElementById('stageAsmReset');
      if(b1)b1.textContent=isUser?'保存修改':'保存到本档';
      if(b2)b2.textContent=isUser?'回到初始':'还原出厂';
    }
  }catch(e){}
}
setTimeout(function(){try{pedPaint();}catch(e){}},0);  /* 打开即同步一次标题栏文案 */
function pedPost(url,body,okMsg){
  fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(function(r){return r.json();}).then(function(j){
      if(!j.ok){toast2('没成：'+(j.error||'未知'));return;}
      toast2(okMsg+' · 正在刷新…');
      /* BRO 2026-09-23：保存后先按当前档重生成产物（让 profData.layers 跟上），再 reload ——
         否则 reload 读的是旧档数据，用户会看到勾选被打回 */
      setTimeout(function(){
        var k=pedCur();
        fetch('/context-prefix'+(k?('?profile='+encodeURIComponent(k)):''))
          .then(function(){location.reload();},function(){location.reload();});
      },600);
    }).catch(function(e){toast2('请求失败：'+e);});
}
function pedSave(){
  var k=pedCur();if(!k){toast2('先在左栏选一个档位/预设');return;}
  var g=pedGather();
  if(k.indexOf('u-')===0)pedPost('/profiles/update',{id:k,tools:g.tools,layers:g.layers},'已保存到预设');
  else pedPost('/profiles/override',{pid:k,tools:g.tools,layers:g.layers},'已保存到本档');
}
function pedReset(){
  var k=pedCur();
  if(!k){ /* BRO 2026-09-21：当前会话态也要能还原——回到打开时的初始（CORE 全件 + 全段） */
    pPick('');toast2('已回到默认状态（会话初始）');return;
  }
  var isUser=k.indexOf('u-')===0;
  if(!confirm(isUser?'把这个预设还原到最初创建时的样子？':'把这个档还原到出厂设置？'))return;
  if(isUser)pedPost('/profiles/restore',{id:k},'已回到初始');
  else pedPost('/profiles/override',{pid:k,clear:true},'已还原出厂');
}
/* 装配台 · 切档：段勾选 + 工具勾选 按档重算（数据已嵌在页里·不重新请求）*/
var PROF={},CORE_LIST=[],CORE_SET=new Set(),DIR_TOK=0,SESS_PROF='';
function pPick(k){
  var cfg=(k&&PROF[k])||null;
  document.querySelectorAll('aside .pbtn').forEach(function(b){b.classList.toggle('on',(b.dataset.k||'')===k);});
  /* 段：thin → 只留人格核那一块；有 layers → 按它还原（BRO 2026-09-23 修：此前一律全勾）；否则全勾（空段除外）*/
  var keep=(cfg&&cfg.thin)?'identity':null;
  var lay=(cfg&&Object.prototype.toString.call(cfg.layers)==='[object Array]')?cfg.layers:null;
  document.querySelectorAll('aside input[data-l2ck]').forEach(function(ck){
    var kk=ck.dataset.l2ck;
    ck.checked=keep?(kk===keep):(lay?lay.indexOf(kk)>=0:!ck.dataset.ni);
    ck.indeterminate=false;
  });
  document.querySelectorAll('aside input[data-ck]').forEach(function(i){
    var on=keep?(i.dataset.ck===keep):(lay?lay.indexOf(i.dataset.ck)>=0:!i.dataset.ni);
    i.checked=on;
    var b=document.getElementById('i-'+i.dataset.ck+'-'+i.dataset.j);
    if(b)b.classList.toggle('off',!on);
  });
  /* 工具：按该档名单预勾 */
  var coreMode=!cfg||cfg.tools==='CORE';
  var allow=(cfg&&cfg.tools&&cfg.tools!=='CORE')?cfg.tools:null;
  document.querySelectorAll('nav .titem').forEach(function(el){
    var on=coreMode?CORE_SET.has(el.dataset.n):(allow&&allow.indexOf(el.dataset.n)>=0);
    el.classList.toggle('on',!!on);
    var b=el.querySelector('.bx');if(b)b.textContent=on?'✓':'';
  });
  var h=document.getElementById('pinfoLive');
  if(h){
    var base=cfg?('已切到 <b>'+(cfg.name||k)+'</b> · 灵魂 '+cfg.th+' · 工具 '+(coreMode?CORE_LIST.length:((allow&&allow.length)||0))+' 件'):('已切回 <b>'+(SESS_PROF||'标准')+'</b> 档位');
    var al=(cfg&&cfg.alarm)?('<div class="warn">'+cfg.alarm+'</div>'):'';
    h.innerHTML=base+al;
  }
  l2SyncAll();
  tPaint();
  dirPaint(k);
  pedPaint();
}
function pInit(){
  var cd=document.getElementById('coreData');
  if(cd){try{CORE_LIST=JSON.parse(cd.textContent)||[];}catch(e){CORE_LIST=[];}}
  CORE_SET=new Set(CORE_LIST);
  var pd=document.getElementById('profData');
  if(pd){try{PROF=JSON.parse(pd.textContent)||{};}catch(e){PROF={};}}
  var spd=document.getElementById('sessProfData');
  if(spd){try{SESS_PROF=JSON.parse(spd.textContent)||'';}catch(e){SESS_PROF='';}}
  var dm=document.getElementById('dirMeta');
  if(dm){try{DIR_TOK=+(((JSON.parse(dm.textContent)||{}).tok)||0)||0;}catch(e){DIR_TOK=0;}}
}
pInit();
/* 说人话 → /tool-suggest（LLM 读工具目录）→ 勾上建议的几件（装配台 B 方案 · 原型同款）*/
async function askLLM(){
  var need=(document.getElementById('need').value||'').trim();
  if(!need){return;}
  var elSt=document.getElementById('askSt'),adv=document.getElementById('advice');
  elSt.textContent='在问…';adv.innerHTML='';
  try{
    var r=await fetch('/tool-suggest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({need:need})});
    var j=await r.json();
    if(!j.ok){elSt.textContent='';adv.innerHTML='<span class="warn">出错了：'+tEsc(j.error||'未知')+'</span>';return;}
    elSt.textContent='';
    var set={};(j.tools||[]).forEach(function(n){set[n]=1;});
    document.querySelectorAll('nav .titem').forEach(function(el){
      var on=!!set[el.dataset.n];el.classList.toggle('on',on);
      var b=el.querySelector('.bx');if(b)b.textContent=on?'✓':'';});
    /* wish-e1178ade · 层建议：先全开基线，再按 off_layers 收起 */
    var offSet={};(j.off_layers||[]).forEach(function(k){offSet[k]=1;});
    document.querySelectorAll('aside input[data-ck]').forEach(function(i){
      var on=!offSet[i.dataset.ck];i.checked=on;
      var b=document.getElementById('i-'+i.dataset.ck+'-'+i.dataset.j);
      if(b)b.classList.toggle('off',!on);});
    l2SyncAll();
    var offN=(j.off_layers||[]);
    adv.innerHTML='建议开 <b>'+(j.tools||[]).length+'</b> 件'
      +(j.profile?' · 像「'+tEsc(j.profile)+'」档':'')
      +'<br>'+tEsc(j.why||'')
      +(offN.length?('<br>层：帮你收起了 <b>'+offN.map(function(k){
          var e=document.querySelector('aside input[data-l2ck="'+k+'"]'),nm='',tk='';
          if(e){var l2=e.closest('.l2');nm=l2.querySelector('.nm').textContent.replace(/·\s*不进每轮前缀\s*$/,'').trim();tk=l2.querySelector('.tk').textContent;}
          return tEsc(nm||k)+(tk?('（'+tEsc(tk)+' tok）'):'');
        }).join('、')+'</b>（省体量）'):'<br>层：整套都留着（这个场景不用动）');
    tPaint();
  }catch(e){elSt.textContent='';adv.innerHTML='<span class="warn">请求失败：'+tEsc(String(e))+'</span>';}
}
function svOpen(){var m=document.getElementById('svMask');if(!m)return;
  var n=document.getElementById('svName');n.value='';m.classList.add('on');n.focus();}
function svClose(){var m=document.getElementById('svMask');if(m)m.classList.remove('on');}
function svDo(){
  var name=(document.getElementById('svName').value||'').trim();
  if(!name){toast2('给预设起个名字');return;}
  var tools=[];
  document.querySelectorAll('nav .titem.on').forEach(function(el){if(el.dataset.n)tools.push(el.dataset.n);});
  if(!tools.length){toast2('一件工具都没勾 → 先在上面勾几件');return;}
  /* wish-e1178ade · 层配置：勾了哪几段一起存（全勾 = null·不钉死现状）*/
  var allK={},onK={};
  document.querySelectorAll('aside input[data-ck]').forEach(function(i){
    if(i.dataset.ni)return;   /* 空段 / 不进前缀：不参与层配置（BRO 2026-09-23）*/
    allK[i.dataset.ck]=1;if(i.checked)onK[i.dataset.ck]=1;});
  var uniqOn=Object.keys(onK);
  if(!uniqOn.length && !window.confirm('层一个都没勾（没有灵魂的档）—— 就这么存？')) return;
  var layers=(uniqOn.length>=Object.keys(allK).length)?null:uniqOn;
  fetch('/profiles/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:name,tools:tools,soul_thickness:'standard',layers:layers})})
    .then(function(r){return r.json();})
    .then(function(d){
      if(!d||!d.ok){toast2('没存上：'+((d&&d.error)||'未知'));return;}
      svClose();toast2('已存为「'+name+'」· 新对话的选档卡里能看到它');
      try{if(window.parent&&window.parent!==window&&typeof window.parent.tpLoad==='function')window.parent.tpLoad();}catch(_e){}
    })
    .catch(function(e){toast2('请求失败：'+e);});
}
function toast2(t){var e=document.getElementById('tst');if(!e)return;e.textContent=t;e.classList.add('on');
  clearTimeout(window._t2);window._t2=setTimeout(function(){e.classList.remove('on');},2600);}
/* wish-0571fd96 批次 · 两层结构：简洁（卡居中）⇄ 全貌（输入框飞回左上角 → 三栏淡入）—— BRO 2026-09-21 拍板 */
function pfxLayout(){
  var w=document.getElementById('askWrap');if(!w)return;
  var wasFull=document.body.classList.contains('full');
  var t=w.style.transition;w.style.transition='none';
  var tw0=w.style.transform;w.style.transform='none';
  if(!wasFull)document.body.classList.add('full');
  var r=w.getBoundingClientRect();
  if(!wasFull)document.body.classList.remove('full');
  w.style.transform=tw0;w.style.transition=t;
  var tw=Math.min(540,innerWidth-60);   /* 与 CSS 里 540 / 100vw-48 同一口径 */
  var tx=(innerWidth-tw)/2-r.left;
  var ty=Math.max(40,innerHeight*0.22-r.top);
  var s=document.body.style;
  s.setProperty('--tx0',tx+'px');s.setProperty('--ty0',ty+'px');
}
function pfxToggle(open){
  var show=(open===undefined)?!document.body.classList.contains('full'):open;
  var bd=document.body;
  clearTimeout(window._pfxT);
  if(show){
    bd.classList.add('full');
    /* 栏相关（栏线/滚动条/三栏）等卡飞到位（0.5s+）再进 —— BRO 2026-09-21 */
    window._pfxT=setTimeout(function(){bd.classList.add('fullDone');},520);
  }else{
    bd.classList.remove('full');bd.classList.remove('fullDone');
  }
  var b=document.getElementById('moreBtn');if(b)b.textContent=show?'收起到简洁 ▴':'我要自己配置 ▾';
  try{localStorage.setItem('pfx.full',show?'1':'0');}catch(e){}
  if(!show)window.scrollTo({top:0,behavior:'smooth'});
}
(function(){
  var full=false;try{full=localStorage.getItem('pfx.full')==='1';}catch(e){}
  if(full){document.body.classList.add('full');document.body.classList.add('fullDone');}
  pfxLayout();
  var _w=document.getElementById('askWrap');if(_w)_w.style.visibility='visible';
  addEventListener('resize',function(){
    var w=document.getElementById('askWrap');if(!w)return;
    w.style.transition='none';pfxLayout();requestAnimationFrame(function(){w.style.transition='';});
  });
})();
</script>""" 


@router.get("/context-prefix")
async def get_context_prefix(authorization: Optional[str] = Header(None),
                           profile: Optional[str] = Query(None),
                           sess: Optional[str] = Query(None)):
    """前缀全貌 × 档位装配台 → 铺中栏（wish-740b2d2c）。

    BRO：「目录这里可以点√全选全不选 · 拼装提示词部分一定要大 · 能看到全部 · 不能是小窗」
    BRO（三栏定案）：「左边各种层、中间工具、最右拼接后的真实预览」
    profile 不传 = 当前会话真装的原始前缀；传了 = 那一档的长相（装配台）。
    产物固定落 data/design/前缀全貌（实时）.html · 每次覆盖（不产生垃圾文件）。
    勾选只影响右侧显示（查看器 · 零破坏性）—— 不决定任何东西进不进前缀。
    """
    check_auth(authorization)
    from pathlib import Path as _P
    import html as _h
    root = _P(__file__).resolve().parent.parent

    # ── 档位表（装配台用 · 只读 —— 不改任何档位语义）────────────
    _profs, _porder = {}, []
    _uprofs, _ovs, _pu = {}, set(), {}
    try:
        import json as _pj
        _pj0 = _pj.loads((root / "data" / "cognition" / "tool_profiles.json").read_text(encoding="utf-8"))
        _profs = _pj0.get("profiles") or {}
        _porder = [k for k in ("chat", "standard", "work", "code", "dev3d", "image", "writing")
                   if k in _profs]
        _porder += [k for k in _profs if k not in _porder]
    except Exception:
        _profs, _porder = {}, []
    # wish-36ef3ea9 续 · 用户预设也进装配台（编辑对象）+ 内置档覆盖标志
    try:
        import json as _pj2
        _pu = _pj2.loads((root / "data" / "cognition" / "tool_profiles_user.json").read_text(encoding="utf-8"))
        _uprofs = _pu.get("presets") or {}
        _ovs = set((_pu.get("overrides") or {}).keys())
    except Exception:
        _uprofs, _ovs = {}, set()
    _ovo = _pu.get("overrides") if isinstance(_pu.get("overrides"), dict) else {}
    _all_profs = {}
    for _k0, _v0 in list(_profs.items()) + list(_uprofs.items()):
        if isinstance(_v0, dict) and _k0 in _ovs and isinstance(_ovo.get(_k0), dict):
            _o0 = _ovo[_k0]
            _v0 = {**_v0, "tools": _o0.get("tools") or _v0.get("tools")}
            if "layers" in _o0:
                _v0 = {**_v0, "layers": _o0.get("layers")}
        _all_profs[_k0] = _v0
    # BRO 2026-09-21：「当前会话」文案显示该会话真实档名（原来写死"标准"· 他抓到了）
    _sess_name = ""
    try:
        _spid = "standard"
        if sess:
            from daemon_session import get_session_meta as _gsm1
            _spid = ((_gsm1(sess) or {}).get("last_tool_profile") or "") or "standard"
        _sv1 = _all_profs.get(_spid) or {}
        _sess_name = _sv1.get("name") or _spid
    except Exception:
        _sess_name = "标准"
    _cur = (profile or "").strip() or None
    if _cur and _cur not in _all_profs:
        _cur = None
    _pd = (_all_profs.get(_cur) or {}) if _cur else {}
    # thickness：load_soul 只认 thin / standard（full 会被静默归一 —— 装配台拿它显真）
    _th_want = (_pd.get("soul_thickness") or "standard") if _cur else "standard"
    _th_eff = _th_want if _th_want in ("thin", "standard") else "standard"

    try:
        from soul_loader import load_soul
        # wish-9de9bce3 · 精准磨：编辑某档时，目录按该档「已全量提上的」去重（与真装口径同源）
        _sp_excl = None
        if _cur:
            _tl_ex = (_pd.get("tools") if isinstance(_pd, dict) else None)
            if isinstance(_tl_ex, (list, tuple)) and _tl_ex:
                try:
                    from agent_tools._tool_catalog import visible_names as _vn
                    _sp_excl = set(_vn(set(_tl_ex))) or None
                except Exception:
                    _sp_excl = None
        sp = load_soul(root, with_runtime=True, catalog_exclude=_sp_excl).system_prompt or ""
        _thin_tok = 0
        if _th_want == "thin":
            _sp_thin = load_soul(root, with_runtime=True, thickness="thin").system_prompt or ""
    except Exception as _e:
        return {"ok": False, "error": f"load_soul 失败: {_e}"}
    segs = _soul_segments(sp)
    if not segs:
        return {"ok": False, "error": "切不出任何块 —— SECTION_MARKS 可能没对上"}
    _tot = sum(s["tokens"] for s in segs)

    # tiktoken（条目 tok / 工具 tok 共用）
    try:
        import json as _json
        import tiktoken as _tk
        _e2 = _tk.get_encoding("cl100k_base")

        def _tok2(_s):
            return len(_e2.encode(_s)) if _s else 0
    except Exception:
        import json as _json

        def _tok2(_s):
            return int(len(_s) / 0.67) if _s else 0

    # 左侧目录：按层分组
    _layers = []
    for _s in segs:
        _nm, _ln, _cl = _CTX_SEG_META.get(_s["key"], (_s["key"], "其他", "#718096"))
        _s["name"], _s["layer"], _s["color"] = _nm, _ln, _cl
        _hit = next((L for L in _layers if L["name"] == _ln), None)
        if _hit is None:
            _hit = {"name": _ln, "items": []}
            _layers.append(_hit)
        _hit["items"].append(_s)

    # 段 → 条目：按标题切（第一块带前言）—— 左栏三级 & 预览分块共用
    import re as _re3

    def _items_of(seg):
        _txt = seg.get("text") or ""
        _parts = _re3.split(r"(?m)^(#{1,4}\s+.+)$", _txt)
        _raw = []
        if _parts and _parts[0].strip():
            _raw.append(("（前言）", _parts[0]))
        for _i2 in range(1, len(_parts), 2):
            _head = _parts[_i2].strip()
            _rest = _parts[_i2 + 1] if _i2 + 1 < len(_parts) else ""
            _raw.append((_head.lstrip("#").strip(), _rest))
        return [{"name": _nm2, "text": (_tx2 if _nm2 == "（前言）" else _nm2 + "\n" + _tx2),
                 "tokens": _tok2(_tx2 if _nm2 == "（前言）" else _nm2 + "\n" + _tx2)}
                for _nm2, _tx2 in _raw]

    _toc = []
    for L in _layers:
        _sub = sum(i["tokens"] for i in L["items"])
        _toc.append(f'<div class="l1"><span>{_h.escape(L["name"])}</span><span class="tk">{_sub:,}</span></div>')
        for i in L["items"]:
            _badge = "" if i["inject"] else ' <span style="color:#9b93b5;font-size:10px">不进前缀</span>'
            _qm = ""
            if i["key"] == "catalog":
                _qm = ('<span class="qm" onclick="event.stopPropagation()" data-q="'
                       '延迟工具目录 = 没勾进本档的工具的「备用名单」（一行名字+简介）。'
                       '模型靠它知道库里还有什么、临时需要时能拉起来用。'
                       '已选工具确认足够的话，可以不开启它 —— 省下这块几千 tok；'
                       '代价是临时想用其他工具时模型很难想起。">?</span>')
            # BRO 2026-09-23：空段 / 不进前缀的段不参与层配置 —— 默认不勾 + 打 data-ni 标
            _ni = (not i["inject"]) or (i["tokens"] == 0)
            _niattr = ' data-ni="1"' if _ni else ""
            _ckattr = "" if _ni else " checked"
            _toc.append(
                f'<div class="l2" onclick="jump(\'{i["key"]}\')">'
                f'<input type="checkbox" class="l2c" data-l2ck="{i["key"]}"{_niattr}{_ckattr} '
                f'onclick="event.stopPropagation()" onchange="selKey(\'{i["key"]}\',this.checked)">'
                f'<span class="nm">{_h.escape(i["name"])}{_badge}</span>{_qm}'
                f'<span class="tk">{i["tokens"]:,}</span></div>'
            )
            for _j, _it in enumerate(_items_of(i)):
                _toc.append(
                    f'<label class="l3">'
                    f'<input type="checkbox" data-ck="{i["key"]}" data-j="{_j}"{_niattr}{_ckattr} onchange="iKey(this)">'
                    f'<span class="nm">{_h.escape(_it["name"])}</span>'
                    f'<span class="tk">{_it["tokens"]:,}</span></label>'
                )

    # ── 第三栏 · 工具（wish-740b2d2c）────────────────────────
    # BRO：「各种层 / 工具 / 实时拼出来的效果」—— 工具单独一栏，勾的时候能看它是干啥的。
    # 零破坏性：勾选只影响这一栏的合计，**不动 tools[] / 不动档位**。
    _titems = []
    _CORESET = []
    _tnames = {}
    try:
        _tnames = (_json.loads((root / "data" / "cognition" / "tool_names.json").read_text(encoding="utf-8")) or {}).get("tools") or {}
    except Exception:
        _tnames = {}
    try:
        import agent_tools as _at
        from agent_tools._tool_catalog import CORE as _CORESET  # noqa: F811
        _CORESET = list(_CORESET)
        # 选中档位 → 按那一档的名单预勾（不选 = 按核心手）
        _allow = None
        if _cur:
            _tl = _pd.get("tools")
            if _tl == "CORE":
                _allow = set(_CORESET)
            elif isinstance(_tl, (list, tuple)):
                _allow = set(_tl)
        for _n, _spec in _at.REGISTRY.items():
            _d = " ".join((getattr(_spec, "description", "") or "").split())
            _sch = getattr(_spec, "input_schema", {}) or {}
            _c = _tok2(_json.dumps({"name": _n, "description": _d, "input_schema": _sch}, ensure_ascii=False))
            _on = (_n in _allow) if _allow is not None else (_n in _CORESET)
            _tm = _tnames.get(_n) or {}
            # 2026-09-21 · 延迟目录件（非核心）的实装体量 = 「名字+一句简介」一行
            #   （口径同 _tool_catalog._one_line：单行化 + 72 字截断）——供前端实装口径估算
            _lite = _d if len(_d) <= 72 else _d[:71] + "…"
            _l = _tok2(f"- {_n}: {_lite}")
            _titems.append((_n, _d[:800], _c, _on, _tm.get("cn") or "", _tm.get("tag") or "", _l))
        _titems.sort(key=lambda x: (not x[3], x[0]))
    except Exception:
        _titems = []
    # 中文名 + 标签（BRO：「工具那一栏不能做成原型这样的吗」—— 原型样：中文名 / 标签筛选 / 批量勾）
    _trows = "".join(
        f'<div class="titem{" on" if _c4 else ""}" data-n="{_h.escape(_n4)}" data-t="{_c}" data-l="{_l4}"'
        f' data-cn="{_h.escape(_cn4)}" data-tag="{_h.escape(_tg4)}" data-d="{_h.escape(_d4)}">'
        f'<span class="bx">{"✓" if _c4 else ""}</span>'
        + ((f'<span class="cn">{_h.escape(_cn4)}</span><span class="nm">{_h.escape(_n4)}</span>') if _cn4
           else f'<span class="cn">{_h.escape(_n4)}</span>')
        + f'<span class="tk">{_c:,}</span></div>'
        for _n4, _d4, _c, _c4, _cn4, _tg4, _l4 in _titems
    )
    _tagc = {}
    for _t5 in _titems:
        if _t5[5]:
            _tagc[_t5[5]] = _tagc.get(_t5[5], 0) + 1
    _tagchips = (f'<span class="tg on" data-tag="" onclick="tgPick(this)">全部 {len(_titems)}</span>'
                 + "".join(f'<span class="tg" data-tag="{_h.escape(_k5)}" onclick="tgPick(this)">'
                           f'{_h.escape(_k5)} {_v5}</span>'
                           for _k5, _v5 in sorted(_tagc.items(), key=lambda kv: (-kv[1], kv[0]))))

    # 2026-09-21 · 延迟目录 header 的 tok（供前端「实装口径」估算 —— header = 目录块里工具行之外的部分）
    _dir_hdr_tok = 0
    _dir_tok = 0
    for _s9 in segs:
        if _s9.get("key") == "catalog":
            _t9 = _s9.get("text") or ""
            _i9 = _t9.find("\n- ")
            _dir_hdr_tok = _tok2(_t9[:_i9]) if _i9 > 0 else _tok2(_t9)
            _dir_tok = _s9.get("tokens") or 0
            break

    # ── 左栏顶 · 档位选择器（装配台）──────────────
    _psel_html = ""
    if _profs:
        def _dot(k):
            return '<span class="ovd" title="这个档被改过（已存用户覆盖）"></span>' if k in _ovs else ""
        _btns = [f'<button class="pbtn{" on" if not _cur else ""}" data-k="" onclick="pPick(\'\')">新档位</button>']
        for _k in _porder:
            _btns.append(
                f'<button class="pbtn{" on" if _cur == _k else ""}" data-k="{_k}" onclick="pPick(\'{_k}\')">'
                f'{_h.escape(_profs[_k].get("name") or _k)}{_dot(_k)}</button>'
            )
        _psel_html = '<div class="grp">基于哪个档位</div><div class="prow">' + "".join(_btns) + '</div>'
        if _uprofs:
            _ub = []
            for _k in _uprofs.keys():
                _ub.append(
                    f'<button class="pbtn{" on" if _cur == _k else ""}" data-k="{_k}" onclick="pPick(\'{_k}\')">'
                    f'{_h.escape(_uprofs[_k].get("name") or _k)}</button>'
                )
            _psel_html += '<div class="grp">我的预设</div><div class="prow">' + "".join(_ub) + '</div>'
        # 这一档的真话 —— full 会被 load_soul 静默归一成 standard
        if _cur:
            _nm = _h.escape(_pd.get("name") or _cur)
            _tools_n = "CORE" if _pd.get("tools") == "CORE" else str(len(_pd.get("tools") or []))
            _alarm = ""
            if _th_want not in ("thin", "standard"):
                _alarm = (f'<div class="warn">⚠ 表里写的是 <b>{_h.escape(_th_want)}</b>，但 load_soul 只认 '
                          f'thin / standard —— 实际被归一成 standard。这一档写的厚度是假的。</div>')
            elif _th_want == "thin":
                _alarm = ('<div class="warn">⚠ 这一档装的是人格核 <b>soul/MINIMAL-CORE.md</b> '
                          '—— 不是下面这些段（段列表只对 standard 档成立）。</div>')
            _psel_html += (
                f'<div class="pinfo">这一档：<b>{_nm}</b> · 灵魂 {_h.escape(_th_want)}'
                f' · 工具 {_tools_n} 件{(" · <b>已改</b>（用户覆盖）") if _cur in _ovs else ""}</div>' + _alarm
            )
        else:
            _psel_html += '<div class="pinfo">新档位 · 从现在的真实前缀开始（不按任何档位重算）</div>'
        _psel_html += '<div class="pinfo" id="pinfoLive"></div>'
        # BRO 2026-09-21：「保存修改 / 回到初始」从底部挪到 stage 标题栏（stage.js 注入三按钮）。
        #   产物页只保留函数 pedSave/pedReset 供标题栏跨 frame 调用 · 按钮不再画在这里。

    _body = []
    for i in segs:
        _badge = "" if i["inject"] else ' <span class="warn">· 不进每轮前缀</span>'
        _why = '' if i["inject"] else f'<div class="meta">{_h.escape(i.get("why") or "")}</div>'
        if i["text"]:
            _inner = "".join(
                f'<div class="ib" id="i-{i["key"]}-{_j}" data-k="{i["key"]}" data-t="{_it["tokens"]}">'
                f'<div class="ibh">▸ {_h.escape(_it["name"])} · {_it["tokens"]:,} tok（未选 · 已折叠）</div>'
                f'<pre>{_h.escape(_it["text"])}</pre></div>'
                for _j, _it in enumerate(_items_of(i))
            )
        else:
            _inner = '<div class="empty">（这段当前不在 system prompt 里）</div>'
        _body.append(
            f'<section class="sec" id="s-{i["key"]}" data-t="{i["tokens"]}">'
            f'<h2><span style="color:{i["color"]}">■</span> {_h.escape(i["name"])}'
            f'<span class="tk">{i["tokens"]:,} tok · {i["tokens"] * 100 // max(_tot, 1)}%</span>{_badge}</h2>'
            f'{_why}{_inner}</section>'
        )

    # ── 前端切档要用两份数据（嵌进页里 —— 切档不重新请求）
    _pdata = {}
    for _k in list(_porder) + [x for x in _uprofs if x not in _profs]:
        _p0 = _all_profs.get(_k) or {}
        _tl0 = _p0.get("tools")
        _tw0 = _p0.get("soul_thickness") or "standard"
        if _tw0 not in ("thin", "standard"):
            _al0 = f'⚠ 表里写的是 <b>{_tw0}</b>，但 load_soul 只认 thin / standard —— 实际被归一成 standard。这一档写的厚度是假的。'
        elif _tw0 == "thin":
            _al0 = '⚠ 这一档装的是人格核 <b>soul/MINIMAL-CORE.md</b> —— 不是左侧那些段。'
        else:
            _al0 = ""
        _pdata[_k] = {
            "name": _p0.get("name") or _k,
            "th": _tw0,
            "thin": (_tw0 == "thin"),
            "tools": ("CORE" if _tl0 == "CORE" else list(_tl0 or [])),
            "alarm": _al0,
            # BRO 2026-09-23 报的 bug：切档时前端要按 layers 还原勾选（此前漏带 → 一律全勾·看不到自己的选择）
            "layers": _p0.get("layers") if isinstance(_p0.get("layers"), list) else None,
        }
    _data_json = (
        '<script type="application/json" id="coreData">'
        + _json.dumps(sorted(_CORESET), ensure_ascii=False).replace("<", "\\u003c")
        + '</script>'
        '<script type="application/json" id="profData">'
        + _json.dumps(_pdata, ensure_ascii=False).replace("<", "\\u003c")
        + '</script>'
        '<script type="application/json" id="sessProfData">'
        + _json.dumps(_sess_name, ensure_ascii=False).replace("<", "\\u003c")
        + '</script>'
        '<script type="application/json" id="dirMeta">'
        + _json.dumps({"hdr": _dir_hdr_tok, "tok": _dir_tok}, ensure_ascii=False)
        + '</script>'
        # BRO 2026-09-23：打开/重载即按当前档还原层勾选（此前无初始化 → 一律 HTML 硬编码全勾 →
        #   他取消勾选后被重载打回，且再点「保存修改」就把“全勾”真写回数据）
        '<script type="application/json" id="curProfData">'
        + _json.dumps(_cur or "", ensure_ascii=False)
        + '</script>'
    )

    _html_doc = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>前缀全貌</title>' + _PFX_CSS + '</head><body>'
        + _data_json +
        '<aside><div id="askWrap"><h1>前缀全貌</h1>'
        '<div class="ask">'
        '<div class="ask-t">说一句你要干什么 —— 它读工具目录，帮你挑该开哪几件</div>'
        '<textarea id="need" rows="2" placeholder="例：我要用 blender 捏个椅子 / 帮我做一份季度汇报 PPT"></textarea>'
        '<div class="btnrow" style="margin:7px 0 0"><button onclick="askLLM()">问它要开哪几件</button>'
        '<span class="tally" id="askSt"></span></div>'
        '<div class="adv" id="advice"></div>'
        '</div>'
        '<div class="pinrow"><div id="gsumMini"></div>'
        '<span class="moreLnk" id="moreBtn" onclick="pfxToggle()">我要自己配置 ▾</span></div>'
        '</div>'
        + _psel_html +
        f'<div class="sum">system prompt 共 <b>{len(sp):,}</b> 字符 · <b>{_tot:,}</b> tok · {len(segs)} 块<br>'
        '☑ 只控制右侧显示 —— 不决定任何东西进不进前缀</div>'
        '<div class="sum" id="gsum"></div>'
        '<div class="btnrow"><button onclick="selAll(1)">全选</button>'
        '<button onclick="selAll(0)">全不选</button></div>'
        + "".join(_toc) + '</aside>'
        '<nav><h1>工具</h1>'
        f'<div class="sum">库里 <b>{len(_titems)}</b> 件 · 核心手 <b>{len(_CORESET)}</b> 件<br>'
        '☑ 只影响这一栏合计 —— 不动 tools[] / 不动档位</div>'
        '<div class="btnrow"><button onclick="tAll(1)">全选</button>'
        '<button onclick="tAll(0)">全不选</button>'
        '<button onclick="tCore()">只留核心手</button>'
        '<span class="tally">已勾 <b id="tn">0</b> · <b id="tk">0</b> tok</span><span class="tknote" id="tkNote"></span>'
        '<span class="twarn" id="twarn" style="display:none">⚠ 超预设上限 40 件</span></div>'
        '<input id="tq" class="ts" placeholder="搜中文名 / 工具名 / 说明里的词…">'
        f'<div class="tags" id="tags">{_tagchips}</div>'
        '<div id="tgops" style="display:none"><button onclick="tgSelect(1)">全选这类</button>'
        '<button onclick="tgSelect(0)">全不选这类</button>'
        '<span class="sm" id="tgos"></span></div>'
        f'<div class="tlist" id="tlist">{_trows}</div>'
        '<div class="td" id="td">点工具名 → 这里显示它是干什么的</div>'
        '</nav>'
        '<main>' + "".join(_body) + '</main>'
        '<div class="mask" id="svMask"><div class="dlg">'
        '<h3>保存为预设</h3>'
        '<p>存下以后，新建对话的选档卡里就能直接选它。<br>存在本机 · 升级不覆盖。</p>'
        '<label>名字<input id="svName" maxlength="30" placeholder="例：3D 打印视频"></label>'
        '<div class="row"><button onclick="svClose()">取消</button>'
        '<button class="primary" onclick="svDo()">保存</button></div>'
        '</div></div><div class="tst" id="tst"></div><div id="tip"></div>'
        + _PFX_JS
        + '<script>(function(){try{var el=document.getElementById("curProfData");'
          'var k=el?(JSON.parse(el.textContent)||""):"";'
          'if(typeof pPick==="function")pPick(k);}catch(e){}})();</script>'
        + '</body></html>'
    )

    dst = root / "data" / "design" / "前缀全貌（实时）.html"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(_html_doc, encoding="utf-8")
    return {
        "ok": True,
        "stage_path": "data/design/前缀全貌（实时）.html",
        "total_tokens": _tot,
        "chars": len(sp),
        "blocks": [{"key": s["key"], "name": s["name"], "tokens": s["tokens"]} for s in segs],
    }


@router.post("/tool-suggest")
async def post_tool_suggest(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """说人话 → LLM 读工具目录 → 建议开哪几件（wish-6350cced · 装配台 B 方案）。

    BRO：「有个对话框，直接说明需求，调用 LLM 专门读工具目录来判断用户要用哪些工具？」
    输入: {"need": "我要用 blender 捏个椅子"}
    输出: {"ok": true, "tools": [英文名...], "profile": "档位 key 或 null", "why": "一句话为什么"}
    只读：不改档位、不写文件、不碰会话 —— 原型拿它勾选。
    """
    check_auth(authorization)
    from pathlib import Path as _P
    import json as _j
    root = _P(__file__).resolve().parent.parent
    payload = payload or {}

    need = (payload.get("need") or "").strip()[:500]
    if not need:
        return {"ok": False, "error": "need 为空"}

    # 工具目录（人话版）+ 档位表
    try:
        _names = (_j.loads((root / "data" / "cognition" / "tool_names.json").read_text(encoding="utf-8")) or {}).get("tools") or {}
    except Exception:
        _names = {}
    try:
        _profs = (_j.loads((root / "data" / "cognition" / "tool_profiles.json").read_text(encoding="utf-8")) or {}).get("profiles") or {}
    except Exception:
        _profs = {}

    import agent_tools as _at
    cats = []
    for _n in sorted(_at.REGISTRY.keys()):
        _m = _names.get(_n) or {}
        cats.append(f"- {_n}｜{_m.get('cn') or _n}｜{(_m.get('what') or '')[:60]}｜{_m.get('tag') or ''}")
    _ptxt = "；".join(
        f"{k}={v.get('name')}({v.get('tools') if isinstance(v.get('tools'), str) else len(v.get('tools') or [])}件)"
        for k, v in _profs.items()
    )

    # wish-e1178ade · 层清单（给 LLM 判断「这次要不要收起某些层」）——从内存 sp 切段·不重复 load
    _segs_lite = []
    try:
        from soul_loader import SECTION_MARKS as _SMK, SECTION_META as _SMT2
        from daemon_runtime import RUNTIME as _RT2
        _sp2 = getattr(_RT2, "system_prompt", "") or ""
        _marks2 = sorted([(_sp2.find(mk), k) for k, mk in _SMK.items() if _sp2.find(mk) >= 0])
        for _ix, (_pos, _k2) in enumerate(_marks2):
            _end2 = _marks2[_ix + 1][0] if _ix + 1 < len(_marks2) else len(_sp2)
            _segs_lite.append((_k2, _SMT2.get(_k2, ("", True, ""))[0], len(_sp2[_pos:_end2])))
    except Exception:
        _segs_lite = []
    _segs_txt = "；".join(f"{k}｜{nm}｜≈{ch // 3} tok" for k, nm, ch in _segs_lite) or "(无)"

    prompt = (
        "你在帮用户挑工具与「层」。用户说他想干什么：你从工具库里挑出真正需要的几件，"
        "并判断要不要帮他把某些「层」收起来省 token。\n\n"
        f"工具库（{len(cats)} 件 · 格式 英文名｜中文名｜干什么｜标签）：\n"
        + "\n".join(cats) + "\n\n"
        f"预设档位：{_ptxt}\n\n"
        f"层清单（默认全开 · 每轮都在系统提示里；≈tok 越大越费钱）：{_segs_txt}\n"
        "层的取舍规则（宁少勿多）：identity(身份)/rules(铁律)/runtime 永远不要关；"
        "structure(路标) 默认留着；"
        "catalog（延迟工具目录）在任务非常明确、用不上挑工具时才可以建议关；"
        "notebook(画像)/memories(自传)/evolution(成长) 只有用户明确说'要轻量/省 token/快'时才建议关。\n\n"
        f"用户说：{need}\n\n"
        '只输出 JSON（不要任何别的文字）：'
        '{"tools": ["英文名", ...], "profile": "档位 key 或 null", "why": "一句话为什么挑这些", '
        '"off_layers": ["要收起的层 key", ...]}'
        "。规则：只挑真用得上的 3-15 件，宁少勿多；tools 里必须是上面出现过的英文名；"
        "优先挑跟用户说的场景直接对应的专门工具，不要只挑 read_file / python_exec 这类谁都能用的通用件；"
        "如果用户说的就是某个预设档位的典型用途，可以直接给 profile；"
        "off_layers 大多数情况给空数组 []（默认不动层）。"
    )

    from daemon_runtime import RUNTIME
    if getattr(RUNTIME, "client", None) is None:
        return {"ok": False, "error": "RUNTIME.client 未初始化"}
    try:
        if getattr(RUNTIME, "provider", "") == "anthropic":
            _r = RUNTIME.client.messages.create(
                model=RUNTIME.model, max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )
            _txt = "".join(b.text for b in _r.content if getattr(b, "type", "") == "text").strip()
        else:
            _r = RUNTIME.client.chat.completions.create(
                model=RUNTIME.model, max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )
            _msg = _r.choices[0].message
            _txt = (_msg.content or "").strip()
            # 推理模型（deepseek-flash 等）把预算花在思考上时 content 会是空的 ——
            # 800 tok 实测被 reasoning_tokens 吃光（finish_reason=length）· 所以给到 4000 并留这道兜底
            if not _txt:
                _txt = (getattr(_msg, "reasoning_content", "") or "").strip()
    except Exception as _e:
        return {"ok": False, "error": f"LLM 调用失败: {_e}"}

    # 解析（容错：剥 ```json 围栏 / 截取第一个 {...}）
    _s = _txt.strip()
    if _s.startswith("```"):
        _s = _s[3:]
        if _s[:4].lower() == "json":
            _s = _s[4:]
        _s = _s.split("```")[0].strip()
    try:
        _out = _j.loads(_s)
    except Exception:
        import re as _re
        _m = _re.search(r"\{.*\}", _txt, _re.S)
        try:
            _out = _j.loads(_m.group(0)) if _m else {}
        except Exception:
            _out = {}
    if not isinstance(_out, dict):
        _out = {}
    _ts = [t for t in (_out.get("tools") or []) if isinstance(t, str) and t in _at.REGISTRY]
    _pf = _out.get("profile")
    # wish-e1178ade · off_layers：只认合法段键（identity/rules/runtime 服务端保底不关 · 双保险）
    try:
        from soul_loader import SECTION_MARKS as _SMK3
        _valid3 = set(_SMK3.keys())
    except Exception:
        _valid3 = set()
    _off = [k for k in (_out.get("off_layers") or [])
            if isinstance(k, str) and k in _valid3 and k not in ("identity", "rules", "runtime")]
    return {
        "ok": True,
        "tools": _ts,
        "profile": _pf if _pf in _profs else None,
        "why": str(_out.get("why") or "")[:300],
        "off_layers": _off,
        "n_lib": len(cats),
        "raw": _txt[:600],  # 诊断用（本机 loopback 才调得到）· 挑空了看这里就知道模型说了啥
    }


@router.get("/context-usage")
async def get_context_usage(
    session_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """wish-bec4f3b9 · 当前会话上下文占用分块 + 缓存提示 (压缩圆圈 + Context Usage 卡片用).

    返回契约 = chat-compress-proto.html 的 MOCK:
      {total_tokens, max_tokens, used_pct, cache_hint,
       blocks: [{key,label,icon,color,tokens,sub}]}
    - soul/tools/rules/skills/profile 用 soul_loader 各段实测 (len//3 估 token · 中文偏 1:1 保守取 /3)
    - history 用 session jsonl 消息实测 (_estimate_tokens)
    - max_tokens = 当前模型 context_window × _get_ratio() (对齐 memory_compression.token_budget_check)
    """
    check_auth(authorization)
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent

    # ── 1. 固定分块 (soul_loader 实测 · 含 runtime 画像/演化) ──
    blocks = []
    try:
        from soul_loader import load_soul
        # wish-93b0cabf · 30s 缓存 · 避免每次轮询/done 重刷都全量 load_soul
        _now = time.time()
        # BRO 2026-09-23 报：卡片「固定前缀」显示的是**全量**（20.8k），与这一档实装（≈3k）不符。
        #   口径改成跟真装同一调用式（daemon_api 2164-2172 同源）：会话档配了 layers → sp_for_profile(该档)。
        #   缓存键带上档位（跨档不串）· 仍 30s 过期。
        _sess_pid = ""
        try:
            if session_id:
                from daemon_session import get_session_meta as _gsm0
                _sess_pid = (_gsm0(session_id) or {}).get("last_tool_profile") or ""
        except Exception:
            _sess_pid = ""
        if (_ctx_soul_cache.get("sp") is None
                or _ctx_soul_cache.get("pid") != _sess_pid
                or _now - _ctx_soul_cache.get("ts", 0) > 30):
            _sp_now = ""
            try:
                from daemon_runtime import sp_for_profile as _spfp0
                _sp_now = _spfp0(_sess_pid) or ""
            except Exception:
                _sp_now = ""
            if not _sp_now:      # 档没配 layers / 取不到 → 全量（零回归）
                _sp_now = load_soul(root, with_runtime=True).system_prompt or ""
            _ctx_soul_cache["sp"] = _sp_now
            _ctx_soul_cache["pid"] = _sess_pid
            _ctx_soul_cache["ts"] = _now
        sp = _ctx_soul_cache["sp"]
        # wish-31fd335e (2026-09-16) · 修三处口径:
        #   ① 段区间 — 原 _seg 是"从标记往后取 6 万字符"·铁律标记后不足 6 万字 → 实际取到全文尾
        #      (后果: Rules 行 == 整个 system·和 System prompt 行同数)
        #   ② token 真计数 — 原 len//3 (注释"中文保守取/3")·中文实测 ≈0.67 字符/token → 面板偏低约一半
        #   ③ 锚点 — 原 '=== BRO 的活人画像' 在 system 里不存在 (真锚点 '=== 画像 ===') → 该行是错拼的
        def _tok(s: str) -> int:
            """真 token 计数 (tiktoken) · 不可用时按中文实测系数 0.67 字符/token 退算。"""
            if not s:
                return 0
            try:
                import tiktoken
                return len(tiktoken.get_encoding("cl100k_base").encode(s))
            except Exception:
                return int(len(s) / 0.67)

        # 有序锚点 = soul_loader.SECTION_MARKS（**单一真相源** · wish-811eb5f5 第6步）
        # why: 原来这里手抄了一份硬编码锚点 → SKILL.md 改名后找不到就默默显示 0。
        # 现在从 soul_loader 拿：**改段头只改 soul_loader 一处，面板自动跟上**。
        _MARKS = []
        _META = {}
        try:
            from soul_loader import SECTION_MARKS as _SM
            from soul_loader import SECTION_META as _SMT
            _MARKS = [_SM[_k] for _k in (
                "structure", "identity", "rules", "const_common", "const_local",
                "runtime", "catalog", "memories", "notebook", "evolution",
            )]
            _META = dict(_SMT)
        except Exception:
            _MARKS = []

        def _seg_by_mark(mark: str) -> int:
            """本段 = 本锚点 → 下一个出现的锚点（按 _MARKS 顺序找最近的）"""
            idx = sp.find(mark)
            if idx < 0:
                return 0
            end = len(sp)
            for _other in _MARKS:
                if _other == mark:
                    continue
                _j = sp.find(_other, idx + 1)
                if 0 <= _j < end:
                    end = _j
            return _tok(sp[idx:end])

        # 每块都带 `file`（来源文件）—— BRO 看着数字就知道是谁贡献的
        _BLOCK_DEFS = [
            ("structure", "沉淀位地图", "ri-map-2-fill", "#9F7AEA", "data/cognition/STRUCTURE.md"),
            ("identity", "身份层", "ri-book-open-fill", "#4FD1C5", "soul/IDENTITY.md（摘录）"),
            ("rules", "规则层 · 工程铁律", "ri-shield-check-fill", "#F6AD55", "data/cognition/daemon_rules.md"),
            ("const_common", "规则层 · 宪法通用三条", "ri-scales-3-fill", "#ED8936", "内核 product_constitution.py"),
            ("const_local", "规则层 · 宪法本实例", "ri-scales-3-fill", "#DD6B20", "soul/CONSTITUTION.md"),
            ("runtime", "规则层 · Runtime", "ri-settings-3-fill", "#FBD38D", "soul_loader 代码生成"),
            ("catalog", "工具层 · 延迟目录", "ri-apps-2-fill", "#68D391", "agent_tools/_tool_catalog.py（实时渲染）"),
            ("memories", "灵魂层 · 自传", "ri-history-fill", "#B794F4", "soul/OPUS-MEMORIES.md"),
            ("notebook", "灵魂层 · 画像", "ri-user-heart-fill", "#FC8181", "soul/notebook/（一格一文件 · 进前缀 4 格）"),
            ("evolution", "灵魂层 · 成长", "ri-seedling-fill", "#F687B3", "soul/SELF-EVOLUTION.md（最近 3 条）"),
        ]

        # 拆格（wish-a4c007bb · 2026-09-28）：「三之二、怎么跟他干活」是画像里的独立一格，
        #   在灵魂层里单独占一行（BRO：「把自传换了…不要平铺，折叠了，放二级」——
        #   要的是平级成块，不是画像下面三级下钻）。
        #   注意：不给它加 SECTION_MARKS —— 那张表是按 index 跟 _BLOCK_DEFS 对齐的，插进去会错位。
        _HWW_TOK = 0
        try:
            from pathlib import Path as _P2
            import soul_loader as _SL2
            import re as _re4
            _nbt = _SL2._load_bro_notebook(_P2(__file__).resolve().parent.parent)
            for _q in _re4.split(r"\n(?=## )", _nbt):
                if '怎么跟他干活' in _q[:60]:
                    _HWW_TOK = _tok(_q)
                    break
        except Exception:
            _HWW_TOK = 0

        # soul 总块 = 整份 system prompt（明细块仅供拆解展示 · 总量不重复计入）
        blocks.append({"key": "soul", "label": "System prompt", "icon": "ri-file-settings-fill",
                       "color": "#B794F4", "tokens": _tok(sp),
                       "sub": "固定前缀 · 下列 10 块之和（与每轮后缀无关）"})
        def _rules_subblocks() -> list:
            """铁律文件的内部构成。

            wish-631ff85b · 为什么要这个：它 2/3 的体量**不在「铁律」上** ——
            而在「工具速查 hot path」和「场景索引表」。不摊开看，BRO 以为自己在读铁律，
            其实只看到 12%，治理就成了对着影子做决定。
            """
            try:
                from agent_tools.list_iron_rules import DAEMON_RULES_PATH as _DP
                from agent_tools.list_iron_rules import read_rules_text as _rrt
                _t = _rrt(_DP)
            except Exception:
                return []
            import re as _re2
            out = []
            for _p in _re2.split(r"\n(?=## )", _t):
                _h = _p.strip().split("\n")[0].lstrip("# ").strip()
                if _h:
                    out.append({"label": _h[:26], "tokens": _tok(_p)})
            return out

        for _i, (_k, _label, _icon, _color, _file) in enumerate(_BLOCK_DEFS):
            _mark = _MARKS[_i] if _i < len(_MARKS) else ""
            # 进/不进前缀 = 设计判据（soul_loader.SECTION_META 单一真相源 ·
            # wish-3ba1c0e2）—— 面板直接打标记，省得每次靠人回想。
            _m = _META.get(_k) or ("", True, "")
            # 显示名从 SECTION_META 第 4 位拿（单一真相源 · BRO 2026-09-30 抓过：
            #   这里手抄一份 label，改 soul_loader 层名时面板不跟）。
            #   第 4 位缺就退回 _BLOCK_DEFS 里的兜底值，向后兼容。
            if len(_m) > 3 and _m[3]:
                _label = _m[3]
            _t = _seg_by_mark(_mark) if _mark else 0
            if _k == "notebook" and _HWW_TOK:
                _t = max(0, _t - _HWW_TOK)   # 拆出去的那块不能重复计
            _blk = {
                "key": _k, "label": _label, "icon": _icon, "color": _color,
                "tokens": _t,
                "sub": _file, "file": _file,
                "layer": _m[0], "inject": bool(_m[1]),
                "why": _m[2] if len(_m) > 2 else "",
            }
            if _k == "rules":
                _sb = _rules_subblocks()
                if _sb:
                    _blk["sub_blocks"] = _sb
            blocks.append(_blk)

        # 拆格 · 灵魂层第二行（与「画像」平级 · 同源同文件）
        if _HWW_TOK:
            blocks.append({
                "key": "how-we-work", "label": "灵魂层 · 怎么跟他干活",
                "icon": "ri-hand-heart-fill", "color": "#F687B3",
                "tokens": _HWW_TOK,
                "sub": "soul/notebook/how-we-work.md",
                "file": "soul/notebook/how-we-work.md",
                "layer": "灵魂层 · 画像 / 成长", "inject": True,
                "why": "授权风格 / 验收标准 / 沟通纪律 —— 拆格后从画像单列出来",
            })
    except Exception:
        # 兜底锚点 (实测值 · soul_loader 加载失败时)
        blocks.append({"key": "soul", "label": "System prompt", "icon": "ri-file-settings-fill",
                       "color": "#B794F4", "tokens": 34923, "sub": "灵魂层 (实测锚点)"})
        blocks.append({"key": "profile", "label": "画像 & 记忆注入", "icon": "ri-user-heart-fill",
                       "color": "#FC8181", "tokens": 6000, "sub": "画像 + 演化日记 + 每轮检索注入"})

    # tools: REGISTRY 序列化实测 (单条 · 去重)
    # wish-16fa5930 · 跟会话档位联动：闲聊档只摊 12 件 · 面板数字必须跟着变（否则误导 BRO）
    try:
        from agent_tools import REGISTRY
        _tnames, _tpid = None, ""
        if session_id:
            try:
                from daemon_session import get_session_meta as _gsm2
                from workers.tool_profiles import resolve_profile as _rpf2
                _tpid, _tnames = _rpf2((_gsm2(session_id) or {}).get("last_tool_profile") or "")
            except Exception:
                _tnames = None
        _allowed = set(_tnames) if _tnames else None
        try:
            # wish-31fd335e · 修正：默认只算“手边”(CORE)工具 — 原来算 REGISTRY 全量 138 个，
            # 而真正进 tools[] 的是 visible_names(CORE≈36) · 面板因此偏高
            from agent_tools._tool_catalog import visible_specs as _vspecs
            _specs = _vspecs(_allowed)
        except Exception:
            _specs = [s for s in REGISTRY.values() if not _tnames or s.name in _tnames]
        # wish-31fd335e · 名字+描述走 tiktoken · 参数 schema 以英文/符号为主按 4 字符/token
        # (原来只算 name+description → 面板 tools 块比真实 schema 小 ~1/3)
        # 优先：按**真实发出去的 API 序列化**计数 (与 tool_loop.to_openai_tools 逐字一致)
        # wish-811eb5f5 · 修精度缺口：旧算法只加 name+description+schema，
        #   漏了 JSON 包装壳 {"type":"function","function":{...}} → 每件少计 ~23 tok
        #   · 30 件合计少 703 tok（面板 5,661 vs 真实 6,364）
        import json as _json

        def _tool_tokens(s) -> int:
            base = _tok(s.name + s.description)
            try:
                _sch = _json.dumps(getattr(s, "parameters", None) or getattr(s, "input_schema", {}) or {}, ensure_ascii=False)
            except Exception:
                _sch = ""
            return base + (_tok(_sch) if _sch else 0)

        try:
            from tool_loop import to_openai_tools as _to_api_tools
            _tt = _tok(_json.dumps(_to_api_tools(_specs), ensure_ascii=False))
            _exact = True
        except Exception:
            _tt = sum(_tool_tokens(s) for s in _specs)   # 退回逐件估算（偏低 ~23/件）
            _exact = False
        _tsub = f"{len(_specs)} 个工具 · 名字+描述+参数 schema"
        if not _exact:
            _tsub += "（估算口径·偏低）"
        if _tnames:
            _tsub += f" · 本档 {_tpid}"
        blocks.append({"key": "tools", "label": "Tool definitions", "icon": "ri-tools-fill",
                       "color": "#63B3ED", "tokens": _tt,
                       "sub": _tsub,
                       "file": "agent_tools/_tool_catalog.py（tools[] 按真实 API 序列化计数）"})

        # 每轮后缀 (wish-31fd335e · 字符数由 daemon_api 拼接 _sys_tail 时写进 RUNTIME)
        # telemetry+口吻+检索提示等·每轮变→缓存外·面板原来完全看不到它
        try:
            from daemon_runtime import RUNTIME as _RT2
            _sfx_chars = int(getattr(_RT2, "last_suffix_chars", 0) or 0)
        except Exception:
            _sfx_chars = 0
        if _sfx_chars:
            blocks.append({"key": "suffix", "label": "每轮后缀", "icon": "ri-timer-flash-fill",
                           "color": "#D6BCFA", "tokens": max(1, int(_sfx_chars / 2.5)),
                           "sub": "telemetry+口吻+检索提示 (每轮变 · 缓存外 · 按字符估)"})
    except Exception:
        blocks.append({"key": "tools", "label": "Tool definitions", "icon": "ri-tools-fill",
                       "color": "#63B3ED", "tokens": 22604, "sub": "97 个工具 (实测锚点)"})

    # ── 2. history: 优先用内存真实状态 (RUNTIME.messages = 压缩/修剪后的当前上下文) ──
    history_tokens = 0
    history_src = "内存 (压缩后真实状态)"
    sid = session_id or ""
    try:
        from daemon_runtime import RUNTIME
        if RUNTIME.messages:
            from workers.memory_compression import _estimate_tokens
            history_tokens = _estimate_tokens(RUNTIME.messages)
            # 会话匹配: 只在没显式指定 session 或指定的是当前会话时用内存
            # B-① · 2026-08-27 · RUNTIME.session_id 为空时也会误用内存估别的会话 · 条件放宽 (Grok 全量审计)
            if sid and sid != (RUNTIME.session_id or ""):
                history_tokens = 0  # 指定了别的会话 → 走磁盘
    except Exception:
        pass
    if history_tokens == 0:
        if sid:
            try:
                from daemon_session import load_session  # 现有加载器 · 返回 message list
                msgs = load_session(sid) or []
                from workers.memory_compression import _estimate_tokens
                history_tokens = _estimate_tokens(msgs)
                history_src = f"磁盘 {sid}"
            except Exception:
                try:
                    p = root / "sessions" / f"{sid}.jsonl"
                    if p.exists():
                        import json as _json
                        msgs = []
                        for line in p.read_text(encoding="utf-8").splitlines():
                            try:
                                msgs.append(_json.loads(line))
                            except Exception:
                                pass
                        from workers.memory_compression import _estimate_tokens
                        history_tokens = _estimate_tokens(msgs)
                        history_src = f"磁盘 {sid}"
                except Exception:
                    history_tokens = 0
        else:
            try:
                from daemon_session import load_session
                msgs = load_session("") or []
                from workers.memory_compression import _estimate_tokens
                history_tokens = _estimate_tokens(msgs)
                history_src = "磁盘"
            except Exception:
                history_tokens = 0
    # v3 · 这行文案要用 _get_ratio/_get_abs_cap, 而它们的 import 在下方(878) ——
    # 提前到这里, 不然 F821 Undefined name。
    from workers.memory_compression import _get_ratio, _get_abs_cap
    blocks.append({"key": "history", "label": "Conversation", "icon": "ri-chat-3-fill",
                   "color": "#A0AEC0", "tokens": history_tokens,
                   "sub": f"{history_src} · 超阈值触发压缩 (min(窗口×{_get_ratio():.2f}, {_get_abs_cap()//1000}K))"})

    # ── 3. max_tokens: 对齐 memory_compression.token_budget_check 真实阈值 ──
    #    阈值 = min(context_window × ratio, abs_cap) · 不是裸窗口×比例(ratio)
    max_tokens = 172000  # 兜底
    try:
        from workers.memory_compression import _get_context_window, _get_ratio, _get_abs_cap
        model_id = ""
        try:
            from daemon_runtime import RUNTIME
            model_id = RUNTIME.model or ""
        except Exception:
            pass
        if not model_id and sid:
            # 从 session meta 找模型 (尽力)
            try:
                from daemon_session import get_session_meta
                model_id = (get_session_meta(sid).get("model") or "")
            except Exception:
                pass
        cw = _get_context_window(model_id)
        if cw > 0:
            max_tokens = min(int(cw * _get_ratio()), _get_abs_cap())
        elif model_id:
            # 窗口未知但模型名有 → 用绝对线兜底
            max_tokens = _get_abs_cap()
    except Exception:
        pass

    # ── 4. 缓存提示: 最近一轮 cache_read > 0 = 前缀已预热 (+ 窗口命中率) ──
    # wish-631ff85b · 单看「上轮命中 N tok」看不出好坏 —— 上下文越长命中越多，是自然增长。
    # 真正有用的是**命中率**：它一旦掉下来，就说明前缀被改动了（缓存失效）。
    cache_hint = {"primed": False}
    try:
        p = root / "data" / "runtime" / "chat_turns_usage.jsonl"
        if p.exists():
            lines = p.read_text(encoding="utf-8").splitlines()
            if lines:
                import json as _json
                last = _json.loads(lines[-1])
                cache_hint = {"primed": (last.get("cache_read_tokens") or 0) > 0,
                              "last_cache_read": last.get("cache_read_tokens") or 0}
                # 窗口 = 近 24 小时（2026-09-19 · wish-9697480c）
                # 原来是固定「近 20 轮」—— 在密集开发期只覆盖十几分钟，样本太小：
                # 一次大改动就能把它拉到 50%，看着像"缓存崩了"，实际是"这两分钟恰好改过前缀"。
                # 按时间窗算才反映"最近一天的真实健康度"，也跟 BRO 定的基准口径一致
                # （稳定期 >97% / 开发期 93-94% 合理 / <89% 该警惕）。
                from datetime import datetime as _dt, timedelta as _td
                _cutoff = _dt.now() - _td(hours=24)
                _cr, _inp, _n = 0, 0, 0
                for _ln in reversed(lines):
                    try:
                        _o = _json.loads(_ln)
                    except Exception:
                        continue
                    _ts = _o.get("ts") or ""
                    try:
                        if _dt.fromisoformat(_ts) < _cutoff:
                            break
                    except Exception:
                        pass      # 时间戳读不动 → 算进来，不因解析失败丢样本
                    _cr += int(_o.get("cache_read_tokens") or 0)
                    _inp += int(_o.get("input_tokens") or 0)
                    _n += 1
                if _inp > 0:
                    cache_hint["hit_rate"] = round(_cr / _inp, 4)
                    cache_hint["window"] = _n
                    cache_hint["window_kind"] = "24h"
                    cache_hint["window_cache_read"] = _cr
                    cache_hint["window_input"] = _inp
    except Exception:
        pass

    # ── 主进度只算会话部分 (对齐 token_budget_check 压缩口径 · 固定块不进圆圈) ──
    # wish-31fd335e · 修重复计数: soul 块 = 整份 system prompt (已含下列各块)
    #   → 总量只加"顶层块": soul + tools + suffix + history; 明细块仅供拆解展示·不再重复计入
    # wish-811eb5f5 第6步 · 明细 key 改成层名 (structure/identity/rules/catalog/...)，
    #   它们全都含在 soul 里 → **不能进 _TOP_KEYS**（否则双倍计数）。
    _TOP_KEYS = {"soul", "tools", "suffix", "history"}
    total = sum(b["tokens"] for b in blocks if b["key"] in _TOP_KEYS)   # 真实固定前缀 + 会话
    history_tok = next((b["tokens"] for b in blocks if b["key"] == "history"), 0)
    fixed_tokens = total - history_tok
    used_pct = round(history_tok / max_tokens * 100, 1) if max_tokens else 0
    model = "unknown"
    try:
        from daemon_runtime import RUNTIME
        model = RUNTIME.model
    except Exception:
        pass
    return {
        "total_tokens": total,
        "fixed_tokens": fixed_tokens,
        "history_tokens": history_tok,
        "max_tokens": max_tokens,
        # v3 · 真实触发比例（前端 tooltip 直接读它 · 别再硬编 0.7 —— 调参时两边会打架）
        "ratio": _get_ratio(),
        "used_pct": used_pct,       # 会话部分占比 · 压缩检查同口径
        "model": model,
        "cache_hint": cache_hint,
        "blocks": blocks,
    }
