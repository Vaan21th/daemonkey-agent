"""
workers/session_search.py
=========================

卷四十六 II · wish-2a92774d · hermes 风格 L2 session 聚合搜索

设计动机:
  现状: workers/memory_index.py 已经把 sessions/*.jsonl 全部 index 进 FTS5 (每条
        message 成一个 chunk · 1221 chunks · scope='sessions' 也能搜)。
  缺口: 搜出来是 message-level 碎片 · 没按 session 分组聚合 · BRO 看不出
        "X session 在 5/23 谈了什么 · 跟 5/26 哪个 session 同主题"。

本模块在 memory_index 之上做 hermes L2 增强:
  1. session 列表 + metadata 提取 (创建时间 / 第一句 BRO message / msg 数)
  2. since/until 时间过滤
  3. 单 session 全 message 拉取 (LLM 想看某 session 完整上下文时)
  4. 按 session 聚合的搜索 (1 个 session 多 matched_messages · 不是 N 个孤立碎片)

不动 memory_index 的 schema · 只在它之上加聚合层。
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("opus.session_search")

ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = ROOT / "sessions"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "memory_index.db"


@dataclass
class SessionMeta:
    """单个 session 的元数据 (从 jsonl 头部 + stat 提取)"""
    session_id: str         # = jsonl stem (e.g. 'api-2026-05-26_014022_697694')
    filename: str           # 完整文件名
    created_at: str         # 第一条 message 的 ts (ISO)
    last_msg_at: str        # 最后一条 message 的 ts (ISO)
    msg_count: int          # 总 message 数
    first_user_msg: str     # 第一条 user message 截前 200 字 (作为摘要)
    size_bytes: int         # 文件大小


@dataclass
class SessionSearchHit:
    """搜出来的 message hit + session 上下文"""
    session_id: str
    role: str               # user / assistant / system / tool
    ts: str                 # ISO 时间
    content: str            # 完整内容 (可能很长)
    rank: float = 0.0       # FTS5 BM25 rank


@dataclass
class SessionSearchAggregated:
    """按 session 聚合后的结果"""
    session: SessionMeta
    matched_count: int      # 这个 session 里有几条 message 命中
    hits: list[SessionSearchHit] = field(default_factory=list)  # 前 N 条 (top_messages_per_session)


# ─── session metadata 提取 ──────────────────────────────────────────────────

def _read_first_n_lines(path: Path, n: int = 6) -> list[dict]:
    """读 jsonl 前 n 个 record (跳过空行) · 用于提取头部元数据。"""
    records: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if len(records) >= n:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.warning("读 %s 前 %d 行失败: %s", path.name, n, e)
    return records


def _read_last_line(path: Path) -> Optional[dict]:
    """tail 1 line (用于 last_msg_at)"""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            file_size = f.tell()
            block_size = min(2048, file_size)
            f.seek(-block_size, 2)
            tail = f.read().decode("utf-8", errors="ignore")
        lines = [ln.strip() for ln in tail.splitlines() if ln.strip()]
        if not lines:
            return None
        return json.loads(lines[-1])
    except Exception:
        return None


def _count_lines(path: Path) -> int:
    """快速 line count"""
    try:
        with open(path, "rb") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def get_session_meta(session_id_or_path: str | Path) -> Optional[SessionMeta]:
    """读单个 session 的元数据。 session_id 不含扩展名。"""
    if isinstance(session_id_or_path, Path):
        path = session_id_or_path
    else:
        path = SESSIONS_DIR / f"{session_id_or_path}.jsonl"
    if not path.exists():
        return None

    head_records = _read_first_n_lines(path, 6)
    if not head_records:
        return None

    last = _read_last_line(path)

    # 找第一条 user message
    first_user = ""
    created_at = ""
    for rec in head_records:
        if not created_at and rec.get("ts"):
            created_at = rec["ts"]
        if rec.get("role") == "user" and not first_user:
            first_user = (rec.get("content") or "")[:200]
        if first_user and created_at:
            break

    last_at = (last.get("ts") if last else "") or created_at
    msg_count = _count_lines(path)

    return SessionMeta(
        session_id=path.stem,
        filename=path.name,
        created_at=created_at or "",
        last_msg_at=last_at or "",
        msg_count=msg_count,
        first_user_msg=first_user,
        size_bytes=path.stat().st_size,
    )


def list_sessions(
    limit: int = 30,
    since: Optional[str] = None,
    until: Optional[str] = None,
    sort_by: str = "mtime_desc",  # 'mtime_desc' / 'created_desc' / 'msg_count_desc'
) -> list[SessionMeta]:
    """列出 sessions/ 下所有 jsonl · 按 sort_by 排序 · 时间过滤。"""
    if not SESSIONS_DIR.exists():
        return []

    files = list(SESSIONS_DIR.glob("*.jsonl"))
    metas: list[SessionMeta] = []
    for f in files:
        meta = get_session_meta(f)
        if meta is None:
            continue
        if since and meta.created_at and meta.created_at < since:
            continue
        if until and meta.created_at and meta.created_at > until:
            continue
        metas.append(meta)

    if sort_by == "created_desc":
        metas.sort(key=lambda m: m.created_at, reverse=True)
    elif sort_by == "msg_count_desc":
        metas.sort(key=lambda m: m.msg_count, reverse=True)
    else:  # mtime_desc 默认
        metas.sort(key=lambda m: m.last_msg_at, reverse=True)

    return metas[:limit]


def get_session_messages(session_id: str, limit: int = 200) -> list[dict]:
    """读单个 session 全 messages (按时间序)。 limit 防超大 session 卡 LLM。"""
    path = SESSIONS_DIR / f"{session_id}.jsonl"
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if len(out) >= limit:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    out.append({
                        "role": rec.get("role", ""),
                        "ts": rec.get("ts", ""),
                        "content": rec.get("content", ""),
                    })
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.warning("读 %s 失败: %s", path.name, e)
    return out


# ─── 按 session 聚合的搜索 ──────────────────────────────────────────────────

def search_in_sessions(
    query: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    session_id: Optional[str] = None,
    limit_sessions: int = 10,
    top_messages_per_session: int = 3,
    max_total_messages: int = 30,
) -> list[SessionSearchAggregated]:
    """按 session 聚合搜索 · 不返碎片 message · 返 session 列表 + 每个 session 的 top N 命中。

    Args:
        query: FTS5 query
        since/until: ISO date · 按 chunk.updated_at (= record.ts) 过滤
        session_id: 限定单个 session
        limit_sessions: 最多返多少 session
        top_messages_per_session: 每 session 返多少 top message
        max_total_messages: 全局 message 上限 (防超大返回)
    """
    if not DB_PATH.exists():
        return []

    safe_query = query.replace('"', '""')
    fts_query = f'"{safe_query}"'

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    # 走 FTS5 · 只看 source='session' · 用 BM25 rank 排序 (修 wish-1c229865 顺带发现的 latent bug · 之前 FTS5 path 失败 · 跑 LIKE fallback)
    sql = """
        SELECT c.source, c.section, c.content, c.updated_at, memory_fts.rank
        FROM memory_fts
        JOIN memory_chunks c ON memory_fts.rowid = c.id
        WHERE memory_fts MATCH ? AND c.source = 'session'
        ORDER BY memory_fts.rank
        LIMIT 500
    """

    try:
        rows = conn.execute(sql, (fts_query,)).fetchall()
    except sqlite3.OperationalError as e:
        logger.warning("FTS5 query failed: %s · 退化 LIKE", e)
        # 退化: LIKE 慢但能跑
        like_sql = """
            SELECT c.source, c.section, c.content, c.updated_at, 0 AS rank
            FROM memory_chunks c
            WHERE c.source = 'session' AND c.content LIKE ?
            LIMIT 500
        """
        try:
            rows = conn.execute(like_sql, (f"%{query}%",)).fetchall()
        except sqlite3.OperationalError:
            conn.close()
            return []

    conn.close()

    # rows = (source, section='<sid>:<role>', content, updated_at, rank)
    # 按 session_id 聚合
    by_session: dict[str, list[SessionSearchHit]] = {}
    for source, section, content, updated_at, rank in rows:
        # section = "<filename_stem>:<role>"
        if ":" not in section:
            continue
        sid, _, role = section.partition(":")

        if session_id and sid != session_id:
            continue
        if since and updated_at and updated_at < since:
            continue
        if until and updated_at and updated_at > until:
            continue

        hit = SessionSearchHit(
            session_id=sid,
            role=role,
            ts=updated_at,
            content=content,
            rank=float(rank) if rank is not None else 0.0,
        )
        by_session.setdefault(sid, []).append(hit)

    # session-level 排序 · 按"该 session 最佳 rank" 升序 (FTS5 rank 越小越相关)
    session_ids_sorted = sorted(
        by_session.keys(),
        key=lambda sid: min(h.rank for h in by_session[sid]),
    )

    aggregated: list[SessionSearchAggregated] = []
    total_msgs = 0
    for sid in session_ids_sorted[:limit_sessions]:
        meta = get_session_meta(sid)
        if meta is None:
            continue
        hits = sorted(by_session[sid], key=lambda h: h.rank)[:top_messages_per_session]
        if total_msgs + len(hits) > max_total_messages:
            hits = hits[: max_total_messages - total_msgs]
        total_msgs += len(hits)
        aggregated.append(SessionSearchAggregated(
            session=meta,
            matched_count=len(by_session[sid]),
            hits=hits,
        ))
        if total_msgs >= max_total_messages:
            break

    return aggregated


# ─── stats / 自检 ──────────────────────────────────────────────────────────

def get_session_stats() -> dict:
    """sessions/ 统计 · daemon 启动时 / BRO 查 `sessions 多少 jsonl 多少 message` 时用。"""
    if not SESSIONS_DIR.exists():
        return {"sessions_dir_exists": False, "total_sessions": 0}

    files = list(SESSIONS_DIR.glob("*.jsonl"))
    total_msg = 0
    total_bytes = 0
    earliest = None
    latest = None
    for f in files:
        msg = _count_lines(f)
        total_msg += msg
        total_bytes += f.stat().st_size
        meta = get_session_meta(f)
        if meta and meta.created_at:
            if earliest is None or meta.created_at < earliest:
                earliest = meta.created_at
            if latest is None or meta.last_msg_at > latest:
                latest = meta.last_msg_at

    # 索引覆盖率
    index_stats = {"indexed": False, "session_chunks": 0}
    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(str(DB_PATH))
            row = conn.execute(
                "SELECT COUNT(*), SUM(token_count) FROM memory_chunks WHERE source = 'session'"
            ).fetchone()
            conn.close()
            index_stats = {
                "indexed": True,
                "session_chunks": row[0] or 0,
                "session_tokens": row[1] or 0,
            }
        except sqlite3.DatabaseError:
            pass

    return {
        "sessions_dir_exists": True,
        "total_sessions": len(files),
        "total_messages": total_msg,
        "total_bytes": total_bytes,
        "size_mb": round(total_bytes / 1024 / 1024, 2),
        "earliest_session_at": earliest or "",
        "latest_session_at": latest or "",
        "index": index_stats,
    }
