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
  POST /api/wechat/test              · 卷六十一 · 手动给 BRO 微信发一条
  POST /api/wechat/login/qr          · 卷六十一 · 取扫码登录二维码 (base64)
  GET  /api/wechat/login/poll        · 卷六十一 · 轮询扫码状态 · 落 token
  GET  /api/wechat/frequency         · 卷六十一 · 主动 CALL 频率档 (猫↔犬)
  POST /api/wechat/frequency         · 卷六十一 · 设频率档
  POST /api/session/repair           · R3 · 悬空 tool_call 自愈
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException, Request

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


@router.get("/api/git-debt")
async def api_git_debt(authorization: Optional[str] = Header(None)):
    """启动亮灯 · 当前 git 欠账 (只读 · 前端 header 胶囊启动时查 + 轮询)。

    2026-07-29 BRO 拍板: 欠账检查从「turn 结束兜底」扩到「开 WebUI 第一眼」——
    打开页面时若分支领先 master 未合 / 有未提交改动, 左上角胶囊亮灯。
    复用 workers.closure_check._git_debt (与收尾三问第四问同一事实源)。
    """
    check_auth(authorization)
    try:
        from workers.closure_check import _debt_text, _git_debt
        debt = _git_debt()
        if not debt:
            return {"debt": False}
        return {"debt": True, **debt, "message": _debt_text(debt)}
    except Exception as e:
        return {"debt": False, "error": str(e)}


