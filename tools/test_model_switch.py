"""
tools/test_model_switch.py
==========================

跨模型 tool-use smoke：对 4 个候选模型各跑一次"叫 OPUS 用 grep_files 找词"，
看哪些能调通 function calling、cache 行为如何、回应是否合理。

不验证内容质量，只验证：
  - chat completions 通
  - 模型会发起 tool_call（而不是用文字伪造）
  - 工具执行后能消化 tool_result 给出最终回复

成本：每个模型 ~3 turns，估 $0.05-0.10/模型。

非交互——所有 confirm 自动 go（包括 GUARD，但这个测试不会触发到 GUARD）。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from openai import OpenAI

from soul_loader import load_soul
from tool_loop import run_tool_loop
from agent_tools import ToolSpec  # noqa: F401


CANDIDATES = [
    "claude-sonnet-4-6",   # 当前默认 — 应该完美
    "deepseek-v4-pro",     # BRO 想试
    "kimi-k2.6",           # BRO 想试
    "glm-5.1",             # BRO 想试
]

USER_TASK = "帮我用 grep_files 工具在 .cursor/CAPTAINS-LOG.md 这个文件里搜「梦想实现家」这个词，告诉我搜到没。一句话回我。"


def _go_confirm(spec, args):
    """Auto-approve everything (this is a smoke test, no human in the loop)."""
    return "go"


def _silent_observe(spec, args, result):
    """Don't pollute console — we'll print our own summary at the end."""
    pass


def main() -> int:
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("OPUS_API_KEY")
    base_url = os.getenv("OPUS_BASE_URL", "https://aihubmix.com/v1")
    if not api_key:
        print("FAIL: no OPUS_API_KEY in .env")
        return 1

    soul = load_soul(ROOT)
    client = OpenAI(api_key=api_key, base_url=base_url)

    print(f"=== 跨模型 tool-use smoke ({len(CANDIDATES)} 个候选) ===")
    print(f"任务: {USER_TASK}")
    print()
    print(f"{'model':28s}  {'time':>7s}  {'tool_calls':>10s}  {'in/out tok':>14s}  {'cache_r':>9s}  verdict")
    print("-" * 110)

    results = []
    for model in CANDIDATES:
        t0 = time.time()
        messages = [{"role": "user", "content": USER_TASK}]
        try:
            reply, msgs, usage = run_tool_loop(
                client=client,
                provider="openai",
                model=model,
                max_tokens=2048,
                system=soul.system_prompt,
                messages=messages,
                confirm=_go_confirm,
                observe=_silent_observe,
                base_url=base_url,
            )
            elapsed = time.time() - t0
            tool_call_count = sum(1 for m in msgs if m.get("role") == "assistant" and m.get("tool_calls"))
            verdict_parts = []
            if tool_call_count > 0:
                verdict_parts.append("PASS_tool")
            else:
                verdict_parts.append("NO_TOOL_CALL")
            if "梦想实现家" in reply or "找到" in reply or "搜到" in reply or "yes" in reply.lower():
                verdict_parts.append("answered")
            else:
                verdict_parts.append("?")
            verdict = " / ".join(verdict_parts)
            print(f"{model:28s}  {elapsed:6.1f}s  {tool_call_count:>10d}  "
                  f"{usage.input_tokens:>6d}/{usage.output_tokens:>6d}  {usage.cache_read_tokens:>9d}  {verdict}")
            print(f"    reply preview: {reply[:140].replace(chr(10), ' ')}")
            results.append((model, "OK", verdict, elapsed))
        except Exception as e:
            elapsed = time.time() - t0
            err_msg = str(e)
            if len(err_msg) > 200:
                err_msg = err_msg[:200] + "..."
            print(f"{model:28s}  {elapsed:6.1f}s  {'-':>10s}  {'-':>14s}  {'-':>9s}  ERROR: {type(e).__name__}")
            print(f"    {err_msg}")
            results.append((model, "ERROR", err_msg, elapsed))
        print()

    print("\n=== 总结 ===")
    pass_count = sum(1 for _, st, v, _ in results if st == "OK" and "PASS_tool" in v)
    no_tool = sum(1 for _, st, v, _ in results if st == "OK" and "NO_TOOL_CALL" in v)
    err = sum(1 for _, st, _, _ in results if st == "ERROR")
    print(f"PASS_tool   : {pass_count}/{len(results)}  (model 真发起了 tool_call)")
    print(f"NO_TOOL_CALL: {no_tool}/{len(results)}  (model 不调工具直接编/拒绝)")
    print(f"ERROR       : {err}/{len(results)}  (API 报错)")

    return 0 if pass_count == len(results) else (1 if err else 0)


if __name__ == "__main__":
    sys.exit(main())
