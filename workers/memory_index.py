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


# 0.8.9 · 查询停用词 (虚词/语气词/代词/高频介词) · 防污染 bm25 排名
# 根因: "压缩后细节丢了" 切出 "后/了" 让只含停用词的 chunk 排名虚高 → 真命中被挤出阈值
_QUERY_STOPWORDS = {
    "后", "了", "的", "是", "我", "你", "他", "她", "它", "我们", "你们", "他们",
    "吗", "呢", "吧", "啊", "呀", "哦", "嗯", "怎么", "什么", "为啥", "为什么",
    "如何", "怎样", "咋", "在", "有", "就", "都", "和", "与", "及", "这", "那",
    "个", "把", "被", "让", "用", "可以", "能", "会", "要", "想", "请", "帮",
    "一下", "一个", "这个", "那个", "这些", "那些", "对", "给", "向", "从", "到",
}

# 0.8.9 · 中英/同义映射 (用户口语词 → 技术词) · 治词面不重合漏召回
# 例: "git 提交卡住了" 切出 "提交" → 扩成 "commit" · 命中 "daemon-工程-commit-超时" playbook
_QUERY_SYNONYMS = {
    "提交": ["commit"], "卡住": ["commit"], "卡": ["commit"],
    "报错": ["error"], "出错": ["error"], "错误": ["error"],
    "发布": ["release"], "发版": ["release"], "上线": ["release"],
    "缓存": ["cache"], "压缩": ["compact"],
    "下载": ["download"], "视频": ["video"],
    "生图": ["image"], "出图": ["image"], "画图": ["image"],
    "前端": ["frontend", "ui"], "界面": ["ui"], "页面": ["ui"],
    "换行": ["linebreak"], "乱码": ["encoding"], "编码": ["encoding"],
    "重启": ["restart"], "崩溃": ["crash"], "假死": ["hang"],
    # wish-fec0e2f6 实测补: 中英混排时 jieba 把"飞书"切成"飞"+"书" (cut_for_search HMM 猜词失败)
    # → 显式加自定义词 + 同义词映射 · "飞书"在消息里永远切为完整词 · 不再碎成单字
    "飞书": ["feishu", "lark"], "群聊": ["group"],
}

# wish-fec0e2f6 · 自定义词典: 让 jieba 把专有名词当完整词切 · 治中英混排猜词失败
# ("验证飞书 0.9.0 BETA" → 无此表时切 '飞'+'书' · 有则切 '飞书')
if _JIEBA_AVAILABLE:
    try:
        for _word in ("飞书", "daemonkey", "Daemonkey", "playbook", "webui", "WebUI", "gitee", "Gitee", "github", "GitHub"):
            jieba.add_word(_word)
    except Exception:
        pass


