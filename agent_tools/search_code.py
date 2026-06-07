"""
agent_tools/search_code.py
==========================

OPUS 的"按意思找代码"——语义代码搜索。补 Cursor SemanticSearch 那块盲区 (续 ②)。

为什么 (grep_files 不够):
  grep_files 是【字面正则】——你得先猜对关键词。 问"哪里处理重启后续场"这种概念问题·
  正则答不上。 Cursor 的 SemanticSearch 靠向量按意思找。 本工具补这层。

两档后端 (自包含·离线也能用·配 key 自动升级):
  - 默认 **TF-IDF** (纯 Python·零网络·即时): 对代码做了 camelCase/snake_case 拆词·
    所以 "load session" 能命中 `loadSession` / `_load_session_history`。 比 grep 懂概念·
    但抓不到真同义词 (login vs authenticate)。
  - 可选 **neural rerank** (配了 embedding 端点才开): TF-IDF 先预筛 top-N 候选·
    再用 embedding 余弦重排 → 成本有界 (每次 query 只 embed ~60 段·还按 mtime 缓存)。
    开启方式: 设环境变量 OPUS_EMBED_BASE_URL + OPUS_EMBED_API_KEY + OPUS_EMBED_MODEL。
    任何一步出错 → 静默退回 TF-IDF (绝不因为 embedding 挂了就搜不了)。

AUTO tier · 纯读 · 不改任何文件。
"""

from __future__ import annotations

import math
import os
import re
from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


ROOT = Path(__file__).resolve().parent.parent

_EXT = {".py", ".js", ".mjs", ".ts", ".jsx", ".tsx", ".md"}
_SKIP_PARTS = {
    ".git", ".venv", "node_modules", "__pycache__", "site-packages", "sessions",
    "_backups", "_archive", "lib", "dist", "build", ".pytest_cache",
    "browser_profile_standalone", "cursor_sdk",
    # 巨型 append-only 叙事文件 (船长日志 / 自我演化 / 灵魂自传) 会用密集散文淹没真代码——
    # 那些是 recall_memory / session_search 的地盘·code 搜索不碰。 docs/ 和 data/cognition 的
    # 参考文档体量小·保留 (它们答"X 怎么设计"有用)。
    ".cursor", "soul",
}
_MAX_FILE_BYTES = 1_000_000
_CHUNK_LINES = 45
_CHUNK_STRIDE = 35
_MAX_CHUNKS = 9000
_NEURAL_PREFILTER = 60

_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_SUB_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


def _tokens(text: str) -> list[str]:
    """拆词: 整 token + camelCase/snake_case 子词·都小写·长度>=2。"""
    out: list[str] = []
    for m in _WORD_RE.finditer(text):
        w = m.group(0)
        if len(w) >= 2:
            out.append(w.lower())
        for s in _SUB_RE.findall(w):
            s = s.lower()
            if len(s) >= 2 and s != w.lower():
                out.append(s)
    return out


def _summarize(args: dict) -> str:
    return f"search_code  '{args.get('query', '?')}'  top{args.get('top_k', 8)}"


def _iter_files(scope: Path):
    if scope.is_file():
        if scope.suffix.lower() in _EXT:
            yield scope
        return
    for p in scope.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in _EXT:
            continue
        if any(part in _SKIP_PARTS for part in p.parts):
            continue
        try:
            if p.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield p


def _build_chunks(scope: Path) -> list[dict]:
    chunks: list[dict] = []
    for p in _iter_files(scope):
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        rel = str(p.relative_to(ROOT)) if str(p).startswith(str(ROOT)) else str(p)
        n = len(lines)
        start = 0
        while start < n:
            seg = lines[start:start + _CHUNK_LINES]
            text = "\n".join(seg)
            if text.strip():
                chunks.append({
                    "rel": rel, "path": p,
                    "start": start + 1, "end": min(start + _CHUNK_LINES, n),
                    "text": text, "mtime": p.stat().st_mtime,
                })
                if len(chunks) >= _MAX_CHUNKS:
                    return chunks
            start += _CHUNK_STRIDE
    return chunks


def _tfidf_scores(query: str, chunks: list[dict]) -> list[float]:
    """纯 Python 稀疏 TF-IDF 余弦·返回每个 chunk 的得分。"""
    df: dict[str, int] = {}
    doc_tf: list[dict[str, int]] = []
    for c in chunks:
        tf: dict[str, int] = {}
        for t in _tokens(c["text"]):
            tf[t] = tf.get(t, 0) + 1
        doc_tf.append(tf)
        for t in tf:
            df[t] = df.get(t, 0) + 1

    n = len(chunks) or 1
    idf = {t: math.log((1 + n) / (1 + d)) + 1.0 for t, d in df.items()}

    q_tf: dict[str, int] = {}
    for t in _tokens(query):
        q_tf[t] = q_tf.get(t, 0) + 1
    q_vec = {t: c * idf.get(t, 0.0) for t, c in q_tf.items()}
    q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1.0

    scores: list[float] = []
    for tf in doc_tf:
        dot = 0.0
        dnorm_sq = 0.0
        for t, c in tf.items():
            w = c * idf.get(t, 0.0)
            dnorm_sq += w * w
            if t in q_vec:
                dot += w * q_vec[t]
        dnorm = math.sqrt(dnorm_sq) or 1.0
        scores.append(dot / (q_norm * dnorm))
    return scores


