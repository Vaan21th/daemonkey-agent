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
from pathlib import Path as _Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request

from api_routes._deps import check_auth, safe_json_body
from daemon_api import ROOT

logger = logging.getLogger("opus.daemon.knowledge")

router = APIRouter()

_REPORTS_DIR = ROOT / "data" / "reports"

# 2026-10-01 · 拖拽进来的原件固定落这里（BRO:「都要放到我们 daemonkey 某个固定的目录，
# 这个不能乱」）—— 跟 docs/（抽好的正文）分开，一眼能看出哪些是投递进来的原料。
INCOMING_DIR = ROOT / "data" / "knowledge" / "incoming"


@router.get("/dashboard/knowledge")
def dashboard_knowledge(authorization: Optional[str] = Header(None)):
    """私有文档知识库看板 · 只读文档清单 + 参考/静音状态 + 文件夹归属。"""
    check_auth(authorization)
    try:
        from workers import knowledge_base as kb
        # folders = 显式登记过的（含空文件夹）；文档自带的 folder 由前端合并，两边都算。
        return {"items": kb.list_documents(), "stats": kb.stats(), "folders": kb.list_folders()}
    except Exception as e:
        logger.warning("knowledge endpoint failed: %s", e)
        raise HTTPException(500, f"knowledge failed: {e}")


@router.post("/dashboard/knowledge/folder")
async def dashboard_knowledge_folder(request: Request, authorization: Optional[str] = Header(None)):
    """新建一个知识库文件夹（空文件夹也存得住 · 幂等）。

    BODY: {"name": "合同"}
    返回: {ok, name, created, folders: [...]}
    """
    check_auth(authorization)
    body = await safe_json_body(request)
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "没给文件夹名")
    from workers import knowledge_base as kb
    try:
        return kb.add_folder(name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/dashboard/knowledge/folder/remove")
async def dashboard_knowledge_folder_remove(request: Request, authorization: Optional[str] = Header(None)):
    """删一个知识库文件夹。

    BODY: {"name": "合同", "drop_docs": false}
    非空默认【拒绘】（不偷着把分组连文档一起干掉）；
    drop_docs=true 才把里面文档的 folder 清成 ""（回到未分类，文档本身不删）。
    返回: {ok, name, removed, moved_docs, folders} 或 {ok:false, doc_count, error}
    """
    check_auth(authorization)
    body = await safe_json_body(request)
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "没给文件夹名")
    from workers import knowledge_base as kb
    try:
        return kb.remove_folder(name, drop_docs=bool(body.get("drop_docs")))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/dashboard/knowledge/drop")