def _tokenize_for_query(query: str) -> str:
    """search 用 · 切 query 后去重 + 过滤操作符 + 用 OR 连。

    case 1: 用户 query 含 OR (BRO 习惯 'X OR Y OR Z') · 切完会有连续 OR token → 必须去掉
    case 2: 'hermes-agent' 切完是 'hermes - agent' · '-' 是 FTS5 操作符 → 过滤
    case 3: 去重 · 同词出现多次没必要 (jieba 切 '工作模式 工作节奏' 会有 '工作' 两次)
    case 4 (0.8.9): 停用词过滤 (虚词污染 bm25 排名) + 中英同义词扩展 (词面不重合漏召回)
    case 5 (wish-6ff9d89b · C1): 显式 FTS5 语法透传 — query 含 FTS5 操作符
        (AND/OR/NOT/NEAR/引号短语/前缀*/括号分组/排除-) 时·不再拆成宽松 OR·
        原样交给 FTS5 原生解析·让 SPEC 承诺的 AND/NOT/"短语"/前缀 语法真实生效。
        纯自然语言 (无操作符) 才走上面的宽松 OR 分词 (记忆检索的实际用法)。
        注意: 中文 query 透传时 FTS5 按索引词 (jieba 切过的) 匹配·短语/排除对中文
        词同样有效 (索引时已分词·FTS5 在 token 序列上做邻接/排除)。
    """
    if not query:
        return ""
    # M5 (wish-6ff9d89b) · 超长 query 防御: >500 字截断 (防 jieba 切 5000 字全丢成空 / 烧时间)
    if len(query) > 500:
        query = query[:500]
    # C1 · 显式 FTS5 语法检测: 引号短语 / 大写操作符 / 前缀* / 括号分组 / 排除-
    _has_fts_syntax = (
        '"' in query
        or re.search(r"\b(AND|OR|NOT|NEAR)\b", query, re.IGNORECASE) is not None
        or "*" in query
        or "(" in query or ")" in query
        or re.search(r"(^|\s)-[\w\u4e00-\u9fff]", query) is not None
    )
    if _has_fts_syntax:
        # C1 · 透传前做安全清洗 (wish-6ff9d89b):
        #   FTS5 query 层排除符 (-) 有语法限制 (单独 -X 或 * -X 都不合法)。
        #   'NOT 缓存' → 这里只标记出排除词·真排除在 search 的 SQL 层做
        #   (WHERE ... AND c.content NOT LIKE '%缓存%') · 因为 FTS5 MATCH 是"找出匹配"·
        #   "排除"是 SQL 层语义。见 search() 的 _exclude 处理。
        return query
    if not _JIEBA_AVAILABLE:
        return query
    raw = [w.strip() for w in jieba.cut_for_search(query) if w and w.strip()]
    seen = set()
    safe = []
    for w in raw:
        w_low = w.lower()
        # 停用词 (虚词/语气词) · 只含它们的 chunk 不该参与排名
        if w in _QUERY_STOPWORDS or w_low in _QUERY_STOPWORDS:
            continue
        # 单字符碎片全滤 (wish-fec0e2f6 实测同根因): 中英混排时 jieba 把"飞书"切成"飞"+"书" ·
        # "验证飞书 0.9.0 BETA" → 单字"飞/书/新/上"污染 FTS5 候选池 (top_k=4 被噪音占位·真 playbook 挤不进)
        # 英文单字 (a/i) / 数字单字 (0/9) 同样滤 · 只有多字符 token 才有语义
        if len(w) == 1:
            continue
        if w.upper() in _FTS5_RESERVED:
            continue  # 去 'OR'/'AND'/'NOT'/'NEAR' (含小写)
        if not _FTS5_SAFE_RE.match(w):
            continue  # 去 FTS5 操作符 (- + ( ) : 等)
        if w in seen:
            continue
        seen.add(w)
        safe.append(w)
        # 同义词扩展 (中英映射 · 词面不重合时救召回)
        for syn in _QUERY_SYNONYMS.get(w, []):
            if syn not in seen:
                seen.add(syn)
                safe.append(syn)
    if not safe:
        # wish-189cab52 (墨言模块 8) · 纯停用词 query 归零修复。
        # 原逻辑: return '"<query>"' 当短语 → 但索引侧 jieba 把 '怎么了' 切成 '怎么'+'了'
        # 两个 token · FTS5 里根本没有 '怎么了' 连续 token → 短语必然 0 命中。
        # 修法: 回退宽松 OR (不过滤停用词) · 用 jieba 切出的原始词 (含虚词) OR 连 →
        # '怎么'/'了' 能分别命中 → 纯虚词查询不再静默归零。
        # 注意: 这是"尽力召回"兜底 · 停用词仍留在 _QUERY_STOPWORDS 正常路径过滤·
        # 只有 query 全是停用词时才走到这 (正常查询不受影响)。
        fallback = [w.strip() for w in jieba.cut_for_search(query) if w and w.strip()]
        fallback = list(dict.fromkeys(fallback))  # 去重保序
        if fallback:
            return " OR ".join(fallback)
        return query
    return " OR ".join(safe)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "memory_index.db"


