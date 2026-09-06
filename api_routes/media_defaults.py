"""api_routes/media_defaults.py · 设置多模态：默认生图 / 语音合成"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException

from api_routes._deps import check_auth

router = APIRouter()


@router.get("/media-defaults")
async def get_media_defaults(authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    from workers.media_defaults import status
    return status()


@router.post("/media-defaults")
async def set_media_defaults(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    check_auth(authorization)
    kind = (payload.get("kind") or "").strip()
    app_id = (payload.get("app_id") or "").strip()
    if kind not in ("image", "tts", "stt"):
        raise HTTPException(400, "kind 必须是 image / tts / stt")
    if app_id and not app_id.startswith("app-"):
        raise HTTPException(400, "app_id 必须是工坊应用")
    from workers.media_defaults import save
    if kind == "image":
        save(image_app_id=app_id)
    elif kind == "tts":
        save(tts_app_id=app_id)
    else:
        save(stt_app_id=app_id)
    from workers.media_defaults import status
    return {"ok": True, **status()}
