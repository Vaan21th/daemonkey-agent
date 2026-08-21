"""
agent_tools/manage_hygiene_rules.py
====================================

0.9.6 · 噪音治理搭档自治 (BRO 拍板: "你可以判断你要记哪些东西·哪些我完全不关心")。

OPUS 反刍自己的记忆库时发现噪音模式 → 自己写一条本地规则 →
下次清理 (启动时 migrate / 手动) 自动生效。 规则落在 data/my_hygiene_rules.json ·
跟母体内置规则 (workers/memory_hygiene.py) 并行 · 互不覆盖。

架构红线 (写进 ROADMAP 的): 判断权在搭档 · 但判断发生在**治理层** (可逆 ·
jsonl 原文永远在 · rebuild 可恢复) · 不在**入库层** (不可逆)。 入库永远全收。

档位：CONFIRM · 写本地规则文件 · 不碰库 (清理由 hygiene migrate 执行)

actions:
  - add · 加一条规则 (name + match 必填 · source 可选限定 · reason 备忘)
  - list · 看现有本地规则
  - remove · 按 name 删一条
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool

_RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "my_hygiene_rules.json"


def _load() -> dict:
    if not _RULES_PATH.exists():
        return {"rules": []}
    try:
        data = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("rules"), list):
            return data
    except Exception:
        pass
    return {"rules": []}


def _save(data: dict) -> None:
    _RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RULES_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _summarize(args: dict) -> str:
    action = (args.get("action") or "list").lower()
    if action == "add":
        return f"加卫生规则 · {args.get('name', '?')[:30]}"
    if action == "remove":
        return f"删卫生规则 · {args.get('name', '?')[:30]}"
    return "manage_hygiene_rules · list"


def _run(args: dict) -> ToolResult:
    action = (args.get("action") or "list").lower().strip()
    data = _load()
    rules = data["rules"]

    if action == "add":
        name = (args.get("name") or "").strip()
        match = (args.get("match") or "").strip()
        source = (args.get("source") or "").strip()
        reason = (args.get("reason") or "").strip()
        if not name or not match:
            return ToolResult(False, "add 需要 name 和 match (match 是 substring · 命中即噪音)")
        if len(match) < 6:
            return ToolResult(
                False,
                f"match 只有 {len(match)} 字符 · 太短会误伤一片 · 至少 6 字符 · "
                "挑这段噪音里独一无二的一句",
            )
        if any(r.get("name") == name for r in rules):
            return ToolResult(False, f"规则名「{name}」已存在 · 换个名或先 remove")
        rules.append({
            "name": name,
            "match": match,
            **({"source": source} if source else {}),
            "reason": reason,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        _save(data)
        scope = f" · 仅 source={source}" if source else " · 全来源"
        return ToolResult(
            True,
            f"规则「{name}」已加入本地层{scope} · 命中串: 「{match[:50]}」\n"
            f"下次启动 (或 hygiene migrate) 时生效清理 · 判错可恢复 (jsonl 原文永远在)",
        )

    if action == "list":
        if not rules:
            return ToolResult(True, "本地规则层为空 · 母体内置规则在 workers/memory_hygiene.py")
        lines = [f"本地自治规则 {len(rules)} 条:"]
        for r in rules:
            scope = f" [source={r['source']}]" if r.get("source") else ""
            lines.append(f"  · {r['name']}{scope} · 命中「{str(r.get('match', ''))[:40]}」 · {r.get('reason', '')[:50]}")
        return ToolResult(True, "\n".join(lines))

    if action == "remove":
        name = (args.get("name") or "").strip()
        before = len(rules)
        data["rules"] = [r for r in rules if r.get("name") != name]
        if len(data["rules"]) == before:
            return ToolResult(False, f"没找到规则「{name}」")
        _save(data)
        return ToolResult(True, f"规则「{name}」已删 · 已被它清掉的 chunk 不会自动回来 (rebuild 才恢复) · 但它不会再误伤新的")

    return ToolResult(False, f"未知 action: {action} · 支持 add / list / remove")


SPEC = ToolSpec(
    name="manage_hygiene_rules",
    description=(
        "Manage LOCAL memory-hygiene rules (data/my_hygiene_rules.json) — the companion's own "
        "layer, parallel to the built-in rules. When you notice a recurring noise pattern in "
        "recalled memories (e.g. a template sentence, a test artifact), add a rule: match is a "
        "literal substring (min 6 chars · pick a phrase unique to the noise), optional source "
        "limits it to one source (session/skill/...). Rules take effect on next hygiene migrate "
        "(daemon restart). Deletions are recoverable (session jsonl originals always exist) — "
        "but be conservative anyway: prefer narrow matches over broad ones."
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "list", "remove"],
                "description": "add=new local rule / list=show all / remove=delete by name",
            },
            "name": {
                "type": "string",
                "description": "add/remove: rule name (unique · short · e.g. 'wechat_sync_footer')",
            },
            "match": {
                "type": "string",
                "description": "add: literal substring that marks noise (min 6 chars · must be unique to the noise pattern)",
            },
            "source": {
                "type": "string",
                "description": "add: optional · limit to one source (session / session_summary / skill / BRO-NOTEBOOK ...)",
            },
            "reason": {
                "type": "string",
                "description": "add: why this is noise (memo for future self)",
            },
        },
        "required": ["action"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