def _query_real_terms(query: str) -> list[str]:
    """wish-fec0e2f6 (墨言 03 · 自研) · 返回 query 的实词列表 (jieba 精确切 + 停用词/泛词过滤 + 同义词展开)。

    跟 _tokenize_for_query 同源 (同一套 jieba + 停用词 + 同义词) · 但返回词数组而非 OR 串:
    - 供 _overlap_count 做"实词重叠闸" (min_overlap=2) — overlap 比 bm25 更可靠的语义信号
    - 供 _has_retrieval_intent 判断"消息有没有可检索的主题词" (纯应答/语气词滤光 → 空列表 → 不检索)
    - 供 _PB_GENERIC_WORDS 泛词剔除 (应用/做/帮我 不参与检索)
    切词故障 → 返回空列表 (调用侧 fail-open: 意图门槛放行 · 重叠闸退化)
    """
    if not query:
        return []
    if len(query) > 500:
        query = query[:500]
    if not _JIEBA_AVAILABLE:
        # 无 jieba → 用空格分词兜底 (英文场景)
        return [w for w in query.replace(",", " ").split() if w.strip()][:20]
    raw = [w.strip() for w in jieba.cut_for_search(query) if w and w.strip()]
    seen: set[str] = set()
    terms: list[str] = []
    for w in raw:
        w_low = w.lower()
        if w in _QUERY_STOPWORDS or w_low in _QUERY_STOPWORDS:
            continue
        # 单字符碎片全滤 (wish-fec0e2f6 实测: 中英混排时 jieba 把"飞书"切成"飞"+"书"·
        # "验证飞书 0.9.0 BETA" → 单字"飞/书/新/上"污染 overlap 计数 → 真 playbook 被 min_overlap 挡掉)
        # 英文单字 (a/i) 也滤 · 数字单字 (0/9) 也滤 · 只有多字符 token 才有语义
        if len(w) == 1:
            continue
        if w.upper() in _FTS5_RESERVED:
            continue
        if not _FTS5_SAFE_RE.match(w):
            continue
        if w in seen:
            continue
        seen.add(w)
        terms.append(w)
        for syn in _QUERY_SYNONYMS.get(w, []):
            if syn not in seen:
                seen.add(syn)
                terms.append(syn)
    return terms


def _overlap_count(query_terms: list[str], text: str) -> int:
    """wish-fec0e2f6 (墨言 03 · 自研) · 实词重叠计数: query 实词里有多少个出现在 text 里。

    与检索闸同口径 (不去子串): "转化率提升" 切出 [转化率, 提升] · 两个都出现 = overlap 2。
    比 len(_hit_terms) 可靠: _hit_terms 去子串后 "转化率提升"→[转化率] 长度 1 · 会误标弱。
    """
    if not query_terms or not text:
        return 0
    t_low = text.lower()
    n = 0
    for t in query_terms:
        if t.lower() in t_low:
            n += 1
    return n

SOUL_DIR = ROOT / "soul"
SESSIONS_DIR = ROOT / "sessions"
PLAYBOOKS_DIR = ROOT / "data" / "playbooks"
# 私有文档知识库 (workers/knowledge_base.py 写入)· 直接读盘避免与 knowledge_base 循环导入
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"
KNOWLEDGE_DOCS_DIR = KNOWLEDGE_DIR / "docs"
KNOWLEDGE_MANIFEST = KNOWLEDGE_DIR / "manifest.json"

# 客户档案 notes (workers/clients.py 写入)· source = client:<id> · 让"客户档案=记忆延伸"
CLIENTS_MANIFEST = ROOT / "data" / "clients" / "manifest.json"

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


