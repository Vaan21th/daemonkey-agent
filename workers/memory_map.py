"""workers/memory_map.py
========================
记忆星图 + 记忆管理统计的数据组装 (2026-08-20 · 0.9.6 成长档案可视化)。

why: 社区沟通里"知识图谱"是个被念叨的词 —— 与其解释"我们不用知识图谱",
不如把记忆体系真实的样子摆出来: playbook 的语义簇 (向量 PCA 降维后天然成团),
配上卫生闸/分层/漏斗的实测数字。 看着是"图谱", 底层是语义簇 —— 诚实且直观。

纯数据组装 · 不碰写 · 全部现算 (库是单一真源 · 不落缓存文件)。
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "memory_index.db"
INJECT_LOG = ROOT / "data" / "runtime" / "inject_log.jsonl"
INJECT_USED = ROOT / "data" / "runtime" / "inject_used.jsonl"

_CLUSTER_THRESHOLD = 0.80  # 跟判重清单同口径


def _load_pb_vectors(conn: sqlite3.Connection) -> dict[str, dict]:
    """skill chunks 按 playbook 聚合: centroid 向量 + 总字符数。"""
    import numpy as np

    pbs: dict[str, dict] = {}
    for section, content, emb in conn.execute(
        "SELECT section, content, embedding FROM memory_chunks "
        "WHERE source='skill' AND embedding IS NOT NULL"
    ):
        name = (section or "").split(":")[0]
        if not name:
            continue
        d = pbs.setdefault(name, {"vecs": [], "chars": 0})
        d["vecs"].append(np.frombuffer(emb, dtype=np.float32))
        d["chars"] += len(content or "")
    for d in pbs.values():
        c = np.mean(d["vecs"], axis=0)
        d["centroid"] = c / (float(np.linalg.norm(c)) + 1e-9)
        del d["vecs"]
    return pbs


def _constellation_empty_reason(conn: sqlite3.Connection, n_pb: int) -> dict:
    """星图空态的三层原因 (2026-08-21 · test3 实测暴露: 空数组无说明 = 用户对着黑框猜)。

    分层诊断: 没配embedding → 配了但向量覆盖 0 → 有向量但手艺 <3 门。
    返回 {"code", "msg", "action"} · action=settings 时前端给「去设置」按钮。
    """
    try:
        from workers.memory_embed import load_config, stats
        cfg = load_config()
        if not cfg.get("configured"):
            return {"code": "no_embed_config", "action": "settings",
                    "msg": "星图靠语义向量把相似手艺聚成星系·但embedding服务还没配——配上后历史记忆自动向量化·星图就亮"}
        st = stats(conn)
        if st.get("total", 0) > 0 and st.get("covered", 0) == 0:
            return {"code": "no_vectors", "action": "settings",
                    "msg": "embedding 已配·但历史记忆还没向量化——到设置页「视觉」区点一次【回填】·或等新记忆慢慢攒"}
    except Exception:
        pass
    return {"code": "few_playbooks", "action": "",
            "msg": f"星图至少要 3 门已向量的手艺才开图 (现在 {n_pb} 门)——手艺是踩坑之后说「抽成 playbook」攒下来的·用着用着就亮了"}


def _constellation(conn: sqlite3.Connection) -> dict:
    """playbook 星图: centroid → PCA 2D + ≥阈值连边 + 簇编号 (并查集)。"""
    import numpy as np

    pbs = _load_pb_vectors(conn)
    names = sorted(pbs)
    if len(names) < 3:
        return {"points": [], "edges": [], "clusters": 0,
                "empty_reason": _constellation_empty_reason(conn, len(names))}

    X = np.stack([pbs[n]["centroid"] for n in names])
    Xc = X - X.mean(axis=0)
    try:
        u, s, _vt = np.linalg.svd(Xc, full_matrices=False)
        coords = u[:, :3] * s[:3]  # 3 维 · 前端 Three.js 星图
    except Exception as e:
        logger.warning("memory_map PCA 失败: %s", e)
        coords = np.zeros((len(names), 3))

    # 归一化到 [-1, 1] · 前端好画
    for axis in range(3):
        lo, hi = float(coords[:, axis].min()), float(coords[:, axis].max())
        span = hi - lo
        if span > 1e-9:
            coords[:, axis] = (coords[:, axis] - lo) / span * 2 - 1

    # 连边 + 簇 (并查集)
    parent = list(range(len(names)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    edges = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            sim = float(X[i] @ X[j])  # centroid 已归一 → 点积 = cosine
            if sim >= _CLUSTER_THRESHOLD:
                edges.append([i, j, round(sim, 3)])
                pi, pj = find(i), find(j)
                if pi != pj:
                    parent[pi] = pj

    # 只给多成员簇编号 (0,1,2...) · 单点统一 -1 (孤星) · 前端按簇着色不碎
    root_members: dict[int, list[int]] = {}
    for i in range(len(names)):
        root_members.setdefault(find(i), []).append(i)
    cluster_ids: dict[int, int] = {}
    for root, members in root_members.items():
        if len(members) > 1:
            cluster_ids[root] = len(cluster_ids)

    loaded = _loaded_playbooks()
    points = [
        {
            "id": names[i],
            "x": round(float(coords[i, 0]), 4),
            "y": round(float(coords[i, 1]), 4),
            "z": round(float(coords[i, 2]), 4),
            "chars": pbs[names[i]]["chars"],
            "loaded": names[i] in loaded,
            "cluster": cluster_ids.get(find(i), -1),
        }
        for i in range(len(names))
    ]
    return {"points": points, "edges": edges, "clusters": len(cluster_ids),
            "cluster_names": _name_clusters(points)}


def _name_clusters(points: list[dict]) -> dict[str, str]:
    """给每个多成员簇起星系名: 簇内 slug 标题按分隔符 split 成 token 取高频。

    playbook 标题是 slug 化的关键词序列 (daemonkey-发布-一条龙-...) ·
    连字符本来就是词边界 · 比字符 n-gram 可靠。 只收 ≥2 字符的 token ·
    中文 token 优先于纯英文。 返回 {cluster_id: 名字} · 前端悬浮显示。
    """
    from collections import Counter

    by_cluster: dict[int, list[str]] = {}
    for p in points:
        if p["cluster"] >= 0:
            by_cluster.setdefault(p["cluster"], []).append(p["id"])

    out: dict[str, str] = {}
    for cid, titles in by_cluster.items():
        cnt: Counter = Counter()
        for t in titles:
            for tok in re.split(r"[^一-鿿a-zA-Z0-9]+", t):
                if len(tok) >= 2:
                    cnt[tok] += 1
        # 至少在 2 个标题里出现过的才算簇特征 · 中文优先
        common = [(tok, c) for tok, c in cnt.most_common(30) if c >= 2]
        zh = [tok for tok, _ in common if re.search(r"[一-鿿]", tok)]
        label = (zh[0] if zh else (common[0][0] if common else titles[0][:4]))
        out[str(cid)] = f"{label}星系"
    return out


def _norm_pb_id(pid: str) -> str:
    """inject_used 存 `pb-<标题>` · inject_log 的 items 存裸标题 —— 剥前缀对齐。"""
    pid = str(pid).strip()
    return pid[3:] if pid.startswith("pb-") else pid


def _loaded_playbooks() -> set[str]:
    """inject_used.jsonl 里 load 过的 playbook id 集合 (漏斗的分母侧)。"""
    out = set()
    if INJECT_USED.exists():
        for line in INJECT_USED.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            pid = row.get("id") or row.get("playbook_id")
            if pid:
                out.add(_norm_pb_id(pid))
    return out


def _funnel() -> dict:
    """递送漏斗: 注入次数 / 被递送的不同 playbook / load 过的 / 转化率。"""
    injected_ids: dict[str, int] = {}
    n_inj = 0
    if INJECT_LOG.exists():
        for line in INJECT_LOG.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("kind") != "playbook":
                continue
            n_inj += 1
            for it in row.get("items") or []:
                k = _norm_pb_id(it)
                injected_ids[k] = injected_ids.get(k, 0) + 1
    loaded = _loaded_playbooks()
    both = set(injected_ids) & loaded
    return {
        "inject_events": n_inj,
        "delivered": len(injected_ids),
        "loaded": len(both),
        "never_loaded": len(set(injected_ids) - loaded),
        "rate": round(len(both) / len(injected_ids), 3) if injected_ids else None,
    }


def _sources(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT source, COUNT(*), SUM(embedding IS NOT NULL) FROM memory_chunks GROUP BY source ORDER BY 2 DESC"
    ).fetchall()
    return [{"source": s or "?", "count": c, "embedded": e or 0} for s, c, e in rows]


def _hygiene(conn: sqlite3.Connection) -> dict:
    """卫生闸现状: 规则版本 + 当前还剩多少噪音 (dry_run 现算 · 只读)。"""
    from workers import memory_hygiene as mh

    rep = mh.purge_noise(conn, dry_run=True)
    return {
        "version": mh.HYGIENE_VERSION,
        "migrated": not mh.needs_migration(conn),
        "remaining_noise": rep["total"],
        "by_rule": rep["by_rule"],
    }


def _notebook_tiers() -> dict:
    """画像分层实测: 全量 vs 分层后字符数。"""
    from workers.notebook_tiers import split_tiers

    for fn in ("OWNER-NOTEBOOK.md", "BRO-NOTEBOOK.md"):
        p = ROOT / "soul" / fn
        if p.exists():
            full = p.read_text(encoding="utf-8")
            core, archived = split_tiers(full)
            return {
                "full_chars": len(full),
                "core_chars": len(core),
                "archived": [{"title": t, "chars": n} for t, n in archived],
            }
    return {"full_chars": 0, "core_chars": 0, "archived": []}


def build_memory_map(lite: bool = False) -> dict:
    """成长档案「记忆星图」tab 的全部数据 · 一次返。

    lite=True: BI 看板记忆卡专用 · 只返回秒出的数字 (总量/手艺数/卫生版本/画像分层) ·
    跳过 PCA + 卫生 dry_run 全库扫 + 漏斗 jsonl 扫 (全量实测 4.4s · lite 目标 <100ms)。
    """
    if not DB_PATH.exists():
        return {"error": "memory_index.db 不存在"}
    conn = sqlite3.connect(str(DB_PATH))
    try:
        total = conn.execute("SELECT COUNT(*) FROM memory_chunks").fetchone()[0]
        if lite:
            from workers import memory_hygiene as mh

            pb_count = conn.execute(
                "SELECT COUNT(DISTINCT section) FROM memory_chunks WHERE source='skill'"
            ).fetchone()[0]
            return {
                "lite": True,
                "total_chunks": total,
                "playbook_count": pb_count,
                "hygiene": {"version": mh.HYGIENE_VERSION,
                            "migrated": not mh.needs_migration(conn)},
                "notebook": _notebook_tiers(),
            }
        return {
            "total_chunks": total,
            "constellation": _constellation(conn),
            "sources": _sources(conn),
            "hygiene": _hygiene(conn),
            "notebook": _notebook_tiers(),
            "funnel": _funnel(),
        }
    finally:
        conn.close()
