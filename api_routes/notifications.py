"""api_routes/notifications.py · 通知配置 2 路由 (wish-fb6b7427)

GET  /notification-config  · 读当前通知配置（文件不存在返回默认骨架）
POST /notification-config  · 写（merge · 只收已知字段）
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Header

from api_routes._deps import check_auth

router = APIRouter()


@router.get("/notification-config")
async def get_notification_config(authorization: Optional[str] = Header(None)):
    """读当前通知配置。"""
    check_auth(authorization)
    from workers.notification_config import load_notification_config

    return load_notification_config()


@router.post("/notification-config")
async def set_notification_config(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """写入通知配置。只收已知字段（pet_sound/windows_toast/tab_flash/pet_sound_path）。"""
    check_auth(authorization)
    from workers.notification_config import save_notification_config

    merged = save_notification_config(payload or {})
    return {"saved": True, "config": merged}
