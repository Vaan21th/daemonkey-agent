"""agent_tools/list_iron_rules.py
====================================

 K stage 2c++ · wish-a72b2f0a 配套 · 列现有铁律编号 + 标题

LLM 调 add_iron_rule 之前 · 必须先调这个看现有最大编号 · 取 max+1。
也用来诊断 (用户 问『现在有几条铁律』时直接调这个)。

tier: TIER_AUTO (只读 metadata)
"""

from __future__ import annotations

import re
from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


ROOT = Path(__file__).resolve().parent.parent
DAEMON_RULES_PATH = ROOT / "data" / "cognition" / "daemon_rules.md"


def _summarize(args: dict) -> str:
    return "列 daemon_rules.md 现有铁律 (编号 + 标题) · LLM 加铁律前查重必备"


def _run(args: dict) -> ToolResult:
    if not DAEMON_RULES_PATH.exists():
        return ToolResult(ok=False, output="", error=f"daemon_rules.md 不存在: {DAEMON_RULES_PATH}")

    text = DAEMON_RULES_PATH.read_text(encoding="utf-8")

    #  II · wish-ff100836 · 解析 domain 注释 (与 add_iron_rule 写出格式呼应)
    # 把整个 daemon_rules.md 按 `## 铁律 N · TITLE` 切段 · 每段抽 `<!-- domain: X -->`
    header_re = re.compile(r"^## 铁律 (\d+)\s+·\s+(.+)$", re.MULTILINE)
    domain_re = re.compile(r"<!--\s*domain:\s*(\w+)\s*-->")
    matches = list(header_re.finditer(text))
    rules = []
    for idx, m in enumerate(matches):
        try:
            num = int(m.group(1))
        except ValueError:
            continue
        title = m.group(2).strip()
        title_main = re.sub(r"\s*\([^)]*\)\s*$", "", title)
        # 段 body 范围 = 当前 match 到下一个 match (或 anchor)
        body_start = m.end()
        body_end = matches[idx + 1].start() if (idx + 1 < len(matches)) else len(text)
        body = text[body_start:body_end]
        domain_match = domain_re.search(body)
        domain = domain_match.group(1).strip().lower() if domain_match else "global"
        rules.append({"n": num, "title": title_main, "domain": domain})

    rules.sort(key=lambda r: r["n"])

    if not rules:
        return ToolResult(ok=True, output="(daemon_rules.md 没匹配 `## 铁律 N · ...` 格式 · 文件可能损坏)")

    # 按 domain 分组统计
    by_domain: dict[str, list[dict]] = {}
    for r in rules:
        by_domain.setdefault(r["domain"], []).append(r)

    lines = [
        f"# 现有铁律 (共 {len(rules)} 条 · 加新铁律传 rule_number={rules[-1]['n'] + 1})",
        "",
        "## 按 domain 分组 (wish-ff100836  II)",
        "",
    ]
    for dom in sorted(by_domain.keys()):
        lines.append(f"### `{dom}` ({len(by_domain[dom])} 条)")
        for r in by_domain[dom]:
            lines.append(f"  - **铁律 {r['n']}** · {r['title']}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("→ 调 `add_iron_rule` 加新条目 · rule_number 必须 = " + str(rules[-1]["n"] + 1))
    lines.append("→ domain 默认 'global' (所有场景看见) · 可选 self_evolution / app_creation / workflow_creation / client_ops / production / reflection")

    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="list_iron_rules",
    description=(
        "列 daemon_rules.md 现有所有铁律 (编号 + 标题) · 给 LLM 加铁律前查重用\n\n"
        "**用途**:\n"
        "  - 调 add_iron_rule 之前 · 看现有最大编号 · 取 max+1 (防漏编 / 撞号)\n"
        "  - 用户 问『现在工程多少条铁律』时直接调这个回\n"
        "  - OPUS 自己反思想加铁律前 · 看是否已有同类规则 (避免重复)"
    ),
    tier=TIER_AUTO,
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
