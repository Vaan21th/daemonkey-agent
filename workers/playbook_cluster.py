"""手册同簇召回：主册 + 对照。对照正文上限 400 字。"""
from __future__ import annotations

import math
import re
from typing import Iterable

PEER_CHAR_CAP = 400
COSINE_TH = 0.80
_TOKEN = re.compile(r"[0-9A-Za-z一-鿿]{2,}")


def _norm(vec: Iterable[float]) -> list[float]:
    xs = [float(x) for x in vec]
    n = math.sqrt(sum(x * x for x in xs)) or 1.0
    return [x / n for x in xs]


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    aa, bb = _norm(a), _norm(b)
    return sum(x * y for x, y in zip(aa, bb))


def rank_by_vectors(
    query_vec: list[float],
    items: list[dict],
    *,
    threshold: float = COSINE_TH,
    k: int = 3,
) -> list[dict]:
    """items: {id, vec, title, ...}。低于 threshold 的干扰项丢掉。"""
    scored = []
    for it in items:
        vec = it.get("vec")
        if not vec:
            continue
        sim = cosine(query_vec, vec)
        row = dict(it)
        row["sim"] = round(sim, 4)
        scored.append(row)
    scored.sort(key=lambda r: r["sim"], reverse=True)
    keep = [r for r in scored if r["sim"] >= threshold]
    if not keep and scored:
        keep = scored[:1]
    return keep[:k]


def _live_vectors() -> dict[str, list[float]]:
    try:
        import sqlite3
        from workers.memory_map import DB_PATH, _load_pb_vectors
        if not DB_PATH.exists():
            return {}
        conn = sqlite3.connect(str(DB_PATH))
        try:
            pbs = _load_pb_vectors(conn)
        finally:
            conn.close()
        out = {}
        for name, d in pbs.items():
            c = d.get("centroid")
            if c is None:
                continue
            out[name] = [float(x) for x in c.tolist()]
        return out
    except Exception:
        return {}


def re_tokens(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN.finditer(text or "")]


def _title_overlap(query: str, title: str) -> float:
    q = set(re_tokens(query))
    t = set(re_tokens(title))
    if not q or not t:
        return 0.0
    return len(q & t) / math.sqrt(len(q) * len(t))


def peers_of(
    slug: str,
    *,
    query: str = "",
    vectors: dict[str, list[float]] | None = None,
    items: list[dict] | None = None,
    k: int = 3,
) -> list[dict]:
    """同簇对照。vectors 可注入假向量（夹具）。"""
    from workers.playbooks import list_playbooks
    catalog = items if items is not None else list_playbooks()
    vecs = vectors if vectors is not None else _live_vectors()
    qvec = vecs.get(slug)
    packed = []
    for pb in catalog:
        s = pb.get("slug") or ""
        if not s or s == slug:
            continue
        row = dict(pb)
        if s in vecs and qvec is not None:
            row["vec"] = vecs[s]
        packed.append(row)
    if qvec is not None and any(r.get("vec") for r in packed):
        return rank_by_vectors(qvec, packed, k=k)
    scored = []
    seed = query or slug
    for pb in catalog:
        s = pb.get("slug") or ""
        if s == slug:
            continue
        sim = _title_overlap(seed, f"{pb.get('title', '')} {s}")
        if sim <= 0:
            continue
        row = dict(pb)
        row["sim"] = round(sim, 4)
        scored.append(row)
    scored.sort(key=lambda r: r["sim"], reverse=True)
    return scored[:k]


def _clip(text: str, n: int) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


def format_injection(fresh: list[dict], message: str = "", *, vectors: dict | None = None) -> str:
    """主册问题/试错过 + 同簇对照。对照总长 ≤ PEER_CHAR_CAP。"""
    from workers.playbook_case import case_snippets
    lines: list[str] = []
    peer_budget = PEER_CHAR_CAP
    for pb in fresh:
        pid = pb.get("id") or ""
        snip = case_snippets(pid)
        if snip.get("problem"):
            lines.append(f"  问题: {_clip(snip['problem'], 72)}")
        trial = snip.get("trial") or ""
        if trial and trial not in ("暂无记录", "尚无失败路径"):
            lines.append(f"  试错过: {_clip(trial, 88)}")
        peers = peers_of(pb.get("slug") or "", query=message, vectors=vectors, k=3)
        if not peers or peer_budget <= 0:
            continue
        chunk = ["  同簇对照:"]
        used = 0
        for peer in peers:
            bit = f"    · {peer.get('title') or peer.get('slug')} (sim={peer.get('sim', '?')})"
            if used + len(bit) + 1 > peer_budget:
                break
            chunk.append(bit)
            used += len(bit) + 1
        if len(chunk) > 1:
            lines.extend(chunk)
            peer_budget -= used
    return "\n".join(lines)


def peers_action(args: dict) -> dict:
    pid = str(args.get("playbook_id") or "").strip()
    query = str(args.get("query") or "").strip()
    if not pid and not query:
        return {"ok": False, "output": "", "error": "peers 需要 playbook_id 或 query"}
    from workers.playbooks import load_playbook, search_playbooks
    slug = ""
    if pid:
        loaded = load_playbook(playbook_id=pid)
        slug = (loaded.get("meta") or {}).get("slug") or ""
        if loaded.get("error") and not query:
            return {"ok": False, "output": "", "error": loaded["error"]}
    if slug:
        rows = peers_of(slug, query=query or slug, k=5)
    else:
        rows = search_playbooks(query=query, limit=5)
    if not rows:
        return {"ok": True, "output": "no peers", "error": ""}
    lines = [f"peers {len(rows)}:"]
    for r in rows:
        lines.append(f"- {r.get('title')}  id={r.get('id')}  sim={r.get('sim', '-')}")
    return {"ok": True, "output": "\n".join(lines), "error": ""}
