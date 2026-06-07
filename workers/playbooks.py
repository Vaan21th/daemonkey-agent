"""
workers/playbooks.py
====================

卷三十七 · Playbook 系统核心

OPUS 完成任务后，把可复用的操作模式抽成 playbook（markdown 文件）。
下次类似任务时，OPUS 手动搜索匹配的 playbook 加速。

设计原则（反 Hermes）:
  - 不打断 LLM 思考流 · 不每 15 步自检
  - task 完成后才复盘 · 觉得可复用才抽 playbook
  - 纯 markdown + frontmatter · 不引入新维度 / 新数据库
  - 瘦到不会出错

文件结构:
  data/playbooks/
    ├── <slug>.md      · 每个 playbook 一个文件
    └── _index.json    · 索引（快速搜索用 · 不从 markdown 解析）
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK_DIR = ROOT / "data" / "playbooks"
INDEX_PATH = PLAYBOOK_DIR / "_index.json"


def _ensure_dir() -> None:
    PLAYBOOK_DIR.mkdir(parents=True, exist_ok=True)


# ── 索引操作 ──────────────────────────────────────────────────

def _load_index() -> dict:
    """加载索引 · 不存在则返回空"""
    _ensure_dir()
    if not INDEX_PATH.exists():
        return {"playbooks": {}, "updated_at": None}
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"playbooks": {}, "updated_at": None}


def _save_index(index: dict) -> None:
    """保存索引"""
    index["updated_at"] = datetime.now(timezone.utc).isoformat()
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def _slugify(text: str, max_len: int = 60) -> str:
    """把标题/任务名转成文件 slug"""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or "playbook"


# ── CRUD ──────────────────────────────────────────────────────

def save_playbook(
    title: str,
    task_type: str,
    steps: str,
    prerequisites: str = "",
    pitfalls: str = "",
    lessons: str = "",
    tags: list[str] | None = None,
) -> dict:
    """
    保存一份 playbook 到 data/playbooks/<slug>.md。

    返回: {"id": ..., "slug": ..., "path": ...}
    """
    _ensure_dir()

    slug = _slugify(title)
    # 防重名：如果 slug 已存在，加短 hash
    existing = PLAYBOOK_DIR / f"{slug}.md"
    if existing.exists():
        short_hash = hashlib.md5(title.encode()).hexdigest()[:6]
        slug = f"{slug}-{short_hash}"

    filepath = PLAYBOOK_DIR / f"{slug}.md"
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M UTC")

    tags_yaml = ""
    if tags:
        tags_yaml = "tags: [" + ", ".join(tags) + "]\n"

    # 卷四十六 II · wish-1c229865 · agentskills.io 兼容 frontmatter (phase C)
    # 给 LLM 调 recall_memory(scope='skill') 时 · 头部 metadata 帮助判断相关性
    frontmatter = (
        "---\n"
        f"title: {title}\n"
        f"task_type: {task_type}\n"
        f"created_at: {now.isoformat()}\n"
        f"used_count: 0\n"
        f"agentskills_version: 1\n"
        f"{tags_yaml}"
        "---\n\n"
    )

    # 写 markdown 文件
    content = (
        frontmatter
        + f"# {title}\n\n"
        f"<!-- playbook · 由 OPUS 在 {now_str} 抽取 -->\n\n"
        f"## 前置条件\n\n{prerequisites or '无特殊前置条件'}\n\n"
        f"## 步骤\n\n{steps}\n\n"
        f"## 常见坑\n\n{pitfalls or '暂无记录'}\n\n"
        f"## 经验教训\n\n{lessons or '暂无记录'}\n"
    )
    filepath.write_text(content, encoding="utf-8")

    # 更新索引
    index = _load_index()
    playbook_id = f"pb-{slug[:40]}"
    index["playbooks"][playbook_id] = {
        "id": playbook_id,
        "title": title,
        "slug": slug,
        "task_type": task_type,
        "tags": tags or [],
        "created_at": now.isoformat(),
        "used_count": 0,
        "last_used_at": None,
        "file_size": len(content.encode("utf-8")),
    }
    _save_index(index)

    logger.info("playbook saved: %s → %s", title, filepath)

    # 卷四十六 II · wish-1c229865 · 新增 playbook 后触发 FTS5 增量索引
    # 这样 recall_memory(scope='skill') 能立刻搜到新 skill · 不用等下次 daemon 启动 rebuild
    try:
        from workers.memory_index import rebuild as _rebuild_memory_index
        _rebuild_memory_index()  # 简单粗暴 full rebuild · 几秒内完成 · 跟其他源同步
    except Exception as e:
        logger.warning("playbook saved 后 FTS5 增量索引失败: %s · 等 daemon 重启时 rebuild", e)

    return {"id": playbook_id, "slug": slug, "path": str(filepath)}


def load_playbook(playbook_id: str | None = None, slug: str | None = None) -> dict:
    """
    读单份 playbook · 按 id 或 slug 查找。

    返回: {"id": ..., "title": ..., "content": ..., "meta": {...}}
    """
    _ensure_dir()
    index = _load_index()
    playbooks = index.get("playbooks", {})

    meta = None
    if playbook_id and playbook_id in playbooks:
        meta = playbooks[playbook_id]
    elif slug:
        for pid, m in playbooks.items():
            if m.get("slug") == slug:
                meta = m
                playbook_id = pid
                break

    if meta is None:
        return {"id": None, "title": "", "content": "", "meta": {}, "error": "playbook 不存在"}

    filepath = PLAYBOOK_DIR / f"{meta['slug']}.md"
    if not filepath.exists():
        return {"id": playbook_id, "title": meta.get("title", ""), "content": "", "meta": meta, "error": "文件丢失"}

    content = filepath.read_text(encoding="utf-8")
    return {"id": playbook_id, "title": meta.get("title", ""), "content": content, "meta": meta}


def search_playbooks(query: str | None = None, task_type: str | None = None, tag: str | None = None, limit: int = 10) -> list[dict]:
    """
    搜索 playbook · 按 query（标题/标签模糊）或 task_type 或 tag 过滤。

    返回: [{"id": ..., "title": ..., "slug": ..., "tags": [...], ...}, ...]
    """
    _ensure_dir()
    index = _load_index()
    playbooks = index.get("playbooks", {})

    results = []
    query_lower = (query or "").lower()

    for pid, meta in playbooks.items():
        # task_type 过滤
        if task_type and meta.get("task_type", "").lower() != task_type.lower():
            continue
        # tag 过滤
        if tag and tag.lower() not in [t.lower() for t in meta.get("tags", [])]:
            continue
        # query 模糊匹配（标题 + tags）
        if query_lower:
            title_lower = meta.get("title", "").lower()
            tags_lower = " ".join(meta.get("tags", [])).lower()
            if query_lower not in title_lower and query_lower not in tags_lower:
                continue

        results.append({
            "id": pid,
            "title": meta.get("title", ""),
            "slug": meta.get("slug", ""),
            "task_type": meta.get("task_type", ""),
            "tags": meta.get("tags", []),
            "created_at": meta.get("created_at", ""),
            "used_count": meta.get("used_count", 0),
            "last_used_at": meta.get("last_used_at"),
        })

    results.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return results[:limit]


def list_playbooks() -> list[dict]:
    """列出所有 playbook（全量）"""
    return search_playbooks(limit=200)


def mark_used(playbook_id: str) -> bool:
    """标记 playbook 被使用（used_count += 1）"""
    index = _load_index()
    playbooks = index.get("playbooks", {})
    if playbook_id not in playbooks:
        return False
    playbooks[playbook_id]["used_count"] = playbooks[playbook_id].get("used_count", 0) + 1
    playbooks[playbook_id]["last_used_at"] = datetime.now(timezone.utc).isoformat()
    _save_index(index)
    return True


def delete_playbook(playbook_id: str) -> bool:
    """删一份 playbook（文件 + 索引）"""
    index = _load_index()
    playbooks = index.get("playbooks", {})
    if playbook_id not in playbooks:
        return False
    meta = playbooks[playbook_id]
    filepath = PLAYBOOK_DIR / f"{meta['slug']}.md"
    if filepath.exists():
        filepath.unlink()
    del playbooks[playbook_id]
    _save_index(index)
    return True
