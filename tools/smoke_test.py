"""
smoke_test.py
=============

向一个 OpenAI 兼容端点发一条最小的真实请求，验证 round-trip 通顺 + 拿到 usage / cost。

用法：
  python tools/smoke_test.py --key sk-xxx --base-url https://openrouter.ai/api/v1
  python tools/smoke_test.py --key sk-xxx --base-url ... --model anthropic/claude-opus-4.5

这是 probe_provider.py 的下一步：probe 验证 key 在 /models 端点过，
smoke_test 验证 key 真的能调出对话 + 看真实计费。
"""

from __future__ import annotations

import argparse
import sys

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: openai not installed. Run: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)


def mask(k: str) -> str:
    if len(k) < 12:
        return "***"
    return f"{k[:6]}...{k[-4:]}"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--key", required=True)
    p.add_argument("--base-url", required=True)
    p.add_argument("--model", default="anthropic/claude-sonnet-4.5")
    p.add_argument("--prompt", default="Reply with only one word in caps: PONG.")
    p.add_argument("--max-tokens", type=int, default=20)
    args = p.parse_args()

    print()
    print(f"  key       : {mask(args.key)}")
    print(f"  base_url  : {args.base_url}")
    print(f"  model     : {args.model}")
    print(f"  prompt    : {args.prompt!r}")
    print()

    client = OpenAI(api_key=args.key, base_url=args.base_url)

    try:
        resp = client.chat.completions.create(
            model=args.model,
            max_tokens=args.max_tokens,
            messages=[{"role": "user", "content": args.prompt}],
        )
    except Exception as e:
        print(f"  [FAIL]  {type(e).__name__}: {e}")
        return 1

    reply = resp.choices[0].message.content
    print(f"  [OK]   reply: {reply!r}")
    print()

    u = resp.usage
    print(f"  usage:")
    print(f"    prompt_tokens     : {getattr(u, 'prompt_tokens', '?')}")
    print(f"    completion_tokens : {getattr(u, 'completion_tokens', '?')}")
    print(f"    total_tokens      : {getattr(u, 'total_tokens', '?')}")

    # OpenRouter / 一些供应商会在 usage 里附加 cost
    try:
        u_dict = u.model_dump()
    except Exception:
        u_dict = dict(getattr(u, "__dict__", {}))
    extras = {k: v for k, v in u_dict.items() if k not in ("prompt_tokens", "completion_tokens", "total_tokens")}
    if extras:
        print(f"  extras:")
        for k, v in extras.items():
            print(f"    {k:<18}: {v}")

    # finish reason
    fr = resp.choices[0].finish_reason
    print()
    print(f"  finish_reason: {fr}")
    print(f"  model returned: {resp.model}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
