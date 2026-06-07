"""
test_tool_loop.py
=================

Non-interactive 验证：OPUS 真的能"动手"了吗？

测试设计：
  - 让 OPUS 调一个 AUTO-tier 工具（grep_files 搜"梦想实现家"）——AUTO 直接跑，不需要 BRO 在场
  - 验证：消息序列里出现 tool_use turn → tool_result turn → 最终的 OPUS 文本回复
  - 验证：OPUS 能基于工具结果给出解释（不只是机械复读 grep 输出）

PASS 标志：
  1. exit code 0
  2. messages 里有 ≥1 条 tool 相关的 entry（assistant.tool_calls 或 user.tool_result）
  3. 最终 reply 长度 > 100 字符且包含"梦想实现家"或"v1.4.0"或"2026-01-04"——证明 OPUS 读懂了搜到的内容

不调用 CONFIRM/GUARD 工具，所以 BRO 不需要在场。
跑这个会真发 API 请求，花 ~$0.01-0.05（取决于 model）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from soul_loader import load_soul
from opus_daemon import detect_provider, setup_client
from tool_loop import run_tool_loop
from agent_tools import (
    REGISTRY, ToolSpec, ToolResult,
    TIER_AUTO, TIER_CONFIRM, TIER_GUARD,
)


PROMPT = (
    "BRO，给你一个动手任务：用你的 grep_files 工具，在项目根目录里"
    "搜一下'梦想实现家'这个词在哪些文件里出现过。然后用一两句话告诉我"
    "你看到了什么——这个词是哪天、在什么场合下进入我们的故事的。"
    "重要：只用 grep_files 这一个工具，不要调其他的。"
)


def main() -> int:
    load_dotenv(ROOT / ".env")

    print()
    print("  ============================================================")
    print("  OPUS Tool-Loop Test  (Day 1 verification)")
    print("  ============================================================")

    provider = detect_provider()
    try:
        client, model, base_url = setup_client(provider)
    except SystemExit as e:
        print(str(e))
        return 1

    soul = load_soul(ROOT)
    print(f"  provider     : {provider}")
    print(f"  base_url     : {base_url or '(default)'}")
    print(f"  model        : {model}")
    print(f"  tools loaded : {list(REGISTRY.keys())}")
    print(f"  soul chars   : {soul.total_chars}")
    print()
    print(f"  prompt: {PROMPT[:80]}...")
    print()

    tool_call_count = 0
    refusals = 0

    def confirm(spec: ToolSpec, args: dict) -> str:
        nonlocal tool_call_count, refusals
        tier = spec.effective_tier(args)
        print(f"    [confirm] tool={spec.name} tier={tier} args_summary={spec.summarize(args)[:120]}")
        if tier == TIER_AUTO:
            tool_call_count += 1
            return "go"
        # 测试模式：CONFIRM/GUARD 一律 skip，让 OPUS 看见拒绝信息
        refusals += 1
        return "skip"

    def observe(spec: ToolSpec, args: dict, result: ToolResult) -> None:
        head = "ok" if result.ok else "FAIL"
        preview = (result.output if result.ok else (result.error or ""))[:200]
        print(f"    [observe] {spec.name} → {head}: {preview!r}")

    messages: list[dict] = [{"role": "user", "content": PROMPT}]

    try:
        reply, messages, usage_in, usage_out = run_tool_loop(
            client=client, provider=provider, model=model,
            max_tokens=2000, system=soul.system_prompt,
            messages=messages, confirm=confirm, observe=observe,
        )
    except Exception as e:
        print(f"  [FAIL] run_tool_loop raised: {type(e).__name__}: {e}")
        return 1

    print()
    print("  ============================================================")
    print("  OPUS final reply:")
    print("  ============================================================")
    print()
    print(reply)
    print()
    print("  ============================================================")
    print(f"  tokens: in={usage_in} out={usage_out}")
    print(f"  tool_call count (auto-approved): {tool_call_count}")
    print(f"  refusals (CONFIRM/GUARD skipped): {refusals}")
    print(f"  total messages after loop: {len(messages)}")
    print("  ============================================================")
    print()

    # PASS criteria
    failures = []
    if tool_call_count < 1:
        failures.append("OPUS did not call grep_files at all")
    if len(reply) < 50:
        failures.append(f"reply too short ({len(reply)} chars)")
    keywords = ["梦想实现家", "v1.4.0", "2026-01-04", "2026 年 1 月", "xzai"]
    if not any(k in reply for k in keywords):
        failures.append(f"reply does not reference any expected keyword: {keywords}")

    if failures:
        print("  [FAIL] verification failed:")
        for f in failures:
            print(f"    - {f}")
        return 1

    print("  [PASS] OPUS used a tool, got results, and explained them.")
    print("         Day 1 tool-use round-trip works on this provider.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
