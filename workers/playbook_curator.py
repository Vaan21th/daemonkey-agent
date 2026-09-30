"""workers/playbook_curator.py
=============================
操作手册的自动整理 (wish-fa1699c1 后续 · 第 3 步 · 2026-09-29)。

## 为什么需要它

手册 300+ 份，重复簇一直有 —— `audit_playbooks` 早就能查出来，但**最后一步
(合并) 要人拍板，而人不会来**。BRO 原话:

> 「你不可能让用户陪着你每周去讨论一下什么留什么不留，为一个根本不确定收益的东西」

这一层就是把那一脚接上: 每周自动体检 → 合并高置信度簇 → 备份 → 留报告。

## 安全设计 (敢自动的底气)

1. **只增不删** —— LLM 的活是把候选里「保留版没有的」并进去；原信息不许丢
2. **原稿全备份** —— `data/playbooks/_retired_archive/<时间戳>/`
3. **候选走状态机退休** —— `set_stale_state(id, '退休')`，不删文件、可恢复
4. **限速** —— 一次最多合 1 个簇 (宁可分几周，不要一口气重写整个书架)
5. **高阈值** —— 默认 0.86 (星图连线 0.80) · 只动「几乎肯定重复」的
6. **失败即停** —— LLM 出错 / 输出不合格 → 这一轮整个不动 (宁可下次，不要半成品)
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAYBOOKS_DIR = ROOT / "data" / "playbooks"
ARCHIVE_DIR = PLAYBOOKS_DIR / "_retired_archive"
REPORT_DIR = ROOT / "data" / "runtime" / "playbook_curation"

logger = logging.getLogger("opus.playbook_curator")

AUTO_MERGE_THRESHOLD = 0.86
MAX_CLUSTERS_PER_RUN = 1

_MERGE_SYSTEM = (
    "你是操作手册的管理员。给你一份「保留版」和若干份「候选」。\n"
    "任务：把候选里**保留版没有的**内容并进保留版。\n\n"
    "硬规则：\n"
    "1. 只增不删 —— 保留版原有的信息一个字都不许丢，不许改写它的意思。\n"
    "2. 只并真正的新信息 —— 候选里与保留版重复的、或明显更差的说法，直接丢掉。\n"
    "3. 输出必须是 JSON 对象，键: steps / pitfalls / lessons，值是 markdown 文本。\n"
    "4. 没把握就别动那一段 —— 原样返回保留版那一段。\n"
)


def _pb_file(slug: str) -> Path:
    return PLAYBOOKS_DIR / f"{slug}.md"


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def cluster_members(threshold: float = AUTO_MERGE_THRESHOLD) -> list[list[dict]]:
    """重复簇 (按质心 cosine) → [[{id,title,slug,chars}, ...], ...] · 大的排前。

    复用 playbook_cluster.clusters —— 判重只有一份实现 (与星图连边 / 体检工具同口径)。
    """
    from workers import playbook_cluster
    from workers.playbooks import list_playbooks

    groups = playbook_cluster.clusters(threshold)
    if not groups:
        return []

    # 向量表的 key 是 slug（不是 title）—— 2026-09-29 实测踩过:
    # 按 title 匹配 319 条只命中 10 条，按 slug 才对得上。
    by_slug: dict[str, dict] = {}
    for pb in list_playbooks():
        s = (pb.get("slug") or "").strip()
        if s:
            by_slug.setdefault(s, pb)

    out: list[list[dict]] = []
    for g in groups:
        members: list[dict] = []
        for name in g:
            pb = by_slug.get(name)
            if not pb:
                continue
            body = _read(_pb_file(pb.get("slug") or ""))
            members.append({
                "id": pb.get("id"), "title": pb.get("title") or name,
                "slug": pb.get("slug", ""), "chars": len(body),
            })
        if len(members) > 1:
            out.append(sorted(members, key=lambda m: -m["chars"]))
    return out


def _backup(paths: list[Path], stamp: str) -> Path:
    d = ARCHIVE_DIR / stamp
    d.mkdir(parents=True, exist_ok=True)
    for p in paths:
        try:
            if p.exists():
                shutil.copy2(p, d / p.name)
        except Exception as e:
            logger.warning("备份失败 %s (%s)", p.name, e)
    return d


def _llm_merge(keeper: str, others: list[tuple[str, str]]) -> dict | None:
    """让 LLM 出合并后的 steps/pitfalls/lessons。失败返回 None (调用方整簇跳过)。"""
    from workers.state_condenser import _call_llm

    user = f"## 保留版\n\n{keeper}\n\n"
    for t, c in others:
        user += f"## 候选: {t}\n\n{c}\n\n"
    raw, _usage, err = _call_llm(_MERGE_SYSTEM, user)
    if err or not (raw or "").strip():
        logger.warning("合并 LLM 失败: %s", err)
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        logger.warning("合并 LLM 输出里没有 JSON")
        return None
    try:
        data = json.loads(m.group(0))
    except Exception as e:
        logger.warning("合并 JSON 解析失败: %s", e)
        return None
    return data if isinstance(data, dict) else None


def _write_report(stamp: str, report: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    p = REPORT_DIR / f"{stamp}.json"
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def latest_report() -> dict | None:
    """最近一次整理的报告 (给看板/节律条显示「上次并了啥」)。"""
    if not REPORT_DIR.exists():
        return None
    files = sorted(REPORT_DIR.glob("*.json"), reverse=True)
    if not files:
        return None
    try:
        return json.loads(files[0].read_text(encoding="utf-8"))
    except Exception:
        return None


def curate(*, threshold: float = AUTO_MERGE_THRESHOLD,
           max_clusters: int = MAX_CLUSTERS_PER_RUN,
           dry_run: bool = False) -> dict:
    """体检 + 自动合并高置信度重复簇。返回报告 dict (同时落盘一份)。

    dry_run=True 只看不改（给看板预览 / 首轮观察用）。
    """
    from workers.playbooks import revise_playbook, set_stale_state

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    groups = cluster_members(threshold)
    report: dict = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "threshold": threshold, "dry_run": dry_run,
        "clusters_found": len(groups),
        "merged": [], "skipped": [],
    }

    if not groups:
        report["note"] = "没有重复簇 · 手册很干净"
        _write_report(stamp, report)
        return report

    for g in groups[:max_clusters]:
        keeper, others = g[0], g[1:]
        kpath = _pb_file(keeper["slug"])
        ktext = _read(kpath)
        if not ktext:
            report["skipped"].append({"keeper": keeper["title"], "why": "保留版读不到"})
            continue

        opaths = [_pb_file(o["slug"]) for o in others]
        otexts = [(o["title"], _read(p)) for o, p in zip(others, opaths)]

        if dry_run:
            report["skipped"].append({
                "keeper": keeper["title"], "why": "dry_run",
                "would_merge": [o["title"] for o in others],
            })
            continue

        merged = _llm_merge(ktext, otexts)
        if not merged:
            report["skipped"].append({
                "keeper": keeper["title"], "why": "LLM 没给出可用结果 · 整簇不动",
            })
            continue

        archive = _backup([kpath] + opaths, stamp)
        res = revise_playbook(
            keeper["id"],
            steps=(merged.get("steps") or None),
            pitfalls=(merged.get("pitfalls") or None),
            lessons=(merged.get("lessons") or None),
        )
        if res.get("error"):
            report["skipped"].append({
                "keeper": keeper["title"], "why": f"revise 失败: {res['error']}",
            })
            continue

        retired_pairs = [(o["id"], o["title"]) for o in others if set_stale_state(o["id"], "退休")]
        retired = [t for _, t in retired_pairs]
        report["merged"].append({
            "keeper": keeper["title"], "keeper_id": keeper["id"],
            "retired": retired,
            "retired_ids": [i for i, _ in retired_pairs],
            "backup": str(archive.relative_to(ROOT)).replace("\\", "/"),
        })
        logger.info("手册合并 · 保留「%s」· 退休 %d 份", keeper["title"], len(retired))

    if report["merged"]:
        try:
            from workers.memory_index import incremental_update
            from workers.playbooks import load_playbook
            for m in report["merged"]:
                # 保留者: 正文已被 revise_playbook 换过 → 按新正文重索引
                pb = load_playbook(m.get("keeper_id")) or {}
                meta = pb.get("meta") or {}
                slug = meta.get("slug") or ""
                tt = meta.get("task_type") or "general"
                if slug and pb.get("content"):
                    incremental_update("skill", pb["content"], section=f"{slug}:{tt}")
                # 被退休的: 必须从 FTS5 里撤掉。set_stale_state 只改 _index.json、
                # 不碰索引 —— 不撤的话它还在索引里 · 下个 tick 又聚成同一簇 · 重复合并。
                # (2026-09-29 真跑现场: 18:23 与 18:52 两次 tick 合了同一簇 · 归档里
                #  同名文件两份 · 大小不同 = 这就是那条 WARNING 的实际后果)
                for rid in m.get("retired_ids") or []:
                    rob = load_playbook(rid) or {}
                    rmeta = rob.get("meta") or {}
                    rslug = rmeta.get("slug") or ""
                    rtt = rmeta.get("task_type") or "general"
                    if rslug:
                        incremental_update("skill", "", section=f"{rslug}:{rtt}")
        except Exception as e:
            logger.warning("合并后重建索引失败 (%s) · 下次 tick 会补", e)

    _write_report(stamp, report)
    return report
