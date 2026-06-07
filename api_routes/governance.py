"""
api_routes/governance.py · 治理路由 (wish-413999da · phase 1)
============================================================

6 路由 · daemon 自治面板:

  GET  /status                       · 总状态 (model/provider/sessions/scheduler)
  GET  /api/token_budget/status      · Y2 · token 用量查询
  POST /api/token_budget/reset       · Y2 · 重置 token 用量
  GET  /api/ratelimit/status         · Y7 · 限流快照 (default disabled)
  GET  /api/audit/recent             · Y7 · 审计最近 N 条 (default disabled)
  GET  /api/proactive/status         · 卷六十 · 主动 CALL 判定 + 台账
  GET  /api/proactive/inbox          · 卷六十 · 收件箱 (前端心跳轮询)
  POST /api/proactive/test           · 卷六十 · 手动触发一次主动 CALL
  GET  /api/wechat/status            · 卷六十一 · iLink 微信渠道 / 24h 窗口 / 监听
  POST /api/wechat/test              · 卷六十一 · 手动给用户微信发一条
  POST /api/wechat/login/qr          · 卷六十一 · 取扫码登录二维码 (base64)
  GET  /api/wechat/login/poll        · 卷六十一 · 轮询扫码状态 · 落 token
  GET  /api/wechat/frequency         · 卷六十一 · 主动 CALL 频率档 (猫↔犬)
  POST /api/wechat/frequency         · 卷六十一 · 设频率档
  POST /api/session/repair           · R3 · 悬空 tool_call 自愈
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException

from api_routes._deps import check_auth
from daemon_runtime import RUNTIME


router = APIRouter()


@router.get("/status")
async def status(authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    scheduler_state = None
    try:
        from workers.scheduler import get_scheduler_state, is_scheduler_alive
        scheduler_state = {
            "alive": is_scheduler_alive(),
            **get_scheduler_state(),
        }
    except Exception:
        scheduler_state = {"alive": False}

    # _API_SESSIONS 在 daemon_api.py 模块级 · 跨模块共享 (import 时 daemon_api 已加载完)
    try:
        from daemon_api import _API_SESSIONS
        sessions_in_memory = list(_API_SESSIONS.keys())
    except Exception:
        sessions_in_memory = []

    return {
        "alive": True,
        "model": RUNTIME.model,
        "provider": RUNTIME.provider,
        "base_url": RUNTIME.base_url,
        "api_sessions_in_memory": sessions_in_memory,
        "default_confirm_policy": (
            os.environ.get("OPUS_API_DEFAULT_CONFIRM", "").strip() or "confirm"
        ),
        "scheduler": scheduler_state,
    }


@router.get("/api/token_budget/status")
async def token_budget_status_endpoint(
    session_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """卷四十六 III 补丁 5 · Y2 · token budget 状态查询

    Query params:
        session_id: 可选 · 给出会附加 session_total / session_calls

    Returns:
        limits / today / day_total / day_calls / session_count / (session_*)
    """
    check_auth(authorization)
    try:
        from workers.token_budget_guard import get_status as _tbg_status
        return _tbg_status(session_id)
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.get("/api/ratelimit/status")
async def ratelimit_status_endpoint(
    authorization: Optional[str] = Header(None),
):
    """卷四十六 III 补丁 5 · Y7 · 限流状态 · default disabled"""
    check_auth(authorization)
    try:
        from workers.rate_limiter import snapshot as _rl_snap
        return _rl_snap()
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.get("/api/audit/recent")
async def audit_recent_endpoint(
    n: int = 50,
    endpoint_filter: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """卷四十六 III 补丁 5 · Y7 · 审计最近 N 条 · default disabled

    Query:
        n: 1..500 · 默认 50
        endpoint_filter: 只看某个 endpoint · 例 '/chat'
    """
    check_auth(authorization)
    try:
        from workers.audit_logger import recent as _audit_recent, is_enabled
        return {
            "enabled": is_enabled(),
            "items": _audit_recent(n=n, endpoint_filter=endpoint_filter),
        }
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.post("/api/token_budget/reset")
async def token_budget_reset_endpoint(
    payload: dict = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    """卷四十六 III 补丁 5 · Y2 · 重置 token budget

    Args (JSON body · 都可选):
        session_id: 给出则只清这个 session
        day: 给出则只清这天 (YYYY-MM-DD)
        scope: 'session' / 'day' · 二选一

    例:
        POST /api/token_budget/reset {"session_id": "abc"}
        POST /api/token_budget/reset {"day": "2026-05-26"}
    """
    check_auth(authorization)
    if not isinstance(payload, dict):
        payload = {}
    try:
        from workers.token_budget_guard import reset_session, reset_day, get_status
        sid = (payload.get("session_id") or "").strip()
        day = (payload.get("day") or "").strip()
        if sid:
            reset_session(sid)
        if day:
            reset_day(day)
        if not sid and not day:
            reset_day()
        return {"ok": True, "status": get_status()}
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.get("/api/proactive/status")
async def proactive_status_endpoint(authorization: Optional[str] = Header(None)):
    """卷六十 · 主动 CALL 状态 · 只读判定 + 台账 · 不发 turn

    Returns: enabled / scheduler_alive / in_quiet_hours / calls_today /
        candidate_triggers / would_call_now / next_trigger / recent[]
    """
    check_auth(authorization)
    try:
        from workers.proactive_call import status as _pc_status
        return _pc_status()
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.get("/api/proactive/inbox")
async def proactive_inbox_endpoint(
    since: str = "",
    authorization: Optional[str] = Header(None),
):
    """卷六十 · 主动 CALL 收件箱 · 前端心跳轮询 · 返回 since 之后投递的主动消息

    Query:
        since: ISO 时间戳 · 只返回此刻之后投递的 · 空则返回空 (避免回放历史)

    前端据此弹 toast + 自动加载对应 session · 让用户不用手刷就看到主动开口。
    """
    check_auth(authorization)
    from datetime import datetime, timezone

    def _parse(ts: str):
        if not ts:
            return None
        try:
            d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    since_dt = _parse(since)
    if since_dt is None:
        return {"items": []}
    try:
        from workers.proactive_call import _read_ledger
        items = []
        for e in _read_ledger():
            if not e.get("delivered"):
                continue
            e_dt = _parse(e.get("ts", ""))
            if e_dt is None or e_dt <= since_dt:
                continue
            items.append({
                "ts": e.get("ts"),
                "session_id": e.get("session_id"),
                "reason": e.get("reason"),
                "kind": e.get("kind"),
                "reply_preview": e.get("reply_preview", ""),
            })
        return {"items": items}
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.post("/api/proactive/test")
async def proactive_test_endpoint(
    payload: dict = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    """卷六十 · 手动触发一次主动 CALL · 让用户随时见证 (跳过防骚扰门控)

    Args (JSON body · 都可选):
        kind: 'silence' (默认) / 'ritual'

    后台 thread 跑真 LLM turn · 立刻返回 target_session · 几秒后打开那个 session 看 OPUS 的话。
    """
    check_auth(authorization)
    if not isinstance(payload, dict):
        payload = {}
    kind = (payload.get("kind") or "silence").strip()
    try:
        import threading
        from workers.proactive_call import build_test_trigger, run_proactive_call, _proactive_session
        trigger = build_test_trigger(kind)
        sid = _proactive_session()

        def _go():
            run_proactive_call(trigger, force=True)

        threading.Thread(target=_go, daemon=True, name="opus-proactive-test").start()
        return {
            "triggered": True,
            "target_session": sid,
            "trigger": trigger,
            "note": "几秒后打开这个 session · 看 OPUS 的主动问候落地",
        }
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.get("/api/wechat/status")
async def wechat_status_endpoint(authorization: Optional[str] = Header(None)):
    """卷六十一 · iLink 微信渠道状态 · 配置 / 24h 窗口 / 监听线程 / 静默"""
    check_auth(authorization)
    try:
        from workers import ilink_client
        out = ilink_client.status()
        try:
            from workers.wechat_listener import get_state
            out["listener"] = get_state()
        except Exception:
            out["listener"] = {"alive": False}
        return out
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.post("/api/wechat/test")
def wechat_test_endpoint(
    payload: dict = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    """卷六十一 · 手动给用户微信发一条 · 验证 24h 窗口内主动推送

    ⚠ 同步 def：send_text 是阻塞 requests · async 会卡事件循环 (卷六十一续修)。

    Args (JSON · 可选): text (默认一句测试语)
    """
    check_auth(authorization)
    if not isinstance(payload, dict):
        payload = {}
    text = (payload.get("text") or "【OPUS·微信自测】这条是我主动推给你的，窗口还开着。").strip()
    try:
        from workers import ilink_client
        if not ilink_client.enabled():
            return {"ok": False, "reason": "not_configured", "note": "未扫码或 OPUS_WECHAT_ILINK=0"}
        if not ilink_client.window_open():
            return {"ok": False, "reason": "window_closed", "note": "你超过 24h 没在微信开口·先发条微信开窗"}
        r = ilink_client.send_text(text)
        return {"ok": bool(r.get("ok")), "resp": r}
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.post("/api/wechat/login/qr")
def wechat_login_qr_endpoint(authorization: Optional[str] = Header(None)):
    """取微信登录二维码 · 返回 base64 data URI 直接给 <img>

    ⚠ 故意写成同步 def (不是 async)：里面是阻塞式 requests.get(腾讯)·写成 async 会卡死
    事件循环·导致取码/轮询期间整个 daemon 假死 (卷六十一续修)。def 让 FastAPI 丢线程池跑。

    微信是标配功能（走腾讯官方 iLink·零私有服务器·每个用户扫码连自己的微信）。
    依赖 requests / qrcode 已写进 requirements。万一依赖没装全 / 临时取不到码·
    优雅返回 available=False·不抛 500。
    """
    check_auth(authorization)
    try:
        from workers.ilink_login import fetch_qr
    except Exception as e:
        return {
            "available": False,
            "note": f"微信模块加载失败（{type(e).__name__}）——多半是依赖没装全。"
                    "在项目目录跑一下 pip install -r requirements.txt（或 pip install requests qrcode）再重启即可。",
        }
    try:
        return fetch_qr()
    except Exception as e:
        return {
            "available": False,
            "note": f"微信二维码暂时取不到（{type(e).__name__}）·过一会儿再点一次。"
                    "如果一直不行·检查下网络能不能连 ilinkai.weixin.qq.com。",
        }


@router.get("/api/wechat/login/poll")
def wechat_login_poll_endpoint(
    qrcode: str = "",
    authorization: Optional[str] = Header(None),
):
    """卷六十一 · 轮询扫码状态 · confirmed 时落 token + 拉起监听

    ⚠ 同步 def：阻塞 requests · 前端每 2.5s 轮一次·若写 async 会反复卡死事件循环 (卷六十一续修)。"""
    check_auth(authorization)
    if not qrcode:
        raise HTTPException(400, "missing qrcode")
    try:
        from workers.ilink_login import poll_status
        return poll_status(qrcode)
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.get("/api/wechat/frequency")
async def wechat_frequency_get_endpoint(authorization: Optional[str] = Header(None)):
    """卷六十一 · 主动 CALL 频率档位 (猫系↔犬系) · 当前档 + 全部档位"""
    check_auth(authorization)
    try:
        from workers.proactive_prefs import status
        return status()
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.post("/api/wechat/frequency")
async def wechat_frequency_set_endpoint(
    payload: dict = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    """卷六十一 · 设主动 CALL 频率档位 · 写 env (即时 + 持久)"""
    check_auth(authorization)
    preset = (payload or {}).get("preset", "").strip()
    if not preset:
        raise HTTPException(400, "missing preset")
    try:
        from workers.proactive_prefs import set_preset, current_preset_id
        applied = set_preset(preset)
        return {"ok": True, "current": current_preset_id(), "applied": applied}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.post("/api/session/repair")
async def session_repair_endpoint(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """卷四十六 III 补丁 5 · R3 · 给用户手动触发 session 悬空 tool_call 自愈

    Args (JSON body):
        session_id: 必填 · 例 'aaff8c0c-...'
        dry_run: 默认 True · 只检测不改 · False 才真修

    Returns: workers.session_repair.repair_session 的返回结构 + 'ok' 字段
    """
    check_auth(authorization)
    if not isinstance(payload, dict):
        raise HTTPException(400, "request body must be a JSON object")
    session_id = (payload.get("session_id") or "").strip()
    if not session_id:
        raise HTTPException(400, "session_id is required")
    dry_run = bool(payload.get("dry_run", True))
    try:
        from workers.session_repair import repair_session
        return repair_session(session_id, dry_run=dry_run)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
