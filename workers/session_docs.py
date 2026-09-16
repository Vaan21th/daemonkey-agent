"""本话题正在做的稿 · 挂进 session，改稿 / 续做 / 附件都认同一份。"""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_OFFICE = {".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls", ".xlsm"}
_PRODUCT = {
    ".pptx": "presentations", ".ppt": "presentations",
    ".docx": "reports", ".doc": "reports",
    ".xlsx": "spreadsheets", ".xls": "spreadsheets", ".xlsm": "spreadsheets",
}
_PATH_RE = re.compile(
    r"data/(?:presentations|reports|spreadsheets|runtime/attachments)/"
    r"[^\s\"'`\]=]+?\.(?:pptx?|docx?|xlsx?|xlsm)\b",
    re.I,
)
_PATH_EQ = re.compile(
    r"path=(\s*)(data/(?:presentations|reports|spreadsheets)/[^\s]+?\.(?:pptx?|docx?|xlsx?|xlsm))\b",
    re.I,
)
_KEEP = 5
_DIGEST = 2500


def is_office_name(name: str) -> bool:
    return Path(name or "").suffix.lower() in _OFFICE


def is_office_mime(mime: str) -> bool:
    m = (mime or "").lower()
    return any(k in m for k in (
        "presentationml", "wordprocessingml", "spreadsheetml",
        "ms-powerpoint", "msword", "ms-excel", "officedocument",
    ))


def rel_of(path: Path, *, root: Path | None = None) -> str | None:
    base = (root or _ROOT).resolve()
    try:
        return path.resolve().relative_to(base).as_posix()
    except ValueError:
        return None


def _canon_rel(rel: str, *, root: Path | None = None) -> str:
    rel = (rel or "").strip().replace("\\", "/")
    if rel.startswith("file://"):
        rel = rel[7:]
    base = (root or _ROOT).resolve()
    if len(rel) >= 3 and rel[1] == ":":
        try:
            return Path(rel).resolve().relative_to(base).as_posix()
        except ValueError:
            return rel
    rel = rel.lstrip("/")
    for a, b in (
        ("presentations/", "data/presentations/"),
        ("reports/", "data/reports/"),
        ("spreadsheets/", "data/spreadsheets/"),
        ("attachments/", "data/runtime/attachments/"),
    ):
        if rel.startswith(a):
            return b + rel[len(a):]
    return rel


def resolve_rel(rel: str, *, root: Path | None = None) -> Path | None:
    rel = _canon_rel(rel, root=root)
    if not rel or ".." in rel or rel.startswith("/") or "\x00" in rel:
        return None
    if not is_office_name(rel):
        return None
    base = (root or _ROOT).resolve()
    path = (base / rel).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        return None
    allowed = (
        base / "data" / "presentations",
        base / "data" / "reports",
        base / "data" / "spreadsheets",
        base / "data" / "runtime" / "attachments",
    )
    if not any(path == d or d in path.parents for d in allowed):
        return None
    if not path.is_file():
        return None
    return path


