"""api_routes/advisor.py · /api/advisor/status + /api/advisor/trace

wish-ea8922f7 · 顾问在场感的两个只读端点:

  GET /api/advisor/status         · 顾问实时状态 (live 卡 · 刷新/另一标签页恢复用)
  GET /api/advisor/trace?sub=<id> · 顾问过程回放 (解析 sessions/sub-<id>.jsonl 成时间线)

主路径其实是 SSE (tool_progress / advisor_status 事件实时推) ·
这两个端点是【兜底 + 回放】——BRO 刷新页面 / 换设备 / 事后想看顾问怎么推的。
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from typing import Optional

from api_routes._deps import check_auth

router = APIRouter()


@router.get("/api/advisor/status")
async def advisor_status(authorization: Optional[str] = Header(None)):
    """顾问实时状态 · 读 data/runtime/advisor_live.json (单一事实源)。"""
    check_auth(authorization)
    from workers import advisor_live
    return advisor_live.read_live()


@router.get("/api/advisor/trace")
async def advisor_trace(sub: str = "", authorization: Optional[str] = Header(None)):
    """顾问过程回放 · 把 sub session jsonl 解析成时间线节点列表。"""
    check_auth(authorization)
    if not (sub or "").strip():
        raise HTTPException(400, "sub 参数必填 (sub session id · replan 结果尾部的 sub-xxxx)")
    from workers import advisor_live
    nodes = advisor_live.parse_trace(sub)
    if nodes is None:
        raise HTTPException(404, f"顾问过程找不到或无法解析: {sub}")
    return {"sub": sub, "nodes": nodes, "count": len(nodes)}
