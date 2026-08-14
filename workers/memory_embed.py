"""
memory_embed.py · 可选 embedding 语义检索层 (wish-45b8ff04)
==========================================================
设计原则 (BRO 拍板: 稳定和聪明第一 · 省钱只做零风险项):
  - **可选增强层** · 不阻塞主索引: embedding 没建好 / API 挂了 → 自动退化为纯 FTS5
  - **懒加载**: 只有显式调用 embedding 功能时才初始化客户端 · 平时零开销
  - **全量回填 + 增量补算**: rebuild 时批量回填 · 新增 chunk 单独补算
  - **零新增依赖**: 用 requests (已装) + numpy (已装) · 不用 sentence_transformers

存储:
  - memory_chunks 表加 `embedding BLOB` 列 (float32 序列化 · 2048 维 ≈ 8KB/chunk)
  - 查询时只对 query 算一次 embedding (¥0.0001) · chunk 的 embedding 全在本地 → 零查询成本

API: 智谱 embedding-3 (open.bigmodel.cn) · 已验证 (ATM-Bench 11034 条 · ¥2)
"""
from __future__ import annotations

import json
import logging
import pathlib
import sqlite3
import threading
import time

import numpy as np

logger = logging.getLogger("opus.embed")

# ---------------------------------------------------------------------------
# 配置 (wish-b313583b · 用户可配 · 面向开源纯净版)
# 优先级: data/embedding_config.json (用户自配) → provider_configs 智谱 (母体兼容) → .env
# 参照 vision_config.py 单例模式 · 不写死单一 API
# ---------------------------------------------------------------------------
EMBED_MODEL = "embedding-3"                    # 默认模型 (用户没配时用)
EMBED_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"  # 默认端点根 (不含 /embeddings · 拼装时加)
EMBED_DIM = 2048          # embedding-3 维度 (用户自定义模型时可能不同 · 以实际返回为准)
EMBED_BATCH = 32          # 单批最大条数 (实测: 32 OK · 64 报 400 参数错误 · 2026-08-12)
EMBED_MAX_TEXT = 4000     # 单条文本最大字符 (截断防超限)
_DEFAULT_TIMEOUT = 15     # P1-5 修复 · 120s→15s (embedding API 挂时白等 2 分钟 → 15s 快速失败)

# P1-5 修复 · 熔断: 连续 3 次失败 → 熔断 300s (embedding 暂不可用 · 不再白等)
# 背景: 用户配错 key / API 掉线时 · 每次 recall 都白等 timeout · 高并发时直接把 daemon 拖死。
_CIRCUIT = {"fail_count": 0, "open_until": 0.0}
_CIRCUIT_MAX_FAILS = 3
_CIRCUIT_OPEN_SEC = 300

# 用户配置持久化 (wish-b313583b · 前端可编辑 · 独立文件方便开源纯净版)
_EMBED_CONFIG_PATH = pathlib.Path("data/embedding_config.json")


def load_config() -> dict:
    """读用户 embedding 配置。 返回 {model, base_url, api_key, enabled, configured, source}。

    优先级: data/embedding_config.json → provider_configs 智谱 (母体兼容) → 空骨架。
    source: 'user' (用户自配) / 'zhipu-provider' (fallback 智谱) / '' (未配置)
    """
    cfg = {"model": "", "base_url": "", "api_key": "", "enabled": True, "configured": False, "source": ""}

    # 1. 用户自配 (embedding_config.json)
    try:
        if _EMBED_CONFIG_PATH.exists():
            user_cfg = json.loads(_EMBED_CONFIG_PATH.read_text(encoding="utf-8"))
            m = (user_cfg.get("model") or "").strip()
            u = (user_cfg.get("base_url") or "").strip()
            k = (user_cfg.get("api_key") or "").strip()
            if m and u and k:
                cfg.update(model=m, base_url=u.rstrip("/"), api_key=k,
                           enabled=user_cfg.get("enabled", True),
                           configured=True, source="user")
                return cfg
            # 只有开关时也读 enabled
            if "enabled" in user_cfg:
                cfg["enabled"] = bool(user_cfg["enabled"])
    except Exception:
        pass

    # 2. fallback: provider_configs 里的智谱 (母体开箱即用 · 不配也能跑)
    try:
        cfg_path = pathlib.Path("data/provider_configs.json")
        if cfg_path.exists():
            pcfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            for c in pcfg.get("configs", []):
                if "bigmodel" in (c.get("base_url") or "") or "zhipu" in (c.get("name") or "").lower():
                    cfg.update(model=EMBED_MODEL, base_url=EMBED_BASE_URL,
                               api_key=c.get("api_key", ""), configured=True, source="zhipu-provider")
                    return cfg
    except Exception:
        pass

    # 3. .env 回退
    try:
        from dotenv import dotenv_values  # type: ignore
        env = dotenv_values(".env")
        k = env.get("ZHIPU_API_KEY") or env.get("BIGMODEL_API_KEY") or ""
        if k:
            cfg.update(model=EMBED_MODEL, base_url=EMBED_BASE_URL,
                       api_key=k, configured=True, source="env")
    except Exception:
        pass
    return cfg


