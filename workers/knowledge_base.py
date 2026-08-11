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
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from workers.safe_write import atomic_write_json, _do_backup

ROOT = Path(__file__).resolve().parent.parent
KB_DIR = ROOT / "data" / "knowledge"
DOCS_DIR = KB_DIR / "docs"
MANIFEST_PATH = KB_DIR / "manifest.json"

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
        return {"docs": {}}
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        # 损坏 → 先备份现场 (safe_write._do_backup 到 data/_backups/) · 再返空壳
        try:
            _do_backup(MANIFEST_PATH)
        except Exception:
            pass
        return {"docs": {}}
    if not isinstance(data.get("docs"), dict):
        data["docs"] = {}
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


def remove_document(doc_id: str) -> dict:
    """删档:出 manifest + 删 .md + 从 FTS5 清索引。找不到抛 KeyError。"""
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
        return meta


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