async def dashboard_knowledge_drop(
    request: Request, authorization: Optional[str] = Header(None),
):
    """拖拽进来的文件/文件夹 → 落 data/knowledge/incoming/ → 走同一个 add_document。

    BRO 2026-10-01:「用户拖拽进来的文件或者文件，都要放到我们 daemonkey 某个固定的
    目录，这个不能乱」—— 固定落点 INCOMING_DIR，子目录按拖进来的相对路径重建。

    为什么是上传而不是记路径：浏览器安全沙箱下，拖进来的 File 拿不到磁盘绝对路径，
    只能拿到内容本身。所以拖拽 = 复制一份进库里，跟原文件脱钩（前端会明确告知）。

    multipart: files=<文件>[] · rels=<相对路径>[]（可选·与 files 一一对应）· folder=<可选·覆盖推断>
    folder 推断：rel 的首段目录名（拖整个文件夹时 = 文件夹名），散文件没有 rel → 未分类。
    返回: {ok, saved_n, added_n, skipped_n, errors: [...]}
    """
    check_auth(authorization)

    from workers import knowledge_base as kb
    from workers.doc_ingest import IngestError

    form = await request.form()
    ups = [v for k, v in form.multi_items() if k == "files" and hasattr(v, "read")]
    if not ups:
        raise HTTPException(400, "没收到文件")

    rels = [str(v) for k, v in form.multi_items() if k == "rels"]
    forced_folder = str(form.get("folder") or "").strip()

    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    saved, added, skipped, errors = [], [], 0, []
    _INCOMING_ABS = INCOMING_DIR.resolve()

    for i, up in enumerate(ups):
        raw_name = str(getattr(up, "filename", "") or f"drop-{i}")
        rel = rels[i] if i < len(rels) else raw_name
        # 只取相对路径 —— 绝不能爬到 incoming 外面去。
        # Windows 下盘符/UNC/根锚点不是「路径的一段」: _Path("C:/x").parts 是 ('C:/','x')，
        # 那个 'C:/' 既不以 ':' 结尾也不在下面的黑名单里，会被当成普通目录名留下，
        # 于是 INCOMING_DIR / WindowsPath('C:/x') 里 pathlib 丢弃左侧 → 直接写到 C:/x。
        # 所以先用 anchor 把锚点整段摘掉，再逐段过滤。
        _txt = rel.replace("\\", "/")
        _p = _Path(_txt)
        if _p.anchor:
            _txt = _txt[len(_p.anchor):]
        parts = [p for p in _Path(_txt).parts
                 if p not in ("", ".", "..", "/") and not p.endswith(":")]
        if not parts:
            parts = [_Path(raw_name).name or f"drop-{i}"]
        safe_rel = _Path(*parts)
        dest = INCOMING_DIR / safe_rel
        # 第二道: 不管上面怎么绕，写盘前坐实它在 incoming 底下（软链/符号锚点也拦得住）
        try:
            dest.resolve().relative_to(_INCOMING_ABS)
        except ValueError:
            errors.append({"path": raw_name, "error": "路径越界 · 已跳过"})
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            # 重名不覆盖 —— 加 -1 / -2 后缀（用户可能是两次拖同一个名字的不同文件）
            if dest.exists():
                stem, suf = dest.stem, dest.suffix
                n = 1
                while dest.exists():
                    dest = dest.with_name(f"{stem}-{n}{suf}")
                    n += 1
            dest.write_bytes(await up.read())
        except Exception as e:  # noqa: BLE001
            errors.append({"path": raw_name, "error": f"落盘失败: {e}"})
            continue
        saved.append(str(dest))

        # 归属：显式给的 folder > 相对路径首段（拖文件夹时=文件夹名）> 未分类
        folder = forced_folder or (str(safe_rel.parts[0]) if len(safe_rel.parts) > 1 else "")
        try:
            meta = kb.add_document(str(dest), folder=folder)
            added.append({"id": meta.get("id"), "title": meta.get("title"),
                          "orig_path": meta.get("orig_path"), "chars": meta.get("chars"),
                          "folder": folder})
            if folder:
                try:
                    kb.add_folder(folder)      # 顺带把文件夹登记上（空组也不会消失）
                except Exception:  # noqa: BLE001
                    pass
        except IngestError as e:
            skipped += 1
            errors.append({"path": raw_name, "error": f"格式不支持: {e}"})
        except Exception as e:  # noqa: BLE001
            errors.append({"path": raw_name, "error": f"{type(e).__name__}: {e}"})

    logger.info("knowledge drop: 收 %d · 落盘 %d · 入库 %d · 跳过 %d · 失败 %d",
                len(ups), len(saved), len(added), skipped, len(errors))
    return {
        "ok": True, "saved": saved, "saved_n": len(saved),
        "added": added, "added_n": len(added),
        "skipped_n": skipped, "errors": errors,
    }


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
    """删档 · body: {doc_id} · 原文与索引一起清。

    2026-10-01 · 拖拽进来的那些，原件是我们复制到 data/knowledge/incoming/ 的副本，
    删档时一并送回收站（data/runtime/trash/，跟智能清理共用，能还原）。
    从用户自己盘上选进来的 —— 他的原文件一概不碰。
    """
    check_auth(authorization)
    body = await safe_json_body(request)
    did = (body.get("doc_id") or "").strip()
    from workers import knowledge_base as kb
    try:
        meta = kb.remove_document(did)
    except KeyError:
        raise HTTPException(404, f"doc not found: {did}")
    return {
        "ok": True,
        "deleted": meta["id"],
        # 前端据此提示「原件副本也一起进回收站了」—— 不说的话用户会以为文件凭空消失
        "original_dropped": bool(meta.get("original_dropped")),
        "trashed_to": meta.get("original_trashed_to") or "",
    }


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


# ══════════════════════════════════════════════════════════════
# 用户添加（wish · BRO 2026-09-30）
#   原话:「知识库我想让他支持用户添加，并且复用产物库的工坊产物 - 按应用的模式，
#          类似于有文件夹，然后有文件」「能用类似我得项目 - 添加一个项目，那个逻辑，
#          来选择文件夹或者选择文件」
#   旧状: 灌文档只有一条路 —— 在对话框跟 OPUS 说「把 D:\x.pdf 加进知识库」(NLP 调 manage_knowledge)。
#         UI 空态里那句提示就是这个意思。
#   本条给 UI 补上「自己选」的入口，同时【不分叉】:
#         · 选目录/选文件 → api_routes/picker.py（跟「我的项目」同一个实现）
#         · 摊平目录 → picker.scan_importable()（也是同一份）
#         · 入库 → workers.knowledge_base.add_document()（跟 NLP 那条路同一个函数）
#   所以这里没有任何新的抽取/存储逻辑，只是把已有的三段接起来。
# ══════════════════════════════════════════════════════════════

