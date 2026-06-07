"""
tools/lint_agent_tools.py
=========================

卷四十五 · register_tool 红线

防止 OPUS 改 agent_tools/*.py 时把 register_tool(SPEC) 调用一并删了——
那种 bug 不会立即报错（daemon 照常启动），只会让那个工具从 REGISTRY 静默消失。
LLM 收到的 tool list 突然少一个，但没人知道为什么。

用法:
    python tools/lint_agent_tools.py
      退出码 0 = 全部 OK
      退出码 1 = 至少一个 agent_tool 缺 register_tool 调用

挂载点:
  1. opus_daemon.py 启动后 import 完所有 agent_tools 时 · 自动跑一次 · 不通过 ERROR 日志
  2. 任何时候 BRO 想手动确认: 直接跑这个脚本
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AT_DIR = ROOT / "agent_tools"

EXEMPT_FILES = {"__init__.py"}


def lint_agent_tools() -> tuple[list[str], int]:
    bad: list[str] = []
    total = 0
    for py in sorted(AT_DIR.glob("*.py")):
        if py.name in EXEMPT_FILES:
            continue
        total += 1
        try:
            text = py.read_text(encoding="utf-8")
        except Exception as e:
            bad.append(f"{py.name} (UTF-8 read failed: {e})")
            continue
        if "register_tool(" not in text:
            bad.append(py.name)
    return bad, total


def main() -> int:
    bad, total = lint_agent_tools()
    if bad:
        print(f"[FAIL] {len(bad)}/{total} agent_tools 缺 register_tool 调用:")
        for n in bad:
            print(f"  - {n}")
        print()
        print("可能原因: OPUS 改这个文件时把 register_tool(SPEC) 删了 · 或新工具忘了加。")
        print("修复: 在 agent_tools/<name>.py 末尾确保有 `register_tool(SPEC)` 一行。")
        return 1
    print(f"[OK] 所有 agent_tools/*.py 都注册了 register_tool ({total} 个)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