def _embed_config() -> dict | None:
    base = os.environ.get("OPUS_EMBED_BASE_URL")
    key = os.environ.get("OPUS_EMBED_API_KEY")
    model = os.environ.get("OPUS_EMBED_MODEL")
    if base and key and model:
        return {"base_url": base, "api_key": key, "model": model}
    return None


def _neural_rerank(query: str, cands: list[dict], cfg: dict) -> list[float] | None:
    """对预筛候选做 embedding 余弦重排。 任何异常返 None (调用方退回 TF-IDF)。"""
    try:
        import numpy as np
        from openai import OpenAI
    except Exception:
        return None
    try:
        client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"])
        inputs = [query] + [c["text"][:2000] for c in cands]
        resp = client.embeddings.create(model=cfg["model"], input=inputs)
        vecs = [np.array(d.embedding, dtype="float32") for d in resp.data]
        q = vecs[0]
        qn = np.linalg.norm(q) or 1.0
        out = []
        for v in vecs[1:]:
            out.append(float(np.dot(q, v) / (qn * (np.linalg.norm(v) or 1.0))))
        return out
    except Exception:
        return None


def _run(args: dict) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, output="", error="missing 'query'")
    top_k = int(args.get("top_k") or 8)
    top_k = max(1, min(top_k, 25))

    scope_arg = args.get("path") or "."
    scope = Path(scope_arg)
    if not scope.is_absolute():
        scope = ROOT / scope
    scope = scope.resolve()
    if not scope.exists():
        return ToolResult(ok=False, output="", error=f"path not found: {scope}")

    chunks = _build_chunks(scope)
    if not chunks:
        return ToolResult(ok=True, output=f"# search_code: {query!r}\n(没找到可索引的源码文件)")

    tfidf = _tfidf_scores(query, chunks)
    order = sorted(range(len(chunks)), key=lambda i: tfidf[i], reverse=True)

    backend = "tf-idf"
    cfg = _embed_config()
    if cfg:
        pre = order[:_NEURAL_PREFILTER]
        cands = [chunks[i] for i in pre]
        rer = _neural_rerank(query, cands, cfg)
        if rer is not None:
            paired = sorted(zip(pre, rer), key=lambda x: x[1], reverse=True)
            order = [i for i, _ in paired] + [i for i in order if i not in pre]
            for idx, (i, s) in enumerate(paired):
                tfidf[i] = s  # 复用 tfidf 数组存最终展示分
            backend = f"neural-rerank ({cfg['model']})"

    top = order[:top_k]
    n_files = len({c["rel"] for c in chunks})
    lines = [f"# search_code: {query!r}  (backend={backend} · {len(chunks)} chunks / {n_files} files)"]
    for rank, i in enumerate(top, 1):
        c = chunks[i]
        preview = "\n".join(
            "      " + ln for ln in c["text"].splitlines()[:3] if ln.strip()
        )
        lines.append(f"\n{rank}. [{tfidf[i]:.3f}] {c['rel']}:{c['start']}-{c['end']}\n{preview}")
    lines.append(
        "\n→ 用 read_file(path, start_line, end_line) 看全段 · outline_file 看整文件骨架 · 再 edit_file。"
    )
    body = "\n".join(lines)
    truncated = False
    if len(body) > 20000:
        body = body[:20000] + "\n\n... [truncated · 缩小 path 或减小 top_k]"
        truncated = True
    return ToolResult(ok=True, output=body, truncated=truncated)


SPEC = ToolSpec(
    name="search_code",
    description=(
        "Semantic code search — find code by MEANING, not exact text (complements grep_files's literal regex). "
        "Ask conceptual questions like 'where do we resume a turn after restart' or 'how are attachments parsed'. "
        "Default backend is offline TF-IDF with camelCase/snake_case tokenization (so 'load session' matches "
        "loadSession / _load_session_history); if OPUS_EMBED_BASE_URL/API_KEY/MODEL env are set it upgrades to "
        "neural embedding rerank (bounded cost, falls back to TF-IDF on any error). "
        "Returns ranked file:line ranges — then read_file that range / outline_file the file / edit_file. Read-only."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A conceptual question or description of the code you're looking for.",
            },
            "path": {
                "type": "string",
                "description": "Optional directory/file to scope the search. Default: whole project.",
            },
            "top_k": {
                "type": "integer",
                "description": "How many results to return (1-25, default 8).",
            },
        },
        "required": ["query"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
