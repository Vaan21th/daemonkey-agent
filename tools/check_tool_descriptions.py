"""工具简介机器闸 · REGISTRY description 超 180 tok 则 exit 1。

用法:  python tools/check_tool_descriptions.py
verify_daemon_endpoints fast 也会跑同一闸。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_tools import REGISTRY  # noqa: E402
from agent_tools._desc_budget import (  # noqa: E402
    MAX_DESC_TOKENS,
    audit_registry,
    count_desc_tokens,
)


def main() -> int:
    over = audit_registry(REGISTRY)
    rows = sorted(
        ((s.name, count_desc_tokens(s.description or "")) for s in REGISTRY.values()),
        key=lambda x: -x[1],
    )
    print(f"tools={len(REGISTRY)} cap={MAX_DESC_TOKENS} over={len(over)}")
    for name, n in rows[:10]:
        flag = " *" if n > MAX_DESC_TOKENS else ""
        print(f"  {n:4d}  {name}{flag}")
    if over:
        print("FAIL · 超线:")
        for o in over:
            print(f"  {o['name']} {o['tok']} (+{o['over']})")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
