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

from pathlib import Path, PurePosixPath
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

# 卷八十一续 · artifacts 端点 LRU 缓存 · sid+mtime 签名 → 产物列表
# 会话上下文大时全量重扫 jsonl 很慢 · 文件没变就秒回缓存
_ARTIFACTS_CACHE: dict[str, list] = {}


@router.get("/sessions")
async def sessions(
    authorization: Optional[str] = Header(None),
    limit: int = 50,
    offset: int = 0,
    api_only: bool = False,
    include_archived: bool = False,
    archived_only: bool = False,
):
    """列 session · 带 label / pinned / archived 元数据 (卷三十四补丁)

    Query:
      api_only=true       · 只返 api- 前缀 (WebUI 默认 · 避免污染终端 session)
      include_archived    · 是否包含已归档 · 默认不包含
      archived_only       · 只列已归档 (做"已归档"切换视图用)
      offset              · 分页偏移 · 配合 limit 做"加载更多" (卷八十一 · BRO: 老会话被 50 条挤掉)

    排序：pinned 在前 (pinned_at desc) → unpinned 按 mtime desc。
    """
    check_auth(authorization)

    # wish-xxx · 全局活跃 turn 集合 (daemon 正在为哪些 session 跑 LLM)
    # 真相源: daemon_api._TURN_TO_SID (turn_id → session_id) · 前端历史列表据此显示运行状态
    try:
        from daemon_api import _TURNS_LOCK, _TURN_TO_SID
        with _TURNS_LOCK:
            _active_sids = set(_TURN_TO_SID.values())
    except Exception:
        _active_sids = set()

    items = list_sessions_with_meta()
    out = []
    archived_count = 0
    skipped = 0
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
    # 分页: 先跳过 offset 条已过滤结果
        if skipped < offset:
            skipped += 1
            continue
        out.append({
            "session_id": sid,
            "mtime": row["mtime"].isoformat(timespec="seconds"),
            "turns": row["turns"],
            "is_api": is_api,
            "label": row.get("label"),
            "pinned_at": row.get("pinned_at"),
            "archived_at": row.get("archived_at"),
            "last_model_cfg": row.get("last_model_cfg"),
            "active": sid in _active_sids,   # wish-xxx · 会话是否正在被 daemon 跑 (历史列表运行状态点)
        })
        if len(out) >= limit:
            break
    return {
        "sessions": out,
        "total": len(items),
        "returned": len(out),
        "offset": offset,
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
    label = meta.get("label")
    # 老会话补名 · 内核加即时命名之前建的 session 没 label · 前端标签栏就一直是裸 api-xxxx。
    # 这里按需从第一句用户话补一个并落盘(只补一次)· 让标签栏/历史列表就地改名·治本。
    if not label:
        try:
            from daemon_session import derive_label_from_first_turn
            derived = derive_label_from_first_turn(sid)
            if derived:
                set_session_meta(sid, label=derived)
                label = derived
        except Exception:
            pass
    return {
        "session_id": sid,
        "meta": {
            "label": label,
            "pinned_at": meta.get("pinned_at"),
            "archived_at": meta.get("archived_at"),
            "last_model_cfg": meta.get("last_model_cfg"),
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
    if "last_model_cfg" in body:
        v = body.get("last_model_cfg")
        kwargs["last_model_cfg"] = v if v is None else str(v)
    if not kwargs:
        raise HTTPException(400, "body 至少要包含 label / pinned / archived / last_model_cfg 之一")

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


@router.get("/sessions/{sid}/artifacts")
async def session_artifacts(sid: str, authorization: Optional[str] = Header(None)):
    """卷八十一 · 本会话真实产物列表 (压缩/折叠也不丢)

    收集逻辑: 扫 session 主 jsonl + sessions/archive/ 下该 sid 的所有归档文件
    (compact/prune 折叠原件), 从 content + tool_calls.arguments 里抽产物路径,
    过滤示例占位符 (X.md / xxx.docx / x.png 这类), 只返回磁盘上真实存在的文件。

    前端「本会话产物」视图数据源 · 不依赖 DOM (懒加载/压缩都不影响)。

    性能 (卷八十一续 · BRO 反馈打开产物每次卡): 会话上下文大时主 jsonl + 归档
    几万行 · 每次全量 json.loads + 磁盘 stat 很慢。加模块级缓存:
      - 缓存键 = sid + 所有相关文件 (主 + archive) 的 (size, mtime)
      - 内容没变 (无新消息/新压缩) → 直接返回缓存 · 秒开
      - 有变化 → 重扫 + 更新缓存
    """
    check_auth(authorization)

    import json
    import re

    sid_file = session_path(sid)
    if not sid_file.exists():
        raise HTTPException(404, f"session not found: {sid}")

    # ---- 缓存键: sid + 所有相关文件的 (size, mtime) ----
    def _cache_key() -> str:
        parts = [sid]
        for f in sorted(sid_file.parent.glob("archive/*" + sid + "*.jsonl")) + [sid_file]:
            try:
                st = f.stat()
                parts.append(f"{f.name}:{st.st_size}:{int(st.st_mtime)}")
            except Exception:
                pass
        return "|".join(parts)

    ck = _cache_key()
    _ARTIFACTS_CACHE.get(sid)  # touch (简单 LRU: 命中就更新顺序)
    if ck in _ARTIFACTS_CACHE:
        hit = _ARTIFACTS_CACHE.pop(ck)
        _ARTIFACTS_CACHE[ck] = hit  # 移到末尾 (最近使用)
        return {"session_id": sid, "artifacts": hit, "count": len(hit), "cached": True}

    # 所有要扫的行: 主文件 + 归档 (compact/prune)
    lines: list[str] = []
    for f in sorted(sid_file.parent.glob("archive/*" + sid + "*.jsonl")):
        try:
            lines.extend(f.read_text(encoding="utf-8", errors="replace").splitlines())
        except Exception:
            pass
    try:
        lines.extend(sid_file.read_text(encoding="utf-8", errors="replace").splitlines())
    except Exception:
        pass
    # 产物路径正则 (白名单类型)
    # 防路径穿越: 第二分支整段负向前瞻 (?!.*\.\.) 拒绝含 .. 的路径 · 字符类去掉 % (避免 %2e%2e 编码穿越)
    RE_DOCPATH = re.compile(
        r"(?:data/(?:docs|content|design|dev|presentations)/[\w\u4e00-\u9fa5\-（）()·\.]+\.(?:docx?|md|pdf|xlsx?|pptx?|html?|png|jpe?g|gif|webp|mp3|wav|mp4|webm|zip))"
        r"|(?:(?!.*\.\.)(?:/reports/|/workshop/(?:outputs|preview|file)/|/presentations/)[\w\u4e00-\u9fa5\-（）()·\./]+\.(?:docx?|md|pdf|xlsx?|pptx?|html?|png|jpe?g|gif|webp|mp3|wav|mp4|webm|zip))",
        re.IGNORECASE,
    )
    # 占位符/示例过滤: X.md / xxx.docx / x.png / xxx.md 等
    RE_PLACEHOLDER = re.compile(r"(^|/)(x|xxx|test|tmp|sample|example|placeholder|demo)(\.|/|$)", re.IGNORECASE)
    _FAKE = {"x", "xxx", "test", "tmp", "sample", "example", "placeholder", "demo"}

    def _is_fake(p: str) -> bool:
        base = PurePosixPath(p.split("?")[0]).name  # 文件名
        stem = base.rsplit(".", 1)[0].lower()
        if stem in _FAKE or stem.endswith((".x", ".xxx")):
            return True
        return bool(RE_PLACEHOLDER.search(p))

    ROOT = Path(__file__).resolve().parent.parent

    def _exists_on_disk(p: str) -> bool:
        # 归一化到绝对路径验证真实存在
        cands = []
        if p.startswith("data/"):
            cands.append(ROOT / p)
        elif p.startswith("/reports/"):
            cands.append(ROOT / "data" / "reports" / p[len("/reports/"):])
        elif p.startswith("/workshop/preview/"):
            rel = p[len("/workshop/preview/"):]
            if "/" in rel:
                d, f = rel.split("/", 1)
                cands.append(ROOT / "data" / d / f)
        elif p.startswith("/workshop/file/"):
            rel = p[len("/workshop/file/"):]
            if "/" in rel:
                d, f = rel.split("/", 1)
                cands.append(ROOT / "data" / d / f)
        elif p.startswith("/workshop/outputs/"):
            cands.append(ROOT / "data" / "workshop" / "outputs" / p[len("/workshop/outputs/"):])
        for c in cands:
            try:
                if c.resolve().is_file():
                    return True
            except Exception:
                pass
        return False

    def _norm_url(p: str) -> str:
        if p.startswith("data/docs/"): return "/workshop/preview/docs/" + p[len("data/docs/"):]
        if p.startswith("data/content/"): return "/workshop/preview/content/" + p[len("data/content/"):]
        if p.startswith("data/design/"): return "/workshop/preview/design/" + p[len("data/design/"):]
        if p.startswith("data/dev/"): return "/workshop/preview/dev/" + p[len("data/dev/"):]
        if p.startswith("data/workshop/outputs/"): return "/workshop/outputs/" + p[len("data/workshop/outputs/"):]
        return p

    seen: set[str] = set()
    artifacts: list[dict] = []
    # 粗筛关键词 (卷八十一续二 · BRO 反馈产物首次 6s 慢 · 根因是 RE_DOCPATH 在超长 HTML/代码上
    # 灾难性回溯 · 每段 10K+ 字符的文本跑正则要 0.06-0.28s。先用零回溯的 in 判断跳过
    # 不含任何产物路径关键词的文本 · 命中才跑正则 · 6s → 秒级)
    _DOC_HINTS = ("/workshop/", "/reports/", "/presentations/",
                  "data/docs/", "data/content/", "data/design/", "data/dev/", "data/presentations/")
    for line in lines:
        try:
            msg = json.loads(line)
        except Exception:
            continue
        texts: list[str] = []
        c = msg.get("content")
        if isinstance(c, str):
            texts.append(c)
        elif isinstance(c, list):
            for it in c:
                if isinstance(it, dict) and it.get("text"):
                    texts.append(it["text"])
        tc = msg.get("tool_calls")
        if tc:
            for x in tc:
                a = None
                if isinstance(x, dict):
                    if "arguments" in x:
                        a = x.get("arguments")
                    elif isinstance(x.get("function"), dict):
                        a = x["function"].get("arguments")
                if isinstance(a, str):
                    texts.append(a)
                elif a:
                    try:
                        texts.append(json.dumps(a, ensure_ascii=False))
                    except Exception:
                        pass
        for txt in texts:
            if not txt:
                continue
            if not any(h in txt for h in _DOC_HINTS):
                continue  # 粗筛: 无产物路径关键词 → 跳过正则 (防回溯)
            for m in RE_DOCPATH.finditer(txt):
                raw = m.group(0)
                if _is_fake(raw):
                    continue
                url = _norm_url(raw)
                if url in seen:
                    continue
                seen.add(url)
                if not _exists_on_disk(raw):
                    continue
                ext = PurePosixPath(url.split("?")[0]).suffix.lower().lstrip(".")
                name = PurePosixPath(url.split("?")[0]).name
                artifacts.append({"name": name, "url": url, "ext": ext})

    # 更新缓存 (LRU 上限 64 会话 · 超了弹最老的)
    if len(_ARTIFACTS_CACHE) >= 64:
        _ARTIFACTS_CACHE.pop(next(iter(_ARTIFACTS_CACHE)))
    _ARTIFACTS_CACHE[ck] = artifacts
    return {"session_id": sid, "artifacts": artifacts, "count": len(artifacts), "cached": False}


@router.get("/sessions/{sid}/active_turn")
async def session_active_turn(sid: str, authorization: Optional[str] = Header(None)):
    """wish-3fef4bc7 follow-up · 浏览器 F5 后查这个 session 有没有 active turn

    浏览器刷新后 SSE connection 断了 · 但 daemon worker 仍在跑 (sync thread · 不依赖 SSE)。
    BRO F5 后 frontend 调这个 endpoint · 有 active turn 就启动 3s polling auto-refresh
    历史 · 让 BRO 不用手动 F5 第二次就能看到 daemon 后台跑出来的内容。
    """
    check_auth(authorization)
    # 从 daemon_api 模块取共享 state (build_app 时 daemon_api 已 load)
    from daemon_api import _TURNS_LOCK, _TURN_TO_SID, get_turn_progress

    found = None
    with _TURNS_LOCK:
        for tid, t_sid in _TURN_TO_SID.items():
            if t_sid == sid:
                found = tid
                break
    if not found:
        return {"session_id": sid, "turn_id": None}
    # ② 自主巡航进度 · 带上最新一步 (get_turn_progress 自己拿锁 · 必须在 with 外调 · 防重入死锁)
    return {"session_id": sid, "turn_id": found, "progress": get_turn_progress(found)}


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
