"""
agent_tools/audit_playbooks.py
==============================

0.9.6 · 手艺判重体检 (BRO 拍板: playbook 面板 + 记忆星图加按钮 · 点击自动发
"帮我看看手艺是不是有重复的" → 搭档调本工具出簇清单 → 不确定的簇摆给用户选)。

why: playbook 越攒越多必然出现语义重复 (同一主题写了两版/旧版忘了 retired)。
母体 2026-08-20 实测 68 门手艺里 4 簇重复 (cosine ≥ 0.80 · 跟星图连边同口径)。
判重依据是 memory_chunks 里 skill 源的 embedding 质心 —— 库是单一真源 · 现算不缓存。

档位：AUTO · 纯只读 (合并动作由用户拍板后 · 搭档用文件工具执行 · 本工具不碰写)
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "memory_index.db"


def _summarize(args: dict) -> str:
    return f"audit_playbooks · 阈值 {args.get('threshold', 0.80)}"


def _run(args: dict) -> ToolResult:
    try:
        threshold = float(args.get("threshold") or 0.80)
    except (TypeError, ValueError):
        threshold = 0.80
    threshold = max(0.5, min(threshold, 0.99))

    if not _DB_PATH.exists():
        return ToolResult(False, "", "memory_index.db 不存在 · 还没有记忆索引")

    import numpy as np

    conn = sqlite3.connect(str(_DB_PATH))
    try:
        rows = conn.execute(
            "SELECT section, content, embedding FROM memory_chunks "
            "WHERE source='skill' AND embedding IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()

    # 按 playbook 聚合 (section 前缀 = playbook 标题) · 质心 + 总字符数
    pbs: dict[str, dict] = defaultdict(lambda: {"vecs": [], "chars": 0})
    for section, content, emb in rows:
        name = (section or "").split(":")[0]
        if not name:
            continue
        pbs[name]["vecs"].append(np.frombuffer(emb, dtype=np.float32))
        pbs[name]["chars"] += len(content or "")

    names = sorted(pbs)
    if len(names) < 2:
        return ToolResult(True, f"只有 {len(names)} 门手艺有向量 · 凑不成对 · 无需判重")

    centroids = {}
    for n in names:
        c = np.mean(pbs[n]["vecs"], axis=0)
        centroids[n] = c / (float(np.linalg.norm(c)) + 1e-9)

    # 两两相似度 ≥ 阈值聚簇 (并查集)
    parent = {n: n for n in names}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    pair_sims: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            s = float(centroids[names[i]] @ centroids[names[j]])
            if s >= threshold:
                pair_sims[names[i]].append((names[j], s))
                pair_sims[names[j]].append((names[i], s))
                parent[find(names[i])] = find(names[j])

    clusters: dict[str, list[str]] = defaultdict(list)
    for n in names:
        clusters[find(n)].append(n)
    dup_clusters = [sorted(v) for v in clusters.values() if len(v) > 1]
    dup_clusters.sort(key=len, reverse=True)

    if not dup_clusters:
        return ToolResult(
            True,
            f"{len(names)} 门手艺 · 阈值 {threshold} · 没有发现重复簇 · 手艺箱很干净",
        )

    lines = [f"{len(names)} 门手艺 · 阈值 {threshold} · 发现 {len(dup_clusters)} 个重复簇："]
    for idx, members in enumerate(dup_clusters, 1):
        # 建议保留字符最多的 (信息量最全) · 其余标 retired 候选
        keeper = max(members, key=lambda m: pbs[m]["chars"])
        lines.append(f"\n簇 {idx} ({len(members)} 门) · 建议保留「{keeper}」({pbs[keeper]['chars']:,} 字符):")
        for m in members:
            sims = ", ".join(f"{s:.2f}" for _, s in sorted(pair_sims[m], key=lambda x: -x[1]))
            tag = " ← 保留" if m == keeper else " ← retired 候选"
            lines.append(f"  - {m} ({pbs[m]['chars']:,} 字符 · 簇内相似度 {sims}){tag}")
    lines.append(
        "\n合并方式 (用户拍板后执行): 把 retired 候选的独有内容并入保留版 · "
        "候选文件改名 <标题>.retired.md (卫生闸 v2 自动把它挡出索引)。"
    )
    return ToolResult(True, "\n".join(lines))


SPEC = ToolSpec(
    name="audit_playbooks",
    description=(
        "Audit playbooks (skills) for semantic duplicates using embedding centroids. "
        "When the user asks 'are any of my skills/playbooks duplicates?' or wants to tidy "
        "the skill box, run this and present the clusters. Read-only: merging requires the "
        "user's explicit pick, then merge via file tools (fold unique content into the keeper, "
        "rename the others to <title>.retired.md — hygiene gate v2 excludes them from the index)."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "threshold": {
                "type": "number",
                "description": "cosine similarity threshold 0.5-0.99 · default 0.80 (same as star-map edges) · lower = wider net",
            },
        },
        "required": [],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
