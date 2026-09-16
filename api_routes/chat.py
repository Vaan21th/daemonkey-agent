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
            thinking=_thinking,
            reasoning_effort=_reasoning_effort,
            advisor_coop=_advisor_coop,
            mode=_mode,
            tool_profile=_tool_profile,
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
    - max_tokens = 当前模型 context_window × 0.7 (对齐 memory_compression.token_budget_check)
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
        if _ctx_soul_cache["sp"] is None or _now - _ctx_soul_cache["ts"] > 30:
            soul = load_soul(root, with_runtime=True)
            _ctx_soul_cache["sp"] = soul.system_prompt or ""
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

        # 有序锚点 = soul_loader.load_soul 的拼装顺序 · 每段 = 本锚点 → 下一锚点
        _ANCHORS = [
            "=== DAEMON 工程铁律",
            "=== 产品宪法",
            "=== SKILL.md",
            "=== OPUS-MEMORIES.md",
            "=== Runtime context",
            "=== 画像 ===",
            "=== SELF-EVOLUTION",
            "## 更多工具（不在本轮 tools[]）",
        ]

        def _seg(i: int) -> int:
            idx = sp.find(_ANCHORS[i])
            if idx < 0:
                return 0
            end = len(sp)
            for _nxt in _ANCHORS[i + 1:]:
                _j = sp.find(_nxt, idx + 1)
                if _j >= 0:
                    end = _j
                    break
            return _tok(sp[idx:end])

        # soul 总 = 全量 (铁律+宪法+SKILL+自传+画像+演化都含在 system_prompt 里)
        blocks.append({"key": "soul", "label": "System prompt", "icon": "ri-file-settings-fill",
                       "color": "#B794F4", "tokens": _tok(sp), "sub": "灵魂层: 铁律+宪法+SKILL+自传+画像+演化 (全量)"})
        blocks.append({"key": "rules", "label": "Rules", "icon": "ri-shield-check-fill",
                       "color": "#F6AD55", "tokens": _seg(0), "sub": "daemon_rules 铁律"})
        blocks.append({"key": "skills", "label": "Skills", "icon": "ri-book-open-fill",
                       "color": "#4FD1C5", "tokens": _seg(2), "sub": "SKILL.md + 场景索引"})
        blocks.append({"key": "profile", "label": "画像 & 记忆注入", "icon": "ri-user-heart-fill",
                       "color": "#FC8181", "tokens": _seg(5) + _seg(6), "sub": "画像 + 演化日记 (易变 · 不进缓存)"})
        # 延迟工具目录 (wish-31fd335e · 单列 · 原被算进 profile 行) · 详情走 catalog_search
        blocks.append({"key": "catalog", "label": "延迟工具目录", "icon": "ri-apps-2-fill",
                       "color": "#68D391", "tokens": _seg(7), "sub": "名字+简介各一行 · 详情走 catalog_search"})
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
        import json as _json

        def _tool_tokens(s) -> int:
            base = _tok(s.name + s.description)
            try:
                _sch = _json.dumps(getattr(s, "parameters", None) or getattr(s, "input_schema", {}) or {}, ensure_ascii=False)
            except Exception:
                _sch = ""
            return base + (_tok(_sch) if _sch else 0)

        _tt = sum(_tool_tokens(s) for s in _specs)
        _tsub = f"{len(_specs)} 个工具 · 名字+描述+参数 schema"
        if _tnames:
            _tsub += f" · 本档 {_tpid}"
        blocks.append({"key": "tools", "label": "Tool definitions", "icon": "ri-tools-fill",
                       "color": "#63B3ED", "tokens": _tt,
                       "sub": _tsub})

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
    blocks.append({"key": "history", "label": "Conversation", "icon": "ri-chat-3-fill",
                   "color": "#A0AEC0", "tokens": history_tokens,
                   "sub": f"{history_src} · 超阈值触发压缩 (min(窗口×0.7, 256K))"})

    # ── 3. max_tokens: 对齐 memory_compression.token_budget_check 真实阈值 ──
    #    阈值 = min(context_window × ratio, abs_cap) · 不是裸窗口×0.7
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

    # ── 4. 缓存提示: 最近一轮 cache_read > 0 = 前缀已预热 ──
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
    except Exception:
        pass

    # ── 主进度只算会话部分 (对齐 token_budget_check 压缩口径 · 固定块不进圆圈) ──
    # wish-31fd335e · 修重复计数: soul 块 = 灵魂层全量 (已含 rules/skills/profile/catalog 明细)
    #   → 总量只加"顶层块": soul + tools + suffix + history; 明细块仅供拆解展示·不再重复计入
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
        "used_pct": used_pct,       # 会话部分占比 · 压缩检查同口径
        "model": model,
        "cache_hint": cache_hint,
        "blocks": blocks,
    }
