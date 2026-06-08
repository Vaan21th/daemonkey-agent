"""
workers/memory_index.py
=======================

SQLite FTS5 全文检索引擎 —— 让 OPUS 能跨会话搜索灵魂层文件。

卷三十五 · wish-273374f6 · 接 SQLite FTS5 让 BRO-NOTEBOOK 跨会话可全文检索。

设计原则 (BRO 红线):
  - 只写 data/memory_index.db · 不动系统目录
  - 索引只读源文件 · 不修改任何 soul/ 下的 md
  - 轻量 · 同步 · 无外部依赖 (Python stdlib sqlite3 已足够)

用法 · CLI 单跑:
    .\\.venv\\Scripts\\python.exe -m workers.memory_index --rebuild
    .\\.venv\\Scripts\\python.exe -m workers.memory_index --search "关键词"

用法 · 被 agent_tools/recall_memory.py 调用:
    from workers.memory_index import search, rebuild, check_stale, incremental_update, get_stats
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("opus.memory_index")

# 卷四十六 II · wish-43f705b8 · 中文 jieba tokenizer · 修中文搜 0 命中 latent bug
# SQLite FTS5 默认 unicode61 tokenizer 按空白分词 · 中文没空格 → 一句话被当一个 token · 必然 0 命中
# 修法: 写入时用 jieba 切词后 join ' ' 存 content_tok · search 时 query 也切词
# 这样原文存 content (给 LLM 看 · 不带空格) · 切词版存 content_tok (给 FTS5 索引)
try:
    import jieba
    jieba.setLogLevel(logging.WARNING)  # 不打 jieba 自己的 build dict log
    _JIEBA_AVAILABLE = True
except ImportError:
    _JIEBA_AVAILABLE = False
    logger.warning("jieba 未装 · 中文 FTS5 搜索退化到 unicode61 · 中文 query 会 0 命中。 pip install jieba 即可")


def _tokenize_for_index(text: str) -> str:
    """写入索引用 · 把文本切词 join ' ' · 让 FTS5 能按词匹配。

    jieba.cut(cut_all=False) = 精确模式 · 切出最长成词
    英文 / 数字 jieba 不动 · 跟原始空格分词等价
    """
    if not _JIEBA_AVAILABLE:
        return text
    if not text:
        return ""
    # cut 返 generator · join space · jieba 自动跳过 None / 空串
    return " ".join(w for w in jieba.cut(text, cut_all=False) if w and w.strip())


_FTS5_SAFE_RE = re.compile(r"^[\w\u4e00-\u9fff]+$")  # 允许字母数字下划线 + CJK · 拒所有 FTS5 操作符
# FTS5 reserved words · 用户 query 里可能有 (BRO 写"X OR Y") · 切完会变成连续 OR OR 触发 syntax error
_FTS5_RESERVED = {"OR", "AND", "NOT", "NEAR"}


def _tokenize_for_query(query: str) -> str:
    """search 用 · 切 query 后去重 + 过滤操作符 + 用 OR 连。

    case 1: 用户 query 含 OR (BRO 习惯 'X OR Y OR Z') · 切完会有连续 OR token → 必须去掉
    case 2: 'hermes-agent' 切完是 'hermes - agent' · '-' 是 FTS5 操作符 → 过滤
    case 3: 去重 · 同词出现多次没必要 (jieba 切 '工作模式 工作节奏' 会有 '工作' 两次)
    """
    if not _JIEBA_AVAILABLE:
        return query
    if not query:
        return ""
    raw = [w.strip() for w in jieba.cut_for_search(query) if w and w.strip()]
    seen = set()
    safe = []
    for w in raw:
        if w.upper() in _FTS5_RESERVED:
            continue  # 去 'OR'/'AND'/'NOT'/'NEAR' (含小写)
        if not _FTS5_SAFE_RE.match(w):
            continue  # 去 FTS5 操作符 (- + ( ) : 等)
        if w in seen:
            continue
        seen.add(w)
        safe.append(w)
    if not safe:
        return '"' + query.replace('"', '""') + '"'
    return " OR ".join(safe)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "memory_index.db"

SOUL_DIR = ROOT / "soul"
SESSIONS_DIR = ROOT / "sessions"
PLAYBOOKS_DIR = ROOT / "data" / "playbooks"

# ---- 切块参数 ----
MAX_CHUNK_CHARS = 2000       # 单块上限（超出按段落边界切）
TOKEN_ESTIMATE_DIVISOR = 3.5  # 英文 4、中文 1.5，3.5 是混合折衷


def _estimate_tokens(text: str) -> int:
    """粗略 token 估算 · 不做精确分词。"""
    return max(1, int(len(text) / TOKEN_ESTIMATE_DIVISOR))


def _summary_entry_text(entry: dict) -> str:
    """把一条 .summary.json 压缩记录拼成可索引文本 (摘要正文 + 关键事实)。

    卷五十八续 · 接通血管: 摘要是对话的高信号蒸馏·比原始 turn 更值得召回。
    """
    summary = (entry.get("summary") or "").strip()
    facts = entry.get("key_facts") or []
    parts: list[str] = []
    if summary:
        parts.append(summary)
    if isinstance(facts, list) and facts:
        parts.append("关键事实: " + " · ".join(str(f) for f in facts if f))
    return "\n".join(parts).strip()


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class MemoryChunk:
    id: int = -1
    source: str = ""
    section: str = ""
    chunk_index: int = 0
    content: str = ""
    token_count: int = 0
    updated_at: str = ""


# ---------------------------------------------------------------------------
# 建表
# ---------------------------------------------------------------------------


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """建实体表 + FTS5 索引 (独立 · 存切词版)。

    卷四十六 II · wish-43f705b8 · jieba tokenizer:
    - memory_chunks · 存原文 (给 LLM 看 · 不带空格)
    - memory_fts · 独立 standalone FTS5 (不再 external content) · 存 content_tok = jieba 切词版
      rowid = memory_chunks.id · search 时 JOIN chunks 取原文

    为什么不用 external content + 同步: external content + 改 content_tok 要双写 · 复杂。
    standalone 简单 · search 时 JOIN 一次 chunks 拿原文 · 一样快。
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            section TEXT DEFAULT '',
            chunk_index INTEGER DEFAULT 0,
            content TEXT NOT NULL,
            token_count INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT ''
        )
    """)
    # standalone FTS5 · 不是 external content · content_tok 是 jieba 切词后版
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
            content_tok,
            source,
            section
        )
    """)
    conn.commit()


