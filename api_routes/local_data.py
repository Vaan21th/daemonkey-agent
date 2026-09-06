"""设置页本地占用 · GET /local-data · POST /local-data/purge"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException

from api_routes._deps import check_auth

router = APIRouter()


@router.get("/local-data")
def get_local_data(authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    from workers.local_data import usage
    return usage()


@router.post("/local-data/purge")
def purge_local_data(
    payload: Optional[dict] = Body(None),
    authorization: Optional[str] = Header(None),
):
    check_auth(authorization)
    ids = list((payload or {}).get("ids") or [])
    from workers.local_data import purge
    try:
        return purge(ids)
    except ValueError as e:
        raise HTTPException(400, str(e))
