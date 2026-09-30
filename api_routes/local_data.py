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


# ─── wish-9d30a22e · 临时件智能扫描 / 可恢复清理 ─────────────────


@router.post("/local-data/temp-scan")
def temp_scan_start(authorization: Optional[str] = Header(None)):
    """起一次后台扫描 · 立即返回。

    状态落 data/runtime/temp_scan.json —— 切页面 / 刷新 / 关闭浏览器都不影响它。
    已经在跑就直接把当前状态原样返回，不会起来第二个。
    """
    check_auth(authorization)
    from workers.local_data import start_scan
    return start_scan()


@router.get("/local-data/temp-scan")
def temp_scan_status(authorization: Optional[str] = Header(None)):
    """查当前扫描状态：idle / running / done / error。

    done 时带 result（可直接渲染的表单）· error 时带 error 文案。
    前端每次挂载这个页都先问这里 —— 所以「扫到一半切走再回来」能看到进行中。
    """
    check_auth(authorization)
    from workers.local_data import scan_status
    return scan_status()


@router.post("/local-data/temp-purge")
def temp_purge(
    payload: Optional[dict] = Body(None),
    authorization: Optional[str] = Header(None),
):
    """清掉选中的候选 · 只认扫描出的 id。

    mode="trash"（默认）→ 移到 data/runtime/trash/<ts>/ · 还能捞回来
    mode="delete"        → 永久删除 · 找不回
    """
    check_auth(authorization)
    from workers.local_data import purge_paths
    p = payload or {}
    paths = list(p.get("paths") or [])
    mode = str(p.get("mode") or "trash")
    try:
        return purge_paths(paths, mode=mode)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ─── 回收站：列出 / 还原 / 清空（2026-10-01 补）────────────────
#
# 之前只有 purge_paths 往里【写】，没有任何往外的通道 —— 挪进回收站的东西
# 既看不见也清不掉，等于把垃圾从 A 搬到 B。知识库删档也要把拖拽副本挪进来，
# 所以这个口必须先补全，否则一边修一边漏。


@router.get("/local-data/trash")
def trash_list(authorization: Optional[str] = Header(None)):
    """列回收站（data/runtime/trash/<ts>/ 每个批次 = 一次清理）。

    顺手跑一次 30 天剪枝 —— 打开页面就看到过往该清的已经清了，
    不用再为它单开一个定时任务。
    """
    check_auth(authorization)
    from workers.local_data import list_trash, prune_trash
    pruned = {}
    try:
        pruned = prune_trash()
    except Exception as e:  # noqa: BLE001 — 剪枝失败不该让面板打不开
        # 不抛是对的，但不能啥痕迹都不留: 剪枝是回收站唯一的 30 天过期入口，
        # 静默失败 = 垃圾永远清不掉，而面板显示的和「没东西可清」一模一样。
        import logging
        logging.getLogger(__name__).warning("prune_trash 失败，本次跳过: %s", e, exc_info=True)
        pruned = {"ok": False, "error": str(e)}
    data = list_trash()
    data["pruned"] = pruned
    return data


@router.post("/local-data/trash/restore")
def trash_restore(
    payload: Optional[dict] = Body(None),
    authorization: Optional[str] = Header(None),
):
    """还原 items=["<批次>/<相对路径>"]（就是 list 里 items 那个写法）。"""
    check_auth(authorization)
    from workers.local_data import restore_trash
    p = payload or {}
    return restore_trash(list(p.get("items") or []))


@router.post("/local-data/trash/empty")
def trash_empty(
    payload: Optional[dict] = Body(None),
    authorization: Optional[str] = Header(None),
):
    """清空回收站（body 带 batch 就只清那一批）—— 真删 · 找不回。"""
    check_auth(authorization)
    from workers.local_data import empty_trash
    p = payload or {}
    b = str(p.get("batch") or "").strip() or None
    return empty_trash(batch=b)