def _drop_tables(conn: sqlite3.Connection) -> None:
    """删旧表（重建前调用）。"""
    conn.execute("DROP TABLE IF EXISTS memory_fts")
    conn.execute("DROP TABLE IF EXISTS memory_chunks")
    conn.commit()


def _insert_chunk_with_fts(
    conn: sqlite3.Connection,
    *,
    source: str,
    section: str,
    chunk_index: int,
    content: str,
    token_count: int,
    updated_at: str,
) -> int:
    """插一条 chunk 到 chunks 表 + 同步 jieba 切词版到 fts。 返新 chunk id。"""
    cur = conn.execute(
        "INSERT INTO memory_chunks (source, section, chunk_index, content, token_count, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (source, section, chunk_index, content, token_count, updated_at),
    )
    new_id = cur.lastrowid
    content_tok = _tokenize_for_index(content)
    conn.execute(
        "INSERT INTO memory_fts(rowid, content_tok, source, section) VALUES (?, ?, ?, ?)",
        (new_id, content_tok, source, section),
    )
    return new_id


# ---------------------------------------------------------------------------
# 分块
# ---------------------------------------------------------------------------


def _chunk_markdown(text: str, source: str, updated_at: str) -> list[dict]:
    """按 ## 标题分块，超 MAX_CHUNK_CHARS 的再按段落切。"""
    blocks = re.split(r"\n(?=## )", text)

    chunks: list[dict] = []
    section = ""

    for block in blocks:
        m = re.match(r"^##\s+(.+)", block)
        if m:
            section = m.group(1).strip()

        if len(block) <= MAX_CHUNK_CHARS:
            chunks.append({
                "source": source,
                "section": section,
                "chunk_index": len(chunks),
                "content": block.strip(),
                "token_count": _estimate_tokens(block),
                "updated_at": updated_at,
            })
        else:
            paragraphs = block.split("\n\n")
            sub_chunk = ""
            for para in paragraphs:
                if len(sub_chunk) + len(para) + 2 <= MAX_CHUNK_CHARS:
                    sub_chunk += ("\n\n" + para) if sub_chunk else para
                else:
                    if sub_chunk:
                        chunks.append({
                            "source": source,
                            "section": section,
                            "chunk_index": len(chunks),
                            "content": sub_chunk.strip(),
                            "token_count": _estimate_tokens(sub_chunk),
                            "updated_at": updated_at,
                        })
                    sub_chunk = para
            if sub_chunk:
                chunks.append({
                    "source": source,
                    "section": section,
                    "chunk_index": len(chunks),
                    "content": sub_chunk.strip(),
                    "token_count": _estimate_tokens(sub_chunk),
                    "updated_at": updated_at,
                })

    return chunks


