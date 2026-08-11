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
import threading
from datetime import datetime, timezone
from pathlib import Path

from workers.safe_write import atomic_write_json, _do_backup

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK_DIR = ROOT / "data" / "playbooks"
INDEX_PATH = PLAYBOOK_DIR / "_index.json"

# wish-a1c5f147 (墨言模块 12) · 复合操作锁: _load_index→改→_save_index 读改写三段·
# 多 session 并行丢更新 → 公开写函数整体持锁
_INDEX_LOCK = threading.Lock()


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
        # wish-a1c5f147 (墨言模块 12) · 损坏 → 先备份现场再返空壳 (防静默覆盖清空索引)
        try:
            _do_backup(INDEX_PATH)
        except Exception:
            pass
        return {"playbooks": {}, "updated_at": None}


def _save_index(index: dict) -> None:
    """保存索引 · wish-a1c5f147 · 原子写 + 写前备份 (safe_write 复用)"""
    index["updated_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write_json(INDEX_PATH, index)


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

    # wish-a1c5f147 (墨言模块 12) · 整体持锁: slug 检测 + .md 写 + index 写 ·
    # 防并发同 title 覆盖 / index 读改写竞态 (锁内全包)
    with _INDEX_LOCK:
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
            "suppression": 0.0,   # wish-88b4dcdc (墨言 02) · RIF 式抑制分 · 慢性干扰项降权用
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
        # 0.8.8 · 退役过滤 (BRO 否掉的资产不再进注入池 · wish-e3db429f)
        if meta.get("status") == "retired":
            continue
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
    with _INDEX_LOCK:  # wish-a1c5f147 · 复合操作锁
        index = _load_index()
        playbooks = index.get("playbooks", {})
        if playbook_id not in playbooks:
            return False
        playbooks[playbook_id]["used_count"] = playbooks[playbook_id].get("used_count", 0) + 1
        playbooks[playbook_id]["last_used_at"] = datetime.now(timezone.utc).isoformat()
        _save_index(index)
        return True


def delete_playbook(playbook_id: str) -> bool:
    """删一份 playbook（文件 + 索引 + FTS5）。

    R1-P3 (墨言三审) · 补 FTS5 rebuild: 原实现只删 md + _index.json · 不重建 FTS5 →
    已删 playbook 的 skill chunk 仍被 recall_memory(scope='skill') 搜到 (该路径不走 slug_map
    校验 · 绕过退役防护) · 实测删除后 FTS5 残留 3 条。与 save_playbook 对称触发 rebuild。
    """
    with _INDEX_LOCK:  # wish-a1c5f147 · 复合操作锁
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

    # R1-P3 · 删除后触发 FTS5 增量重建 · 清掉已删 playbook 的 skill chunk (与 save 对称)
    try:
        from workers.memory_index import rebuild as _rebuild_memory_index
        _rebuild_memory_index()
    except Exception as e:
        logger.warning("playbook deleted 后 FTS5 重建失败: %s · 等 daemon 重启时 rebuild", e)
    return True


# ── RIF 式抑制记账 (wish-88b4dcdc · 墨言 02) ──────────────────────
# 治"慢性干扰项": 注入 ≥2 次从未 load 的 playbook 记 suppression · 下次召回时降权/不占名额。
# 参考 lethe 的 RIF (retrieval-induced forgetting) · 只惩罚"反复被带出但从未被用"的条目。

# 阈值: 注入多少次未用才开始抑制 · 抑制增量 (learning_rate) · 抑制上限 (防彻底消失)
_SUPPRESS_MIN_INJECT = 2        # 注入 ≥2 次且 0 load → 开始记
_SUPPRESS_LR = 0.3              # 每次触发 +0.3
_SUPPRESS_MAX = 3.0             # bump 硬上限 · 防御性封顶 (cutoff 1.0 已先拦截·实际到不了)
_SUPPRESS_CUTOFF = 1.0          # 抑制分达到此值 → 不再注入 (closure_check 消费侧用)


def get_suppression(playbook_id: str) -> float:
    """读单份 playbook 的抑制分 (旧索引无字段 → 0)"""
    index = _load_index()
    return index.get("playbooks", {}).get(playbook_id, {}).get("suppression", 0.0)


def bump_suppression(playbook_id: str, delta: float = _SUPPRESS_LR) -> float:
    """给一份 playbook 加抑制分 (注入未用记账) · 返回新值"""
    with _INDEX_LOCK:
        index = _load_index()
        playbooks = index.get("playbooks", {})
        if playbook_id not in playbooks:
            return 0.0
        cur = float(playbooks[playbook_id].get("suppression", 0.0))
        new = min(cur + delta, _SUPPRESS_MAX)
        playbooks[playbook_id]["suppression"] = new
        _save_index(index)
    return new


def clear_suppression(playbook_id: str) -> None:
    """清零一份 playbook 的抑制分 (被 load 过 = 证明有用 · 撤销抑制)"""
    with _INDEX_LOCK:
        index = _load_index()
        playbooks = index.get("playbooks", {})
        if playbook_id not in playbooks:
            return
        if playbooks[playbook_id].get("suppression", 0.0) != 0.0:
            playbooks[playbook_id]["suppression"] = 0.0
            _save_index(index)


def top_suppressed(limit: int = 5) -> list[dict]:
    """返回抑制分最高的 playbook 清单 (慢性干扰项 · 供 inject_stats 展示)"""
    index = _load_index()
    rows = []
    for pid, m in index.get("playbooks", {}).items():
        s = float(m.get("suppression", 0.0))
        if s > 0:
            rows.append({"id": pid, "title": m.get("title", ""), "suppression": s})
    rows.sort(key=lambda x: -x["suppression"])
    return rows[:limit]