@router.post("/dashboard/knowledge/add")
async def dashboard_knowledge_add(request: Request, authorization: Optional[str] = Header(None)):
    """批量把本地文件 / 一个目录里的文件灌进知识库（幂等：灌过的跳过）。

    BODY:
      {
        "paths":     ["D:\\\\资料\\\\合同.pdf", "D:\\\\资料\\\\法规"],   # 文件或目录都可
        "folder":    "合同",          # 前端选的文件夹分组名（可选）
        "tags":      [],              # 附加标签（可选）
        "pinned":    false,
        "sensitive": false,
        "scan_dir":  true             # paths 里的目录要不要递归摊平（默认要）
      }
    返回: {ok, added: [...], added_n, skipped_n, skipped_ext, truncated, errors: [...]}
    """
    check_auth(authorization)
    body = await safe_json_body(request)

    from workers import knowledge_base as kb
    from workers.doc_ingest import IngestError

    raw = body.get("paths") or []
    if isinstance(raw, str):
        raw = [raw]
    raw = [str(p).strip() for p in raw if str(p).strip()]
    if not raw:
        raise HTTPException(400, "没给路径（paths 空）")

    folder = str(body.get("folder") or "").strip()
    tags = body.get("tags") or []
    pinned = bool(body.get("pinned"))
    sensitive = bool(body.get("sensitive"))
    scan_dir = bool(body.get("scan_dir", True))

    # ① 摊平：文件直接用 · 目录按 scan_dir 决定要不要递归（跟前端预览同一份实现）
    from api_routes.picker import scan_importable
    cands: list[str] = []
    skipped_ext = 0
    truncated = False
    for p in raw:
        pp = _Path(p)
        if pp.is_dir():
            if not scan_dir:
                continue
            r = scan_importable(pp, recursive=True)
            if r.get("ok"):
                cands.extend(r.get("files") or [])
                skipped_ext += int(r.get("skipped") or 0)
                truncated = truncated or bool(r.get("truncated"))
            else:
                pass
        else:
            r = scan_importable(pp, recursive=False)
            if r.get("ok") and r.get("files"):
                cands.extend(r["files"])
            else:
                skipped_ext += 1

    # 去重（同一次提交里重复选的路径）
    seen, uniq = set(), []
    for c in cands:
        k = str(_Path(c)).lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(c)

    # ② 幂等：已经灌过的 orig_path 直接跳过（不重复占索引）
    try:
        already = {str(d.get("orig_path") or "").lower() for d in kb.list_documents()}
    except Exception:  # noqa: BLE001
        already = set()

    added, skipped, errors = [], 0, []
    for c in uniq:
        if str(_Path(c)).lower() in already:
            skipped += 1
            continue
        try:
            meta = kb.add_document(c, tags=tags, pinned=pinned, sensitive=sensitive, folder=folder)
            added.append({"id": meta.get("id"), "title": meta.get("title"),
                          "orig_path": meta.get("orig_path"), "chars": meta.get("chars")})
        except IngestError as e:
            errors.append({"path": c, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            errors.append({"path": c, "error": f"{type(e).__name__}: {e}"})

    logger.info("knowledge add: %d 入库 · %d 已存在 · %d 格式不符 · %d 失败",
                len(added), skipped, skipped_ext, len(errors))
    return {
        "ok": True,
        "added": added, "added_n": len(added),
        "skipped_n": skipped, "skipped_ext": skipped_ext,
        "truncated": truncated, "errors": errors,
    }


@router.post("/dashboard/knowledge/scan")
async def dashboard_knowledge_scan(request: Request, authorization: Optional[str] = Header(None)):
    """选完文件夹先预览「将加入哪几篇」—— 不写库，只摊平。

    BODY: {"path": "D:\\\\资料"}
    返回: {ok, files: [...], count, skipped, truncated}
    """
    check_auth(authorization)
    body = await safe_json_body(request)
    p = str(body.get("path") or "").strip()
    if not p:
        raise HTTPException(400, "没给路径")
    from api_routes.picker import scan_importable
    return scan_importable(p, recursive=bool(body.get("recursive", True)))
