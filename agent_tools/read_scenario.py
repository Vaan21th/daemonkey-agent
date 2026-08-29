"""
agent_tools/read_scenario.py
============================

 II · wish-af1245d7 · 按需读场景化铁律细则

设计动机:
  当前 daemon_rules.md 注入 system prompt 顶部 · 8 条铁律全部强读 ~14000 字。
  实际上每条铁律都有触发条件 · 不相关时占 LLM 注意力 + 引发铁律打架。

  方案 C (用户 钉死): system prompt 留场景索引 + 一句话纪律 ·
  完整细则按 domain 拆到 data/cognition/scenarios/<domain>.md ·
  LLM 触发时调本工具按需读。

调用时机:
  - LLM 看到 system_prompt 末尾"场景索引" section
  - 任务匹配某 domain 的触发关键词
  - 准备改 daemon 代码 / 造工坊资产 / 装 API key 等之前

档位: TIER_AUTO (纯读 + 一处文件 · 无写副作用)
"""

from __future__ import annotations

from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = ROOT / "data" / "cognition" / "scenarios"

# 跟 workers.cognition_loader._VALID_DOMAINS 同步 · 但去掉 'global' (global 是默认场景 · 不需要读)
_AVAILABLE_SCENARIOS = (
    "self_evolution",
    "app_creation",
    "workflow_creation",
    "client_ops",
    "production",
    "reflection",
    "presentation",
)


def _summarize(args: dict) -> str:
    name = (args.get("name") or "?").strip()
    return f"读 scenario · {name} · 按需取场景化铁律细则 (wish-af1245d7  II)"


def _run(args: dict) -> ToolResult:
    name = (args.get("name") or "").strip().lower()
    if not name:
        return ToolResult(
            ok=False,
            output="",
            error="name 必填 · 可选: " + " / ".join(_AVAILABLE_SCENARIOS),
        )
    if name not in _AVAILABLE_SCENARIOS:
        return ToolResult(
            ok=False,
            output="",
            error=f"未知 scenario name: {name!r} · 可选: {list(_AVAILABLE_SCENARIOS)}",
        )

    path = SCENARIOS_DIR / f"{name}.md"
    if not path.exists():
        # 列已有 · 让 LLM 知道哪些 scenario 还没建
        existing = sorted([p.stem for p in SCENARIOS_DIR.glob("*.md") if p.stem != "README"])
        return ToolResult(
            ok=False,
            output="",
            error=(
                f"scenario '{name}' 还没建 · 当前已有: {existing}\n"
                f"建议: 已落档 self_evolution / app_creation / presentation · "
                f"其他 domain 待立铁律 + 拆 scenario md (参考 scenarios/README.md)"
            ),
        )

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"读 {path.name} 失败: {e}")

    from ._hotpath_guard import mark_scenario_read
    mark_scenario_read(name)

    # 给一点导言 · 让 LLM 知道这是 scenario 不是普通文档
    output = (
        f"# [scenario: {name}] 完整细则\n\n"
        f"(从 data/cognition/scenarios/{name}.md · {len(text)} 字符)\n\n"
        f"---\n\n"
        f"{text}"
    )
    return ToolResult(ok=True, output=output)


SPEC = ToolSpec(
    name="read_scenario",
    description=(
        "按需读场景细则（system 里只有索引）。改 daemon/wish → self_evolution；造 app/workflow/密钥 → app_creation；PPT/生图 → presentation；月报复盘 → reflection。不确定就先读。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "enum": list(_AVAILABLE_SCENARIOS),
                "description": "scenario 名 · 铁律 domain（去 global）+ presentation 工艺合同",
            },
        },
        "required": ["name"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
