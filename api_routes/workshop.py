"""
api_routes/workshop.py · 工坊路由 (wish-413999da · phase 1)
==========================================================

18 路由 · 出品工坊全部:

  Apps CRUD (4):
    GET    /workshop/apps                       · 列所有 app
    GET    /workshop/apps/{aid}                 · 读单个 app
    POST   /workshop/apps                       · 落 / 更新
    DELETE /workshop/apps/{aid}                 · 软删 (移到回收站)

  Apps SSE 跑 (1):
    POST   /workshop/apps/{aid}/run             · scripted (HTTP) / agentic (LLM) · SSE

  Flows SSE 跑 (2):
    POST   /workshop/flows/run                  · 跑还没落盘的 (inline)
    POST   /workshop/flows/{fid}/run            · 跑已落盘的 (按 id)

  Flows CRUD (4):
    GET    /workshop/flows                      · 列
    GET    /workshop/flows/{fid}                · 读
    POST   /workshop/flows                      · 落 / 更新
    DELETE /workshop/flows/{fid}                · 软删

  Trash (4):
    GET    /workshop/trash                      · 列
    POST   /workshop/trash/{trash_id}/restore   · 恢复
    DELETE /workshop/trash/{trash_id}           · 真删一条
    DELETE /workshop/trash                      · 清空 (kind=app|flow|all)

  Files (3):
    GET    /workshop/preview/{domain}/{filename}  · 在线 markdown 预览 + frontmatter
    GET    /workshop/file/{domain}/{filename}     · 原始 .md 下载
    POST   /workshop/reveal/{domain}/{filename}   · 本机外部应用打开

注: app/flow run 的 SSE 用 daemon_api 模块级 _TURNS_LOCK / _ACTIVE_TURNS 共享
    (build_app() 末尾 include_router · 此时 daemon_api 已 load 完)
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from agent_tools._subprocess_helper import no_window_kwargs
from api_routes._deps import check_auth
from daemon_runtime import RUNTIME


ROOT = Path(__file__).resolve().parent.parent
_WORKSHOP_DOMAINS = {"content", "design", "dev", "docs"}


router = APIRouter()


def _resolve_workshop_md(domain: str, filename: str) -> "Path":
    """白名单 + 防越权 · 返回安全的 .md 绝对路径"""
    if domain not in _WORKSHOP_DOMAINS:
        raise HTTPException(400, f"invalid workshop domain: {domain}")
    if not filename.lower().endswith(".md"):
        raise HTTPException(400, "only .md files allowed")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "invalid filename")
    if filename.startswith(".") or filename.startswith("~"):
        raise HTTPException(400, "hidden / temp files forbidden")
    base = (ROOT / "data" / domain).resolve()
    path = (base / filename).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        raise HTTPException(403, "path escapes workshop directory")
    if not path.exists() or not path.is_file():
        raise HTTPException(404, f"workshop file not found: {domain}/{filename}")
    return path


# ─── Apps CRUD ───

@router.get("/workshop/apps")
async def workshop_list_apps(
    authorization: Optional[str] = Header(None),
):
    """列所有 app · 时间倒序"""
    check_auth(authorization)
    from workers.workshop_assets import list_apps
    return {"apps": list_apps()}


@router.get("/workshop/apps/{aid}")
async def workshop_load_app(
    aid: str,
    authorization: Optional[str] = Header(None),
):
    check_auth(authorization)
    from workers.workshop_assets import load_app
    app_data = load_app(aid)
    if not app_data:
        raise HTTPException(404, f"app not found: {aid}")
    return app_data


@router.post("/workshop/apps")
async def workshop_save_app(
    body: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """落 / 更新一个 app · body = app spec (含 name + description ...)"""
    check_auth(authorization)
    from workers.workshop_assets import save_app
    if not isinstance(body, dict):
        raise HTTPException(400, "body 必须是 JSON object")
    try:
        return save_app(body)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/workshop/apps/{aid}")
async def workshop_delete_app(
    aid: str,
    authorization: Optional[str] = Header(None),
):
    """软删 · 移到回收站 · 不再物理删 (wish-6fd76512)"""
    check_auth(authorization)
    from workers.workshop_assets import delete_app
    ok = delete_app(aid)
    if not ok:
        raise HTTPException(404, f"app not found or undeletable: {aid}")
    return {"ok": True, "id": aid, "moved_to_trash": True}


# ─── Apps SSE run (wish-165ea1f6 phase B/C) ───

@router.post("/workshop/apps/{aid}/run")
async def workshop_run_app(
    aid: str,
    payload: dict = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    """跑一个 app · SSE 流式 · 按 app.exec_kind 路由

    - exec_kind='scripted' → http_executor · 直接 HTTP · 0 LLM (phase C · 快/省/稳)
    - exec_kind='agentic'  → app_runner · LLM session · tool_loop (phase B · 灵活)
    """
    check_auth(authorization)
    if not isinstance(payload, dict):
        raise HTTPException(400, "request body must be a JSON object")

    from workers.workshop_assets import load_app
    app_data = load_app(aid)
    if not app_data:
        raise HTTPException(404, f"app not found: {aid}")

    exec_kind = (app_data.get("exec_kind") or "agentic").lower()
    if exec_kind == "agentic" and RUNTIME.client is None:
        raise HTTPException(503, "LLM client not initialized · /set_active_provider first (agentic apps need LLM)")

    inputs = payload.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise HTTPException(400, "inputs must be a JSON object")
    max_iterations = int(payload.get("max_iterations") or 12)

    # daemon_api 内 _TURNS_LOCK / _ACTIVE_TURNS 是共享 cancel 注册表
    from daemon_api import _TURNS_LOCK, _ACTIVE_TURNS

    run_id = "run-" + uuid.uuid4().hex[:12]
    cancel_event = threading.Event()
    with _TURNS_LOCK:
        _ACTIVE_TURNS[run_id] = cancel_event

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def push_event(event_type: str, data: dict) -> None:
        asyncio.run_coroutine_threadsafe(queue.put((event_type, data)), loop)

    def worker() -> None:
        try:
            if exec_kind == "scripted":
                from workers.http_executor import run_scripted_app
                result = run_scripted_app(
                    app=app_data,
                    inputs=inputs,
                    runtime=RUNTIME,
                    progress=push_event,
                )
            else:
                from workers.app_runner import run_app as _run_app
                result = _run_app(
                    app=app_data,
                    inputs=inputs,
                    runtime=RUNTIME,
                    progress=push_event,
                    cancel_check=cancel_event.is_set,
                    max_iterations=max_iterations,
                )
            push_event("done", result)
        except Exception as e:
            push_event("error", {"status": 500, "detail": f"{type(e).__name__}: {e}"})
        finally:
            with _TURNS_LOCK:
                _ACTIVE_TURNS.pop(run_id, None)

    threading.Thread(target=worker, daemon=True).start()

    async def event_stream():
        hello_payload = json.dumps({"run_id": run_id, "app_id": aid, "exec_kind": exec_kind})
        yield f"event: hello\ndata: {hello_payload}\n\n"

        KEEPALIVE = 25
        while True:
            try:
                event_type, data = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            try:
                data_str = json.dumps(data, ensure_ascii=False, default=str)
            except Exception:
                data_str = json.dumps({"error": "non-serializable event payload"})
            yield f"event: {event_type}\ndata: {data_str}\n\n"
            if event_type in ("done", "error"):
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ─── Flows SSE run ───

@router.post("/workshop/flows/run")
async def workshop_run_flow_inline(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """跑一条还没落盘的 workflow · BRO 在画布编辑时点 ▶ 真跑 · 不强迫先 save"""
    check_auth(authorization)
    if not isinstance(payload, dict):
        raise HTTPException(400, "request body must be a JSON object")
    graph = payload.get("litegraph_json")
    if not isinstance(graph, dict):
        raise HTTPException(400, "litegraph_json (dict) required")

    from workers.workflow_engine import flow_requires_llm as _flow_req_llm
    _flow_meta = _flow_req_llm(graph)
    if _flow_meta["requires_llm"] and RUNTIME.client is None:
        raise HTTPException(
            503,
            f"LLM client not initialized · agentic nodes: {_flow_meta['agentic_apps']} · "
            "set_active_provider 之后再跑·或把工作流改造成全 scripted",
        )

    entry_inputs = payload.get("entry_inputs") or {}
    max_iterations = int(payload.get("max_iterations") or 12)

    flow_data = {"id": "flow-inline", "name": "(inline)", "litegraph_json": graph}

    from daemon_api import _TURNS_LOCK, _ACTIVE_TURNS

    run_id = "frun-" + uuid.uuid4().hex[:12]
    cancel_event = threading.Event()
    with _TURNS_LOCK:
        _ACTIVE_TURNS[run_id] = cancel_event

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def push_event(event_type: str, data: dict) -> None:
        asyncio.run_coroutine_threadsafe(queue.put((event_type, data)), loop)

    def worker() -> None:
        try:
            from workers.workflow_engine import run_workflow
            result = run_workflow(
                flow=flow_data, entry_inputs=entry_inputs, runtime=RUNTIME,
                progress=push_event, cancel_check=cancel_event.is_set,
                max_iterations_per_node=max_iterations,
            )
            push_event("done", result)
        except Exception as e:
            push_event("error", {"status": 500, "detail": f"{type(e).__name__}: {e}"})
        finally:
            with _TURNS_LOCK:
                _ACTIVE_TURNS.pop(run_id, None)

    threading.Thread(target=worker, daemon=True).start()

    async def event_stream():
        yield f"event: hello\ndata: {json.dumps({'run_id': run_id})}\n\n"
        KEEPALIVE = 25
        while True:
            try:
                event_type, data = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            try:
                data_str = json.dumps(data, ensure_ascii=False, default=str)
            except Exception:
                data_str = json.dumps({"error": "non-serializable"})
            yield f"event: {event_type}\ndata: {data_str}\n\n"
            if event_type in ("done", "error"):
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/workshop/flows/{fid}/run")
async def workshop_run_flow(
    fid: str,
    payload: dict = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    """跑一条 workflow · 拓扑排序按 node 顺序串跑 · SSE 流式"""
    check_auth(authorization)
    if not isinstance(payload, dict):
        raise HTTPException(400, "request body must be a JSON object")

    from workers.workshop_assets import load_flow
    flow_data = load_flow(fid)
    if not flow_data:
        raise HTTPException(404, f"flow not found: {fid}")

    from workers.workflow_engine import flow_requires_llm as _flow_req_llm
    _flow_meta = _flow_req_llm(flow_data.get("litegraph_json") or {})
    if _flow_meta["requires_llm"] and RUNTIME.client is None:
        raise HTTPException(
            503,
            f"LLM client not initialized · agentic nodes: {_flow_meta['agentic_apps']} · "
            "set_active_provider 之后再跑·或把工作流改造成全 scripted",
        )

    entry_inputs = payload.get("entry_inputs") or {}
    max_iterations = int(payload.get("max_iterations") or 12)

    from daemon_api import _TURNS_LOCK, _ACTIVE_TURNS

    run_id = "frun-" + uuid.uuid4().hex[:12]
    cancel_event = threading.Event()
    with _TURNS_LOCK:
        _ACTIVE_TURNS[run_id] = cancel_event

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def push_event(event_type: str, data: dict) -> None:
        asyncio.run_coroutine_threadsafe(queue.put((event_type, data)), loop)

    def worker() -> None:
        try:
            from workers.workflow_engine import run_workflow
            result = run_workflow(
                flow=flow_data,
                entry_inputs=entry_inputs,
                runtime=RUNTIME,
                progress=push_event,
                cancel_check=cancel_event.is_set,
                max_iterations_per_node=max_iterations,
            )
            push_event("done", result)
        except Exception as e:
            push_event("error", {"status": 500, "detail": f"{type(e).__name__}: {e}"})
        finally:
            with _TURNS_LOCK:
                _ACTIVE_TURNS.pop(run_id, None)

    threading.Thread(target=worker, daemon=True).start()

    async def event_stream():
        hello_payload = json.dumps({"run_id": run_id, "flow_id": fid})
        yield f"event: hello\ndata: {hello_payload}\n\n"
        KEEPALIVE = 25
        while True:
            try:
                event_type, data = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            try:
                data_str = json.dumps(data, ensure_ascii=False, default=str)
            except Exception:
                data_str = json.dumps({"error": "non-serializable event payload"})
            yield f"event: {event_type}\ndata: {data_str}\n\n"
            if event_type in ("done", "error"):
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ─── Flows CRUD ───

@router.get("/workshop/flows")
async def workshop_list_flows(
    authorization: Optional[str] = Header(None),
):
    """列所有 workflow · 时间倒序 · 不带 graph 详情 (减体积)"""
    check_auth(authorization)
    from workers.workshop_assets import list_flows
    return {"flows": list_flows()}


@router.get("/workshop/flows/{fid}")
async def workshop_load_flow(
    fid: str,
    authorization: Optional[str] = Header(None),
):
    """读单个 workflow · 含完整 litegraph_json"""
    check_auth(authorization)
    from workers.workshop_assets import load_flow
    flow = load_flow(fid)
    if not flow:
        raise HTTPException(404, f"flow not found: {fid}")
    return flow


@router.post("/workshop/flows")
async def workshop_save_flow(
    body: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """落 / 更新一个 workflow · body 必含 name + description + litegraph_json"""
    check_auth(authorization)
    from workers.workshop_assets import save_flow
    if not isinstance(body, dict):
        raise HTTPException(400, "body 必须是 JSON object")
    try:
        return save_flow(body)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/workshop/flows/{fid}")
async def workshop_delete_flow(
    fid: str,
    authorization: Optional[str] = Header(None),
):
    check_auth(authorization)
    from workers.workshop_assets import delete_flow
    ok = delete_flow(fid)
    if not ok:
        raise HTTPException(404, f"flow not found or undeletable: {fid}")
    return {"ok": True, "id": fid, "moved_to_trash": True}


# ─── Trash (wish-6fd76512) ───

@router.get("/workshop/trash")
async def workshop_list_trash(
    authorization: Optional[str] = Header(None),
):
    """列回收站 · apps + flows 合并返"""
    check_auth(authorization)
    from workers.workshop_assets import list_trash_apps, list_trash_flows
    return {
        "apps": list_trash_apps(),
        "flows": list_trash_flows(),
    }


@router.post("/workshop/trash/{trash_id}/restore")
async def workshop_restore(
    trash_id: str,
    authorization: Optional[str] = Header(None),
):
    """恢复一条回收站项目 · id 用前缀区分 app- / flow-"""
    check_auth(authorization)
    from workers.workshop_assets import restore_app, restore_flow
    if trash_id.startswith("app-"):
        ok = restore_app(trash_id)
    elif trash_id.startswith("flow-"):
        ok = restore_flow(trash_id)
    else:
        raise HTTPException(400, f"id 必须以 app- 或 flow- 开头: {trash_id}")
    if not ok:
        raise HTTPException(
            404,
            f"无法恢复: {trash_id} (不在回收站 / active 已存在同 id)",
        )
    return {"ok": True, "id": trash_id, "restored": True}


@router.delete("/workshop/trash/{trash_id}")
async def workshop_empty_trash_one(
    trash_id: str,
    authorization: Optional[str] = Header(None),
):
    """真删一条回收站项目 · 不可恢复"""
    check_auth(authorization)
    from workers.workshop_assets import empty_trash_app, empty_trash_flow
    if trash_id.startswith("app-"):
        ok = empty_trash_app(trash_id)
    elif trash_id.startswith("flow-"):
        ok = empty_trash_flow(trash_id)
    else:
        raise HTTPException(400, f"id 必须以 app- 或 flow- 开头: {trash_id}")
    if not ok:
        raise HTTPException(404, f"回收站里没有: {trash_id}")
    return {"ok": True, "id": trash_id, "hard_deleted": True}


@router.delete("/workshop/trash")
async def workshop_empty_trash_all(
    kind: str = "all",
    authorization: Optional[str] = Header(None),
):
    """清空回收站 · query param kind = app | flow | all (默认 all)"""
    check_auth(authorization)
    from workers.workshop_assets import empty_trash_all
    kind = (kind or "all").strip().lower()
    if kind not in ("app", "flow", "all"):
        raise HTTPException(400, f"kind 必须是 app / flow / all: {kind}")
    n = empty_trash_all(kind)
    return {"ok": True, "kind": kind, "deleted_count": n}


# ─── Files preview / download / reveal (卷四十六续 8) ───

@router.get("/workshop/preview/{domain}/{filename}")
async def preview_workshop_file(
    domain: str,
    filename: str,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = None,
):
    """工坊产物在线预览 · 返回 markdown + frontmatter meta JSON · 给 webui mdRender"""
    if token and not authorization:
        authorization = f"Bearer {token}"
    check_auth(authorization)
    path = _resolve_workshop_md(domain, filename)
    raw = path.read_text(encoding="utf-8")
    meta: dict = {}
    md_body = raw
    if raw.startswith("---\n"):
        end = raw.find("\n---\n", 4)
        if end > 0:
            fm = raw[4:end]
            md_body = raw[end + 5:].lstrip("\n")
            for line in fm.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip()
    return {
        "ok": True,
        "domain": domain,
        "name": filename,
        "markdown": md_body,
        "meta": meta,
        "size_bytes": path.stat().st_size,
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
    }


@router.get("/workshop/file/{domain}/{filename}")
async def download_workshop_file(
    domain: str,
    filename: str,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = None,
):
    """原始 .md 下载 · 浏览器拿到后系统默认应用 (Typora / VSCode / 记事本) 打开"""
    if token and not authorization:
        authorization = f"Bearer {token}"
    check_auth(authorization)
    path = _resolve_workshop_md(domain, filename)
    return FileResponse(
        path,
        media_type="text/markdown; charset=utf-8",
        filename=filename,
    )


@router.post("/workshop/reveal/{domain}/{filename}")
async def reveal_workshop_file(
    domain: str,
    filename: str,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = None,
):
    """本机调系统外部应用打开 · 仅 daemon 跟 BRO 在同一台机器时有意义 (Day 0 阶段)"""
    if token and not authorization:
        authorization = f"Bearer {token}"
    check_auth(authorization)
    path = _resolve_workshop_md(domain, filename)
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)], **no_window_kwargs())
        else:
            subprocess.Popen(["xdg-open", str(path)], **no_window_kwargs())
        return {"ok": True, "domain": domain, "name": filename, "method": os.name}
    except Exception as e:
        return {
            "ok": False,
            "domain": domain,
            "name": filename,
            "error": f"{type(e).__name__}: {e}",
            "fallback_hint": "前端可改用下载按钮 · 浏览器拿到 .md 后系统会用默认应用打开",
        }


# ─── 产出画廊 (wish-ccd2fc5f · 内容制作预览 + 产出画廊) ───

@router.get("/workshop/outputs-list/{app_id}")
async def list_workshop_outputs(
    app_id: str,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = None,
):
    """列出 app 的输出文件 · 给工坊产出画廊用"""
    if token and not authorization:
        authorization = f"Bearer {token}"
    check_auth(authorization)
    if not app_id.startswith("app-"):
        raise HTTPException(400, "invalid app_id format")
    if "/" in app_id or "\\" in app_id or ".." in app_id:
        raise HTTPException(400, "invalid app_id")

    outputs_dir = ROOT / "data" / "workshop" / "outputs" / app_id
    if not outputs_dir.exists():
        return {"app_id": app_id, "files": [], "count": 0}

    _IMAGE = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
    _AUDIO = {".wav", ".mp3", ".ogg", ".flac", ".m4a"}
    _VIDEO = {".mp4", ".webm", ".mov"}

    files = []
    for f in sorted(outputs_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not f.is_file():
            continue
        name = f.name
        if name.startswith(".") or name.startswith("_"):
            continue
        suffix = f.suffix.lower()
        if suffix in _IMAGE:
            ft = "image"
        elif suffix in _AUDIO:
            ft = "audio"
        elif suffix in _VIDEO:
            ft = "video"
        else:
            ft = "other"
        files.append({
            "name": name,
            "size": f.stat().st_size,
            "mtime": f.stat().st_mtime,
            "type": ft,
            "url": f"/workshop/outputs/{app_id}/{name}",
        })

    return {"app_id": app_id, "files": files, "count": len(files)}
