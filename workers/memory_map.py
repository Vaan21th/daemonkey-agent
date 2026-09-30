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
import time
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "memory_index.db"
INJECT_LOG = ROOT / "data" / "runtime" / "inject_log.jsonl"
INJECT_USED = ROOT / "data" / "runtime" / "inject_used.jsonl"

_CLUSTER_THRESHOLD = 0.80  # 跟判重清单同口径

# 星图重活缓存 (2026-09-29 · BRO: "有新的就只缓存新的, 不会越用越慢")
#   why: _hygiene 要全库扫 11 万条 chunks 数噪音 —— 实测 5.9s, 占 /memory_map 总耗时 85%。
#   星图是「看板」不是「账本」· 分钟级陈旧可接受, 每次现算 7 秒不可接受。
#   TTL 分开: 噪音数变很慢给 30 分钟 · 点云图 5 分钟足够新。
_CACHE: dict = {}


def _cached(key: str, ttl: float, fn):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and (now - hit[0]) < ttl:
        return hit[1]
    val = fn()
    _CACHE[key] = (now, val)
    return val


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
                    "msg": "星图靠语义向量把相似操作手册聚成星系·但embedding服务还没配——配上后历史记忆自动向量化·星图就亮"}
        st = stats(conn)
        if st.get("total", 0) > 0 and st.get("covered", 0) == 0:
            return {"code": "no_vectors", "action": "settings",
                    "msg": "embedding 已配·但历史记忆还没向量化——到设置页「视觉」区点一次【回填】·或等新记忆慢慢攒"}
    except Exception:
        pass
    return {"code": "few_playbooks", "action": "",
            "msg": f"星图至少要 3 份已向量的操作手册才开图 (现在 {n_pb} 份)——操作手册是踩坑之后说「抽成操作手册」攒下来的·用着用着就亮了"}


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
    """画像分层实测: 全量 vs 分层后字符数。

    2026-09-30 wish-27273a5b · 画像拆成一格一文件后改走 identity 句柄 ——
    原来硬找 soul/OWNER-NOTEBOOK.md / BRO-NOTEBOOK.md，两个都不在 →
    画像柜 full_chars/core_chars 恒定 0（星图上「画像」显得空的）。
    """
    from workers.notebook_tiers import split_tiers

    try:
        from identity import owner_notebook_path

        nb = owner_notebook_path(ROOT / "soul")
        if nb.exists():
            full = nb.read_text(encoding="utf-8")
            core, archived = split_tiers(full)
            return {
                "full_chars": len(full),
                "core_chars": len(core),
                "archived": [{"title": t, "chars": n} for t, n in archived],
            }
    except Exception:
        pass
    return {"full_chars": 0, "core_chars": 0, "archived": []}