def _enabled_knowledge_docs() -> list[tuple[str, str]]:
    """读知识库 manifest · 返回 [(doc_id, 正文文本)] 只含 enabled 的文档。

    直接读盘 (不 import knowledge_base) · 避免与其循环导入。全只读 · 失败返 []。
    """
    if not KNOWLEDGE_MANIFEST.exists():
        return []
    try:
        manifest = json.loads(KNOWLEDGE_MANIFEST.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    docs = manifest.get("docs")
    if not isinstance(docs, dict):
        return []
    out: list[tuple[str, str]] = []
    for doc_id, meta in docs.items():
        if not isinstance(meta, dict) or not meta.get("enabled", True):
            continue
        md = KNOWLEDGE_DOCS_DIR / f"{doc_id}.md"
        if not md.exists():
            continue
        try:
            out.append((doc_id, md.read_text(encoding="utf-8")))
        except OSError:
            continue
    return out


def _client_notes() -> list[tuple[str, str]]:
    """读客户档案 manifest · 返回 [(client_id, name+notes 文本)] · 只含有 notes 的。

    直接读盘(不 import clients)· 避免循环导入。全只读 · 失败返 []。
    """
    if not CLIENTS_MANIFEST.exists():
        return []
    try:
        manifest = json.loads(CLIENTS_MANIFEST.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    clients = manifest.get("clients")
    if not isinstance(clients, dict):
        return []
    out: list[tuple[str, str]] = []
    for cid, meta in clients.items():
        if not isinstance(meta, dict):
            continue
        notes = (meta.get("notes") or "").strip()
        if not notes:
            continue
        body = f"客户档案 · {meta.get('name', '')}\n\n{notes}".strip()
        out.append((cid, body))
    return out


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
    # FTS5 bm25 排名分数 · 越负越相关 (0.0 = LIKE 退化路径无分数)。
    # 卷? · 自动注入靠它做相关性门槛 · 没分数门槛会每轮硬塞 top_k 噪音
    score: float = 0.0


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
    conn.execute("PRAGMA busy_timeout=30000")  # wish-93b0cabf 残留修复 · 连接都等锁不炸
    conn.execute("PRAGMA synchronous=NORMAL")
    # wish-93b0cabf 残留修复 (2026-08-10 BRO 报 database is locked) ·
    # 缺 busy_timeout = 默认 0 → 并发写一撞立刻抛 "database is locked" (rebuild 后台重建撞
    # 主对话写入) → 新 session 首次 load_soul 触发重建 → 挂起/空回复。
    # 加 30s 等待: WAL 下写写冲突排队而不是立即炸 · 30s 足够前一个写完成。
    conn.execute("PRAGMA busy_timeout=30000")
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

    # ---- 索引私有文档知识库 (data/knowledge · 只索引 enabled 的) ----
    # source = doc:<id> · recall_memory(scope='docs') 靠 LIKE 'doc:%' 召回
    for doc_id, text in _enabled_knowledge_docs():
        try:
            chunks = _chunk_markdown(text, f"doc:{doc_id}", now)
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
        except Exception as e:
            logger.warning("索引知识库文档 %s 失败: %s", doc_id, e)

    # ---- 索引客户档案 notes (data/clients) · source = client:<id> ----
    # recall_memory(scope='clients'/'all') 靠 LIKE 'client:%' 召回·让客户档案长在记忆里
    for cid, text in _client_notes():
        try:
            chunks = _chunk_markdown(text, f"client:{cid}", now)
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
        except Exception as e:
            logger.warning("索引客户档案 %s 失败: %s", cid, e)

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

    # 注意: sessions/*.jsonl + *.summary.json 不参与 stale 判定 (wish-93b0cabf · 2026-08-06)
    # 病根: session 每轮对话必写 → mtime 永远 > db → check_stale 永远 True →
    #       load_soul 每次都同步全量 rebuild (30-40s) → 阻塞事件循环 → 对话卡死。
    # session 内容的索引走 index_session_turn (611 行·每轮写盘即插 FTS) + index_session_summary·
    # 不需要全量重建来索引它们。灵魂/playbook/知识库/客户档案 (低频源) 仍走全量重建。

    # 卷四十六 II · wish-1c229865 · playbooks 也参与 stale 检测
    if PLAYBOOKS_DIR.exists():
        for pb in PLAYBOOKS_DIR.glob("*.md"):
            if pb.stat().st_mtime > db_mtime:
                logger.info("索引过期: playbooks/%s 有新修改", pb.name)
                return True

    # 知识库 manifest / 文档变动 (灌档 / 参考开关切换) 也算过期
    if KNOWLEDGE_MANIFEST.exists() and KNOWLEDGE_MANIFEST.stat().st_mtime > db_mtime:
        logger.info("索引过期: 知识库 manifest 有更新")
        return True
    if KNOWLEDGE_DOCS_DIR.exists():
        for md in KNOWLEDGE_DOCS_DIR.glob("*.md"):
            if md.stat().st_mtime > db_mtime:
                logger.info("索引过期: 知识库文档 %s 有更新", md.name)
                return True

    # 客户档案 notes 变动也算过期(建档/追加备注会刷新 manifest)
    if CLIENTS_MANIFEST.exists() and CLIENTS_MANIFEST.stat().st_mtime > db_mtime:
        logger.info("索引过期: 客户档案 manifest 有更新")
        return True

    return False


def search(
    query: str,
    top_k: int = 5,
    scope: str = "all",
    context_window: int = 8000,
    min_score: float | None = None,
    window_by: str = "content",
    min_overlap: int | None = None,
) -> list[MemoryChunk]:
    """FTS5 全文检索。

    Args:
        query: 搜索关键词
        top_k: 返回条数 (1-20)
        scope: 'all' | 'bro' | 'self' | 'sessions' | 'skill'
        context_window: 总内容上限 (chars)，超出截断
        min_score: bm25 相关性门槛 · 只留 score <= min_score 的块 (越负越相关)。
            None = 不过滤 (recall_memory 工具走高召回)。
            自动注入 (relevant_memories) 传一个负阈值·把弱命中挡在外面·防每轮塞噪音。
        window_by (wish-6ff9d89b · I1): 截断窗口口径。
            'content' (默认) = 按全文累计截断 (full 模式·取原文看细节)
            'snippet' = 按单条摘要 140 chars 截断·不累计 (list 模式·给摘要省 token·
                        不被全文窗口压制条数·top_k 多少就回多少摘要)
        min_overlap (wish-fec0e2f6 · 墨言 03 思路自研): 实词重叠闸。
            query 实词 (jieba 切 + 停用词/泛词滤 + 同义词) 里至少 N 个出现在 chunk 内容里才保留。
            overlap 比 bm25 更可靠的语义信号 — 防"单虚词/泛词撞标题"误召回 (min_score 放宽后的副作用)。
            None = 不过滤 (recall_memory 工具走高召回)。

    Returns:
        按 BM25 排名的 MemoryChunk 列表
    """
    top_k = max(1, min(top_k, 20))
    # M3 (wish-6ff9d89b) · context_window 无上限 → clamp 500-20000 (对齐 SPEC)
    context_window = max(500, min(int(context_window or 8000), 20000))

    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")  # wish-93b0cabf 残留修复 · 连接都等锁不炸

    # 卷四十六 II · wish-43f705b8 jieba tokenizer · 修中文 0 命中
    # 切 query (jieba.cut_for_search) → " OR " 连接 · 任一词命中即算 hit
    # 切完是 "工作 OR 模式 OR 工作模式" 这种形式 · FTS5 能用 BM25 排序
    # wish-189cab52 · 显式 FTS5 语法检测 (跟 _tokenize_for_query 内同款逻辑) ·
    # 供 MATCH 列限定判断: 显式语法透传路径不加列前缀 (语法会错) · 普通 OR 路径加。
    _has_fts_syntax = (
        '"' in query
        or re.search(r"\b(AND|OR|NOT|NEAR)\b", query, re.IGNORECASE) is not None
        or "*" in query
        or "(" in query or ")" in query
        or re.search(r"(^|\s)-[\w\u4e00-\u9fff]", query) is not None
    )
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
    elif scope == "docs":
        # 私有文档知识库 · 每篇 source = doc:<id>
        scope_filter_c = "AND c.source LIKE 'doc:%'"
    elif scope == "clients":
        # 客户档案 notes · 每个 source = client:<id>
        scope_filter_c = "AND c.source LIKE 'client:%'"

    # wish-6ff9d89b · C1: FTS5 的 NOT 排除语义转到 SQL 层实现。
    # FTS5 query 层 'NOT X' / 'A -B' 有语法限制 (单独排除不合法 · 中间 - 也易 syntax error) ·
    # 且 MATCH 是"找出匹配"·"排除"本质是 SQL 层 NOT LIKE。这里解析出排除词·
    # 生成 AND c.content NOT LIKE '%词%' (多词 AND 连) · 转义 LIKE 通配符 (M2)。
    exclude_terms: list[str] = []
    q_parse = query
    m_not = re.search(r"\bNOT\s+([\w\u4e00-\u9fff]+)", q_parse, re.IGNORECASE)
    if m_not:
        exclude_terms.append(m_not.group(1))
        # 从 query 里去掉 NOT 段 · 剩余当正向匹配
        q_parse = q_parse[:m_not.start()] + " " + q_parse[m_not.end():]
    # 也处理 'A -B' 形态 (FTS5 排除符)
    m_neg = re.findall(r"(?:^|\s)-([\w\u4e00-\u9fff]+)", q_parse)
    if m_neg:
        exclude_terms.extend(m_neg)
    if exclude_terms:
        for term in exclude_terms:
            _esc = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            scope_filter_c += f" AND c.content NOT LIKE '%{_esc}%' ESCAPE '\\'"
        # 去掉 query 里的 -B 排除段 (FTS5 query 层不处理了)
        q_parse = re.sub(r"(?:^|\s)-[\w\u4e00-\u9fff]+", " ", q_parse)
    if q_parse.strip():
        fts_query = _tokenize_for_query(q_parse.strip())
    else:
        # query 只剩排除词 (如 "NOT 缓存" 无正向词) → 不跑 FTS5 MATCH · 纯 NOT LIKE 全扫
        fts_query = ""

    has_score = True
    try:
        if fts_query:
            # wish-189cab52 (墨言模块 8) · MATCH 列限定。
            # FTS5 表 3 列 (content_tok/source/section) · 裸 MATCH 扫全列 → source/section
            # 元数据词 ('assistant'/'tool'/'session') 污染召回。列限定 'content_tok : q' 只扫正文。
            # 但显式语法透传 (C1 · NOT/AND/短语/前缀) 不能加列前缀 (语法会错) ·
            # 只在宽松 OR 普通路径加限定 · 显式语法本来就是用户精确意图·元数据污染风险低。
            if _has_fts_syntax:
                _match_expr = fts_query
            else:
                _match_expr = f"content_tok : {fts_query}"
            rows = conn.execute(
                f"SELECT memory_fts.rowid, c.source, c.section, c.chunk_index, "
                f"       c.content, c.token_count, c.updated_at, memory_fts.rank "
                f"FROM memory_fts "
                f"JOIN memory_chunks c ON memory_fts.rowid = c.id "
                f"WHERE memory_fts MATCH ? {scope_filter_c} "
                f"ORDER BY memory_fts.rank LIMIT ?",
                (_match_expr, top_k),
            ).fetchall()
        else:
            # 只剩排除词 (NOT 缓存 无正向词) → 跳过 MATCH · 纯 SQL NOT LIKE 全扫 (rank 无意义)
            rows = conn.execute(
                f"SELECT c.id, c.source, c.section, c.chunk_index, c.content, "
                f"       c.token_count, c.updated_at, 0.0 "
                f"FROM memory_chunks c "
                f"WHERE 1=1 {scope_filter_c} "
                f"ORDER BY c.id DESC LIMIT ?",
                (top_k,),
            ).fetchall()
    except sqlite3.OperationalError as e:
        logger.warning("FTS5 search failed (%s) · 退化 LIKE · 用原 query", e)
        has_score = False  # LIKE 路径没 bm25 分数 · min_score 过滤跳过
        try:
            # M2 (wish-6ff9d89b) · LIKE 通配符转义: query 含 % _ 会当通配符爆炸 → 转义字面量
            _like_q = q_parse.strip() or query  # 用排除后的 (不含 NOT 段)
            _like_esc = _like_q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like_sql = f"""
                SELECT c.id, c.source, c.section, c.chunk_index, c.content,
                       c.token_count, c.updated_at
                FROM memory_chunks c
                WHERE c.content LIKE ? ESCAPE '\\' {scope_filter_c}
                ORDER BY c.id DESC
                LIMIT ?
            """
            rows = conn.execute(like_sql, (f"%{_like_esc}%", top_k)).fetchall()
        except sqlite3.OperationalError:
            conn.close()
            return []

    results: list[MemoryChunk] = []
    total_chars = 0
    # wish-fec0e2f6 (墨言 03 思路自研) · 实词重叠闸: 检索前算一次 query 实词 ·
    # min_overlap=None (recall_memory 高召回) 不启用 · 自动注入传 2 (防单虚词/泛词撞标题)
    _ov_terms = _query_real_terms(query) if min_overlap else []

    for row in rows:
        score = float(row[7]) if has_score and len(row) > 7 else 0.0
        # min_score 门槛 · bm25 越负越相关 → score 比阈值大 (更接近 0) 说明太弱·丢掉。
        # LIKE 退化路径没分数·不过滤 (has_score=False)。
        if min_score is not None and has_score and score > min_score:
            continue
        # wish-fec0e2f6 · min_overlap 闸: query 实词里至少 N 个出现在 chunk 内容 (含 section) 才留
        # overlap 比 bm25 更可靠的语义信号 — bm25 对高频词天然低分 (记忆/系统/三审三修 IDF 低 ·
        # score -3 也强相关) · min_score 放宽后必须靠 overlap 挡"单词撞库"
        if min_overlap and _ov_terms:
            if _overlap_count(_ov_terms, (row[4] or "") + " " + (row[2] or "")) < min_overlap:
                continue
        chunk = MemoryChunk(
            id=row[0],
            source=row[1],
            section=row[2],
            chunk_index=row[3],
            content=row[4],
            token_count=row[5],
            updated_at=row[6],
            score=score,
        )
        if window_by == "snippet":
            # I1 (wish-6ff9d89b) · list 模式: 每块只留 140 chars 摘要 · 不累计
            # (不被全文窗口压制条数 · top_k 多少就回多少摘要)
            if len(chunk.content) > 140:
                chunk.content = chunk.content[:139] + "…"
            results.append(chunk)
        else:
            # 默认 full 模式: 按全文累计截断 · 超出 break (保留前面的完整块)
            if total_chars + len(chunk.content) > context_window:
                chunk.content = chunk.content[: max(0, context_window - total_chars)] + "…"
                results.append(chunk)
                break
            results.append(chunk)
            total_chars += len(chunk.content)

    conn.close()
    return results


def get_chunks_by_ids(ids: list[int], context_window: int = 8000) -> list[MemoryChunk]:
    """按 chunk id 批量取全文 · 给 recall_memory 两段式的 fetch 阶段用。

    第一阶段 (mode=list) 返回 id + 摘要让 OPUS 挑·这里按挑中的 id 取原文。
    保持入参 ids 的顺序返回 (OPUS 挑的优先级)·超 context_window 截断尾部。
    wish-6ff9d89b · I3: 默认 8000 对齐 SPEC (原 12000 文档-行为不一致) · 截断加提示。
    """
    if not ids:
        return []
    if not DB_PATH.exists():
        return []

    safe_ids = [int(i) for i in ids if str(i).strip().lstrip("-").isdigit()][:20]
    if not safe_ids:
        return []

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")  # wish-93b0cabf 残留修复 · 连接都等锁不炸
    placeholders = ",".join("?" for _ in safe_ids)
    try:
        rows = conn.execute(
            f"SELECT id, source, section, chunk_index, content, token_count, updated_at "
            f"FROM memory_chunks WHERE id IN ({placeholders})",
            safe_ids,
        ).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return []
    conn.close()

    by_id = {row[0]: row for row in rows}
    results: list[MemoryChunk] = []
    total_chars = 0
    for cid in safe_ids:
        row = by_id.get(cid)
        if row is None:
            continue
        chunk = MemoryChunk(
            id=row[0], source=row[1], section=row[2], chunk_index=row[3],
            content=row[4], token_count=row[5], updated_at=row[6],
        )
        if total_chars + len(chunk.content) > context_window:
            # I3 (wish-6ff9d89b) · 截断加明确提示 (不只 ...) · 让 OPUS 知道这是截断版不是全文
            _room = max(0, context_window - total_chars)
            _truncated = len(chunk.content) - _room
            chunk.content = chunk.content[:_room] + f"\n…[截断 {_truncated} 字符]"
            results.append(chunk)
            break
        results.append(chunk)
        total_chars += len(chunk.content)
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