@router.get("/api/git-debt/detail")
async def api_git_debt_detail(authorization: Optional[str] = Header(None)):
    """欠账详情 (只读) · 前端面板事实源: 文件清单 + 人话分类 + 分支领先 commits。

    2026-07-29 BRO 直批三件套 B: "我点击之后完全没法知道未提交的是什么" ——
    面板让 BRO 看见每个文件是什么 (代码工作/文档/账本/会话数据...) 再决定收不收。
    """
    check_auth(authorization)
    try:
        from workers.git_ops import git_debt_detail
        return git_debt_detail()
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.post("/api/git-collect")
async def api_git_collect(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """一键收进主干 (BRO 直批三件套 C · 2026-07-29)。

    BRO 原话: "coding 小白也能不说合主干 · 自己把完成工作合到主干防止被新实例覆盖"。
    master 上 = 安全 commit · 分支上 = 先 commit 再 merge_wish_to_master 五道保护。
    body 可带 {"session_id": "api-..."} → 精准归属收 (别的活跃会话裸奔改动留工作区)。
    """
    check_auth(authorization)
    try:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    except Exception:
        body = {}
    session_id = str((body or {}).get("session_id") or "").strip() or None
    try:
        from workers.git_ops import collect_to_master
        return collect_to_master(session_owner=session_id)
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


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

    前端据此弹 toast + 自动加载对应 session · 让 BRO 不用手刷就看到 OPUS 主动开口。
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
    """卷六十 · 手动触发一次主动 CALL · 让 BRO 随时见证 (跳过防骚扰门控)

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


# ── 0.9.0 (wish-aac348a1) · 飞书渠道 ─────────────────────────────

@router.get("/api/feishu/status")
async def feishu_status_endpoint(authorization: Optional[str] = Header(None)):
    """0.9.0 · 飞书渠道状态 · 配置 / token / 长连接监听"""
    check_auth(authorization)
    try:
        from workers import feishu_client
        out = feishu_client.status()
        try:
            from workers.feishu_listener import get_state
            out["listener"] = get_state()
        except Exception:
            out["listener"] = {"alive": False}
        return out
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.post("/api/feishu/config")
async def feishu_config_endpoint(authorization: Optional[str] = Header(None), payload: dict = Body(...)):
    """0.9.0 · 保存飞书配置 (app_id + app_secret + enabled) · 保存后自动拉起监听"""
    check_auth(authorization)
    app_id = (payload.get("app_id") or "").strip()
    app_secret = (payload.get("app_secret") or "").strip()
    enabled_flag = bool(payload.get("enabled", True))
    if not app_id or not app_secret:
        raise HTTPException(400, "app_id 和 app_secret 都要填")
    try:
        from workers import feishu_client
        feishu_client.save_config(app_id, app_secret, enabled_flag)
        token = feishu_client.get_tenant_token()
        if token:
            from workers.feishu_listener import start_listener_in_background
            start_listener_in_background()
            return {"ok": True, "token_ok": True, "status": feishu_client.status()}
        return {"ok": True, "token_ok": False, "warning": "配置已存但 token 获取失败 · 检查 app_id/app_secret", "status": feishu_client.status()}
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.post("/api/feishu/toggle")
async def feishu_toggle_endpoint(authorization: Optional[str] = Header(None), payload: dict = Body(...)):
    """0.9.0 · 启用/停用飞书监听 (enabled: bool)"""
    check_auth(authorization)
    try:
        from workers import feishu_client, feishu_listener
        feishu_client.set_enabled(bool(payload.get("enabled", True)))
        if payload.get("enabled"):
            feishu_listener.start_listener_in_background()
        return {"ok": True, "status": feishu_client.status(), "listener": feishu_listener.get_state()}
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.post("/api/feishu/test")
async def feishu_test_endpoint(authorization: Optional[str] = Header(None), payload: dict = Body(...)):
    """0.9.0 · 发一条测试消息到指定会话 (receive_id + receive_id_type) · 验证配置可用"""
    check_auth(authorization)
    try:
        from workers import feishu_client
        rid = (payload.get("receive_id") or "").strip()
        rtype = (payload.get("receive_id_type") or "chat_id").strip()
        text = (payload.get("text") or "✅ 这是 Daemonkey 飞书通道的测试消息").strip()
        if not rid:
            raise HTTPException(400, "receive_id 必填 (飞书会话/用户 ID)")
        r = feishu_client.send_text(text, rid, rtype)
        if r.get("ok"):
            return {"ok": True, "message_id": r.get("message_id")}
        return {"ok": False, "error": r.get("msg") or r.get("error")}
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.post("/api/feishu/webhook")
async def feishu_webhook_endpoint(authorization: Optional[str] = Header(None), payload: dict = Body(...)):
    """0.9.1 · 保存 L1 群机器人 webhook URL (零门槛推送 · 不用建应用)"""
    check_auth(authorization)
    url = (payload.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "webhook URL 必填")
    if not url.startswith("https://"):
        raise HTTPException(400, "URL 要以 https:// 开头 (复制飞书群机器人的完整地址)")
    try:
        from workers import feishu_client
        feishu_client.save_webhook(url)
        return {"ok": True, "status": feishu_client.status()}
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.post("/api/feishu/webhook/test")
async def feishu_webhook_test_endpoint(authorization: Optional[str] = Header(None), payload: dict = Body(...)):
    """0.9.1 · 通过群机器人 webhook 发一条测试消息 (验证 L1 推送通)"""
    check_auth(authorization)
    try:
        from workers import feishu_client
        text = (payload.get("text") or "✅ Daemonkey 飞书推送已接通 · 以后长任务完成/重要通知都会发到这里").strip()
        r = feishu_client.send_webhook(text)
        if r.get("ok"):
            return {"ok": True, "msg": "已发出 · 去群里看看有没有收到"}
        return {"ok": False, "error": r.get("msg") or r.get("error")}
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.post("/api/wechat/test")
def wechat_test_endpoint(
    payload: dict = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    """卷六十一 · 手动给 BRO 微信发一条 · 验证 24h 窗口内主动推送

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
            return {"ok": False, "reason": "window_closed", "note": "BRO 超过 24h 没在微信开口·先发条微信开窗"}
        r = ilink_client.send_text(text)
        return {"ok": bool(r.get("ok")), "resp": r}
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.post("/api/wechat/login/qr")
def wechat_login_qr_endpoint(authorization: Optional[str] = Header(None)):
    """卷六十一 · 取微信 ClawBot 登录二维码 · 返回 base64 data URI 直接给 <img>

    ⚠ 同步 def (不是 async)：里面是阻塞式 requests.get(腾讯)·写 async 会卡死事件循环·
    导致取码/轮询期间整个 daemon 假死 (卷六十一续修)。def 让 FastAPI 丢线程池跑。"""
    check_auth(authorization)
    try:
        from workers.ilink_login import fetch_qr
        return fetch_qr()
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.get("/api/wechat/login/poll")
def wechat_login_poll_endpoint(
    qrcode: str = "",
    authorization: Optional[str] = Header(None),
):
    """卷六十一 · 轮询扫码状态 · confirmed 时落 token + 拉起监听

    ⚠ 同步 def：阻塞 requests · 前端每 2.5s 轮一次·async 会反复卡死事件循环 (卷六十一续修)。"""
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
    """卷四十六 III 补丁 5 · R3 · 给 BRO 手动触发 session 悬空 tool_call 自愈

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


# ── 0.8.4 · 更新状态端点 (前端"有新版"胶囊用) ─────────────────────────
# 检查 Gitee 官方仓库是否有比本地更新的版本 · 返回版本号 + changelog 摘要。
# 10 分钟缓存防频繁拉 gitee · 失败静默 (无更新返回 has_update=False · 不阻塞 UI)。
_UPDATE_STATUS_CACHE: dict = {"ts": 0.0, "result": None}
_UPDATE_STATUS_TTL = 600  # 10s 秒级缓存

def _version_parts(v: str):
    import re
    # 支持 0.8.5 / 0.8.9a / 0.8.5beta / 0.8.5-hf1 / 0.9.1-beta-hf2 / 0.9.2beta 全格式
    # (2026-08-06 修: 旧正则只认 -hf1 单段后缀 · 0.8.9a / 0.9.1-beta-hf2 / 0.9.2beta 全解析失败 → 胶囊永不亮)
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:[-_]*([A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*))?$", (v or "").strip())
    if not m:
        return None
    nums = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    suffix = (m.group(4) or "").strip('-_')
    toks = [t for t in re.split(r'[-_]', suffix) if t]
    return (nums, toks)


def _suffix_rank(s) -> int:
    """后缀定序(多段): alpha/a=0 < beta=1 < 空(release)=2 < hfN(hotfix)=3 · 同序按字符串比。
    toks 可为 list(新实现) 或 str(旧调用·兼容)。"""
    import re
    if s is None:
        return 2
    if isinstance(s, str):
        toks = [t for t in re.split(r'[-_]', s) if t] if s else []
    else:
        toks = s
    if not toks:
        return 2
    if any(t.startswith("hf") for t in toks):
        return 3
    if any(t.startswith("beta") for t in toks):
        return 1
    if any(t.startswith("alpha") for t in toks):
        return 0
    if any(t.startswith("a") for t in toks):
        return 0  # 0.8.9a 的 a = alpha 变体
    return 2  # 未知后缀按 release 对待


def _remote_newer(local: str, remote: str) -> bool:
    """remote > local → True · 支持 0.8.5beta / 0.8.9a / 0.8.5-hf1 / 0.9.1-beta-hf2 / 0.9.2beta (2026-08-06 修)。"""
    lp, rp = _version_parts(local), _version_parts(remote)
    if not lp or not rp:
        return False
    for a, b in zip(lp[0], rp[0]):
        if b > a:
            return True
        if b < a:
            return False
    # 数字相同 → 后缀: hf(hotfix) > release > beta > alpha
    lr, rr = _suffix_rank(lp[1]), _suffix_rank(rp[1])
    if rr > lr:
        return True
    if rr < lr:
        return False
    return rp[1] > lp[1] if rp[1] != lp[1] else False


@router.get("/api/update-status")
async def api_update_status(authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    import time as _t
    now = _t.time()
    cache = _UPDATE_STATUS_CACHE
    if cache["result"] is not None and (now - cache["ts"]) < _UPDATE_STATUS_TTL:
        return cache["result"]

    result = {"has_update": False, "local_version": "", "remote_version": "",
              "changelog": "", "checked_at": now, "error": ""}
    # 本地版本
    try:
        from pathlib import Path
        _root = Path(__file__).resolve().parent.parent
        _mf = json_load(_root / "core_manifest.json")
        result["local_version"] = str(_mf.get("core_version") or "")
    except Exception as e:
        result["error"] = f"local: {e}"
        cache["result"] = result
        cache["ts"] = now
        return result

    # 拉远程 (官方 Gitee 仓库 raw manifest · 超时 5s · 失败静默)
    # 0.8.4 · 必须 async 执行 (asyncio.to_thread) · 同步 httpx 会阻塞 event loop 5s
    # (缓存未命中时所有请求卡住 · BRO 实测反馈"会不会拖慢性能" → 这是唯一的性能隐患点)
    try:
        import asyncio, httpx

        async def _fetch_remote():
            return await asyncio.to_thread(
                lambda: httpx.get(
                    "https://gitee.com/vaan21th/dae-monkey/raw/master/core_manifest.json",
                    timeout=5.0, follow_redirects=True,
                )
            )

        r = await _fetch_remote()
        remote_mf = r.json()
        remote_ver = str(remote_mf.get("core_version") or "")
        result["remote_version"] = remote_ver
        if remote_ver and _remote_newer(result["local_version"], remote_ver):
            result["has_update"] = True
            # changelog: 复用 startup_notices 的提取逻辑 (log_ref 累积文本取末段)
            try:
                from workers.startup_notices import _read_changelog
                result["changelog"] = _read_changelog(str(remote_mf.get("log_ref") or ""), max_chars=1200)
            except Exception:
                result["changelog"] = ""
    except Exception as e:
        result["error"] = f"remote: {e}"

    cache["result"] = result
    cache["ts"] = now
    return result


def json_load(p):
    import json
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)