def _boxes(constellation: dict) -> list[dict]:
    """六个沉淀位（柜子）· 星图全景数据 (2026-09-29 BRO 拍板)。

    why: 星图以前只有「操作手册」一柜 —— 它其实是整个记忆体系的看板，
    却只照到了四分之一。 现在收成六柜，一眼看清「东西放在哪、各占多少、进不进前缀」。

    分工（别越界）: 这里出「有哪些柜子 / 各多少 / 进不进前缀 / **柜里每条是什么**」——
    **空间位置是呈现层的事（前端定），后端不越界**。

    items (2026-09-29 二刀 · BRO): 以前只有操作手册的点是真条目，其他柜的点是前端随机糊的，
    鼠标移上去出不了明细。现在每柜都出逐条 items → 每颗星就是一条，悬停即见。
    """

    def _dir_files(p: Path) -> list[Path]:
        if not p.exists():
            return []
        return [p] if p.is_file() else [f for f in sorted(p.rglob("*.md")) if f.is_file()]

    def _text(p: Path) -> str:
        try:
            return p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    def _dir_chars(p: Path) -> tuple[int, int]:
        fs = _dir_files(p)
        return sum(len(_text(f)) for f in fs), len(fs)

    def _clip(s, n: int = 52) -> str:
        s = re.sub(r"\s+", " ", str(s or "")).strip()
        return s if len(s) <= n else s[: n - 1] + "…"

    nb = _notebook_tiers()
    rules_p = ROOT / "data" / "cognition" / "daemon_rules.md"
    rules_chars, _ = _dir_chars(rules_p)
    rules_txt = _text(rules_p)
    rules_n = len(re.findall(r"(?m)^## 铁律", rules_txt))
    pb_chars, _ = _dir_chars(ROOT / "data" / "playbooks")
    docs_p = ROOT / "data" / "knowledge"
    docs_chars, docs_n = _dir_chars(docs_p)
    arch = nb.get("archived") or []

    # ── 逐条明细：星图上每颗星 = 一条 ─────────────────────
    nb_items: list[dict] = []
    try:
        from workers.notebook_tiers import _iter_sections, is_core_section
        from identity import owner_notebook_path

        # 2026-09-30 wish-27273a5b · 拆格后必须走句柄（原来硬找 BRO-NOTEBOOK.md，
        # 文件已删 → _text 返 "" → 画像柜一颗星都出不来）。
        _nb_txt = owner_notebook_path(ROOT / "soul").read_text(encoding="utf-8")
        for title, body in _iter_sections(_nb_txt):
            if is_core_section(title):
                nb_items.append({"label": _clip(title, 26), "chars": len(body), "sub": "进前缀"})
    except Exception:
        pass

    rules_items: list[dict] = []
    for m in re.finditer(r"(?m)^## (铁律[^\n]*)$", rules_txt):
        nxt = rules_txt.find("\n## ", m.end())
        rules_items.append({
            "label": _clip(m.group(1), 30),
            "chars": (nxt - m.end()) if nxt > 0 else (len(rules_txt) - m.end()),
            "sub": "走操作标准",
        })

    docs_items = []
    for f in _dir_files(docs_p):
        t = _text(f)
        m = re.search(r"(?m)^#\s+(.{1,80})", t)
        docs_items.append({"label": _clip(m.group(1) if m else f.stem, 30),
                           "chars": len(t), "sub": "按需召回"})
    arch_items = [{"label": _clip(a.get("title"), 30), "chars": int(a.get("chars") or 0),
                   "sub": "格满自动沉下来"} for a in arch]

    dec_items: list[dict] = []
    dec_chars, dec_n = 0, 0
    try:
        from workers import wishlist as wl

        for w in (wl.list_wishes() or []):
            if isinstance(w, dict) and w.get("status") == "rejected":
                n = len(json.dumps(w, ensure_ascii=False))
                dec_n += 1
                dec_chars += n
                dec_items.append({"label": _clip(w.get("title"), 30), "chars": n, "sub": "已否掉 · 为什么不做"})
    except Exception:
        pass

    return [
        {"id": "notebook", "label": "画像", "color": "#a99fff", "inject": "full",
         "chars": int(nb.get("core_chars") or 0), "count": len(nb_items),
         "sub": "本体约束 / 怎么跟他干活", "items": nb_items},
        {"id": "rules", "label": "铁律", "color": "#5ee8b0", "inject": "full",
         "chars": rules_chars, "count": rules_n, "sub": "走操作标准 · 不参与升降",
         "items": rules_items},
        {"id": "playbooks", "label": "操作手册", "color": "#ffc45c", "inject": "recall",
         "chars": pb_chars, "count": len(constellation.get("points") or []), "sub": "原星图的家"},
        {"id": "archive", "label": "归档层", "color": "#7cc8ff", "inject": "none",
         "chars": sum(int(a.get("chars") or 0) for a in arch), "count": len(arch),
         "sub": "格子满了自动沉下来", "items": arch_items},
        {"id": "docs", "label": "知识库", "color": "#ff9ec9", "inject": "recall",
         "chars": docs_chars, "count": docs_n, "sub": "私有文档 · 按需召回",
         "items": docs_items},
        {"id": "decisions", "label": "决策留痕", "color": "#c3b6ff", "inject": "recall",
         "chars": dec_chars, "count": dec_n, "sub": "否掉过什么 · 为什么",
         "items": dec_items},
    ]


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
        constellation = _cached("constellation", 300, lambda: _constellation(conn))
        return {
            "total_chunks": total,
            "constellation": constellation,
            "boxes": _boxes(constellation),
            "sources": _sources(conn),
            "hygiene": _cached("hygiene", 1800, lambda: _hygiene(conn)),
            "notebook": _notebook_tiers(),
            "funnel": _funnel(),
        }
    finally:
        conn.close()
