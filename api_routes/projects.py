"""
api_routes/projects.py · 外部项目管理路由
=========================================

给左导航「我的项目」供数（wish-acc37841）：

  GET    /api/projects            列表（含每个项目挂了多少对话 + 目录还在不在）
  POST   /api/projects            挂一个目录当项目
  GET    /api/projects/{pid}      单个
  PATCH  /api/projects/{pid}      改名字 / 默认档位 / 交接条 / 归档
  DELETE /api/projects/{pid}      取消挂载

红线（BRO 2026-09-20）：
  取消挂载 = **只取消这条记录** · 磁盘上的目录和文件一个都不动。

为什么列表要带 path_exists：
  目录可能被 BRO 移走/改名 —— 那项目卡就成了死链。前端据此优雅降级
  （显示「这个目录找不到了」），而不是点进去报一堆错。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException, Request

from api_routes._deps import check_auth

router = APIRouter()

_PATCH_FIELDS = ("name", "profile", "handoff", "archived", "touch", "last_used_at")


def _pj():
    from workers import projects as pj
    return pj


def _chat_counts() -> dict:
    """每个项目挂了几条对话 —— 从会话 meta 的 project_id 数

    读不到就当 0 · 绝不因为统计失败打断列表。
    """
    out: dict = {}
    try:
        from daemon_session import list_sessions_with_meta
        for s in list_sessions_with_meta():
            pid = str(s.get("project_id") or "").strip()
            if pid:
                out[pid] = out.get(pid, 0) + 1
    except Exception:
        pass
    return out


@router.get("/api/projects")
async def projects_list(include_archived: bool = True, authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    pj = _pj()
    cnt = _chat_counts()
    items = pj.list_projects(include_archived=include_archived)
    for e in items:
        e["chat_count"] = cnt.get(e.get("id"), 0)
        try:
            e["path_exists"] = Path(e.get("path") or "").is_dir()
        except Exception:
            e["path_exists"] = False
    return {"ok": True, "items": items}


@router.post("/api/projects")
async def projects_add(body: dict = Body(...), authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    r = _pj().add_project(
        (body or {}).get("path") or "",
        name=(body or {}).get("name") or "",
        profile=(body or {}).get("profile") or "标准",
    )
    if not r.get("ok"):
        raise HTTPException(status_code=400, detail=r.get("error") or "挂载失败")
    return r


# 2026-09-30 · 选择器实现已抽到 api_routes/picker.py（知识库要做「选文件夹/选文件」，
#   BRO 明确「不要代码分叉，能复用直接复用」）—— 这里只留转发，不再自己维护一份脚本。
from api_routes.picker import _PICK_SCRIPT  # noqa: F401  (兼容老引用)


@router.post("/api/projects/pick-folder")
async def projects_pick_folder(
    request: Request,
    initial: str = "",
    authorization: Optional[str] = Header(None),
):
    """拉系统自己的目录选择器（Windows 资源管理器那个）

    ⚠ 只在**本机**访问时可用 —— 对话框是开在 daemon 那台机器的桌面上的，
      远程（手机 / 隧道）请求根本看不见它，会挂在那里干等到超时。
      所以远程直接返回 remote=True，让前端退回手输。

    ⚠ 子进程跑（不单因为阻塞：tkinter 必须占主线程）· 用户取消 → 空串 → cancelled。
    """
    check_auth(authorization)
    # 转发到 api_routes/picker.py 的公共实现（原来这里自己抄了一份脚本 · 2026-09-30 收敛）
    from api_routes.picker import pick_folder as _pick
    return await _pick(request, initial=initial, authorization=authorization)


@router.post("/api/projects/{pid}/open-folder")
async def projects_open_folder(pid: str, request: Request, authorization: Optional[str] = Header(None)):
    """在（daemon 这台机器的）文件管理器里打开项目目录

    ⚠ 同 pick-folder：远程接入时开的是**这台机器**的资源管理器，请求方看不见 ——
      直接拒绝，别让人以为点了没反应。
    """
    check_auth(authorization)
    from api_routes._deps import _client_is_local_machine
    if not _client_is_local_machine(request):
        return {"ok": False, "remote": True, "error": "资源管理器开在 daemon 那台机器上 · 远程看不见"}
    e = _pj().get_project(pid)
    if not e:
        raise HTTPException(status_code=404, detail=f"没有这个项目：{pid}")
    p = Path(e.get("path") or "")
    if not p.is_dir():
        return {"ok": False, "error": "这个目录已经不在了"}
    try:
        os.startfile(str(p))     # noqa: S606 · Windows 专属 · 路径来自登记表（挂载时已验过是目录）
    except Exception as ex:
        return {"ok": False, "error": f"打不开：{ex}"}
    return {"ok": True}


@router.get("/api/projects/{pid}")
async def projects_get(pid: str, authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    e = _pj().get_project(pid)
    if not e:
        raise HTTPException(status_code=404, detail=f"没有这个项目：{pid}")
    try:
        e["path_exists"] = Path(e.get("path") or "").is_dir()
    except Exception:
        e["path_exists"] = False
    return {"ok": True, "project": e}


@router.get("/api/projects/{pid}/detail")
async def projects_detail(pid: str, authorization: Optional[str] = Header(None)):
    """项目详情一次拉全 —— 状态条 / 版本 / 进度 / git / 对话

    BRO 2026-09-21：详情不能只有一个路径 + 档位名，要一眼看到「做到哪了」。
    版本优先级：git tag（真发生过的）> OPUS.md 手写；
    进度：只认 OPUS.md 里程碑（勾必须带证据 —— 方案见 wish-178a8517）。
    目录不在时不跑 git（防一个死目录把请求拖到超时）。
    """
    check_auth(authorization)
    pj = _pj()
    e = pj.get_project(pid)
    if not e:
        raise HTTPException(status_code=404, detail=f"没有这个项目：{pid}")
    path = e.get("path") or ""
    try:
        e["path_exists"] = Path(path).is_dir()
    except Exception:
        e["path_exists"] = False
    if e["path_exists"]:
        e["opus_md"] = pj.read_opus_md(path)
        e["git"] = pj.git_snapshot(path)
    else:
        e["opus_md"] = {"exists": False, "version": "", "milestones": [], "err": ""}
        e["git"] = {"is_repo": False, "branch": "", "dirty": 0, "tag": "", "ahead": 0, "behind": 0}
    e["version"] = (e["git"].get("tag") or "").lstrip("v") \
        or (e["opus_md"].get("version") or "").lstrip("v") or ""
    e["chat_count"] = _chat_counts().get(pid, 0)
    return {"ok": True, "project": e}


@router.patch("/api/projects/{pid}")
async def projects_patch(pid: str, body: dict = Body(...), authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    fields = {k: v for k, v in (body or {}).items() if k in _PATCH_FIELDS}
    if not fields:
        raise HTTPException(status_code=400, detail=f"至少要给一个字段：{list(_PATCH_FIELDS)}")
    r = _pj().update_project(pid, **fields)
    if not r.get("ok"):
        raise HTTPException(status_code=404, detail=r.get("error") or "没有这个项目")
    return r


@router.get("/api/projects/{pid}/sessions")
async def projects_sessions(pid: str, authorization: Optional[str] = Header(None)):
    """这个项目下面挂着哪几场对话 —— 项目视图展开某一行时按需拉

    BRO 2026-09-20：「确实挂载在这个项目目录下面的对话，是不是也应该在这呈现？」
    —— 该。展开那一行就该看到它们，点一下切过去。
    """
    check_auth(authorization)
    if not _pj().get_project(pid):
        raise HTTPException(status_code=404, detail=f"没有这个项目：{pid}")
    rows = []
    try:
        from daemon_session import list_sessions_with_meta
        for s in list_sessions_with_meta():
            if str(s.get("project_id") or "").strip() == pid:
                rows.append(s)
        rows.sort(key=lambda s: s.get("mtime") or 0, reverse=True)
    except Exception:
        rows = []
    return {
        "ok": True,
        "sessions": [{
            "session_id": r.get("session_id"),
            "label": r.get("label") or "",
            "mtime": r["mtime"].isoformat(timespec="seconds") if r.get("mtime") else "",
            "turns": r.get("turns") or 0,
            "archived": bool(r.get("archived_at")),
        } for r in rows[:50]],
    }


@router.delete("/api/projects/{pid}")
async def projects_remove(pid: str, authorization: Optional[str] = Header(None)):
    """移出项目 —— ⚠ 只从列表里划掉这一行，磁盘上一个字节都不动

    顺手把挂在它下面的会话的项目标记摘掉：不摘的话那些会话会一直顶着一个
    已经不存在的项目名，点药丸只能弹「读不到这个项目」。对话本身不动。
    """
    check_auth(authorization)
    freed = 0
    try:
        from daemon_session import list_sessions_with_meta, set_session_meta
        for s in list_sessions_with_meta():
            if str(s.get("project_id") or "").strip() == pid:
                set_session_meta(s["session_id"], project_id="")
                freed += 1
    except Exception:
        pass
    r = _pj().remove_project(pid)
    r["unbound_sessions"] = freed
    return r


@router.post("/api/projects/{pid}/handoff")
async def projects_handoff(pid: str, authorization: Optional[str] = Header(None)):
    """给这个项目攒一条交接条（上次停在哪 / 下一步干嘛）

    纯规则 · 不上 LLM（省一次调用，也不会编）：
      ① 项目下最近一场会话的**任务账本**里有未完成的步 → 用它们
      ② 没有账本 / 都干完了 → 退回「最近动过的那场 + 什么时候」

    为什么存进项目资产：交接条是项目级的记忆，不是会话级的 ——
    下一场对话进来时直接读它，不用把上一场的几干轮历史翻一遍。
    """
    check_auth(authorization)
    pj = _pj()
    e = pj.get_project(pid)
    if not e:
        raise HTTPException(status_code=404, detail=f"没有这个项目：{pid}")

    rows = []
    try:
        from daemon_session import list_sessions_with_meta
        rows = [s for s in list_sessions_with_meta()
                if str(s.get("project_id") or "").strip() == pid]
        rows.sort(key=lambda s: s.get("mtime") or 0, reverse=True)
    except Exception:
        rows = []

    pending = []
    used_session = ""
    try:
        from workers import task_ledger as tl
        for r in rows[:8]:
            sid = r.get("session_id") or ""
            slug = tl.active_slug(sid) if sid else ""
            led = tl.get_ledger(slug) if slug else None
            if not led or not led.get("steps"):
                continue
            todo = [s for s in led["steps"]
                    if (s.get("status") or "") not in ("done", "skip")]
            if todo:
                pending = todo
                used_session = sid
                break
    except Exception:
        pass

    parts = []
    if rows:
        top = rows[0]
        when = ""
        try:
            when = top["mtime"].strftime("%m-%d %H:%M")
        except Exception:
            when = ""
        parts.append("上次动的是「%s」%s" % (top.get("label") or top.get("session_id") or "",
                                        ("（" + when + "）") if when else ""))
    if pending:
        items = []
        for s in pending[:5]:
            t = s.get("text") or s.get("title") or s.get("label") or ""
            t = str(t).strip()
            if t:
                items.append(t[:40])
        if items:
            parts.append("没干完的：" + "、".join(items))
    elif rows:
        parts.append("上一场没留未完成的步（可能已收尾）")

    handoff = " · ".join(parts)
    pj.update_project(pid, handoff=handoff)
    return {
        "ok": True,
        "handoff": handoff,
        "sessions": len(rows),
        "pending_steps": len(pending),
        "from_session": used_session,
    }
