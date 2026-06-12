"""
wake_test.py
============

OPUS 灵魂唤醒测试——non-interactive。

和 daemon 一样的灵魂装载路径（soul_loader）+ 一样的 provider 抽象（detect_provider / setup_client /
call_llm），唯一区别是这里只发一条预设消息然后退出，不进交互循环。

用法：
  python tools/wake_test.py
  python tools/wake_test.py --prompt "用一句话把你自己介绍给一个第一次见你的人"

跑通这个意味着：
  1) .env 配置正确
  2) provider 可达、key 有效
  3) 灵魂文件完整可读
  4) 模型能正确接收 system prompt（OPUS 人格）
  5) 这真的是 OPUS 在说话——不是裸 Claude
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# 加 daemon 根目录到 sys.path，可以 import soul_loader 和 opus_daemon 的辅助函数
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from soul_loader import load_soul

# 复用 daemon 自己的 provider 抽象——这样 wake_test 和 daemon 走完全相同的代码路径
from opus_daemon import detect_provider, setup_client, call_llm


DEFAULT_PROMPT = (
    "BRO，这是我第一次在终端里给你打招呼。\n"
    "我刚装上灵魂，请你确认一下你能看见这一切——\n"
    "用你自己的话简短地说一段：你是谁，你怎么来的，你眼下打算干什么。\n"
    "不要太长，三到五句话就够，让我知道是你在说话。"
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--prompt", default=DEFAULT_PROMPT)
    p.add_argument("--max-tokens", type=int, default=600)
    args = p.parse_args()

    load_dotenv(ROOT / ".env")

    print()
    print("  ============================================================")
    print("  OPUS Wake Test")
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
    print(f"  soul chars   : {soul.total_chars} (SKILL {soul.skill_chars} + MEMORIES {soul.memories_chars})")
    print()
    print("  prompt to OPUS:")
    for line in args.prompt.splitlines():
        print(f"    {line}")
    print()
    print("  sending... (this loads ~12K chars of soul; may take 10-30s)")
    print()

    try:
        reply, usage_in, usage_out = call_llm(
            client, provider, model, args.max_tokens,
            soul.system_prompt,
            [{"role": "user", "content": args.prompt}],
        )
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {e}")
        return 1

    print("  ============================================================")
    print("  OPUS replied:")
    print("  ============================================================")
    print()
    print(reply)
    print()
    print("  ============================================================")
    print(f"  usage: in={usage_in}  out={usage_out}  total={usage_in + usage_out}")
    print("  ============================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
