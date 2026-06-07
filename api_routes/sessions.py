"""
api_routes/sessions.py · session 管理路由 (wish-413999da · phase 1)
==================================================================

6 路由 · session jsonl 的 CRUD + 元数据:

  GET    /sessions                       · 列 session 带 label/pinned/archived (卷三十四补丁)
  POST   /sessions/{sid}/meta            · 改 label/pinned/archived
  DELETE /sessions/{sid}                 · 删 jsonl + 清 meta
  GET    /sessions/{sid}                 · 返回 raw jsonl
  GET    /sessions/{sid}/messages        · WebUI 友好的结构化 turn 列表
  GET    /sessions/{sid}/active_turn     · wish-3fef4bc7 · 浏览器 F5 后查 active turn

注: 用 daemon_api 模块级 _TURNS_LOCK / _TURN_TO_SID 共享状态
    (daemon_api 已 load 完才 include_router · 此时 module attr 可访问)
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import PlainTextResponse

from api_routes._deps import check_auth
from daemon_runtime import RUNTIME
from daemon_session import (
    delete_session,
    get_session_meta,
    list_sessions_with_meta,
    load_session_for_ui,
    session_path,
    set_session_meta,
)


router = APIRouter()


@router.get("/sessions")
async def sessions(
    authorization: Optional[str] = Header(None),
    limit: int = 50,
    api_only: bool = False,
    include_archived: bool = False,
    archived_only: bool = False,
):
    """列 session · 带 label / pinned / archived 元数据 (卷三十四补丁)

    Query:
      api_only=true       · 只返 api- 前缀 (WebUI 默认 · 避免污染终端 session)
      include_archived    · 是否包含已归档 · 默认不包含
      archived_only       · 只列已归档 (做"已归档"切换视图用)

    排序：pinned 在前 (pinned_at desc) → unpinned 按 mtime desc。
    """
    check_auth(authorization)

    items = list_sessions_with_meta()
    out = []
    archived_count = 0
    for row in items:
        sid = row["session_id"]
        is_api = sid.startswith("api-")
        if api_only and not is_api:
            continue
        is_archived = bool(row.get("archived_at"))
        if is_archived:
            archived_count += 1
        if archived_only:
            if not is_archived:
                continue
        else:
            if is_archived and not include_archived:
                continue
        out.append({
            "session_id": sid,
            "mtime": row["mtime"].isoformat(timespec="seconds"),
            "turns": row["turns"],
            "is_api": is_api,
            "label": row.get("label"),
            "pinned_at": row.get("pinned_at"),
            "archived_at": row.get("archived_at"),
        })
        if len(out) >= limit:
            break
    return {
        "sessions": out,
        "total": len(items),
        "returned": len(out),
        "archived_count": archived_count,
    }


@router.get("/sessions/{sid}/meta")
async def get_session_meta_endpoint(
    sid: str,
    authorization: Optional[str] = Header(None),
):
    """取单个 session 的 metadata (spawnTask 配套 · 前端切 session 时即时拉标题)

    返回: { session_id, meta: { label, pinned_at, archived_at } } · label 可能为 null
    """
    check_auth(authorization)

    if not session_path(sid).exists():
        raise HTTPException(404, f"session not found: {sid}")

    meta = get_session_meta(sid)
    return {
        "session_id": sid,
        "meta": {
            "label": meta.get("label"),
            "pinned_at": meta.get("pinned_at"),
            "archived_at": meta.get("archived_at"),
        },
    }


@router.post("/sessions/{sid}/meta")
async def update_session_meta_endpoint(
    sid: str,
    body: dict,
    authorization: Optional[str] = Header(None),
):
    """更新 session 的 label / pinned / archived (卷三十四补丁)

    Body (任意子集):
      label: str|null  · 重命名 · null 或空字符串 = 清掉别名
      pinned: bool · 置顶 / 取消置顶
      archived: bool · 归档 / 取消归档

    返回更新后的完整 meta dict。
    """
    check_auth(authorization)

    if not session_path(sid).exists():
        raise HTTPException(404, f"session not found: {sid}")

    kwargs = {}
    if "label" in body:
        v = body.get("label")
        kwargs["label"] = v if v is None else str(v)
    if "pinned" in body:
        kwargs["pinned"] = bool(body.get("pinned"))
    if "archived" in body:
        kwargs["archived"] = bool(body.get("archived"))
    if not kwargs:
        raise HTTPException(400, "body 至少要包含 label / pinned / archived 之一")

    meta = set_session_meta(sid, **kwargs)
    return {"session_id": sid, "meta": meta}


@router.delete("/sessions/{sid}")
async def remove_session(
    sid: str,
    authorization: Optional[str] = Header(None),
):
    """删一个 session · 真删 jsonl + 清 meta (卷三十四补丁)

    如果 RUNTIME 当前正在用这个 session · 顺便把 RUNTIME.session_id 清掉·
    防止下一笔 append_turn 写到一个已经删了的文件路径。
    """
    check_auth(authorization)

    if not session_path(sid).exists():
        raise HTTPException(404, f"session not found: {sid}")
    delete_session(sid)

    try:
        if RUNTIME and getattr(RUNTIME, "session_id", None) == sid:
            RUNTIME.session_id = ""
    except Exception:
        pass

    return {"ok": True, "session_id": sid}


@router.get("/sessions/{sid}")
async def session_detail(sid: str, authorization: Optional[str] = Header(None)):
    """返回 raw jsonl（不推荐 WebUI 用——用 /sessions/{sid}/messages）。"""
    check_auth(authorization)
    path = session_path(sid)
    if not path.exists():
        raise HTTPException(404, f"session not found: {sid}")
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(500, f"failed to read session: {e}")
    return PlainTextResponse(content, media_type="application/x-ndjson")


@router.get("/sessions/{sid}/messages")
async def session_messages(sid: str, authorization: Optional[str] = Header(None)):
    """WebUI 友好的结构化 turn 列表 —— 加载历史对话用。"""
    check_auth(authorization)
    try:
        turns = load_session_for_ui(sid)
    except FileNotFoundError:
        raise HTTPException(404, f"session not found: {sid}")
    except Exception as e:
        raise HTTPException(500, f"failed to load session: {e}")
    return {
        "session_id": sid,
        "turns": turns,
        "count": len(turns),
    }


@router.get("/sessions/{sid}/active_turn")
async def session_active_turn(sid: str, authorization: Optional[str] = Header(None)):
    """wish-3fef4bc7 follow-up · 浏览器 F5 后查这个 session 有没有 active turn

    浏览器刷新后 SSE connection 断了 · 但 daemon worker 仍在跑 (sync thread · 不依赖 SSE)。
    BRO F5 后 frontend 调这个 endpoint · 有 active turn 就启动 3s polling auto-refresh
    历史 · 让 BRO 不用手动 F5 第二次就能看到 daemon 后台跑出来的内容。
    """
    check_auth(authorization)
    # 从 daemon_api 模块取共享 state (build_app 时 daemon_api 已 load)
    from daemon_api import _TURNS_LOCK, _TURN_TO_SID

    with _TURNS_LOCK:
        for tid, t_sid in _TURN_TO_SID.items():
            if t_sid == sid:
                return {"session_id": sid, "turn_id": tid}
    return {"session_id": sid, "turn_id": None}

    return {"session_id": sid, "turn_id": None}


@router.get("/sessions/{sid}/background_turn_status")
async def session_bg_turn_status(sid: str, authorization: Optional[str] = Header(None)):
    """wish-83fe7c7b 补丁 · 重启后 WebUI 等 background turn 完成

    waitForDaemonAfterRestartTool 在 daemon alive 后轮询此端点 ·
    等到 status 为 completed/failed/none 后再加载 session 历史，
    避免 background turn 还在跑时就加载到旧快照。
    """
    check_auth(authorization)
    from workers.resume_runner import get_background_turn_status
    status = get_background_turn_status(sid)
    return {"session_id": sid, "status": status}
