"""
agent_tools/audit_playbooks.py
==============================

0.9.6 · 手艺判重体检 (BRO 拍板: playbook 面板 + 记忆星图加按钮 · 点击自动发
"帮我看看手艺是不是有重复的" → 搭档调本工具出簇清单 → 不确定的簇摆给用户选)。

2026-09-29 改 (wish-0ce03cae) · 两处:
  ① 判重收成单一真源 —— 改走 playbook_curator.cluster_members()
     (内部复用 playbook_cluster.clusters · 与星图连边 / 自动整理同口径)。
     原来本工具自带一套并查集 @0.80 · 与 curator 的 @0.86 各长一套 = 铁律 6 违规
     (两套实现会各自长歪 · 而且用户不会发现 · 因为看起来都能跑)。
  ② 补上「最后一脚」—— action='curate' 当场合 (先备份 + 候选走退休状态机 · 可捞回)。
     原来只出清单 · BRO 拍完板没地方按下去 · 只能等每周 tick。

why: playbook 越攒越多必然出现语义重复 (同一主题写了两版/旧版忘了 retired)。
判重依据是 memory_chunks 里 skill 源的 embedding 质心 —— 库是单一真源 · 现算不缓存。

档位：AUTO。audit 分支纯只读；curate 分支会写盘 (备份 + 状态机)，
      靠 confirm=true 自把关 (不带 confirm 只回确认提示 · 不动文件)。
"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    act = (args.get("action") or "audit").strip().lower()
    return f"audit_playbooks · {act} · 阈值 {args.get('threshold', 0.80)}"


def _pb_total() -> int:
    try:
        from workers.playbooks import list_playbooks
        return len(list_playbooks())
    except Exception:
        return 0


def _run_audit(threshold: float) -> ToolResult:
    """只读体检 —— 判重走 playbook_curator.cluster_members() (单一真源)。"""
    from workers.playbook_curator import cluster_members

    groups = cluster_members(threshold)
    total = _pb_total()
    if not groups:
        return ToolResult(
            True,
            f"{total} 份操作手册 · 阈值 {threshold} · 没有发现重复簇 · 操作手册很干净",
        )

    lines = [f"{total} 份操作手册 · 阈值 {threshold} · 发现 {len(groups)} 个重复簇："]
    for idx, members in enumerate(groups, 1):
        keeper = members[0]          # cluster_members 已按字符数降序
        lines.append(
            f"\n簇 {idx} ({len(members)} 份) · 建议保留「{keeper['title']}」"
            f"({keeper['chars']:,} 字符):"
        )
        for m in members:
            tag = " ← 保留" if m is keeper else " ← 合并候选"
            lines.append(f"  - {m['title']} ({m['chars']:,} 字符){tag}")
    lines.append(
        "\n要合并的话两条路：\n"
        "  · 当场合 —— 再调一次本工具 action='curate' + confirm=true（原稿先备份 · "
        "候选走「退休」状态机不删文件可捞回 · 一次最多合 1 簇）\n"
        "  · 等自动 —— 每周 tick 的 playbook_curator 自己会合（同一套阈值与备份）"
    )
    return ToolResult(True, "\n".join(lines))


def _run_curate(args: dict, threshold: float) -> ToolResult:
    """真合并 —— 复用 playbook_curator.curate() (备份 + 状态机 + 幂等)。"""
    from workers.playbook_curator import curate

    dry = bool(args.get("dry_run"))
    if not dry and not args.get("confirm"):
        return ToolResult(
            True,
            "合并会真改手册文件。安全网：原稿先备份到 "
            "data/playbooks/_retired_archive/<时间戳>/ · 被合掉的候选走「退休」状态机"
            "（不删文件 · set_stale_state 可捞回）· 一次最多合 1 簇。\n"
            "确认要合：action='curate' + confirm=true。只想先看会合哪一簇：+ dry_run=true。",
        )

    rep = curate(threshold=threshold, dry_run=dry)
    out = [f"手册整理 · 阈值 {threshold} · dry_run={dry}"]
    merged = rep.get("merged") or []
    skipped = rep.get("skipped") or []
    found = rep.get("clusters_found", 0)
    if not found:
        return ToolResult(True, f"{_pb_total()} 份操作手册 · 阈值 {threshold} · 没有重复簇 · 很干净")

    out.append(f"发现 {found} 个重复簇 · 本轮处理 {len(merged) + len(skipped)} 个")
    for m in merged:
        retired = m.get("retired") or []
        out.append(
            f"\n✓ 已合并 · 保留「{m.get('keeper')}」\n"
            f"  退休 {len(retired)} 份：" + "、".join(retired) + "\n"
            f"  备份：{m.get('backup')}\n"
            f"  索引已重建 · 捞回候选：set_stale_state(<id>, '正常')"
        )
    for s in skipped:
        if s.get("why") == "dry_run":
            out.append(
                f"\n（预览）会合「{s.get('keeper')}」← " + "、".join(s.get("would_merge") or [])
            )
        else:
            out.append(f"\n✗ 跳过「{s.get('keeper')}」· {s.get('why')}")

    rest = found - len(merged) - len(skipped)
    if rest > 0:
        out.append(
            f"\n还剩 {rest} 个簇 · 限速一次 1 个（宁可分几次，不要一口气重写书架）· 下次 tick 接着来"
        )
    return ToolResult(True, "\n".join(out))


def _run(args: dict) -> ToolResult:
    action = (args.get("action") or "audit").strip().lower()
    if action not in ("audit", "curate"):
        return ToolResult(False, "", f"action 只能是 audit 或 curate · 收到 {action!r}")

    default_th = 0.86 if action == "curate" else 0.80
    try:
        threshold = float(args.get("threshold") or default_th)
    except (TypeError, ValueError):
        threshold = default_th
    threshold = max(0.5, min(threshold, 0.99))

    if action == "curate":
        return _run_curate(args, threshold)
    return _run_audit(threshold)


SPEC = ToolSpec(
    name="audit_playbooks",
    description=(
        "查操作手册是否语义重复，或把重复的当场合并。他说「操作手册有没有重复 / 整理操作手册」时调。"
        "action='audit'（默认）只读出簇清单；action='curate' 真合并（先备份 · 需 confirm=true）。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["audit", "curate"],
                "description": "audit 只读体检（默认）· curate 真合并（先备份 · 候选退休）",
            },
            "confirm": {
                "type": "boolean",
                "description": "curate 必填 true —— 不带只返回确认提示，不动文件",
            },
            "dry_run": {
                "type": "boolean",
                "description": "curate 时只预览会合哪一簇，不改文件",
            },
            "threshold": {
                "type": "number",
                "description": "cosine 阈值 0.5-0.99 · audit 默认 0.80 · curate 默认 0.86（同自动整理）",
            },
        },
        "required": [],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