def save_config(cfg: dict) -> bool:
    """写用户 embedding 配置 (model/base_url/api_key/enabled)。 返回是否成功。"""
    try:
        _EMBED_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing = {}
        if _EMBED_CONFIG_PATH.exists():
            try:
                existing = json.loads(_EMBED_CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
        merged = dict(existing)
        for k in ("model", "base_url", "api_key", "enabled"):
            if k in cfg:
                merged[k] = cfg[k]
        _EMBED_CONFIG_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
        return True
    except Exception:
        return False


def is_enabled() -> bool:
    """embedding 语义检索是否开启 (默认开 · 前端可关)。"""
    return bool(load_config().get("enabled", True))


def set_enabled(enabled: bool) -> bool:
    """持久化开关。 返回是否成功。"""
    return save_config({"enabled": bool(enabled)})

# 全局客户端状态 (懒加载 · 线程安全)
_client_lock = threading.Lock()
_client_state: dict = {"ready": False, "api_key": "", "base_url": "", "model": ""}

# wish-45b8ff04 · query embedding 内存缓存 (LRU 简单实现 · 同 query 短时间重复查不重调 API)
# 母体对话里 recall_memory 可能连续多次同 query (如自动注入 + OPUS 主动查) · 缓存省 API 费 + 0.7s
_query_embed_cache: dict[str, tuple[float, np.ndarray]] = {}
_QUERY_CACHE_MAX = 64
_QUERY_CACHE_TTL = 300.0  # 5 分钟


def _cache_get(query: str) -> np.ndarray | None:
    hit = _query_embed_cache.get(query)
    if hit and time.time() - hit[0] < _QUERY_CACHE_TTL:
        return hit[1]
    return None


def _cache_put(query: str, vec: np.ndarray) -> None:
    if len(_query_embed_cache) >= _QUERY_CACHE_MAX:
        # 淘汰最旧 (dict 保序 · pop 第一个)
        _query_embed_cache.pop(next(iter(_query_embed_cache)))
    _query_embed_cache[query] = (time.time(), vec)


def _circuit_open() -> bool:
    """熔断器是否处于打开状态 (embedding 暂不可用)。"""
    if _CIRCUIT["open_until"] > time.time():
        return True
    return False


def _circuit_report_failure() -> None:
    """报告一次失败 · 连续 _CIRCUIT_MAX_FAILS 次 → 打开熔断器。"""
    _CIRCUIT["fail_count"] += 1
    if _CIRCUIT["fail_count"] >= _CIRCUIT_MAX_FAILS:
        _CIRCUIT["open_until"] = time.time() + _CIRCUIT_OPEN_SEC
        _CIRCUIT["fail_count"] = 0
        logger.warning("embedding API 连续 %d 次失败 · 熔断 %ds · 语义检索降级 FTS5",
                       _CIRCUIT_MAX_FAILS, _CIRCUIT_OPEN_SEC)


def _circuit_report_success() -> None:
    """报告一次成功 · 复位熔断计数。"""
    _CIRCUIT["fail_count"] = 0


def ensure_client() -> bool:
    """懒初始化 embedding 客户端。 返回是否可用。

    P1-5 修复: 熔断期内直接返回 False (不初始化 · 不白等)。
    """
    if _circuit_open():
        return False
    if _client_state["ready"]:
        return True
    with _client_lock:
        if _circuit_open():
            return False
        if _client_state["ready"]:
            return True
        cfg = load_config()
        if not cfg.get("configured") or not cfg.get("api_key"):
            return False
        _client_state.update(api_key=cfg["api_key"], base_url=cfg["base_url"], model=cfg["model"], ready=True)
        return True


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """批量 embedding (单批 ≤ EMBED_BATCH)。 失败返回 None (调用方降级 FTS5)。

    P1-2 修复: 不假定 API 返回顺序 = 输入顺序 · 用 data[].index 对齐 ·
    乱序/缺条/维度不符 → 整批 fail 返回 None (不做部分结果 · 防错位写入)。
    P1-5 修复: 失败计入熔断计数 · 超时 15s。
    """
    if not ensure_client():
        return None
    import requests

    url = f"{_client_state['base_url'].rstrip('/')}/embeddings"
    out: list[list[float]] = []
    try:
        headers = {"Authorization": f"Bearer {_client_state['api_key']}"}
        for i in range(0, len(texts), EMBED_BATCH):
            batch = [t[:EMBED_MAX_TEXT] for t in texts[i:i + EMBED_BATCH]]
            r = requests.post(url, headers=headers,
                              json={"model": _client_state["model"], "input": batch},
                              timeout=_DEFAULT_TIMEOUT)
            if r.status_code != 200:
                _circuit_report_failure()
                return None
            data = r.json()
            items = data.get("data", [])
            # P1-2 · index 对齐: 不假定返回顺序 = 输入顺序
            by_idx: dict[int, list[float]] = {}
            dim = None
            for item in items:
                try:
                    idx = int(item.get("index", -1))
                except (TypeError, ValueError):
                    idx = -1
                emb = item.get("embedding")
                if idx >= 0 and isinstance(emb, list):
                    # 子代理交叉验证 (sub-f1bb133b) · 维度一致校验:
                    # 用户配不同维度模型时混入异构向量 → cosine_topk np.stack 抛 ValueError →
                    # 被 search try/except 吞掉 → 整库语义检索静默降级无日志。
                    if dim is None:
                        dim = len(emb)
                    if len(emb) != dim or len(emb) == 0:
                        _circuit_report_failure()
                        logger.warning("embedding API 返回维度不一致 (%d vs %d) · 整批 fail", len(emb), dim)
                        return None
                    by_idx[idx] = emb
            # 缺条 / 乱序无法对齐 → 整批 fail (防错位)
            if len(by_idx) != len(batch) or any(i not in by_idx for i in range(len(batch))):
                _circuit_report_failure()
                logger.warning("embedding API 返回乱序/缺条 (%d/%d) · 整批 fail", len(by_idx), len(batch))
                return None
            out.extend(by_idx[i] for i in range(len(batch)))
        _circuit_report_success()
        return out
    except Exception:
        _circuit_report_failure()
        return None


def embed_query(text: str) -> np.ndarray | None:
    """单条 query embedding (带内存缓存)。 失败返回 None。"""
    cached = _cache_get(text)
    if cached is not None:
        return cached
    embs = embed_texts([text])
    if not embs:
        return None
    vec = np.asarray(embs[0], dtype=np.float32)
    _cache_put(text, vec)
    return vec


# ---------------------------------------------------------------------------
# 存储
# ---------------------------------------------------------------------------

def _has_embedding_col(conn: sqlite3.Connection) -> bool:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(memory_chunks)").fetchall()]
    return "embedding" in cols


def ensure_schema(conn: sqlite3.Connection) -> bool:
    """给 memory_chunks 加 embedding 列 (幂等)。 返回是否可用。"""
    if _has_embedding_col(conn):
        return True
    try:
        conn.execute("ALTER TABLE memory_chunks ADD COLUMN embedding BLOB")
        conn.commit()
        return True
    except Exception:
        return False


def _vec_to_blob(v: np.ndarray) -> bytes:
    return v.astype(np.float32).tobytes()


def _blob_to_vec(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def embed_chunk(conn: sqlite3.Connection, chunk_id: int, content: str) -> bool:
    """单条 chunk 增量补 embedding (best-effort)。 成功返回 True · 失败 False (不炸)。"""
    try:
        if not _has_embedding_col(conn):
            return False
        embs = embed_texts([content[:EMBED_MAX_TEXT]])
        if not embs:
            return False
        conn.execute("UPDATE memory_chunks SET embedding=? WHERE id=?",
                     (_vec_to_blob(np.asarray(embs[0], dtype=np.float32)), chunk_id))
        return True
    except Exception:
        return False


def backfill_all(conn: sqlite3.Connection, limit: int | None = None) -> tuple[int, int]:
    """全量回填缺失的 embedding。 返回 (成功数, 失败数)。"""
    if not ensure_schema(conn):
        return 0, 0
    if not ensure_client():
        return 0, 0

    from .memory_index import embed_where_sql  # 分层过滤 · 只回填高信号源 (session 原文不进向量)
    sql = f"SELECT id, content FROM memory_chunks WHERE embedding IS NULL AND {embed_where_sql()}"
    if limit:
        sql += f" LIMIT {limit}"
    rows = conn.execute(sql).fetchall()
    if not rows:
        return 0, 0

    ok = fail = 0
    for i in range(0, len(rows), EMBED_BATCH):
        batch = rows[i:i + EMBED_BATCH]
        texts = [r[1] for r in batch]
        embs = embed_texts(texts)
        if embs is None:
            # P2-1 修复 (墨言审查): 失败批 1 次指数退避重试 (网络抖动自愈 · 避免静默丢 embedding)
            import time as _t
            _t.sleep(1.0)
            embs = embed_texts(texts)
        if embs is None:
            fail += len(batch)
            continue
        for (cid, _), e in zip(batch, embs):
            conn.execute("UPDATE memory_chunks SET embedding=? WHERE id=?",
                         (_vec_to_blob(np.asarray(e, dtype=np.float32)), cid))
            ok += 1
        conn.commit()
    return ok, fail


def cosine_topk(query_vec: np.ndarray, conn: sqlite3.Connection, top_k: int = 20,
                scope: str | None = None) -> list[tuple[int, float]]:
    """分层余弦相似度 top-k (内存 numpy 向量化 · 只扫高信号源 ~480 条 · <2ms)。 返回 [(chunk_id, score)]。

    P1-4 修复 (墨言审查): 加 scope 参数 · 补漏路径不再跨 scope 泄漏。
    之前只按 embed_where_sql() 扫全部高信号源 → scope='bro' 也会带回 SELF-EVOLUTION 内容。
    现在 scope 非空时拼对应的 source 条件 · 与 FTS5 层过滤一致。
    """
    from .memory_index import embed_where_sql  # 分层过滤 · session 原文向量不参与语义检索
    where = embed_where_sql()
    if scope and scope != "all":
        # 与 memory_index.search 的 scope_filter 同口径 (L62-76)
        if scope == "bro":
            where += " AND source = 'BRO-NOTEBOOK'"
        elif scope == "self":
            where += " AND source IN ('SELF-EVOLUTION','OPUS-MEMORIES','SKILL')"
        elif scope == "sessions":
            where += " AND source IN ('session','session_summary')"
        elif scope == "skill":
            where += " AND source = 'skill'"
        elif scope == "docs":
            where += " AND source LIKE 'doc:%'"
        elif scope == "clients":
            where += " AND source LIKE 'client:%'"
    rows = conn.execute(
        f"SELECT id, embedding FROM memory_chunks WHERE embedding IS NOT NULL AND {where}"
    ).fetchall()
    if not rows:
        return []
    ids = [r[0] for r in rows]
    # 2048 维 × N 条 → 矩阵 (numpy 向量化)
    mat = np.stack([_blob_to_vec(r[1]) for r in rows])
    q = query_vec.astype(np.float32)
    denom = np.linalg.norm(mat, axis=1) * np.linalg.norm(q)
    denom[denom == 0] = 1.0
    scores = (mat @ q) / denom
    top_idx = np.argsort(-scores)[:top_k]
    return [(int(ids[i]), float(scores[i])) for i in top_idx]


def stats(conn: sqlite3.Connection) -> dict:
    """embedding 覆盖统计 (分层口径 · wish-ba84aa18)。

    分母 = 应进向量的高信号源 (session_summary/skill/灵魂文件/doc:) ·
    不是全库 —— session 对话原文 (占 97%+) 只走 FTS5 不计入向量 · 否则显示 2% 误导用户。
    """
    if not _has_embedding_col(conn):
        return {"enabled": False, "covered": 0, "total": 0}
    from .memory_index import embed_where_sql
    total = conn.execute(f"SELECT count(*) FROM memory_chunks WHERE {embed_where_sql()}").fetchone()[0]
    covered = conn.execute(
        f"SELECT count(*) FROM memory_chunks WHERE embedding IS NOT NULL AND {embed_where_sql()}"
    ).fetchone()[0]
    return {"enabled": True, "covered": covered, "total": total}


# ---------------------------------------------------------------------------
# 跟 memory_index.search 的整合 (由 memory_index 调用 · 不反向 import)
# ---------------------------------------------------------------------------

def hybrid_rerank(query: str, fts_hits: list, conn: sqlite3.Connection,
                  top_k: int = 20, embed_weight: float = 0.4, scope: str | None = None) -> list:
    """三通道混合: FTS5 命中 + embedding 语义命中 → 加权融合排序。

    fts_hits: search() 现有的 MemoryChunk 列表 (已按 FTS5 bm25 排 · score 越负越相关)。
    conn: 已打开的 DB 连接 (search() 传进来 · 避免重复 open)。
    返回重排后的 MemoryChunk 列表 (embedding 语义命中能翻越 FTS5 弱命中 · 但不能压过 FTS5 强命中)。

    wish-b8bd0c01 · 修复 (原实现 bug): 旧版只做 "FTS5 原序 + 补进尾部"· 补进的条目在
    FTS5 满召回时被 merged[:top_k] 截断 · embedding 永远不生效 (embed_weight 死代码)。
    新版真加权融合: fts_norm (bm25 归一化 0-1) × (1-w) + cosine × w ·
    FTS5 强命中 fts_norm≈1 → final≥0.6 永远保住 · 纯语义命中 (FTS5 无分) final=0.4×cos ·
    只有 cosine>0.65 的强语义命中才能翻越 fts_norm<0.5 的 FTS5 弱命中 — 正是 embedding 该有的价值。
    """
    if not is_enabled():  # wish-b313583b · 前端可关
        return fts_hits
    if not _has_embedding_col(conn):
        return fts_hits
    qv = embed_query(query)
    if qv is None:
        return fts_hits

    sem_hits = cosine_topk(qv, conn, top_k=max(top_k * 3, 60), scope=scope)  # P1-4: scope 透传
    if not sem_hits:
        return fts_hits

    # 相对显著性闸门 (2026-08-14 · BRO 质疑+重测暴露): 纯绝对阈值 cos>0.25 不够 —
    # 随机 query 也能碰出 0.37-0.57 的"伪相似"(cosine_topk 取相对 top-N · 噪音也进)。
    # 数据实测 (ATM 31 题 + 随机噪音对照): 真语义命中是"紧密簇"(前3名衰减 d1-3 <0.1 ·
    #   照片ID 0.007/酒店 0.011/会议 0.043/论文 0.064/行程 0.032 · 且 top1 0.33-0.48)，
    #   随机噪音是"单点碰巧"(d1-3 ≥0.13 · 随机串 0.137/0.167/闲聊 0.175)。
    # v2 闸门: 前3名内聚度 d1-3 < 0.10 且 top1 > 0.30 (软下限)。
    #   (v1 用 d1-10 + top10>0.35 绝对兜底 · 误杀低相似度真簇 580a4fee top10=0.30 → 45.2% vs 54.8%)
    _sem_scores = [cos for _, cos in sem_hits]
    _sem_top1 = _sem_scores[0] if _sem_scores else 0.0
    _sem_d3 = _sem_scores[0] - _sem_scores[2] if len(_sem_scores) >= 3 else 0.0
    if _sem_d3 >= 0.10 or _sem_top1 <= 0.30:
        return fts_hits  # 判定无语义命中 · 不补漏 · 防噪音污染

    sem_map = dict(sem_hits)

    # FTS5 bm25 分归一化: 越负越相关 → 在命中集内部 min-max 到 [0,1] (最强=1 · 最弱=0)。
    # 注意: 不能除以全局 range — bm25 分绝对值跨库差异大 (ATM 英文库 -14~-11 · 中文库可能 -5~-1) ·
    # 除以全局会让所有命中都≈1 (clamp 后满榜) · embedding 永远翻不进来。
    # 命中集内部 min-max: 最强的 FTS5 命中保持 1.0 (永不被打败) · 最弱的给 0 (让位给强语义命中)。
    fts_scores = [c.score for c in fts_hits if c.score != 0.0]
    fts_min = min(fts_scores) if fts_scores else 0.0
    fts_max = max(fts_scores) if fts_scores else 0.0
    fts_span = max(fts_max - fts_min, 1e-9)

    scored: list[tuple[float, int, object]] = []
    fts_ids = {c.id for c in fts_hits}
    for c in fts_hits:
        if c.score != 0.0 and fts_span > 1e-9:
            fts_norm = max(0.0, min(1.0, (fts_max - c.score) / fts_span))
        else:
            fts_norm = 0.0  # LIKE 退化路径无分数
        cos = sem_map.get(c.id, 0.0)
        final = (1 - embed_weight) * fts_norm + embed_weight * cos
        scored.append((final, c.id, c))
    for cid, cos in sem_hits:
        if cid not in fts_ids and cos > 0.25:  # 语义阈值 · 太低的噪音不进
            # 需要取 chunk 全文 → 延迟 import 防循环
            from .memory_index import get_chunks_by_ids
            chunk = get_chunks_by_ids([cid], context_window=2000)
            if chunk:
                scored.append((embed_weight * cos, cid, chunk[0]))

    scored.sort(key=lambda x: -x[0])
    return [c for _, _, c in scored[:top_k]]
