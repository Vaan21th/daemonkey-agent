"""
api_routes/trust.py · 信任清单路由 (wish-413999da · phase 1)
==========================================================

3 路由 · trusted_commands 管理 (wish-f563a56d · shell_exec 30min/24h/永久信任窗口):

  GET    /trusted_commands              · 列当前条目 (顺手清过期 + 剩余秒数)
  POST   /trusted_commands              · 加一条 {pattern, duration_minutes, reason}
  DELETE /trusted_commands/{item_id}    · 删一条
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException

from api_routes._deps import check_auth


router = APIRouter()


@router.get("/trusted_commands")
async def list_trusted_commands(
    authorization: Optional[str] = Header(None),
):
    """列出当前 trusted commands · 顺手清过期"""
    check_auth(authorization)
    from workers import trusted_commands as tc
    items = tc.list_trusted(prune_expired=True)
    for it in items:
        it["_remaining_seconds"] = tc.remaining_seconds(it)
    return {"ok": True, "items": items}


@router.post("/trusted_commands")
async def add_trusted_command(
    body: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """加一条 trusted command
    body: {pattern, duration_minutes (None=永久), reason}
    """
    check_auth(authorization)
    from workers import trusted_commands as tc
    pattern = (body.get("pattern") or "").strip()
    duration_minutes = body.get("duration_minutes")
    reason = (body.get("reason") or "").strip()
    if duration_minutes is not None:
        try:
            duration_minutes = int(duration_minutes)
        except (ValueError, TypeError):
            raise HTTPException(400, "duration_minutes 必须是整数 (None / 0 = 永久)")
    try:
        item = tc.add_trusted(pattern=pattern, duration_minutes=duration_minutes, reason=reason)
    except ValueError as e:
        raise HTTPException(400, str(e))
    item["_remaining_seconds"] = tc.remaining_seconds(item)
    return {"ok": True, "item": item}


@router.delete("/trusted_commands/{item_id}")
async def delete_trusted_command(
    item_id: str,
    authorization: Optional[str] = Header(None),
):
    """删一条 trusted command"""
    check_auth(authorization)
    from workers import trusted_commands as tc
    ok = tc.remove_trusted(item_id)
    if not ok:
        raise HTTPException(404, f"trusted command not found: {item_id}")
    return {"ok": True}