def extract_paths(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for m in _PATH_EQ.finditer(text or ""):
        p = m.group(2).replace("\\", "/")
        if p not in seen:
            seen.add(p)
            found.append(p)
    for m in _PATH_RE.finditer(text or ""):
        p = m.group(0).replace("\\", "/")
        if p not in seen:
            seen.add(p)
            found.append(p)
    return found


def home_of(rel: str) -> str | None:
    """这份稿的【产出者】场 —— 唯一权威，别的场不参与竞争。

    wish-1518b97f.2 · 语义钉死: 旧实现取「最早挂上它的场」· 把「谁碰过」
    当成「谁产出」→ 一份稿被几场碰过就有几个妈。现在只认 origin 字段。
    兼容老记录 (无 origin): 退回最早 bound_at · 且只当兜底不当依据。
    """
    rel = _canon_rel(rel)
    if not rel:
        return None
    from daemon_session import _load_meta_index
    best: tuple[str, str] | None = None
    for sid, meta in (_load_meta_index() or {}).items():
        if not isinstance(meta, dict):
            continue
        for d in meta.get("working_docs") or []:
            if not isinstance(d, dict):
                continue
            if _canon_rel(d.get("path") or "") != rel:
                continue
            org = str(d.get("origin") or "").strip()
            if org:
                return org              # 有 origin → 直接信它 · 不比较
            ts = str(d.get("bound_at") or meta.get("updated_at") or "9999")
            if best is None or ts < best[0]:
                best = (ts, sid)
    return best[1] if best else None


def bind(sid: str, rel: str, *, root: Path | None = None, claim: bool = False,
         via: str = "manual") -> dict | None:
    path = resolve_rel(rel, root=root)
    if not path or not sid:
        return None
    rel = rel_of(path, root=root) or rel.replace("\\", "/")
    from daemon_session import get_session_meta, set_session_meta
    cur = [d for d in (get_session_meta(sid).get("working_docs") or []) if isinstance(d, dict)]
    prev = next((d for d in cur if _canon_rel(d.get("path") or "") == rel), None)
    owner = home_of(rel)
    # wish-1518b97f.2 · 产物归属铁律 (BRO 2026-09-14 拍板):
    #   一份稿只属于产出/带入它的那一场 · 别的场【压根不记录】这条绑定
    #   (不是显示层过滤 · 是数据层不写)。
    # 立新家的两条合法路 (都要 claim=True · 由调用方声明):
    #   ① via='generated' 本场真调生成工具产出
    #   ② via='uploaded'  用户主动上传 / 手动挂进本场
    # 除此之外 (via='mentioned' 等) 一律不写。
    if not claim and not prev:
        return {"path": rel, "name": path.name, "home_sid": owner or ""}
    if owner and owner != sid and not prev:
        # 已有产出者 (且不是本场) → 拒绝抢 · 只回只读描述
        return {"path": rel, "name": path.name, "home_sid": owner, "readonly": True}
    rec = {
        "path": rel,
        "name": path.name,
        "home_sid": sid,
        "origin": sid,
        "via": str((prev or {}).get("via") or via or "manual"),
        "bound_at": (prev or {}).get("bound_at") or datetime.now().isoformat(timespec="seconds"),
    }
    docs = [d for d in cur if _canon_rel(d.get("path") or "") != rel]
    docs.insert(0, rec)
    set_session_meta(sid, working_docs=docs[:_KEEP])
    return rec


def list_bound(sid: str) -> list[dict]:
    from daemon_session import get_session_meta
    docs = get_session_meta(sid).get("working_docs") or []
    return [d for d in docs if isinstance(d, dict) and d.get("path")]


def unbind(sid: str, rel: str, *, root: Path | None = None) -> bool:
    """把一份办公稿从本场摘掉 (wish-1518b97f · 挂错了要能手动纠正)。

    只摘本场的记录 · 不动文件 · 也不动别的场。摘掉后 home_of 可能落到另一场
    (别场也挂着的话) —— 那正常 · 说明它本来就是别场的稿。
    """
    if not sid:
        return False
    rel = _canon_rel(rel, root=root)
    if not rel:
        return False
    from daemon_session import get_session_meta, set_session_meta
    cur = [d for d in (get_session_meta(sid).get("working_docs") or []) if isinstance(d, dict)]
    keep = [d for d in cur if _canon_rel(d.get("path") or "") != rel]
    if len(keep) == len(cur):
        return False                       # 本场本来就没挂它
    set_session_meta(sid, working_docs=keep)
    return True


def digest(rel: str, *, root: Path | None = None, limit: int = _DIGEST) -> str:
    path = resolve_rel(rel, root=root)
    if not path:
        return ""
    md = path.with_suffix(".md")
    text = ""
    if md.is_file():
        try:
            raw = md.read_text(encoding="utf-8")
            if raw.startswith("---\n"):
                end = raw.find("\n---\n", 4)
                raw = raw[end + 5:] if end > 0 else raw
            text = raw.strip()
        except OSError:
            text = ""
    if not text:
        try:
            from agent_tools.inspect_office import _fallback_text
            text = (_fallback_text(path) or "").strip()
        except Exception:
            text = ""
    if len(text) > limit:
        text = text[:limit].rstrip() + "\n…"
    return text


def system_note(sid: str, *, root: Path | None = None) -> str:
    docs = [d for d in list_bound(sid) if resolve_rel(d.get("path") or "", root=root)]
    if not docs:
        return ""
    lines = [
        "\n\n=== 本话题正在做的稿 ===",
        "这些文件挂在这场对话里。改字 revise_office，加图 illustrate_office，加页 extend_office，不要 generate_* 整份重出。",
    ]
    for i, d in enumerate(docs):
        rel = d["path"]
        lines.append(f"- {rel}")
        if i == 0:
            body = digest(rel, root=root)
            if body:
                lines.append("摘要（最新这份）：")
                lines.append(body)
    return "\n".join(lines) + "\n"


def bind_from_text(sid: str, text: str, *, root: Path | None = None) -> list[dict]:
    """已停用 · wish-1518b97f.2 (BRO 2026-09-14 拍板)。

    旧行为: 消息文本里出现某个路径 → 那条路径就挂进本场。后果:
      ① A 场产出的稿 · 只因 B 场聊到它的名字 · 就被 B 场冒认
      ② 同一份稿多场各自 home_sid = 自己 (一份稿几个妈)
      ③ 越扯越乱: 一份稿到底属于谁无从判定

    现在: 产物/附件【只认产出者与主动带入】· 聊到名字不算数。
    保留函数名与签名 (调用点仍调它) · 但不再写任何绑定 · 恒返空。
    """
    return []


def _resolve_current_sid() -> str:
    """当前对话身份 —— 产物 origin 只能信它。

    wish-c6422f9c: 原来直接用 RUNTIME.session_id（进程级全局单例），多对话并发时
    它停在「最后设过的那一场」，导致 A 场产出的稿记到 B 场名下（21:00 实测：新场
    7c472f 产出的 pptx·origin 被记到上一场 291f25）。 全仓其余需要「当前对话身份」
    的地方（track_task / edit_file / write_file / dispatch_subagent / turn_checkpoint）
    都已改用 agent_tools.current_session_id() 会话级 ContextVar，这里跟上。
    """
    try:
        from agent_tools import current_session_id
        sid = str(current_session_id() or "").strip()
        # 拿不到时会退化成 t<线程id> · 那不是真 session id · 不能用
        if sid and not (sid.startswith("t") and sid[1:].isdigit()):
            return sid
    except Exception:
        pass
    try:                                    # 兜底：终端 REPL / 无上下文的后台路径
        from daemon_runtime import RUNTIME
        return str(getattr(RUNTIME, "session_id", "") or "").strip()
    except Exception:
        return ""


def bind_runtime(rel: str, *, session_id: str | None = None) -> dict | None:
    try:
        sid = (session_id or "").strip() or _resolve_current_sid()
        if sid:
            return bind(sid, rel, claim=True, via="generated")   # wish-1518b97f.2 · 工具真产出
    except Exception:
        return None
    return None


def ingest_file(sid: str, src: Path, name: str, *, root: Path | None = None) -> dict | None:
    base = root or _ROOT
    src = Path(src)
    if not src.is_file() or not sid:
        return None
    ext = Path(name or src.name).suffix.lower() or src.suffix.lower()
    folder_name = _PRODUCT.get(ext)
    if not folder_name:
        return None
    from workers.output_versions import publish, safe_family, staged_path
    family = safe_family(Path(name or src.name).stem)
    folder = base / "data" / folder_name
    dest = folder / f"{family}{ext}"
    if not dest.exists():
        wip = staged_path(folder, family, ext)
        shutil.copy2(src, wip)
        dest, _ver = publish(wip, folder, family, ext)
    rel = rel_of(dest, root=base)
    if not rel:
        return None
    return bind(sid, rel, root=base, claim=True, via="uploaded")


def accept_upload(sid: str, raw: str, *, root: Path | None = None):
    """attachments 办公稿入库；货架上的稿挂进这场。"""
    rel = _canon_rel(raw, root=root)
    path = resolve_rel(rel, root=root)
    if path is None:
        return None, "path 不是本机上的办公稿"
    if "runtime/attachments" in rel:
        m = re.match(r"^.+?_\d+_\d+_(.+)$", path.name)
        rec = ingest_file(sid, path, m.group(1) if m else path.name, root=root)
        path = resolve_rel((rec or {}).get("path") or "", root=root) if rec else None
        return (path, "") if path else (None, "办公稿入库失败")
    if sid:
        bind(sid, rel_of(path, root=root) or rel, root=root, claim=True, via="uploaded")
    return path, ""


def describe_office(rel: str, *, root: Path | None = None) -> str:
    body = digest(rel, root=root, limit=1800)
    bits = [
        f"办公稿已挂进本话题 · 路径: {rel}",
        f"改字 revise_office path={rel}。加图 illustrate_office。加页 extend_office path={rel}（after=页码插在该页后）。不要 generate_presentation，原页板式必须留下。",
    ]
    if body:
        bits.append("摘要：")
        bits.append(body)
    return "\n".join(bits)


def merge_into_artifacts(artifacts: list[dict], sid: str) -> list[dict]:
    seen = {str(a.get("url") or "") for a in artifacts}
    out = list(artifacts)
    for d in list_bound(sid):
        rel = d.get("path") or ""
        if not resolve_rel(rel):
            continue
        url = "/" + rel[5:] if rel.startswith("data/") else rel
        if "runtime/attachments/" in rel:
            url = "/attachments/" + Path(rel).name
        if url in seen:
            continue
        seen.add(url)
        ext = Path(rel).suffix.lower().lstrip(".")
        out.append({"name": d.get("name") or Path(rel).name, "url": url, "ext": ext})
    return out