# ---------------------------------------------------------------------------
# 核心操作
# ---------------------------------------------------------------------------


def _get_conn() -> sqlite3.Connection:
    """获取可写连接 · 自动建表。"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    _ensure_tables(conn)
    return conn


def rebuild() -> int:
    """全量重建索引：清空旧表 → 逐文件索引 → INSERT 实体表 → rebuild FTS。

    修复：不再手动 DELETE/INSERT memory_fts（外部内容表不允许）；
    改为 `INSERT INTO memory_fts(memory_fts) VALUES('rebuild')` 一键同步。

    Returns: 写入的 chunk 总数。
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 如果 db 已存在且损坏——直接删掉重来
    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(str(DB_PATH))
            conn.execute("SELECT COUNT(*) FROM memory_chunks").fetchone()
            conn.close()
        except sqlite3.DatabaseError:
            logger.warning("db 损坏，删除重建")
            DB_PATH.unlink()

    conn = _get_conn()
    _drop_tables(conn)
    _ensure_tables(conn)

    total = 0

    # ---- 索引 soul/ 下的 md 文件 ----
    soul_files = [
        ("OWNER-NOTEBOOK.md", "OWNER-NOTEBOOK"),
        ("BRO-NOTEBOOK.md", "BRO-NOTEBOOK"),
        ("SELF-EVOLUTION.md", "SELF-EVOLUTION"),
        ("OPUS-MEMORIES.md", "OPUS-MEMORIES"),
        ("SKILL.md", "SKILL"),
    ]
    for filename, source_label in soul_files:
        path = SOUL_DIR / filename
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        chunks = _chunk_markdown(text, source_label, now)
        for c in chunks:
            _insert_chunk_with_fts(
                conn,
                source=c["source"],
                section=c["section"],
                chunk_index=c["chunk_index"],
                content=c["content"],
                token_count=c["token_count"],
                updated_at=c["updated_at"],
            )
        total += len(chunks)
        logger.info("  索引 %s: %d chunks", source_label, len(chunks))

    # ---- 索引 playbooks (卷四十六 II · wish-1c229865 · skill 主动召回) ----
    if PLAYBOOKS_DIR.exists():
        pb_files = sorted(PLAYBOOKS_DIR.glob("*.md"))
        for pb in pb_files:
            try:
                pb_text = pb.read_text(encoding="utf-8")
                task_type = "general"
                try:
                    idx_path = PLAYBOOKS_DIR / "_index.json"
                    if idx_path.exists():
                        idx_data = json.loads(idx_path.read_text(encoding="utf-8"))
                        for pid, meta in idx_data.get("playbooks", {}).items():
                            if meta.get("slug") == pb.stem:
                                task_type = meta.get("task_type", "general")
                                break
                except Exception:
                    pass
                _insert_chunk_with_fts(
                    conn,
                    source="skill",
                    section=f"{pb.stem}:{task_type}",
                    chunk_index=0,
                    content=pb_text,
                    token_count=_estimate_tokens(pb_text),
                    updated_at=datetime.fromtimestamp(pb.stat().st_mtime, timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                )
                total += 1
            except Exception as e:
                logger.warning("索引 playbook %s 失败: %s", pb.name, e)

    # ---- 索引 sessions/ 下的 jsonl ----
    if SESSIONS_DIR.exists():
        session_files = sorted(SESSIONS_DIR.glob("*.jsonl"))
        for sf in session_files:
            try:
                with open(sf, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        content = record.get("content", "")
                        role = record.get("role", "")
                        ts = record.get("ts", "")
                        text = f"[{role}] {content}" if role else content
                        _insert_chunk_with_fts(
                            conn,
                            source="session",
                            section=f"{sf.stem}:{role}",
                            chunk_index=0,
                            content=text,
                            token_count=_estimate_tokens(text),
                            updated_at=ts or now,
                        )
                        total += 1
            except Exception as e:
                logger.warning("索引 session 文件 %s 时出错: %s", sf.name, e)

    # ---- 索引 sessions/ 下的 .summary.json (卷五十八续 · 接通血管) ----
    # auto_compress 早就在生成压缩摘要·只是从没流进召回。 摘要是高信号蒸馏·
    # 作为独立源 session_summary 入索引·scope=sessions/all 都能召回。
    if SESSIONS_DIR.exists():
        for sf in sorted(SESSIONS_DIR.glob("*.summary.json")):
            sid = sf.name[: -len(".summary.json")]
            try:
                entries = json.loads(sf.read_text(encoding="utf-8")) or []
                if not isinstance(entries, list):
                    continue
                for i, entry in enumerate(entries):
                    if not isinstance(entry, dict):
                        continue
                    text = _summary_entry_text(entry)
                    if not text:
                        continue
                    _insert_chunk_with_fts(
                        conn,
                        source="session_summary",
                        section=f"{sid}:summary#{i}",
                        chunk_index=i,
                        content=text,
                        token_count=_estimate_tokens(text),
                        updated_at=entry.get("compressed_at") or now,
                    )
                    total += 1
            except Exception as e:
                logger.warning("索引 summary 文件 %s 时出错: %s", sf.name, e)

    conn.commit()
    conn.close()

    logger.info("全量重建完成: %d chunks · jieba=%s", total, _JIEBA_AVAILABLE)
    return total


def incremental_update(source: str, full_text: str) -> int:
    """增量更新单个源：删旧 chunks + 删旧 fts → 重新分块插入 (含 fts 同步)。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = _get_conn()

    # 删旧 chunks 时同步删 fts 里对应 rowid (standalone fts 不会自动删)
    old_ids = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM memory_chunks WHERE source = ?", (source,)
        ).fetchall()
    ]
    if old_ids:
        placeholders = ",".join("?" * len(old_ids))
        conn.execute(f"DELETE FROM memory_fts WHERE rowid IN ({placeholders})", old_ids)
        conn.execute("DELETE FROM memory_chunks WHERE source = ?", (source,))

    chunks = _chunk_markdown(full_text, source, now)
    for c in chunks:
        _insert_chunk_with_fts(
            conn,
            source=c["source"],
            section=c["section"],
            chunk_index=c["chunk_index"],
            content=c["content"],
            token_count=c["token_count"],
            updated_at=c["updated_at"],
        )

    conn.commit()
    conn.close()

    logger.info("增量更新 %s: %d chunks", source, len(chunks))
    return len(chunks)


def index_session_turn(session_id: str, role: str, content: str, ts: str = "") -> bool:
    """卷五十四 · 单 turn 即时增量进 FTS5 (Hermes '搜自己的历史对话' 那一环)。

    病根 (断链 G): append_turn 没 hook · 新对话要等 check_stale 触发全量 rebuild 才可搜 ·
    "记得上次聊啥"靠运气。 现在每条 user/assistant turn 写盘后顺手插一条 fts chunk。

    只索引对话实质 (user / assistant) · 过滤工具调用/结果噪音。 单条 chunk · 不删旧 ·
    全量 rebuild 会先 drop 再扫 jsonl · 所以不会和这里累积重复。 best-effort · 失败静默。
    返回是否真索引了。
    """
    if role not in ("user", "assistant"):
        return False
    if not content or not content.strip():
        return False
    try:
        now = ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        text = f"[{role}] {content}"
        if len(text) > MAX_CHUNK_CHARS:
            text = text[:MAX_CHUNK_CHARS]
        conn = _get_conn()
        _insert_chunk_with_fts(
            conn,
            source="session",
            section=f"{session_id}:{role}",
            chunk_index=0,
            content=text,
            token_count=_estimate_tokens(text),
            updated_at=now,
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def index_session_summary(
    session_id: str,
    summary: str,
    key_facts: list[str] | None = None,
    ts: str = "",
) -> bool:
    """卷五十八续 · 接通血管: auto_compress 写完摘要即把它推进 FTS5 召回索引。

    病根: memory_compression 早就在生成 sessions/{sid}.summary.json · 但 rebuild 只 glob
    *.jsonl · 摘要从没进召回 ("记得上次聊啥的蒸馏版"靠下次全量 rebuild 才出现)。 现在压缩
    落盘后顺手插一条 session_summary chunk · recall_memory(scope=sessions/all) 立刻能召回。

    append-only · best-effort (与 index_session_turn 一致) · 全量 rebuild 会 drop 重扫
    .summary.json 做权威重建·不会累积重复。 返回是否真索引了。
    """
    text = _summary_entry_text({"summary": summary, "key_facts": key_facts or []})
    if not text:
        return False
    try:
        now = ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if len(text) > MAX_CHUNK_CHARS:
            text = text[:MAX_CHUNK_CHARS]
        conn = _get_conn()
        _insert_chunk_with_fts(
            conn,
            source="session_summary",
            section=f"{session_id}:summary",
            chunk_index=0,
            content=text,
            token_count=_estimate_tokens(text),
            updated_at=now,
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def load_recent_summaries(max_chars: int = 4000, max_sessions: int = 12) -> str:
    """读最近 N 个 session 的压缩摘要 · 拼成带 session id + 日期的可读文本。

    卷五十八续 VI · 接通桥: capability_mirror / review 此前只看收藏/雷达/outcomes
    这些"点击痕迹"·看不到你们真正聊过、决定过、卡过的事。 这个口子把 Layer0 的
    对话摘要(高信号蒸馏)喂上去·让镜子照得见对话的影子。

    每个 session 取最后一条摘要(最新一次压缩)·按 mtime 倒序·总长截到 max_chars。
    带 [会话 sid · 日期] 前缀·让 LLM 能 cite 真实来源(不发明信源 · 卷三十二第 5 条)。
    全只读 · 失败返提示串(不抛)。
    """
    if not SESSIONS_DIR.exists():
        return "（暂无对话摘要 · sessions/ 不存在）"

    files = sorted(
        SESSIONS_DIR.glob("*.summary.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:max_sessions]
    if not files:
        return "（暂无对话摘要 · 还没触发过自动压缩）"

    blocks: list[str] = []
    used = 0
    for sf in files:
        sid = sf.name[: -len(".summary.json")]
        try:
            entries = json.loads(sf.read_text(encoding="utf-8")) or []
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(entries, list) or not entries:
            continue
        last = entries[-1]
        if not isinstance(last, dict):
            continue
        text = _summary_entry_text(last)
        if not text:
            continue
        when = last.get("compressed_at") or datetime.fromtimestamp(
            sf.stat().st_mtime, timezone.utc
        ).strftime("%Y-%m-%d")
        block = f"[会话 {sid} · {when}]\n{text}"
        if used + len(block) > max_chars:
            remain = max_chars - used
            if remain > 80:
                blocks.append(block[:remain] + " …")
            break
        blocks.append(block)
        used += len(block) + 2

    if not blocks:
        return "（暂无可用对话摘要）"
    return "\n\n".join(blocks)


def check_stale() -> bool:
    """检查索引是否过期（db 不存在 或 源文件 mtime > db mtime）。

    Returns: True 表示需要重建。
    """
    if not DB_PATH.exists():
        return True

    db_mtime = DB_PATH.stat().st_mtime

    soul_files = ["OWNER-NOTEBOOK.md", "BRO-NOTEBOOK.md", "SELF-EVOLUTION.md", "OPUS-MEMORIES.md", "SKILL.md"]
    for fn in soul_files:
        p = SOUL_DIR / fn
        if p.exists() and p.stat().st_mtime > db_mtime:
            logger.info("索引过期: %s 有新修改", fn)
            return True

    if SESSIONS_DIR.exists():
        for sf in SESSIONS_DIR.glob("*.jsonl"):
            if sf.stat().st_mtime > db_mtime:
                logger.info("索引过期: sessions/%s 有新文件", sf.name)
                return True
        # 卷五十八续 · 接通血管: 摘要更新也算过期 (auto_compress 重新压缩会刷新 .summary.json)
        for sf in SESSIONS_DIR.glob("*.summary.json"):
            if sf.stat().st_mtime > db_mtime:
                logger.info("索引过期: sessions/%s 摘要有更新", sf.name)
                return True

    # 卷四十六 II · wish-1c229865 · playbooks 也参与 stale 检测
    if PLAYBOOKS_DIR.exists():
        for pb in PLAYBOOKS_DIR.glob("*.md"):
            if pb.stat().st_mtime > db_mtime:
                logger.info("索引过期: playbooks/%s 有新修改", pb.name)
                return True

    return False


def search(
    query: str,
    top_k: int = 5,
    scope: str = "all",
    context_window: int = 8000,
) -> list[MemoryChunk]:
    """FTS5 全文检索。

    Args:
        query: 搜索关键词
        top_k: 返回条数 (1-20)
        scope: 'all' | 'bro' | 'self' | 'sessions'
        context_window: 总内容上限 (chars)，超出截断

    Returns:
        按 BM25 排名的 MemoryChunk 列表
    """
    top_k = max(1, min(top_k, 20))

    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    # 卷四十六 II · wish-43f705b8 jieba tokenizer · 修中文 0 命中
    # 切 query (jieba.cut_for_search) → " OR " 连接 · 任一词命中即算 hit
    # 切完是 "工作 OR 模式 OR 工作模式" 这种形式 · FTS5 能用 BM25 排序
    fts_query = _tokenize_for_query(query)
    if not fts_query.strip():
        conn.close()
        return []

    scope_filter_c = ""
    if scope == "bro":
        scope_filter_c = "AND c.source = 'BRO-NOTEBOOK'"
    elif scope == "self":
        scope_filter_c = "AND c.source IN ('SELF-EVOLUTION', 'OPUS-MEMORIES', 'SKILL')"
    elif scope == "sessions":
        # 卷五十八续 · 接通血管: sessions 既含原始 turn·也含蒸馏摘要
        scope_filter_c = "AND c.source IN ('session', 'session_summary')"
    elif scope == "skill":
        scope_filter_c = "AND c.source = 'skill'"

    try:
        rows = conn.execute(
            f"SELECT memory_fts.rowid, c.source, c.section, c.chunk_index, "
            f"       c.content, c.token_count, c.updated_at "
            f"FROM memory_fts "
            f"JOIN memory_chunks c ON memory_fts.rowid = c.id "
            f"WHERE memory_fts MATCH ? {scope_filter_c} "
            f"ORDER BY memory_fts.rank LIMIT ?",
            (fts_query, top_k),
        ).fetchall()
    except sqlite3.OperationalError as e:
        logger.warning("FTS5 search failed (%s) · 退化 LIKE · 用原 query", e)
        try:
            like_sql = f"""
                SELECT c.id, c.source, c.section, c.chunk_index, c.content,
                       c.token_count, c.updated_at
                FROM memory_chunks c
                WHERE c.content LIKE ? {scope_filter_c}
                ORDER BY c.id DESC
                LIMIT ?
            """
            rows = conn.execute(like_sql, (f"%{query}%", top_k)).fetchall()
        except sqlite3.OperationalError:
            conn.close()
            return []

    results: list[MemoryChunk] = []
    total_chars = 0

    for row in rows:
        chunk = MemoryChunk(
            id=row[0],
            source=row[1],
            section=row[2],
            chunk_index=row[3],
            content=row[4],
            token_count=row[5],
            updated_at=row[6],
        )
        if total_chars + len(chunk.content) > context_window:
            chunk.content = chunk.content[: context_window - total_chars] + "..."
            results.append(chunk)
            break
        results.append(chunk)
        total_chars += len(chunk.content)

    conn.close()
    return results


def get_stats() -> dict:
    """返回当前索引统计。"""
    if not DB_PATH.exists():
        return {"db_path": str(DB_PATH), "total_chunks": 0, "by_source": [], "error": "db 不存在"}

    try:
        conn = sqlite3.connect(str(DB_PATH))
        total = conn.execute("SELECT COUNT(*) FROM memory_chunks").fetchone()[0]
        by_source = conn.execute(
            "SELECT source, COUNT(*), SUM(token_count) FROM memory_chunks GROUP BY source ORDER BY 2 DESC"
        ).fetchall()
        conn.close()
    except sqlite3.DatabaseError as e:
        return {"db_path": str(DB_PATH), "total_chunks": 0, "by_source": [], "error": str(e)}

    return {
        "db_path": str(DB_PATH),
        "total_chunks": total,
        "by_source": [
            {"source": s, "chunks": c, "tokens": t or 0} for s, c, t in by_source
        ],
    }


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

    if "--rebuild" in sys.argv:
        n = rebuild()
        print(f"重建完成: {n} chunks")
    elif "--search" in sys.argv:
        idx = sys.argv.index("--search")
        q = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        if not q:
            print("用法: --search \"关键词\"")
            sys.exit(1)
        results = search(q, top_k=5)
        for i, chunk in enumerate(results, 1):
            print(f"\n--- {i}. [{chunk.source}] {chunk.section[:40]} ---")
            print(chunk.content[:300])
    elif "--stats" in sys.argv:
        import json as _json
        print(_json.dumps(get_stats(), indent=2, ensure_ascii=False))
    else:
        print("用法: python -m workers.memory_index [--rebuild | --search \"query\" | --stats]")
