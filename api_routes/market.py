"""扩展市场 HTTP · 工作台中间栏可视化。NLP 入口是 list_market / submit_market。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from api_routes._deps import check_auth

router = APIRouter()


class InstallBody(BaseModel):
    id: str
    overwrite: bool = False


class ShareBody(BaseModel):
    kind: str
    name: str
    author: str = ""
    version: str = ""
    description: str = ""


class RateBody(BaseModel):
    id: str
    score: int


class InboxBody(BaseModel):
    number: int = 0
    action: str = ""
    reason: str = ""


@router.get("/market")
def market_get(authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    from workers.market_index import snapshot
    return snapshot()


@router.post("/market/install")
def market_install(body: InstallBody, authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    from workers import market_install as inst
    result = inst.install(body.id, overwrite=body.overwrite)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "安装失败")
    return {"ok": True, "output": result.get("output")}


@router.post("/market/share")
def market_share(body: ShareBody, authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    kind = (body.kind or "").strip().lower()
    name = (body.name or "").strip()
    if kind not in ("app", "flow", "skin") or not name:
        raise HTTPException(400, "kind 必须是 app/flow/skin，且 name 必填")
    from workers.market_submit import submit
    result = submit(
        kind=kind, name=name, author=body.author,
        version=body.version, description=body.description,
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "上架失败")
    return result


@router.post("/market/rate")
def market_rate(body: RateBody, authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    from workers.market_rate import rate
    result = rate(body.id, body.score)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "打分失败")
    return {"ok": True, "output": result.get("output"), "published": result.get("published")}


@router.get("/market/inbox")
def market_inbox(authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    from workers.market_inbox import list_inbox
    return list_inbox()


@router.post("/market/inbox")
def market_inbox_act(body: InboxBody, authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    action = (body.action or "").strip()
    from workers import market_inbox as inbox
    if action == "merge" and body.number:
        result = inbox.merge_one(body.number)
    elif action == "close" and body.number:
        result = inbox.close_one(body.number, body.reason)
    elif action in ("sweep_red", "merge_green"):
        result = inbox.sweep(action)
    else:
        raise HTTPException(400, "action 必须是 merge/close/sweep_red/merge_green")
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "待审操作失败")
    return result
