"""
agent_tools/verify_claim.py
===========================

补丁3 · 让 OPUS 在对话里主动验证一条事实陈述。

跟 web_search 区别：
  - web_search · 你想找资料·浏览搜索结果
  - verify_claim · 你已经有一条 claim · 要的是"这条对不对"的判定

用法（NLP）:
  用户: 「我刚听说 ChatGPT 月活 1000 万了 · 真的吗？」
  OPUS: 调 verify_claim(claim="ChatGPT 月活 1000 万")
        → 返回 verdict + 找到的相关网页
        → OPUS 把判定告诉 用户

也给 UI 「佐证」按钮用 (走 POST /verify/claim · 见 daemon_api.py)。
"""

from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    claim = (args.get("claim") or "").strip()
    if len(claim) > 60:
        claim = claim[:60] + "..."
    return f"verify_claim  claim={claim!r}"


def _run(args: dict) -> ToolResult:
    claim = (args.get("claim") or "").strip()
    if not claim:
        return ToolResult(ok=False, output="", error="claim 不能为空")
    try:
        from workers.fact_check import verify_claim as _verify
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"import fact_check 失败: {e!r}")
    limit = int(args.get("limit") or 5)
    result = _verify(claim, limit=limit)
    if not result.get("ok"):
        return ToolResult(
            ok=False, output="",
            error=result.get("notes") or "verify_claim 失败",
        )

    results = result.get("results") or []
    lines = [
        f"verify_claim · {claim!r}",
        f"verdict: {result.get('verdict')} · {result.get('notes')}",
        "",
    ]
    if results:
        lines.append("找到的公开信源:")
        for i, r in enumerate(results, start=1):
            lines.append(f"  [{i}] {r.get('title', '')}")
            lines.append(f"      {r.get('url', '')}")
            snip = (r.get("snippet") or "").strip()
            if snip:
                if len(snip) > 240:
                    snip = snip[:240] + "..."
                lines.append(f"      {snip}")
    else:
        lines.append("(没找到相关公开网页 · 这条 claim 可能不属实 · 也可能太冷门没收录)")

    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="verify_claim",
    description=(
        "Verify a single factual claim by running a web search and checking "
        "if any results support it. Returns a verdict: supported|partial|unsupported|inconclusive. "
        "Use this when 用户 asks 'is X true?' or when YOU need to check before stating a fact. "
        "Cheaper / more focused than web_search when the goal is fact-checking one specific statement."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "claim": {
                "type": "string",
                "description": "The factual claim to verify (Chinese or English).",
            },
            "limit": {
                "type": "integer",
                "description": "Max search results to check (1-10, default 5)",
            },
        },
        "required": ["claim"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
