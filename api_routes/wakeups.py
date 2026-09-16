"""
api_routes/wakeups.py · 会话内延迟唤醒（计时器）路由 · wish-1b00ca00
=================================================================

给前端「对话输入栏上方的倒计时卡」供数:

  GET  /api/wakeups          · 当前会话的 armed 唤醒(附 remaining_sec)
  POST /api/wakeups/cancel   · 取消一条(body {id})

这是铁律 6 的第③件「可查」—— 后台跑的东西必须有对外端点能查, 前端断线重连
才能接着显示, 而不是只能猜。

写入一律走 workers/wakeups.py —— 跟 AI 工具层 set_wakeup 共用同一个执行函数 ·
不许两边各写一份(那会各自长歪, 而且两条路"看起来都能跑")。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Header

from api_routes._deps import check_auth

router = APIRouter()


def _w():
    from workers import wakeups as wk
    return wk


@router.get("/api/wakeups")
async def list_wakeups(session_id: str = "", authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    wk = _w()
    items = wk.list_armed(session_id)
    return {
        "session_id": session_id,
        "count": len(items),
        "wakeups": items,
        "scheduler": wk.get_wakeup_state(),
    }


@router.post("/api/wakeups/cancel")
async def cancel_wakeup_ep(body: Optional[dict] = Body(default=None),
                           authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    wid = str((body or {}).get("id") or (body or {}).get("wakeup_id") or "").strip()
    ok = _w().cancel_wakeup(wid)
    return {"ok": ok, "id": wid}
