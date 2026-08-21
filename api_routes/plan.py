"""
api_routes/plan.py · 任务计划路由
=================================

给前端「对话框上方的计划条」供数 + 让用户直接改计划:

  GET    /api/plan/active   · 当前会话的活跃计划 (steps + 进度 + 关联 wish)
  PUT    /api/plan/steps    · 整份替换步骤 (用户在面板里重排/批量改)
  PATCH  /api/plan/step     · 改一步 (打钩 / 改文案 / 标跳过)
  POST   /api/plan/step     · 加一步
  DELETE /api/plan/step     · 删一步
  GET    /api/plan/list     · 所有任务账本 (面板里切历史任务)
  POST   /api/plan/open     · 把某个历史任务设为本会话活跃

为什么用户也能写(不只是 AI 写):
  产品观第 2 条闭环范式 —— AI 列的计划人得能改·否则人只能看着它跑偏。
  用户改完·下一轮 render_hint 就把新计划回灌给 AI·真的influences 下一次 LLM 调用。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Body, Header, HTTPException

from api_routes._deps import check_auth

router = APIRouter()


def _tp():
    from workers import task_plan as tp
    return tp


def _tl():
    from workers import task_ledger as tl
    return tl


def _shape(led: Optional[dict]) -> dict:
    """统一出参形状 · 前端只认这一种(空计划也给同样的键·省掉前端判空分支)。"""
    if not led:
        return {"active": False, "slug": "", "title": "", "steps": [], "progress": {}}
    tp = _tp()
    return {
        "active": bool(led.get("steps")),
        "slug": led.get("slug") or "",
        "title": led.get("title") or led.get("slug") or "",
        "steps": led.get("steps") or [],
        "progress": tp.progress(led),
        "wish_id": led.get("wish_id") or "",
        "updated": led.get("updated") or "",
        # 结论条数 —— 面板上标一下"这任务还攒了 N 条结论"·让人知道账本不只有清单
        "entry_count": len(led.get("entries") or []),
    }


def _active_led(session_id: str) -> Optional[dict]:
    tl = _tl()
    slug = tl.active_slug(session_id)
    return tl.get_ledger(slug) if slug else None


@router.get("/api/plan/active")
async def plan_active(session_id: str = "", authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    if not session_id:
        return _shape(None)
    return _shape(_active_led(session_id))


@router.get("/api/plan/list")
async def plan_list(limit: int = 30, authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    tl, tp = _tl(), _tp()
    rows = []
    for r in tl.list_ledgers(limit=max(1, min(100, limit))):
        led = tl.get_ledger(r.get("slug") or "")
        p = tp.progress(led) if led else {}
        rows.append({
            **r,
            "steps_total": p.get("total") or 0,
            "steps_settled": p.get("settled") or 0,
            "wish_id": (led or {}).get("wish_id") or "",
        })
    return {"items": rows}


@router.get("/api/plan/by-wish")
async def plan_by_wish(wish_id: str = "", authorization: Optional[str] = Header(None)):
    """反查: 这条心愿单干到第几步了(给心愿单面板用)。

    为什么反查而不是在 wish 里存 ledger_slug: 一条 wish 可能被拆成几本账
    (勘察一本 / 实施一本)·单字段存不住;而账本侧的 wish_id 是天然多对一。
    """
    check_auth(authorization)
    wish_id = (wish_id or "").strip()
    if not wish_id:
        raise HTTPException(400, "wish_id 必填")
    tl, tp = _tl(), _tp()
    out = []
    for r in tl.list_ledgers(limit=100):
        led = tl.get_ledger(r.get("slug") or "")
        if not led or led.get("wish_id") != wish_id:
            continue
        p = tp.progress(led)
        out.append({
            "slug": led.get("slug"),
            "title": led.get("title") or led.get("slug"),
            "updated": led.get("updated") or "",
            "steps_total": p.get("total") or 0,
            "steps_settled": p.get("settled") or 0,
            "all_done": p.get("all_done") or False,
            "current": (p.get("current") or {}).get("text") or "",
            "entry_count": len(led.get("entries") or []),
        })
    return {"wish_id": wish_id, "items": out}


@router.post("/api/plan/open")
async def plan_open(body: dict = Body(...), authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    sid = str(body.get("session_id") or "").strip()
    slug = str(body.get("slug") or "").strip()
    if not sid or not slug:
        raise HTTPException(400, "session_id 和 slug 都必填")
    tl = _tl()
    if tl.get_ledger(slug) is None:
        raise HTTPException(404, f"没有这本账本: {slug}")
    tl.set_active(sid, slug)
    return _shape(tl.get_ledger(slug))


@router.put("/api/plan/steps")
async def plan_set_steps(body: dict = Body(...), authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    sid = str(body.get("session_id") or "").strip()
    steps: Any = body.get("steps")
    if not sid:
        raise HTTPException(400, "session_id 必填")
    if not isinstance(steps, list):
        raise HTTPException(400, "steps 必须是数组")
    task = (str(body.get("task") or "").strip() or None)
    if not task and not _tl().active_slug(sid):
        raise HTTPException(400, "本会话还没有活跃任务 · 请带上 task(任务名)")
    led = _tp().set_steps(sid, steps, slug=task, title=task)
    if led is None:
        raise HTTPException(400, "计划落盘失败")
    return _shape(led)


@router.patch("/api/plan/step")
async def plan_update_step(body: dict = Body(...), authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    sid = str(body.get("session_id") or "").strip()
    if not sid:
        raise HTTPException(400, "session_id 必填")
    try:
        i = int(body.get("i"))
    except (TypeError, ValueError):
        raise HTTPException(400, "i(第几步 · 1 开始)必填且为整数")
    led = _tp().update_step(
        sid, i,
        status=body.get("status") or None,
        text=body.get("text") or None,
        note=body.get("note") if body.get("note") is not None else None,
        slug=(str(body.get("slug") or "").strip() or None),
    )
    if led is None:
        raise HTTPException(404, f"没找到第 {i} 步(或本会话没有活跃计划)")
    return _shape(led)


@router.post("/api/plan/step")
async def plan_add_step(body: dict = Body(...), authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    sid = str(body.get("session_id") or "").strip()
    text = str(body.get("text") or "").strip()
    if not sid or not text:
        raise HTTPException(400, "session_id 和 text 必填")
    after = body.get("after")
    try:
        after = int(after) if after is not None else None
    except (TypeError, ValueError):
        after = None
    led = _tp().add_step(sid, text, slug=(str(body.get("slug") or "").strip() or None), after=after)
    if led is None:
        raise HTTPException(400, "加不进去(没有活跃计划 · 或已到 40 步上限)")
    return _shape(led)


@router.delete("/api/plan/step")
async def plan_remove_step(body: dict = Body(...), authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    sid = str(body.get("session_id") or "").strip()
    if not sid:
        raise HTTPException(400, "session_id 必填")
    try:
        i = int(body.get("i"))
    except (TypeError, ValueError):
        raise HTTPException(400, "i(第几步)必填且为整数")
    led = _tp().remove_step(sid, i, slug=(str(body.get("slug") or "").strip() or None))
    if led is None:
        raise HTTPException(404, "删不掉(没有活跃计划或没这一步)")
    return _shape(led)
