"""
workers/knowledge_base.py
=========================

私有文档知识库 —— "合伙人的第二大脑"。存量文档的家 + FTS5 索引接线。

存储(全在 data/knowledge/ · never_sync · 升级绝不覆盖用户资料):
  data/knowledge/docs/<doc_id>.md   · 抽出的 markdown 正文(原文备份 · 供重建索引/预览)
  data/knowledge/manifest.json      · 每篇元数据 + 设置(enabled/pinned/tags/sensitive…)

检索复用 workers/memory_index 的 FTS5 引擎:每篇文档 source = 'doc:<id>'。
  - enabled=True  → 索引进 FTS5 · recall_memory(scope='docs') 能召回
  - enabled=False → 从 FTS5 删掉(彻底静音)· 原文 .md 保留 · 一键开回来自动重建

设计红线:只动 data/knowledge/ · 不碰 soul / sessions / 系统目录。
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from workers.safe_write import atomic_write_json, _do_backup

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
KB_DIR = ROOT / "data" / "knowledge"
DOCS_DIR = KB_DIR / "docs"
MANIFEST_PATH = KB_DIR / "manifest.json"

# 拖拽进来的原件固定落这里（api_routes6knowledge.py 的 INCOMING_DIR 同指一处）。
INCOMING_DIR = KB_DIR / "incoming"
# 回收站：与「本地数据 → 智能清理」共用同一套（同一个目录、同一个 <ts>/<相对路径> 布局），
# 这样用户在智能清理的回收站里能一起看到 / 还原 / 清空，不用再学一个新地方。
TRASH_REL = "data/runtime/trash"

DOC_SOURCE_PREFIX = "doc:"

# wish-a1c5f147 (墨言模块 10) · 复合操作锁: load→改→save 是读改写三段·
# 多 session 并行 (BRO 多开实例) 时丢更新 → 公开写函数整体持锁
_MANIFEST_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_dirs() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)


def _doc_md_path(doc_id: str) -> Path:
    return DOCS_DIR / f"{doc_id}.md"


def load_manifest() -> dict:
    """读 manifest · 缺文件/损坏都退回空壳(绝不抛)。

    wish-a1c5f147 (墨言模块 10) · 损坏备份: JSON 解析失败时先把损坏文件备份为
    manifest.json.corrupt-<ts> 保留现场 → 再返空壳。防"写操作静默覆盖清空用户元数据"
    (红线: 升级绝不覆盖用户资料 · 一旦 manifest 损坏且被写覆盖 · 全部文档元数据丢失)。
    """
    if not MANIFEST_PATH.exists():
        return {"docs": {}, "folders": []}
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        # 损坏 → 先备份现场 (safe_write._do_backup 到 data/_backups/) · 再返空壳
        try:
            _do_backup(MANIFEST_PATH)
        except Exception:
            pass
        return {"docs": {}, "folders": []}
    if not isinstance(data.get("docs"), dict):
        data["docs"] = {}
    # 2026-10-01 · folders = 显式登记的文件夹名。
    #   不登记就存不住「我先建个空文件夹、回头再往里放」—— 小组原来是靠文档的 folder 字段
    #   现算出来的（见 dashboard-panels.js 的 folderOf），一篇都没有时这个组就消失了。
    if not isinstance(data.get("folders"), list):
        data["folders"] = []
    return data


def _save_manifest(data: dict) -> None:
    _ensure_dirs()
    # wish-a1c5f147 · 原子写 + 写前备份 (safe_write 复用 · 断电半写不再损坏 JSON)
    atomic_write_json(MANIFEST_PATH, data)


def _new_doc_id() -> str:
    return "doc-" + uuid.uuid4().hex[:8]


def _index(doc_id: str, text: str) -> int:
    """把文档正文送进 FTS5(source=doc:<id>)· 返回切出的块数。"""
    from workers.memory_index import incremental_update

    return incremental_update(f"{DOC_SOURCE_PREFIX}{doc_id}", text)


def _deindex(doc_id: str) -> None:
    """空文本增量更新 = 删掉该 source 的全部 FTS5 块(静音/删档共用)。"""
    from workers.memory_index import incremental_update

    incremental_update(f"{DOC_SOURCE_PREFIX}{doc_id}", "")


def resolve_doc_id(hint: str) -> str | None:
    """按 id / 标题(精确→模糊)找 doc_id · 给 NLP 工具用。"""
    hint = (hint or "").strip()
    if not hint:
        return None
    docs = load_manifest()["docs"]
    if hint in docs:
        return hint
    low = hint.lower()
    for did, meta in docs.items():
        if (meta.get("title") or "").lower() == low:
            return did
    for did, meta in docs.items():
        if low in (meta.get("title") or "").lower():
            return did
    return None


def _auto_summary(text: str, max_chars: int = 180) -> str:
    """缺口⑤ · 入库抽一句摘要(取首个有意义段落·跳过标题/表格/代码栏)。
    零 LLM 成本·纯抽取·让目录注入更省 token、命中更直观。日后可升级为 LLM 总结。
    """
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("#>-*• \t")
        if len(line) >= 8 and not line.startswith(("|", "```", "---", "===")):
            return line[:max_chars] + ("…" if len(line) > max_chars else "")
    flat = " ".join((text or "").split())
    return flat[:max_chars] + ("…" if len(flat) > max_chars else "")


def add_document(
    path: str | Path,
    *,
    tags: list[str] | None = None,
    pinned: bool = False,
    sensitive: bool = False,
    folder: str = "",
    client_id: str = "",
) -> dict:
    """抽文字 → 落 docs/<id>.md → 记 manifest → 建 FTS5 索引 · 返回元数据。

    Raises: workers.doc_ingest.IngestError —— 抽取失败(格式/扫描件/缺依赖)。
    """
    from workers.doc_ingest import extract

    title, text, doc_type = extract(path)
    _ensure_dirs()
    with _MANIFEST_LOCK:  # wish-a1c5f147 · 复合操作锁 (读改写整体持锁)
        data = load_manifest()
        doc_id = _new_doc_id()
        _doc_md_path(doc_id).write_text(text, encoding="utf-8")

        chunks = _index(doc_id, text)
        meta = {
            "id": doc_id,
            "title": title,
            "orig_path": str(Path(path)),
            "type": doc_type,
            "enabled": True,
            "pinned": bool(pinned),
            "sensitive": bool(sensitive),
            "tags": list(tags or []),
            "folder": (folder or "").strip(),
            "client_id": (client_id or "").strip(),
            "summary": _auto_summary(text),
            "chars": len(text),
            "chunks": chunks,
            "added_at": _now(),
            "updated_at": _now(),
        }
        data["docs"][doc_id] = meta
        _save_manifest(data)
        return meta


def list_documents(tag: str | None = None) -> list[dict]:
    """列全部文档元数据(可按 tag 过滤)· 新入库的排前面。"""
    docs = list(load_manifest()["docs"].values())
    if tag:
        docs = [d for d in docs if tag in (d.get("tags") or [])]
    docs.sort(key=lambda d: d.get("added_at", ""), reverse=True)
    return docs


def list_folders() -> list[str]:
    """列显式登记的文件夹名（空文件夹也留着）。"""
    return [str(x) for x in (load_manifest().get("folders") or []) if str(x).strip()]


def add_folder(name: str) -> dict:
    """新建一个知识库文件夹。

    2026-10-01 BRO:「文件夹显示 ＋添加旁边加一个创建文件夹」——
    空文件夹必须存得住，所以走 manifest 的 folders 字段显式登记，
    而不是靠文档的 folder 字段现算（那样一篇都没有时这个组就消失了）。
    幂等：同名直接返回 created=False，不报错。
    """
    name = str(name or "").strip().strip("/\\")
    if not name:
        raise ValueError("文件夹名不能为空")
    with _MANIFEST_LOCK:
        data = load_manifest()
        folders = data.setdefault("folders", [])
        if name in folders:
            return {"ok": True, "name": name, "created": False, "folders": list(folders)}
        folders.append(name)
        _save_manifest(data)
        return {"ok": True, "name": name, "created": True, "folders": list(folders)}


def remove_folder(name: str, *, drop_docs: bool = False) -> dict:
    """删一个知识库文件夹登记。

    非空时【默认拒绘】—— 不偷着把用户的分组连文档一起干掉。
    但要让他知道里面有多少篇，前端才好问「里面有 N 篇，一并放回未分类？」——
    drop_docs=True 才真把里面文档的 folder 清成 ""（文档本身不删，只是回到未分类）。

    幂等：文件夹不存在返回 removed=False，不报错。
    """
    name = str(name or "").strip().strip("/\\")
    if not name:
        raise ValueError("文件夹名不能为空")
    with _MANIFEST_LOCK:
        data = load_manifest()
        folders = data.setdefault("folders", [])
        if name not in folders:
            return {"ok": True, "name": name, "removed": False, "folders": list(folders)}
        n = sum(1 for d in data["docs"].values() if str(d.get("folder") or "") == name)
        if n and not drop_docs:
            return {"ok": False, "name": name, "removed": False, "doc_count": n,
                    "error": f"里面还有 {n} 篇文档"}
        for d in data["docs"].values():
            if str(d.get("folder") or "") == name:
                d["folder"] = ""
        folders.remove(name)
        _save_manifest(data)
        return {"ok": True, "name": name, "removed": True,
                "moved_docs": n, "folders": list(folders)}


def get_document(doc_id: str) -> dict | None:
    return load_manifest()["docs"].get(doc_id)


def find_by_orig_path(path: str | Path) -> dict | None:
    """按原始文件路径找已入库文档 · 给「存入知识库」防重复灌用。"""
    target = str(Path(path)).lower()
    for meta in load_manifest()["docs"].values():
        if (meta.get("orig_path") or "").lower() == target:
            return meta
    return None


def read_document_text(doc_id: str) -> str:
    p = _doc_md_path(doc_id)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _our_own_copy(meta: dict) -> Path | None:
    """这篇的原件是不是「我们自己复制进来的副本」（落在 incoming/ 里）？

    是 → 返回该路径（删档时该连它一起走）；
    不是（在用户自己的盘上）→ None，**绝不碰**。

    守卫不是「删之前校验一下」，而是根本不会发生：
    只有落在 INCOMING_DIR 底下的路径才过得了 relative_to()，
    用户盘上的 D:\我的资料\合同.pdf 天然抛 ValueError → 直接 None。

    2026-10-01 BRO:「拖拽进来的，点击删除只删索引不删文件，那不就有两份了？
    时间久了文件会很多吗？」—— 之前确实会：拖拽 = 复制一份进 incoming/，
    删档只清 manifest + docs/，incoming/ 里那份就变成没人引用的孤儿，越拖越多。
    """
    raw = str(meta.get("orig_path") or "").strip()
    if not raw:
        return None
    try:
        p = Path(raw).resolve()
        p.relative_to(INCOMING_DIR.resolve())
    except (ValueError, OSError):
        return None
    return p


def remove_document(doc_id: str, *, drop_original: bool = True) -> dict:
    """删档:出 manifest + 删 .md + 从 FTS5 清索引。找不到抛 KeyError。

    drop_original=True → 若这篇的原料是我们自己复制进来的副本，连它一起送回收站。
    不用调用方告知「这篇是不是拖进来的」—— _our_own_copy() 自己看 orig_path 落在
    哪儿就知道了。从用户自己盘上选进来的那些，相对路径天然不在 incoming/ 下，
    自动跳过，绝不会动他的盘。
    """
    with _MANIFEST_LOCK:  # wish-a1c5f147 · 复合操作锁
        data = load_manifest()
        meta = data["docs"].pop(doc_id, None)
        if meta is None:
            raise KeyError(doc_id)
        _deindex(doc_id)
        p = _doc_md_path(doc_id)
        if p.exists():
            p.unlink()
        _save_manifest(data)

    # 文件搬运放锁外（不持锁做 IO）。挪不动也绝不让删档失败 —— 宁可留个孤儿，
    # 也不能让用户点了删除却没反应。
    meta["original_dropped"] = False
    if drop_original:
        src = _our_own_copy(meta)
        if src is not None and src.exists():
            try:
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                dst = ROOT / TRASH_REL / stamp / src.relative_to(ROOT)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                meta["original_dropped"] = True
                meta["original_trashed_to"] = dst.relative_to(ROOT).as_posix()
            except (OSError, ValueError) as e:
                # ValueError: src 不在 ROOT 下（incoming 被做成指向外部的软链）時 relative_to 会抛。
                # 必须一并接住 —— 这时候文档和 manifest 都已经落了，再冒到 API 就是
                # 「东西删了、用户却收到报错」的反向体验。宁可留个孤儿。
                # 也不能静默（否则 incoming 里攒孤儿、事后无从查是哪次删档什么原因）。
                logger.warning("删档时原件搬运失败 · 留孤儿 %s: %s", src, e)
                meta["original_drop_error"] = str(e)
    return meta


def scan_incoming_orphans() -> list[dict]:
    """扫 incoming/ 里已经不被任何文档引用的文件（孤儿副本）。

    兜底用：正常流程下删档会把副本一起带走，不该有孤儿。
    但手动改过 manifest / 早期版本留下的会漏在里头 —— 这时用这个扫出来清掉，
    免得「时间久了文件越积越多」（BRO 2026-10-01 担心的就是这个）。
    """
    if not INCOMING_DIR.exists():
        return []
    used = set()
    for d in load_manifest()["docs"].values():
        raw = str(d.get("orig_path") or "").strip()
        if raw:
            try:
                used.add(str(Path(raw).resolve()).lower())
            except OSError:
                pass
    out: list[dict] = []
    for p in INCOMING_DIR.rglob("*"):
        if not p.is_file():
            continue
        try:
            key = str(p.resolve()).lower()
            stt = p.stat()
        except OSError:
            continue
        if key in used:
            continue
        out.append({
            "name": p.name,
            "rel": p.relative_to(ROOT).as_posix(),
            "bytes": stt.st_size,
            "mtime": datetime.fromtimestamp(stt.st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    out.sort(key=lambda x: -(x.get("bytes") or 0))
    return out


def set_enabled(doc_id: str, enabled: bool) -> dict:
    """参考开关:关掉 → 从 FTS5 删索引(静音)· 打开 → 从原文重建索引。"""
    with _MANIFEST_LOCK:  # wish-a1c5f147 · 复合操作锁
        data = load_manifest()
        meta = data["docs"].get(doc_id)
        if meta is None:
            raise KeyError(doc_id)
        meta["enabled"] = bool(enabled)
        meta["updated_at"] = _now()
        if enabled:
            meta["chunks"] = _index(doc_id, read_document_text(doc_id))
        else:
            _deindex(doc_id)
            meta["chunks"] = 0
        _save_manifest(data)
        return meta


def update_document(doc_id: str, **changes) -> dict:
    """改元数据(tags/pinned/sensitive/summary/title/folder/client_id)· 不动索引。"""
    allowed = {"tags", "pinned", "sensitive", "summary", "title", "folder", "client_id"}
    with _MANIFEST_LOCK:  # wish-a1c5f147 · 复合操作锁
        data = load_manifest()
        meta = data["docs"].get(doc_id)
        if meta is None:
            raise KeyError(doc_id)
        for key, val in changes.items():
            if key in allowed:
                meta[key] = val
        meta["updated_at"] = _now()
        _save_manifest(data)
        return meta


def search_documents(query: str, top_k: int = 5, context_window: int = 8000) -> list:
    """在知识库范围内检索(FTS5 scope='docs')· 返回 MemoryChunk 列表。"""
    from workers.memory_index import search

    return search(query, top_k=top_k, scope="docs", context_window=context_window)


def stats() -> dict:
    docs = load_manifest()["docs"]
    on = sum(1 for d in docs.values() if d.get("enabled", True))
    return {"total": len(docs), "enabled": on, "disabled": len(docs) - on}
