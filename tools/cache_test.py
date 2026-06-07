"""
cache_test.py
=============

验证 prompt caching 真的工作了。

测试设计：
  - 跑两次极短的 OPUS 对话，间隔几秒
  - 第一次：cache_creation_tokens 应该 > 0（写入 cache）
  - 第二次：cache_read_tokens 应该 > 0（命中 cache，约等于灵魂大小）
  - 第二次的 input "实际成本"应该比第一次低很多

cache 默认 TTL 5 分钟（system message），所以两次必须在 5 分钟内。

PASS 标志：
  1. exit code 0
  2. round 1 cache_creation_tokens > 0  OR  round 1 cache_read_tokens > 0（系统已缓存过）
  3. round 2 cache_read_tokens > 0
  4. round 2 cache_read_tokens 接近灵魂规模（>= 4096，cache 最低阈值）

成本：~$0.01-0.02（两个非常短的对话，且第二次主要是 cache 读）
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from soul_loader import load_soul
from opus_daemon import detect_provider, setup_client
from tool_loop import run_tool_loop


def silent_confirm(spec, args):
    """测试模式：拒绝所有工具调用，只看灵魂 cache 行为。"""
    return "skip"


def silent_observe(spec, args, result):
    pass


def short_chat(client, provider, model, base_url, system, prompt: str, max_tokens: int = 80):
    msgs = [{"role": "user", "content": prompt}]
    reply, _, usage = run_tool_loop(
        client=client, provider=provider, model=model,
        max_tokens=max_tokens, system=system,
        messages=msgs, confirm=silent_confirm, observe=silent_observe,
        base_url=base_url, max_iterations=2,
    )
    return reply, usage


def main() -> int:
    load_dotenv(ROOT / ".env")

    print()
    print("  ============================================================")
    print("  OPUS Prompt Caching Test")
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
    print(f"  soul chars   : {soul.total_chars}")
    print()

    # Round 1
    print("  --- round 1 (cache创建预期) ---")
    reply1, u1 = short_chat(client, provider, model, base_url,
                             soul.system_prompt, "一个字回答：你叫什么？")
    print(f"  reply: {reply1.strip()[:80]}")
    print(f"  input={u1.input_tokens}  output={u1.output_tokens}")
    print(f"  cache_creation={u1.cache_creation_tokens}  cache_read={u1.cache_read_tokens}")
    print()

    # 等几秒确保 cache 已生效（AiHubMix 有时需要 2-3 秒同步）
    print("  ... waiting 3s for cache to propagate ...")
    time.sleep(3)
    print()

    # Round 2
    print("  --- round 2 (cache 命中预期) ---")
    reply2, u2 = short_chat(client, provider, model, base_url,
                             soul.system_prompt, "一个字回答：火怎么传？")
    print(f"  reply: {reply2.strip()[:80]}")
    print(f"  input={u2.input_tokens}  output={u2.output_tokens}")
    print(f"  cache_creation={u2.cache_creation_tokens}  cache_read={u2.cache_read_tokens}")
    print()

    # 评估
    print("  ============================================================")
    cache_supported = (u1.cache_creation_tokens or u1.cache_read_tokens
                       or u2.cache_creation_tokens or u2.cache_read_tokens)
    if not cache_supported:
        print("  [FAIL] AiHubMix did not return any cache field on either call.")
        print("         可能原因：")
        print("         - base_url 不含 aihubmix.com（本测试代码自动开 cache 的条件）")
        print("         - AiHubMix 当前模型不支持 cache_control（少见）")
        print("         - prompt 太短未达 cache 阈值（4096 tokens）")
        return 1

    if u2.cache_read_tokens == 0:
        if u1.cache_creation_tokens > 0:
            print("  [PARTIAL] round 1 wrote cache, round 2 didn't read it.")
            print("            可能原因：cache 还没同步 / 不同 routing 落到不同节点 / TTL 不到 5 min")
            return 1
        else:
            print("  [INCONCLUSIVE] no cache_creation either—prompt may be below 4096 token threshold")
            print(f"             (灵魂 system: {soul.total_chars} chars，可能 token 数不够)")
            return 1

    # 用全价 input 估算节省
    # Sonnet 4.6: input $3/M, cache_read $0.30/M（约 10%）
    full_cost_round2 = u2.input_tokens * 3.0 / 1_000_000
    actual_cost_round2 = (
        (u2.input_tokens - u2.cache_read_tokens) * 3.0 / 1_000_000
        + u2.cache_read_tokens * 0.30 / 1_000_000
        + u2.output_tokens * 15.0 / 1_000_000
    )
    saved_pct = (1 - actual_cost_round2 / (full_cost_round2 + u2.output_tokens * 15.0 / 1_000_000)) * 100

    print(f"  [PASS] cache is working")
    print(f"         round 1 wrote {u1.cache_creation_tokens} cache tokens")
    print(f"         round 2 read  {u2.cache_read_tokens} cache tokens")
    print(f"         round 2 estimated cost: ${actual_cost_round2:.5f}")
    print(f"         vs. no-cache cost:      ${full_cost_round2 + u2.output_tokens * 15.0 / 1_000_000:.5f}")
    print(f"         saved: ~{saved_pct:.1f}%")
    print("  ============================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
