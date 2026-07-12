"""api_routes/knowledge.py · 私有文档知识库(第二大脑)API

知识库 MVP + P1 · 5 路由:
  GET  /dashboard/knowledge               · 文档清单 + stats(前端按文件夹分组渲染)
  POST /dashboard/knowledge/toggle        · 参考开关(静音/恢复)
  POST /dashboard/knowledge/flag          · 引用开关精细化(常驻 pinned / 敏感 sensitive)
  POST /dashboard/knowledge/delete        · 删档(原文+索引一起清)
  GET  /dashboard/knowledge/doc           · 单篇元数据+正文(前端点卡片弹窗预览)
  POST /dashboard/knowledge/import-report · 报告库一键存入知识库

注册顺序铁律: build_app() 里必须在 dashboard.router(/dashboard/{domain} catch-all)
**之前** include · 否则 /dashboard/knowledge 会被 catch-all 吞掉走成 domain='knowledge'。

灌文档的主入口是 NLP(对话里跟 OPUS 说 · 它调 manage_knowledge add)· 本路由只放
UI 侧的只读清单 + 快捷操作(开关/删除/预览/报告导入)。这块整体纳入内核白名单 ·
让升级用户能拿到「第二大脑」全套功能(不然 MVP 的存储/工具/端点根本下发不到)。
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request

from api_routes._deps import check_auth, safe_json_body
from daemon_api import ROOT

logger = logging.getLogger("opus.daemon.knowledge")

router = APIRouter()

_REPORTS_DIR = ROOT / "data" / "reports"


@router.get("/dashboard/knowledge")
def dashboard_knowledge(authorization: Optional[str] = Header(None)):
    """私有文档知识库看板 · 只读文档清单 + 参考/静音状态 + 文件夹归属。"""
    check_auth(authorization)
    try:
        from workers import knowledge_base as kb
        return {"items": kb.list_documents(), "stats": kb.stats()}
    except Exception as e:
        logger.warning("knowledge endpoint failed: %s", e)
        raise HTTPException(500, f"knowledge failed: {e}")


@router.post("/dashboard/knowledge/toggle")
async def dashboard_knowledge_toggle(
    request: Request, authorization: Optional[str] = Header(None),
):
    """参考开关 · body: {doc_id, enabled}。enabled=False 从召回静音·原文保留。"""
    check_auth(authorization)
    body = await safe_json_body(request)
    did = (body.get("doc_id") or "").strip()
    from workers import knowledge_base as kb
    try:
        meta = kb.set_enabled(did, bool(body.get("enabled")))
    except KeyError:
        raise HTTPException(404, f"doc not found: {did}")
    return {"ok": True, "doc": meta}


@router.post("/dashboard/knowledge/flag")
async def dashboard_knowledge_flag(
    request: Request, authorization: Optional[str] = Header(None),
):
    """引用开关精细化 · body: {doc_id, pinned?/sensitive?}。

    pinned=常驻(命中优先/靠前)· sensitive=敏感(不自动注入提示·仅显式召回可见)。
    只改元数据·不动索引/原文。
    """
    check_auth(authorization)
    body = await safe_json_body(request)
    did = (body.get("doc_id") or "").strip()
    changes = {}
    if "pinned" in body:
        changes["pinned"] = bool(body.get("pinned"))
    if "sensitive" in body:
        changes["sensitive"] = bool(body.get("sensitive"))
    if not changes:
        raise HTTPException(400, "no flag to set (pinned/sensitive)")
    from workers import knowledge_base as kb
    try:
        meta = kb.update_document(did, **changes)
    except KeyError:
        raise HTTPException(404, f"doc not found: {did}")
    return {"ok": True, "doc": meta}


@router.post("/dashboard/knowledge/delete")
async def dashboard_knowledge_delete(
    request: Request, authorization: Optional[str] = Header(None),
):
    """删档 · body: {doc_id} · 原文与索引一起清。"""
    check_auth(authorization)
    body = await safe_json_body(request)
    did = (body.get("doc_id") or "").strip()
    from workers import knowledge_base as kb
    try:
        meta = kb.remove_document(did)
    except KeyError:
        raise HTTPException(404, f"doc not found: {did}")
    return {"ok": True, "deleted": meta["id"]}


@router.get("/dashboard/knowledge/doc")
def dashboard_knowledge_doc(
    doc_id: str, authorization: Optional[str] = Header(None),
):
    """取单篇文档的元数据 + 正文 · 前端点卡片弹窗预览用。正文过长截断(只给预览·不是全文导出)。"""
    check_auth(authorization)
    from workers import knowledge_base as kb
    did = (doc_id or "").strip()
    meta = kb.get_document(did)
    if meta is None:
        raise HTTPException(404, f"doc not found: {did}")
    text = kb.read_document_text(did)
    _MAX = 60000
    truncated = len(text) > _MAX
    if truncated:
        text = text[:_MAX] + "\n\n…(内容较长·预览已截断·完整原文在你磁盘的原始文件)"
    return {"ok": True, "meta": meta, "text": text, "truncated": truncated}


@router.post("/dashboard/knowledge/import-report")
async def dashboard_knowledge_import_report(
    request: Request, authorization: Optional[str] = Header(None),
):
    """把报告库里的一份报告存入知识库 · body: {name}(报告 .docx 文件名)。
    优先灌 markdown 源(文本更干净)· 否则灌 docx。已灌过的不重复。归入「报告」文件夹。
    """
    check_auth(authorization)
    body = await safe_json_body(request)
    name = (body.get("name") or "").strip()
    if not name or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "invalid report name")
    docx_path = (_REPORTS_DIR / name).resolve()
    try:
        docx_path.relative_to(_REPORTS_DIR.resolve())
    except ValueError:
        raise HTTPException(403, "path escapes reports directory")
    if not docx_path.exists():
        raise HTTPException(404, f"report not found: {name}")

    from workers import knowledge_base as kb
    md_path = docx_path.with_suffix(".md")
    src = md_path if md_path.exists() else docx_path
    existing = kb.find_by_orig_path(src)
    if existing:
        return {"ok": True, "existed": True, "doc": existing}
    from workers.doc_ingest import IngestError
    try:
        meta = kb.add_document(str(src), tags=["报告"], folder="报告")
    except IngestError as e:
        raise HTTPException(422, f"ingest failed: {e}")
    return {"ok": True, "existed": False, "doc": meta}
