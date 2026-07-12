"""api_routes/clients.py · 客户档案(合伙人记得每个客户)API

缺口②③ · 4 路由:
  GET  /dashboard/clients          · 客户清单 + stats(前端按 pipeline 阶段渲染)
  GET  /dashboard/clients/detail   · 单个客户完整档案 + 挂在名下的知识库文档
  POST /dashboard/clients/status   · 改 pipeline 阶段(UI 拖动/下拉)
  POST /dashboard/clients/delete   · 删档

注册顺序铁律: build_app() 里必须在 dashboard.router(/dashboard/{domain} catch-all)
**之前** include · 否则 /dashboard/clients 会被 catch-all 吞掉走成 domain='clients'。

建档/加备注的主入口是 NLP(对话里跟 OPUS 说 · 它调 manage_client)· 本路由只放
UI 侧的只读清单 + 快捷操作(改阶段/删除/看详情)。整体纳入内核白名单让升级用户可用。
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, File, Header, HTTPException, Request, UploadFile

from api_routes._deps import check_auth, safe_json_body

logger = logging.getLogger("opus.daemon.clients")

router = APIRouter()

# python-multipart 探测 · 缺包时 FastAPI 会在【路由定义期】就为 File()/UploadFile 抛错 →
# 整个 clients 路由 import 失败。升级用户(update_core 只搬 .py 不装 pip 包)可能就缺它。
# 所以按可用性条件定义上传端点:有则真上传·无则登记一个返 503 的同名端点·不拖垮整条路由。
# NLP 建档/记录/清单/搜索全不依赖 multipart·缺包也照常工作。
try:
    import multipart as _mp  # noqa: F401 — python-multipart
    _HAS_MULTIPART = True
    del _mp
except Exception:
    _HAS_MULTIPART = False


def _linked_docs(client_id: str) -> list[dict]:
    try:
        from workers.knowledge_base import list_documents
        return [d for d in list_documents() if d.get("client_id") == client_id]
    except Exception:
        return []


@router.get("/dashboard/clients")
def dashboard_clients(authorization: Optional[str] = Header(None)):
    """客户档案看板 · 清单 + 按 pipeline 阶段统计。"""
    check_auth(authorization)
    try:
        from workers import clients as cl
        return {"items": cl.list_clients(), "stats": cl.stats()}
    except Exception as e:
        logger.warning("clients endpoint failed: %s", e)
        raise HTTPException(500, f"clients failed: {e}")


@router.get("/dashboard/clients/detail")
def dashboard_clients_detail(
    client_id: str, authorization: Optional[str] = Header(None),
):
    """单个客户完整档案 + 挂在名下的知识库文档(点开客户卡片用)。"""
    check_auth(authorization)
    from workers import clients as cl
    cid = (client_id or "").strip()
    meta = cl.get_client(cid)
    if meta is None:
        raise HTTPException(404, f"client not found: {cid}")
    return {"ok": True, "client": meta, "docs": _linked_docs(cid)}


@router.get("/dashboard/clients/search")
def dashboard_clients_search(q: str = "", authorization: Optional[str] = Header(None)):
    """跨客户检索 · 一个词捞出名字/公司/需求/时间线命中的所有客户(第二大脑·跨客户面板)。"""
    check_auth(authorization)
    from workers import clients as cl
    try:
        return {"ok": True, "q": q, "items": cl.search_clients(q)}
    except Exception as e:  # noqa: BLE001
        logger.warning("clients search failed: %s", e)
        raise HTTPException(500, f"search failed: {e}")


@router.post("/dashboard/clients/note")
async def dashboard_clients_note(
    request: Request, authorization: Optional[str] = Header(None),
):
    """往客户时间线追加一条动态 · body: {client_id, text, kind?}。

    会议纪要模式整理出的纪要就一键存这里(kind=meeting)· 只增不改。
    """
    check_auth(authorization)
    body = await safe_json_body(request)
    cid = (body.get("client_id") or "").strip()
    text = (body.get("text") or "").strip()
    kind = (body.get("kind") or "note").strip().lower()
    if not text:
        raise HTTPException(400, "text 不能为空")
    from workers import clients as cl
    if kind not in cl.KINDS:
        kind = "note"
    try:
        meta = cl.append_note(cid, text, kind=kind)
    except KeyError:
        raise HTTPException(404, f"client not found: {cid}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "client": meta}


@router.post("/dashboard/clients/update")
async def dashboard_clients_update(
    request: Request, authorization: Optional[str] = Header(None),
):
    """UI 侧改字段 · body: {client_id, need?/name?/company?/role?/contact?/tags?}。不覆盖时间线。"""
    check_auth(authorization)
    body = await safe_json_body(request)
    cid = (body.get("client_id") or "").strip()
    changes = {k: body.get(k) for k in
               ("name", "company", "role", "contact", "tags", "need", "intent", "quote", "next")
               if body.get(k) is not None}
    if not changes:
        raise HTTPException(400, "没有要改的字段")
    from workers import clients as cl
    try:
        meta = cl.update_client(cid, **changes)
    except KeyError:
        raise HTTPException(404, f"client not found: {cid}")
    return {"ok": True, "client": meta}


@router.post("/dashboard/clients/status")
async def dashboard_clients_status(
    request: Request, authorization: Optional[str] = Header(None),
):
    """改 pipeline 阶段 · body: {client_id, status}。"""
    check_auth(authorization)
    body = await safe_json_body(request)
    cid = (body.get("client_id") or "").strip()
    status = (body.get("status") or "").strip()
    from workers import clients as cl
    if status not in cl.STATUSES:
        raise HTTPException(400, f"invalid status: {status}")
    try:
        meta = cl.update_client(cid, status=status)
    except KeyError:
        raise HTTPException(404, f"client not found: {cid}")
    return {"ok": True, "client": meta}


@router.post("/dashboard/clients/delete")
async def dashboard_clients_delete(
    request: Request, authorization: Optional[str] = Header(None),
):
    """删档 · body: {client_id}。挂在其名下的知识库文档不删·仅解除关联展示。"""
    check_auth(authorization)
    body = await safe_json_body(request)
    cid = (body.get("client_id") or "").strip()
    from workers import clients as cl
    try:
        meta = cl.remove_client(cid)
    except KeyError:
        raise HTTPException(404, f"client not found: {cid}")
    return {"ok": True, "deleted": meta["id"]}


# ── B-P0 · Excel/CSV 批量导入(合伙人接手现成客户名单)──────────────
#   两步: preview(上传→拆表→猜列映射) → import(确认映射→批量建档)。
#   preview 把拆好的行原样回给前端·import 时前端连行带映射回传(无状态·不落临时文件)。
if _HAS_MULTIPART:
    @router.post("/dashboard/clients/import-preview")
    async def dashboard_clients_import_preview(
        file: UploadFile = File(...), authorization: Optional[str] = Header(None),
    ):
        """上传 csv/xlsx → 拆表 + 猜列映射 · 返回表头/全部数据行/建议映射(前端渲染映射弹窗)。"""
        check_auth(authorization)
        from workers import clients as cl
        try:
            data = await file.read()
            headers, rows = cl.parse_table(data, file.filename or "")
        except Exception as e:  # noqa: BLE001 — 解析错误当 400 交给前端提示
            raise HTTPException(400, f"解析失败: {e}")
        truncated = len(rows) >= cl.MAX_IMPORT_ROWS
        return {
            "ok": True,
            "filename": file.filename or "",
            "headers": headers,
            "rows": rows[: cl.MAX_IMPORT_ROWS],
            "total": len(rows),
            "truncated": truncated,
            "suggested_mapping": cl.suggest_mapping(headers),
        }
else:
    @router.post("/dashboard/clients/import-preview")
    async def dashboard_clients_import_preview_unavailable(
        authorization: Optional[str] = Header(None),
    ):
        """降级占位:缺 python-multipart 时上传不可用·给明确提示而非 500/路由崩溃。"""
        check_auth(authorization)
        raise HTTPException(
            503,
            "Excel/CSV 上传需要 python-multipart · 请更新到最新整包 · "
            "或在运行环境里 pip install python-multipart 后重启 daemon。"
            "(对话里直接把客户信息告诉我·也能一条条建档·不依赖上传)",
        )


@router.post("/dashboard/clients/import")
async def dashboard_clients_import(
    request: Request, authorization: Optional[str] = Header(None),
):
    """确认映射后批量建档 · body: {rows[][], mapping{field:col}, dedupe?}。只新增·不覆盖。"""
    check_auth(authorization)
    body = await safe_json_body(request)
    rows = body.get("rows") or []
    mapping = body.get("mapping") or {}
    dedupe = bool(body.get("dedupe", True))
    from workers import clients as cl
    try:
        result = cl.import_rows(rows, mapping, dedupe=dedupe)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"import failed: {e}")
    return {"ok": True, **result}
